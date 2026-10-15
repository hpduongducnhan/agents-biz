"""Bảng `tasks` + `task_comments` (migration `0009_tasks`) — theo tenant (B14)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, Column, DateTime, Float, ForeignKey, Index, String, Text, Uuid, func
from sqlmodel import Field

from app.core.tenancy import TenantScoped

STATUSES: tuple[str, ...] = ("todo", "doing", "done", "cancelled")
OPEN_STATUSES: tuple[str, ...] = ("todo", "doing")
PRIORITIES: tuple[str, ...] = ("low", "normal", "high", "urgent")


def _now() -> datetime:
    return datetime.now(UTC)


def _ts(*, nullable: bool = False, onupdate: bool = False) -> Column:
    return Column(
        DateTime(timezone=True),
        nullable=nullable,
        server_default=None if nullable else func.now(),
        onupdate=_now if onupdate else None,
    )


class Task(TenantScoped, table=True):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("status IN ('todo', 'doing', 'done', 'cancelled')", name="ck_tasks_status"),
        CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')", name="ck_tasks_priority"),
        CheckConstraint("source IN ('web', 'agent')", name="ck_tasks_source"),
        Index("ix_tasks_tenant_status_due", "tenant_id", "status", "due_at"),
        Index("ix_tasks_tenant_assignee", "tenant_id", "assignee_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, sa_column=Column(Uuid, primary_key=True))
    title: str = Field(sa_column=Column(String(200), nullable=False))
    description: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))
    status: str = Field(default="todo", sa_column=Column(String(16), nullable=False, server_default="todo"))
    priority: str = Field(default="normal", sa_column=Column(String(16), nullable=False, server_default="normal"))
    due_at: datetime | None = Field(default=None, sa_column=_ts(nullable=True))
    assignee_id: uuid.UUID | None = Field(
        default=None, sa_column=Column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    )
    position: float = Field(default=0.0, sa_column=Column(Float, nullable=False, server_default="0"))
    created_by: uuid.UUID | None = Field(
        default=None, sa_column=Column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    )
    source: str = Field(default="web", sa_column=Column(String(8), nullable=False, server_default="web"))
    agent_run_id: uuid.UUID | None = Field(default=None, sa_column=Column(Uuid, nullable=True))
    completed_at: datetime | None = Field(default=None, sa_column=_ts(nullable=True))
    created_at: datetime = Field(default_factory=_now, sa_column=_ts())
    updated_at: datetime = Field(default_factory=_now, sa_column=_ts(onupdate=True))


class TaskComment(TenantScoped, table=True):
    __tablename__ = "task_comments"
    __table_args__ = (Index("ix_task_comments_task_created", "task_id", "created_at"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, sa_column=Column(Uuid, primary_key=True))
    task_id: uuid.UUID = Field(sa_column=Column(Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False))
    author_id: uuid.UUID | None = Field(
        default=None, sa_column=Column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    )
    body: str = Field(sa_column=Column(Text, nullable=False))
    source: str = Field(default="web", sa_column=Column(String(8), nullable=False, server_default="web"))
    created_at: datetime = Field(default_factory=_now, sa_column=_ts())
