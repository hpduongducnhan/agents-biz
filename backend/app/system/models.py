"""Bảng `system_settings` — đúng một dòng (id=1); `data` jsonb chỉ chứa khoá đã được cấu hình."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, SmallInteger, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(UTC)


class SystemSettingsRow(SQLModel, table=True):
    __tablename__ = "system_settings"
    __table_args__ = (CheckConstraint("id = 1", name="ck_system_settings_single_row"),)

    id: int = Field(default=1, sa_column=Column(SmallInteger, primary_key=True, autoincrement=False))
    data: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    )
    updated_by: uuid.UUID | None = Field(
        default=None, sa_column=Column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    )
    updated_at: datetime = Field(
        default_factory=_now, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
