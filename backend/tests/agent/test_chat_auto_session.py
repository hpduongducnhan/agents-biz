"""Phiên chat tự động: cài đặt, agent.send auto, current_session, tool_titles, agent:llm, lịch sử."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from app.agent.chat.models import AgentMessage, AgentSession
from app.agent.testing import fake_llm as fl
from app.core.connections.registry import get_connections
from app.tenants.models import DEFAULT_TENANT_ID
from tests.agent.helpers import add_notes, chat, events_of, messages, send, set_run, setup

KEYS = ("chat_session_idle_min", "chat_history_limit", "chat_history_tools")
MARK_TITLE = "Đọc hết"


@pytest.fixture
async def env(api, aenv, rt, fake_llm):
    stack = await setup(api, fake_llm.base_url)
    u = await api.as_user("u@x.io")
    return api, u, rt, stack


async def age(session_id: str, minutes: float) -> None:
    async with get_connections().postgres.rw() as s:
        stmt = update(AgentSession).where(AgentSession.id == uuid.UUID(session_id))
        await s.exec(stmt.values(updated_at=datetime.now(UTC) - timedelta(minutes=minutes)))


async def set_settings(stack, **values):
    return await stack.api.post("system.update_settings", stack.root, **values)


async def test_settings_defaults_update_and_validation(env):
    api, _, _, stack = env
    out = await api.get("system.get_settings", stack.root)
    assert (out["chat_session_idle_min"], out["chat_history_limit"], out["chat_history_tools"]) == (30, 20, True)
    assert set(KEYS) <= set(out["defaults_applied"])
    out = await set_settings(stack, chat_session_idle_min=5, chat_history_limit=7, chat_history_tools=False)
    assert (out["chat_session_idle_min"], out["chat_history_limit"], out["chat_history_tools"]) == (5, 7, False)
    assert not set(KEYS) & set(out["defaults_applied"])
    for bad in (
        {"chat_session_idle_min": 0},
        {"chat_session_idle_min": 1441},
        {"chat_history_limit": 0},
        {"chat_history_limit": 101},
        {"chat_history_tools": "nope"},
    ):
        assert await api.err("POST", "system.update_settings", stack.root, json=bad) == (422, 1002)
    assert (await api.get("system.get_settings", stack.root))["chat_history_limit"] == 7


async def test_auto_send_reuses_open_session_and_ignores_client_session_id(env):
    api, u, kicks, stack = env
    first = await send(api, u, "một", auto=True)
    await set_run(first["run_id"], status="done")
    again = await send(api, u, "hai", auto=True, session_id=str(uuid.uuid4()))  # session_id lạ bị bỏ qua
    assert again["session_id"] == first["session_id"] and again["run_id"] != first["run_id"]
    assert [m.seq for m in await messages(first["session_id"])] == [1, 2]
    await set_run(again["run_id"], status="done")
    await age(first["session_id"], 31)  # quá 30 phút → phiên mới
    third = await send(api, u, "ba", auto=True)
    assert third["session_id"] != first["session_id"]


async def test_auto_send_idempotent_by_client_msg_id_and_follows_idle_setting(env):
    api, u, _, stack = env
    first = await send(api, u, "một", auto=True, client_msg_id="cm-a")
    again = await send(api, u, "một", auto=True, client_msg_id="cm-a")
    assert again == first and len(await messages(first["session_id"])) == 1
    await set_run(first["run_id"], status="done")
    await age(first["session_id"], 10)
    await set_settings(stack, chat_session_idle_min=5)
    assert (await send(api, u, "hai", auto=True))["session_id"] != first["session_id"]


async def test_auto_send_keeps_session_with_open_run_even_if_stale(env):
    api, u, _, _ = env
    first = await send(api, u, "một", auto=True)
    await age(first["session_id"], 600)
    # run còn mở → vẫn là phiên hiện tại → send trùng lượt mở = 6005
    body = {"content": "hai", "client_msg_id": "c2", "auto": True}
    assert await api.err("POST", "agent.send", u, json=body) == (409, 6005)


async def test_current_session_op(env):
    api, u, _, stack = env
    out = await api.get("agent.current_session", u)
    assert out == {"current": None, "previous": None, "idle_min": 30, "expires_at": None}
    first = await send(api, u, "một", auto=True)
    await set_run(first["run_id"], status="done")
    out = await api.get("agent.current_session", u)
    assert out["current"]["id"] == first["session_id"] and out["previous"] is None and out["idle_min"] == 30
    expires = datetime.fromisoformat(out["expires_at"])
    assert abs(expires - (datetime.fromisoformat(out["current"]["updated_at"]) + timedelta(minutes=30))) < timedelta(1)
    await age(first["session_id"], 40)
    out = await api.get("agent.current_session", u)
    assert out["current"] is None and out["previous"]["id"] == first["session_id"] and out["expires_at"] is None
    other = await api.as_user("o@x.io")
    assert (await api.get("agent.current_session", other))["previous"] is None  # không lẫn phiên của user khác


async def test_current_session_scoped_to_agent(env):
    api, u, _, stack = env
    await send(api, u, "một", auto=True)
    other = await api.post("studio.save_agent", stack.root, slug="helper", name="Helper", instructions="x")
    out = await api.get("agent.current_session", u, agent_id=other["id"])
    assert out["current"] is None and out["previous"] is None
    assert (await api.get("agent.current_session", u, agent_id=stack.agent_id))["current"] is not None


async def test_get_session_tool_titles_and_llm_events(env):
    api, u, rt, _ = env
    await add_notes(u.id, 2)
    sent, run = await chat(api, u, "đọc call:notifications_mark_all_read {}")
    assert run.status == "done"
    detail = await api.get("agent.get_session", u, session_id=sent["session_id"])
    assert detail["tool_titles"] == {"notifications_mark_all_read": MARK_TITLE}
    llm = [d for _, d in events_of(rt, u.id, "agent:llm")]
    assert len(llm) == 2
    assert llm[0]["tools"] == [{"name": "notifications_mark_all_read", "title": MARK_TITLE}]
    assert llm[0]["status"] == "done"
    assert llm[1]["tools"] == [] and llm[1]["text"] is True
    assert all(isinstance(d["ms"], int) and d["ms"] >= 0 for d in llm)
    assert all({"input", "output"} <= set(d["tokens"]) for d in llm)
    names = [e for e, _ in events_of(rt, u.id)]
    assert names.index("agent:llm") < names.index("agent:end")


async def test_tool_titles_handoff_and_unknown_name(env):
    api, u, _, _ = env
    sent = await send(api, u, "hi", auto=True)
    calls = [{"id": "1", "name": "handoff", "args": {}}, {"id": "2", "name": "khong_co_op", "args": {}}]
    async with get_connections().postgres.rw() as s:
        s.add(
            AgentMessage(
                tenant_id=DEFAULT_TENANT_ID,
                session_id=uuid.UUID(sent["session_id"]),
                seq=2,
                role="assistant",
                content={"text": "", "tool_calls": calls},
            )
        )
    detail = await api.get("agent.get_session", u, session_id=sent["session_id"])
    assert detail["tool_titles"] == {"handoff": "Chuyển chuyên gia", "khong_co_op": "khong_co_op"}


async def test_runner_history_limit_from_settings(env):
    api, u, _, stack = env
    await set_settings(stack, chat_history_limit=2)
    first, _ = await chat(api, u, "câu một")
    sid = first["session_id"]
    for text in ("câu hai", "câu ba", "câu bốn"):
        await chat(api, u, text, session_id=sid)
    sent = [(m["role"], m["content"]) for m in fl.REQUESTS[-1]["body"]["messages"] if m["role"] != "system"]
    assert [r for r, _ in sent] == ["user", "assistant", "user"]
    assert "câu ba" in sent[0][1] and "câu bốn" in sent[2][1] and "câu một" not in json.dumps(sent)


async def test_runner_history_tools_flag(env):
    api, u, _, stack = env
    await add_notes(u.id, 2)
    first, _ = await chat(api, u, "đọc call:notifications_mark_all_read {}")
    await chat(api, u, "tiếp", session_id=first["session_id"])
    assert "tool" in [m["role"] for m in fl.REQUESTS[-1]["body"]["messages"]]  # mặc định giữ tool
    await set_settings(stack, chat_history_tools=False)
    await chat(api, u, "nữa", session_id=first["session_id"])
    roles = [m["role"] for m in fl.REQUESTS[-1]["body"]["messages"]]
    assert "tool" not in roles and roles[0] == "system" and roles[-1] == "user"
