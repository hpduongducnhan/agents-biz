"""Phiên đăng nhập = cặp (access JWT, refresh token xoay vòng theo họ `family_id`)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import delete, update
from sqlmodel import select

from app.auth.models import RefreshToken, User
from app.auth.rbac import user_permissions
from app.auth.superadmins import apply_superadmin
from app.auth.tokens import get_token_service, hash_token, new_refresh_token
from app.core.connections.registry import get_connections
from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.settings import Settings
from app.notifications.models import PushSubscription

logger = get_logger(__name__)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


async def issue_session(
    session, user: User, *, settings: Settings, ip: str | None = None, family_id: uuid.UUID | None = None
) -> TokenPair:
    perms = frozenset() if user.is_superadmin else await user_permissions(session, user.id)
    access, expires_in = get_token_service().issue_access(
        user_id=user.id, sup=user.is_superadmin, perms=perms, tenant_id=user.tenant_id
    )
    raw = new_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(raw),
            family_id=family_id or uuid.uuid4(),
            expires_at=datetime.now(UTC) + timedelta(days=settings.AUTH_REFRESH_TOKEN_EXPIRE_DAYS),
            ip=ip[:64] if ip else None,
        )
    )
    await session.flush()
    return TokenPair(access_token=access, refresh_token=raw, expires_in=expires_in)


async def revoke_family(session, family_id: uuid.UUID) -> None:
    await session.exec(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


async def revoke_all(session, user_id: uuid.UUID) -> None:
    """Thu hồi mọi phiên (đăng xuất mọi nơi, đổi / đặt lại mật khẩu, khoá tài khoản) — kèm gỡ mọi máy đã bật thông báo
    đẩy để máy cũ không còn nhận thông báo của tài khoản."""
    await session.exec(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await session.exec(delete(PushSubscription).where(PushSubscription.user_id == user_id))


async def find_refresh(session, raw: str, *, lock: bool = False) -> RefreshToken | None:
    stmt = select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw))
    if lock:
        stmt = stmt.with_for_update()
    return (await session.exec(stmt)).first()


async def _revoke_family_now(family_id: uuid.UUID) -> None:
    """Commit riêng: lỗi 401 phía sau rollback session chính nhưng việc thu hồi phải giữ."""
    async with get_connections().postgres.rw() as other:
        await revoke_family(other, family_id)


async def _has_live_token(session, family_id: uuid.UUID) -> bool:
    stmt = select(RefreshToken.id).where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
    return (await session.exec(stmt)).first() is not None


async def rotate_refresh(session, raw: str, *, settings: Settings, ip: str | None = None) -> tuple[User, TokenPair]:
    row = await find_refresh(session, raw, lock=True)
    if row is None:
        raise AppException(2104, status_code=401)
    now = datetime.now(UTC)
    if row.revoked_at is not None:
        grace = timedelta(seconds=settings.AUTH_REFRESH_REUSE_GRACE_SECONDS)
        if now - row.revoked_at <= grace and await _has_live_token(session, row.family_id):
            raise AppException(2104, status_code=401)  # hai tab refresh cùng lúc — tab kia đã giữ phiên
        logger.warning(
            "refresh token đã thu hồi bị dùng lại — thu hồi cả họ user=%s", row.user_id, extra={"loc": "auth0401"}
        )
        await _revoke_family_now(row.family_id)
        raise AppException(2104, status_code=401)
    user = await session.get(User, row.user_id)
    if row.expires_at <= now or user is None or not user.is_active:
        raise AppException(2104, status_code=401)
    row.revoked_at = now
    session.add(row)
    apply_superadmin(user, settings)
    session.add(user)
    return user, await issue_session(session, user, settings=settings, ip=ip, family_id=row.family_id)
