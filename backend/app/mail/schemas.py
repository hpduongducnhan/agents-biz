"""Dữ liệu một thư — đi qua task `mail.send` (JSON) nên chỉ gồm kiểu thuần."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MailMessage(BaseModel):
    id: str = Field(max_length=64)  # khoá idempotency của lần gửi
    to: str = Field(max_length=320)
    subject: str = Field(max_length=300)
    text: str
    html: str | None = None


class OutboxItem(MailMessage):
    """Thư transport `console` đã "gửi" — chỉ để xem ở trang `/sa/mail` khi dev / stack thử."""

    sent_at: datetime


class OutboxOut(BaseModel):
    enabled: bool  # False khi transport khác `console`
    items: list[OutboxItem] = []
