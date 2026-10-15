"""observability.* qua REST thật: chỉ superadmin; lọc + phân trang (R14); đổi trạng thái issue làm mới trang của
superadmin khác; Mongo tắt → enabled:false; Mongo chết lúc đọc → 7001."""

from datetime import UTC, datetime, timedelta

import pytest

from app.observability.sinks import capture_issue, get_sinks
from app.observability.store import get_store
from tests.observability.fakes import DownMongoDb, make_entry
from tests.platform_env import eventually, rt_listener, superadmin

pytestmark = pytest.mark.integration
FP = "a" * 40
CALLS = (
    ("GET", "observability.list_events", {"params": {}}),
    ("GET", "observability.list_issues", {"params": {}}),
    ("GET", "observability.get_issue", {"params": {"fingerprint": FP}}),
    ("POST", "observability.set_issue_status", {"json": {"fingerprint": FP, "status": "resolved"}}),
)


async def _at_least(col, n: int) -> bool:
    return await col.count_documents({}) >= n


async def test_superadmin_only(stack):
    user = await stack.api.as_user("u@x.io")
    for method, op, kw in CALLS:
        assert await stack.api.err(method, op, user, **kw) == (403, 1005), op
        assert await stack.api.err(method, op, None, **kw) == (401, 1004), op


async def test_disabled_mode_answers_enabled_false(plain_stack):
    api, sa = plain_stack.api, await superadmin(plain_stack)
    empty = {"enabled": False, "items": [], "total": 0, "limit": 20, "offset": 0}
    assert await api.get("observability.list_events", sa) == empty
    assert (await api.get("observability.list_issues", sa))["enabled"] is False
    assert await api.get("observability.get_issue", sa, fingerprint=FP) == {"enabled": False, "item": None}
    assert await api.post("observability.set_issue_status", sa, fingerprint=FP, status="resolved") == {
        "enabled": False,
        "item": None,
    }


async def test_list_events_over_rest(mongo_stack):
    api, sa = mongo_stack.api, await superadmin(mongo_stack)
    user = await api.as_user("u@x.io")
    await api.post("notifications.mark_all_read", user)  # runner ghi event log thật
    t0 = datetime.now(UTC) - timedelta(hours=1)
    await get_sinks().event_log.write(make_entry(ts=t0, operation="auth.login", ok=False, error_code=2102))
    col = mongo_stack.conns.mongo.rw["event_log"]
    await eventually(lambda: col.find_one({"operation": "notifications.mark_all_read"}))
    await eventually(lambda: col.find_one({"operation": "auth.login", "ok": False}))
    page = await api.get("observability.list_events", sa, operation="notifications.")
    assert page["enabled"] is True and page["total"] == 1 and (page["limit"], page["offset"]) == (20, 0)
    item = page["items"][0]
    assert (item["operation"], item["actor_id"], item["ok"], item["source"]) == (
        "notifications.mark_all_read",
        user.id,
        True,
        "web",
    )
    assert {"id", "ts", "cid", "actor_kind", "is_superadmin", "effect", "duration_ms"} <= set(item)
    failed = await api.get("observability.list_events", sa, ok="false", since=(t0 - timedelta(seconds=1)).isoformat())
    assert [i["operation"] for i in failed["items"]] == ["auth.login"]
    assert await api.err("GET", "observability.list_events", sa, params={"limit": 101}) == (422, 1002)


async def test_issues_list_get_and_set_status(mongo_stack):
    api, sa = mongo_stack.api, await superadmin(mongo_stack)
    for i in range(3):
        await capture_issue(ValueError(f"v{i}"), source="test", loc="obs0921", context={"path": "/x"})
    await capture_issue(KeyError("k"), source="test", loc="obs0922")
    issues = mongo_stack.conns.mongo.rw["issues"]
    await eventually(lambda: issues.find_one({"count": 3}))
    await eventually(lambda: _at_least(issues, 2))
    listed = await api.get("observability.list_issues", sa)
    assert listed["enabled"] is True and listed["total"] == 2 and {i["count"] for i in listed["items"]} == {3, 1}
    assert all("traceback" not in i["sample"] and "recent" not in i for i in listed["items"])
    fp = next(i["fingerprint"] for i in listed["items"] if i["count"] == 3)
    full = (await api.get("observability.get_issue", sa, fingerprint=fp))["item"]
    assert full["sample"]["path"] == "/x" and "ValueError" in full["sample"]["traceback"] and len(full["recent"]) == 3
    async with rt_listener(mongo_stack) as rt:
        await rt.bind("sup")
        out = await api.post("observability.set_issue_status", sa, fingerprint=fp, status="resolved")
        refresh = await eventually(lambda: rt.data("sup", "data:changed"))
    assert out["item"]["status"] == "resolved" and out["item"]["status_changed_by"] == sa.id
    assert {"keys": ["observability"]} in refresh
    assert (await api.get("observability.list_issues", sa, status="resolved"))["total"] == 1
    assert (await api.get("observability.list_issues", sa, status="open"))["total"] == 1


async def test_unknown_or_malformed_fingerprint(mongo_stack):
    api, sa = mongo_stack.api, await superadmin(mongo_stack)
    assert await api.err("GET", "observability.get_issue", sa, params={"fingerprint": "b" * 40}) == (404, 7002)
    body = {"fingerprint": "b" * 40, "status": "ignored"}
    assert await api.err("POST", "observability.set_issue_status", sa, json=body) == (404, 7002)
    for params in ({"fingerprint": "xyz"}, {"fingerprint": "B" * 40}):
        assert await api.err("GET", "observability.get_issue", sa, params=params) == (422, 1002)
    assert await api.err("GET", "observability.list_issues", sa, params={"status": "closed"}) == (422, 1002)
    bad = {"fingerprint": "b" * 40, "status": "closed"}
    assert await api.err("POST", "observability.set_issue_status", sa, json=bad) == (422, 1002)


async def test_mongo_down_on_read_is_a_clear_503(mongo_stack, monkeypatch):
    api, sa = mongo_stack.api, await superadmin(mongo_stack)
    monkeypatch.setattr(get_store(), "_ro", DownMongoDb())
    for method, op, kw in CALLS[:3]:
        assert await api.err(method, op, sa, **kw) == (503, 7001), op
