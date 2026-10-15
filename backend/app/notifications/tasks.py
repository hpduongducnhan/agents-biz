"""Task nền của thông báo: dọn thông báo cũ hơn 90 ngày — scheduler bắn mỗi ngày lúc 03:15."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from app.core.connections.registry import get_connections
from app.core.logging import get_logger
from app.core.messaging.tasks import task
from app.notifications.models import Notification

logger = get_logger(__name__)
RETENTION_DAYS = 90


async def delete_older_than(days: int) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    async with get_connections().postgres.rw() as session:
        result = await session.exec(delete(Notification).where(Notification.created_at < cutoff))
    removed = result.rowcount or 0
    logger.info("dọn %d thông báo cũ hơn %d ngày", removed, days, extra={"loc": "ntf0001"})
    return removed


@task("notifications.cleanup", cron="15 3 * * *")
async def cleanup() -> int:
    return await delete_older_than(RETENTION_DAYS)
