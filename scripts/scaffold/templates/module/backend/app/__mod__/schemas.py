"""Input / output của op __title_vi__."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.core.operations.pagination import PageIn

Status = Literal["open", "done"]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class PersonRef(BaseModel):
    id: uuid.UUID
    name: str


class ItemOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str
    status: Status
    created_by: PersonRef | None
    source: str
    created_at: datetime
    updated_at: datetime


class ListIn(PageIn):
    status: Status | None = None
    mine: bool = Field(default=False, description="chỉ mục do tôi tạo")
    q: str | None = Field(default=None, max_length=200, description="tìm trong tiêu đề / mô tả")


class IdIn(BaseModel):
    item_id: uuid.UUID


class CreateIn(BaseModel):
    title: Title
    description: str = Field(default="", max_length=10_000)


class UpdateIn(BaseModel):
    """Chỉ trường gửi lên mới đổi."""

    item_id: uuid.UUID
    title: Title | None = None
    description: str | None = Field(default=None, max_length=10_000)
    status: Status | None = None
