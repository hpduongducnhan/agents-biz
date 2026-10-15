"""Điều kiện đăng nhập ngoài mật khẩu: tenant còn hoạt động (2110), email đã xác thực khi
`email_verification=required` (2113 — superadmin miễn). Dùng chung cho email + mật khẩu và Google."""

from __future__ import annotations

from app.auth.flags import auth_flags
from app.auth.models import User
from app.core.errors import AppException
from app.core.settings import Settings
from app.tenants.models import Tenant


async def check_can_sign_in(session, settings: Settings, user: User) -> None:
    tenant = await session.get(Tenant, user.tenant_id) if user.tenant_id else None
    if tenant is None or tenant.status != "active":
        raise AppException(2110, status_code=403)
    if user.is_superadmin or user.email_verified_at is not None:
        return
    if (await auth_flags(session, settings)).email_verification == "required":
        raise AppException(2113, status_code=403)
