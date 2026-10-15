"""Web Push: khoá VAPID tự sinh (mã hoá `CREDENTIAL_KEYS`), kiểm endpoint, gửi
các dòng thông báo vừa đẩy socket tới mọi máy đã bật của người nhận — task `notifications.web_push` (worker)."""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx2
from sqlalchemy import delete, update
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import select

from app.core.connections.registry import get_connections
from app.core.logging import get_logger
from app.core.messaging.tasks import task
from app.core.settings import Settings, active_settings
from app.credentials.crypto import configured_keys, decrypt, encrypt
from app.notifications.models import Notification, PushKey, PushSubscription
from app.notifications.service import PUSHED_HOOKS
from app.notifications.webpush import VapidKeys, headers, new_vapid_keys, unb64u
from app.notifications.webpush import encrypt as seal

logger = get_logger(__name__)
_state = {"warned": False}
MAX_FAILURES = 10
TIMEOUT = 10.0
# Chỉ gửi tới push service của trình duyệt — endpoint do người dùng gửi lên, chặn SSRF tới địa chỉ khác.
PUSH_HOSTS = (
    "fcm.googleapis.com",
    "push.apple.com",
    "push.services.mozilla.com",
    "notify.windows.com",
)


def enabled(settings: Settings) -> bool:
    """Bật khi có `CREDENTIAL_KEYS` (khoá VAPID riêng mã hoá được, mọi process giải được); thiếu → no-op (R12)."""
    if configured_keys(settings):
        return True
    if not _state["warned"]:
        _state["warned"] = True
        logger.warning("Web Push tắt: thiếu CREDENTIAL_KEYS; DEFAULTS_APPLIED=[web_push=off]", extra={"loc": "ntf0601"})
    return False


def subject(settings: Settings) -> str:
    base = settings.PUBLIC_URL.strip().rstrip("/")
    return base if base.startswith("https://") else "mailto:noreply@bizwithagents.local"


def allowed_endpoint(endpoint: str) -> bool:
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host == h or host.endswith("." + h) for h in PUSH_HOSTS)


def valid_keys(p256dh: str, auth: str) -> bool:
    try:
        point, secret = unb64u(p256dh), unb64u(auth)
    except ValueError:
        return False
    return len(point) == 65 and point[0] == 4 and len(secret) == 16


async def public_key(settings: Settings) -> str:
    """Khoá công khai VAPID; chưa có thì sinh (một lần — `ON CONFLICT DO NOTHING` khi nhiều process cùng sinh)."""
    async with get_connections().postgres.rw() as session:
        return (await vapid(session, settings)).public_key


async def vapid(session, settings: Settings) -> VapidKeys:
    row = await session.get(PushKey, 1)
    if row is None:
        fresh = new_vapid_keys()
        cipher, kid = encrypt(fresh.private_pem, settings)
        values = {"id": 1, "public_key": fresh.public_key, "private_key_enc": cipher, "key_id": kid}
        await session.exec(insert(PushKey).values(**values).on_conflict_do_nothing(index_elements=["id"]))
        await session.flush()
        row = await session.get(PushKey, 1, populate_existing=True)
        logger.info("tạo khoá VAPID cho Web Push (key_id=%s)", row.key_id, extra={"loc": "ntf0602"})
    return VapidKeys(private_pem=decrypt(row.private_key_enc, settings), public_key=row.public_key)


def _url(row: Notification) -> str:
    to = (row.action or {}).get("to")
    return (
        to
        if (row.action or {}).get("kind") == "link" and isinstance(to, str) and to.startswith("/")
        else "/notifications"
    )


def payload(row: Notification) -> bytes:
    data = {"id": str(row.id), "kind": row.kind, "title": row.title, "body": row.body, "url": _url(row)}
    return json.dumps(data, ensure_ascii=False).encode()


async def _has_subscribers(user_ids: list[uuid.UUID]) -> bool:
    async with get_connections().postgres.ro() as session:
        stmt = select(PushSubscription.id).where(PushSubscription.user_id.in_(user_ids)).limit(1)
        return (await session.exec(stmt)).first() is not None


async def enqueue(rows: list[Notification]) -> None:
    """Hook sau `notifications.service.push`: người nhận có máy đã bật → xếp task gửi (một task cho cả lô)."""
    if not rows or not enabled(active_settings()):
        return
    if await _has_subscribers(sorted({r.user_id for r in rows})):
        await web_push.kiq([str(r.id) for r in rows])


@task("notifications.web_push", retry=0, timeout=60)
async def web_push(ids: list[str]) -> dict:
    settings = active_settings()
    if not enabled(settings):
        return {"sent": 0}
    async with get_connections().postgres.rw() as session:
        rows = list(
            (await session.exec(select(Notification).where(Notification.id.in_([uuid.UUID(i) for i in ids])))).all()
        )
        subs = list(
            (
                await session.exec(
                    select(PushSubscription).where(PushSubscription.user_id.in_({r.user_id for r in rows}))
                )
            ).all()
        )
        keys = await vapid(session, settings) if subs else None
    if keys is None:
        return {"sent": 0}
    by_user: dict[uuid.UUID, list[PushSubscription]] = defaultdict(list)
    for s in subs:
        by_user[s.user_id].append(s)
    ok, gone, failed = set(), set(), set()
    async with httpx2.AsyncClient(timeout=TIMEOUT) as client:
        for row in rows:
            body = payload(row)
            for s in by_user[row.user_id]:
                if not allowed_endpoint(s.endpoint):
                    gone.add(s.id)
                    continue
                try:
                    res = await client.post(
                        s.endpoint,
                        content=seal(body, s.p256dh, s.auth),
                        headers=headers(s.endpoint, keys, subject(settings)),
                    )
                except (httpx2.HTTPError, ValueError) as exc:
                    logger.warning("gửi Web Push lỗi: %s", exc, extra={"loc": "ntf0603"})
                    failed.add(s.id)
                    continue
                if res.status_code in (404, 410):
                    gone.add(s.id)
                elif res.status_code >= 400:
                    logger.warning("push service trả %s", res.status_code, extra={"loc": "ntf0604"})
                    failed.add(s.id)
                else:
                    ok.add(s.id)
    await _record(ok, gone, failed - gone)
    return {"sent": len(ok), "gone": len(gone), "failed": len(failed)}


async def _record(ok: set[uuid.UUID], gone: set[uuid.UUID], failed: set[uuid.UUID]) -> None:
    S = PushSubscription
    async with get_connections().postgres.rw() as session:
        if ok:
            await session.exec(update(S).where(S.id.in_(ok)).values(failures=0, last_ok_at=datetime.now(UTC)))
        if failed:
            await session.exec(update(S).where(S.id.in_(failed)).values(failures=S.failures + 1))
        await session.exec(delete(S).where(S.id.in_(gone) | (S.failures >= MAX_FAILURES)))
    if gone:
        logger.info("gỡ %d đăng ký Web Push hết hạn", len(gone), extra={"loc": "ntf0605"})


PUSHED_HOOKS.append(enqueue)
