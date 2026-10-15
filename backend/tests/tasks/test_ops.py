"""tasks.* qua REST: tạo / sửa / giao / trạng thái / xoá / bình luận, lọc + phân trang, quyền theo role có sẵn, tách
tổ chức (404 chéo, giao chéo → 10002), thông báo người được giao / bình luận, `data:changed` tới cả tổ chức (R18)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from tests.auth.api import data_of
from tests.conftest import until
from tests.tasks.helpers import create, notifications_of, world

pytestmark = pytest.mark.integration


@pytest.fixture
async def w(api):
    return await world(api)


def iso(delta: timedelta) -> str:
    return (datetime.now(UTC) + delta).isoformat()


async def test_paths_follow_convention(api):
    paths = (await api.call("GET", "/openapi.json")).json()["paths"]
    for op in ("list", "get", "summary", "people"):
        assert "get" in paths[f"/bizwithagents/api/tasks/{op}"], op
    for op in ("create", "update", "assign", "set_status", "delete", "add_comment"):
        assert "post" in paths[f"/bizwithagents/api/tasks/{op}"], op


async def test_create_get_update_and_defaults(w):
    api = w.api
    t = await create(
        api, w.member, title="  Gọi khách  ", description="Báo giá", priority="high", due_at=iso(timedelta(days=1))
    )
    assert (t["title"], t["status"], t["priority"], t["source"], t["comment_count"]) == (
        "Gọi khách",
        "todo",
        "high",
        "web",
        0,
    )
    assert t["created_by"]["name"] == "Lan" and t["assignee"] is None and not t["overdue"]
    got = await api.get("tasks.get", w.viewer, task_id=t["id"])
    assert got["title"] == "Gọi khách" and got["comments"] == []
    upd = await api.post("tasks.update", w.member, task_id=t["id"], title="Gọi lại khách", due_at=None)
    assert (
        upd["title"] == "Gọi lại khách" and upd["due_at"] is None and upd["priority"] == "high"
    )  # trường không gửi giữ nguyên
    assert await api.err("POST", "tasks.create", w.member, json={"title": "   "}) == (422, 1002)
    assert await api.err("POST", "tasks.create", w.member, json={"title": "x", "status": "zombie"}) == (422, 1002)
    assert await api.err("GET", "tasks.get", w.member, params={"task_id": str(uuid.uuid4())}) == (404, 10001)


async def test_status_sets_completed_at_and_overdue_flag(w):
    api = w.api
    t = await create(api, w.member, due_at=iso(-timedelta(hours=2)))
    assert t["overdue"] is True
    done = await api.post("tasks.set_status", w.member, task_id=t["id"], status="done")
    assert done["status"] == "done" and done["completed_at"] and done["overdue"] is False
    back = await api.post("tasks.set_status", w.member, task_id=t["id"], status="todo")
    assert back["completed_at"] is None and back["overdue"] is True


async def test_roles(w):
    api = w.api
    t = await create(api, w.member)
    body = {"title": "x"}
    assert await api.err("POST", "tasks.create", w.viewer, json=body) == (403, 1005)
    assert (await api.get("tasks.list", w.viewer))["total"] == 1  # viewer xem được
    assert await api.err("POST", "tasks.delete", w.member, json={"task_id": t["id"]}) == (403, 1005)
    assert await api.post("tasks.delete", w.admin, task_id=t["id"]) is None
    assert await api.err("GET", "tasks.get", w.admin, params={"task_id": t["id"]}) == (404, 10001)


async def test_other_tenant_cannot_see_or_touch(w):
    api = w.api
    t = await create(api, w.member, title="Bí mật")
    assert (await api.get("tasks.list", w.other))["total"] == 0
    assert await api.err("GET", "tasks.get", w.other, params={"task_id": t["id"]}) == (404, 10001)
    for op, extra in (("tasks.update", {"title": "hack"}), ("tasks.set_status", {"status": "done"}),
                      ("tasks.add_comment", {"body": "hi"})):  # fmt: skip
        assert await api.err("POST", op, w.other, json={"task_id": t["id"], **extra}) == (404, 10001), op
    mine = await create(api, w.other, title="Của Acme")
    assert [x["title"] for x in (await api.get("tasks.list", w.member))["items"]] == ["Bí mật"]
    assert mine["title"] == "Của Acme"
    people = {p["name"] for p in await api.get("tasks.people", w.member)}
    assert {"Sếp", "Lan", "Người xem"} <= people and "Far" not in people


async def test_assign_only_within_tenant_and_notifies(w):
    api = w.api
    t = await create(api, w.admin, title="Báo cáo tháng")
    assert await api.err("POST", "tasks.assign", w.admin, json={"task_id": t["id"], "assignee_id": w.other.id}) == (
        422,
        10002,
    )
    out = await api.post("tasks.assign", w.admin, task_id=t["id"], assignee_id=w.member.id)
    assert out["assignee"] == {"id": w.member.id, "name": "Lan"}
    assert await until(lambda: True)
    (note,) = await notifications_of(w.member.id)
    assert note.kind == "task_assigned" and note.params == {"title": "Báo cáo tháng", "by": "Sếp"}
    assert note.action == {"kind": "link", "to": f"/tasks?task={t['id']}"}
    await api.post("tasks.assign", w.admin, task_id=t["id"], assignee_id=w.member.id)  # không đổi → không báo lại
    assert len(await notifications_of(w.member.id)) == 1
    self_made = await create(api, w.member, title="Tự giao", assignee_id=w.member.id)
    assert self_made["assignee"]["id"] == w.member.id and len(await notifications_of(w.member.id)) == 1
    cleared = await api.post("tasks.assign", w.admin, task_id=t["id"], assignee_id=None)
    assert cleared["assignee"] is None


async def test_comments_notify_assignee_and_creator_not_author(w):
    api = w.api
    t = await create(api, w.admin, title="Hợp đồng", assignee_id=w.member.id)
    c = await api.post("tasks.add_comment", w.member, task_id=t["id"], body="  Đã gửi bản nháp  ")
    assert (c["body"], c["author"]["name"]) == ("Đã gửi bản nháp", "Lan")
    notes = [n.kind for n in await notifications_of(w.admin.id)]
    assert notes == ["task_commented"]  # người tạo nhận; người viết (Lan) không tự nhận
    detail = await api.get("tasks.get", w.viewer, task_id=t["id"])
    assert [x["body"] for x in detail["comments"]] == ["Đã gửi bản nháp"] and detail["comment_count"] == 1
    assert await api.err("POST", "tasks.add_comment", w.viewer, json={"task_id": t["id"], "body": "x"}) == (403, 1005)


async def test_filters_sort_and_paging(w):
    api = w.api
    late = await create(api, w.admin, title="Trễ", due_at=iso(-timedelta(days=1)), assignee_id=w.member.id)
    soon = await create(api, w.admin, title="Sắp", due_at=iso(timedelta(days=2)), priority="urgent")
    later = await create(api, w.admin, title="Xa", due_at=iso(timedelta(days=30)))
    nodue = await create(api, w.admin, title="Không hạn thư", description="gửi thư cảm ơn")
    done = await create(api, w.admin, title="Xong rồi", status="done", due_at=iso(-timedelta(days=3)))

    async def titles(**q):
        return [x["title"] for x in (await api.get("tasks.list", w.member, **q))["items"]]

    assert await titles() == ["Xong rồi", "Trễ", "Sắp", "Xa", "Không hạn thư"]  # theo hạn, không hạn cuối
    assert await titles(due="overdue") == ["Trễ"]  # việc xong không tính quá hạn
    assert await titles(due="week") == ["Sắp"]
    assert await titles(due="none") == ["Không hạn thư"]
    assert await titles(mine="true") == ["Trễ"]
    assert await titles(assignee_id=w.member.id) == ["Trễ"]
    assert (await titles(open_only="true", sort="priority"))[0] == "Sắp"
    assert await titles(status="done") == ["Xong rồi"]
    assert await titles(q="THƯ") == ["Không hạn thư"]  # tìm cả mô tả, không phân biệt hoa thường
    page = await api.get("tasks.list", w.member, limit=2, offset=2)
    assert (page["total"], len(page["items"])) == (5, 2)
    assert await api.err("GET", "tasks.list", w.member, params={"limit": 101}) == (422, 1002)
    s = await api.get("tasks.summary", w.member)
    assert (s["todo"], s["done"], s["overdue"], s["mine_open"], s["mine_overdue"]) == (4, 1, 1, 1, 1)
    assert {late["id"], soon["id"], later["id"], nodue["id"], done["id"]}


async def test_writes_tell_the_whole_tenant(w, rt):
    api = w.api
    tid = (await api.get("auth.me", w.member))["tenant"]["id"]
    before = len(data_of(rt, f"tenant.{tid}", "data:changed"))
    other_before = len(data_of(rt, f"tenant.{w.acme_id}", "data:changed"))
    await create(api, w.member)
    assert await until(lambda: len(data_of(rt, f"tenant.{tid}", "data:changed")) > before)
    keys = data_of(rt, f"tenant.{tid}", "data:changed")[-1]["keys"]
    assert {"tasks.list", "tasks.detail", "tasks.summary"} <= set(keys)
    assert len(data_of(rt, f"tenant.{w.acme_id}", "data:changed")) == other_before
