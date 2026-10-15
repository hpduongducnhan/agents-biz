"""Bearer JWT → Principal (quyền nằm trong token); ghi dấu khoá tài khoản; kiểm lại token superadmin cũ."""

from __future__ import annotations

import time
import uuid

from fastapi import Request

from app.auth.models import User
from app.auth.tokens import get_token_service
from app.core.connections.registry import get_connections
from app.core.errors import AppException
from app.core.security.principal import Principal, disabled_key, is_disabled, principal_from_claims
from app.tenants.service import is_tenant_disabled

BOOT_TS = int(time.time())  # token `sup` cấp trước mốc này được kiểm lại với DB


async def mark_disabled(redis, user_id: uuid.UUID | str, disabled: bool, ttl: int) -> None:
    if disabled:
        await redis.set(disabled_key(user_id), "1", ex=ttl)
    else:
        await redis.delete(disabled_key(user_id))


async def _still_superadmin(user_id: uuid.UUID) -> bool:
    async with get_connections().postgres.ro() as session:
        user = await session.get(User, user_id)
    return bool(user is not None and user.is_active and user.is_superadmin)


async def jwt_resolver(request: Request) -> Principal | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    claims = get_token_service().decode_access(token.strip())
    principal = principal_from_claims(claims)
    if principal is None:
        raise AppException(1004, status_code=401, detail="Invalid token")
    redis = get_connections().redis.rw
    if await is_disabled(redis, principal.user_id):
        raise AppException(2103, status_code=403)
    if await is_tenant_disabled(redis, principal.tenant_id):
        raise AppException(2110, status_code=403)
    if principal.sup and int(claims["iat"]) < BOOT_TS and not await _still_superadmin(principal.user_id):
        raise AppException(1004, status_code=401, detail="Token expired")
    return principal
