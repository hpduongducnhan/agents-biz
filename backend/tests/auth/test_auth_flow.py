"""auth.* qua REST thật: đăng ký / đăng nhập / phiên / hồ sơ / đổi mật khẩu; signup_open; rate limit; email hoa
thường + khoảng trắng; superadmin bị bỏ khỏi env; đường dẫn theo quy ước operation."""

import asyncio

import pytest
from sqlalchemy import text

from app.core.connections.registry import get_connections
from app.system import settings_store
from tests.auth.api import data_of, system_flags
from tests.auth.factories import PASSWORD, make_user, user_perms
from tests.conftest import until

pytestmark = pytest.mark.integration


async def sql(query: str, **params) -> None:
    async with get_connections().postgres.rw() as s:
        await s.exec(text(query).bindparams(**params))


async def test_paths_follow_convention(api):
    paths = (await api.call("GET", "/openapi.json")).json()["paths"]
    for op in ("register", "login", "refresh", "logout", "logout_all", "update_me", "change_password"):
        assert "post" in paths[f"/bizwithagents/api/auth/{op}"], op
    assert "get" in paths["/bizwithagents/api/auth/me"]


async def test_register_returns_profile_tokens_and_role_member(api):
    me = await api.register("Alice@Example.io", name="Alice")
    u = me.user
    assert (u["email"], u["name"], u["is_superadmin"], u["must_change_password"]) == (
        "alice@example.io",
        "Alice",
        False,
        False,
    )
    assert [r["name"] for r in u["roles"]] == ["member"] and u["permissions"] == user_perms()
    assert u["tenant"]["slug"] == "default" and u["email_verified"] is False and me.verification_sent is True
    assert (u["timezone"], u["locale"], u["has_password"]) == ("Asia/Ho_Chi_Minh", "vi", True)
    assert me.tokens["token_type"] == "bearer" and me.tokens["expires_in"] == 1800
    again = await api.get("auth.me", me)
    assert again["id"] == u["id"] and again["last_login_at"]


async def test_email_case_and_spaces_mean_one_account(api):
    await api.register("  Bao.Tran@Example.IO ")
    body = {"email": "BAO.TRAN@example.io", "password": PASSWORD}
    assert await api.err("POST", "auth.register", json=body) == (409, 2101)
    s = await api.login(" bao.tran@EXAMPLE.io ")
    assert s.user["email"] == "bao.tran@example.io"


async def test_concurrent_register_same_email_one_409(api):
    body = {"email": "race@x.io", "password": PASSWORD}
    a, b = await asyncio.gather(
        api.call("POST", "/auth/register", json=body), api.call("POST", "/auth/register", json=body)
    )
    assert sorted([a.status_code, b.status_code]) == [200, 409]


async def test_register_validation(api):
    assert await api.err("POST", "auth.register", json={"email": "not-an-email", "password": PASSWORD}) == (422, 1002)
    assert await api.err("POST", "auth.register", json={"email": "s@x.io", "password": "1234567"}) == (422, 2107)
    assert await api.err("POST", "auth.register", json={"email": "s@x.io", "password": "x" * 201}) == (422, 1002)


async def test_invite_only_blocks_everyone_but_superadmin_emails(api, monkeypatch):
    monkeypatch.setattr(settings_store, "get_system_settings", system_flags(signup_mode="invite_only"))
    assert await api.err("POST", "auth.register", json={"email": "new@x.io", "password": PASSWORD}) == (403, 2105)
    root = await api.register(" Root@Test.local ")
    assert root.user["is_superadmin"] and {"user.view", "user.manage", "tenant.invite"} <= set(root.user["permissions"])
    assert root.user["tenant"]["slug"] == "default"


async def test_wrong_password_and_unknown_email_look_the_same(api):
    await api.register("who@x.io")
    wrong = await api.err("POST", "auth.login", json={"email": "who@x.io", "password": "wrong-pass"})
    ghost = await api.err("POST", "auth.login", json={"email": "ghost@x.io", "password": "wrong-pass"})
    assert wrong == ghost == (401, 2102)


async def test_login_rate_limit_is_per_ip_and_normalised_email(api, app_env, monkeypatch):
    monkeypatch.setattr(app_env, "AUTH_LOGIN_RATE_LIMIT", 2)
    await api.register("rl@x.io")
    tries = [
        await api.call("POST", "/auth/login", json={"email": e, "password": "wrong-pass"})
        for e in ("rl@x.io", "RL@x.io", " rl@X.IO ")
    ]
    assert [r.status_code for r in tries] == [401, 401, 429]
    assert tries[2].json()["code"] == 1007 and tries[2].json()["data"]["retry_after_sec"] >= 1
    other = await api.call("POST", "/auth/login", json={"email": "other@x.io", "password": "wrong-pass"})
    assert other.status_code == 401  # email khác: bộ đếm riêng


async def test_register_rate_limit_per_ip(api, app_env, monkeypatch):
    monkeypatch.setattr(app_env, "AUTH_REGISTER_RATE_LIMIT", 2)
    await api.register("r1@x.io")
    await api.register("r2@x.io")
    assert await api.err("POST", "auth.register", json={"email": "r3@x.io", "password": PASSWORD}) == (429, 1007)


async def test_disabled_or_google_only_accounts_cannot_password_login(api):
    async with get_connections().postgres.rw() as s:
        await make_user(s, "off@x.io", is_active=False)
        await make_user(s, "g@x.io", password=None)
    assert await api.err("POST", "auth.login", json={"email": "off@x.io", "password": PASSWORD}) == (403, 2103)
    assert await api.err("POST", "auth.login", json={"email": "off@x.io", "password": "wrong-pass"}) == (401, 2102)
    assert await api.err("POST", "auth.login", json={"email": "g@x.io", "password": PASSWORD}) == (401, 2102)


async def test_refresh_rotates_and_late_reuse_kills_family(api):
    s = await api.register("rot@x.io")
    new = await api.post("auth.refresh", refresh_token=s.tokens["refresh_token"])
    assert new["refresh_token"] != s.tokens["refresh_token"] and new["access_token"]
    await sql("update refresh_tokens set revoked_at = now() - interval '1 minute' where revoked_at is not null")
    assert await api.err("POST", "auth.refresh", json={"refresh_token": s.tokens["refresh_token"]}) == (401, 2104)
    assert await api.err("POST", "auth.refresh", json={"refresh_token": new["refresh_token"]}) == (401, 2104)


async def test_logout_and_logout_all(api):
    s = await api.register("lo@x.io")
    other = await api.login("lo@x.io")
    assert await api.post("auth.logout", refresh_token=s.tokens["refresh_token"]) is None
    assert await api.err("POST", "auth.refresh", json={"refresh_token": s.tokens["refresh_token"]}) == (401, 2104)
    await api.post("auth.refresh", refresh_token=other.tokens["refresh_token"])  # phiên khác còn
    await api.post("auth.logout", refresh_token="không-có-token-này")  # token lạ: vẫn 200
    third = await api.login("lo@x.io")
    assert await api.post("auth.logout_all", third) is None
    assert await api.err("POST", "auth.refresh", json={"refresh_token": third.tokens["refresh_token"]}) == (401, 2104)


async def test_update_me_profile_fields(api):
    s = await api.register("me@x.io")
    me = await api.post("auth.update_me", s, name="  Tôi  ", timezone="Asia/Tokyo", locale="en")
    assert (me["name"], me["timezone"], me["locale"]) == ("Tôi", "Asia/Tokyo", "en")
    assert (await api.get("auth.me", s))["timezone"] == "Asia/Tokyo"
    assert await api.err("POST", "auth.update_me", s, json={"timezone": "Mars/Base"}) == (422, 1002)
    assert await api.err("POST", "auth.update_me", s, json={"locale": "fr"}) == (422, 1002)
    assert await api.err("GET", "auth.me") == (401, 1004)


async def test_change_password_revokes_sessions_and_clears_must_change(api):
    async with get_connections().postgres.rw() as db:
        await make_user(db, "pw@x.io", must_change_password=True)
    s = await api.login("pw@x.io")
    assert s.user["must_change_password"] is True
    bad = {"current_password": "nope-nope", "new_password": "newpass123"}
    assert await api.err("POST", "auth.change_password", s, json=bad) == (400, 2106)
    short = {"current_password": PASSWORD, "new_password": "short"}
    assert await api.err("POST", "auth.change_password", s, json=short) == (422, 2107)
    tokens = await api.post("auth.change_password", s, current_password=PASSWORD, new_password="newpass123")
    assert await api.err("POST", "auth.refresh", json={"refresh_token": s.tokens["refresh_token"]}) == (401, 2104)
    me = await api.ok("GET", "/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me["must_change_password"] is False
    await api.login("pw@x.io", "newpass123")


async def test_superadmin_removed_from_env_loses_power_on_refresh(api, app_env, monkeypatch):
    root = await api.as_user("root@test.local")
    assert root.user["is_superadmin"] is True
    monkeypatch.setattr(app_env, "SUPERADMIN_EMAILS", "")  # deploy mới bỏ email này khỏi env
    fresh = await api.refresh(root)
    assert fresh.user["is_superadmin"] is False and fresh.user["permissions"] == user_perms()


async def test_register_refreshes_user_lists_of_viewers(api, rt):
    admin = await api.as_user("adm@x.io", roles=("member", "admin"))
    plain = await api.as_user("plain@x.io")
    await api.register("new@x.io")
    assert await until(lambda: any("admin.users" in d["keys"] for d in data_of(rt, f"user.{admin.id}", "data:changed")))
    assert data_of(rt, f"user.{plain.id}", "data:changed") == []
