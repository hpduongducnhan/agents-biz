"""Xác thực email + quên / đặt lại mật khẩu (D14): thư đi sau commit, link dùng một lần, chế độ `required` chặn đăng
nhập tới khi xác thực, op gửi thư không lộ email có tài khoản hay không."""

import pytest

from app.auth import emailflow
from app.system import settings_store
from tests.auth.api import PASSWORD, system_flags

pytestmark = pytest.mark.integration


@pytest.fixture
def outbox(monkeypatch):
    sent: list[dict] = []

    async def fake(to, template, locale, **ctx):
        sent.append({"to": to, "template": template, "locale": locale, **ctx})
        return "id"

    monkeypatch.setattr(emailflow, "queue_mail", fake)
    return sent


def token_of(mail: dict) -> str:
    return mail["link"].split("token=", 1)[1]


async def test_soft_mode_sends_verify_and_link_verifies_once(api, outbox):
    s = await api.register("v@x.io", name="Vy")
    assert s.verification_sent and s.tokens  # soft: vẫn có phiên
    assert [(m["to"], m["template"], m["name"]) for m in outbox] == [("v@x.io", "verify_email", "Vy")]
    assert "/verify-email?token=" in outbox[0]["link"]
    await api.post("auth.verify_email", token=token_of(outbox[0]))
    assert (await api.get("auth.me", s))["email_verified"] is True
    assert await api.err("POST", "auth.verify_email", json={"token": token_of(outbox[0])}) == (400, 2114)


async def test_required_mode_blocks_login_until_verified(api, monkeypatch, outbox):
    monkeypatch.setattr(settings_store, "get_system_settings", system_flags(email_verification="required"))
    data = await api.post("auth.register", email="r@x.io", password=PASSWORD)
    assert data["tokens"] is None and data["verification_sent"] is True
    assert await api.err("POST", "auth.login", json={"email": "r@x.io", "password": PASSWORD}) == (403, 2113)
    await api.post("auth.request_verify", email="r@x.io")  # gửi lại: link cũ hết hiệu lực
    assert len(outbox) == 2
    assert await api.err("POST", "auth.verify_email", json={"token": token_of(outbox[0])}) == (400, 2114)
    await api.post("auth.verify_email", token=token_of(outbox[1]))
    assert (await api.login("r@x.io")).user["email_verified"] is True


async def test_off_mode_sends_nothing(api, monkeypatch, outbox):
    monkeypatch.setattr(settings_store, "get_system_settings", system_flags(email_verification="off"))
    s = await api.register("off@x.io")
    assert not s.verification_sent and outbox == []
    await api.post("auth.request_verify", email="off@x.io")
    assert outbox == []


async def test_forgot_and_reset_password(api, outbox):
    s = await api.register("f@x.io")
    outbox.clear()
    assert await api.post("auth.forgot_password", email="ghost@x.io") == {"ok": True}  # không lộ
    assert outbox == []
    await api.post("auth.forgot_password", email="F@X.io")
    mail = outbox[0]
    assert mail["template"] == "reset_password" and "/reset-password?token=" in mail["link"]
    bad = {"token": token_of(mail), "new_password": "x"}
    assert await api.err("POST", "auth.reset_password", json=bad) == (422, 2107)
    await api.post("auth.reset_password", token=token_of(mail), new_password="mat-khau-moi-1")
    assert await api.err("POST", "auth.refresh", json={"refresh_token": s.tokens["refresh_token"]}) == (401, 2104)
    again = await api.login("f@x.io", "mat-khau-moi-1")
    assert again.user["email_verified"] is True
    assert await api.err(
        "POST", "auth.reset_password", json={"token": token_of(mail), "new_password": "khac-nua-123"}
    ) == (
        400,
        2114,
    )


async def test_email_ops_are_rate_limited(api, app_env, monkeypatch, outbox):
    monkeypatch.setattr(app_env, "AUTH_EMAIL_RATE_LIMIT", 2)
    for _ in range(2):
        await api.post("auth.forgot_password", email="rl@x.io")
    assert await api.err("POST", "auth.forgot_password", json={"email": "rl@x.io"}) == (429, 1007)
