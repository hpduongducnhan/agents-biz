"""Mã hoá credential: danh sách khoá Fernet `CREDENTIAL_KEYS` — khoá đầu mã hoá, mọi khoá giải mã (xoay khoá được).
Prod thiếu khoá → 6016 (không tự sinh: mất khoá = mất mọi credential). Dev / test thiếu khoá → khoá tạm trong bộ nhớ,
cảnh báo một lần (R11)."""

from __future__ import annotations

import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.settings import Settings

logger = get_logger(__name__)
_state: dict[str, bytes | None] = {"ephemeral": None}


def configured_keys(settings: Settings) -> list[bytes]:
    return [k.strip().encode() for k in settings.CREDENTIAL_KEYS.split(",") if k.strip()]


def keys(settings: Settings) -> list[bytes]:
    found = configured_keys(settings)
    if found:
        return found
    if settings.is_prod:
        raise AppException(6016, status_code=503, detail="CREDENTIAL_KEYS is not configured")
    if _state["ephemeral"] is None:
        _state["ephemeral"] = Fernet.generate_key()
        logger.warning(
            "CREDENTIAL_KEYS trống — khoá tạm trong bộ nhớ (mất khi tắt process); DEFAULTS_APPLIED=[CREDENTIAL_KEYS]",
            extra={"loc": "cred0001"},
        )
    return [_state["ephemeral"]]


def keys_ready(settings: Settings) -> bool:
    return bool(configured_keys(settings)) or not settings.is_prod


def key_id(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:8]


def encrypt(plain: str, settings: Settings) -> tuple[str, str]:
    first = keys(settings)[0]
    return Fernet(first).encrypt(plain.encode()).decode(), key_id(first)


def decrypt(cipher: str, settings: Settings) -> str:
    for key in keys(settings):
        try:
            return Fernet(key).decrypt(cipher.encode()).decode()
        except InvalidToken:
            continue
    raise AppException(6016, status_code=503, detail="Credential cannot be decrypted with the configured keys")


def mask(plain: str) -> str:
    """`sk-abcdef1234` → `sk-…1234`; quá ngắn → `…` (không lộ gì)."""
    value = plain.strip()
    if len(value) < 10:
        return "…"
    dash = value.find("-")
    prefix = value[: dash + 1] if 0 < dash < 6 else value[:2]
    return f"{prefix}…{value[-4:]}"


def new_key() -> str:
    return Fernet.generate_key().decode()
