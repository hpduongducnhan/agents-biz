"""Cron nhắc hạn công việc (mỗi 15 phút): việc đang mở sắp tới hạn (≤ 24 giờ) hoặc đã quá hạn → thông báo người làm
(chưa giao thì người tạo). Mỗi mốc (sắp / quá) của một hạn chỉ nhắc một lần — khoá Redis theo tenant + việc + hạn."""

from __future__ import annotations

from datetime import timedelta

from sqlmodel import select

from app.core.connections.registry import get_connections
from app.core.logging import get_logger
from app.core.messaging.tasks import task
from app.core.rkeys import rkey
from app.notifications.service import notify_users
from app.tasks import notify, service
from app.tasks.models import OPEN_STATUSES, Task

logger = get_logger(__name__)
SOON = timedelta(hours=24)
MARK_TTL = int(timedelta(days=14).total_seconds())
KINDS = {"soon": notify.DUE_SOON, "overdue": notify.OVERDUE}
TITLES = {"soon": "Sắp tới hạn: {title}", "overdue": "Quá hạn: {title}"}


def remind_key(t: Task, mark: str) -> str:
    return rkey("tasks", str(t.tenant_id), "remind", str(t.id), mark, t.due_at.isoformat() if t.due_at else "-")


async def remind_due(*, limit: int = 1000) -> dict[str, int]:
    at = service.now()
    conns = get_connections()
    # việc nền đọc mọi tổ chức (session worker không scope) — ngoại lệ duy nhất của module (B14)
    async with conns.postgres.ro() as session:
        stmt = (
            select(Task)
            .where(Task.status.in_(OPEN_STATUSES), Task.due_at.is_not(None), Task.due_at < at + SOON)
            .order_by(Task.due_at)
            .limit(limit)
        )
        rows = (await session.exec(stmt)).all()
    sent = 0
    for t in rows:
        target = t.assignee_id or t.created_by
        mark = "overdue" if t.due_at < at else "soon"
        if target is None or not await conns.redis.rw.set(remind_key(t, mark), "1", nx=True, ex=MARK_TTL):
            continue
        await notify_users(
            [target],
            KINDS[mark],
            TITLES[mark].format(title=t.title),
            params={"title": t.title, "due_at": t.due_at.isoformat()},
            action=notify.link(t.id),
        )
        sent += 1
    logger.info("nhắc hạn công việc: %d việc tới / quá hạn, gửi %d", len(rows), sent, extra={"loc": "tsk0001"})
    return {"checked": len(rows), "sent": sent}


@task("tasks.due_reminders", cron="*/15 * * * *")
async def due_reminders() -> dict[str, int]:
    return await remind_due()
