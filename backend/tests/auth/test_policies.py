"""Chính sách tài khoản (sp9): đọc jsonb chịu lỗi, ops chỉ superadmin, hạn mức hiệu lực 4 tầng."""

import logging
import uuid

import pytest

from app.auth.models import User
from app.auth.policies import AccountPolicies, dump_policies, effective_limits, read_policies
from app.core.connections.registry import get_connections
from tests.auth.factories import make_role, make_user

pytestmark = pytest.mark.integration
ROOT = "root@test.local"
NO_CHAT = {"chat_per_minute": None, "chat_per_hour": None, "chat_per_day": None}


def test_read_policies_ignores_unset_null_and_invalid(caplog):
    assert read_policies(None, owner="x") == AccountPolicies()
    assert read_policies({}, owner="x") == AccountPolicies()
    assert read_policies({"chat_per_minute": None}, owner="x").chat_per_minute is None
    assert read_policies({"chat_per_minute": 7, "bogus": 1}, owner="x").chat_per_minute == 7
    with caplog.at_level(logging.WARNING):
        for bad in (-1, 100_001, "abc"):
            assert read_policies({"chat_per_minute": bad}, owner="role r").chat_per_minute is None
    assert any(getattr(r, "loc", None) == "auth0601" for r in caplog.records)


def test_dump_policies_omits_unset():
    assert dump_policies(AccountPolicies()) == {}
    assert dump_policies(AccountPolicies(chat_per_minute=0)) == {"chat_per_minute": 0}


async def role_id(api, who, name: str) -> str:
    items = (await api.get("rbac.list_roles", who, limit=100))["items"]
    return next(r["id"] for r in items if r["name"] == name)


DEFAULTS = {"chat_per_minute": 5, "chat_per_hour": 50, "chat_per_day": 500}


async def limit(user_id, key: str = "chat_per_minute"):
    async with get_connections().postgres.ro() as s:
        user = await s.get(User, uuid.UUID(user_id))
        return (await effective_limits(s, user, DEFAULTS))[key]


async def test_default_tier(api):
    u = await api.as_user("u@x.io")
    e = await limit(u.id)
    assert (e.value, e.source, e.role) == (5, "default", None)


async def test_role_tier_on_builtin_user_role(api):
    root = await api.as_user(ROOT)
    u = await api.as_user("u@x.io")
    out = await api.post(
        "rbac.set_role_policies", root, role_id=await role_id(api, root, "member"), policies={"chat_per_minute": 8}
    )
    assert out["policies"] == {"chat_per_minute": 8, "chat_per_hour": None, "chat_per_day": None}
    e = await limit(u.id)
    assert (e.value, e.source, e.role) == (8, "role", "member")
    # thay cả bộ: null = bỏ đặt
    await api.post("rbac.set_role_policies", root, role_id=await role_id(api, root, "member"), policies={})
    assert (await limit(u.id)).source == "default"


async def test_max_over_multiple_roles(api):
    root = await api.as_user(ROOT)
    async with get_connections().postgres.rw() as s:
        await make_role(s, "gd", ["agent.chat"])
        await make_role(s, "vip", ["agent.chat"])
    u = await api.as_user("u@x.io", roles=("member", "gd", "vip"))
    for name, n in (("gd", 10), ("vip", 20)):
        await api.post(
            "rbac.set_role_policies", root, role_id=await role_id(api, root, name), policies={"chat_per_minute": n}
        )
    e = await limit(u.id)
    assert (e.value, e.source, e.role) == (20, "role", "vip")


async def test_user_override_wins_even_when_lower(api):
    root = await api.as_user(ROOT)
    u = await api.as_user("u@x.io")
    await api.post(
        "rbac.set_role_policies", root, role_id=await role_id(api, root, "member"), policies={"chat_per_minute": 10}
    )
    out = await api.post("admin.set_user_policies", root, user_id=u.id, policies={"chat_per_minute": 2})
    assert out["policies"] == {"chat_per_minute": 2, "chat_per_hour": None, "chat_per_day": None}
    e = await limit(u.id)
    assert (e.value, e.source) == (2, "user")
    got = await api.get("admin.user_policies", root, user_id=u.id)
    assert got["policies"]["chat_per_minute"] == 2
    await api.post("admin.set_user_policies", root, user_id=u.id, policies={})
    e = await limit(u.id)
    assert (e.value, e.source) == (10, "role")


async def test_superadmin_is_unlimited(api):
    root = await api.as_user(ROOT)
    e = await limit(root.id)
    assert (e.value, e.source) == (None, "superadmin")


async def test_policy_ops_are_superadmin_only(api):
    async with get_connections().postgres.rw() as s:
        await make_role(s, "mgr", ["tenant.settings", "user.manage", "user.view"])
    adm = await api.as_user("adm@x.io", roles=("member", "admin", "mgr"))
    root = await api.as_user(ROOT)
    target = await api.as_user("t@x.io")
    rid = await role_id(api, root, "member")
    assert await api.err("POST", "rbac.set_role_policies", adm, json={"role_id": rid, "policies": {}}) == (403, 1005)
    assert await api.err("POST", "admin.set_user_policies", adm, json={"user_id": target.id, "policies": {}}) == (
        403,
        1005,
    )
    assert await api.err("GET", "admin.user_policies", adm, params={"user_id": target.id}) == (403, 1005)
    assert await api.err("POST", "rbac.set_role_policies", json={"role_id": rid, "policies": {}}) == (401, 1004)


async def test_set_user_policies_rejects_superadmin_and_bad_values(api):
    root = await api.as_user(ROOT)
    other = await api.as_user("o@x.io")
    async with get_connections().postgres.rw() as s:
        sa = await make_user(s, "sa2@x.io", is_superadmin=True)
    assert await api.err("POST", "admin.set_user_policies", root, json={"user_id": str(sa.id), "policies": {}}) == (
        409,
        2204,
    )
    for bad in (-1, 100_001):
        body = {"user_id": other.id, "policies": {"chat_per_minute": bad}}
        assert await api.err("POST", "admin.set_user_policies", root, json=body) == (422, 1002)
