"""Inbox thông báo: một dòng `notifications` / người nhận, ghi trong một session RW ngắn SAU commit
của thao tác, rồi đẩy `core:notification` tới phòng `user:<id>`. Người nhận offline vẫn thấy khi quay lại."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import Any, Protocol

from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.auth.models import User
from app.core.connections.registry import get_connections
from app.core.logging import get_logger
from app.core.messaging.realtime import emit_to_user
from app.core.operations.runner import set_notifier
from app.notifications.models import Notification
from app.notifications.schemas import NotificationOut, validate_payload

logger = get_logger(__name__)
# Miền sau đăng ký: Web Push gửi tiếp các dòng vừa đẩy socket tới máy đã bật thông báo của người nhận.
PUSHED_HOOKS: list[Callable[[list[Notification]], Awaitable[None]]] = []
NOTIFICATION_EVENT = "core:notification"
TITLE_LIMIT = 300
Payload = BaseModel | dict[str, Any] | None


class PendingLike(Protocol):
    """Một mục `ctx.notify(...)` runner đã xếp hàng — cùng tên với tham số của `ctx.notify`."""

    user_id: uuid.UUID | str
    kind: str
    title: str
    body: str
    params: dict[str, Any] | None
    action: dict[str, Any] | None


def to_out(row: Notification) -> NotificationOut:
    return NotificationOut.model_validate(row, from_attributes=True)


def payload(row: Notification) -> dict[str, Any]:
    return to_out(row).model_dump(mode="json")


def _uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _row(user_id: uuid.UUID | str, kind: str, title: str, body: str, params: Payload, action: Payload) -> Notification:
    clean_params, clean_action = validate_payload(kind, params, action)
    return Notification(
        user_id=_uuid(user_id),
        kind=kind,
        title=title[:TITLE_LIMIT],
        body=body or "",
        params=clean_params,
        action=clean_action,
    )


async def push(rows: list[Notification]) -> None:
    """Đẩy `core:notification` cho các dòng đã commit, rồi các hook (Web Push) — mọi lỗi chỉ log."""
    for row in rows:
        try:
            await emit_to_user(row.user_id, NOTIFICATION_EVENT, payload(row))
        except Exception as exc:  # noqa: BLE001 — dòng inbox đã bền; realtime chỉ là best-effort
            logger.warning("đẩy thông báo %s lỗi: %s", row.id, exc, extra={"loc": "ntf0502"})
    for hook in PUSHED_HOOKS:
        try:
            await hook(rows)
        except Exception as exc:  # noqa: BLE001 — thông báo đẩy ngoài app là best-effort
            logger.warning("hook sau đẩy thông báo lỗi: %s", exc, extra={"loc": "ntf0504"})


async def _store_and_push(rows: list[Notification]) -> list[Notification]:
    if not rows:
        return rows
    async with get_connections().postgres.rw() as session:
        session.add_all(rows)
        await session.flush()
    await push(rows)
    return rows


async def stage(
    session: AsyncSession,
    user_id: uuid.UUID | str,
    kind: str,
    title: str,
    body: str = "",
    params: Payload = None,
    action: Payload = None,
) -> Notification:
    """Ghi trong transaction đang mở để biết `id` ngay; người gọi tự `push` SAU commit (`ctx.after_commit`)."""
    row = _row(user_id, kind, title, body, params, action)
    session.add(row)
    await session.flush()
    return row


async def notify_users(
    user_ids: Iterable[uuid.UUID | str],
    kind: str,
    title: str,
    body: str = "",
    params: Payload = None,
    action: Payload = None,
) -> list[Notification]:
    """Ghi + đẩy ngay (task nền, sink issue…). Người nhận trùng chỉ nhận một dòng; dữ liệu sai → ValueError."""
    rows = [_row(u, kind, title, body, params, action) for u in dict.fromkeys(_uuid(u) for u in user_ids)]
    return await _store_and_push(rows)


async def superadmin_ids(session: AsyncSession) -> list[uuid.UUID]:
    stmt = select(User.id).where(User.is_superadmin.is_(True), User.is_active.is_(True))
    return list((await session.exec(stmt)).all())


async def notify_superadmins(
    kind: str, title: str, body: str = "", params: Payload = None, action: Payload = None
) -> list[Notification]:
    async with get_connections().postgres.ro() as session:
        ids = await superadmin_ids(session)
    return await notify_users(ids, kind, title, body, params, action)


async def deliver_pending(items: Sequence[PendingLike]) -> None:
    """Notifier của runner: thao tác đã commit — mục sai bị bỏ (`ntf0503`), lỗi ghi chỉ log (`ntf0501`), không ném."""
    rows: list[Notification] = []
    for item in items:
        try:
            rows.append(_row(item.user_id, item.kind, item.title, item.body, item.params, item.action))
        except ValueError as exc:
            logger.warning("bỏ thông báo %s sai dữ liệu: %s", item.kind, exc, extra={"loc": "ntf0503"})
    try:
        await _store_and_push(rows)
    except Exception as exc:  # noqa: BLE001 — thao tác đã commit; mất thông báo phải thấy trong log
        logger.error("ghi %d thông báo sau commit lỗi: %s", len(rows), exc, extra={"loc": "ntf0501"})


def install() -> None:
    """Gắn notifier vào runner — `app.notifications.ops` gọi khi được nạp (`load_domains`, mọi role)."""
    set_notifier(deliver_pending)
