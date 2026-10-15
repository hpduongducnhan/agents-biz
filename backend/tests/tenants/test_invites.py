"""Lời mời vào tenant: email (thư, dùng 1 lần) / link (nhiều lượt), xem trước công khai, đăng ký bằng lời mời, thu hồi,
email đã có tài khoản, phải xác thực email trước khi mời (chế độ soft), realtime phát cho cả tenant."""

import pytest

from app.system import settings_store
from app.tenants import invites as invites_mod
from tests.auth.api import PASSWORD, system_flags

pytestmark = pytest.mark.integration


@pytest.fixture
def outbox(monkeypatch):
    sent: list[dict] = []

    async def fake(to, template, locale, **ctx):
        sent.append({"to": to, "template": template, "locale": locale, **ctx})
        return "id"

    monkeypatch.setattr(invites_mod, "queue_mail", fake)
    return sent


def token_of(link: str) -> str:
    return link.rsplit("/", 1)[1]


async def admin_of_new_tenant(api, monkeypatch, email="boss@acme.io"):
    monkeypatch.setattr(
        settings_store, "get_system_settings", system_flags(signup_mode="new_tenant", email_verification="off")
    )
    return await api.register(email, name="Boss", tenant_name="Acme")


async def test_email_invite_sends_mail_and_joins_with_role(api, monkeypatch, outbox, rt):
    boss = await admin_of_new_tenant(api, monkeypatch)
    viewer = next(r for r in (await api.get("rbac.list_roles", boss))["items"] if r["name"] == "viewer")
    out = await api.post("tenant.invite", boss, email="Lan@X.io", role_id=viewer["id"])
    assert out["email"] == "lan@x.io" and out["max_uses"] == 1 and out["link"].endswith(out["link"].rsplit("/", 1)[1])
    assert [(m["to"], m["template"], m["tenant"], m["role"]) for m in outbox] == [
        ("lan@x.io", "invite", "Acme", "viewer")
    ]
    assert any(m["routing_key"] == f"tenant.{boss.user['tenant']['id']}" for m in rt.sent)
    token = token_of(out["link"])
    preview = await api.get("invites.preview", token=token)
    assert (preview["tenant_name"], preview["role_name"], preview["email"]) == ("Acme", "viewer", "l***@x***.io")
    # đăng ký bằng lời mời ở chế độ invite_only vẫn được; email khác email được mời → 2114
    monkeypatch.setattr(settings_store, "get_system_settings", system_flags(signup_mode="invite_only"))
    wrong = {"email": "other@x.io", "password": PASSWORD, "invite_token": token}
    assert await api.err("POST", "auth.register", json=wrong) == (400, 2114)
    lan = await api.register("lan@x.io", invite_token=token)
    assert lan.user["tenant"]["slug"] == "acme" and [r["name"] for r in lan.user["roles"]] == ["viewer"]
    assert lan.user["email_verified"] is True  # mở được thư mời = sở hữu email
    again = {"email": "lan2@x.io", "password": PASSWORD, "invite_token": token}
    assert await api.err("POST", "auth.register", json=again) == (400, 2114)  # đã dùng hết lượt
    assert await api.get("tenant.list_invites", boss) == []


async def test_link_invite_many_uses_and_revoke(api, monkeypatch, outbox):
    boss = await admin_of_new_tenant(api, monkeypatch)
    link = await api.post("tenant.invite", boss, max_uses=2)
    assert link["email"] is None and link["max_uses"] == 2 and outbox == []
    token = token_of(link["link"])
    a = await api.register("a@link.io", invite_token=token)
    assert [r["name"] for r in a.user["roles"]] == ["member"] and a.user["email_verified"] is False
    pending = await api.get("tenant.list_invites", boss)
    assert [(p["id"], p["uses"], p["link"]) for p in pending] == [(link["id"], 1, None)]
    await api.post("tenant.revoke_invite", boss, invite_id=link["id"])
    assert await api.err("GET", "invites.preview", params={"token": token}) == (400, 2114)


async def test_invite_rules(api, monkeypatch, outbox):
    boss = await admin_of_new_tenant(api, monkeypatch)
    await api.register("taken@x.io", tenant_name="Other")
    assert await api.err("POST", "tenant.invite", boss, json={"email": "taken@x.io"}) == (409, 2109)
    member = await api.register("plain@x.io", tenant_name="Plain")
    other_invite = await api.post("tenant.invite", member)  # admin của tenant Plain
    assert await api.err("POST", "tenant.revoke_invite", boss, json={"invite_id": other_invite["id"]}) == (404, 1001)
    # chế độ soft: admin chưa xác thực email không mời được
    monkeypatch.setattr(settings_store, "get_system_settings", system_flags(signup_mode="new_tenant"))
    fresh = await api.register("fresh@x.io", tenant_name="Fresh")
    assert await api.err("POST", "tenant.invite", fresh, json={"email": "z@x.io"}) == (403, 2112)


async def test_member_cannot_invite_or_rename(api, monkeypatch, outbox):
    boss = await admin_of_new_tenant(api, monkeypatch)
    m = await api.register("m@acme.io", invite_token=token_of((await api.post("tenant.invite", boss))["link"]))
    assert await api.err("POST", "tenant.invite", m, json={}) == (403, 1005)
    assert await api.err("POST", "tenant.update", m, json={"name": "X"}) == (403, 1005)
    renamed = await api.post("tenant.update", boss, name="Acme Corp")
    assert renamed["name"] == "Acme Corp" and renamed["user_count"] == 2
