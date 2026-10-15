"""Lượt nhiều bước: mỗi bước một chuyên gia, tin lưu dưới agent của bước, sự kiện mang `by`, tin các bước trước
chuyển cho bước sau, huỷ giữa chừng, agent đơn (specialist) không qua router."""

import asyncio
import json
import uuid

import pytest

from app.agent.runtime import checkpoint, runner, steps
from app.agent.runtime.plan import Plan, PlanStep, load
from app.agent.runtime.steps import NO_REPLY, SCOPE, _tail
from app.agent.testing import fake_llm as fl
from tests.agent.helpers import (
    chat,
    events_of,
    messages,
    run_row,
    send,
    setup,
    setup_router,
    slug_ids,
)
from tests.conftest import until


@pytest.fixture
async def env(team, api, aenv, rt, kicks, fake_llm, trace_sink):
    stack = await setup_router(api, fake_llm.base_url)
    return stack, await api.as_user("u@x.io"), rt


def llm_user_text(req) -> str:
    return next(m["content"] for m in reversed(req["body"]["messages"]) if m["role"] == "user")


async def test_one_step_streams_and_saves_message_with_specialist_agent_id(env):
    stack, u, rt = env
    ids = await slug_ids()
    sent, run = await chat(stack.api, u, "route:personal call:notifications_list {}")
    assert run.status == "done" and run.entry_agent_id == ids["assistant"]
    rows = await messages(sent["session_id"])
    assert [m.role for m in rows] == ["user", "assistant", "tool", "assistant"]
    assert {m.agent_id for m in rows[1:]} == {ids["personal"]}  # tin lưu dưới chuyên gia, không phải orchestrator
    assert rows[3].content["text"].startswith("Kết quả: ")
    by = {"agent_id": str(ids["personal"]), "slug": "personal", "name": "Cá nhân"}
    steps = events_of(rt, u.id, "agent:step")
    tokens = events_of(rt, u.id, "agent:token")
    assert steps and tokens and all(d.get("by") == by for _, d in [*steps, *tokens])
    names = [e for e, _ in events_of(rt, u.id)]
    assert names[:2] == ["agent:start", "agent:route"] and names.count("agent:end") == 1 and names[-1] == "agent:end"
    end = events_of(rt, u.id, "agent:end")[0][1]
    assert end["message_id"] == str(rows[-1].id) and "by" not in end and end["status"] == "done"
    assert events_of(rt, u.id, "agent:route")[0][1].get("by") is None  # agent:route không gắn by
    detail = await stack.api.get("agent.get_session", u, session_id=sent["session_id"])
    assert detail["session"]["last_agent_id"] == str(ids["personal"])


async def test_last_token_of_last_step_still_carries_by(env):
    stack, u, rt = env
    await chat(stack.api, u, "route:personal call:notifications_list {}")
    last = events_of(rt, u.id, "agent:token")[-1][1]
    assert last.get("by", {}).get("slug") == "personal"


async def test_two_steps_run_in_order_second_sees_first_tool_results(env):
    stack, u, rt = env
    fl.REQUESTS.clear()
    sent, run = await chat(stack.api, u, "route:personal,report call:notifications_list {} | xem tổng")
    assert run.status == "done" and run.plan["cursor"] == 2
    ids = await slug_ids()
    rows = await messages(sent["session_id"])
    assert [(m.role, m.agent_id) for m in rows[1:]] == [
        ("assistant", ids["personal"]),
        ("tool", ids["personal"]),
        ("assistant", ids["personal"]),
        ("assistant", ids["report"]),
    ]
    token_by = [d["by"]["slug"] for _, d in events_of(rt, u.id, "agent:token")]
    assert token_by == sorted(token_by, key=["personal", "report"].index) and set(token_by) == {"personal", "report"}
    report_req = fl.REQUESTS[-1]
    text = llm_user_text(report_req)
    assert "<task>xem tổng</task>" in text and "<earlier>" in text
    assert "[Cá nhân → notifications_list]" in text  # kết quả tool của bước trước
    assert all(
        "tool_calls" not in m or m.get("tool_calls") is None for m in report_req["body"]["messages"]
    )  # không mồ côi
    assert len(events_of(rt, u.id, "agent:end")) == 1


async def test_steps_tokens_and_calls_recorded_per_real_agent(env, trace_sink):
    stack, u, _ = env
    _, run = await chat(stack.api, u, "route:personal,report a | b")
    ids = await slug_ids()
    calls = trace_sink.calls
    assert {c["agent_id"] for c in calls} == {
        str(ids[k]) for k in ("assistant", "personal", "report")
    }  # router + 2 bước
    assert sum(c["input_tokens"] + c["cache_read_tokens"] for c in calls) == run.tokens_in


async def test_cancel_between_steps_stops_remaining(env):
    stack, u, rt = env
    sent = await send(stack.api, u, "route:personal,personal,report call:notifications_list {} | slow chậm | xem tổng")
    task = asyncio.create_task(runner.execute(sent["run_id"]))
    assert await until(lambda: any(d["by"]["slug"] == "personal" for _, d in events_of(rt, u.id, "agent:token")), 15)
    await stack.api.post("agent.cancel", u, run_id=sent["run_id"])
    await asyncio.wait_for(task, 15)
    run = await run_row(sent["run_id"])
    assert run.status == "cancelled" and run.error_code == 6014
    ids = await slug_ids()
    rows = await messages(sent["session_id"])
    assert ids["report"] not in {m.agent_id for m in rows}  # bước 3 không chạy
    assert not any("w39" in (m.content.get("text") or "") for m in rows)
    assert events_of(rt, u.id, "agent:end")[-1][1]["status"] == "cancelled"
    saver = await checkpoint.get_checkpointer()
    for i in range(3):  # thread từng bước đã bị xoá
        assert [c async for c in saver.alist({"configurable": {"thread_id": f"{sent['run_id']}:{i}"}})] == []


async def test_failed_step_marks_run_failed_and_keeps_earlier_messages(env):
    stack, u, rt = env
    sent, run = await chat(stack.api, u, "route:personal,report call:notifications_list {} | tuỳ ý fail500")
    # fake LLM chỉ đọc kịch bản trong <task>; "fail500" nằm trong task bước 2 → LLM 500
    assert run.status == "failed" and run.error_code == 6011
    ids = await slug_ids()
    rows = await messages(sent["session_id"])
    assert ids["personal"] in {m.agent_id for m in rows} and ids["report"] not in {m.agent_id for m in rows}
    assert events_of(rt, u.id, "agent:error")[-1][1]["code"] == 6011


async def test_specialist_entry_runs_without_router(api, aenv, rt, kicks, fake_llm):
    stack = await setup(api, fake_llm.base_url)  # "Assistant" chuyển về specialist
    u = await api.as_user("u@x.io")
    fl.REQUESTS.clear()
    sent, run = await chat(api, u, "route:report không đọc route")
    assert run.status == "done" and run.plan is None
    assert all(
        "RouteDecision" not in {t["function"]["name"] for t in r["body"].get("tools") or []} for r in fl.REQUESTS
    )
    assert "handoff" not in {t["function"]["name"] for r in fl.REQUESTS for t in r["body"].get("tools") or []}
    assert not events_of(rt, u.id, "agent:route")
    assert all("by" not in d for _, d in events_of(rt, u.id, "agent:token"))
    rows = await messages(sent["session_id"])
    assert {m.agent_id for m in rows if m.role != "user"} == {uuid.UUID(stack.agent_id)}


async def test_events_carry_by_and_session_lists_agent_names(env):
    stack, u, rt = env
    sent, _ = await chat(stack.api, u, "route:personal,report a | b")
    detail = await stack.api.get("agent.get_session", u, session_id=sent["session_id"])
    agents = {a["slug"]: a for a in detail["agents"]}
    assert set(agents) == {"assistant", "personal", "report"}
    assert agents["personal"]["name"] == "Cá nhân" and agents["report"]["kind"] == "specialist"
    assert agents["assistant"]["kind"] == "orchestrator"
    by_names = {d["by"]["name"] for _, d in events_of(rt, u.id, "agent:token")}
    assert by_names == {"Cá nhân", "Báo cáo"}
    msg_agents = {m["agent_id"] for m in detail["messages"] if m["role"] != "user"}
    assert msg_agents <= {a["id"] for a in detail["agents"]}


async def test_drop_checkpoint_threads_of_every_step(aenv):
    saver = await checkpoint.get_checkpointer()
    rid = uuid.uuid4()
    cfg = {"configurable": {"thread_id": f"{rid}:1", "checkpoint_ns": ""}}
    from langgraph.checkpoint.base import empty_checkpoint  # noqa: PLC0415

    await saver.aput(cfg, empty_checkpoint(), {"source": "input", "step": 0, "parents": {}}, {})
    assert [c async for c in saver.alist({"configurable": {"thread_id": f"{rid}:1"}})]
    await checkpoint.drop(rid, 0)  # steps=0: chỉ thread `<run>` → thread bước còn nguyên
    assert [c async for c in saver.alist({"configurable": {"thread_id": f"{rid}:1"}})]
    await checkpoint.drop(rid, 3)
    assert [c async for c in saver.alist({"configurable": {"thread_id": f"{rid}:1"}})] == []


def test_plan_model_roundtrip_and_cursor():
    a, b = uuid.uuid4(), uuid.uuid4()
    plan = Plan(steps=[PlanStep(agent_id=a, slug="personal", name="P"), PlanStep(agent_id=b, slug="report", name="R")])
    assert plan.current.slug == "personal" and not plan.done
    plan.insert_after_current(PlanStep(agent_id=b, slug="general", name="G", via="handoff"))
    assert [s.slug for s in plan.steps] == ["personal", "general", "report"] and plan.handoffs == 1
    plan.cursor = 3
    assert plan.done and plan.current is None
    back = load(json.loads(json.dumps(plan.dump())))
    assert back == plan and load(None) is None and load({}) is None


def requests_with_task(task: str) -> list[str]:
    return [t for t in (llm_user_text(r) for r in fl.REQUESTS if r["body"].get("messages")) if f"<task>{task}" in t]


async def test_two_step_turn_tells_each_specialist_its_scope(env):
    stack, u, _ = env
    fl.REQUESTS.clear()
    _, run = await chat(stack.api, u, "route:personal,report call:notifications_list {} | xem tổng")
    assert run.status == "done"
    first = requests_with_task("call:notifications_list")
    second = requests_with_task("xem tổng")
    assert first and second
    assert all("<scope>" in t and "chia 2 bước" in t and "bước 1" in t for t in first)
    assert all("<scope>" in t and "chia 2 bước" in t and "bước 2" in t for t in second)


async def test_one_step_turn_has_no_scope(env):
    stack, u, _ = env
    fl.REQUESTS.clear()
    await chat(stack.api, u, "route:personal call:notifications_list {}")
    texts = [llm_user_text(r) for r in fl.REQUESTS if r["body"].get("messages")]
    assert texts and not any("<scope>" in t for t in texts)


def test_tail_orders_task_scope_earlier():
    step = PlanStep(agent_id=uuid.uuid4(), slug="report", name="Báo cáo", task="xem tổng")
    out = _tail(step, "[Cá nhân → notifications_list] ok", index=1, total=2)
    scope = SCOPE.format(n=2, i=2)
    assert out.index("<task>") < out.index(scope) < out.index("<earlier>")
    assert "chia 2 bước" in out and "bước 2" in out
    single = _tail(step, "x")
    assert "<scope>" not in single and single.index("<task>") < single.index("<earlier>")
    assert "<scope>" not in _tail(step, "", index=0, total=1)


async def test_turn_without_any_text_gets_fallback_reply(env, monkeypatch):
    stack, u, rt = env
    orig = fl._plan

    def empty_for_specialist(body):
        plan = orig(body)
        if plan["kind"] == "text" and "RouteDecision" not in {t["function"]["name"] for t in body.get("tools") or []}:
            return {"kind": "text", "text": "", "delay": 0.0}
        return plan

    monkeypatch.setattr(fl, "_plan", empty_for_specialist)
    sent, run = await chat(stack.api, u, "route:personal việc gì đó")
    assert run.status == "done"
    ids = await slug_ids()
    rows = [m for m in await messages(sent["session_id"]) if m.role == "assistant"]
    assert rows[-1].content["text"] == NO_REPLY and rows[-1].content["kind"] == "fallback"
    assert rows[-1].agent_id == ids["assistant"]  # lưu dưới agent đầu vào (orchestrator)
    assert not any((m.content.get("text") or "").strip() for m in rows[:-1])
    assert NO_REPLY in "".join(d["delta"] for _, d in events_of(rt, u.id, "agent:token"))


async def test_turn_with_text_has_no_fallback(env):
    stack, u, _ = env
    sent, run = await chat(stack.api, u, "route:personal call:notifications_list {}")
    assert run.status == "done"
    rows = await messages(sent["session_id"])
    assert not any(m.content.get("kind") == "fallback" or m.content.get("text") == NO_REPLY for m in rows)


async def test_fallback_logs_warning_agt0104(env, monkeypatch, caplog):
    stack, u, _ = env
    monkeypatch.setattr(steps, "_answered", _never_answered)
    with caplog.at_level("WARNING"):
        sent, _ = await chat(stack.api, u, "route:personal xin chào")
    assert any(getattr(r, "loc", None) == "agt0104" and r.levelname == "WARNING" for r in caplog.records)
    assert (await messages(sent["session_id"]))[-1].content["kind"] == "fallback"


async def _never_answered(run_id):
    return False
