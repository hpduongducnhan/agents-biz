"""Sink Mongo: hàng đợi giới hạn (đầy thì bỏ + đếm, không chờ), ghi nền theo lô, document có kiểu + đã che, TTL theo
cài đặt; Mongo chết lúc chạy không làm chậm request (Review Focus 1)."""

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pymongo import AsyncMongoClient
from pymongo.errors import DuplicateKeyError

from app.core.connections.documents import init_documents
from app.core.operations.runner import run_operation
from app.observability.documents import MODELS, EventLogDoc, IssueDoc
from app.observability.mongo_sinks import MongoSinks, event_log_ttl_days
from app.observability.sinks import Sinks, capture_issue, get_sinks, set_sinks
from app.system.settings_store import update_system_settings
from tests.observability.fakes import make_entry
from tests.platform_env import as_principal, eventually


async def _ttl180() -> int:
    return 180


class SlowCollection:
    """Collection giả: `insert_many` chờ tới khi mở cổng — mô phỏng Mongo treo."""

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.docs: list[dict] = []

    async def insert_many(self, docs, ordered=False):
        await self.gate.wait()
        self.docs.extend(docs)


class RaceIssues:
    """Collection giả: lần upsert đầu đụng DuplicateKey (process khác vừa chèn cùng fingerprint)."""

    def __init__(self) -> None:
        self.calls: list[bool] = []

    async def find_one_and_update(self, where, change, upsert=False, return_document=None):
        self.calls.append(upsert)
        if len(self.calls) == 1:
            raise DuplicateKeyError("E11000 duplicate key")
        return {"fingerprint": where["fingerprint"], "status": "open", "count": 1}


def _open_gate() -> SlowCollection:
    col = SlowCollection()
    col.gate.set()
    return col


# ── hàng đợi: không cần hạ tầng ──────────────────────────────────────────────


async def test_full_queue_drops_with_counter_and_never_blocks(bw_log):
    sinks = MongoSinks(SlowCollection(), SlowCollection(), ttl_days=_ttl180, max_queue=5)  # chưa start
    started = time.perf_counter()
    for i in range(12):
        await sinks.event_log.write(make_entry(operation=f"t.op{i}"))
    assert time.perf_counter() - started < 0.05
    assert sinks.stats() == {"queued": 5, "written": 0, "dropped": 7, "failed": 0}
    assert [line["loc"] for line in bw_log()].count("obs0502") == 1


async def test_stop_flushes_what_is_queued():
    events = _open_gate()
    sinks = MongoSinks(events, SlowCollection(), ttl_days=_ttl180)
    sinks.start()
    for i in range(3):
        await sinks.event_log.write(make_entry(operation=f"t.op{i}"))
    await sinks.stop(timeout=1.0)
    assert [d["operation"] for d in events.docs] == ["t.op0", "t.op1", "t.op2"]
    assert sinks.stats()["written"] == 3 and not sinks.running


async def test_stop_never_hangs_on_a_stuck_mongo(bw_log):
    sinks = MongoSinks(SlowCollection(), SlowCollection(), ttl_days=_ttl180, batch=1)
    sinks.start()
    for i in range(3):
        await sinks.event_log.write(make_entry(operation=f"t.op{i}"))
    started = time.perf_counter()
    await sinks.stop(timeout=0.2)
    assert time.perf_counter() - started < 1.0 and not sinks.running
    assert "obs0504" in [line["loc"] for line in bw_log()]


async def test_event_doc_is_typed_redacted_and_bounded():
    events = _open_gate()
    sinks = MongoSinks(events, SlowCollection(), ttl_days=_ttl180)
    sinks.start()
    uid, run = uuid.uuid4(), uuid.uuid4()
    await sinks.event_log.write(
        make_entry(
            actor_id=uid,
            actor_sup=True,
            agent_run_id=run,
            input={"password": "p@ss", "new_password": "x", "amount": 5, "to": uid},
        )
    )
    await sinks.event_log.write(make_entry(input={"note": "x" * 20_000}))
    await sinks.event_log.write(make_entry(ts=datetime(2026, 10, 12, 8, 0)))  # ts không múi giờ
    await sinks.stop(timeout=1.0)
    first, big, naive = events.docs
    assert (first["actor_id"], first["actor_kind"], first["is_superadmin"]) == (str(uid), "user", True)
    assert first["agent_run_id"] == str(run)
    assert first["input"] == {"password": "[REDACTED]", "new_password": "[REDACTED]", "amount": 5, "to": str(uid)}
    assert big["input"]["_truncated"] is True and len(big["input"]["preview"]) == 16_000
    assert big["actor_kind"] == "system" and naive["ts"].tzinfo is UTC
    assert naive["expire_at"] - naive["ts"] == timedelta(days=180)


async def test_ttl_provider_failure_falls_back_to_default(bw_log):
    async def broken() -> int:
        raise ConnectionError("pg down")

    events = _open_gate()
    sinks = MongoSinks(events, SlowCollection(), ttl_days=broken, default_ttl_days=180)
    sinks.start()
    ts = datetime(2026, 10, 12, tzinfo=UTC)
    await sinks.event_log.write(make_entry(ts=ts))
    await sinks.stop(timeout=1.0)
    assert events.docs[0]["expire_at"] == ts + timedelta(days=180)
    [line] = [line for line in bw_log() if line["loc"] == "obs0506"]
    assert "DEFAULTS_APPLIED=[event_log_ttl_days]" in line["msg"]


async def test_concurrent_insert_race_becomes_an_update_without_alert(bw_log):
    alerts: list[dict] = []

    async def alert(issue: dict) -> None:
        alerts.append(issue)

    issues = RaceIssues()
    sinks = MongoSinks(SlowCollection(), issues, ttl_days=_ttl180, alert=alert)
    sinks.start()
    await sinks.issues.capture(ValueError("x"), source="test", loc="obs0900", cid=None, context={})
    await sinks.stop(timeout=1.0)
    assert issues.calls == [True, False] and alerts == []
    assert sinks.stats()["written"] == 1 and "obs0004" in [line["loc"] for line in bw_log()]


# ── Mongo thật ────────────────────────────────────────────────────────────────


@pytest.mark.integration
async def test_event_log_expire_at_follows_setting(mongo_stack):
    await init_documents(mongo_stack.conns.mongo, MODELS)
    sinks = MongoSinks(
        EventLogDoc.get_pymongo_collection(), IssueDoc.get_pymongo_collection(), ttl_days=event_log_ttl_days
    )
    sinks.start()
    col = mongo_stack.conns.mongo.rw["event_log"]
    ts = datetime.now(UTC).replace(microsecond=0)
    try:
        await sinks.event_log.write(make_entry(ts=ts, operation="t.default"))
        doc = await eventually(lambda: col.find_one({"operation": "t.default"}))
        assert doc["expire_at"] - doc["ts"] == timedelta(days=180)
        async with mongo_stack.conns.postgres.rw() as session:
            await update_system_settings(session, {"event_log_ttl_days": 7})
        await sinks.event_log.write(make_entry(ts=ts, operation="t.short"))
        doc = await eventually(lambda: col.find_one({"operation": "t.short"}))
        assert doc["expire_at"] - doc["ts"] == timedelta(days=7)
    finally:
        await sinks.stop(timeout=1.0)


@pytest.mark.integration
async def test_requests_unaffected_when_mongo_dies_at_runtime(mongo_stack, bw_log):
    user = await mongo_stack.api.as_user("a@x.io")
    dead = AsyncMongoClient("mongodb://127.0.0.1:1", serverSelectionTimeoutMS=300)
    sinks = MongoSinks(dead["x"]["event_log"], dead["x"]["issues"], ttl_days=_ttl180)
    sinks.start()
    old = get_sinks()
    set_sinks(Sinks(event_log=sinks.event_log, issues=sinks.issues, enabled=True))
    try:
        started = time.perf_counter()
        for _ in range(5):
            await run_operation("notifications.mark_all_read", as_principal(user), None)
        await capture_issue(RuntimeError("boom"), source="test", loc="obs0905")
        assert time.perf_counter() - started < 2.0  # 5 thao tác ghi thật + 1 issue, không chờ Mongo
        await eventually(lambda: sinks.stats()["failed"] >= 6, timeout=10)
        assert "obs0503" in [line["loc"] for line in bw_log()]
    finally:
        set_sinks(old)
        await sinks.stop(timeout=0.5)
        await dead.close()
