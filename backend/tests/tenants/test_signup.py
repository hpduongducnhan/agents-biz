"""Đăng ký vào tenant (D12): `signup_mode`, hạn mức user, tenant bị khoá; JWT mang `tid`; admin tenant chỉ thấy user
tenant mình, superadmin thấy hết."""

import pytest

from app.auth.tokens import get_token_service
from app.core.connections.registry import get_connections
from app.system import settings_store
from tests.auth.api import PASSWORD, system_flags
from tests.auth.factories import make_tenant, make_user

pytestmark = pytest.mark.integration


async def test_default_tenant_mode_puts_everyone_in_default(api):
    s = await api.register("d1@x.io")
    assert s.user["tenant"]["slug"] == "default" and [r["name"] for r in s.user["roles"]] == ["member"]
    claims = get_token_service().decode_access(s.tokens["access_token"])
    assert claims["tid"] == s.user["tenant"]["id"]


async def test_new_tenant_mode_creates_tenant_and_makes_admin(api, monkeypatch):
    monkeypatch.setattr(settings_store, "get_system_settings", system_flags(signup_mode="new_tenant"))
    a = await api.register("owner@acme.io", name="Owner", tenant_name="Công ty Á Châu")
    b = await api.register("owner2@acme.io", name="Owner 2", tenant_name="Công ty Á Châu")
    assert a.user["tenant"]["slug"] == "cong-ty-a-chau" and b.user["tenant"]["slug"] == "cong-ty-a-chau-2"
    assert [r["name"] for r in a.user["roles"]] == ["admin"]
    assert {"tenant.invite", "tenant.settings", "user.manage"} <= set(a.user["permissions"])
    mine = await api.get("tenant.get", a)
    assert (mine["name"], mine["user_count"], mine["status"]) == ("Công ty Á Châu", 1, "active")


async def test_admin_sees_only_own_tenant_users_superadmin_sees_all(api, monkeypatch):
    monkeypatch.setattr(settings_store, "get_system_settings", system_flags(signup_mode="new_tenant"))
    a = await api.register("adm-a@x.io", tenant_name="A")
    b = await api.register("adm-b@x.io", tenant_name="B")
    emails = {u["email"] for u in (await api.get("admin.list_users", a))["items"]}
    assert emails == {"adm-a@x.io"}
    assert await api.err("GET", "admin.get_user", a, params={"user_id": b.user["id"]}) == (404, 1001)
    root = await api.register("root@test.local")
    everyone = {u["email"] for u in (await api.get("admin.list_users", root, limit=100))["items"]}
    assert {"adm-a@x.io", "adm-b@x.io", "root@test.local"} <= everyone
    only_b = await api.get("admin.list_users", root, tenant_id=b.user["tenant"]["id"])
    assert [u["email"] for u in only_b["items"]] == ["adm-b@x.io"]


async def test_user_limit_blocks_new_members(api, monkeypatch):
    monkeypatch.setattr(settings_store, "get_system_settings", system_flags(user_limit_default=1))
    await api.register("first@x.io")
    assert await api.err("POST", "auth.register", json={"email": "second@x.io", "password": PASSWORD}) == (409, 2111)


async def test_suspended_tenant_cannot_sign_in(api):
    async with get_connections().postgres.rw() as s:
        frozen = await make_tenant(s, "Frozen", status="suspended")
        await make_user(s, "ice@x.io", tenant_id=frozen.id)
    assert await api.err("POST", "auth.login", json={"email": "ice@x.io", "password": PASSWORD}) == (403, 2110)
