"""Thông báo: notifier của runner ghi inbox SAU commit rồi đẩy `core:notification`; rollback thì không có gì;
`params` / `action` có kiểu (R13)."""

import uuid
from dataclasses import dataclass

import pytest
from pydantic import BaseModel, ConfigDict
from sqlmodel import select

from app.core.errors import AppException
from app.core.operations.context import OpContext
from app.core.operations.runner import run_operation
from app.core.operations.spec import operation
from app.notifications import service
from app.notifications.models import Notification
from app.notifications.schemas import LinkAction, register_kind
from tests.auth.factories import make_user
from tests.platform_env import as_principal, eventually, rt_listener

pytestmark = pytest.mark.integration


class ProbeParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    n: int


register_kind("test_probe", ProbeParams)


class ProbeIn(BaseModel):
    to: uuid.UUID
    fail: bool = False


@operation(
    name="fx.test_notify_probe",
    title="Probe thông báo (test)",
    description="Chỉ dùng trong test: gọi ctx.notify rồi (tuỳ chọn) ném lỗi để rollback",
    effect="write",
    invalidates=("notifications",),
)
async def notify_probe(ctx: OpContext, inp: ProbeIn) -> dict:
    ctx.notify(inp.to, "test_probe", "Xin chào", body="thân", params={"n": 1}, action={"kind": "link", "to": "/x"})
    if inp.fail:
        raise AppException(1003)
    return {}


@dataclass
class Pending:
    user_id: uuid.UUID | str
    kind: str
    title: str
    body: str = ""
    params: dict | None = None
    action: dict | None = None


async def inbox(stack, user_id) -> list[Notification]:
    async with stack.conns.postgres.ro() as session:
        stmt = (
            select(Notification)
            .where(Notification.user_id == uuid.UUID(str(user_id)))
            .order_by(Notification.created_at)
        )
        return list((await session.exec(stmt)).all())


async def test_ctx_notify_writes_inbox_after_commit_and_pushes(stack):
    a = await stack.api.as_user("a@x.io")
    b = await stack.api.as_user("b@x.io")
    async with rt_listener(stack) as rt:
        await rt.bind(f"user.{b.id}")
        await run_operation("fx.test_notify_probe", as_principal(a), {"to": b.id})
        [data] = await eventually(lambda: rt.data(f"user.{b.id}", "core:notification"))
    rows = await inbox(stack, b.id)
    assert [(r.kind, r.title, r.body, r.params, r.action, r.read_at) for r in rows] == [
        ("test_probe", "Xin chào", "thân", {"n": 1}, {"kind": "link", "to": "/x"}, None)
    ]
    assert data == service.payload(rows[0]) | {"created_at": data["created_at"]}
    assert (data["id"], data["kind"], data["action"]) == (str(rows[0].id), "test_probe", {"kind": "link", "to": "/x"})


async def test_rollback_writes_and_pushes_nothing(stack):
    a = await stack.api.as_user("a@x.io")
    b = await stack.api.as_user("b@x.io")
    async with rt_listener(stack) as rt:
        await rt.bind(f"user.{b.id}")
        with pytest.raises(AppException):
            await run_operation("fx.test_notify_probe", as_principal(a), {"to": b.id, "fail": True})
        assert await rt.data(f"user.{b.id}", "core:notification") == []
    assert await inbox(stack, b.id) == []


async def test_notify_users_dedupes_validates_and_caps_title(plain_stack):
    a = await plain_stack.api.as_user("a@x.io")
    b = await plain_stack.api.as_user("b@x.io")
    rows = await service.notify_users([a.id, uuid.UUID(a.id), b.id], "test_probe", "t" * 400, params=ProbeParams(n=2))
    assert sorted(str(r.user_id) for r in rows) == sorted([a.id, b.id]) and all(len(r.title) == 300 for r in rows)
    link = await service.notify_users([a.id], "test_probe", "có link", params={"n": 3}, action=LinkAction(to="/sa"))
    assert link[0].action == {"kind": "link", "to": "/sa"}
    for kind, params, action in (
        ("chua_dang_ky", {}, None),
        ("test_probe", {"n": "không phải số"}, None),
        ("test_probe", {"n": 1, "thừa": 1}, None),
        ("test_probe", {"n": 1}, {"kind": "link", "to": "khong-bat-dau-bang-gach"}),
        ("test_probe", {"n": 1}, {"kind": "la", "to": "/x"}),
    ):
        with pytest.raises(ValueError):
            await service.notify_users([a.id], kind, "t", params=params, action=action)
    assert len(await inbox(plain_stack, a.id)) == 2  # dữ liệu sai không ghi gì


async def test_notify_superadmins_targets_active_superadmins_only(plain_stack):
    root = await plain_stack.api.as_user("root@test.local")  # trong SUPERADMIN_EMAILS → login bật cờ
    await plain_stack.api.as_user("u@x.io")
    async with plain_stack.conns.postgres.rw() as session:
        await make_user(session, "off@x.io", is_superadmin=True, is_active=False)  # superadmin đã bị khoá
    async with plain_stack.conns.postgres.ro() as session:
        ids = await service.superadmin_ids(session)
    assert ids == [uuid.UUID(root.id)]
    rows = await service.notify_superadmins(
        "issue_new", "Issue mới", params={"fingerprint": "a" * 40, "loc": "exc0500", "source": "http"}
    )
    assert [str(r.user_id) for r in rows] == [root.id]


async def test_deliver_pending_skips_bad_items_and_never_raises(plain_stack, monkeypatch, bw_log):
    a = await plain_stack.api.as_user("a@x.io")
    await service.deliver_pending(
        [
            Pending(user_id=a.id, kind="test_probe", title="tốt", params={"n": 1}),
            Pending(user_id=a.id, kind="test_probe", title="xấu", params={"n": "x"}),
            Pending(user_id="khong-phai-uuid", kind="test_probe", title="xấu", params={"n": 1}),
        ]
    )
    assert [r.title for r in await inbox(plain_stack, a.id)] == ["tốt"]
    assert [line["loc"] for line in bw_log()].count("ntf0503") == 2
    await service.deliver_pending([Pending(user_id=uuid.uuid4(), kind="test_probe", title="t", params={"n": 1})])
    assert "ntf0501" in [line["loc"] for line in bw_log()]  # user không tồn tại → FK lỗi, chỉ log

    async def rabbit_down(*args, **kwargs):
        raise ConnectionError("rabbit down")

    monkeypatch.setattr(service, "emit_to_user", rabbit_down)
    await service.deliver_pending([Pending(user_id=a.id, kind="test_probe", title="vẫn lưu", params={"n": 1})])
    assert "vẫn lưu" in [r.title for r in await inbox(plain_stack, a.id)]
    assert "ntf0502" in [line["loc"] for line in bw_log()]
