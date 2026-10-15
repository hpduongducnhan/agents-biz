"""Bảng `__mod__` (migration `__rev__`) — theo tenant (B14)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, String, Text, Uuid, func
from sqlmodel import Field

from app.core.tenancy import TenantScoped

STATUSES: tuple[str, ...] = ("open", "done")


def _now() -> datetime:
    return datetime.now(UTC)


def _ts(*, onupdate: bool = False) -> Column:
    return Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=_now if onupdate else None)


class __Mod__Item(TenantScoped, table=True):
    __tablename__ = "__mod__"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'done')", name="ck___mod___status"),
        CheckConstraint("source IN ('web', 'agent')", name="ck___mod___source"),
        Index("ix___mod___tenant_status", "tenant_id", "status"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, sa_column=Column(Uuid, primary_key=True))
    title: str = Field(sa_column=Column(String(200), nullable=False))
    description: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))
    status: str = Field(default="open", sa_column=Column(String(16), nullable=False, server_default="open"))
    created_by: uuid.UUID | None = Field(
        default=None, sa_column=Column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    )
    source: str = Field(default="web", sa_column=Column(String(8), nullable=False, server_default="web"))
    agent_run_id: uuid.UUID | None = Field(default=None, sa_column=Column(Uuid, nullable=True))
    created_at: datetime = Field(default_factory=_now, sa_column=_ts())
    updated_at: datetime = Field(default_factory=_now, sa_column=_ts(onupdate=True))
