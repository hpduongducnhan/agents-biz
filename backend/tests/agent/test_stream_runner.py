"""Stream chat (D23): lượt với chat_stream bật / tắt, cửa sổ gom flush_ms, resume, span."""

import pytest

from app.agent.runtime import runner
from app.agent.testing import fake_llm as fl
from tests.agent.helpers import approvals, chat, events_of, messages, run_row, setup

pytestmark = pytest.mark.integration


@pytest.fixture
async def env(api, aenv, rt, kicks, fake_llm, trace_sink):
    stack = await setup(api, fake_llm.base_url)
    u = await api.as_user("u@x.io")
    yield stack, u, rt, trace_sink
    await api.post("system.update_settings", stack.root, chat_stream=True, chat_stream_flush_ms=50)


async def configure(stack, **values):
    await stack.api.post("system.update_settings", stack.root, **values)


def tokens(rt, u):
    return [d["delta"] for _, d in events_of(rt, u.id, "agent:token")]


async def test_stream_on_emits_many_tokens_and_start_flag(env):
    stack, u, rt, sink = env
    await configure(stack, chat_stream=True, chat_stream_flush_ms=20)
    sent, run = await chat(stack.api, u, "xin chào các bạn thân mến nhé")
    assert run.status == "done"
    deltas = tokens(rt, u)
    assert len(deltas) >= 2 and "".join(deltas) == "Bạn nói: xin chào các bạn thân mến nhé"
    assert events_of(rt, u.id, "agent:start")[0][1]["stream"] is True
    assert fl.REQUESTS[0]["body"].get("stream") is True


async def test_stream_off_one_token_and_plain_request(env):
    stack, u, rt, sink = env
    await configure(stack, chat_stream=False)
    sent, run = await chat(stack.api, u, "xin chào các bạn thân mến nhé")
    assert run.status == "done"
    names = [e for e, _ in events_of(rt, u.id)]
    assert names.count("agent:token") == 1
    full = "Bạn nói: xin chào các bạn thân mến nhé"
    assert tokens(rt, u) == [full]
    assert "agent:llm" in names and names.index("agent:token") < names.index("agent:llm")
    assert events_of(rt, u.id, "agent:start")[0][1]["stream"] is False
    assert not fl.REQUESTS[0]["body"].get("stream")
    answer = (await messages(sent["session_id"]))[-1]
    assert answer.content["text"] == full
    assert run.tokens_out > 0  # usage vẫn có khi gọi một lần


async def test_stream_off_one_token_per_model_call_with_tools(env):
    stack, u, rt, sink = env
    await configure(stack, chat_stream=False)
    sent, run = await chat(stack.api, u, "call:notifications_list {}")
    assert run.status == "done"
    llm_calls = len(events_of(rt, u.id, "agent:llm"))
    assert len(tokens(rt, u)) <= llm_calls and len(tokens(rt, u)) >= 1
    assert all(not r["body"].get("stream") for r in fl.REQUESTS)


async def test_flush_ms_500_gives_fewer_token_events_than_20(env):
    stack, u, rt, sink = env
    await configure(stack, chat_stream=True, chat_stream_flush_ms=20)
    await chat(stack.api, u, "slow một")
    first = len(tokens(rt, u))
    await configure(stack, chat_stream_flush_ms=500)
    await chat(stack.api, u, "slow hai")
    total = len(events_of(rt, u.id, "agent:token"))
    coarse = total - first
    assert first >= 20 and 3 <= coarse <= first // 2, (first, coarse)


async def test_resume_rereads_settings(env, confirm_write):
    stack, u, rt, sink = env
    api = stack.api
    await configure(stack, chat_stream=True)
    sent, run = await chat(api, u, "call:notifications_mark_all_read {}")
    assert run.status == "waiting_approval"
    assert events_of(rt, u.id, "agent:start")[0][1]["stream"] is True
    before = len(events_of(rt, u.id, "agent:token"))
    (req,) = await approvals(sent["run_id"])
    await api.post("agent.decide_approval", u, approval_id=str(req.id), approve=True)
    await configure(stack, chat_stream=False)  # đổi giữa lúc chờ duyệt
    await runner.resume(sent["run_id"])
    assert (await run_row(sent["run_id"])).status == "done"
    after = events_of(rt, u.id, "agent:token")[before:]
    assert len(after) == 1 and after[0][1]["delta"].startswith("Kết quả: ")
    assert not fl.REQUESTS[-1]["body"].get("stream")


async def test_run_span_has_stream_input_and_off_sets_ttft(env):
    stack, u, rt, sink = env
    await configure(stack, chat_stream=False, chat_stream_flush_ms=200)
    sent, run = await chat(stack.api, u, "xin chào")
    rid = sent["run_id"]
    spans = [s for s in sink.spans.values() if s["run_id"] == rid]
    (run_span,) = [s for s in spans if s["kind"] == "run"]
    assert run_span["input"]["stream"] == {"on": False, "flush_ms": 200, "defaults_applied": []}
    (llm_span,) = [s for s in spans if s["kind"] == "llm"]
    assert llm_span["ttft_ms"] is not None and llm_span["ttft_ms"] >= 0
    latency_ms = (llm_span["end"] - llm_span["start"]).total_seconds() * 1000
    assert abs(llm_span["ttft_ms"] - latency_ms) <= 50  # gọi một lần: chữ đầu = cả lần gọi


async def test_run_span_stream_on_defaults(env):
    stack, u, rt, sink = env
    sent, run = await chat(stack.api, u, "xin chào")
    (run_span,) = [s for s in sink.spans.values() if s["run_id"] == sent["run_id"] and s["kind"] == "run"]
    assert run_span["input"]["stream"] == {"on": True, "flush_ms": 50, "defaults_applied": []}
