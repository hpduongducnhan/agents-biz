"""Mã lỗi miền auth (gồm RBAC) — dải 2000–2999 (bảng mã ở auth-rbac)."""

from __future__ import annotations

from app.core.errors import register_errors

AUTH_ERRORS: dict[int, str] = {
    2101: "Email already registered",
    2102: "Invalid email or password",
    2103: "Account is disabled",
    2104: "Invalid or expired refresh token",
    2105: "Sign-up is closed",
    2106: "Current password is incorrect",
    2107: "Password is too short",
    2108: "Google sign-in is unavailable",
    2201: "Role name already exists",
    2202: "Built-in roles cannot be changed or deleted",
    2203: "Unknown permission",
    2204: "Superadmin is managed by SUPERADMIN_EMAILS, not via API",
    2205: "Role is assigned to users and cannot be deleted",
    2206: "You cannot disable your own account",
}
register_errors(AUTH_ERRORS, owner="auth")
