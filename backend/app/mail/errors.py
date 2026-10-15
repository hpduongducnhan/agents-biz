"""Mã lỗi mail — dải 8000–8999."""

from __future__ import annotations

from app.core.errors import register_errors

MAIL_ERRORS: dict[int, str] = {
    8001: "Mail template not found",
    8002: "Mail transport failed",
}
register_errors(MAIL_ERRORS, owner="mail")
