"""Chọn + xoay API key của agent: key khoẻ = gắn agent + bật + credential `active` + không đang nguội
(`bw:key:cool:<id>`). `round_robin` = `INCR bw:rr:<agent>` theo vòng; `auto` = ít request nhất (giờ này + giờ trước,
chia `weight`), hoà → ngẫu nhiên. Lỗi provider: `rate` → nguội + đổi key; `auth` → tắt credential + issue + báo
superadmin + đổi key; `server` (5xx, mạng, lỗi báo giữa luồng) → thử lại một lần cùng key rồi đổi."""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import update
from sqlmodel import select

from app.agent.config.registry import AgentSpec
from app.agent.notify import KEY_DISABLED, KeyDisabledParams
from app.core.connections.registry import get_connections
from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.rkeys import rkey
from app.core.settings import Settings
from app.credentials.models import Credential
from app.credentials.service import reveal
from app.notifications.service import notify_superadmins
from app.observability.sinks import capture_issue

logger = get_logger(__name__)
REQ_TTL = 2 * 3600


@dataclass(frozen=True)
class PickedKey:
    id: uuid.UUID
    name: str
    secret: str
    masked_hint: str = ""


def cool_key(cred_id: uuid.UUID) -> str:
    return rkey("key", "cool", str(cred_id))


def _req_key(cred_id: uuid.UUID, at: datetime) -> str:
    return rkey("key", "req", str(cred_id), at.strftime("%Y%m%d%H"))


async def healthy(session, redis, spec: AgentSpec, exclude=()) -> list[Credential]:
    ids = [k for k in spec.key_ids if k not in set(exclude)]
    if not ids:
        return []
    stmt = select(Credential).where(Credential.id.in_(ids), Credential.status == "active")
    creds = sorted((await session.exec(stmt)).all(), key=lambda c: str(c.id))
    if not creds:
        return []
    cooled = await redis.rw.mget([cool_key(c.id) for c in creds])
    return [c for c, hot in zip(creds, cooled, strict=True) if not hot]


async def _least_used(redis, creds: list[Credential]) -> Credential:
    now = datetime.now(UTC)
    keys = [k for c in creds for k in (_req_key(c.id, now), _req_key(c.id, now - timedelta(hours=1)))]
    counts = [int(x or 0) for x in await redis.rw.mget(keys)]
    scores = [(counts[2 * i] + counts[2 * i + 1]) / max(1, c.weight) for i, c in enumerate(creds)]
    best = min(scores)
    return random.choice([c for c, s in zip(creds, scores, strict=True) if s == best])  # noqa: S311 — chia tải


async def pick(session, redis, settings: Settings, spec: AgentSpec, *, exclude=()) -> PickedKey:
    creds = await healthy(session, redis, spec, exclude)
    if not creds:
        raise AppException(6010, status_code=503)
    if spec.agent.key_strategy == "auto" and len(creds) > 1:
        cred = await _least_used(redis, creds)
    else:
        n = int(await redis.rw.incr(rkey("rr", str(spec.id))))
        cred = creds[(n - 1) % len(creds)]
    secret = await reveal(session, cred.id, settings, purpose=f"agent:{spec.agent.slug}")
    req = _req_key(cred.id, datetime.now(UTC))
    await redis.rw.incr(req)
    await redis.rw.expire(req, REQ_TTL)
    return PickedKey(cred.id, cred.name, secret, cred.masked_hint)


def _status(exc: BaseException) -> int | None:
    for attr in ("status_code", "code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int) and 100 <= value < 600:
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def classify(exc: BaseException) -> str:
    """`rate` | `auth` | `server` | `other` — xét cả chuỗi nguyên nhân (LangChain bọc lỗi SDK của provider)."""
    seen: BaseException | None = exc
    while seen is not None:
        status = _status(seen)
        if status == 429:
            return "rate"
        if status in (401, 403):
            return "auth"
        if (status is not None and status >= 500) or isinstance(seen, httpx.TransportError | TimeoutError):
            return "server"
        if type(seen).__name__ in (
            "APIConnectionError",
            "APITimeoutError",
            "ServiceUnavailable",
            "InternalServerError",
        ):
            return "server"
        if _in_stream(seen, status):
            return "server"
        seen = seen.__cause__ or seen.__context__
    return "other"


def _in_stream(exc: BaseException, status: int | None) -> bool:
    """Lỗi provider báo giữa luồng SSE sau HTTP 200 (vd "servers are currently overloaded") — SDK ném `APIError`
    không mã (OpenAI) hoặc `APIStatusError` mã 2xx (Anthropic): coi là lỗi tạm thời phía server."""
    return (
        type(exc).__module__.split(".")[0] in ("openai", "anthropic")
        and type(exc).__name__ in ("APIError", "APIStatusError")
        and (status is None or status < 300)
    )


async def cool(redis, cred_id: uuid.UUID, seconds: int) -> None:
    await redis.rw.set(cool_key(cred_id), "1", ex=max(1, seconds))
    logger.warning("key %s bị giới hạn tốc độ — nguội %ss", cred_id, seconds, extra={"loc": "agt0601"})


async def disable(cred_id: uuid.UUID, name: str, exc: BaseException) -> None:
    reason = f"provider từ chối key ({type(exc).__name__}: {str(exc)[:300]})"
    async with get_connections().postgres.rw() as session:
        await session.exec(
            update(Credential)
            .where(Credential.id == cred_id, Credential.status == "active")
            .values(status="disabled", disabled_reason=reason)
        )
    logger.warning("tắt key %s (%s): %s", cred_id, name, reason, extra={"loc": "agt0602"})
    await capture_issue(exc, source="agent", loc="agt0602", context={"credential_id": str(cred_id)})
    try:
        params = KeyDisabledParams(name=name, reason=reason).model_dump()
        await notify_superadmins(
            KEY_DISABLED,
            f"Key '{name}' đã bị tắt",
            reason,
            params=params,
            action={"kind": "link", "to": "/studio?tab=credentials"},
        )
    except Exception as err:  # noqa: BLE001 — báo superadmin hỏng không được làm hỏng lượt chạy (đã có issue)
        logger.warning("báo key bị tắt lỗi: %s", err, extra={"loc": "agt0603"})
