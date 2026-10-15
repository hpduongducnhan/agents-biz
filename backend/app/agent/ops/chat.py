"""agent.* — chat: danh sách agent mở cho mình, gửi tin (tạo run `queued` rồi kick sau commit), phiên của mình."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import delete, func
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.agent import tasks
from app.agent.chat import service as chat
from app.agent.chat.models import OPEN_STATUSES, AgentApproval, AgentMessage, AgentRun, AgentSession
from app.agent.config import registry
from app.agent.config.models import Agent
from app.agent.config.seed import ASSISTANT
from app.agent.guard import service as guard
from app.agent.runtime import limits
from app.agent.runtime.tools import HANDOFF, tool_name
from app.auth.models import User
from app.auth.rbac import role_names
from app.core.errors import AppException
from app.core.operations.context import OpContext
from app.core.operations.pagination import Page, PageIn
from app.core.operations.registry import all_specs
from app.core.operations.spec import operation
from app.system.settings_store import get_system_settings
from app.tenants.models import Tenant
from app.tenants.policies import agent_enabled

REASON = "giao diện chat — agent không tự gọi"
KEYS = ("agent.sessions", "agent.session")
MAX_MESSAGES = 200
HANDOFF_TITLE = "Chuyển chuyên gia"
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]


class AgentCard(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str
    starters: list[str]


class SendIn(BaseModel):
    session_id: uuid.UUID | None = None
    agent_id: uuid.UUID | None = None
    content: Text
    client_msg_id: str = Field(min_length=1, max_length=64)
    auto: bool = Field(
        default=False, description="true: server chọn phiên đang mở theo `chat_session_idle_min` (bỏ qua session_id)"
    )


class SendOut(BaseModel):
    session_id: uuid.UUID
    run_id: uuid.UUID
    message_id: uuid.UUID


class SessionOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    entry_agent_id: uuid.UUID
    last_agent_id: uuid.UUID | None
    open_run_status: str | None = None
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    id: uuid.UUID
    seq: int
    role: str
    agent_id: uuid.UUID | None
    content: dict[str, Any]
    run_id: uuid.UUID | None
    created_at: datetime


class RunOut(BaseModel):
    id: uuid.UUID
    status: str
    error_code: int | None
    error: str | None
    tokens_in: int
    tokens_out: int
    created_at: datetime
    ended_at: datetime | None


class ApprovalOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    tool_call_id: str
    operation: str
    args: dict[str, Any]
    status: str
    reason: str | None
    expires_at: datetime


class AgentRef(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    kind: str


class SessionDetail(BaseModel):
    session: SessionOut
    messages: list[MessageOut]
    open_run: RunOut | None
    approvals: list[ApprovalOut]
    last_run: RunOut | None
    agents: list[AgentRef] = []  # agent xuất hiện trong phiên (entry + chuyên gia của từng tin)
    tool_titles: dict[str, str] = {}  # tên tool trong tin → `title` op (chấm tiến trình)


class CurrentIn(BaseModel):
    agent_id: uuid.UUID | None = None


class CurrentOut(BaseModel):
    current: SessionOut | None
    previous: SessionOut | None
    idle_min: int
    expires_at: datetime | None


class ListSessionsIn(PageIn):
    user_id: uuid.UUID | None = None


class SessionIdIn(BaseModel):
    session_id: uuid.UUID


class RenameIn(SessionIdIn):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


def visible(agent: Agent, roles: list[str], sup: bool) -> bool:
    if not agent.is_active:
        return False
    return sup or agent.visible_to == "all" or bool(set(agent.visible_roles or []) & set(roles))


def session_out(s: AgentSession, open_status: str | None = None) -> SessionOut:
    return SessionOut(**s.model_dump(), open_run_status=open_status)


def run_out(r: AgentRun) -> RunOut:
    return RunOut(**r.model_dump())


async def tenant_agent_on(ctx: OpContext) -> bool:
    """Tenant của người gọi được dùng trợ lý (`tenants.policies.agent_enabled`); superadmin luôn được."""
    if ctx.principal.sup or ctx.tenant_id is None:
        return True
    return agent_enabled(await ctx.session.get(Tenant, ctx.tenant_id))


async def require_agent_on(ctx: OpContext) -> None:
    if not await tenant_agent_on(ctx):
        raise AppException(6023, status_code=403)


async def own_session(ctx: OpContext, session_id: uuid.UUID, *, lock: bool = False) -> AgentSession:
    s = await chat.lock_session(ctx.session, session_id) if lock else await ctx.session.get(AgentSession, session_id)
    if s is None or (s.user_id != ctx.principal.user_id and not ctx.principal.sup):
        raise AppException(6004, status_code=404)
    return s


@operation(
    "agent.list_agents",
    title="Agent mở cho tôi",
    description="Agent đang bật mà tôi được chat (theo role); tổ chức tắt trợ lý → rỗng",
    permission="agent.chat",
    agent_reason=REASON,
)
async def list_agents(ctx: OpContext) -> list[AgentCard]:
    if not await tenant_agent_on(ctx):
        return []
    roles = await role_names(ctx.session, ctx.principal.user_id)
    rows = (await ctx.session.exec(select(Agent).order_by(Agent.slug != ASSISTANT, Agent.name))).all()
    return [AgentCard(**a.model_dump()) for a in rows if visible(a, roles, ctx.principal.sup)]


async def _agent_for(ctx: OpContext, agent_id: uuid.UUID | None) -> Agent:
    stmt = select(Agent).where(Agent.id == agent_id) if agent_id else select(Agent).where(Agent.slug == ASSISTANT)
    agent = (await ctx.session.exec(stmt)).first()
    roles = await role_names(ctx.session, ctx.principal.user_id)
    if agent is None or not visible(agent, roles, ctx.principal.sup):
        raise AppException(6003, status_code=404)
    return agent


async def _auto_session(ctx: OpContext, agent_id: uuid.UUID | None) -> AgentSession | None:
    """Phiên đang mở của agent được chọn — đã khoá dòng; quá hạn / chưa có → None (send tạo mới)."""
    agent = await _agent_for(ctx, agent_id)
    cfg = await get_system_settings(ctx.session)
    current, _ = await chat.current_session(ctx.session, ctx.principal.user_id, agent.id, cfg.chat_session_idle_min)
    return await chat.lock_session(ctx.session, current.id) if current is not None else None


async def _guard_and_count(ctx: OpContext, agent: Agent) -> limits.Counted | None:
    """Đang bị chặn → 6022; đếm hạn mức agent + tài khoản; chạm trần → một lần vi phạm, đủ N lần → tự chặn."""
    me, sup = ctx.principal.user_id, ctx.principal.sup
    if not sup and (block := await guard.active_block(ctx.session, me)) is not None:
        raise guard.blocked_error(block)
    spec = await registry.load(ctx.session, ctx.redis, agent.id)
    lim = await limits.effective(ctx.session, agent.id, me, spec.limits if spec else None)
    cfg = await get_system_settings(ctx.session)
    account = (0, 0, 0) if sup else limits.account_caps(await limits.account_limits(ctx.session, await _me(ctx), cfg))
    try:
        return await limits.check_and_count(
            ctx.redis, agent_id=agent.id, user_id=me, limits=lim, tz=ctx.settings.APP_TIMEZONE, exempt=sup,
            account=account,
        )  # fmt: skip
    except AppException as exc:
        if exc.code in (6001, 6002) and not sup and (block := await guard.strike(ctx.redis, me, cfg)) is not None:
            raise guard.blocked_error(block) from exc
        raise


async def _me(ctx: OpContext) -> User:
    user = await ctx.session.get(User, ctx.principal.user_id)
    if user is None:
        raise AppException(1004, status_code=401)
    return user


@operation(
    "agent.send",
    title="Gửi tin nhắn cho agent",
    description="Ghi tin nhắn + lượt chạy `queued`, trả `run_id` ngay; kết quả tới qua socket (agent:*); "
    "tổ chức tắt trợ lý → 6023",
    effect="write",
    permission="agent.chat",
    agent_reason=REASON,
    invalidates=(*KEYS, guard.LIMITS_KEY),
)
async def send(ctx: OpContext, inp: SendIn) -> SendOut:
    await require_agent_on(ctx)
    me = ctx.principal.user_id
    chat_row = await own_session(ctx, inp.session_id, lock=True) if inp.session_id and not inp.auto else None
    if inp.auto:
        chat_row = await _auto_session(ctx, inp.agent_id)
    if chat_row is not None:
        stmt = select(AgentMessage).where(
            AgentMessage.session_id == chat_row.id, AgentMessage.client_msg_id == inp.client_msg_id
        )
        dup = (await ctx.session.exec(stmt)).first()
        if dup is not None and dup.run_id is not None:  # gửi lại (mạng chập) → trả lượt cũ
            return SendOut(session_id=chat_row.id, run_id=dup.run_id, message_id=dup.id)
    agent = await _agent_for(ctx, chat_row.entry_agent_id if chat_row else inp.agent_id)
    counted = await _guard_and_count(ctx, agent)
    try:
        if chat_row is None:
            chat_row = AgentSession(user_id=me, entry_agent_id=agent.id, title=chat.title_of(inp.content))
            ctx.session.add(chat_row)
            await ctx.session.flush()
        elif await chat.open_run(ctx.session, chat_row.id) is not None:
            raise AppException(6005, status_code=409)
        run = AgentRun(session_id=chat_row.id, user_id=me, entry_agent_id=agent.id)
        ctx.session.add(run)
        await ctx.session.flush()
        item = {"role": "user", "content": {"text": inp.content}, "client_msg_id": inp.client_msg_id}
        (msg,) = await chat.add_messages(ctx.session, chat_row, run.id, None, [item])
    except IntegrityError as exc:
        await limits.refund(ctx.redis, counted)
        raise AppException(6005, status_code=409) from exc
    except Exception:
        await limits.refund(ctx.redis, counted)
        raise
    run_id = str(run.id)

    async def kick() -> None:
        await tasks.run_turn.kiq(run_id)

    ctx.after_commit(kick)
    ctx.invalidate(KEYS, users=[me])
    return SendOut(session_id=chat_row.id, run_id=run.id, message_id=msg.id)


@operation(
    "agent.list_sessions",
    title="Phiên chat của tôi",
    description="Mới nhất trước; superadmin xem phiên của user khác bằng `user_id`",
    permission="agent.chat",
    agent_reason=REASON,
)
async def list_sessions(ctx: OpContext, inp: ListSessionsIn) -> Page[SessionOut]:
    owner = inp.user_id if inp.user_id and ctx.principal.sup else ctx.principal.user_id
    base = select(AgentSession).where(AgentSession.user_id == owner)
    total = (await ctx.session.exec(select(func.count()).select_from(base.subquery()))).one()
    rows = (
        await ctx.session.exec(base.order_by(AgentSession.updated_at.desc()).limit(inp.limit).offset(inp.offset))
    ).all()
    ids = [r.id for r in rows]
    open_runs = {}
    if ids:
        stmt = select(AgentRun.session_id, AgentRun.status).where(
            AgentRun.session_id.in_(ids), AgentRun.status.in_(OPEN_STATUSES)
        )
        open_runs = dict((await ctx.session.exec(stmt)).all())
    items = [session_out(r, open_runs.get(r.id)) for r in rows]
    return Page[SessionOut](items=items, total=total, limit=inp.limit, offset=inp.offset)


@operation(
    "agent.get_session",
    title="Xem phiên chat",
    description=f"Tin nhắn (≤ {MAX_MESSAGES} gần nhất), lượt đang mở, yêu cầu duyệt đang chờ",
    permission="agent.chat",
    agent_reason=REASON,
)
async def get_session(ctx: OpContext, inp: SessionIdIn) -> SessionDetail:
    s = await own_session(ctx, inp.session_id)
    stmt = select(AgentMessage).where(AgentMessage.session_id == s.id).order_by(AgentMessage.seq.desc())
    messages = list(reversed((await ctx.session.exec(stmt.limit(MAX_MESSAGES))).all()))
    open_run = await chat.open_run(ctx.session, s.id)
    last = (
        await ctx.session.exec(
            select(AgentRun).where(AgentRun.session_id == s.id).order_by(AgentRun.created_at.desc()).limit(1)
        )
    ).first()
    pending = []
    if open_run is not None:
        stmt = select(AgentApproval).where(AgentApproval.run_id == open_run.id, AgentApproval.status == "pending")
        pending = [ApprovalOut(**a.model_dump()) for a in (await ctx.session.exec(stmt)).all()]
    used = {c.get("name") for m in messages if m.role == "assistant" for c in (m.content or {}).get("tool_calls") or []}
    ids = {s.entry_agent_id} | {m.agent_id for m in messages if m.agent_id}
    agents = (await ctx.session.exec(select(Agent).where(Agent.id.in_(ids)))).all()
    return SessionDetail(
        session=session_out(s, open_run.status if open_run else None),
        messages=[MessageOut(**m.model_dump()) for m in messages],
        open_run=run_out(open_run) if open_run else None,
        approvals=pending,
        last_run=run_out(last) if last else None,
        agents=[AgentRef(id=a.id, slug=a.slug, name=a.name, kind=a.kind) for a in agents],
        tool_titles=_tool_titles(used),
    )


def _tool_titles(names: set[str | None]) -> dict[str, str]:
    titles = {tool_name(spec.name): spec.title for spec in all_specs()}
    return {n: titles.get(n, HANDOFF_TITLE if n == HANDOFF else n) for n in names if n}


@operation(
    "agent.current_session",
    title="Phiên chat đang mở",
    description="Phiên đang mở (tin cuối trong `chat_session_idle_min` phút hoặc còn lượt chạy) + phiên ngay trước",
    permission="agent.chat",
    agent_reason=REASON,
)
async def current_session(ctx: OpContext, inp: CurrentIn) -> CurrentOut:
    agent = await _agent_for(ctx, inp.agent_id)
    idle = (await get_system_settings(ctx.session)).chat_session_idle_min
    current, previous = await chat.current_session(ctx.session, ctx.principal.user_id, agent.id, idle)
    ids = [x.id for x in (current, previous) if x is not None]
    opened = {}
    if ids:
        stmt = select(AgentRun.session_id, AgentRun.status).where(
            AgentRun.session_id.in_(ids), AgentRun.status.in_(OPEN_STATUSES)
        )
        opened = dict((await ctx.session.exec(stmt)).all())
    return CurrentOut(
        current=session_out(current, opened.get(current.id)) if current else None,
        previous=session_out(previous, opened.get(previous.id)) if previous else None,
        idle_min=idle,
        expires_at=current.updated_at + timedelta(minutes=idle) if current else None,
    )


@operation(
    "agent.rename_session",
    title="Đổi tên phiên chat",
    effect="write",
    permission="agent.chat",
    agent_reason=REASON,
    invalidates=KEYS,
)
async def rename_session(ctx: OpContext, inp: RenameIn) -> SessionOut:
    s = await own_session(ctx, inp.session_id, lock=True)
    s.title = inp.title
    ctx.session.add(s)
    await ctx.session.flush()
    ctx.invalidate(KEYS, users=[s.user_id])
    return session_out(s)


@operation(
    "agent.delete_session",
    title="Xoá phiên chat",
    description="Xoá phiên + tin nhắn; phiên đang có lượt chạy → 6005",
    effect="destructive",
    permission="agent.chat",
    agent_reason=REASON,
    invalidates=KEYS,
)
async def delete_session(ctx: OpContext, inp: SessionIdIn) -> None:
    s = await own_session(ctx, inp.session_id, lock=True)
    if await chat.open_run(ctx.session, s.id) is not None:
        raise AppException(6005, status_code=409)
    await ctx.session.exec(delete(AgentSession).where(AgentSession.id == s.id))
    ctx.invalidate(KEYS, users=[s.user_id])
