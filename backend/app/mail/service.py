"""Xếp thư vào hàng gửi: dựng nội dung theo mẫu + ngôn ngữ của người nhận, rồi `mail.send` chạy nền (lane `default`).
Trong `@operation` gọi qua `ctx.after_commit(...)` — thư chỉ đi khi thao tác đã commit."""

from __future__ import annotations

import uuid
from typing import Any

from app.core.logging import get_logger
from app.mail.render import render
from app.mail.schemas import MailMessage
from app.mail.tasks import send_mail

logger = get_logger(__name__)


def build(to: str, template: str, locale: str | None, **ctx: Any) -> MailMessage:
    subject, text, html = render(template, locale, **ctx)
    return MailMessage(id=uuid.uuid4().hex, to=to, subject=subject, text=text, html=html)


async def queue_mail(to: str, template: str, locale: str | None, **ctx: Any) -> str:
    msg = build(to, template, locale, **ctx)
    await send_mail.kiq(msg.model_dump())
    logger.info("xếp thư %s (%s) tới %s", msg.id, template, to, extra={"loc": "mail0004"})
    return msg.id
