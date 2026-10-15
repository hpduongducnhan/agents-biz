"""JWT access token ký bất đối xứng (EdDSA / RS256): api ký bằng private key, mọi nơi kiểm bằng public key.
Refresh token là chuỗi ngẫu nhiên — DB chỉ lưu SHA-256."""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from collections.abc import Iterable
from functools import cached_property

import jwt

from app.core.errors import AppException
from app.core.settings import Settings, get_settings


def pem_from_env(value: str) -> str:
    """PEM dán vào env có khi mất xuống dòng (một dòng với `\\n`) — đưa về dạng nhiều dòng."""
    value = value.strip()
    return value.replace("\\n", "\n") if "\n" not in value else value


class TokenService:
    def __init__(self, settings: Settings) -> None:
        self.algorithm = settings.AUTH_ALGORITHM
        self.access_minutes = settings.AUTH_ACCESS_TOKEN_EXPIRE_MINUTES
        self._private_path = settings.resolve_path(settings.AUTH_PRIVATE_KEY_FILE)
        self._public_path = settings.resolve_path(settings.AUTH_PUBLIC_KEY_FILE)
        self._private_pem = settings.AUTH_PRIVATE_KEY
        self._public_pem = settings.AUTH_PUBLIC_KEY

    @cached_property
    def private_key(self) -> str:
        if self._private_pem:
            return pem_from_env(self._private_pem)
        if self._private_path is None or not self._private_path.is_file():
            raise RuntimeError("AUTH_PRIVATE_KEY_FILE chưa cấu hình / không tồn tại — process này không ký được token")
        return self._private_path.read_text(encoding="utf-8")

    @cached_property
    def public_key(self) -> str:
        if self._public_pem:
            return pem_from_env(self._public_pem)
        if self._public_path is None or not self._public_path.is_file():
            raise RuntimeError("AUTH_PUBLIC_KEY_FILE chưa cấu hình / không tồn tại")
        return self._public_path.read_text(encoding="utf-8")

    def issue_access(
        self, *, user_id: uuid.UUID, sup: bool, perms: Iterable[str], tenant_id: uuid.UUID | None = None
    ) -> tuple[str, int]:
        """Claims BizWithAgents: sub · tid · typ · perms · sup · iat · exp."""
        now = int(time.time())
        expires_in = self.access_minutes * 60
        claims = {
            "sub": str(user_id),
            "tid": str(tenant_id) if tenant_id else None,
            "typ": "access",
            "perms": [] if sup else sorted(set(perms)),  # superadmin bỏ qua kiểm quyền → token nhỏ hơn
            "sup": sup,
            "iat": now,
            "exp": now + expires_in,
        }
        return jwt.encode(claims, self.private_key, algorithm=self.algorithm), expires_in

    def decode_access(self, token: str) -> dict:
        try:
            claims = jwt.decode(
                token, self.public_key, algorithms=[self.algorithm], options={"require": ["exp", "iat", "sub"]}
            )
        except jwt.ExpiredSignatureError as exc:
            raise AppException(1004, status_code=401, detail="Token expired") from exc
        except jwt.InvalidTokenError as exc:
            raise AppException(1004, status_code=401, detail="Invalid token") from exc
        if claims.get("typ") != "access":
            raise AppException(1004, status_code=401, detail="Invalid token")
        return claims


_service: TokenService | None = None


def configure_tokens(settings: Settings) -> TokenService:
    global _service
    _service = TokenService(settings)
    return _service


def get_token_service() -> TokenService:
    return _service if _service is not None else configure_tokens(get_settings())


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
