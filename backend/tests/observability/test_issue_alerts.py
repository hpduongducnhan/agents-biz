"""Issue trên Mongo thật: upsert `$inc`, `recent` ≤ 20, mẫu mới nhất, resolved → mở lại, ignored giữ nguyên;
`issue_new` tối đa 1 lần / fingerprint / giờ cho superadmin đang hoạt động (Review Focus 2)."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial

import pytest
from sqlalchemy import func
from sqlmodel import select

from app.core.cid import set_cid
from app.core.connections.documents import init_documents
from app.notifications.models import Notification
from app.observability import alerts
from app.observability.alerts import alert_key, notify_new_issue
from app.observability.capture import fingerprint
from app.observability.documents import MODELS, EventLogDoc, IssueDoc
from app.observability.mongo_sinks import MongoSinks, event_log_ttl_days
from app.observability.sinks import Sinks, capture_issue, get_sinks, set_sinks
from tests.auth.factories import make_user
from tests.platform_env import eventually, rt_listener, superadmin

pytestmark = pytest.mark.integration


@asynccontextmanager
async def running_sinks(stack) -> AsyncIterator[MongoSinks]:
    """Sink Mongo thật + báo issue qua Redis, gắn làm sink của process trong khối."""
    await init_documents(stack.conns.mongo, MODELS)
    sinks = MongoSinks(
        EventLogDoc.get_pymongo_collection(),
        IssueDoc.get_pymongo_collection(),
        ttl_days=event_log_ttl_days,
        alert=partial(notify_new_issue, stack.conns.redis.rw),
    )
    sinks.start()
    old = get_sinks()
    set_sinks(Sinks(event_log=sinks.event_log, issues=sinks.issues, enabled=True))
    try:
        yield sinks
    finally:
        set_sinks(old)
        await sinks.stop(timeout=1.0)


def _boom(i: int = 0) -> ValueError:
    try:
        raise ValueError(f"lỗi {i}")
    except ValueError as exc:
        return exc


async def _issue_new_counts(stack) -> dict[uuid.UUID, int]:
    async with stack.conns.postgres.ro() as session:
        stmt = (
            select(Notification.user_id, func.count())
            .where(Notification.kind == "issue_new")
            .group_by(Notification.user_id)
        )
        return dict((await session.exec(stmt)).all())


async def _counts_are(stack, want: dict) -> bool:
    return await _issue_new_counts(stack) == want


async def test_upsert_counts_keeps_recent_20_and_reopens(mongo_stack):
    issues = mongo_stack.conns.mongo.rw["issues"]
    async with running_sinks(mongo_stack):
        for i in range(25):
            set_cid(f"cid-{i}")
            context = {"operation": "t.op", "user_id": "u-1", "extra": {"password": "x"}}
            await capture_issue(_boom(i), source="test", loc="obs0901", context=context)
        doc = await eventually(lambda: issues.find_one({"count": 25}))
        assert doc["status"] == "open" and doc["first_seen"] <= doc["last_seen"]
        assert [r["cid"] for r in doc["recent"]] == [f"cid-{i}" for i in range(5, 25)]
        assert doc["title"] == "ValueError: lỗi 24"  # tiêu đề + mẫu theo lần gần nhất
        assert (doc["exc_type"], doc["loc"], doc["source"]) == ("ValueError", "obs0901", "test")
        assert (doc["sample"]["operation"], doc["sample"]["user_id"]) == ("t.op", "u-1")
        assert doc["sample"]["context"] == {"extra": {"password": "[REDACTED]"}}
        await issues.update_one({"_id": doc["_id"]}, {"$set": {"status": "resolved"}})
        await capture_issue(_boom(), source="test", loc="obs0901")
        await eventually(lambda: issues.find_one({"count": 26, "status": "open"}))
        await issues.update_one({"_id": doc["_id"]}, {"$set": {"status": "ignored"}})
        await capture_issue(_boom(), source="test", loc="obs0901")
        still = await eventually(lambda: issues.find_one({"count": 27}))
        assert still["status"] == "ignored"  # bỏ qua thì gặp lại vẫn bỏ qua


async def test_repeated_issue_notifies_superadmins_once_per_hour(mongo_stack):
    root = await superadmin(mongo_stack)
    await mongo_stack.api.as_user("u@x.io")
    async with mongo_stack.conns.postgres.rw() as session:
        await make_user(session, "off@x.io", is_superadmin=True, is_active=False)  # superadmin đã bị khoá: không nhận
    issues = mongo_stack.conns.mongo.rw["issues"]
    want = {uuid.UUID(root.id): 1}
    async with running_sinks(mongo_stack):
        for i in range(50):
            await capture_issue(_boom(i), source="test", loc="obs0902")
        doc = await eventually(lambda: issues.find_one({"count": 50}))
        await eventually(lambda: _counts_are(mongo_stack, want))
        redis = mongo_stack.conns.redis.rw
        assert 0 < await redis.ttl(alert_key(doc["fingerprint"])) <= alerts.ALERT_TTL

        # resolved rồi gặp lại trong cùng giờ → mở lại nhưng KHÔNG báo lần nữa
        await issues.update_one({"_id": doc["_id"]}, {"$set": {"status": "resolved"}})
        await capture_issue(_boom(), source="test", loc="obs0902")
        await eventually(lambda: issues.find_one({"count": 51, "status": "open"}))
        await asyncio.sleep(0.3)
        assert await _issue_new_counts(mongo_stack) == want

        # qua một giờ (khoá hết hạn) → resolved rồi gặp lại → báo thêm đúng 1
        await redis.delete(alert_key(doc["fingerprint"]))
        await issues.update_one({"_id": doc["_id"]}, {"$set": {"status": "resolved"}})
        await capture_issue(_boom(), source="test", loc="obs0902")
        await eventually(lambda: _counts_are(mongo_stack, {uuid.UUID(root.id): 2}))


async def test_new_issue_pushes_notification_and_refresh_to_superadmins(mongo_stack):
    root = await superadmin(mongo_stack)
    async with running_sinks(mongo_stack), rt_listener(mongo_stack) as rt:
        await rt.bind(f"user.{root.id}", "sup")
        await capture_issue(_boom(), source="test", loc="obs0903")
        [note] = await eventually(lambda: rt.data(f"user.{root.id}", "core:notification"))
        refresh = await eventually(lambda: rt.data("sup", "data:changed"))
    assert note["kind"] == "issue_new" and note["title"].startswith("Issue mới: ValueError")
    assert note["params"]["fingerprint"] == fingerprint(_boom(), "obs0903") and note["params"]["reopened"] is False
    assert note["action"] == {"kind": "link", "to": f"/sa/issues?fingerprint={note['params']['fingerprint']}"}
    assert {"keys": ["observability"]} in refresh


async def test_alert_failure_releases_throttle_key(mongo_stack, monkeypatch, bw_log):
    async def pg_down(*args, **kwargs):
        raise ConnectionError("pg down")

    monkeypatch.setattr(alerts, "notify_superadmins", pg_down)
    exc = _boom()
    async with running_sinks(mongo_stack):
        await capture_issue(exc, source="test", loc="obs0904")
        await eventually(lambda: "obs0505" in [line["loc"] for line in bw_log()])
    assert await mongo_stack.conns.redis.rw.exists(alert_key(fingerprint(exc, "obs0904"))) == 0
