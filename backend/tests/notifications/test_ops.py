"""notifications.*: inbox của chính mình — REST (Api thật), socket và agent đi cùng runner; phân trang R14;
dọn sau 90 ngày."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import BaseModel
from sqlalchemy import update
from sqlmodel import select

from app.core.security.principal import Principal
from app.notifications.consumers import ws_mark_read
from app.notifications.models import Notification
from app.notifications.ops import MarkReadIn
from app.notifications.schemas import register_kind
from app.notifications.service import notify_users
from app.notifications.tasks import RETENTION_DAYS, cleanup, delete_older_than
from tests.platform_env import as_principal, eventually, rt_listener, superadmin

pytestmark = pytest.mark.integration


class NoteParams(BaseModel):
    pass


register_kind("test_note", NoteParams)


@dataclass
class FakeWs:
    """Thay `WsContext` — handler chỉ dùng `principal` (và `reply`)."""

    principal: Principal
    sid: str | None = None
    cid: str | None = "ws-test"
    event: str = "notifications.mark_read"
    replies: list = field(default_factory=list)

    async def reply(self, event: str, data=None) -> None:
        self.replies.append((event, data))


async def _note(who, title: str) -> Notification:
    (row,) = await notify_users([who.id], "test_note", title)
    return row


async def _by_id(stack) -> dict[uuid.UUID, Notification]:
    async with stack.conns.postgres.ro() as session:
        return {n.id: n for n in (await session.exec(select(Notification))).all()}


async def test_list_count_mark_read_mark_all_read_over_rest(stack):
    api = stack.api
    a, b = await api.as_user("a@x.io"), await api.as_user("b@x.io")
    first = await _note(a, "t1")
    await _note(a, "t2")
    await _note(b, "của B")
    listed = await api.get("notifications.list", a)
    assert (listed["total"], listed["limit"], listed["offset"]) == (2, 20, 0)
    assert [i["title"] for i in listed["items"]] == ["t2", "t1"]  # mới nhất trước
    assert await api.get("notifications.unread_count", a) == {"count": 2}
    assert await api.post("notifications.mark_read", a, ids=[str(first.id)]) == {"updated": 1}
    assert await api.post("notifications.mark_read", a, ids=[str(first.id)]) == {"updated": 0}
    assert (await api.get("notifications.list", a, unread_only="true"))["total"] == 1
    page = await api.get("notifications.list", a, limit=1, offset=1)
    assert page["total"] == 2 and [i["title"] for i in page["items"]] == ["t1"]
    assert await api.post("notifications.mark_all_read", a) == {"updated": 1}
    assert await api.get("notifications.unread_count", a) == {"count": 0}
    assert await api.get("notifications.unread_count", b) == {"count": 1}


async def test_mark_read_never_touches_other_users_notifications(stack):
    api = stack.api
    a, b = await api.as_user("a@x.io"), await api.as_user("b@x.io")
    sa = await superadmin(stack)
    mine, theirs = await _note(a, "của A"), await _note(b, "của B")
    assert await api.post("notifications.mark_read", a, ids=[str(theirs.id)]) == {"updated": 0}
    assert await api.post("notifications.mark_read", sa, ids=[str(theirs.id)]) == {"updated": 0}  # superadmin cũng vậy
    assert await api.post("notifications.mark_read", a, ids=[str(uuid.uuid4())]) == {"updated": 0}
    await ws_mark_read(FakeWs(as_principal(a)), MarkReadIn(ids=[theirs.id, mine.id]))
    rows = await _by_id(stack)
    assert rows[theirs.id].read_at is None and rows[mine.id].read_at is not None
    assert [i["id"] for i in (await api.get("notifications.list", a))["items"]] == [str(mine.id)]


async def test_validation_paging_limit_and_login(stack):
    api = stack.api
    a = await api.as_user("a@x.io")
    assert await api.err("GET", "notifications.list") == (401, 1004)
    assert await api.err("GET", "notifications.list", a, params={"limit": 101}) == (422, 1002)  # R14
    for body in ({"ids": []}, {"ids": [str(uuid.uuid4())] * 101}, {"ids": ["khong-phai-uuid"]}):
        assert await api.err("POST", "notifications.mark_read", a, json=body) == (422, 1002)


async def test_mark_read_refreshes_other_tabs(stack):
    a = await stack.api.as_user("a@x.io")
    note = await _note(a, "t")
    async with rt_listener(stack) as rt:
        await rt.bind(f"user.{a.id}")
        await stack.api.post("notifications.mark_read", a, ids=[str(note.id)])
        [changed] = await eventually(lambda: rt.data(f"user.{a.id}", "data:changed"))
    assert "notifications" in changed["keys"]


async def test_send_test_notifies_the_user_in_realtime(stack):
    api, sa = stack.api, await superadmin(stack)
    u = await api.as_user("u@x.io")
    async with rt_listener(stack) as rt:
        await rt.bind(f"user.{u.id}")
        out = await api.post("notifications.send_test", sa, email="  U@x.io ", title="Thử", body="nội dung")
        [data] = await eventually(lambda: rt.data(f"user.{u.id}", "core:notification"))
    assert data["id"] == out["notification_id"]
    got = (data["kind"], data["title"], data["body"], data["params"], data["action"])
    assert got == ("test", "Thử", "nội dung", {}, None)
    assert data["read_at"] is None and data["created_at"]
    assert [i["id"] for i in (await api.get("notifications.list", u))["items"]] == [out["notification_id"]]
    missing = {"email": "khong-co@x.io", "title": "x"}
    assert await api.err("POST", "notifications.send_test", sa, json=missing) == (404, 1001)
    assert await api.err("POST", "notifications.send_test", u, json={"email": "u@x.io", "title": "x"}) == (403, 1005)
    for title in ("", "t" * 201):
        body = {"email": "u@x.io", "title": title}
        assert await api.err("POST", "notifications.send_test", sa, json=body) == (422, 1002)


async def test_cleanup_deletes_only_older_than_90_days(plain_stack):
    a = await plain_stack.api.as_user("a@x.io")
    old, recent = await _note(a, "cũ"), await _note(a, "mới")
    now = datetime.now(UTC)
    async with plain_stack.conns.postgres.rw() as session:
        for row_id, age in ((old.id, timedelta(days=RETENTION_DAYS, minutes=1)), (recent.id, timedelta(days=89))):
            await session.exec(update(Notification).where(Notification.id == row_id).values(created_at=now - age))
    assert await delete_older_than(RETENTION_DAYS) == 1
    assert set(await _by_id(plain_stack)) == {recent.id}
    assert await cleanup() == 0  # task cron gọi đúng hàm trên
