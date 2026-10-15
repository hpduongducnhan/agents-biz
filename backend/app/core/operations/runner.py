"""Chạy một operation — chung cho REST, agent, việc nền: cùng kiểm quyền, session đúng kênh, gửi sau commit,
event log."""

from __future__ import annotations

import functools
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ValidationError

from app.core.cid import get_cid, set_cid
from app.core.connections.registry import get_connections
from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.messaging import realtime
from app.core.operations.context import OpContext, PendingNotification
from app.core.operations.registry import all_specs, get_spec
from app.core.operations.spec import OperationSpec, Source
from app.core.redact import build_keys, redact_mapping
from app.core.security.principal import Principal
from app.core.settings import Settings, active_settings
from app.core.tenancy import scope_session
from app.observability.sinks import EventLogEntry, get_sinks

logger = get_logger(__name__)
Notifier = Callable[[list[PendingNotification]], Awaitable[None]]
_hooks: dict[str, Any] = {"notifier": None, "warned": False}


def set_notifier(fn: Notifier | None) -> None:
    """Miền notifications cài: lưu inbox + đẩy `core:notification` cho các thông báo handler đã xếp hàng."""
    _hooks["notifier"] = fn


def check_operations() -> None:
    """Gọi lúc boot sau load_domains: cấu hình thiếu phải dừng process ngay, không đợi request đầu tiên."""
    for spec in all_specs():
        if spec.agent and not spec.toolset:
            raise RuntimeError(f"operation {spec.name} khai agent=True nhưng thiếu toolset")


def is_allowed(spec: OperationSpec, principal: Principal | None) -> bool:
    """Một chỗ quyết định — runner và danh mục action dùng chung."""
    if spec.public:
        return True
    if principal is None:
        return False
    return (principal.sup or not spec.superadmin) and principal.can(spec.permission)


def _authorize(spec: OperationSpec, principal: Principal | None) -> None:
    if spec.public:
        return
    if principal is None:
        raise AppException(1004, status_code=401)
    if is_allowed(spec, principal):
        return
    sup_only = spec.superadmin and not principal.sup
    logger.warning(
        "từ chối %s: thiếu %s user=%s",
        spec.name,
        "superadmin" if sup_only else spec.permission,
        principal.user_id,
        extra={"loc": "sys0401"},
    )
    raise AppException(1005, status_code=403, detail="Chỉ superadmin" if sup_only else None)


def _scoped(spec: OperationSpec, principal: Principal | None) -> bool:
    """Lọc tenant (D11) trừ: op công khai / chưa có tenant; op `superadmin=True` (quản trị nền tảng); op khai
    `sup_all_tenants` khi superadmin gọi (vd quản trị user — admin tenant vẫn chỉ thấy tenant mình)."""
    if principal is None or principal.tenant_id is None or spec.superadmin:
        return False
    return not (spec.sup_all_tenants and principal.sup)


def _validate(spec: OperationSpec, raw: Any) -> BaseModel | None:
    if spec.input_model is None:
        return None
    if isinstance(raw, spec.input_model):
        return raw
    try:
        return spec.input_model.model_validate(raw if raw is not None else {})
    except ValidationError as exc:
        errors = exc.errors(include_url=False, include_context=False)
        raise AppException(1002, status_code=422, data=errors) from exc


def _log_input(settings: Settings, payload: BaseModel | None, raw: Any) -> dict | None:
    """Input cho event log — che trường bí mật (cùng danh sách với log: mặc định + LOG_REDACT_KEYS)."""
    if payload is not None:
        data = payload.model_dump(mode="json")
    elif raw is None:
        return None
    else:
        data = jsonable_encoder(raw)
    if not isinstance(data, dict):
        data = {"value": data}
    return redact_mapping(data, build_keys(settings.extra_redact_keys))


async def _write_event_log(
    spec: OperationSpec,
    principal: Principal | None,
    *,
    source: Source,
    agent_run_id: uuid.UUID | None,
    data: dict | None,
    ok: bool,
    error_code: int | None,
    started: float,
) -> None:
    entry = EventLogEntry(
        ts=datetime.now(UTC),
        cid=get_cid(),
        actor_id=principal.user_id if principal is not None else None,
        actor_sup=bool(principal is not None and principal.sup),
        source=source,
        agent_run_id=agent_run_id,
        operation=spec.name,
        effect=spec.effect,
        input=data,
        ok=ok,
        error_code=error_code,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    try:
        await get_sinks().event_log.write(entry)
    except Exception as exc:  # noqa: BLE001 — thao tác đã xong; ghi event log hỏng chỉ được báo
        logger.warning("ghi event log %s lỗi: %s", spec.name, exc, extra={"loc": "sys0405"})


async def _execute(
    spec: OperationSpec,
    settings: Settings,
    principal: Principal | None,
    payload: BaseModel | None,
    *,
    source: Source,
    agent_run_id: uuid.UUID | None,
    request_ip: str | None,
) -> tuple[OpContext, Any]:
    conns = get_connections()
    writes = spec.effect != "read"
    session_cm = conns.postgres.rw(read_only=not writes) if writes or spec.read_from == "rw" else conns.postgres.ro()
    async with session_cm as session:  # Postgres.rw commit khi ra khỏi khối, lỗi thì rollback
        ctx = OpContext(
            principal=principal,
            settings=settings,
            session=session,
            redis=conns.redis,
            mongo=conns.mongo,
            cid=get_cid() or set_cid(None),
            source=source,
            agent_run_id=agent_run_id,
            request_ip=request_ip,
        )
        if _scoped(spec, principal):
            scope_session(session, principal.tenant_id)  # D11: mọi câu ORM trên bảng TenantScoped lọc theo tenant
        result = await (spec.func(ctx, payload) if spec.takes_input else spec.func(ctx))
    return ctx, result


def _sends(ctx: OpContext, spec: OperationSpec) -> list[tuple[str, Callable[[], Awaitable[None]]]]:
    sends: list[tuple[str, Callable[[], Awaitable[None]]]] = []
    for e in ctx.pending_emits:
        if e.target == "sup":
            sends.append((e.event, functools.partial(realtime.emit_to_superadmins, e.event, e.data)))
        elif e.target == "tenant":
            sends.append((e.event, functools.partial(realtime.emit_to_tenant, e.tenant_id, e.event, e.data)))
        else:
            sends.append((e.event, functools.partial(realtime.emit_to_users, e.user_ids, e.event, e.data)))
    if spec.effect != "read" and spec.invalidates and ctx.principal is not None:
        changed = {"keys": list(spec.invalidates)}
        emit = functools.partial(realtime.emit_to_user, ctx.principal.user_id, "data:changed", changed)
        sends.append(("data:changed", emit))
    for keys, users in ctx.pending_invalidations:
        emit = functools.partial(realtime.emit_to_users, users, "data:changed", {"keys": list(keys)})
        sends.append(("data:changed", emit))
    for keys, tenant_id in ctx.pending_tenant_invalidations:
        emit = functools.partial(realtime.emit_to_tenant, tenant_id, "data:changed", {"keys": list(keys)})
        sends.append(("data:changed", emit))
    return sends


async def _notify(spec: OperationSpec, items: list[PendingNotification]) -> None:
    if not items:
        return
    notifier = _hooks["notifier"]
    if notifier is None:
        if not _hooks["warned"]:
            _hooks["warned"] = True
            logger.warning(
                "chưa cài notifier — bỏ %d thông báo của %s; DEFAULTS_APPLIED=[notifier=noop]",
                len(items),
                spec.name,
                extra={"loc": "sys0403"},
            )
        else:
            logger.debug("bỏ %d thông báo của %s (chưa cài notifier)", len(items), spec.name)
        return
    try:
        await notifier(list(items))
    except Exception as exc:  # noqa: BLE001 — thông báo best-effort sau commit
        logger.warning("gửi thông báo %s lỗi: %s", spec.name, exc, extra={"loc": "sys0404"})


async def _after_commit(ctx: OpContext, spec: OperationSpec) -> None:
    """Sau commit: hook → emit đã xếp → data:changed → thông báo. Lỗi ở đây chỉ được log — thao tác đã bền, ném ra
    sẽ khiến người dùng bấm lại và ghi trùng."""
    for hook in ctx.pending_hooks:
        try:
            await hook()
        except Exception as exc:  # noqa: BLE001 — thao tác đã commit; hook hỏng chỉ được báo
            name = getattr(hook, "__qualname__", hook)
            logger.warning("after_commit %s lỗi (%s): %s", name, spec.name, exc, extra={"loc": "sys0402"})
    for event, send in _sends(ctx, spec):
        try:
            await send()
        except Exception as exc:  # noqa: BLE001 — realtime best-effort: không làm hỏng thao tác đã commit
            logger.warning("gửi realtime %s lỗi (%s): %s", event, spec.name, exc, extra={"loc": "ws0501"})
    await _notify(spec, ctx.pending_notifications)


async def run_operation(
    name: str,
    principal: Principal | None,
    raw_input: dict | None,
    *,
    source: Source = "web",
    agent_run_id: uuid.UUID | None = None,
    request_ip: str | None = None,
) -> Any:
    spec = get_spec(name)
    if spec is None:
        raise AppException(1001, status_code=404, detail=f"Không có operation '{name}'")
    settings = active_settings()
    started = time.perf_counter()
    payload: BaseModel | None = None
    try:
        _authorize(spec, principal)
        payload = _validate(spec, raw_input)
        ctx, result = await _execute(
            spec,
            settings,
            principal,
            payload,
            source=source,
            agent_run_id=agent_run_id,
            request_ip=request_ip,
        )
    except Exception as exc:
        if spec.effect != "read":
            await _write_event_log(
                spec,
                principal,
                source=source,
                agent_run_id=agent_run_id,
                data=_log_input(settings, payload, raw_input),
                ok=False,
                error_code=exc.code if isinstance(exc, AppException) else 1000,
                started=started,
            )
        raise
    await _after_commit(ctx, spec)
    if spec.effect != "read":
        await _write_event_log(
            spec,
            principal,
            source=source,
            agent_run_id=agent_run_id,
            data=_log_input(settings, payload, raw_input),
            ok=True,
            error_code=None,
            started=started,
        )
    return result
