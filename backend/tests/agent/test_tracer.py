"""Tracer (R19): cây span run → llm → tool → approval qua TraceSink; trace hỏng không làm hỏng lượt; tắt → Noop."""

import json
import uuid

import pytest

from app.agent.runtime import runner
from app.agent.trace.noop import NoopTracer
from app.agent.trace.spans import SPAN, ApprovalSpan, LlmSpan, RunSpan, ToolSpan
from app.agent.trace.tracer import Tracer, tracer_for
from app.core.http_rules import HttpLogRules
from app.core.httpx_log import install_httpx_logging, uninstall_httpx_logging
from app.core.redact import build_keys
from app.observability.sinks import get_sinks
from tests.agent import sinks as helper
from tests.agent.helpers import add_notes, approvals, chat, setup

SECRET = "sk-live-abcdef-wxyz1234"


@pytest.fixture
async def env(api, aenv, rt, kicks, fake_llm, trace_sink):
    stack = await setup(api, fake_llm.base_url, key=SECRET)
    u = await api.as_user("u@x.io")
    return stack, u, trace_sink


def by_kind(sink, run_id):
    spans = sorted((s for s in sink.spans.values() if s["run_id"] == run_id), key=lambda s: s["seq"])
    return {k: [s for s in spans if s["kind"] == k] for k in ("run", "llm", "tool", "approval", "hook")}


async def test_tracer_tree_run_llm_tool_approval(env, confirm_write):
    stack, u, sink = env
    api = stack.api
    await add_notes(u.id, 2)
    sent, run = await chat(api, u, "call:notifications_mark_all_read {}")
    rid = sent["run_id"]
    spans = by_kind(sink, rid)
    (run_span,) = spans["run"]
    assert run_span["id"] == rid and run_span["status"] == "waiting" and run_span["end"] is None
    assert run_span["input"]["model"]["model_id"] == "fake-model" and run_span["input"]["user"]["id"] == u.id
    assert any(t["name"] == "notifications_mark_all_read" for t in run_span["input"]["tools"])
    (llm1,) = spans["llm"]
    (tool,) = spans["tool"]
    (approval,) = spans["approval"]
    assert llm1["parent_id"] == rid and tool["parent_id"] == llm1["id"] and approval["parent_id"] == tool["id"]
    assert tool["status"] == "waiting" and approval["status"] == "waiting"
    assert llm1["output"]["tool_calls"][0]["name"] == "notifications_mark_all_read" and llm1["status"] == "ok"
    (req,) = await approvals(rid)
    await api.post("agent.decide_approval", u, approval_id=str(req.id), approve=True, reason="ok")
    await runner.resume(rid)
    after = by_kind(sink, rid)
    assert (
        len(after["run"]) == 1 and len(after["tool"]) == 1 and len(after["approval"]) == 1
    )  # resume cập nhật, không nhân đôi
    assert after["run"][0]["status"] == "ok" and after["run"][0]["end"] and after["run"][0]["usage"]["input"] > 0
    assert (
        after["tool"][0]["status"] == "ok"
        and after["tool"][0]["output"]["result"]
        and after["tool"][0]["input"]["real_args"] == {}
    )
    assert after["approval"][0]["status"] == "ok" and after["approval"][0]["output"]["status"] == "approved"
    assert after["approval"][0]["output"]["decided_by"] == u.id and after["approval"][0]["output"]["reason"] == "ok"
    assert len(after["llm"]) == 2 and after["llm"][1]["parent_id"] == rid
    seqs = [s["seq"] for s in sink.spans.values() if s["run_id"] == rid]
    assert len(seqs) == len(set(seqs))  # seq không trùng sau resume
    for doc in sink.spans.values():
        SPAN.validate_python(doc)
    assert isinstance(SPAN.validate_python(after["tool"][0]), ToolSpan)
    assert isinstance(SPAN.validate_python(after["approval"][0]), ApprovalSpan)
    assert isinstance(SPAN.validate_python(after["run"][0]), RunSpan) and isinstance(
        SPAN.validate_python(llm1), LlmSpan
    )


async def test_llm_span_records_credential_hint_not_secret(env):
    stack, u, sink = env
    sent, run = await chat(stack.api, u, "xin chào")
    (llm,) = by_kind(sink, sent["run_id"])["llm"]
    assert llm["credential_id"] == stack.cred_id and llm["masked_hint"] == "sk-…1234"
    assert llm["usage"]["input"] > 0 and llm["ttft_ms"] is not None and llm["output"]["text"] == "Bạn nói: xin chào"
    assert llm["input"]["prompt"]["system"] and "<context>" in llm["input"]["prompt"]["new"]
    blob = json.dumps(list(sink.spans.values()), default=str)
    assert SECRET not in blob and "fake-key" not in blob


async def test_tool_error_and_provider_error_spans(env):
    stack, u, sink = env
    sent, _ = await chat(stack.api, u, 'call:notifications_mark_read {"ids": []}')
    (tool,) = by_kind(sink, sent["run_id"])["tool"]
    assert tool["status"] == "error" and tool["error"].startswith("Lỗi ")
    failed, run = await chat(stack.api, u, "fail500")
    spans = by_kind(sink, failed["run_id"])
    assert run.status == "failed" and spans["run"][0]["status"] == "error"
    assert spans["run"][0]["error"] and all(s["status"] == "error" for s in spans["llm"])


async def test_raw_http_captured_and_redacted(env):
    stack, u, sink = env
    install_httpx_logging(HttpLogRules.empty(), build_keys(frozenset()), log=False)
    try:
        sent, _ = await chat(stack.api, u, "chụp raw")
    finally:
        uninstall_httpx_logging()
    (llm,) = by_kind(sink, sent["run_id"])["llm"]
    assert len(llm["raw_ids"]) == 1 and [r["id"] for r in sink.raws] == llm["raw_ids"]
    raw = sink.raws[0]
    assert raw["method"] == "POST" and raw["url"].endswith("/chat/completions") and raw["span_id"] == llm["id"]
    assert json.loads(raw["request"]["body"])["model"] == "fake-model" and raw["response"]["status"] == 200
    assert SECRET not in json.dumps(raw, default=str)
    assert raw["request"]["headers"]["authorization"] != f"Bearer {SECRET}"


async def test_sink_failure_never_breaks_the_run(env, bw_log):
    stack, u, sink = env
    sink.fail = True
    sent, run = await chat(stack.api, u, "sink hỏng")
    assert run.status == "done" and sink.spans == {}
    assert any(r.get("loc") == "agt0505" for r in bw_log())


async def test_tracer_for_is_noop_when_sink_disabled(env):
    stack, u, sink = env
    run = type(
        "R",
        (),
        {"id": uuid.uuid4(), "entry_agent_id": uuid.uuid4(), "session_id": uuid.uuid4(), "user_id": uuid.uuid4()},
    )()
    assert isinstance(tracer_for(run, resuming=False), Tracer)
    helper.uninstall()
    assert not get_sinks().traces.enabled and isinstance(tracer_for(run, resuming=False), NoopTracer)
    noop = tracer_for(run, resuming=True)
    async with noop.llm([], {}, None) as span:
        assert span.id == ""
    assert await noop.start_run() is None and noop.hook(None, "x", {}) is None and await noop.flush() is None
    sent, result = await chat(stack.api, u, "không trace")
    assert result.status == "done"
