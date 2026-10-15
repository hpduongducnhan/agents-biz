"""tenants.* (superadmin): danh sách, tạo + mời admin đầu tiên, sửa chính sách (hạn mức user), khoá → token cũ bị
từ chối 2110 + socket bị ngắt, mở khoá; người thường bị chặn."""

import pytest

from app.core.connections.registry import get_connections
from app.tenants import invites as invites_mod
from app.tenants.models import DEFAULT_TENANT_ID
from app.tenants.service import disabled_key
from tests.auth.factories import make_user

pytestmark = pytest.mark.integration


@pytest.fixture
def outbox(monkeypatch):
    sent: list[dict] = []

    async def fake(to, template, locale, **ctx):
        sent.append({"to": to, "template": template, **ctx})
        return "id"

    monkeypatch.setattr(invites_mod, "queue_mail", fake)
    return sent


async def test_superadmin_creates_tenant_and_invites_first_admin(api, outbox):
    root = await api.register("root@test.local")
    out = await api.post(
        "tenants.create", root, name="Khách Hàng 1", admin_email="ceo@kh1.io", policies={"user_limit": 3}
    )
    tenant, invite = out["tenant"], out["invite"]
    assert (tenant["slug"], tenant["user_limit"], tenant["policies"]["user_limit"]) == ("khach-hang-1", 3, 3)
    assert invite["role"]["name"] == "admin" and outbox[0]["to"] == "ceo@kh1.io"
    ceo = await api.register("ceo@kh1.io", invite_token=invite["link"].rsplit("/", 1)[1])
    assert ceo.user["tenant"]["id"] == tenant["id"] and "tenant.invite" in ceo.user["permissions"]
    listed = await api.get("tenants.list", root, q="khach")
    assert [t["slug"] for t in listed["items"]] == ["khach-hang-1"] and listed["items"][0]["user_count"] == 1
    saved = await api.post("tenants.update", root, tenant_id=tenant["id"], name="KH1", policies={"user_limit": 1})
    assert (saved["name"], saved["user_limit"]) == ("KH1", 1)


async def test_suspend_kicks_users_and_resume_restores(api, rt):
    root = await api.register("root@test.local")
    tenant = (await api.post("tenants.create", root, name="Tạm"))["tenant"]
    async with get_connections().postgres.rw() as s:
        await make_user(s, "t@tam.io", tenant_id=tenant["id"])
    u = await api.login("t@tam.io")
    await api.post("tenants.suspend", root, tenant_id=tenant["id"])
    assert await get_connections().redis.ro.exists(disabled_key(tenant["id"]))
    assert await api.err("GET", "auth.me", u) == (403, 2110)
    assert await api.err("POST", "auth.refresh", json={"refresh_token": u.tokens["refresh_token"]}) == (401, 2104)
    assert any(m["routing_key"] == f"tenant.{tenant['id']}" for m in rt.sent)
    await api.post("tenants.resume", root, tenant_id=tenant["id"])
    assert (await api.login("t@tam.io")).user["tenant"]["id"] == tenant["id"]
    assert await api.err("POST", "tenants.suspend", root, json={"tenant_id": str(DEFAULT_TENANT_ID)}) == (400, 1003)


async def test_tenants_ops_are_superadmin_only(api):
    u = await api.register("u@x.io")
    assert await api.err("GET", "tenants.list", u) == (403, 1005)
    assert await api.err("POST", "tenants.create", u, json={"name": "x"}) == (403, 1005)
