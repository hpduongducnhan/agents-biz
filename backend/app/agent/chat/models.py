"""Bảng chat (migration `0005_agent_chat`): phiên, tin nhắn (nguồn sự thật lịch sử), lượt chạy, yêu cầu duyệt —
đều theo tenant (D22). Checkpoint LangGraph ở schema `agent_lg` (thư viện tự tạo bảng), xoá khi run kết thúc."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from app.core.tenancy import TenantScoped

RUN_STATUSES: tuple[str, ...] = ("queued", "running", "waiting_approval", "done", "failed", "cancelled")
OPEN_STATUSES: tuple[str, ...] = ("queued", "running", "waiting_approval")


def _now() -> datetime:
    return datetime.now(UTC)


def _ts(*, nullable: bool = False, onupdate: bool = False) -> Column:
    return Column(
        DateTime(timezone=True),
        nullable=nullable,
        server_default=None if nullable else text("now()"),
        onupdate=_now if onupdate else None,
    )


class AgentSession(TenantScoped, table=True):
    __tablename__ = "agent_sessions"
    __table_args__ = (Index("ix_agent_sessions_user_updated", "user_id", "updated_at"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(sa_column=Column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False))
    entry_agent_id: uuid.UUID = Field(sa_column=Column(ForeignKey("agents.id", ondelete="CASCADE"), nullable=False))
    title: str = Field(default="", max_length=120)
    last_agent_id: uuid.UUID | None = Field(
        default=None, sa_column=Column(ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    )
    created_at: datetime = Field(default_factory=_now, sa_column=_ts())
    updated_at: datetime = Field(default_factory=_now, sa_column=_ts(onupdate=True))


class AgentRun(TenantScoped, table=True):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'waiting_approval', 'done', 'failed', 'cancelled')",
            name="ck_agent_runs_status",
        ),
        Index(
            "uq_agent_runs_one_open",
            "session_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running', 'waiting_approval')"),
        ),
        Index("ix_agent_runs_status_heartbeat", "status", "heartbeat_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    session_id: uuid.UUID = Field(sa_column=Column(ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False))
    user_id: uuid.UUID = Field(sa_column=Column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False))
    entry_agent_id: uuid.UUID = Field(sa_column=Column(ForeignKey("agents.id", ondelete="CASCADE"), nullable=False))
    status: str = Field(default="queued", max_length=20)
    error_code: int | None = None
    error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    tokens_in: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, server_default="0"))
    tokens_out: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, server_default="0"))
    tokens_cache_read: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, server_default="0"))
    tokens_cache_write: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, server_default="0"))
    cost: Decimal = Field(default=Decimal(0), sa_column=Column(Numeric(14, 6), nullable=False, server_default="0"))
    credential_ids: list = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    )
    plan: dict | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    heartbeat_at: datetime | None = Field(default=None, sa_column=_ts(nullable=True))
    started_at: datetime | None = Field(default=None, sa_column=_ts(nullable=True))
    ended_at: datetime | None = Field(default=None, sa_column=_ts(nullable=True))
    created_at: datetime = Field(default_factory=_now, sa_column=_ts())


class AgentMessage(TenantScoped, table=True):
    __tablename__ = "agent_messages"
    __table_args__ = (
        UniqueConstraint("session_id", "seq", name="uq_agent_messages_session_seq"),
        UniqueConstraint("session_id", "client_msg_id", name="uq_agent_messages_client_msg"),
        CheckConstraint("role IN ('user', 'assistant', 'tool')", name="ck_agent_messages_role"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    session_id: uuid.UUID = Field(sa_column=Column(ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False))
    seq: int = Field(sa_column=Column(Integer, nullable=False))
    role: str = Field(max_length=16)
    agent_id: uuid.UUID | None = Field(
        default=None, sa_column=Column(ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    )
    content: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    run_id: uuid.UUID | None = Field(
        default=None, sa_column=Column(ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True)
    )
    client_msg_id: str | None = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=_now, sa_column=_ts())


class AgentApproval(TenantScoped, table=True):
    __tablename__ = "agent_approvals"
    __table_args__ = (
        UniqueConstraint("run_id", "tool_call_id", name="uq_agent_approvals_call"),
        CheckConstraint("status IN ('pending', 'approved', 'rejected', 'expired')", name="ck_agent_approvals_status"),
        Index("ix_agent_approvals_status_expires", "status", "expires_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(sa_column=Column(ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False))
    tool_call_id: str = Field(max_length=128)
    agent_id: uuid.UUID | None = Field(
        default=None, sa_column=Column(ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    )
    operation: str = Field(max_length=128)
    args: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    status: str = Field(default="pending", max_length=16)
    decided_by: uuid.UUID | None = Field(
        default=None, sa_column=Column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    )
    decided_at: datetime | None = Field(default=None, sa_column=_ts(nullable=True))
    reason: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    created_at: datetime = Field(default_factory=_now, sa_column=_ts())
