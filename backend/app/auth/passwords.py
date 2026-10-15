"""Mật khẩu: argon2id (pwdlib). Không bao giờ log / trả hash."""

from __future__ import annotations

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from app.core.errors import AppException

_hasher = PasswordHash.recommended()
DUMMY_HASH = _hasher.hash("dummy-password-for-timing")  # không có user / chưa có mật khẩu → vẫn so với hash này


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return _hasher.verify(password, hashed)
    except UnknownHashError:  # hash hỏng / lạ = sai mật khẩu; không lộ lý do ra ngoài
        return False


def check_password_policy(password: str, min_length: int) -> None:
    if len(password) < min_length:
        raise AppException(2107, status_code=422, detail=f"Password must be at least {min_length} characters")
