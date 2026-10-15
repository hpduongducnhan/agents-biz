"""Router: quyết định có cấu trúc (LLM giả), slug lạ, dự phòng `general`, luật bám, hỏi lại, token ở entry."""

import uuid

import pytest

from app.agent.chat.models import AgentMessage
from app.agent.config.registry import RouteSpec
from app.agent.router import service
from app.agent.router.schemas import RouteDecision, RouteStep
from app.agent.runtime.limits import _local, _token_key
from app.agent.testing import fake_llm as fl
from app.core.connections.registry import get_connections
from tests.agent.helpers import chat, events_of, messages, setup_router, slug_ids

TZ = "Asia/Ho_Chi_Minh"
ROUTER_TOOL = "RouteDecision"


@pytest.fixture
async def env(team, api, aenv, rt, kicks, fake_llm, trace_sink):
    stack = await setup_router(api, fake_llm.base_url)
    return stack, await api.as_user("u@x.io"), rt


def router_requests():
    return [r for r in fl.REQUESTS if ROUTER_TOOL in {t["function"]["name"] for t in r["body"].get("tools") or []}]


def slugs(run) -> list[str]:
    return [s["slug"] for s in run.plan["steps"]]


async def test_single_step_decision(env):
    stack, u, rt = env
    sent, run = await chat(stack.api, u, "route:report xem tổng chi tháng này")
    assert (
        run.status == "done" and slugs(run) == ["report"] and run.plan["steps"][0]["task"] == "xem tổng chi tháng này"
    )
    assert run.plan["cursor"] == 1 and run.plan["router"]["decision"]["steps"][0]["agent"] == "report"
    (ev,) = events_of(rt, u.id, "agent:route")
    ids = await slug_ids()
    assert ev[1]["clarify"] is None and ev[1]["steps"] == [
        {"agent_id": str(ids["report"]), "slug": "report", "name": "Báo cáo", "task": "xem tổng chi tháng này"}
    ]
    assert len(router_requests()) == 1


async def test_multi_step_decision_keeps_order_and_tasks(env):
    stack, u, rt = env
    _, run = await chat(stack.api, u, "route:personal,report,general ghi 45k | báo cáo | cảm ơn")
    assert slugs(run) == ["personal", "report", "general"]
    assert [s["task"] for s in run.plan["steps"]] == ["ghi 45k", "báo cáo", "cảm ơn"]
    assert [s["via"] for s in run.plan["steps"]] == ["router"] * 3


async def test_unknown_slug_dropped_and_empty_falls_back_general(env, bw_log):
    stack, u, _ = env
    _, run = await chat(stack.api, u, "route:nosuch,report việc")
    assert slugs(run) == ["report"] and "fallback" not in run.plan["router"]
    _, run = await chat(stack.api, u, "route:nosuch việc")
    assert slugs(run) == ["general"] and run.plan["router"]["fallback"] == "unknown_agent"
    warn = [r for r in bw_log() if r.get("loc") == "agt0802"]
    assert len(warn) == 1 and "DEFAULTS_APPLIED=[route]" in warn[0]["msg"]


async def test_max_three_steps_and_sanitize_unit():
    routes = {
        s: RouteSpec(uuid.uuid4(), s, s, "", (), i) for i, s in enumerate(["personal", "report", "general", "group"])
    }
    many = RouteDecision.model_construct(steps=[RouteStep(agent=s) for s in routes], clarify=None)
    steps, clarify, note = service.sanitize(many, routes, last_agent=None, sticky_ok=False)
    assert [s.agent for s in steps] == ["personal", "report", "general"] and clarify is None and note == {}
    steps, clarify, note = service.sanitize(None, routes, last_agent=None, sticky_ok=False)
    assert [s.agent for s in steps] == ["general"] and note == {"fallback": "no_decision"}
    ask = RouteDecision(steps=[RouteStep(agent="report")], clarify="hỏi gì đó?")
    steps, clarify, _ = service.sanitize(ask, routes, last_agent=None, sticky_ok=False)
    assert [s.agent for s in steps] == ["report"] and clarify is None  # có bước thì bỏ clarify
    only_clarify = RouteDecision(steps=[], clarify=" Ví nào? ")
    assert service.sanitize(only_clarify, routes, last_agent="report", sticky_ok=True)[:2] == ([], "Ví nào?")
    blank = RouteDecision(steps=[], clarify="  ")  # không bước + hỏi lại rỗng → general
    steps, clarify, note = service.sanitize(blank, routes, last_agent=None, sticky_ok=False)
    assert [s.agent for s in steps] == ["general"] and clarify is None and note == {"fallback": "empty"}
    no_general = {"report": routes["report"]}  # không có general → lấy route đầu
    assert [s.agent for s in service.sanitize(None, no_general, last_agent=None, sticky_ok=False)[0]] == ["report"]
    assert service.sanitize(None, {}, last_agent=None, sticky_ok=False)[:2] == ([], None)


async def test_router_error_falls_back_general_with_span_attr(env, trace_sink):
    stack, u, _ = env
    sent, run = await chat(stack.api, u, "routefail")
    assert run.status == "done" and slugs(run) == ["general"]
    assert run.plan["router"]["fallback"] in {"no_decision", "empty"}
    spans = [s for s in trace_sink.spans.values() if s["run_id"] == sent["run_id"]]
    (router,) = [s for s in spans if s["kind"] == "router"]
    assert (
        router["status"] == "ok" and router["output"]["fallback"] and router["output"]["steps"][0]["agent"] == "general"
    )


async def test_router_no_decision_logs_defaults_applied(env, bw_log):
    stack, u, _ = env
    await chat(stack.api, u, "routefail")
    warns = [r for r in bw_log() if r.get("loc") in ("agt0801", "agt0802")]
    assert warns and all("DEFAULTS_APPLIED=[route" in w["msg"] for w in warns)  # R11


async def test_router_exception_falls_back_general_with_warning(env, bw_log, monkeypatch):
    stack, u, _ = env

    def boom(*_a, **_k):
        raise RuntimeError("router sập")

    monkeypatch.setattr(service, "create_agent", boom)
    _, run = await chat(stack.api, u, "route:report x")
    assert run.status == "done" and slugs(run) == ["general"] and run.plan["router"]["fallback"] == "no_decision"
    warns = [r for r in bw_log() if r.get("loc") == "agt0801"]
    assert len(warns) == 1 and "DEFAULTS_APPLIED=[route=general]" in warns[0]["msg"]


async def test_asked_back_unit():
    def m(role, text):
        return AgentMessage(session_id=uuid.uuid4(), seq=1, role=role, content={"text": text})

    assert service.asked_back([m("user", "a"), m("assistant", "Ví nào?")]) is True
    assert service.asked_back([m("user", "a"), m("assistant", "Xong.")]) is False
    assert service.asked_back([m("assistant", "Ví nào?"), m("user", "b")]) is False
    assert service.asked_back([m("assistant", "?"), m("tool", "x")]) is True
    assert service.asked_back([]) is False


async def test_sticky_last_agent_when_previous_turn_asked_back(env):
    stack, u, _ = env
    first, run1 = await chat(stack.api, u, "route:report tổng chi tháng nào?")  # chuyên gia trả "…?" → hỏi lại
    texts = [m.content.get("text", "") for m in await messages(first["session_id"]) if m.role == "assistant"]
    assert texts[-1].endswith("?")
    _, run2 = await chat(stack.api, u, "route:general tháng này", session_id=first["session_id"])
    assert slugs(run2) == ["report"] and run2.plan["router"]["sticky"] == "report"
    _, run3 = await chat(stack.api, u, "route:general tháng này", session_id=first["session_id"])
    assert slugs(run3) == ["general"] and "sticky" not in run3.plan["router"]  # lượt trước không hỏi lại
    _, run4 = await chat(stack.api, u, "route:personal ăn trưa 1k", session_id=first["session_id"])
    assert slugs(run4) == ["personal"]


async def test_clarify_returns_question_without_specialist(env):
    stack, u, rt = env
    fl.REQUESTS.clear()
    sent, run = await chat(stack.api, u, "clarify:Bạn muốn ghi vào ví nào?")
    assert run.status == "done" and run.plan["steps"] == [] and run.plan["clarify"] == "Bạn muốn ghi vào ví nào?"
    assert len(fl.REQUESTS) == 1 and len(router_requests()) == 1  # chỉ router, không chuyên gia
    rows = await messages(sent["session_id"])
    assert [m.role for m in rows] == ["user", "assistant"]
    assert rows[1].content["text"] == "Bạn muốn ghi vào ví nào?" and rows[1].content["kind"] == "clarify"
    assert rows[1].agent_id == run.entry_agent_id  # orchestrator trả lời thẳng
    names = [e for e, _ in events_of(rt, u.id)]
    assert names[0] == "agent:start" and "agent:route" in names and names[-1] == "agent:end"
    route = events_of(rt, u.id, "agent:route")[0][1]
    assert route["steps"] == [] and route["clarify"] == "Bạn muốn ghi vào ví nào?"
    token = events_of(rt, u.id, "agent:token")[0][1]
    assert token["delta"] == "Bạn muốn ghi vào ví nào?" and "by" not in token


async def test_router_tokens_counted_on_entry_agent(env, trace_sink):
    stack, u, _ = env
    sent, run = await chat(stack.api, u, "clarify:Ví nào?")
    assert run.tokens_in > 0 and run.tokens_out > 0
    conns = get_connections()
    rows = trace_sink.calls
    assert {c["agent_id"] for c in rows} == {str(run.entry_agent_id)} and {c["purpose"] for c in rows} == {"router"}
    assert sum(c["input_tokens"] + c["cache_read_tokens"] for c in rows) == run.tokens_in
    used = int(await conns.redis.rw.get(_token_key(run.entry_agent_id, uuid.UUID(u.id), _local(None, TZ))) or 0)
    assert used == run.tokens_in + run.tokens_out  # hạn mức tính ở entry (orchestrator)


async def test_router_request_uses_structured_output_and_context(env):
    stack, u, _ = env
    fl.REQUESTS.clear()
    await chat(stack.api, u, "route:general chào")
    (req,) = router_requests()
    body = req["body"]
    assert any(t["function"]["name"] == ROUTER_TOOL for t in body["tools"])
    system, human = body["messages"][0]["content"], body["messages"][-1]["content"]
    assert "`personal`" in system and "`general`" in system and "Tin nhắn mới: route:general chào" in human
