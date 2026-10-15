"""Đăng nhập Google qua router viết tay: tắt khi thiếu env / công tắc; PKCE + state một lần; tạo user (role `user`)
hoặc liên kết theo Google sub rồi theo email; signup_open; tài khoản khoá; lỗi phía Google → về FE kèm mã."""

from urllib.parse import parse_qs, urlparse

import httpx2
import pytest
from sqlalchemy import text

from app.auth import flags as flags_mod
from app.auth import google as google_mod
from app.auth.google import GoogleProfile
from app.core.connections.registry import get_connections
from app.core.errors import AppException
from app.core.settings import Settings
from app.system import settings_store
from tests.auth.api import system_flags
from tests.auth.factories import make_user

pytestmark = pytest.mark.integration
FRONT = "http://front.test/auth/callback"
GOOGLE_ENV = {
    "GOOGLE_CLIENT_ID": "cid",
    "GOOGLE_CLIENT_SECRET": "secret",
    "GOOGLE_REDIRECT_URI": "http://api.test/bizwithagents/api/auth/google/callback",
    "FRONTEND_AUTH_CALLBACK_URL": FRONT,
}


@pytest.fixture(autouse=True)
def fresh_flags(monkeypatch):
    monkeypatch.setattr(flags_mod, "_last", None)


@pytest.fixture
def google(app_env, monkeypatch):
    """Google cấu hình đủ + công tắc google_enabled bật; đổi code → hồ sơ giả (`google["value"]`)."""
    for name, value in GOOGLE_ENV.items():
        monkeypatch.setattr(app_env, name, value)
    monkeypatch.setattr(settings_store, "get_system_settings", system_flags(google_enabled=True))
    profile = {"value": GoogleProfile(sub="g-1", email="GG@x.io", name="Gia Gia")}

    async def fake_exchange(self, code, verifier):
        assert code == "the-code" and verifier
        return profile["value"]

    monkeypatch.setattr(google_mod.GoogleOAuth, "exchange", fake_exchange)
    return profile


async def start(api) -> str:
    r = await api.call("GET", "/auth/google/authorize")
    assert r.status_code == 302, r.text
    return parse_qs(urlparse(r.headers["location"]).query)["state"][0]


async def callback(api, state: str, **params):
    return await api.call("GET", "/auth/google/callback", params={"code": "the-code", "state": state} | params)


def fragment(response) -> dict[str, str]:
    location = response.headers["location"]
    assert response.status_code == 302 and location.startswith(FRONT + "#"), location
    return {k: v[0] for k, v in parse_qs(location.split("#", 1)[1]).items()}


def bearer(tokens: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def test_google_off_until_configured_and_enabled(api, app_env, monkeypatch):
    monkeypatch.setattr(app_env, "GOOGLE_CLIENT_ID", "")  # không phụ thuộc .env dev
    assert await api.err("GET", "auth.google.authorize") == (400, 2108)  # chưa có GOOGLE_CLIENT_ID
    for name, value in GOOGLE_ENV.items():
        monkeypatch.setattr(app_env, name, value)
    assert await api.err("GET", "auth.google.authorize") == (400, 2108)  # có env nhưng công tắc google_enabled tắt
    await get_connections().redis.rw.set("bw:auth:oauth:planted", "v" * 64, ex=60)
    assert await api.err("GET", "auth.google.callback", params={"code": "c", "state": "planted"}) == (400, 2108)
    monkeypatch.setattr(settings_store, "get_system_settings", system_flags(google_enabled=True))
    assert (await api.call("GET", "/auth/google/authorize")).status_code == 302


async def test_authorize_redirects_to_google_with_pkce(api, google):
    r = await api.call("GET", "/auth/google/authorize")
    url = urlparse(r.headers["location"])
    q = parse_qs(url.query)
    assert r.status_code == 302 and url.netloc == "accounts.google.com"
    assert q["client_id"] == ["cid"] and q["code_challenge_method"] == ["S256"]
    assert 0 < await get_connections().redis.rw.ttl(f"bw:auth:oauth:{q['state'][0]}") <= 600


async def test_authorize_uses_public_url_https_callback(api, google, monkeypatch, app_env):
    derived = Settings(_env_file=None, PUBLIC_URL="https://pub.example.com/")
    monkeypatch.setattr(app_env, "GOOGLE_REDIRECT_URI", derived.GOOGLE_REDIRECT_URI)
    r = await api.call("GET", "/auth/google/authorize")
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["redirect_uri"] == ["https://pub.example.com/bizwithagents/api/auth/google/callback"]


async def test_callback_creates_verified_member_in_default_tenant(api, google):
    state = await start(api)
    r = await callback(api, state)
    assert "?" not in r.headers["location"]  # token chỉ nằm ở fragment
    tokens = fragment(r)
    me = await api.ok("GET", "/auth/me", headers=bearer(tokens))
    assert (me["email"], me["name"], me["has_password"]) == ("gg@x.io", "Gia Gia", False)
    assert [role["name"] for role in me["roles"]] == ["member"]
    assert me["tenant"]["slug"] == "default" and me["email_verified"] is True
    assert await api.err("GET", "auth.google.callback", params={"code": "the-code", "state": state}) == (400, 2108)


async def test_callback_links_by_email_then_by_google_id(api, google):
    existing = await api.register("gg@x.io")
    me = await api.ok("GET", "/auth/me", headers=bearer(fragment(await callback(api, await start(api)))))
    assert me["id"] == existing.id and me["has_password"] is True
    google["value"] = GoogleProfile(sub="g-1", email="doi-email@x.io", name="Gia Gia")  # đổi email bên Google, cùng sub
    me = await api.ok("GET", "/auth/me", headers=bearer(fragment(await callback(api, await start(api)))))
    assert me["id"] == existing.id
    async with get_connections().postgres.ro() as s:
        n = (await s.exec(text("select count(*) from oauth_accounts where provider_uid = 'g-1'"))).one()[0]
    assert n == 1


async def test_signup_closed_blocks_new_google_accounts_except_superadmins(api, google, monkeypatch):
    monkeypatch.setattr(
        settings_store, "get_system_settings", system_flags(google_enabled=True, signup_mode="invite_only")
    )
    assert fragment(await callback(api, await start(api))) == {"error": "2105"}
    google["value"] = GoogleProfile(sub="g-root", email="Root@Test.local", name="Root")
    me = await api.ok("GET", "/auth/me", headers=bearer(fragment(await callback(api, await start(api)))))
    assert me["is_superadmin"] is True


async def test_disabled_account_and_google_side_errors(api, google, monkeypatch):
    async with get_connections().postgres.rw() as s:
        await make_user(s, "gg@x.io", is_active=False)
    assert fragment(await callback(api, await start(api))) == {"error": "2103"}
    assert fragment(await callback(api, await start(api), error="access_denied")) == {"error": "google_denied"}

    async def unverified(self, code, verifier):
        raise AppException(2108, status_code=400, detail="Google account email is not verified")

    monkeypatch.setattr(google_mod.GoogleOAuth, "exchange", unverified)
    assert fragment(await callback(api, await start(api))) == {"error": "2108"}

    async def google_down(self, code, verifier):
        raise httpx2.ConnectError("google down")

    monkeypatch.setattr(google_mod.GoogleOAuth, "exchange", google_down)
    assert fragment(await callback(api, await start(api))) == {"error": "google_failed"}
    assert await api.err("GET", "auth.google.callback", params={"code": "c", "state": "forged"}) == (400, 2108)
