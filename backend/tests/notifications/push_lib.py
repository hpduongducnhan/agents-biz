"""Dựng dữ liệu Web Push cho test: khoá máy người dùng, đăng ký trong DB, HTTP client giả."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx2
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlmodel import select

from app.core.connections.registry import get_connections
from app.notifications import push
from app.notifications.models import Notification, PushSubscription
from app.notifications.webpush import b64u

FCM = "https://fcm.googleapis.com/fcm/send/"


def ua_keys() -> tuple[ec.EllipticCurvePrivateKey, str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return key, b64u(pub), b64u(bytes(range(16)))


async def add_sub(
    user_id: str, endpoint: str | None = None, **kw
) -> tuple[PushSubscription, ec.EllipticCurvePrivateKey]:
    key, p256dh, auth = ua_keys()
    row = PushSubscription(
        user_id=uuid.UUID(str(user_id)), endpoint=endpoint or FCM + uuid.uuid4().hex, p256dh=p256dh, auth=auth, **kw
    )
    async with get_connections().postgres.rw() as s:
        s.add(row)
    return row, key


async def subs(user_id: str | None = None) -> list[PushSubscription]:
    async with get_connections().postgres.ro() as s:
        stmt = select(PushSubscription).order_by(PushSubscription.created_at)
        if user_id:
            stmt = stmt.where(PushSubscription.user_id == uuid.UUID(str(user_id)))
        return list((await s.exec(stmt)).all())


async def add_note(user_id: str, **kw) -> Notification:
    row = Notification(user_id=uuid.UUID(str(user_id)), kind="test", title=kw.pop("title", "Tiêu đề"), **kw)
    async with get_connections().postgres.rw() as s:
        s.add(row)
    return row


class FakeClient:
    """Thay `httpx2.AsyncClient` của push: trả status theo endpoint (mặc định 201); `boom` → ném lỗi mạng."""

    def __init__(self, status: dict[str, int] | None = None, boom: set[str] | None = None) -> None:
        self.status, self.boom, self.calls = status or {}, boom or set(), []

    def install(self, monkeypatch) -> FakeClient:
        outer = self

        class Client:
            def __init__(self, **kw) -> None:
                outer.kwargs = kw

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc) -> None:
                return None

            async def post(self, url, content=None, headers=None):
                outer.calls.append({"url": url, "content": content, "headers": headers})
                if url in outer.boom:
                    raise httpx2.ConnectError("boom")
                return SimpleNamespace(status_code=outer.status.get(url, 201))

        monkeypatch.setattr(push, "httpx2", SimpleNamespace(AsyncClient=Client, HTTPError=httpx2.HTTPError))
        return self
