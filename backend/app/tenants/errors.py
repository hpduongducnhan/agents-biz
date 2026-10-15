"""Mã lỗi tenant / đăng ký — trong dải auth (2000–2999)."""

from __future__ import annotations

from app.core.errors import register_errors

TENANT_ERRORS: dict[int, str] = {
    2109: "Email already has an account",
    2110: "Tenant is suspended",
    2111: "Tenant has reached its user limit",
    2112: "Verify your email first",
    2113: "Email not verified",
    2114: "Link is invalid or has expired",
    2115: "Tenant not found",
}
register_errors(TENANT_ERRORS, owner="auth")
