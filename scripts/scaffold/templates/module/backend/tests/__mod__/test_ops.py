"""Op của module __mod__ (sinh bằng `make new-module`):
tạo / sửa / xoá, lọc + phân trang, quyền theo role có sẵn, tách tổ chức (404 chéo),
`data:changed` tới cả tổ chức, chat qua LLM giả (tạo ghi `source=agent`, xoá phải duyệt)."""

import json
import uuid

import pytest

from app.core.connections.registry import get_connections
from tests.agent.helpers import approvals, chat, setup
from tests.auth.api import data_of
from tests.auth.factories import make_tenant, make_user
from tests.conftest import until

pytestmark = pytest.mark.integration


@pytest.fixture
async def w(api):
    admin = await api.as_user("boss@x.io", roles=("admin",), name="Sếp")
    member = await api.as_user("lan@x.io", roles=("member",), name="Lan")
    viewer = await api.as_user("xem@x.io", roles=("viewer",))
    async with get_connections().postgres.rw() as s:
        acme = await make_tenant(s, "Acme")
        await make_user(s, "far@acme.io", tenant_id=acme.id, roles=("member",))
    other = await api.login("far@acme.io")
    return api, admin, member, viewer, other, acme.id


async def test_crud_roles_and_filters(w):
    api, admin, member, viewer, _, _ = w
    a = await api.post("__mod__.create", member, title="  Một  ", description="mô tả có chữ khoá")
    assert (a["title"], a["status"], a["source"], a["created_by"]["name"]) == ("Một", "open", "web", "Lan")
    b = await api.post("__mod__.create", admin, title="Hai")
    upd = await api.post("__mod__.update", member, item_id=a["id"], status="done")
    assert upd["status"] == "done" and upd["title"] == "Một"
    assert (await api.get("__mod__.get", viewer, item_id=b["id"]))["title"] == "Hai"
    assert (await api.get("__mod__.list", viewer))["total"] == 2
    assert [x["title"] for x in (await api.get("__mod__.list", member, status="done"))["items"]] == ["Một"]
    assert [x["title"] for x in (await api.get("__mod__.list", member, mine=True))["items"]] == ["Một"]
    assert [x["title"] for x in (await api.get("__mod__.list", member, q="KHOÁ"))["items"]] == ["Một"]
    assert await api.err("POST", "__mod__.create", viewer, json={"title": "x"}) == (403, 1005)
    assert await api.err("POST", "__mod__.delete", member, json={"item_id": a["id"]}) == (403, 1005)
    assert await api.post("__mod__.delete", admin, item_id=a["id"]) is None
    assert await api.err("GET", "__mod__.get", admin, params={"item_id": a["id"]}) == (404, __code1__)
    assert await api.err("POST", "__mod__.create", member, json={"title": "  "}) == (422, 1002)


async def test_other_tenant_cannot_see_or_touch(w, rt):
    api, _, member, _, other, acme_id = w
    tid = (await api.get("auth.me", member))["tenant"]["id"]
    before = len(data_of(rt, f"tenant.{tid}", "data:changed"))
    other_before = len(data_of(rt, f"tenant.{acme_id}", "data:changed"))
    a = await api.post("__mod__.create", member, title="Bí mật")
    assert await until(lambda: len(data_of(rt, f"tenant.{tid}", "data:changed")) > before)
    assert {"__mod__.list", "__mod__.detail"} <= set(data_of(rt, f"tenant.{tid}", "data:changed")[-1]["keys"])
    assert len(data_of(rt, f"tenant.{acme_id}", "data:changed")) == other_before
    assert (await api.get("__mod__.list", other))["total"] == 0
    assert await api.err("GET", "__mod__.get", other, params={"item_id": a["id"]}) == (404, __code1__)
    body = {"item_id": a["id"], "title": "hack"}
    assert await api.err("POST", "__mod__.update", other, json=body) == (404, __code1__)


async def test_chat_creates_and_delete_waits_for_approval(aenv, kicks, fake_llm, w):
    api, admin, member, _, _, _ = w
    await setup(api, fake_llm.base_url)
    _, run = await chat(api, member, "call:__mod___create " + json.dumps({"title": "Qua chat"}, ensure_ascii=False))
    assert run.status == "done"
    (item,) = (await api.get("__mod__.list", member))["items"]
    assert (item["title"], item["source"]) == ("Qua chat", "agent")
    sent, run = await chat(api, admin, "call:__mod___delete " + json.dumps({"item_id": item["id"]}))
    assert run.status == "waiting_approval"
    (req,) = await approvals(sent["run_id"])
    assert req.operation == "__mod__.delete"
    assert uuid.UUID(item["id"])
