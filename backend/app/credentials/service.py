"""Ghi / đọc credential: mã hoá khi ghi, giải mã phía server khi cần (log mục đích, không log giá trị)."""

from __future__ import annotations

import uuid

from sqlmodel import select

from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.settings import Settings
from app.credentials import crypto
from app.credentials.models import Credential

logger = get_logger(__name__)


def seal(cred: Credential, secret: str, settings: Settings) -> None:
    cred.secret_ciphertext, cred.key_id = crypto.encrypt(secret, settings)
    cred.masked_hint = crypto.mask(secret)


async def reveal(session, credential_id: uuid.UUID, settings: Settings, *, purpose: str) -> str:
    cred = await session.get(Credential, credential_id)
    if cred is None:
        raise AppException(1001, status_code=404, detail="Credential not found")
    plain = crypto.decrypt(cred.secret_ciphertext, settings)
    logger.info("giải mã credential=%s purpose=%s", credential_id, purpose, extra={"loc": "cred0002"})
    return plain


async def rotate_all(session, settings: Settings) -> int:
    """Mã hoá lại mọi credential bằng khoá đầu danh sách (sau khi thêm khoá mới vào đầu `CREDENTIAL_KEYS`)."""
    first = crypto.key_id(crypto.keys(settings)[0])
    changed = 0
    for cred in (await session.exec(select(Credential))).all():
        if cred.key_id == first:
            continue
        seal(cred, crypto.decrypt(cred.secret_ciphertext, settings), settings)
        session.add(cred)
        changed += 1
    await session.flush()
    logger.info("xoay khoá credential: %d bản ghi", changed, extra={"loc": "cred0003"})
    return changed
