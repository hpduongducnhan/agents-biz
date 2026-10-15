"""Web Push: cờ bật, khoá VAPID, SSRF guard, payload, hook xếp task, task gửi và dọn đăng ký."""

import asyncio
import json

import pytest
from sqlmodel import select

from app.core.connections.registry import get_connections
from app.credentials import crypto
from app.notifications import push, service
from app.notifications.models import PushKey
from app.notifications.webpush import b64u, unb64u
from tests.auth.factories import make_user
from tests.notifications.push_lib import FakeClient, add_note, add_sub, subs, ua_keys
from tests.notifications.test_webpush import decrypt

pytestmark = pytest.mark.integration


@pytest.fixture
def on(app_env, monkeypatch):
    monkeypatch.setattr(app_env, "CREDENTIAL_KEYS", crypto.new_key())
    return app_env


@pytest.fixture
def off(app_env, monkeypatch):
    monkeypatch.setattr(app_env, "CREDENTIAL_KEYS", "")
    monkeypatch.setitem(push._state, "warned", False)
    return app_env


@pytest.fixture
def kiq(monkeypatch):
    calls = []

    async def fake(ids):
        calls.append(ids)

    monkeypatch.setattr(push.web_push, "kiq", fake)
    return calls


def test_enabled_warns_once_when_keys_missing(off, bw_log):
    assert push.enabled(off) is False and push.enabled(off) is False
    warns = [r for r in bw_log() if r.get("loc") == "ntf0601"]
    assert len(warns) == 1 and "DEFAULTS_APPLIED=[web_push=off]" in warns[0]["msg"]


def test_enabled_true_with_keys(on):
    assert push.enabled(on) is True


def test_subject_prefers_https_public_url(app_env, monkeypatch):
    monkeypatch.setattr(app_env, "PUBLIC_URL", "https://bizwithagents.example.com/")
    assert push.subject(app_env) == "https://bizwithagents.example.com"
    for bad in ("", "http://localhost:8201"):
        monkeypatch.setattr(app_env, "PUBLIC_URL", bad)
        assert push.subject(app_env) == "mailto:noreply@bizwithagents.local"


@pytest.mark.parametrize(
    "url,ok",
    [
        ("https://fcm.googleapis.com/fcm/send/x", True),
        ("https://updates.push.services.mozilla.com/wpush/v2/x", True),
        ("https://web.push.apple.com/x", True),
        ("https://wns2-par02p.notify.windows.com/w/?token=x", True),
        ("https://push.apple.com/x", True),
        ("http://fcm.googleapis.com/x", False),
        ("https://evil.com/x", False),
        ("https://fcm.googleapis.com.evil.com/x", False),
        ("https://evilfcm.googleapis.com.io/x", False),
        ("https://notfcm.googleapis.com/x", False),  # trùng đuôi chữ nhưng không phải subdomain
        ("https://127.0.0.1/x", False),
        ("ftp://fcm.googleapis.com/x", False),
        ("not a url", False),
        ("", False),
    ],
)
def test_allowed_endpoint(url, ok):
    assert push.allowed_endpoint(url) is ok


def test_valid_keys():
    _, p256dh, auth = ua_keys()
    assert push.valid_keys(p256dh, auth)
    assert not push.valid_keys(p256dh, "AAAA")  # auth sai độ dài
    assert not push.valid_keys("AAAA", auth)  # điểm sai độ dài
    bad_point = bytes([2]) + unb64u(p256dh)[1:]  # điểm nén
    assert not push.valid_keys(b64u(bad_point), auth)


async def test_vapid_created_once_encrypted_and_reusable(on, api):
    first = await push.public_key(on)
    assert await push.public_key(on) == first
    async with get_connections().postgres.ro() as s:
        rows = list((await s.exec(select(PushKey))).all())
    assert len(rows) == 1 and rows[0].id == 1 and rows[0].public_key == first
    assert "BEGIN PRIVATE KEY" not in rows[0].private_key_enc  # đã mã hoá Fernet
    async with get_connections().postgres.rw() as s:
        keys = await push.vapid(s, on)
    assert keys.public_key == first and keys.private_pem.startswith("-----BEGIN PRIVATE KEY-----")


async def test_vapid_concurrent_creation_keeps_single_row(on, api):
    async def one():
        async with get_connections().postgres.rw() as s:
            return (await push.vapid(s, on)).public_key

    got = await asyncio.gather(*(one() for _ in range(4)))
    async with get_connections().postgres.ro() as s:
        rows = list((await s.exec(select(PushKey))).all())
    assert len(rows) == 1 and set(got) <= {rows[0].public_key, *got}


async def test_payload_uses_link_action_else_notifications(api):
    u = await api.as_user("p@x.io")
    link = await add_note(u.id, action={"kind": "link", "to": "/groups/1"})
    none = await add_note(u.id)
    external = await add_note(u.id, action={"kind": "link", "to": "https://evil.com"})
    other = await add_note(u.id, action={"kind": "call", "to": "/x"})
    got = [json.loads(push.payload(r)) for r in (link, none, external, other)]
    assert [g["url"] for g in got] == ["/groups/1", "/notifications", "/notifications", "/notifications"]
    assert got[0] == {"id": str(link.id), "kind": "test", "title": "Tiêu đề", "body": "", "url": "/groups/1"}


async def test_enqueue_only_when_enabled_and_has_subscriber(on, api, kiq):
    a, b = await api.as_user("a@x.io"), await api.as_user("b@x.io")
    na, nb = await add_note(a.id), await add_note(b.id)
    await push.enqueue([])
    await push.enqueue([na, nb])
    assert kiq == []  # chưa ai bật
    await add_sub(b.id)
    await push.enqueue([na])
    assert kiq == []  # người nhận a không có máy
    await push.enqueue([na, nb])
    assert kiq == [[str(na.id), str(nb.id)]]


async def test_enqueue_noop_when_disabled(off, api, kiq):
    u = await api.as_user("a@x.io")
    await add_sub(u.id)
    await push.enqueue([await add_note(u.id)])
    assert kiq == []


async def test_real_notification_goes_through_hook(on, api, kiq):
    n = await api.as_user("n@x.io")
    await add_sub(n.id)
    root = await api.as_user("root@test.local")
    await api.post("notifications.send_test", root, email="n@x.io", title="Chào")
    assert len(kiq) == 1 and len(kiq[0]) == 1


async def test_hook_failure_is_only_logged(app_env, monkeypatch, bw_log):
    async def bad(rows):
        raise RuntimeError("hỏng")

    monkeypatch.setattr(service, "PUSHED_HOOKS", [bad])
    monkeypatch.setattr(service, "emit_to_user", lambda *a, **k: asyncio.sleep(0))
    async with get_connections().postgres.rw() as s:
        user = await make_user(s, "h@x.io")
    await service.push([await add_note(user.id)])
    assert any(r.get("loc") == "ntf0504" for r in bw_log())


async def test_web_push_sends_encrypted_payload_and_marks_ok(on, api, monkeypatch):
    u = await api.as_user("u@x.io")
    sub, ua = await add_sub(u.id, failures=3)
    note = await add_note(u.id, title="Xin chào", action={"kind": "link", "to": "/slips/1"})
    fake = FakeClient().install(monkeypatch)
    assert await push.web_push([str(note.id)]) == {"sent": 1, "gone": 0, "failed": 0}
    [call] = fake.calls
    assert call["url"] == sub.endpoint
    assert call["headers"]["Authorization"].startswith("vapid t=") and call["headers"]["TTL"] == "86400"
    assert json.loads(decrypt(call["content"], ua, sub.auth)) == json.loads(push.payload(note))
    [row] = await subs(u.id)
    assert row.failures == 0 and row.last_ok_at is not None


async def test_web_push_status_handling(on, api, monkeypatch):
    u = await api.as_user("u@x.io")
    ok, gone404, gone410, bad, net = [(await add_sub(u.id))[0] for _ in range(5)]
    note = await add_note(u.id)
    fake = FakeClient(
        status={gone404.endpoint: 404, gone410.endpoint: 410, bad.endpoint: 500}, boom={net.endpoint}
    ).install(monkeypatch)
    assert await push.web_push([str(note.id)]) == {"sent": 1, "gone": 2, "failed": 2}
    assert len(fake.calls) == 5
    left = {s.endpoint: s for s in await subs(u.id)}
    assert set(left) == {ok.endpoint, bad.endpoint, net.endpoint}
    assert (left[ok.endpoint].failures, left[bad.endpoint].failures, left[net.endpoint].failures) == (0, 1, 1)


async def test_web_push_deletes_after_ten_failures(on, api, monkeypatch):
    u = await api.as_user("u@x.io")
    sub, _ = await add_sub(u.id, failures=push.MAX_FAILURES - 1)
    note = await add_note(u.id)
    FakeClient(status={sub.endpoint: 503}).install(monkeypatch)
    assert (await push.web_push([str(note.id)]))["failed"] == 1
    assert await subs(u.id) == []


async def test_web_push_drops_disallowed_endpoint_without_request(on, api, monkeypatch):
    u = await api.as_user("u@x.io")
    await add_sub(u.id, endpoint="https://evil.example.com/x")
    fake = FakeClient().install(monkeypatch)
    note = await add_note(u.id)
    assert await push.web_push([str(note.id)]) == {"sent": 0, "gone": 1, "failed": 0}
    assert fake.calls == [] and await subs(u.id) == []


async def test_web_push_only_targets_recipient_devices(on, api, monkeypatch):
    a, b = await api.as_user("a@x.io"), await api.as_user("b@x.io")
    await add_sub(a.id)
    sb, _ = await add_sub(b.id)
    fake = FakeClient().install(monkeypatch)
    await push.web_push([str((await add_note(b.id)).id)])
    assert [c["url"] for c in fake.calls] == [sb.endpoint]


async def test_web_push_noop_when_disabled(off, api, monkeypatch):
    u = await api.as_user("u@x.io")
    await add_sub(u.id)
    note = await add_note(u.id)
    fake = FakeClient().install(monkeypatch)
    assert await push.web_push([str(note.id)]) == {"sent": 0} and fake.calls == []


async def test_web_push_without_subscribers_creates_no_key(on, api, monkeypatch):
    u = await api.as_user("u@x.io")
    note = await add_note(u.id)
    fake = FakeClient().install(monkeypatch)
    assert await push.web_push([str(note.id)]) == {"sent": 0} and fake.calls == []
    async with get_connections().postgres.ro() as s:
        assert (await s.exec(select(PushKey))).first() is None  # không sinh khoá khi chẳng có ai nhận
