"""notifications.* — inbox của chính người đang đăng nhập. Web, socket và agent đi cùng runner;
thao tác ghi làm mới query `notifications` ở các tab khác (R18)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from functools import partial

from pydantic import BaseModel, Field
from sqlalchemy import func, update
from sqlmodel import select

from app.auth.users import user_by_email
from app.core.errors import AppException
from app.core.operations.context import OpContext
from app.core.operations.pagination import Page, PageIn
from app.core.operations.spec import operation
from app.notifications import push_ops as push_ops  # noqa: F401 — đăng ký op push.*
from app.notifications import service
from app.notifications.models import Notification
from app.notifications.schemas import NotificationOut

INVALIDATES = ("notifications",)


class ListIn(PageIn):
    unread_only: bool = False


class MarkReadIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


class UnreadCountOut(BaseModel):
    count: int


class UpdatedOut(BaseModel):
    updated: int


class SendTestIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=2000)


class SendTestOut(BaseModel):
    notification_id: uuid.UUID


def _me(ctx: OpContext) -> uuid.UUID:
    return ctx.principal.user_id  # runner đã chặn chưa đăng nhập (1004) — không operation nào ở đây public


@operation(
    name="notifications.list",
    title="Danh sách thông báo",
    description="Thông báo của tôi, mới nhất trước; lọc chưa đọc; phân trang",
    agent=True,
    toolset="lookup",
    agent_hint="Dùng khi người dùng hỏi có thông báo / việc gì mới; unread_only=true để chỉ lấy tin chưa đọc.",
)
async def list_notifications(ctx: OpContext, inp: ListIn) -> Page[NotificationOut]:
    where = [Notification.user_id == _me(ctx)]
    if inp.unread_only:
        where.append(Notification.read_at.is_(None))
    total = (await ctx.session.exec(select(func.count()).select_from(Notification).where(*where))).one()
    stmt = (
        select(Notification)
        .where(*where)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .offset(inp.offset)
        .limit(inp.limit)
    )
    rows = (await ctx.session.exec(stmt)).all()
    return Page[NotificationOut](
        items=[service.to_out(r) for r in rows], total=total, limit=inp.limit, offset=inp.offset
    )


@operation(
    name="notifications.unread_count",
    title="Số thông báo chưa đọc",
    description="Đếm thông báo chưa đọc của tôi (badge)",
    agent=True,
    toolset="lookup",
    agent_hint="Trả số thông báo chưa đọc của người đang chat.",
)
async def unread_count(ctx: OpContext, inp: None) -> UnreadCountOut:
    stmt = (
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == _me(ctx), Notification.read_at.is_(None))
    )
    return UnreadCountOut(count=(await ctx.session.exec(stmt)).one())


@operation(
    name="notifications.mark_read",
    title="Đánh dấu đã đọc",
    description="Đánh dấu các thông báo của tôi là đã đọc (id của người khác bị bỏ qua)",
    effect="write",
    agent=True,
    toolset="lookup",
    agent_hint="Gọi sau khi đã đọc lại thông báo cho người dùng; dùng đúng id lấy từ notifications.list.",
    invalidates=INVALIDATES,
)
async def mark_read(ctx: OpContext, inp: MarkReadIn) -> UpdatedOut:
    stmt = (
        update(Notification)
        .where(Notification.user_id == _me(ctx), Notification.id.in_(inp.ids), Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    return UpdatedOut(updated=(await ctx.session.exec(stmt)).rowcount or 0)


@operation(
    name="notifications.mark_all_read",
    title="Đọc hết",
    description="Đánh dấu mọi thông báo của tôi là đã đọc",
    effect="write",
    agent=True,
    toolset="lookup",
    agent_hint="Chỉ gọi khi người dùng nói rõ muốn đánh dấu tất cả là đã đọc.",
    invalidates=INVALIDATES,
)
async def mark_all_read(ctx: OpContext, inp: None) -> UpdatedOut:
    stmt = (
        update(Notification)
        .where(Notification.user_id == _me(ctx), Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    return UpdatedOut(updated=(await ctx.session.exec(stmt)).rowcount or 0)


@operation(
    name="notifications.send_test",
    title="Gửi thông báo thử",
    description="Superadmin: gửi một thông báo `test` tới user theo email — kiểm inbox + realtime",
    effect="write",
    superadmin=True,
    agent=False,
    agent_reason="công cụ kiểm thử của superadmin",
    invalidates=INVALIDATES,
)
async def send_test(ctx: OpContext, inp: SendTestIn) -> SendTestOut:
    user = await user_by_email(ctx.session, inp.email)
    if user is None:
        raise AppException(1001, status_code=404, detail="Không có user với email này")
    # ghi trong transaction của op (biết id ngay) thay vì ctx.notify (chỉ xếp hàng, không trả id)
    row = await service.stage(ctx.session, user.id, "test", inp.title, inp.body)
    ctx.after_commit(partial(service.push, [row]))
    return SendTestOut(notification_id=row.id)


service.install()
