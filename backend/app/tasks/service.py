"""Luật Tasks dùng chung cho op, trợ lý và cron: đọc việc (404 khác tổ chức), người làm cùng tổ chức, khoảng hạn theo
múi giờ người dùng, dựng output kèm tên người."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_
from sqlmodel import select

from app.auth.models import User
from app.core.dates import zone
from app.core.errors import AppException
from app.tasks.models import OPEN_STATUSES, Task, TaskComment
from app.tasks.schemas import CommentOut, DueFilter, PersonRef, TaskOut

PRIORITY_RANK = {"urgent": 0, "high": 1, "normal": 2, "low": 3}


def now() -> datetime:
    return datetime.now(UTC)


async def load(session, task_id: uuid.UUID, *, lock: bool = False) -> Task:
    """Session đã scope theo tenant → việc của tổ chức khác coi như không có."""
    stmt = select(Task).where(Task.id == task_id)
    task = (await session.exec(stmt.with_for_update() if lock else stmt)).first()
    if task is None:
        raise AppException(10001, status_code=404)
    return task


async def check_assignee(session, user_id: uuid.UUID | None) -> None:
    if user_id is None:
        return
    found = (await session.exec(select(User.id).where(User.id == user_id, User.is_active.is_(True)))).first()
    if found is None:
        raise AppException(10002, status_code=422)


def display_name(user: User) -> str:
    return user.name or user.email.split("@", 1)[0]


async def people(session, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, PersonRef]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = (await session.exec(select(User).where(User.id.in_(wanted)))).all()
    return {u.id: PersonRef(id=u.id, name=display_name(u)) for u in rows}


async def user_zone(session, user_id: uuid.UUID):
    user = await session.get(User, user_id)
    return zone(user.timezone if user else None)


def due_window(due: DueFilter, tz, at: datetime) -> list:
    """Điều kiện SQL cho bộ lọc hạn, tính theo ngày của người dùng."""
    start = at.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    is_open = Task.status.in_(OPEN_STATUSES)
    if due == "none":
        return [Task.due_at.is_(None)]
    if due == "overdue":
        return [is_open, Task.due_at < at]
    if due == "today":
        return [Task.due_at >= start, Task.due_at < start + timedelta(days=1)]
    return [Task.due_at >= at, Task.due_at < start + timedelta(days=8)]  # 7 ngày tới (hết ngày thứ 7)


def search(q: str) -> list:
    like = f"%{q.strip()}%"
    return [or_(Task.title.ilike(like), Task.description.ilike(like))]


def is_overdue(task: Task, at: datetime) -> bool:
    return task.status in OPEN_STATUSES and task.due_at is not None and task.due_at < at


async def outs(session, tasks: Sequence[Task]) -> list[TaskOut]:
    names = await people(session, [i for t in tasks for i in (t.assignee_id, t.created_by)])
    counts: dict[uuid.UUID, int] = {}
    if tasks:
        stmt = (
            select(TaskComment.task_id, func.count())
            .where(TaskComment.task_id.in_([t.id for t in tasks]))
            .group_by(TaskComment.task_id)
        )
        counts = dict((await session.exec(stmt)).all())
    at = now()
    return [
        TaskOut(
            **t.model_dump(exclude={"assignee_id", "created_by", "agent_run_id", "tenant_id"}),
            overdue=is_overdue(t, at),
            assignee=names.get(t.assignee_id) if t.assignee_id else None,
            created_by=names.get(t.created_by) if t.created_by else None,
            comment_count=counts.get(t.id, 0),
        )
        for t in tasks
    ]


async def comment_outs(session, rows: Sequence[TaskComment]) -> list[CommentOut]:
    names = await people(session, [c.author_id for c in rows])
    return [
        CommentOut(
            id=c.id,
            task_id=c.task_id,
            author=names.get(c.author_id) if c.author_id else None,
            body=c.body,
            source=c.source,
            created_at=c.created_at,
        )
        for c in rows
    ]
