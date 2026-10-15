"""Chống spam trợ lý: hạn mức + chặn của chính mình (`agent.chat_limits`); superadmin xem / chặn / mở chặn
(`studio.*_chat*`). Cài đặt hạn mức mặc định + luật tự chặn đi qua `system.update_settings`."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import select

from app.agent.guard import service as guard
from app.agent.guard.models import AgentChatBlock
from app.agent.ops.chat import REASON
from app.agent.runtime import limits
from app.auth.models import User
from app.auth.policies import CHAT_KEYS, LimitSource
from app.core.errors import AppException
from app.core.operations.context import OpContext
from app.core.operations.pagination import Page, PageIn
from app.core.operations.spec import operation
from app.system.settings_store import get_system_settings

WINDOW_OF = dict(zip(CHAT_KEYS, ("minute", "hour", "day"), strict=True))


class UserRef(BaseModel):
    id: uuid.UUID
    email: str
    name: str


class BlockOut(BaseModel):
    id: uuid.UUID
    user: UserRef
    until: datetime | None  # None = tới khi superadmin mở
    reason: str
    source: str  # auto | manual
    created_by: str | None  # tên người chặn (chặn tay)
    created_at: datetime
    lifted_at: datetime | None
    lifted_by: str | None
    active: bool


class WindowOut(BaseModel):
    window: str  # minute | hour | day
    limit: int | None  # None = không giới hạn
    used: int
    source: LimitSource
    role: str | None = None


class ChatLimitsOut(BaseModel):
    exempt: bool  # superadmin
    windows: list[WindowOut]
    blocked: BlockOut | None


class ListBlocksIn(PageIn):
    active_only: bool = False


class BlockChatIn(BaseModel):
    user_id: uuid.UUID
    minutes: int | None = Field(default=None, ge=1, le=43_200)  # None = tới khi mở
    reason: str = Field(min_length=1, max_length=500)


class BlockIdIn(BaseModel):
    block_id: uuid.UUID


async def _blocks_out(session, rows: list[AgentChatBlock]) -> list[BlockOut]:
    ids = {r.user_id for r in rows} | {i for r in rows for i in (r.created_by, r.lifted_by) if i}
    users = {u.id: u for u in (await session.exec(select(User).where(User.id.in_(ids)))).all()} if ids else {}

    def name(uid: uuid.UUID | None) -> str | None:
        u = users.get(uid) if uid else None
        return (u.name or u.email) if u else None

    out = []
    for r in rows:
        u = users.get(r.user_id)
        ref = UserRef(id=r.user_id, email=u.email if u else "", name=(u.name or u.email) if u else "")
        out.append(
            BlockOut(
                id=r.id,
                user=ref,
                until=r.until,
                reason=r.reason,
                source=r.source,
                created_by=name(r.created_by),
                created_at=r.created_at,
                lifted_at=r.lifted_at,
                lifted_by=name(r.lifted_by),
                active=r.active(),
            )
        )
    return out


def _studio(name: str, title: str, description: str, effect: str = "write"):
    return operation(name, title=title, description=description, effect=effect, superadmin=True, agent_reason=REASON,
                     invalidates=(guard.BLOCKS_KEY,))  # fmt: skip


@operation(
    "agent.chat_limits",
    title="Hạn mức chat của tôi",
    description="Hạn mức tin nhắn / phút · giờ · ngày đang áp cho mình, số đã dùng, và chặn tạm (nếu có)",
    permission="agent.chat",
    agent_reason=REASON,
)
async def chat_limits(ctx: OpContext) -> ChatLimitsOut:
    me = await ctx.session.get(User, ctx.principal.user_id)
    if me is None:
        raise AppException(1004, status_code=401)
    eff = await limits.account_limits(ctx.session, me, await get_system_settings(ctx.session))
    used = await limits.account_used(ctx.redis, me.id, ctx.settings.APP_TIMEZONE)
    windows = [
        WindowOut(window=WINDOW_OF[k], limit=eff[k].value or None, used=n, source=eff[k].source, role=eff[k].role)
        for k, n in zip(CHAT_KEYS, used, strict=True)
    ]
    block = None if me.is_superadmin else await guard.active_block(ctx.session, me.id)
    blocked = (await _blocks_out(ctx.session, [block]))[0] if block else None
    return ChatLimitsOut(exempt=me.is_superadmin, windows=windows, blocked=blocked)


@_studio(
    "studio.list_chat_blocks",
    "Danh sách chặn trợ lý",
    "Superadmin: các lần chặn user khỏi trợ lý (tự động / tay), mới nhất trước; `active_only` = đang hiệu lực",
    effect="read",
)
async def list_chat_blocks(ctx: OpContext, inp: ListBlocksIn) -> Page[BlockOut]:
    base = guard.open_blocks() if inp.active_only else select(AgentChatBlock)
    total = (await ctx.session.exec(select(func.count()).select_from(base.subquery()))).one()
    stmt = base.order_by(AgentChatBlock.created_at.desc()).offset(inp.offset).limit(inp.limit)
    items = await _blocks_out(ctx.session, list((await ctx.session.exec(stmt)).all()))
    return Page[BlockOut](items=items, total=total, limit=inp.limit, offset=inp.offset)


@_studio(
    "studio.block_chat",
    "Chặn user khỏi trợ lý",
    "Superadmin: chặn một user dùng trợ lý trong N phút hoặc tới khi mở (không khoá tài khoản); lý do bắt buộc",
)
async def block_chat(ctx: OpContext, inp: BlockChatIn) -> BlockOut:
    user = await ctx.session.get(User, inp.user_id, with_for_update=True)
    if user is None:
        raise AppException(1001, status_code=404, detail="User not found")
    if user.is_superadmin:
        raise AppException(2204, status_code=409)
    block = await guard.block_manual(ctx, user.id, inp.minutes, inp.reason.strip())
    return (await _blocks_out(ctx.session, [block]))[0]


@_studio(
    "studio.unblock_chat", "Mở chặn trợ lý", "Superadmin: mở một lần chặn đang hiệu lực (đã hết hạn thì giữ nguyên)"
)
async def unblock_chat(ctx: OpContext, inp: BlockIdIn) -> BlockOut:
    block = await guard.lift(ctx, inp.block_id)
    return (await _blocks_out(ctx.session, [block]))[0]
