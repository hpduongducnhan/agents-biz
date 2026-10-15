"""Stack tích hợp có Mongo thật (`bizwithagents_test`) cho test usage / trace: collection `agent_*` sạch, LLM giả,
Studio seed bằng op thật; tài liệu usage / run được ghi thẳng qua `TraceSink` để kiểm số liệu chính xác."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pymongo import AsyncMongoClient

import app.agent.tasks as agent_tasks
from app.agent.trace.spans import RunSpan
from app.credentials import crypto
from app.observability.sinks import get_sinks
from tests.agent import fixtures
from tests.platform_env import Stack, platform_env

COLLECTIONS = ("agent_spans", "agent_http_raw", "agent_llm_calls")


async def drop_agent_collections(settings) -> None:
    assert settings.MONGO_DB_NAME.endswith("_test")
    client = AsyncMongoClient(settings.MONGO_RW_URL)
    try:
        for name in COLLECTIONS:
            await client[settings.MONGO_DB_NAME].drop_collection(name)
    finally:
        await client.close()


@pytest.fixture(params=[pytest.param(True, id="mongo-on"), pytest.param(False, id="mongo-off")])
async def stack(request, test_settings, fake_llm, monkeypatch) -> AsyncIterator[Stack]:
    fixtures.registry._cache.clear()
    fixtures.checkpoint.reset()
    fixtures._client_utils._cached_async_httpx_client.cache_clear()
    monkeypatch.setattr(agent_tasks.run_turn, "kiq", AsyncMock())
    if request.param:
        await drop_agent_collections(test_settings)
    async with platform_env(test_settings, mongo=request.param, CREDENTIAL_KEYS=crypto.new_key()) as env:
        env.mongo = request.param
        env.llm_url = fake_llm.base_url
        try:
            yield env
        finally:
            fixtures.checkpoint.reset()


def call_doc(**over: Any) -> dict[str, Any]:
    """Một document `agent_llm_calls` đủ trường; ghi đè theo từng test."""
    at = over.pop("at", datetime.now(UTC) - timedelta(hours=2))
    doc: dict[str, Any] = {
        "id": uuid.uuid4().hex,
        "at": at,
        "expire_at": at + timedelta(days=90),
        "run_id": str(uuid.uuid4()),
        "session_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "entry_agent_id": str(uuid.uuid4()),
        "agent_id": str(uuid.uuid4()),
        "agent_slug": "assistant",
        "purpose": "agent",
        "model_id": str(uuid.uuid4()),
        "model": "fake-model",
        "provider_id": str(uuid.uuid4()),
        "provider_kind": "openai_compatible",
        "credential_id": str(uuid.uuid4()),
        "key_hint": "sk-…1234",
        "status": "ok",
        "error_kind": None,
        "error": None,
        "latency_ms": 100,
        "ttft_ms": 20,
        "requests": 1,
        "input_tokens": 1000,
        "output_tokens": 100,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost": 0.0,
    }
    doc.update(over)
    return doc


async def put_calls(*docs: dict[str, Any]) -> None:
    sink = get_sinks().traces
    for d in docs:
        await sink.save_call(d)


async def put_run(
    *, user_id: str, agent_id: str | None = None, session_id: str | None = None, **over: Any
) -> dict[str, Any]:
    """Span `run` đã kết thúc ghi thẳng vào Mongo; trả document."""
    rid = over.pop("id", str(uuid.uuid4()))
    start = over.pop("start", datetime.now(UTC) - timedelta(minutes=5))
    span = RunSpan(
        id=rid,
        run_id=rid,
        name="Assistant",
        agent_id=agent_id or str(uuid.uuid4()),
        session_id=session_id or str(uuid.uuid4()),
        user_id=user_id,
        status=over.pop("status", "ok"),
        start=start,
        end=start + timedelta(seconds=3),
        expire_at=start + timedelta(days=90),
        **over,
    )
    doc = span.model_dump(mode="python")
    await get_sinks().traces.save_span(doc)
    return doc
