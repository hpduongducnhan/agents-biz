"""Tài khoản: kiểu email / múi giờ / tiền tệ cho input, tạo user (+ role `user`), hồ sơ trả về FE."""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.auth.models import Role, User, UserRole
from app.auth.rbac import DEFAULT_ROLE, active_permission_codes, grant_role, user_permissions
from app.core.errors import AppException
from app.core.settings import Settings
from app.core.tenancy import ALL_TENANTS
from app.tenants.models import Tenant
from app.tenants.policies import agent_enabled

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def mask_email(email: str) -> str:
    """Email che cho người khác xem (`n***@gmail.com`) — tìm người nhận phiếu, tìm người mời vào nhóm."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def _check_email(value: str) -> str:
    """Kiểm dạng thoáng (tên miền nội bộ như .local vẫn hợp lệ); bỏ khoảng trắng + chữ thường."""
    value = normalize_email(value)
    if len(value) > 320 or not _EMAIL_RE.match(value):
        raise ValueError("value is not a valid email address")
    return value


def _check_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("unknown time zone") from exc
    return value


Email = Annotated[str, AfterValidator(_check_email)]
TimeZone = Annotated[str, AfterValidator(_check_timezone)]
# Ngôn ngữ giao diện + trợ lý (i18n vi / en — D7).
Locale = Literal["vi", "en"]


class RoleRef(BaseModel):
    id: uuid.UUID
    name: str


class TenantRef(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    agent_enabled: bool = True  # chính sách tenant — false: ẩn trợ lý ở frontend (agent.send → 6023)


class UserOut(BaseModel):
    id: uuid.UUID
    tenant: TenantRef | None  # None chỉ khi dữ liệu hỏng (user trỏ tenant đã xoá)
    email: str
    email_verified: bool
    name: str
    timezone: str
    locale: str
    is_active: bool
    is_superadmin: bool
    must_change_password: bool
    has_password: bool  # False = tài khoản chỉ đăng nhập Google
    roles: list[RoleRef]
    created_at: datetime
    last_login_at: datetime | None


class MeOut(UserOut):
    permissions: list[str]  # superadmin: mọi quyền đang dùng


async def user_by_email(session, email: str) -> User | None:
    """Email duy nhất trên toàn hệ thống (mọi tenant) → tra không lọc tenant, kể cả khi session đã scope."""
    stmt = select(User).where(User.email == normalize_email(email)).execution_options(**{ALL_TENANTS: True})
    return (await session.exec(stmt)).first()


async def create_user(
    session,
    settings: Settings,
    *,
    email: str,
    tenant_id: uuid.UUID,
    name: str = "",
    password_hash: str | None = None,
    role: Role | str = DEFAULT_ROLE,
    verified: bool = False,
) -> User:
    """User mới trong `tenant_id` + một role; cờ superadmin theo env. Trùng email (kể cả hai request song song) → 2101.
    Chọn tenant / role theo `signup_mode` + lời mời là việc của `app.tenants.enroll`."""
    email = normalize_email(email)
    if await user_by_email(session, email) is not None:
        raise AppException(2101, status_code=409)
    user = User(
        tenant_id=tenant_id,
        email=email,
        name=name.strip() or email.split("@")[0],
        password_hash=password_hash,
        timezone=settings.APP_TIMEZONE,
        is_superadmin=email in settings.superadmin_emails,
        email_verified_at=datetime.now(UTC) if verified else None,
    )
    try:
        async with session.begin_nested():  # unique citext chặn bản thứ hai
            session.add(user)
            await session.flush()
    except IntegrityError as exc:
        raise AppException(2101, status_code=409) from exc
    await grant_role(session, user.id, role)
    return user


async def load_active_user(session, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise AppException(1004, status_code=401)
    if not user.is_active:
        raise AppException(2103, status_code=403)
    return user


async def roles_by_user(session, user_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[RoleRef]]:
    out: dict[uuid.UUID, list[RoleRef]] = {uid: [] for uid in user_ids}
    if not out:
        return out
    stmt = (
        select(UserRole.user_id, Role.id, Role.name)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id.in_(list(out)))
        .order_by(Role.is_builtin.desc(), Role.name)
    )
    for user_id, role_id, name in (await session.exec(stmt)).all():
        out[user_id].append(RoleRef(id=role_id, name=name))
    return out


async def tenants_by_id(session, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, TenantRef]:
    if not ids:
        return {}
    rows = (await session.exec(select(Tenant).where(Tenant.id.in_(list(set(ids)))))).all()
    return {t.id: TenantRef(id=t.id, name=t.name, slug=t.slug, agent_enabled=agent_enabled(t)) for t in rows}


def _user_out(user: User, roles: list[RoleRef], tenant: TenantRef | None) -> UserOut:
    return UserOut(
        id=user.id,
        tenant=tenant,
        email=user.email,
        email_verified=user.email_verified_at is not None,
        name=user.name,
        timezone=user.timezone,
        locale=user.locale,
        is_active=user.is_active,
        is_superadmin=user.is_superadmin,
        must_change_password=user.must_change_password,
        has_password=user.password_hash is not None,
        roles=roles,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


async def users_out(session, users: Sequence[User]) -> list[UserOut]:
    roles = await roles_by_user(session, [u.id for u in users])
    tenants = await tenants_by_id(session, [u.tenant_id for u in users if u.tenant_id])
    return [_user_out(u, roles[u.id], tenants.get(u.tenant_id)) for u in users]


async def me_out(session, user: User) -> MeOut:
    base = (await users_out(session, [user]))[0]
    if user.is_superadmin:
        perms = await active_permission_codes(session)
    else:
        perms = sorted(await user_permissions(session, user.id))
    return MeOut(**base.model_dump(), permissions=perms)
