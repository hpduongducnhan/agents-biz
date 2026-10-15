"""Cặp khoá ký JWT của một bộ deploy: PEM trong env (ưu tiên), hoặc file — thiếu thì sinh Ed25519 lần đầu."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.settings import Settings


def _write(path: Path, data: bytes, mode: int) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.chmod(path, mode)  # umask của process không được nới / siết quyền đã định


def generate_pem_pair() -> tuple[bytes, bytes]:
    """Cặp Ed25519 mới dạng PEM: (private PKCS8, public SubjectPublicKeyInfo)."""
    key = Ed25519PrivateKey.generate()
    return (
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()),
        key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo),
    )


def env_lines(private_pem: bytes, public_pem: bytes) -> str:
    """Hai dòng `AUTH_PRIVATE_KEY=…` / `AUTH_PUBLIC_KEY=…`, PEM gói một dòng bằng `\\n` để dán vào env."""

    def one_line(pem: bytes) -> str:
        return pem.decode().strip().replace("\n", "\\n")

    return f"AUTH_PRIVATE_KEY={one_line(private_pem)}\nAUTH_PUBLIC_KEY={one_line(public_pem)}"


def ensure_keypair(settings: Settings) -> Literal["env", "exists", "generated"]:
    if bool(settings.AUTH_PRIVATE_KEY) != bool(settings.AUTH_PUBLIC_KEY):
        raise RuntimeError("AUTH_PRIVATE_KEY và AUTH_PUBLIC_KEY phải đặt cùng nhau (hoặc bỏ trống cả hai)")
    if settings.AUTH_PRIVATE_KEY:
        return "env"
    priv = settings.resolve_path(settings.AUTH_PRIVATE_KEY_FILE)
    pub = settings.resolve_path(settings.AUTH_PUBLIC_KEY_FILE)
    if priv is None or pub is None:
        raise RuntimeError("chưa có khoá JWT: đặt AUTH_PRIVATE_KEY_FILE + AUTH_PUBLIC_KEY_FILE hoặc PEM trong env")
    if priv.is_file() and pub.is_file():
        return "exists"
    if priv.is_file() or pub.is_file():
        raise RuntimeError(f"chỉ có một file khoá JWT ({priv} / {pub}) — xoá file còn lại để sinh cặp mới")
    private_pem, public_pem = generate_pem_pair()
    for path in (priv, pub):
        path.parent.mkdir(parents=True, exist_ok=True)
    _write(priv, private_pem, 0o600)
    _write(pub, public_pem, 0o644)
    return "generated"
