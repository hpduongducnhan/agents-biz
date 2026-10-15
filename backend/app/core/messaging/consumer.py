"""Gắn handler của miền vào RabbitBroker của process `consume` — subscriber (`bw.<miền>.<việc>`), event client
(`bw.rt.in`) và event không ai nhận. Lỗi → log (có loc) + ghi issue."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from faststream import AckPolicy
from faststream.rabbit import Channel, RabbitBroker, RabbitQueue
from faststream.rabbit.annotations import RabbitMessage
from pydantic import BaseModel, ValidationError

from app.core.cid import get_cid, set_cid
from app.core.connections.registry import get_connections
from app.core.logging import get_logger
from app.core.messaging.names import (
    RT_UNROUTED_QUEUE,
    dlq_queue,
    rt_in_exchange,
    rt_unrouted_exchange,
    work_queue,
)
from app.core.messaging.realtime import ENVELOPE_VERSION, WsContext, WsSpec
from app.core.messaging.streams import SubscriberSpec
from app.core.security.principal import is_disabled, principal_from_claims
from app.core.settings import active_settings
from app.observability.sinks import capture_issue

logger = get_logger(__name__)
PREFETCH = 10
DISABLED_CODE = 2103  # tài khoản bị khoá — mã của miền auth


def decode(message: RabbitMessage, model: type[BaseModel] | None) -> Any:
    data = json.loads(message.body) if message.body else {}
    return model.model_validate(data) if model is not None else data


def make_handler(
    label: str, call: Callable[[Any], Awaitable[None]], model: type[BaseModel] | None
) -> Callable[[RabbitMessage], Awaitable[None]]:
    async def handler(message: RabbitMessage) -> None:
        set_cid(message.correlation_id)
        try:
            payload = decode(message, model)
        except ValueError as exc:  # JSON hỏng / pydantic ValidationError
            logger.warning("message sai dạng %s: %s", label, exc, extra={"loc": "bus0502"})
            raise
        try:
            await call(payload)
        except Exception as exc:
            logger.warning("xử lý %s lỗi: %s", label, exc, extra={"loc": "bus0500"})
            await capture_issue(exc, source="consumer", loc="bus0500", context={"subscriber": label})
            raise

    handler.__name__ = f"bw_{label.replace('.', '_')}"
    return handler


def mount_subscriber(broker: RabbitBroker, spec: SubscriberSpec) -> list[RabbitQueue]:
    """Gắn subscriber; trả queue phụ (DLQ) cần khai sau `broker.start()`."""
    queue = work_queue(spec.queue, dlq=True)
    broker.subscriber(queue, channel=Channel(prefetch_count=PREFETCH), ack_policy=AckPolicy.REJECT_ON_ERROR)(
        make_handler(spec.event, spec.func, spec.model)
    )
    return [dlq_queue(queue.name)]


def _stale(ts: Any) -> bool:
    """Event client chờ trong queue quá lâu (consumer chết / nghẽn) — người bấm đã thôi chờ, không chạy nữa."""
    try:
        sent = datetime.fromisoformat(str(ts))
    except ValueError:
        return True
    if sent.tzinfo is None:
        return True
    return (datetime.now(UTC) - sent).total_seconds() > active_settings().REALTIME_EVENT_MAX_AGE


def ws_handler(spec: WsSpec) -> Callable[[RabbitMessage], Awaitable[None]]:
    """Event client: kiểm cũ (1009) → khoá (2103) → quyền (1005) → dữ liệu (1002). Lỗi KHÔNG ném (ack) mà trả
    `sys:error {code, cid}` cho người gửi để UI không treo."""

    async def handler(message: RabbitMessage) -> None:
        set_cid(message.correlation_id)
        try:
            env = json.loads(message.body)
        except ValueError as exc:
            logger.warning("event client không phải JSON (%s): %s", spec.queue, exc, extra={"loc": "ws0102"})
            return
        if not isinstance(env, dict) or env.get("v") != ENVELOPE_VERSION:
            logger.warning("envelope không hỗ trợ (%s)", spec.queue, extra={"loc": "ws0104"})
            return
        principal = principal_from_claims(env.get("claims") or {})
        if principal is None:
            logger.warning("event client thiếu / sai claims (%s) — realtime lỗi?", spec.queue, extra={"loc": "ws0103"})
            return
        cid = get_cid()
        ctx = WsContext(principal=principal, sid=env.get("sid"), cid=cid, event=str(env.get("event")))
        if _stale(env.get("ts")):
            logger.warning("event client quá hạn (%s, ts=%s) — bỏ", spec.queue, env.get("ts"), extra={"loc": "ws0105"})
            await ctx.reply("sys:error", {"code": 1009, "cid": cid})
            return
        if await is_disabled(get_connections().redis.ro, principal.user_id):
            await ctx.reply("sys:error", {"code": DISABLED_CODE, "cid": cid})
            return
        if not principal.can(spec.permission):
            await ctx.reply("sys:error", {"code": 1005, "cid": cid})
            return
        raw = env.get("data") or {}
        try:
            data = spec.model.model_validate(raw) if spec.model is not None else raw
        except ValidationError:
            await ctx.reply("sys:error", {"code": 1002, "cid": cid})
            return
        try:
            await spec.func(ctx, data)
        except Exception as exc:  # noqa: BLE001 — lỗi handler trả sys:error cho người gửi, không requeue
            logger.warning("xử lý event client %s lỗi: %s", spec.event, exc, extra={"loc": "ws0500"})
            context = {"event": spec.event, "user_id": str(principal.user_id)}
            await capture_issue(exc, source="ws", loc="ws0500", context=context)
            await ctx.reply("sys:error", {"code": 1000, "cid": cid})

    handler.__name__ = f"bw_ws_{spec.event.replace('.', '_')}"
    return handler


def mount_ws(broker: RabbitBroker, spec: WsSpec) -> None:
    """Queue bền `bw.rt.in.<miền>.<việc>` bind `bw.rt.in` theo đúng tên event."""
    queue = work_queue(spec.queue, routing_key=spec.event)
    broker.subscriber(
        queue, rt_in_exchange(), channel=Channel(prefetch_count=PREFETCH), ack_policy=AckPolicy.REJECT_ON_ERROR
    )(ws_handler(spec))


async def _log_unrouted(message: RabbitMessage) -> None:
    set_cid(message.correlation_id)
    try:
        env = json.loads(message.body)
    except ValueError:
        env = None
    env = env if isinstance(env, dict) else {}
    logger.warning("event client không ai nhận: %s (sid=%s)", env.get("event"), env.get("sid"), extra={"loc": "ws0101"})


def mount_unrouted(broker: RabbitBroker) -> None:
    """Event client không miền nào khai (alternate exchange của bw.rt.in) → log để thấy lỗi tên."""
    broker.subscriber(work_queue(RT_UNROUTED_QUEUE), rt_unrouted_exchange())(_log_unrouted)
