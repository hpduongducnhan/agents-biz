"""TTL span / raw HTTP lấy từ cài đặt hệ thống (`span_ttl_days`, `raw_http_ttl_days`); đọc lỗi → mặc định + WARNING."""

from datetime import UTC, datetime, timedelta

import pytest

from app.agent.trace import tracer as tracer_mod
from app.core.http_rules import HttpLogRules
from app.core.httpx_log import install_httpx_logging, uninstall_httpx_logging
from app.core.redact import build_keys
from app.system import settings_store
from tests.agent.helpers import chat, get_root, setup

DAY = timedelta(days=1)


@pytest.fixture
async def env(api, aenv, rt, kicks, fake_llm, trace_sink):
    stack = await setup(api, fake_llm.base_url)
    return stack, await api.as_user("u@x.io"), trace_sink


def expire(doc) -> datetime:
    value = doc["expire_at"]
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def days_left(doc) -> float:
    return (expire(doc) - datetime.now(UTC)) / DAY


async def raw_run(stack, user):
    install_httpx_logging(HttpLogRules.empty(), build_keys(frozenset()), log=False)
    try:
        return await chat(stack.api, user, "chụp raw")
    finally:
        uninstall_httpx_logging()


async def test_default_ttl_when_settings_untouched(env):
    stack, u, sink = env
    await raw_run(stack, u)
    spans = list(sink.spans.values())
    assert spans and all(abs(days_left(s) - 90) < 0.01 for s in spans)
    assert sink.raws and all(abs(days_left(r) - 7) < 0.01 for r in sink.raws)


async def test_ttl_follows_system_settings(env):
    stack, u, sink = env
    root = await get_root(stack.api)
    await stack.api.post("system.update_settings", root, span_ttl_days=5, raw_http_ttl_days=2)
    await raw_run(stack, u)
    spans = list(sink.spans.values())
    assert {s["kind"] for s in spans} >= {"run", "llm"} and all(abs(days_left(s) - 5) < 0.01 for s in spans)
    assert sink.raws and all(abs(days_left(r) - 2) < 0.01 for r in sink.raws)
    await stack.api.post("system.update_settings", root, span_ttl_days=30)
    sink.spans.clear()
    await chat(stack.api, u, "lượt hai")
    assert all(abs(days_left(s) - 30) < 0.01 for s in sink.spans.values())


async def test_settings_read_failure_uses_default_ttl_and_warns(env, monkeypatch, bw_log):
    stack, u, sink = env

    async def boom():
        raise ConnectionError("redis chết")

    monkeypatch.setattr(settings_store, "cached_system_settings", boom)
    sent, run = await chat(stack.api, u, "vẫn chạy")
    assert run.status == "done"  # đọc cài đặt hỏng không làm hỏng lượt
    assert sink.spans and all(abs(days_left(s) - 90) < 0.01 for s in sink.spans.values())
    warn = [line for line in bw_log() if line.get("loc") == "agt0507"]
    assert len(warn) == 1 and warn[0]["level"] == "WARNING"
    assert (
        "DEFAULTS_APPLIED=[span_ttl_days=90, raw_http_ttl_days=7]" in warn[0]["msg"] and "redis chết" in warn[0]["msg"]
    )
    assert tracer_mod.SPAN_TTL == 90 * DAY and tracer_mod.RAW_TTL == 7 * DAY
