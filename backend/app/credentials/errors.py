"""Mã lỗi credential — trong dải agent (6000–6999)."""

from __future__ import annotations

from app.core.errors import register_errors

CREDENTIAL_ERRORS: dict[int, str] = {
    6016: "Credential unavailable — encryption key missing / wrong, or credential in use",
}
register_errors(CREDENTIAL_ERRORS, owner="agent")
