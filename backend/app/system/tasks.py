"""Việc nền của miền system: nhịp tim pipeline — scheduler (cron, khoá leader) → worker → consumer."""

from __future__ import annotations

from app.core.connections.registry import get_connections
from app.core.messaging.streams import publish
from app.core.messaging.tasks import task
from app.system import heartbeat


@task("system.ping", every=lambda s: s.HEARTBEAT_INTERVAL, retry=0)
async def ping() -> None:
    """Worker nhận nhịp scheduler kick → ghi nhịp `work` rồi chuyển tiếp cho consumer."""
    await heartbeat.beat(get_connections().redis.rw, "work")
    await publish("system.ping", {"from": "work"})
