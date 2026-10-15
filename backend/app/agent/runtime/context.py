"""Khối `<context>…</context>` gắn vào tin nhắn cuối mỗi lượt: người dùng, giờ hiện tại, quyền trợ lý,
rồi các dòng do module đăng ký (`register_context`). System prompt + danh sách tool đứng yên để được cache. Server vẫn
kiểm quyền mỗi lần gọi tool."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.agent.config.toolsets import perm_of, toolsets
from app.auth.models import User
from app.auth.rbac import role_names, user_permissions
from app.core.dates import zone
from app.core.logging import get_logger
from app.core.tenancy import scope_session, session_tenant
from app.tenants.models import Tenant

logger = get_logger(__name__)

ContextFn = Callable[[object, User], Awaitable[list[str]]]


@dataclass(frozen=True)
class ContextProvider:
    name: str
    fn: ContextFn
    order: int
    budget: int  # số dòng tối đa provider được góp
    router: bool  # góp cả vào ngữ cảnh rút gọn của router (chỉ tên / nhãn — không số liệu)


_PROVIDERS: dict[str, ContextProvider] = {}


def register_context(name: str, fn: ContextFn, *, order: int = 100, budget: int = 30, router: bool = False) -> None:
    """Module góp dòng vào khối ngữ cảnh: `fn(session, user) -> list[str]`; vượt `budget` thì cắt + gợi ý dùng tool.
    `router=True`: dòng cũng vào ngữ cảnh rút gọn của router (giúp chọn chuyên gia) — chỉ nên là tên / nhãn ngắn."""
    if name in _PROVIDERS and _PROVIDERS[name].fn is not fn:
        raise ValueError(f"context provider '{name}' đã đăng ký")
    _PROVIDERS[name] = ContextProvider(name, fn, order, budget, router)


def providers() -> list[ContextProvider]:
    return sorted(_PROVIDERS.values(), key=lambda p: (p.order, p.name))


async def _access_line(session, user: User) -> list[str]:
    """Việc user chưa được dùng trợ lý (thiếu `agent.<toolset>`): để trợ lý nói rõ thay vì đoán tool khác."""
    if user.is_superadmin:
        return []
    perms = await user_permissions(session, user.id)
    missing = [desc.split(":")[0] for name, desc in toolsets().items() if perm_of(name) not in perms]
    if not missing:
        return []
    return [
        f"agent_access: chưa được dùng trợ lý cho {', '.join(missing)} — người dùng nhờ việc này thì nói tài khoản"
        " chưa được cấp quyền dùng trợ lý cho việc đó (nhờ quản trị cấp), không làm thay bằng cách khác"
    ]


async def _provider_lines(session, user: User, p: ContextProvider) -> list[str]:
    """Provider của module đọc bằng session đã scope theo tenant của user (B14 — module không nhắc tới tenant)."""
    previous = session_tenant(session)
    scope_session(session, user.tenant_id)
    try:
        lines = await p.fn(session, user)
    except Exception as exc:  # noqa: BLE001 — một module hỏng không được làm hỏng cả lượt chat
        logger.warning("context provider %s lỗi: %s", p.name, exc, extra={"loc": "agt0105"})
        return []
    finally:
        scope_session(session, previous)
    if len(lines) > p.budget:
        return [*lines[: p.budget], f"- còn {len(lines) - p.budget} dòng {p.name} — dùng tool tra cứu"]
    return lines


async def short(session, user_id: uuid.UUID) -> str:
    """Ngữ cảnh rút gọn cho router: chỉ provider khai `router=True`, tối đa 10 dòng mỗi provider."""
    user = await session.get(User, user_id)
    if user is None:
        return "-"
    lines: list[str] = []
    for p in providers():
        if p.router:
            lines += (await _provider_lines(session, user, p))[:10]
    return "\n".join(lines) or "-"


async def build(session, user_id: uuid.UUID, *, extra: list[str] | None = None, now: datetime | None = None) -> str:
    user = await session.get(User, user_id)
    if user is None:
        return ""
    tz = user.timezone or "Asia/Ho_Chi_Minh"
    at = (now or datetime.now(UTC)).astimezone(zone(tz))
    tenant = await session.get(Tenant, user.tenant_id) if user.tenant_id else None
    lines = [
        "<context>",
        f"user: {user.id} · {user.name or user.email} · múi giờ {tz} · ngôn ngữ {user.locale}"
        f" · role {', '.join(await role_names(session, user.id)) or '-'}"
        + (f" · tổ chức {tenant.name}" if tenant else "")
        + (" · superadmin" if user.is_superadmin else ""),
        f"now: {at.isoformat(timespec='minutes')} ({at.strftime('%A')})",
        *await _access_line(session, user),
    ]
    for p in providers():
        lines += await _provider_lines(session, user, p)
    lines += extra or []
    lines.append("</context>")
    return "\n".join(lines)
