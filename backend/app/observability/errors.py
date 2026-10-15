"""Mã lỗi của quan sát (dải 7000–7999)."""

from __future__ import annotations

from app.core.errors import register_errors

OBS_ERRORS: dict[int, str] = {
    7001: "Log store (Mongo) is not responding",
    7002: "Issue not found",
}
register_errors(OBS_ERRORS, owner="observability")
