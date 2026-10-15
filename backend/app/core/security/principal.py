"""Principal = ai đang gọi + quyền hệ thống + tenant (D10). Nguồn (JWT) cắm qua resolver — miền auth cài."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Request

from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.rkeys import rkey

logger = get_logger(__name__)


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    perms: frozenset[str] = frozenset()
    sup: bool = False  # superadmin — vượt mọi kiểm quyền
    tenant_id: uuid.UUID | None = None  # claim `tid` (D10) — runner lọc dữ liệu theo tenant này

    def can(self, perm: str | None) -> bool:
        return perm is None or self.sup or perm in self.perms


Resolver = Callable[[Request], Awaitable[Principal | None]]
_state: dict = {"resolver": None, "warned": False}


def set_principal_resolver(fn: Resolver | None) -> None:
    _state["resolver"] = fn


async def resolve_principal(request: Request) -> Principal | None:
    """Principal của request (None = ẩn danh). Ghi user vào `request.state` cho dòng log HTTP."""
    resolver = _state["resolver"]
    if resolver is None:
        if not _state["warned"]:
            _state["warned"] = True
            msg = "chưa cài principal resolver — mọi request là ẩn danh; DEFAULTS_APPLIED=[principal_resolver=none]"
            logger.warning(msg, extra={"loc": "sys0406"})
        return None
    principal = await resolver(request)
    if principal is not None:
        request.state.user_id = str(principal.user_id)
    return principal


async def require_principal(request: Request) -> Principal:
    """FastAPI dependency cho route viết tay cần đăng nhập."""
    principal = await resolve_principal(request)
    if principal is None:
        raise AppException(1004, status_code=401)
    return principal


def principal_from_claims(claims: dict) -> Principal | None:
    """Claims đã xác thực (JWT, hoặc envelope `bw.rt.in` do service realtime gắn) → Principal; `sub` hỏng → None."""
    try:
        user_id = uuid.UUID(str(claims.get("sub")))
    except ValueError:
        return None
    sup = claims.get("sup") is True
    perms = frozenset() if sup else frozenset(str(p) for p in claims.get("perms") or ())
    try:
        tenant_id = uuid.UUID(str(claims["tid"])) if claims.get("tid") else None
    except ValueError:
        return None
    return Principal(user_id=user_id, perms=perms, sup=sup, tenant_id=tenant_id)


def disabled_key(user_id: uuid.UUID | str) -> str:
    """Dấu tài khoản bị khoá — ghi khi khoá tài khoản (TTL = đời access token); HTTP và event client cùng đọc."""
    return rkey("auth", "disabled", str(user_id))


async def is_disabled(redis, user_id: uuid.UUID | str) -> bool:
    return bool(await redis.exists(disabled_key(user_id)))
