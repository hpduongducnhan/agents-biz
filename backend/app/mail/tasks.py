"""Task `mail.send`: gửi một thư qua transport đang cấu hình. Idempotent theo `MailMessage.id` (khoá Redis 7 ngày) —
broker giao lại thì không gửi đôi (B11). Lỗi transport → ném lại để taskiq thử lại (retry 2)."""

from __future__ import annotations

from app.core.connections.registry import get_connections
from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.messaging.tasks import task
from app.core.rkeys import rkey
from app.core.settings import active_settings
from app.mail.schemas import MailMessage
from app.mail.transport import get_transport

logger = get_logger(__name__)
SENT_TTL = 7 * 86_400


@task("mail.send", retry=2, timeout=60)
async def send_mail(raw: dict) -> dict:
    msg = MailMessage.model_validate(raw)
    redis = get_connections().redis
    key = rkey("mail", "sent", msg.id)
    if await redis.ro.exists(key):
        logger.info("bỏ thư %s: đã gửi", msg.id, extra={"loc": "mail0005"})
        return {"id": msg.id, "sent": False}
    transport = get_transport(active_settings())
    try:
        await transport.send(msg)
    except Exception as exc:
        logger.warning("gửi thư %s lỗi (%s): %s", msg.id, transport.name, exc, extra={"loc": "mail0501"})
        raise AppException(8002, status_code=502, detail=str(exc)) from exc
    await redis.rw.set(key, "1", ex=SENT_TTL)
    return {"id": msg.id, "sent": True, "transport": transport.name}
