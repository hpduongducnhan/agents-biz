"""admin.* qua REST: quyền user.view / user.manage, tìm + lọc + phân trang, khoá tài khoản có hiệu lực ngay (REST +
socket), gán role → token mới có quyền, đặt lại mật khẩu, superadmin + chính mình được bảo vệ."""

import uuid

import pytest

from app.auth.rbac import role_by_name
from app.core.connections.registry import get_connections
from tests.auth.api import data_of, events_to
from tests.auth.factories import PASSWORD, make_role, make_tenant, make_user
from tests.conftest import until

pytestmark = pytest.mark.integration


async def role_id(name: str) -> str:
    async with get_connections().postgres.ro() as s:
        return str((await role_by_name(s, name)).id)


async def test_admin_paths_follow_convention(api):
    paths = (await api.call("GET", "/openapi.json")).json()["paths"]
    assert "get" in paths["/bizwithagents/api/admin/list_users"] and "get" in paths["/bizwithagents/api/admin/get_user"]
    assert "post" in paths["/bizwithagents/api/admin/update_user"]
    assert "post" in paths["/bizwithagents/api/admin/reset_password"]


async def test_admin_ops_need_the_right_permission(api):
    plain = await api.as_user("plain@x.io")
    target = await api.as_user("t@x.io")
    async with get_connections().postgres.rw() as s:
        await make_role(s, "auditor", ["user.view"])
    viewer = await api.as_user("v@x.io", roles=("member", "auditor"))
    update = {"user_id": target.id, "is_active": False}
    reset = {"user_id": target.id, "new_password": "tamthoi123"}
    for who in (plain, viewer):
        assert await api.err("POST", "admin.update_user", who, json=update) == (403, 1005)
        assert await api.err("POST", "admin.reset_password", who, json=reset) == (403, 1005)
    assert await api.err("GET", "admin.list_users", plain) == (403, 1005)
    assert await api.err("GET", "admin.get_user", plain, params={"user_id": target.id}) == (403, 1005)
    assert (await api.get("admin.get_user", viewer, user_id=target.id))["email"] == "t@x.io"


async def test_list_users_search_filter_and_paginate(api):
    root = await api.as_user("root@test.local")  # superadmin theo env test → vượt mọi kiểm quyền
    for i in range(3):
        await api.as_user(f"find{i}@x.io")
    async with get_connections().postgres.rw() as s:
        await make_user(s, "find-off@x.io", is_active=False)
    page = await api.get("admin.list_users", root, q="FIND", limit=2)
    assert (page["total"], len(page["items"]), page["limit"], page["offset"]) == (4, 2, 2, 0)
    assert all("find" in u["email"] for u in page["items"])
    assert (await api.get("admin.list_users", root))["limit"] == 20  # R14: mặc định 20
    assert (await api.get("admin.list_users", root, q="find", is_active=False))["total"] == 1
    assert (await api.get("admin.list_users", root, q="_"))["total"] == 0  # `_` là chữ, không phải ký tự đại diện
    assert (await api.get("admin.list_users", root, role_id=await role_id("admin")))["total"] == 0
    assert await api.err("GET", "admin.list_users", root, params={"limit": 101}) == (422, 1002)
    assert await api.err("GET", "admin.get_user", root, params={"user_id": str(uuid.uuid4())}) == (404, 1001)


async def test_disable_user_kicks_rest_and_socket_at_once(api, rt):
    admin = await api.as_user("adm@x.io", roles=("member", "admin"))
    a = await api.as_user("kick@x.io")
    await api.get("auth.me", a)  # access token đang sống
    out = await api.post("admin.update_user", admin, user_id=a.id, is_active=False)
    assert out["is_active"] is False
    # REST: token còn hạn bị chặn ngay
    assert await api.err("GET", "auth.me", a) == (403, 2103)
    # Socket: dấu Redis mà @on_ws đọc + lệnh rt:revoke cho mọi instance realtime
    redis = get_connections().redis.rw
    assert 0 < await redis.ttl(f"bw:auth:disabled:{a.id}") <= 1800
    assert await until(lambda: "core:account_disabled" in events_to(rt, f"user.{a.id}"))
    assert await until(lambda: data_of(rt, "all", "rt:revoke") != [])
    revokes = data_of(rt, "all", "rt:revoke")
    assert [r["sub"] for r in revokes] == [a.id] and revokes[0]["until"] - revokes[0]["before"] == 1800
    # refresh / đăng nhập đều hỏng
    assert await api.err("POST", "auth.refresh", json={"refresh_token": a.tokens["refresh_token"]}) == (401, 2104)
    assert await api.err("POST", "auth.login", json={"email": a.email, "password": PASSWORD}) == (403, 2103)
    # mở lại → xoá dấu, đăng nhập được ngay
    await api.post("admin.update_user", admin, user_id=a.id, is_active=True)
    assert await redis.exists(f"bw:auth:disabled:{a.id}") == 0
    await api.get("auth.me", await api.login(a.email))


async def test_superadmin_and_self_are_protected(api):
    admin = await api.as_user("adm@x.io", roles=("member", "admin"))
    root = await api.as_user("root@test.local")
    assert root.user["is_superadmin"] is True
    cases = [
        (admin, "admin.update_user", {"user_id": admin.id, "is_active": False}, (409, 2206)),
        (admin, "admin.update_user", {"user_id": admin.id, "is_superadmin": True}, (409, 2204)),
        (admin, "admin.update_user", {"user_id": root.id, "is_active": False}, (409, 2204)),
        (admin, "admin.update_user", {"user_id": root.id, "role_ids": []}, (409, 2204)),
        (admin, "admin.reset_password", {"user_id": root.id, "new_password": "tamthoi123"}, (409, 2204)),
        (root, "admin.update_user", {"user_id": root.id, "is_active": False}, (409, 2206)),
        (root, "admin.update_user", {"user_id": admin.id, "is_superadmin": False}, (409, 2204)),
    ]
    for who, op, body, want in cases:
        assert await api.err("POST", op, who, json=body) == want, (op, body)


async def test_assign_roles_tells_user_and_refresh_brings_new_perms(api, rt):
    admin = await api.as_user("adm@x.io", roles=("member", "admin"))
    b = await api.as_user("b@x.io")
    async with get_connections().postgres.rw() as s:
        viewer = await make_role(s, "Xem user", ["user.view"])
    out = await api.post("admin.update_user", admin, user_id=b.id, role_ids=[await role_id("member"), str(viewer.id)])
    assert sorted(r["name"] for r in out["roles"]) == ["Xem user", "member"]
    assert await until(lambda: "core:rbac_updated" in events_to(rt, f"user.{b.id}"))
    assert any("auth.me" in d["keys"] for d in data_of(rt, f"user.{b.id}", "data:changed"))
    fresh = await api.refresh(b)
    assert "user.view" in fresh.user["permissions"]
    await api.get("admin.list_users", fresh)
    bad = {"user_id": b.id, "role_ids": [str(uuid.uuid4())]}
    assert await api.err("POST", "admin.update_user", admin, json=bad) == (422, 1002)
    async with get_connections().postgres.rw() as s:
        acme = await make_tenant(s, "Acme")
        stranger = await make_user(s, "far@acme.io", tenant_id=acme.id)
    far = {"user_id": str(stranger.id), "is_active": False}
    assert await api.err("POST", "admin.update_user", admin, json=far) == (404, 1001)  # khác tenant (D11)


async def test_reset_password_forces_change_and_ends_sessions(api):
    admin = await api.as_user("adm@x.io", roles=("member", "admin"))
    c = await api.as_user("c@x.io")
    short = {"user_id": c.id, "new_password": "short"}
    assert await api.err("POST", "admin.reset_password", admin, json=short) == (422, 2107)
    out = await api.post("admin.reset_password", admin, user_id=c.id, new_password="tamthoi123")
    assert out["must_change_password"] is True
    assert await api.err("POST", "auth.refresh", json={"refresh_token": c.tokens["refresh_token"]}) == (401, 2104)
    assert await api.err("POST", "auth.login", json={"email": c.email, "password": PASSWORD}) == (401, 2102)
    s = await api.login(c.email, "tamthoi123")
    assert s.user["must_change_password"] is True
    tokens = await api.post("auth.change_password", s, current_password="tamthoi123", new_password="moi-hon-123")
    me = await api.ok("GET", "/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me["must_change_password"] is False
