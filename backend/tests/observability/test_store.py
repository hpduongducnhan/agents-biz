"""LogStore — chỗ duy nhất đọc / sửa Mongo của trang Event log / Issues (R12): chỉ có khi sink Mongo chạy; lọc,
phân trang, đổi trạng thái, đếm; Mongo chết → 7001."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import AppException
from app.observability.schemas import EventFilter
from app.observability.sinks import capture_issue, get_sinks
from app.observability.store import get_store
from tests.observability.fakes import DownMongoDb, make_entry
from tests.platform_env import eventually

pytestmark = pytest.mark.integration


async def _count(col, n: int) -> bool:
    return await col.count_documents({}) >= n


async def test_store_exists_only_with_mongo(stack):
    assert (get_store() is not None) is stack.settings.MONGO_ENABLED
    assert get_sinks().enabled is stack.settings.MONGO_ENABLED


async def test_event_filters_and_paging(mongo_stack):
    t0 = datetime.now(UTC) - timedelta(hours=1)
    sink = get_sinks().event_log
    await sink.write(make_entry(ts=t0, operation="auth.login", ok=False, error_code=2102))
    await sink.write(make_entry(ts=t0 + timedelta(minutes=1), operation="auth.logout", source="agent"))
    await sink.write(make_entry(ts=t0 + timedelta(minutes=2), operation="notifications.mark_read"))
    await eventually(lambda: _count(mongo_stack.conns.mongo.rw["event_log"], 3))
    store = get_store()

    async def ops(**f) -> list[str]:
        items, _ = await store.list_events(EventFilter(**f), limit=20, offset=0)
        return [i.operation for i in items]

    assert await ops() == ["notifications.mark_read", "auth.logout", "auth.login"]  # mới nhất trước
    assert await ops(operation="auth.") == ["auth.logout", "auth.login"]
    assert await ops(ok=False) == ["auth.login"] and await ops(source="agent") == ["auth.logout"]
    window = {"since": t0 + timedelta(seconds=30), "until": (t0 + timedelta(seconds=90)).replace(tzinfo=None)}
    assert await ops(**window) == ["auth.logout"]
    items, total = await store.list_events(EventFilter(), limit=1, offset=1)
    assert total == 3 and [i.operation for i in items] == ["auth.logout"] and items[0].id


async def test_issue_listing_status_and_count(mongo_stack):
    await capture_issue(ValueError("v"), source="test", loc="obs0911")
    await capture_issue(KeyError("k"), source="test", loc="obs0912")
    await eventually(lambda: _count(mongo_stack.conns.mongo.rw["issues"], 2))
    store = get_store()
    items, total = await store.list_issues(None, limit=20, offset=0)
    assert total == 2 and await store.count_open_issues() == 2
    fp = items[0].fingerprint
    done = await store.set_issue_status(fp, "resolved", by="u-1")
    assert done.status == "resolved" and done.status_changed_by == "u-1" and done.sample.traceback
    assert (await store.list_issues("resolved", limit=20, offset=0))[1] == 1
    assert await store.count_open_issues() == 1
    assert await store.get_issue("b" * 40) is None and await store.set_issue_status("b" * 40, "open", by="u") is None


async def test_mongo_down_is_a_clear_7001(mongo_stack, monkeypatch, bw_log):
    store = get_store()
    monkeypatch.setattr(store, "_ro", DownMongoDb())
    monkeypatch.setattr(store, "_rw", DownMongoDb())
    for call in (
        lambda: store.list_events(EventFilter(), limit=20, offset=0),
        lambda: store.count_open_issues(),
        lambda: store.set_issue_status("a" * 40, "ignored", by="u"),
    ):
        with pytest.raises(AppException) as err:
            await call()
        assert (err.value.code, err.value.status_code) == (7001, 503)
    assert "obs0507" in [line["loc"] for line in bw_log()]
