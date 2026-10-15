"""Phân trang dùng chung (R14): input `PageIn` (`limit` 1–100, mặc định 20; `offset` ≥ 0 — vượt thì
runner trả 422 mã 1002) và output `Page[T]` cho mọi operation danh sách."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
T = TypeVar("T")


class PageIn(BaseModel):
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)
    offset: int = Field(default=0, ge=0)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int
