"""agent.* — gửi tin, phiên, huỷ, duyệt, đọc lại sự kiện; quyền + hạn mức + kick sau commit."""

import uuid

import pytest

from app.agent.chat.models import AgentApproval
from app.agent.trace.events import RunEmitter, cancel_key
from app.core.connections.registry import get_connections
from tests.agent.helpers import (
    add_approval,
    messages,
    redis_get,
    run_row,
    save_agent_body,
    send,
    set_run,
    setup,
)  # fmt: skip


@pytest.fixture
async def env(api, aenv, kicks, fake_llm):
    stack = await setup(api, fake_llm.base_url)
    u = await api.as_user("u@x.io")
    return api, u, kicks, stack


async def test_send_creates_message_and_queued_run_and_kicks_after_commit(env):
    api, u, kicks, _ = env
    seen = {}

    async def spy(run_id):
        seen["run"] = await run_row(run_id)  # lúc kick, dòng run đã commit

    kicks.side_effect = spy
    text = "x" * 100
    out = await send(api, u, text)
    kicks.assert_awaited_once_with(out["run_id"])
    assert seen["run"].status == "queued" and seen["run"].user_id == uuid.UUID(u.id)
    msgs = await messages(out["session_id"])
    assert [(m.role, m.seq, m.content["text"]) for m in msgs] == [("user", 1, text)]
    assert msgs[0].id == uuid.UUID(out["message_id"]) and str(msgs[0].run_id) == out["run_id"]
    detail = await api.get("agent.get_session", u, session_id=out["session_id"])
    assert detail["session"]["title"] == "x" * 59 + "…" and detail["session"]["open_run_status"] == "queued"


async def test_send_same_client_msg_id_returns_same_run(env):
    api, u, kicks, _ = env
    first = await send(api, u, "hi", client_msg_id="cm-1")
    again = await send(api, u, "hi", session_id=first["session_id"], client_msg_id="cm-1")
    assert again == first and kicks.await_count == 1
    assert len(await messages(first["session_id"])) == 1


async def test_one_open_run_per_session_is_6005(env):
    api, u, kicks, _ = env
    first = await send(api, u, "một")
    body = {"session_id": first["session_id"], "content": "hai", "client_msg_id": "c2"}
    assert await api.err("POST", "agent.send", u, json=body) == (409, 6005)
    assert kicks.await_count == 1 and len(await messages(first["session_id"])) == 1
    await set_run(first["run_id"], status="done")
    second = await send(api, u, "hai", session_id=first["session_id"])
    assert second["run_id"] != first["run_id"] and second["session_id"] == first["session_id"]
    assert [m.seq for m in await messages(first["session_id"])] == [1, 2]


async def test_agent_visibility_and_chat_permission(env):
    api, u, _, stack = env
    nobody = await api.as_user("none@x.io", roles=())
    body = {"content": "hi", "client_msg_id": "k1"}
    assert await api.err("POST", "agent.send", nobody, json=body) == (403, 1005)
    assert await api.err("GET", "agent.list_agents", nobody) == (403, 1005)
    root = stack.root
    current = await api.get("studio.get_agent", root, agent_id=stack.agent_id)
    await api.post("studio.save_agent", root, **save_agent_body(current, visible_to="roles", visible_roles=["admin"]))
    assert await api.err("POST", "agent.send", u, json=body) == (404, 6003)
    assert await api.get("agent.list_agents", u) == []
    admin = await api.as_user("adm@x.io", roles=("admin",))
    assert (await send(api, admin, "hi"))["run_id"]
    assert [c["slug"] for c in await api.get("agent.list_agents", admin)] == ["assistant"]
    assert (await send(api, root, "hi"))["run_id"]  # superadmin thấy mọi agent
    await api.post("studio.save_agent", root, **save_agent_body(current, is_active=False))
    assert await api.err("POST", "agent.send", admin, json={**body, "client_msg_id": "k2"}) == (404, 6003)
    ghost = {**body, "agent_id": str(uuid.uuid4()), "client_msg_id": "k3"}
    assert await api.err("POST", "agent.send", admin, json=ghost) == (404, 6003)


async def test_sessions_private_to_owner(env):
    api, u, _, stack = env
    other = await api.as_user("o@x.io")
    mine = await send(api, u, "của tôi")
    theirs = await send(api, other, "của họ")
    page = await api.get("agent.list_sessions", u)
    assert [s["id"] for s in page["items"]] == [mine["session_id"]] and page["items"][0]["open_run_status"] == "queued"
    assert await api.err("GET", "agent.get_session", other, params={"session_id": mine["session_id"]}) == (404, 6004)
    assert await api.err(
        "POST", "agent.rename_session", other, json={"session_id": mine["session_id"], "title": "x"}
    ) == (404, 6004)
    assert await api.err("POST", "agent.delete_session", other, json={"session_id": mine["session_id"]}) == (404, 6004)
    assert await api.err(
        "POST", "agent.send", other, json={"session_id": mine["session_id"], "content": "chen", "client_msg_id": "z"}
    ) == (404, 6004)
    ignored = await api.get("agent.list_sessions", u, user_id=other.id)  # user thường không xem được phiên người khác
    assert [s["id"] for s in ignored["items"]] == [mine["session_id"]]
    sup = await api.get("agent.list_sessions", stack.root, user_id=u.id)
    assert [s["id"] for s in sup["items"]] == [mine["session_id"]]
    assert (await api.get("agent.get_session", stack.root, session_id=theirs["session_id"]))["session"][
        "user_id"
    ] == other.id
    assert await api.err("GET", "agent.get_session", u, params={"session_id": str(uuid.uuid4())}) == (404, 6004)


async def test_rename_and_delete_session(env):
    api, u, _, _ = env
    s = await send(api, u, "đặt tên")
    renamed = await api.post("agent.rename_session", u, session_id=s["session_id"], title="  Tên mới ")
    assert renamed["title"] == "Tên mới"
    assert await api.err("POST", "agent.delete_session", u, json={"session_id": s["session_id"]}) == (409, 6005)
    await set_run(s["run_id"], status="done")
    await api.post("agent.delete_session", u, session_id=s["session_id"])
    assert (await api.get("agent.list_sessions", u))["total"] == 0 and await messages(s["session_id"]) == []


async def test_get_session_detail_has_open_run_and_pending_approvals(env):
    api, u, _, _ = env
    s = await send(api, u, "chờ duyệt")
    await set_run(s["run_id"], status="waiting_approval")
    await add_approval(s["run_id"], args={"wallet_id": "w"})
    await add_approval(s["run_id"], status="approved")
    d = await api.get("agent.get_session", u, session_id=s["session_id"])
    assert d["open_run"]["status"] == "waiting_approval" and d["last_run"]["id"] == s["run_id"]
    assert [a["status"] for a in d["approvals"]] == ["pending"] and d["messages"][0]["role"] == "user"


async def test_decide_approval_only_owner_or_superadmin_once(env):
    api, u, kicks, stack = env
    s = await send(api, u, "x")
    await set_run(s["run_id"], status="waiting_approval")
    a1, a2 = await add_approval(s["run_id"]), await add_approval(s["run_id"])
    other = await api.as_user("o@x.io")
    assert await api.err("POST", "agent.decide_approval", other, json={"approval_id": str(a1.id), "approve": True}) == (
        403,
        1005,
    )
    kicks.reset_mock()
    out = await api.post("agent.decide_approval", u, approval_id=str(a1.id), approve=True)
    assert out["status"] == "approved" and out["run_id"] == s["run_id"]
    kicks.assert_not_awaited()  # còn yêu cầu chờ
    assert await api.err("POST", "agent.decide_approval", u, json={"approval_id": str(a1.id), "approve": False}) == (
        409,
        6008,
    )
    out = await api.post("agent.decide_approval", stack.root, approval_id=str(a2.id), approve=False, reason="không")
    assert out["status"] == "rejected"
    kicks.assert_awaited_once_with(s["run_id"])  # hết yêu cầu → chạy tiếp
    async with get_connections().postgres.ro() as sess:
        row = await sess.get(AgentApproval, a2.id)
    assert row.reason == "không" and row.decided_by is not None and row.decided_at is not None
    assert await api.err(
        "POST", "agent.decide_approval", u, json={"approval_id": str(uuid.uuid4()), "approve": True}
    ) == (404, 6008)


async def test_decide_expired_approval_is_6008(env):
    api, u, _, _ = env
    s = await send(api, u, "x")
    await set_run(s["run_id"], status="waiting_approval")
    a = await add_approval(s["run_id"], expires_in=-5)
    assert await api.err("POST", "agent.decide_approval", u, json={"approval_id": str(a.id), "approve": True}) == (
        409,
        6008,
    )


async def test_cancel_sets_flag_for_running_and_closes_queued(env, rt):
    api, u, _, _ = env
    s = await send(api, u, "huỷ")
    out = await api.post("agent.cancel", u, run_id=s["run_id"])  # queued → đóng ngay
    assert out == {"run_id": s["run_id"], "status": "cancelled"}
    run = await run_row(s["run_id"])
    assert run.status == "cancelled" and run.error_code == 6014 and run.ended_at
    assert [e for e in rt.events() if e[1] == "agent:end" and e[2]["status"] == "cancelled"]
    again = await api.post("agent.cancel", u, run_id=s["run_id"])
    assert again["status"] == "cancelled"
    s2 = await send(api, u, "đang chạy")
    await set_run(s2["run_id"], status="running")
    assert (await api.post("agent.cancel", u, run_id=s2["run_id"]))["status"] == "cancelling"
    assert await redis_get(cancel_key(s2["run_id"])) in (b"1", "1")
    other = await api.as_user("o@x.io")
    assert await api.err("POST", "agent.cancel", other, json={"run_id": s2["run_id"]}) == (404, 6006)
    assert await api.err("POST", "agent.cancel", u, json={"run_id": str(uuid.uuid4())}) == (404, 6006)


async def test_cancel_waiting_run_expires_pending_approvals(env):
    api, u, _, _ = env
    s = await send(api, u, "x")
    await set_run(s["run_id"], status="waiting_approval")
    a = await add_approval(s["run_id"])
    assert (await api.post("agent.cancel", u, run_id=s["run_id"]))["status"] == "cancelled"
    async with get_connections().postgres.ro() as sess:
        assert (await sess.get(AgentApproval, a.id)).status == "expired"


async def test_run_events_after_seq(env):
    api, u, _, _ = env
    s = await send(api, u, "sự kiện")
    empty = await api.get("agent.run_events", u, run_id=s["run_id"])
    assert empty == {"available": False, "events": []}
    em = RunEmitter(get_connections().redis, s["run_id"], s["session_id"], u.id)
    await em.start(agent_id="a")
    await em.step(call_id="c", name="t", status="running")
    await em.end(message_id=None, usage={})
    allv = await api.get("agent.run_events", u, run_id=s["run_id"])
    assert [e["data"]["seq"] for e in allv["events"]] == [1, 2, 3] and allv["available"]
    tail = await api.get("agent.run_events", u, run_id=s["run_id"], after_seq=2)
    assert [e["event"] for e in tail["events"]] == ["agent:end"]
    other = await api.as_user("o@x.io")
    assert await api.err("GET", "agent.run_events", other, params={"run_id": s["run_id"]}) == (404, 6006)


async def test_send_applies_limits_and_refunds_on_conflict(env):
    api, u, _, stack = env
    await api.post("studio.set_agent_limits", stack.root, agent_id=stack.agent_id, per_minute=2)
    first = await send(api, u, "1")
    body = {"session_id": first["session_id"], "content": "2", "client_msg_id": "c2"}
    assert await api.err("POST", "agent.send", u, json=body) == (409, 6005)  # lượt đếm được trả lại
    await set_run(first["run_id"], status="done")
    await send(api, u, "3", session_id=first["session_id"])
    await set_run(first["run_id"], status="done")
    r = await api.call("POST", "/agent/send", u, json={"content": "4", "client_msg_id": "c4"})
    assert r.status_code == 429 and r.json()["code"] == 6001
    assert (
        r.json()["data"]["window"] == "minute"
        and r.json()["data"]["limit"] == 2
        and r.json()["data"]["retry_after_sec"] >= 1
    )
    sup = await send(api, stack.root, "superadmin miễn")
    assert sup["run_id"]
