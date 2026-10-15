"""traces.* trên Mongo thật (`bizwithagents_test`): list / get / raw; Mongo tắt → `enabled: false`; chỉ superadmin."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from pymongo import AsyncMongoClient

import app.agent.tasks as agent_tasks
from app.core.http_rules import HttpLogRules
from app.core.httpx_log import install_httpx_logging, uninstall_httpx_logging
from app.core.redact import build_keys
from app.credentials import crypto
from app.observability.sinks import get_sinks
from tests.agent import fixtures
from tests.agent.helpers import chat, get_root, setup
from tests.platform_env import eventually, platform_env

SECRET = "sk-live-abcdef-wxyz1234"


async def drop_trace_collections(settings) -> None:
    client = AsyncMongoClient(settings.MONGO_RW_URL)
    try:
        for name in ("agent_spans", "agent_http_raw", "agent_llm_calls"):
            await client[settings.MONGO_DB_NAME].drop_collection(name)
    finally:
        await client.close()


@pytest.fixture(params=[pytest.param(True, id="mongo-on"), pytest.param(False, id="mongo-off")])
async def stack(request, test_settings, fake_llm, monkeypatch):
    fixtures.registry._cache.clear()
    fixtures.checkpoint.reset()
    fixtures._client_utils._cached_async_httpx_client.cache_clear()
    monkeypatch.setattr(agent_tasks.run_turn, "kiq", AsyncMock())
    if request.param:
        await drop_trace_collections(test_settings)
    async with platform_env(test_settings, mongo=request.param, CREDENTIAL_KEYS=crypto.new_key()) as env:
        install_httpx_logging(HttpLogRules.empty(), build_keys(frozenset()), log=False)
        env.mongo = request.param
        env.llm_url = fake_llm.base_url
        try:
            yield env
        finally:
            uninstall_httpx_logging()
            fixtures.checkpoint.reset()


async def test_traces_ops_superadmin_only_and_disabled_when_mongo_off(stack):
    api = stack.api
    admin = await api.as_user("adm@x.io", roles=("admin",))
    rid = str(uuid.uuid4())
    for method, op, kw in (
        ("GET", "traces.list", {}),
        ("GET", "traces.get", {"params": {"run_id": rid}}),
        ("GET", "traces.raw", {"params": {"run_id": rid, "raw_id": "x"}}),
    ):
        assert await api.err(method, op, admin, **kw) == (403, 1005), op
    root = await get_root(api)
    listed = await api.get("traces.list", root)
    tree = await api.get("traces.get", root, run_id=rid)
    raw = await api.get("traces.raw", root, run_id=rid, raw_id="x")
    assert listed["items"] == [] and listed["total"] == 0 and tree["spans"] == [] and raw["item"] is None
    assert (listed["enabled"], tree["enabled"], raw["enabled"]) == ((stack.mongo,) * 3)
    assert get_sinks().traces.enabled is stack.mongo


async def test_traces_list_get_raw_roundtrip_on_mongo(stack):
    if not stack.mongo:
        pytest.skip("cần Mongo bật")
    api = stack.api
    await setup(api, stack.llm_url, key=SECRET)
    root = await get_root(api)
    u = await api.as_user("u@x.io")
    first, run1 = await chat(api, u, "call:notifications_list {}")
    second, run2 = await chat(api, u, "fail500")
    assert run1.status == "done" and run2.status == "failed"
    await eventually(lambda: get_sinks().traces.count_spans(first["run_id"]))
    page = await eventually(lambda: _list_ready(api, root))
    assert {r["id"] for r in page["items"]} == {first["run_id"], second["run_id"]} and page["enabled"]
    assert all(r["kind"] == "run" for r in page["items"])
    only_ok = await api.get("traces.list", root, status="ok")
    assert [r["id"] for r in only_ok["items"]] == [first["run_id"]]
    assert (await api.get("traces.list", root, user_id=str(uuid.uuid4())))["total"] == 0
    assert (await api.get("traces.list", root, agent_id=page["items"][0]["agent_id"]))["total"] == 2
    window = await api.get(
        "traces.list",
        root,
        since=(datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        until=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    )
    assert window["total"] == 2
    assert (await api.get("traces.list", root, until=(datetime.now(UTC) - timedelta(hours=1)).isoformat()))[
        "total"
    ] == 0
    assert len((await api.get("traces.list", root, limit=1))["items"]) == 1
    tree = await eventually(lambda: _tree_ready(api, root, first["run_id"]))
    kinds = [s["kind"] for s in tree["spans"]]
    assert kinds[0] == "run" and kinds.count("llm") == 2 and kinds.count("tool") == 1
    llm = next(s for s in tree["spans"] if s["kind"] == "llm")
    assert llm["masked_hint"] == "sk-…1234" and SECRET not in json.dumps(tree)
    raw_id = llm["raw_ids"][0]
    raw = await api.get("traces.raw", root, run_id=first["run_id"], raw_id=raw_id)
    assert raw["item"]["method"] == "POST" and raw["item"]["request"]["headers"]["authorization"] != f"Bearer {SECRET}"
    assert SECRET not in json.dumps(raw)
    assert (await api.get("traces.raw", root, run_id=first["run_id"], raw_id="nope"))["item"] is None
    assert (await api.get("traces.raw", root, run_id=second["run_id"], raw_id=raw_id))[
        "item"
    ] is None  # raw của run khác


async def test_mongo_indexes_have_ttl(stack):
    if not stack.mongo:
        pytest.skip("cần Mongo bật")
    client = AsyncMongoClient(stack.settings.MONGO_RW_URL)
    try:
        for name in ("agent_spans", "agent_http_raw", "agent_llm_calls"):
            info = await client[stack.settings.MONGO_DB_NAME][name].index_information()
            ttl = [v for v in info.values() if v.get("expireAfterSeconds") == 0 and v["key"] == [("expire_at", 1)]]
            assert ttl, f"{name} thiếu TTL theo expire_at"
    finally:
        await client.close()


async def _list_ready(api, root):
    page = await api.get("traces.list", root)
    return page if page["total"] == 2 and all(r["status"] != "running" for r in page["items"]) else None


async def _tree_ready(api, root, run_id):
    tree = await api.get("traces.get", root, run_id=run_id)
    ok = any(s["kind"] == "run" and s["status"] == "ok" for s in tree["spans"])
    return tree if ok else None
