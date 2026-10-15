"""Bảng `agent_chat_blocks` (migration `0008_chat_blocks`): chặn user khỏi trợ lý — nguồn sự thật + lịch sử."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Text, text
from sqlmodel import Field, SQLModel

SOURCES: tuple[str, ...] = ("auto", "manual")


def _now() -> datetime:
    return datetime.now(UTC)


def _ts(*, nullable: bool = False) -> Column:
    return Column(DateTime(timezone=True), nullable=nullable, server_default=None if nullable else text("now()"))


def _user_fk(*, nullable: bool, cascade: bool = False) -> Column:
    return Column(ForeignKey("users.id", ondelete="CASCADE" if cascade else "SET NULL"), nullable=nullable)


class AgentChatBlock(SQLModel, table=True):
    __tablename__ = "agent_chat_blocks"
    __table_args__ = (
        CheckConstraint("source IN ('auto', 'manual')", name="ck_agent_chat_blocks_source"),
        Index("ix_agent_chat_blocks_open", "user_id", postgresql_where=text("lifted_at IS NULL")),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(sa_column=_user_fk(nullable=False, cascade=True))
    until: datetime | None = Field(default=None, sa_column=_ts(nullable=True))  # None = tới khi superadmin mở
    reason: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))
    source: str = Field(max_length=8)
    created_by: uuid.UUID | None = Field(default=None, sa_column=_user_fk(nullable=True))
    created_at: datetime = Field(default_factory=_now, sa_column=_ts())
    lifted_at: datetime | None = Field(default=None, sa_column=_ts(nullable=True))
    lifted_by: uuid.UUID | None = Field(default=None, sa_column=_user_fk(nullable=True))

    def active(self, now: datetime | None = None) -> bool:
        return self.lifted_at is None and (self.until is None or self.until > (now or _now()))
