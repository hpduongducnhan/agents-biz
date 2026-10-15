"""Duyệt giữa lượt nhiều bước: dừng ở bước 2 → lưu `plan.cursor` → resume chạy tiếp bước 2 từ checkpoint rồi bước 3."""

import pytest

from app.agent.runtime import checkpoint, runner
from app.agent.testing import fake_llm as fl
from tests.agent.helpers import (
    add_notes,
    approvals,
    chat,
    events_of,
    messages,
    run_row,
    setup_router,
    slug_ids,
    unread,
)

MARK = "call:notifications_mark_all_read {}"


@pytest.fixture
async def env(team, api, aenv, rt, kicks, fake_llm, confirm_write):
    stack = await setup_router(api, fake_llm.base_url)
    u = await api.as_user("u@x.io")
    await add_notes(u.id, 3)
    return stack, u, rt, kicks


async def test_approval_in_step_two_resumes_at_cursor_and_runs_step_three(env):
    stack, u, rt, kicks = env
    api = stack.api
    script = f"route:personal,personal,report call:notifications_list {{}} | {MARK} | xem tổng"
    sent, run = await chat(api, u, script)
    ids = await slug_ids()
    assert run.status == "waiting_approval" and run.plan["cursor"] == 1 and len(run.plan["steps"]) == 3
    assert await unread(api, u) == 3
    (req,) = await approvals(sent["run_id"])
    assert req.status == "pending" and req.agent_id == ids["personal"]
    assert req.operation == "notifications.mark_all_read"
    ev = events_of(rt, u.id, "agent:approval")[0][1]
    assert ev["by"]["slug"] == "personal" and ev["approval_id"] == str(req.id)
    mid = await messages(sent["session_id"])
    assert {m.agent_id for m in mid if m.role != "user"} == {ids["personal"]}  # bước 1 đã lưu, bước 2 chưa
    saver = await checkpoint.get_checkpointer()
    assert [c async for c in saver.alist({"configurable": {"thread_id": f"{sent['run_id']}:1"}})]
    kicks.reset_mock()
    await api.post("agent.decide_approval", u, approval_id=str(req.id), approve=True)
    kicks.assert_awaited_once_with(sent["run_id"])
    fl.REQUESTS.clear()
    assert await runner.resume(sent["run_id"]) is False
    done = await run_row(sent["run_id"])
    assert done.status == "done" and done.plan["cursor"] == 3
    assert await unread(api, u) == 0  # đã chạy sau duyệt
    rows = await messages(sent["session_id"])
    agents = [m.agent_id for m in rows if m.role == "assistant"]
    assert agents[-1] == ids["report"] and agents.count(ids["personal"]) >= 3
    # chỉ bước 3 gọi LLM thêm sau resume bước 2 (bước 1 không chạy lại)
    texts = [m["content"] for r in fl.REQUESTS for m in r["body"]["messages"] if m["role"] == "user"]
    assert not any("<task>call:notifications_list" in t for t in texts)
    names = [e for e, _ in events_of(rt, u.id)]
    assert "agent:approval_decided" in names and names.count("agent:end") == 1 and names[-1] == "agent:end"
    seqs = [d["seq"] for _, d in events_of(rt, u.id)]
    assert seqs == sorted(seqs)
    for i in range(3):
        assert [c async for c in saver.alist({"configurable": {"thread_id": f"{sent['run_id']}:{i}"}})] == []


async def test_rejected_approval_in_step_two_still_runs_step_three(env):
    stack, u, rt, kicks = env
    api = stack.api
    sent, _ = await chat(api, u, f"route:personal,report {MARK} | xem tổng")
    (req,) = await approvals(sent["run_id"])
    await api.post("agent.decide_approval", u, approval_id=str(req.id), approve=False, reason="không")
    assert await runner.resume(sent["run_id"]) is False
    done = await run_row(sent["run_id"])
    assert done.status == "done" and done.plan["cursor"] == 2
    assert await unread(api, u) == 3  # không chạy
    ids = await slug_ids()
    rows = await messages(sent["session_id"])
    assert [m.agent_id for m in rows if m.role == "assistant"][-1] == ids["report"]


async def test_resume_needs_checkpointer_is_not_triggered_for_finished_runs(env):
    stack, u, _, _ = env
    sent, run = await chat(stack.api, u, "route:report tổng")
    assert run.status == "done"
    assert await runner.resume(sent["run_id"]) is False  # không còn waiting_approval → bỏ qua
    assert (await run_row(sent["run_id"])).status == "done"
