"""chat.history (đếm theo tin hội thoại, tools bật / tắt) + chat.current_session (phiên đang mở theo idle)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update
from sqlmodel import select

from app.agent.chat import service as chat
from app.agent.chat.models import AgentRun, AgentSession
from app.agent.config.models import Agent
from app.core.connections.registry import get_connections
from app.tenants.models import DEFAULT_TENANT_ID
from tests.agent.helpers import assistant_id


@pytest.fixture
async def ctx(api, aenv):
    u = await api.as_user("h@x.io")
    return uuid.UUID(u.id), await assistant_id()


async def new_session(user_id, agent_id, items=(), *, run_id=None, age_min=0.0) -> uuid.UUID:
    """Tạo phiên + tin (item = (role, content)); `age_min` phút trước là lần cập nhật cuối."""
    async with get_connections().postgres.rw() as s:
        row = AgentSession(tenant_id=DEFAULT_TENANT_ID, user_id=user_id, entry_agent_id=agent_id, title="t")
        s.add(row)
        await s.flush()
        if items:
            await chat.add_messages(s, row, run_id, agent_id, [{"role": r, "content": c} for r, c in items])
        await s.exec(
            update(AgentSession)
            .where(AgentSession.id == row.id)
            .values(updated_at=datetime.now(UTC) - timedelta(minutes=age_min))
        )
        return row.id


def u(text):
    return ("user", {"text": text})


def a(text):
    return ("assistant", {"text": text, "tool_calls": []})


def call(name="wallet_list"):
    return ("assistant", {"text": "", "tool_calls": [{"id": "c1", "name": name, "args": {}}]})


def result(name="wallet_list"):
    return ("tool", {"text": "{}", "name": name, "tool_call_id": "c1", "status": "success"})


async def hist(sid, limit, *, tools=True, exclude=None) -> list[tuple[str, str]]:
    async with get_connections().postgres.ro() as s:
        rows = await chat.history(s, sid, limit, exclude_run=exclude or uuid.uuid4(), tools=tools)
    return [(m.role, m.content.get("text") or "<call>") for m in rows]


FLOW = [u("q1"), a("a1"), u("q2"), call(), result(), a("a2"), u("q3"), a("a3")]


async def test_history_counts_only_talk_messages_and_keeps_tools_between(ctx):
    sid = await new_session(*ctx, FLOW)
    # 4 tin hội thoại gần nhất: q2 a2 q3 a3 (call + result nằm giữa q2 và a2 không tính)
    tail = [("user", "q2"), ("assistant", "<call>"), ("tool", "{}"), ("assistant", "a2")]
    assert await hist(sid, 4) == [*tail, ("user", "q3"), ("assistant", "a3")]
    talk = [("user", "q2"), ("assistant", "a2"), ("user", "q3"), ("assistant", "a3")]
    assert await hist(sid, 4, tools=False) == talk
    assert len(await hist(sid, 100)) == 8 and len(await hist(sid, 100, tools=False)) == 6


async def test_history_starts_with_user_message_and_empty_session(ctx):
    sid = await new_session(*ctx, FLOW)
    out = await hist(sid, 3)
    assert out[0][0] == "user" and out == [("user", "q3"), ("assistant", "a3")]  # a2 bị cắt vì đứng đầu
    assert await hist(sid, 1) == []  # chỉ còn a3 → không có tin user mở đầu
    assert await hist(await new_session(*ctx), 5) == []


async def test_history_excludes_current_run(ctx):
    user_id, agent = ctx
    sid = await new_session(user_id, agent, [u("q1"), a("a1")])
    async with get_connections().postgres.rw() as s:
        run = AgentRun(tenant_id=DEFAULT_TENANT_ID, session_id=sid, user_id=user_id, entry_agent_id=agent)
        s.add(run)
        await s.flush()
        run_id = run.id
        row = await s.get(AgentSession, sid)
        await chat.add_messages(s, row, run_id, agent, [{"role": "user", "content": {"text": "now"}}])
    assert await hist(sid, 10, exclude=run_id) == [("user", "q1"), ("assistant", "a1")]
    assert (await hist(sid, 10))[-1] == ("user", "now")


async def cur(user_id, agent_id, idle=30):
    async with get_connections().postgres.ro() as s:
        c, p = await chat.current_session(s, user_id, agent_id, idle)
    return c and c.id, p and p.id


async def test_current_session_fresh_stale_and_none(ctx):
    user_id, agent = ctx
    assert await cur(user_id, agent) == (None, None)
    old = await new_session(user_id, agent, [u("x")], age_min=120)
    assert await cur(user_id, agent) == (None, old)  # quá hạn
    fresh = await new_session(user_id, agent, [u("y")], age_min=5)
    assert await cur(user_id, agent) == (fresh, old)
    assert await cur(user_id, agent, idle=1) == (None, fresh)  # idle ngắn hơn 5 phút


async def test_current_session_open_run_keeps_stale_session_current(ctx):
    user_id, agent = ctx
    sid = await new_session(user_id, agent, [u("x")], age_min=500)
    assert await cur(user_id, agent) == (None, sid)
    async with get_connections().postgres.rw() as s:
        run = AgentRun(tenant_id=DEFAULT_TENANT_ID, session_id=sid, user_id=user_id, entry_agent_id=agent)
        run.status = "running"
        s.add(run)
    assert await cur(user_id, agent) == (sid, None)


async def test_current_session_scoped_to_user_and_agent(api, ctx):
    user_id, agent = ctx
    other = await api.as_user("o@x.io")
    async with get_connections().postgres.ro() as s:
        other_agent = (await s.exec(select(Agent.id).where(Agent.id != agent))).first()
    await new_session(uuid.UUID(other.id), agent, [u("x")])
    await new_session(user_id, other_agent, [u("y")])
    assert await cur(user_id, agent) == (None, None)
