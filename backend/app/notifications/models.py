"""Bảng `notifications` — inbox: một dòng / người nhận; `push_subscriptions` + `push_keys` — Web Push
(migration `0003_notifications_system`)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(UTC)


class Notification(SQLModel, table=True):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_inbox", "user_id", "read_at", "created_at"),
        Index("ix_notifications_created_at", "created_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, sa_column=Column(Uuid, primary_key=True))
    user_id: uuid.UUID = Field(sa_column=Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False))
    kind: str = Field(sa_column=Column(String(64), nullable=False))
    title: str = Field(default="", sa_column=Column(String(300), nullable=False, server_default=""))
    body: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))
    params: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    )
    action: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    read_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    created_at: datetime = Field(
        default_factory=_now, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )


class PushSubscription(SQLModel, table=True):
    """Một trình duyệt / máy đã bật thông báo đẩy; `endpoint` duy nhất — máy đổi tài khoản thì gán lại người dùng."""

    __tablename__ = "push_subscriptions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, sa_column=Column(Uuid, primary_key=True))
    user_id: uuid.UUID = Field(
        sa_column=Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    )
    endpoint: str = Field(sa_column=Column(Text, nullable=False, unique=True))
    p256dh: str = Field(sa_column=Column(String(200), nullable=False))
    auth: str = Field(sa_column=Column(String(100), nullable=False))
    user_agent: str = Field(default="", sa_column=Column(String(300), nullable=False, server_default=""))
    failures: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    created_at: datetime = Field(
        default_factory=_now, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    last_ok_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))


class PushKey(SQLModel, table=True):
    """Khoá VAPID của máy chủ — một dòng (`id = 1`), khoá riêng mã hoá Fernet bằng `CREDENTIAL_KEYS`."""

    __tablename__ = "push_keys"

    id: int = Field(default=1, sa_column=Column(SmallInteger, primary_key=True, autoincrement=False))
    public_key: str = Field(sa_column=Column(String(100), nullable=False))
    private_key_enc: str = Field(sa_column=Column(Text, nullable=False))
    key_id: str = Field(sa_column=Column(String(16), nullable=False))
    created_at: datetime = Field(
        default_factory=_now, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
