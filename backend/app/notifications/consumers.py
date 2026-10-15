"""Handler messaging của miền notifications: event client `notifications.mark_read` (socket)."""

from __future__ import annotations

from app.core.messaging.realtime import WsContext, on_ws
from app.core.operations.runner import run_operation
from app.notifications.ops import MarkReadIn


@on_ws("notifications.mark_read")
async def ws_mark_read(ctx: WsContext, data: MarkReadIn) -> None:
    """Đánh dấu đã đọc qua socket (thao tác nhẹ — R18): đi đúng runner như REST."""
    await run_operation("notifications.mark_read", ctx.principal, data.model_dump(mode="json"), source="ws")
