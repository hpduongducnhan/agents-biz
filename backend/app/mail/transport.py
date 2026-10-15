"""Transport gửi thư — một choke-point (R12): `get_transport(settings)` chọn theo `MAIL_TRANSPORT`.

- `console` (mặc định, dev / test / stack thử): ghi log `mail0001` + giữ ≤ `MAIL_OUTBOX_MAX` thư gần nhất ở Redis
  `bw:mail:outbox` (TTL 1 ngày) cho trang `/sa/mail`. Chạy ở prod vẫn được nhưng không ai nhận thư.
- `smtp`: `aiosmtplib` (STARTTLS hoặc TLS ngầm), mọi nhà có SMTP (Gmail app password, Brevo, SES, Resend SMTP…).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Protocol

import aiosmtplib

from app.core.connections.registry import get_connections
from app.core.logging import get_logger
from app.core.rkeys import rkey
from app.core.settings import Settings
from app.mail.schemas import MailMessage, OutboxItem

logger = get_logger(__name__)
OUTBOX_KEY = rkey("mail", "outbox")
OUTBOX_TTL = 86_400
_warned: dict[str, bool] = {"console": False}


class MailTransport(Protocol):
    name: str

    async def send(self, msg: MailMessage) -> None: ...


class ConsoleTransport:
    name = "console"

    def __init__(self, settings: Settings) -> None:
        self._max = settings.MAIL_OUTBOX_MAX

    async def send(self, msg: MailMessage) -> None:
        logger.info("mail (console) tới %s: %s", msg.to, msg.subject, extra={"loc": "mail0001"})
        item = OutboxItem(**msg.model_dump(), sent_at=datetime.now(UTC))
        rw = get_connections().redis.rw
        await rw.lpush(OUTBOX_KEY, item.model_dump_json())
        await rw.ltrim(OUTBOX_KEY, 0, self._max - 1)
        await rw.expire(OUTBOX_KEY, OUTBOX_TTL)


class SmtpTransport:
    name = "smtp"

    def __init__(self, settings: Settings) -> None:
        self._s = settings

    def build(self, msg: MailMessage) -> EmailMessage:
        em = EmailMessage()
        em["From"] = self._s.MAIL_FROM
        em["To"] = msg.to
        em["Subject"] = msg.subject
        em["Message-ID"] = f"<{msg.id}@{self._s.SERVICE_PATH}>"
        em.set_content(msg.text)
        if msg.html:
            em.add_alternative(msg.html, subtype="html")
        return em

    async def send(self, msg: MailMessage) -> None:
        s = self._s
        await aiosmtplib.send(
            self.build(msg),
            hostname=s.SMTP_HOST,
            port=s.SMTP_PORT,
            username=s.SMTP_USERNAME or None,
            password=s.SMTP_PASSWORD or None,
            start_tls=s.SMTP_STARTTLS and not s.SMTP_SSL,
            use_tls=s.SMTP_SSL,
            timeout=s.SMTP_TIMEOUT,
        )
        logger.info("mail (smtp) tới %s: %s", msg.to, msg.subject, extra={"loc": "mail0002"})


def get_transport(settings: Settings) -> MailTransport:
    if settings.MAIL_TRANSPORT == "smtp" and settings.SMTP_HOST:
        return SmtpTransport(settings)
    if not _warned["console"]:
        _warned["console"] = True
        reason = "MAIL_TRANSPORT=smtp nhưng thiếu SMTP_HOST" if settings.MAIL_TRANSPORT == "smtp" else "mặc định"
        logger.warning(
            "mail đi transport console (%s) — thư không tới người nhận; DEFAULTS_APPLIED=[mail_transport]",
            reason,
            extra={"loc": "mail0003"},
        )
    return ConsoleTransport(settings)


async def read_outbox(limit: int = 50) -> list[OutboxItem]:
    rows = await get_connections().redis.ro.lrange(OUTBOX_KEY, 0, limit - 1)
    return [OutboxItem.model_validate(json.loads(r)) for r in rows]
