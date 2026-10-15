"""Dựng dữ liệu auth cho test — ghi thẳng DB, không qua API (không vướng signup_open / rate limit).
Dùng chung cho mọi test. Cần bước sau migrate đã chạy (role có sẵn)."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from functools import cache

from app.auth import rbac
from app.auth.models import Role, RolePermission, User, UserRole
from app.auth.passwords import hash_password
from app.auth.rbac import role_by_name
from app.domains import load_domains
from app.tenants.models import DEFAULT_TENANT_ID, Tenant

PASSWORD = "password123"


def agent_toolset_codes() -> list[str]:
    """Quyền `agent.<toolset>` theo catalog code (nền `lookup` + toolset của mọi module)."""
    load_domains()
    return sorted(rbac.AGENT_TOOLSET_PERMS)


def role_perms_in_code(role: str) -> list[str]:
    """Quyền role có sẵn theo catalog code (lõi + mọi module) — DB phải khớp sau `bw migrate`."""
    load_domains()
    return sorted(rbac.builtin_roles()[role][1])


def user_perms() -> list[str]:
    return role_perms_in_code("member")  # role mặc định của user mới


@cache
def _hashed(password: str) -> str:
    return hash_password(password)  # argon2 chậm có chủ ý → băm mỗi mật khẩu một lần cho cả phiên test


async def make_user(
    session,
    email: str,
    *,
    password: str | None = PASSWORD,
    name: str | None = None,
    roles: Iterable[str] = ("member",),
    is_active: bool = True,
    tenant_id: uuid.UUID = DEFAULT_TENANT_ID,
    email_verified: bool = True,
    is_superadmin: bool = False,
    must_change_password: bool = False,
) -> User:
    """User + role theo tên (mặc định `member` như người tự đăng ký), thuộc `tenant_id` (mặc định tenant `default`).
    `password=None` = tài khoản chỉ có Google.
    `is_superadmin` chỉ là giá trị ban đầu — đăng nhập / refresh đặt lại theo SUPERADMIN_EMAILS."""
    email = email.strip().lower()
    user = User(
        tenant_id=tenant_id,
        email=email,
        email_verified_at=datetime.now(UTC) if email_verified else None,
        name=name if name is not None else email.split("@")[0],
        password_hash=_hashed(password) if password else None,
        timezone="Asia/Ho_Chi_Minh",
        is_active=is_active,
        is_superadmin=is_superadmin,
        must_change_password=must_change_password,
    )
    session.add(user)
    await session.flush()
    for role in roles:
        await grant_role(session, user, role)
    return user


async def make_role(session, name: str, perms: Iterable[str] = (), *, description: str = "") -> Role:
    """Role tự tạo (không builtin) với quyền cho sẵn — quyền phải có trong bảng permissions."""
    role = Role(name=name, description=description, is_builtin=False)
    session.add(role)
    await session.flush()
    session.add_all(RolePermission(role_id=role.id, permission=p) for p in perms)
    await session.flush()
    return role


async def grant_role(session, user: User, role: Role | str) -> None:
    if isinstance(role, str):
        role = await role_by_name(session, role)
    session.add(UserRole(user_id=user.id, role_id=role.id))
    await session.flush()


async def make_tenant(session, name: str, *, slug: str | None = None, status: str = "active", policies=None) -> Tenant:
    tenant = Tenant(name=name, slug=slug or name.lower().replace(" ", "-"), status=status, policies=policies or {})
    session.add(tenant)
    await session.flush()
    return tenant
