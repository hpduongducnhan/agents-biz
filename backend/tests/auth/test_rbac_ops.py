"""rbac.* qua REST: catalog quyền, role có sẵn (admin / member / viewer) bất biến, role tự tạo chỉ superadmin quản (role
dùng chung mọi tenant — D12): tên trùng / dành riêng, quyền lạ; role đang gán không xoá được; đổi quyền của role →
người giữ nhận core:rbac_updated; số người giữ role chỉ đếm trong tenant của người xem."""

import uuid

import pytest

from app.auth import rbac
from app.core.connections.registry import get_connections
from tests.auth.api import events_to
from tests.auth.factories import agent_toolset_codes, make_tenant, make_user, user_perms
from tests.conftest import until

pytestmark = pytest.mark.integration


async def admin_of(api):
    return await api.as_user("adm@x.io", roles=("admin",))


async def root_of(api):
    return await api.register("root@test.local")  # superadmin theo SUPERADMIN_EMAILS của env test


async def roles(api, who) -> list[dict]:
    return (await api.get("rbac.list_roles", who, limit=100))["items"]


async def test_rbac_paths_follow_convention(api):
    paths = (await api.call("GET", "/openapi.json")).json()["paths"]
    assert "get" in paths["/bizwithagents/api/rbac/list_permissions"]
    assert "get" in paths["/bizwithagents/api/rbac/list_roles"]
    for op in ("create_role", "update_role", "delete_role"):
        assert "post" in paths[f"/bizwithagents/api/rbac/{op}"], op


async def test_list_permissions_is_the_code_catalog(api):
    plain = await api.as_user("plain@x.io")
    perms = {p["codename"]: p["domain"] for p in await api.get("rbac.list_permissions", plain)}
    assert perms == {code: domain for code, (domain, _) in rbac.declared_permissions().items()}  # đúng catalog code
    assert {
        "user.view": "auth",
        "user.manage": "auth",
        "tenant.settings": "tenants",
        "tenant.invite": "tenants",
        "agent.chat": "agent",
        "tasks.view": "tasks",  # module mẫu
        **dict.fromkeys(agent_toolset_codes(), "agent"),
    }.items() <= perms.items()
    assert await api.err("GET", "rbac.list_permissions") == (401, 1004)


async def test_list_roles_needs_user_view_and_counts_only_own_tenant(api):
    plain = await api.as_user("plain@x.io")
    admin = await admin_of(api)
    async with get_connections().postgres.rw() as s:
        acme = await make_tenant(s, "Acme")
        await make_user(s, "far@acme.io", tenant_id=acme.id, roles=("member",))
    assert await api.err("GET", "rbac.list_roles", plain) == (403, 1005)
    page = await api.get("rbac.list_roles", admin)
    assert (page["total"], page["limit"], page["offset"]) == (3, 20, 0)
    assert [(r["name"], r["is_builtin"], r["user_count"]) for r in page["items"]] == [
        ("admin", True, 1),
        ("member", True, 1),  # far@acme.io ở tenant khác → không đếm
        ("viewer", True, 0),
    ]
    assert page["items"][1]["permissions"] == user_perms()
    assert await api.err("GET", "rbac.list_roles", admin, params={"limit": 101}) == (422, 1002)


async def test_custom_roles_are_superadmin_only(api):
    admin = await admin_of(api)
    assert await api.err("POST", "rbac.create_role", admin, json={"name": "x"}) == (403, 1005)


async def test_custom_role_create_update_delete(api):
    admin = await root_of(api)
    role = await api.post(
        "rbac.create_role", admin, name="  Ke toan ", description="Xem user", permissions=["user.view"]
    )
    assert (role["name"], role["is_builtin"], role["permissions"], role["user_count"]) == (
        "Ke toan",
        False,
        ["user.view"],
        0,
    )
    for name in ("ke TOAN", "Superadmin", "ADMIN", "member", "Viewer"):
        assert await api.err("POST", "rbac.create_role", admin, json={"name": name}) == (409, 2201), name
    r = await api.call(
        "POST", "/rbac/create_role", admin, json={"name": "x", "permissions": ["nope.nope", "user.view"]}
    )
    assert (r.status_code, r.json()["code"], r.json()["data"]) == (422, 2203, {"unknown": ["nope.nope"]})
    assert await api.err("POST", "rbac.create_role", admin, json={"name": "   "}) == (422, 1002)
    other = await api.post("rbac.create_role", admin, name="Thu ngan")
    upd = await api.post(
        "rbac.update_role", admin, role_id=role["id"], name="Ke toan truong", permissions=["user.view", "user.manage"]
    )
    assert (upd["name"], upd["permissions"]) == ("Ke toan truong", ["user.manage", "user.view"])
    clash = {"role_id": role["id"], "name": "thu NGAN"}
    assert await api.err("POST", "rbac.update_role", admin, json=clash) == (409, 2201)
    reserved = {"role_id": role["id"], "name": "member"}
    assert await api.err("POST", "rbac.update_role", admin, json=reserved) == (409, 2201)
    same = await api.post("rbac.update_role", admin, role_id=role["id"], name="KE TOAN TRUONG")  # đổi hoa thường
    assert same["name"] == "KE TOAN TRUONG"
    assert await api.post("rbac.delete_role", admin, role_id=other["id"]) is None
    assert [r["name"] for r in await roles(api, admin)] == ["admin", "member", "viewer", "KE TOAN TRUONG"]
    assert await api.err("POST", "rbac.delete_role", admin, json={"role_id": str(uuid.uuid4())}) == (404, 1001)


async def test_builtin_roles_are_immutable(api):
    admin = await root_of(api)
    for role in await roles(api, admin):
        update = {"role_id": role["id"], "permissions": []}
        assert await api.err("POST", "rbac.update_role", admin, json=update) == (409, 2202), role["name"]
        assert await api.err("POST", "rbac.delete_role", admin, json={"role_id": role["id"]}) == (409, 2202)


async def test_role_in_use_cannot_be_deleted(api):
    admin = await root_of(api)
    b = await api.as_user("b@x.io")
    role = await api.post("rbac.create_role", admin, name="Tam", permissions=["user.view"])
    user_role = next(r for r in await roles(api, admin) if r["name"] == "member")
    await api.post("admin.update_user", admin, user_id=b.id, role_ids=[user_role["id"], role["id"]])
    r = await api.call("POST", "/rbac/delete_role", admin, json={"role_id": role["id"]})
    assert (r.status_code, r.json()["code"], r.json()["data"]) == (409, 2205, {"user_count": 1})
    assert "user.view" in (await api.refresh(b)).user["permissions"]  # không ai mất quyền ngầm
    await api.post("admin.update_user", admin, user_id=b.id, role_ids=[user_role["id"]])
    await api.post("rbac.delete_role", admin, role_id=role["id"])


async def test_role_permission_change_tells_holders(api, rt):
    admin = await root_of(api)
    b = await api.as_user("b@x.io")
    role = await api.post("rbac.create_role", admin, name="Tam", permissions=["user.view"])
    user_role = next(r for r in await roles(api, admin) if r["name"] == "member")
    await api.post("admin.update_user", admin, user_id=b.id, role_ids=[user_role["id"], role["id"]])
    before = events_to(rt, f"user.{b.id}").count("core:rbac_updated")
    await api.post("rbac.update_role", admin, role_id=role["id"], permissions=["user.view", "tenant.invite"])
    assert await until(lambda: events_to(rt, f"user.{b.id}").count("core:rbac_updated") == before + 1)
    await api.post("rbac.update_role", admin, role_id=role["id"], description="chỉ đổi mô tả")
    assert events_to(rt, f"user.{b.id}").count("core:rbac_updated") == before + 1  # quyền không đổi → không báo
    assert "tenant.invite" in (await api.refresh(b)).user["permissions"]
