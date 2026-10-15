"""Trace lượt có router (R19): run → router → llm; run → agent(slug) → llm → tool; chờ duyệt rồi resume cùng span."""

import json

import pytest

from app.agent.runtime import runner
from app.agent.trace.noop import NoopTracer
from app.agent.trace.spans import SPAN, AgentStepSpan, RouterSpan
from tests.agent.helpers import add_notes, approvals, chat, setup_router


@pytest.fixture
async def env(team, api, aenv, rt, kicks, fake_llm, trace_sink):
    stack = await setup_router(api, fake_llm.base_url)
    return stack, await api.as_user("u@x.io"), trace_sink


def spans_of(sink, run_id, kind=None):
    rows = sorted((s for s in sink.spans.values() if s["run_id"] == run_id), key=lambda s: s["seq"])
    return [s for s in rows if kind is None or s["kind"] == kind]


async def test_trace_tree_run_router_agent_llm_tool(env):
    stack, u, sink = env
    sent, run = await chat(stack.api, u, "route:personal,report call:notifications_list {} | tổng")
    rid = sent["run_id"]
    (run_span,) = spans_of(sink, rid, "run")
    (router,) = spans_of(sink, rid, "router")
    agents = spans_of(sink, rid, "agent")
    assert run_span["id"] == rid and run_span["status"] == "ok" and run_span["input"]["agent"]
    assert router["parent_id"] == rid and router["name"] == "router" and router["status"] == "ok"
    assert router["input"]["text"].startswith("route:personal") and "personal" in router["input"]["routes"]
    assert [s["steps"] for s in [router["output"]]] == [router["output"]["steps"]]
    assert [x["agent"] for x in router["output"]["steps"]] == ["personal", "report"]
    assert "fallback" not in router["output"]
    (router_llm,) = [s for s in spans_of(sink, rid, "llm") if s["parent_id"] == router["id"]]
    assert router_llm["usage"]["input"] > 0
    assert [a["name"] for a in agents] == ["personal", "report"] and all(a["parent_id"] == rid for a in agents)
    assert all(a["status"] == "ok" and a["end"] for a in agents) and len({a["id"] for a in agents}) == 2
    assert agents[0]["input"]["task"] == "call:notifications_list {}" and agents[0]["input"]["via"] == "router"
    first_llms = [s for s in spans_of(sink, rid, "llm") if s["parent_id"] == agents[0]["id"]]
    assert len(first_llms) == 2  # gọi tool rồi trả lời
    (tool,) = spans_of(sink, rid, "tool")
    assert tool["name"] == "notifications_list" and tool["parent_id"] == first_llms[0]["id"]
    assert [s["parent_id"] for s in spans_of(sink, rid, "llm") if s["parent_id"] == agents[1]["id"]]
    assert run.status == "done"


async def test_agent_span_status_is_waiting_while_step_awaits_approval(env, confirm_write):
    stack, u, sink = env
    await add_notes(u.id, 2)
    sent, _ = await chat(stack.api, u, "route:personal call:notifications_mark_all_read {}")
    (agent,) = spans_of(sink, sent["run_id"], "agent")
    assert agent["status"] == "waiting" and agent["end"] is None


async def test_clarify_has_router_span_and_no_agent_span(env):
    stack, u, sink = env
    sent, _ = await chat(stack.api, u, "clarify:Ví nào?")
    assert [s["kind"] for s in spans_of(sink, sent["run_id"])] == ["run", "router", "llm"]
    assert not spans_of(sink, sent["run_id"], "agent")


async def test_handoff_step_span_records_via_and_reason(env):
    stack, u, sink = env
    reason = "xem tổng chi"
    sent, _ = await chat(stack.api, u, "route:personal call:handoff " + json.dumps({"to": "report", "reason": reason}))
    agents = spans_of(sink, sent["run_id"], "agent")
    assert [(a["name"], a["input"]["via"]) for a in agents] == [("personal", "router"), ("report", "handoff")]
    assert agents[1]["input"]["task"] == reason


async def test_agent_span_waits_for_approval_then_resumes_same_span(env, confirm_write):
    stack, u, sink = env
    api = stack.api
    await add_notes(u.id, 2)
    sent, run = await chat(api, u, "route:personal,report call:notifications_mark_all_read {} | tổng")
    rid = sent["run_id"]
    (agent,) = spans_of(sink, rid, "agent")
    assert run.status == "waiting_approval" and spans_of(sink, rid, "run")[0]["status"] == "waiting"
    assert agent["name"] == "personal"
    (approval,) = spans_of(sink, rid, "approval")
    (tool,) = spans_of(sink, rid, "tool")
    assert approval["parent_id"] == tool["id"]
    (req,) = await approvals(rid)
    await api.post("agent.decide_approval", u, approval_id=str(req.id), approve=True)
    await runner.resume(rid)
    agents = spans_of(sink, rid, "agent")
    assert [a["name"] for a in agents] == ["personal", "report"] and all(a["status"] == "ok" for a in agents)
    assert agents[0]["end"] is not None and spans_of(sink, rid, "run")[0]["status"] == "ok"
    assert len(spans_of(sink, rid, "router")) == 1  # resume không route lại


def test_span_union_parses_router_and_agent_kinds():
    base = {"id": "x", "run_id": "r", "name": "n", "agent_id": "a", "session_id": "s", "user_id": "u"}
    base["expire_at"] = "2030-01-01T00:00:00Z"
    router = SPAN.validate_python({**base, "kind": "router"})
    agent = SPAN.validate_python({**base, "kind": "agent"})
    assert isinstance(router, RouterSpan) and isinstance(agent, AgentStepSpan)


async def test_noop_tracer_router_and_agent_contexts():
    noop = NoopTracer()
    async with noop.router({"x": 1}) as span:
        assert span.id == ""
    async with noop.agent(0, {"slug": "a"}) as span:
        assert span.id == ""
