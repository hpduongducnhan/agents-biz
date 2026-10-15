"""Input / output của op Tasks."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.core.operations.pagination import PageIn

Status = Literal["todo", "doing", "done", "cancelled"]
Priority = Literal["low", "normal", "high", "urgent"]
DueFilter = Literal["overdue", "today", "week", "none"]
Sort = Literal["due", "updated", "created", "priority"]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Body = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class PersonRef(BaseModel):
    id: uuid.UUID
    name: str


class TaskOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str
    status: Status
    priority: Priority
    due_at: datetime | None
    overdue: bool
    assignee: PersonRef | None
    created_by: PersonRef | None
    source: str
    position: float
    comment_count: int
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CommentOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    author: PersonRef | None
    body: str
    source: str
    created_at: datetime


class TaskDetail(TaskOut):
    comments: list[CommentOut]  # 100 bình luận gần nhất, cũ → mới


class TasksIn(PageIn):
    status: Status | None = None
    open_only: bool = Field(default=False, description="chỉ việc chưa xong (todo + doing)")
    assignee_id: uuid.UUID | None = None
    mine: bool = Field(default=False, description="việc giao cho tôi")
    due: DueFilter | None = Field(default=None, description="overdue · today · week (7 ngày tới) · none (không hạn)")
    q: str | None = Field(default=None, max_length=200, description="tìm trong tiêu đề / mô tả")
    sort: Sort = "due"


class TaskIdIn(BaseModel):
    task_id: uuid.UUID


class CreateIn(BaseModel):
    title: Title
    description: str = Field(default="", max_length=10_000)
    status: Status = "todo"
    priority: Priority = "normal"
    due_at: datetime | None = None
    assignee_id: uuid.UUID | None = None


class UpdateIn(BaseModel):
    """Chỉ trường gửi lên mới đổi; `due_at: null` = bỏ hạn."""

    task_id: uuid.UUID
    title: Title | None = None
    description: str | None = Field(default=None, max_length=10_000)
    priority: Priority | None = None
    due_at: datetime | None = None
    position: float | None = None


class AssignIn(BaseModel):
    task_id: uuid.UUID
    assignee_id: uuid.UUID | None = Field(description="null = bỏ giao")


class StatusIn(BaseModel):
    task_id: uuid.UUID
    status: Status


class CommentIn(BaseModel):
    task_id: uuid.UUID
    body: Body


class SummaryOut(BaseModel):
    todo: int
    doing: int
    done: int
    cancelled: int
    overdue: int
    due_today: int
    mine_open: int
    mine_overdue: int


class PeopleIn(BaseModel):
    q: str | None = Field(default=None, max_length=100)
    limit: int = Field(default=20, ge=1, le=100)
