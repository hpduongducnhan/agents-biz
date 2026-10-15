"""Xếp người đăng ký mới vào tenant (D12): lời mời → `SUPERADMIN_EMAILS` → `signup_mode`. Dùng chung cho đăng ký
email + mật khẩu và đăng nhập Google lần đầu."""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import select

from app.auth import onetime
from app.auth.models import AuthToken, Role, User
from app.auth.rbac import DEFAULT_ROLE, TENANT_ADMIN_ROLE
from app.auth.users import create_user, normalize_email, user_by_email
from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.settings import Settings
from app.system import settings_store
from app.tenants.models import DEFAULT_TENANT_ID, Tenant
from app.tenants.service import create_tenant, ensure_can_join, get_tenant

logger = get_logger(__name__)


@dataclass(frozen=True)
class Placement:
    tenant: Tenant
    role: Role | str
    invite: AuthToken | None = None


async def _invite_role(session, row: AuthToken) -> Role | str:
    role = await session.get(Role, row.role_id) if row.role_id else None
    return role or DEFAULT_ROLE  # role của lời mời đã bị xoá → member


async def _pending_email_invite(session, email: str) -> AuthToken | None:
    """Lời mời còn hạn gắn đúng email này (mới nhất) — Google lần đầu không mang token trong URL."""
    stmt = (
        select(AuthToken)
        .where(AuthToken.purpose == "invite", AuthToken.email == email, AuthToken.revoked_at.is_(None))
        .order_by(AuthToken.created_at.desc())
        .with_for_update()
    )
    for row in (await session.exec(stmt)).all():
        if onetime.is_valid(row, "invite"):
            return row
    return None


async def place(
    session,
    settings: Settings,
    *,
    email: str,
    name: str,
    invite_token: str | None = None,
    tenant_name: str | None = None,
    allow_email_invite: bool = False,
) -> Placement:
    email = normalize_email(email)
    system = await settings_store.get_system_settings(session)
    invite: AuthToken | None = None
    if invite_token:
        invite = await onetime.find_valid(session, invite_token, "invite", lock=True)
        if invite is None or (invite.email and invite.email.lower() != email):
            raise AppException(2114, status_code=400)
    elif allow_email_invite:
        invite = await _pending_email_invite(session, email)
    if invite is not None:
        if await user_by_email(session, email) is not None:
            raise AppException(2109, status_code=409)
        placement = Placement(await get_tenant(session, invite.tenant_id), await _invite_role(session, invite), invite)
    elif email in settings.superadmin_emails or system.signup_mode == "default_tenant":
        placement = Placement(await get_tenant(session, DEFAULT_TENANT_ID), DEFAULT_ROLE)
    elif system.signup_mode == "new_tenant":
        placement = Placement(
            await create_tenant(session, tenant_name or name or email.split("@")[0]), TENANT_ADMIN_ROLE
        )
    else:  # invite_only
        raise AppException(2105, status_code=403)
    await ensure_can_join(session, placement.tenant, system.user_limit_default)
    return placement


async def enroll(
    session,
    settings: Settings,
    *,
    email: str,
    name: str = "",
    password_hash: str | None = None,
    invite_token: str | None = None,
    tenant_name: str | None = None,
    verified: bool = False,
    allow_email_invite: bool = False,
) -> User:
    """Tạo user mới đúng tenant + role; tiêu một lượt của lời mời (nếu có). Lỗi → cả transaction rollback (tenant
    mới tạo cho `new_tenant` cũng không còn)."""
    placement = await place(
        session,
        settings,
        email=email,
        name=name,
        invite_token=invite_token,
        tenant_name=tenant_name,
        allow_email_invite=allow_email_invite,
    )
    user = await create_user(
        session,
        settings,
        email=email,
        name=name,
        password_hash=password_hash,
        tenant_id=placement.tenant.id,
        role=placement.role,
        verified=verified or placement.invite is not None and placement.invite.email is not None,
    )
    if placement.invite is not None:
        onetime.consume(session, placement.invite)
    logger.info(
        "user mới %s → tenant %s role %s%s",
        user.id,
        placement.tenant.slug,
        placement.role if isinstance(placement.role, str) else placement.role.name,
        " (lời mời)" if placement.invite is not None else "",
        extra={"loc": "tnt0001"},
    )
    return user
