"""Correlation id (cid) — một ContextVar cho mỗi task async; mọi dòng log mang nó."""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

CID_HEADER = "X-Correlation-ID"
_CID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_cid: ContextVar[str | None] = ContextVar("bw_cid", default=None)


def new_cid() -> str:
    return uuid.uuid4().hex


def is_valid_cid(value: str | None) -> bool:
    return bool(value) and bool(_CID_RE.match(value))


def get_cid() -> str | None:
    return _cid.get()


def set_cid(value: str | None) -> str:
    """Gắn cid cho context hiện tại. Giá trị không hợp lệ → sinh cid mới (không bao giờ tin chuỗi lạ)."""
    cid = value if is_valid_cid(value) else new_cid()
    _cid.set(cid)
    return cid
