"""MessagingHub — kết nối RabbitMQ của process để PUBLISH (mở lười). Một broker duy nhất: RABBITMQ_URL (B3)."""

from __future__ import annotations

import asyncio
from typing import Any

from faststream.rabbit import RabbitBroker, RabbitExchange, RabbitQueue
from taskiq_aio_pika import AioPikaBroker

from app.core.cid import get_cid, new_cid
from app.core.logging import get_logger
from app.core.messaging.lanes import LANES
from app.core.settings import Settings

logger = get_logger(__name__)


class MessagingHub:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._broker: RabbitBroker | None = None
        self._declared: set[tuple[str, str]] = set()
        self._tasks: AioPikaBroker | None = None
        self._lock = asyncio.Lock()

    async def broker(self) -> RabbitBroker:
        async with self._lock:
            if self._broker is None:
                broker = RabbitBroker(self.settings.RABBITMQ_URL, logger=None)
                await broker.connect()
                self._broker = broker
            return self._broker

    async def declare_exchange(self, exchange: RabbitExchange) -> None:
        if ("exchange", exchange.name) not in self._declared:
            await (await self.broker()).declare_exchange(exchange)
            self._declared.add(("exchange", exchange.name))

    async def declare_queue(self, queue: RabbitQueue) -> None:
        if ("queue", queue.name) not in self._declared:
            await (await self.broker()).declare_queue(queue)
            self._declared.add(("queue", queue.name))

    async def task_broker(self) -> AioPikaBroker:
        """Broker kicker taskiq của process (khai queue mọi lane) — mở lười, dùng chung."""
        # defer: tránh vòng import với app.core.messaging.tasks (tasks.py import hub)
        from app.core.messaging.tasks import build_task_broker

        async with self._lock:
            if self._tasks is None:
                broker = build_task_broker(self.settings.RABBITMQ_URL, list(LANES.values()), worker=False)
                await broker.startup()
                self._tasks = broker
            return self._tasks

    async def publish(
        self,
        body: Any,
        *,
        queue: str = "",
        exchange: RabbitExchange | None = None,
        routing_key: str = "",
        persist: bool = False,
        message_id: str | None = None,
        mandatory: bool = True,
        headers: dict[str, str] | None = None,
    ) -> str:
        """Gửi 1 message mang cid của context (thiếu thì sinh mới). Trả cid đã dùng."""
        cid = get_cid() or new_cid()
        broker = await self.broker()
        if exchange is not None:
            await self.declare_exchange(exchange)
        await broker.publish(
            body,
            queue=queue,
            exchange=exchange,
            routing_key=routing_key,
            persist=persist,
            correlation_id=cid,
            message_id=message_id,
            mandatory=mandatory,
            headers=headers,
        )
        return cid

    async def ping(self) -> str:
        try:
            ok = await (await self.broker()).ping(timeout=2)
            return "ok" if ok else "error: ping"
        except Exception as exc:  # noqa: BLE001 — health phải trả kết quả, không được nổ
            logger.warning("ping RabbitMQ lỗi: %s", exc, extra={"loc": "bus0501"})
            return f"error: {type(exc).__name__}"

    async def close(self) -> None:
        if self._broker is not None:
            await self._broker.stop()
            self._broker = None
        if self._tasks is not None:
            await self._tasks.shutdown()
            self._tasks = None
        self._declared.clear()


_hub: MessagingHub | None = None


def set_hub(hub: MessagingHub | None) -> None:
    global _hub
    _hub = hub


def has_hub() -> bool:
    return _hub is not None


def get_hub() -> MessagingHub:
    if _hub is None:
        raise RuntimeError("Chưa có MessagingHub — chỉ có sau khi process khởi động messaging")
    return _hub
