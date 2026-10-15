"""Bảng `credentials` (migration `0004_agent_config`) — chỉ giữ bản mã + dấu khoá + gợi ý che.
`kind`: `api_key` (key provider LLM) | `google_service_account` (JSON service account cho tích hợp Google)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, String, Text, text
from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(UTC)


def _ts(*, nullable: bool = False, onupdate: bool = False) -> Column:
    return Column(
        DateTime(timezone=True),
        nullable=nullable,
        server_default=None if nullable else text("now()"),
        onupdate=_now if onupdate else None,
    )


class Credential(SQLModel, table=True):
    __tablename__ = "credentials"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'disabled')", name="ck_credentials_status"),
        CheckConstraint("weight BETWEEN 1 AND 100", name="ck_credentials_weight"),
        CheckConstraint("kind IN ('api_key', 'google_service_account')", name="ck_credentials_kind"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=100, unique=True)
    kind: str = Field(default="api_key", sa_column=Column(String(32), nullable=False, server_default="api_key"))
    provider_id: uuid.UUID | None = Field(
        default=None, sa_column=Column(ForeignKey("agent_providers.id", ondelete="SET NULL"), nullable=True)
    )
    secret_ciphertext: str = Field(sa_column=Column(Text, nullable=False))
    key_id: str = Field(max_length=8)
    masked_hint: str = Field(max_length=32)
    weight: int = Field(default=1)
    status: str = Field(default="active", max_length=16)
    disabled_reason: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_by: uuid.UUID | None = Field(
        default=None, sa_column=Column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    )
    created_at: datetime = Field(default_factory=_now, sa_column=_ts())
    updated_at: datetime = Field(default_factory=_now, sa_column=_ts(onupdate=True))
