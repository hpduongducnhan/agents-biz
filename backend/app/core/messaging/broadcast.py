"""Broadcast nội bộ `bw.sys.bcast`: báo MỌI process "đã đổi" để xoá cache (không bền, payload nhỏ).

Mỗi process một queue exclusive + auto-delete bind `#`, lọc theo topic lúc nhận → handler đăng ký muộn vẫn nhận.
Cache xoá theo broadcast phải có TTL (broadcast có thể lỡ).
"""

from __future__ import annotations

import inspect
import json
import re
import uuid
from collections.abc import Awaitable, Callable

from faststream.rabbit import RabbitBroker, RabbitQueue
from faststream.rabbit.annotations import RabbitMessage

from app.core.cid import set_cid
from app.core.logging import get_logger
from app.core.messaging.hub import get_hub
from app.core.messaging.names import bcast_exchange
from app.core.messaging.util import utc_iso
from app.core.settings import Settings

logger = get_logger(__name__)
TOPIC_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
Handler = Callable[[dict], Awaitable[None]]
_HANDLERS: dict[str, list[Handler]] = {}


def _check_topic(topic: str) -> str:
    if not TOPIC_RE.match(topic):
        raise ValueError(f"topic broadcast '{topic}' phải dạng <miền>.<việc>")
    return topic


def on_broadcast(topic: str):
    _check_topic(topic)

    def deco(func: Handler) -> Handler:
        if not inspect.iscoroutinefunction(func):
            raise TypeError(f"handler broadcast {func.__qualname__} phải là async def")
        _HANDLERS.setdefault(topic, []).append(func)
        return func

    return deco


def broadcast_handlers() -> dict[str, list[Handler]]:
    return _HANDLERS


async def broadcast(topic: str, data: dict | None = None) -> None:
    body = {"key": _check_topic(topic), "data": data or {}, "ts": utc_iso()}
    await get_hub().publish(body, exchange=bcast_exchange(), routing_key=topic, persist=False, mandatory=False)


async def _dispatch(message: RabbitMessage) -> None:
    set_cid(message.correlation_id)
    try:
        body = json.loads(message.body)
    except ValueError:
        body = None
    if not isinstance(body, dict):
        logger.warning("broadcast sai dạng — bỏ", extra={"loc": "bus0402"})
        return
    topic = body.get("key")
    for func in _HANDLERS.get(topic, []):
        try:
            await func(body.get("data") or {})
        except Exception as exc:  # noqa: BLE001 — 1 handler hỏng không được chặn handler khác
            logger.warning("broadcast %s → %s lỗi: %s", topic, func.__qualname__, exc, extra={"loc": "bus0401"})


class BroadcastListener:
    """Kết nối RIÊNG của process cho broadcast (độc lập với consumer của process)."""

    def __init__(self, settings: Settings, proc: str) -> None:
        self.settings = settings
        self.queue_name = f"bw.sys.bcast.{proc}.{uuid.uuid4().hex[:8]}"
        self._broker: RabbitBroker | None = None

    async def start(self) -> None:
        broker = RabbitBroker(self.settings.RABBITMQ_URL, logger=None)
        queue = RabbitQueue(self.queue_name, exclusive=True, auto_delete=True, routing_key="#")
        broker.subscriber(queue, bcast_exchange())(_dispatch)
        await broker.start()
        self._broker = broker

    async def stop(self) -> None:
        if self._broker is not None:
            await self._broker.stop()
            self._broker = None
