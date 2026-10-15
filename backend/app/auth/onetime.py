"""Token một lần / có hạn qua email hoặc link (`auth_tokens`): xác thực email, đặt lại mật khẩu, lời mời vào tenant.
DB chỉ giữ SHA-256; token thô chỉ có trong link. Kiểm hợp lệ: đúng mục đích, chưa thu hồi, chưa hết hạn, còn lượt."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel import select

from app.auth.models import AuthToken
from app.auth.tokens import hash_token, new_refresh_token


def _now() -> datetime:
    return datetime.now(UTC)


async def issue(
    session,
    *,
    purpose: str,
    ttl: timedelta,
    user_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    email: str | None = None,
    role_id: uuid.UUID | None = None,
    max_uses: int = 1,
    created_by: uuid.UUID | None = None,
) -> tuple[str, AuthToken]:
    raw = new_refresh_token()
    row = AuthToken(
        purpose=purpose,
        token_hash=hash_token(raw),
        user_id=user_id,
        tenant_id=tenant_id,
        email=email,
        role_id=role_id,
        max_uses=max_uses,
        expires_at=_now() + ttl,
        created_by=created_by,
    )
    session.add(row)
    await session.flush()
    return raw, row


def is_valid(row: AuthToken | None, purpose: str) -> bool:
    return bool(
        row is not None
        and row.purpose == purpose
        and row.revoked_at is None
        and row.expires_at > _now()
        and row.uses < row.max_uses
    )


async def find_valid(session, raw: str, purpose: str, *, lock: bool = False) -> AuthToken | None:
    """Token còn dùng được (khoá dòng khi `lock` — chống hai request cùng tiêu một lượt cuối)."""
    if not raw:
        return None
    stmt = select(AuthToken).where(AuthToken.token_hash == hash_token(raw))
    if lock:
        stmt = stmt.with_for_update()
    row = (await session.exec(stmt)).first()
    return row if is_valid(row, purpose) else None


def consume(session, row: AuthToken) -> None:
    row.uses += 1
    row.used_at = _now()
    session.add(row)


async def revoke_for_user(session, user_id: uuid.UUID, purpose: str) -> None:
    """Thu hồi token cũ cùng mục đích của user — gửi lại thư thì chỉ link mới nhất dùng được."""
    stmt = select(AuthToken).where(
        AuthToken.user_id == user_id, AuthToken.purpose == purpose, AuthToken.revoked_at.is_(None)
    )
    for row in (await session.exec(stmt)).all():
        row.revoked_at = _now()
        session.add(row)
