"""Mỗi lần gọi LLM một document `agent_llm_calls`: trường, loại lỗi, token không gồm cache, chi phí, purpose
router / agent; span run gom agents / models / cost / llm_errors (kể cả khi resume)."""

import asyncio
import json
import uuid
from decimal import Decimal

import pytest

from app.agent.config.models import AgentModel
from app.agent.runtime import runner
from app.agent.trace import usage
from app.agent.trace.tracer import CallMeta, Tracer
from app.core.connections.registry import get_connections
from app.core.rkeys import rkey
from tests.agent import sinks as helper
from tests.agent.helpers import add_keys, add_notes, approvals, chat, load_spec, setup, setup_router, slug_ids

PRICED = {
    "input_price_per_1m": "3",
    "output_price_per_1m": "15",
    "cache_read_price_per_1m": "0.3",
    "cache_write_price_per_1m": "3.75",
}
META = CallMeta("agent", "a1", "personal", "m1", "gpt-x", "p1", "openai")
FIELDS = (
    "id at expire_at run_id session_id user_id tenant_id entry_agent_id agent_id agent_slug purpose model_id model "
    "provider_id provider_kind credential_id key_hint status error_kind error latency_ms ttft_ms requests input_tokens "
    "output_tokens cache_read_tokens cache_write_tokens cost"
).split()


def fake_run():
    return type(
        "R",
        (),
        {
            "id": uuid.uuid4(),
            "entry_agent_id": uuid.uuid4(),
            "session_id": uuid.uuid4(),
            "user_id": uuid.uuid4(),
            "tenant_id": uuid.uuid4(),
        },
    )()


class HttpError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"http {status}")
        self.status_code = status


def span_of(sink, run_id, kind="run"):
    return next(s for s in sink.spans.values() if s["run_id"] == run_id and s["kind"] == kind)


@pytest.fixture
async def sink(trace_sink):
    return trace_sink


@pytest.fixture
async def env(api, aenv, rt, kicks, fake_llm, trace_sink):
    stack = await setup(api, fake_llm.base_url, **PRICED)
    return stack, await api.as_user("u@x.io"), trace_sink


# ── Tracer trực tiếp: loại lỗi, huỷ, tên trường ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (HttpError(429), "rate"),
        (HttpError(401), "auth"),
        (HttpError(403), "auth"),
        (HttpError(500), "server"),
        (HttpError(503), "server"),
        (ValueError("lạ"), "other"),
        (HttpError(400), "other"),
    ],
)
async def test_error_call_doc_kind_and_run_counters(sink, exc, kind):
    tracer = Tracer(fake_run(), sink, resuming=False)
    with pytest.raises(type(exc)):
        async with tracer.llm([], {}, None, META):
            raise exc
    await tracer.flush()
    (doc,) = sink.calls
    assert doc["status"] == "error" and doc["error_kind"] == kind and doc["requests"] == 1
    assert doc["error"] and doc["ttft_ms"] is None
    assert tracer._llm_errors == 1


async def test_error_text_is_redacted_and_truncated(sink):
    tracer = Tracer(fake_run(), sink, resuming=False)
    with pytest.raises(ValueError, match="x"):
        async with tracer.llm([], {}, None, META):
            raise ValueError("x" * 2000)
    await tracer.flush()
    assert len(sink.calls[0]["error"]) <= 500


async def test_cancelled_call_is_not_an_error(sink):
    tracer = Tracer(fake_run(), sink, resuming=False)
    with pytest.raises(asyncio.CancelledError):
        async with tracer.llm([], {}, None, META):
            raise asyncio.CancelledError
    await tracer.flush()
    (doc,) = sink.calls
    assert doc["status"] == "cancelled" and doc["error_kind"] is None and doc["error"] is None
    assert tracer._llm_errors == 0


async def test_no_call_meta_writes_no_doc_and_ok_doc_has_all_fields(sink):
    tracer = Tracer(fake_run(), sink, resuming=False)
    async with tracer.llm([], {}, None, None):
        pass
    async with tracer.llm([], {}, None, META) as span:
        span.usage = {"input": 1000, "output": 50, "cache_read": 400, "cache_write": 100}
    await tracer.flush()
    (doc,) = sink.calls
    assert set(doc) == set(FIELDS) and doc["status"] == "ok" and doc["id"] == span.id
    assert (doc["input_tokens"], doc["cache_read_tokens"], doc["cache_write_tokens"], doc["output_tokens"]) == (
        500,
        400,
        100,
        50,
    )
    assert doc["agent_slug"] == "personal" and doc["purpose"] == "agent" and doc["provider_kind"] == "openai"
    assert doc["expire_at"] > doc["at"] and doc["latency_ms"] >= 0


async def test_sink_failure_on_calls_never_breaks_the_call(sink):
    sink.fail = True
    tracer = Tracer(fake_run(), sink, resuming=False)
    async with tracer.llm([], {}, None, META):
        pass
    await tracer.flush()
    assert sink.calls == []


# ── Qua lượt chạy thật (LLM giả) ────────────────────────────────────────────────────────────────────────────────────
async def test_ok_call_doc_tokens_exclude_cache_and_cost_from_prices(env):
    stack, u, sink = env
    sent, run = await chat(stack.api, u, "xin chào bạn")
    (doc,) = sink.calls
    assert doc["status"] == "ok" and doc["error_kind"] is None and doc["error"] is None
    assert doc["run_id"] == sent["run_id"] and doc["user_id"] == u.id and doc["purpose"] == "agent"
    assert doc["credential_id"] == stack.cred_id and doc["key_hint"] and "fake-key" not in json.dumps(doc, default=str)
    assert (
        doc["model_id"] == stack.model_id and doc["model"] == "fake-model" and doc["provider_id"] == stack.provider_id
    )
    assert doc["provider_kind"] == "openai_compatible" and doc["agent_slug"] == "assistant"
    assert doc["cache_read_tokens"] >= 0 and doc["input_tokens"] + doc["cache_read_tokens"] == run.tokens_in
    assert doc["output_tokens"] == run.tokens_out
    async with get_connections().postgres.ro() as s:
        model = await s.get(AgentModel, uuid.UUID(stack.model_id))
    want = usage.cost_of(
        model,
        {k: doc[k] for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")},
    )
    assert want > 0 and Decimal(str(doc["cost"])) == want and run.cost == want
    run_span = span_of(sink, sent["run_id"])
    assert run_span["cost"] == float(want) and run_span["models"] == ["fake-model"] and run_span["llm_errors"] == 0
    assert run_span["agents"] == ["assistant"]
    assert span_of(sink, sent["run_id"], "llm")["cost"] == float(want)


async def test_two_llm_calls_two_docs_and_run_cost_is_their_sum(env):
    stack, u, sink = env
    sent, run = await chat(stack.api, u, "call:notifications_list {}")
    assert len(sink.calls) == 2 and len({c["id"] for c in sink.calls}) == 2
    assert run.cost == sum(Decimal(str(c["cost"])) for c in sink.calls)
    assert span_of(sink, sent["run_id"])["cost"] == pytest.approx(float(run.cost), abs=1e-6)


async def test_router_vs_agent_purpose_agents_and_models(team, api, aenv, rt, kicks, fake_llm, trace_sink):
    stack = await setup_router(api, fake_llm.base_url)
    u = await api.as_user("u@x.io")
    sent, run = await chat(api, u, "route:personal,report call:notifications_list {} | xem tổng")
    ids = await slug_ids()
    by_purpose = {}
    for c in trace_sink.calls:
        by_purpose.setdefault(c["purpose"], []).append(c)
    assert len(by_purpose["router"]) == 1 and len(by_purpose["agent"]) == 3  # router + personal (2 lần) + report
    (router,) = by_purpose["router"]
    assert router["agent_slug"] == "assistant" and router["agent_id"] == str(ids["assistant"])
    assert {c["agent_slug"] for c in by_purpose["agent"]} == {"personal", "report"}
    assert all(c["entry_agent_id"] == str(ids["assistant"]) for c in trace_sink.calls)
    run_span = span_of(trace_sink, sent["run_id"])
    assert run_span["agents"] == ["personal", "report"] and run_span["models"] == ["fake-model"]
    assert run_span["llm_errors"] == 0 and stack and run.status == "done"


async def test_run_error_counters_per_status(api, aenv, rt, kicks, fake_llm, trace_sink):
    stack = await setup(api, fake_llm.base_url)
    u = await api.as_user("u@x.io")
    sent, run = await chat(api, u, "fail500 đi")
    assert run.status == "failed"
    docs = trace_sink.calls
    assert docs and {c["status"] for c in docs} == {"error"} and {c["error_kind"] for c in docs} == {"server"}
    run_span = span_of(trace_sink, sent["run_id"])
    assert run_span["llm_errors"] == len(docs) and run_span["status"] == "error" and run_span["cost"] == 0
    assert all(c["input_tokens"] == 0 and c["cost"] == 0 for c in docs) and stack


@pytest.mark.parametrize(("key", "kind"), [("bad-key", "auth"), ("ratelimit-key", "rate")])
async def test_provider_rejects_key_is_classified(api, aenv, rt, kicks, fake_llm, trace_sink, key, kind):
    await setup(api, fake_llm.base_url, key=key)
    u = await api.as_user("u@x.io")
    sent, run = await chat(api, u, "xin chào")
    assert run.status == "failed"
    (doc,) = trace_sink.calls
    assert doc["status"] == "error" and doc["error_kind"] == kind and doc["error"]
    assert span_of(trace_sink, sent["run_id"])["llm_errors"] == 1


async def test_rotating_to_good_key_records_error_then_ok(api, aenv, rt, kicks, fake_llm, trace_sink):
    stack = await setup(api, fake_llm.base_url)
    a, b = await add_keys(stack, ["bad-key-A", "fake-key"], strategy="round_robin")
    spec = await load_spec(stack.agent_id)
    await get_connections().redis.rw.set(rkey("rr", str(spec.id)), sorted([a, b]).index(a))  # vòng đầu rơi vào key xấu
    u = await api.as_user("u@x.io")
    sent, run = await chat(api, u, "xin chào")
    assert run.status == "done"
    assert sorted(c["status"] for c in trace_sink.calls) == ["error", "ok"]
    assert span_of(trace_sink, sent["run_id"])["llm_errors"] == 1


# ── resume ─────────────────────────────────────────────────────────────────────────────────────────────────────────
async def test_resume_merges_run_summary_from_existing_span(env, confirm_write):
    stack, u, sink = env
    api = stack.api
    await add_notes(u.id, 2)
    sent, _ = await chat(api, u, "call:notifications_mark_all_read {}")
    rid = sent["run_id"]
    first = span_of(sink, rid)
    assert first["status"] == "waiting" and first["cost"] > 0 and first["models"] == ["fake-model"]
    sink.spans[rid].update(llm_errors=3)  # đoạn trước đã ghi thêm
    (req,) = await approvals(rid)
    await api.post("agent.decide_approval", u, approval_id=str(req.id), approve=True, reason="ok")
    await runner.resume(rid)
    after = span_of(sink, rid)
    assert after["status"] == "ok" and after["cost"] > first["cost"]
    assert after["llm_errors"] == 3 and after["models"] == ["fake-model"] and after["agents"] == ["assistant"]
    assert len(sink.calls) == 2 and helper
