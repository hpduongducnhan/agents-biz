"""Duyệt thao tác nguy hiểm trong chat: dừng chờ duyệt → quyết → chạy tiếp (duyệt / từ chối / hết hạn)."""

import pytest
from sqlmodel import select

from app.agent.chat.models import AgentApproval
from app.agent.runtime import checkpoint, runner
from app.agent.testing import fake_llm as fl
from app.core.connections.registry import get_connections
from tests.agent.helpers import add_notes, approvals, chat, events_of, messages, run_row, set_run, setup, unread


@pytest.fixture
async def env(api, aenv, rt, kicks, fake_llm, confirm_write):
    await setup(api, fake_llm.base_url)
    u = await api.as_user("u@x.io")
    await add_notes(u.id, 3)
    assert await unread(api, u) == 3
    script = "đọc hết call:notifications_mark_all_read {}"
    return api, u, rt, kicks, script


async def test_destructive_tool_waits_for_approval_then_resumes(env):
    api, u, rt, kicks, script = env
    sent, run = await chat(api, u, script)
    assert run.status == "waiting_approval" and run.ended_at is None
    assert await unread(api, u) == 3  # chưa chạy
    (req,) = await approvals(sent["run_id"])
    assert req.status == "pending" and req.operation == "notifications.mark_all_read"
    assert req.args == {}
    ev = events_of(rt, u.id, "agent:approval")[0][1]
    assert ev["approval_id"] == str(req.id) and ev["operation"] == "notifications.mark_all_read" and ev["args"] == {}
    assert ev["expires_at"] and ev["title"]
    detail = await api.get("agent.get_session", u, session_id=sent["session_id"])
    assert detail["open_run"]["status"] == "waiting_approval" and [a["id"] for a in detail["approvals"]] == [
        str(req.id)
    ]
    saver = await checkpoint.get_checkpointer()
    assert [c async for c in saver.alist({"configurable": {"thread_id": sent["run_id"]}})]  # checkpoint được giữ
    kicks.reset_mock()
    await api.post("agent.decide_approval", u, approval_id=str(req.id), approve=True)
    kicks.assert_awaited_once_with(sent["run_id"])
    assert await runner.resume(sent["run_id"]) is False
    done = await run_row(sent["run_id"])
    assert done.status == "done"
    assert await unread(api, u) == 0  # đã chạy sau duyệt
    rows = await messages(sent["session_id"])
    assert [m.role for m in rows] == ["user", "assistant", "tool", "assistant"]
    assert rows[2].content["status"] == "success" and rows[3].content["text"].startswith("Kết quả: ")
    names = [e for e, _ in events_of(rt, u.id)]
    assert "agent:approval_decided" in names and names[-1] == "agent:end"
    assert [d["seq"] for _, d in events_of(rt, u.id)] == sorted(d["seq"] for _, d in events_of(rt, u.id))
    assert [c async for c in saver.alist({"configurable": {"thread_id": sent["run_id"]}})] == []  # dọn sau khi xong
    only = await approvals(sent["run_id"])
    assert len(only) == 1 and only[0].status == "approved" and only[0].decided_by is not None


async def test_rejection_is_reported_to_llm(env):
    api, u, rt, kicks, script = env
    sent, run = await chat(api, u, script)
    (req,) = await approvals(sent["run_id"])
    await api.post("agent.decide_approval", u, approval_id=str(req.id), approve=False, reason="để lại")
    await runner.resume(sent["run_id"])
    assert (await run_row(sent["run_id"])).status == "done"
    assert await unread(api, u) == 3
    rows = await messages(sent["session_id"])
    assert (
        rows[2].content["status"] == "error" and rows[2].content["text"] == "Người dùng đã từ chối thao tác này: để lại"
    )
    assert rows[3].content["text"].startswith("Kết quả: Người dùng đã từ chối")
    last_tool = [m for m in fl.REQUESTS[-1]["body"]["messages"] if m["role"] == "tool"]
    assert last_tool and "từ chối" in last_tool[0]["content"]


async def test_expired_approval_tells_llm_it_expired(env):
    api, u, _, _, script = env
    sent, _ = await chat(api, u, script)
    (req,) = await approvals(sent["run_id"])
    async with get_connections().postgres.rw() as s:
        row = (await s.exec(select(AgentApproval).where(AgentApproval.id == req.id))).one()
        row.status = "expired"
        s.add(row)
    await runner.resume(sent["run_id"])
    rows = await messages(sent["session_id"])
    assert rows[2].content["text"] == "Yêu cầu duyệt đã hết hạn — thao tác không chạy."
    assert await unread(api, u) == 3


async def test_cancel_while_waiting_closes_run_and_drops_checkpoint(env):
    api, u, rt, _, script = env
    sent, _ = await chat(api, u, script)
    await api.post("agent.cancel", u, run_id=sent["run_id"])
    run = await run_row(sent["run_id"])
    assert (run.status, run.error_code) == ("cancelled", 6014)
    assert [a.status for a in await approvals(sent["run_id"])] == ["expired"]
    saver = await checkpoint.get_checkpointer()
    assert [c async for c in saver.alist({"configurable": {"thread_id": sent["run_id"]}})] == []
    assert await runner.resume(sent["run_id"]) is False
    assert await unread(api, u) == 3


async def test_two_parallel_calls_need_two_approvals_and_resume_after_last(env):
    api, u, rt, kicks, script = env
    fl.PARALLEL = True
    sent, run = await chat(api, u, script)
    assert run.status == "waiting_approval"
    reqs = await approvals(sent["run_id"])
    assert len(reqs) == 2 and {r.status for r in reqs} == {"pending"}
    kicks.reset_mock()
    await api.post("agent.decide_approval", u, approval_id=str(reqs[0].id), approve=True)
    kicks.assert_not_awaited()
    await api.post("agent.decide_approval", u, approval_id=str(reqs[1].id), approve=False)
    kicks.assert_awaited_once()
    await runner.resume(sent["run_id"])
    assert (await run_row(sent["run_id"])).status == "done"
    assert await unread(api, u) == 0  # cái được duyệt chạy; cái bị từ chối thì không


async def test_resume_runs_only_from_waiting_state(env):
    api, u, _, _, script = env
    sent, _ = await chat(api, u, script)
    await set_run(sent["run_id"], status="running")
    assert await runner.resume(sent["run_id"]) is False
