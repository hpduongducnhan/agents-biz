"""Dựng process theo role: publish (mọi process) · consume (FastStream) · work (taskiq) · schedule (cron, chỉ bản giữ
khoá leader). Hàm `run_*` chạy tới khi `stop` được set."""

from __future__ import annotations

import asyncio
import contextlib

from faststream.rabbit import RabbitBroker, RabbitQueue
from taskiq import TaskiqScheduler
from taskiq.api import run_receiver_task, run_scheduler_task

from app.core.connections.registry import Connections
from app.core.logging import get_logger
from app.core.messaging.broadcast import BroadcastListener
from app.core.messaging.consumer import mount_subscriber, mount_unrouted, mount_ws
from app.core.messaging.hub import MessagingHub, get_hub, has_hub, set_hub
from app.core.messaging.lanes import LANES
from app.core.messaging.leader import LeaderLock
from app.core.messaging.names import rt_in_exchange, rt_out_exchange, rt_unrouted_exchange
from app.core.messaging.realtime import all_ws
from app.core.messaging.streams import all_subscribers
from app.core.messaging.tasks import TaskScheduleSource, all_tasks, build_task_broker, register_tasks
from app.core.settings import Settings
from app.system import heartbeat

logger = get_logger(__name__)
_listener: BroadcastListener | None = None


async def start_messaging(settings: Settings, proc: str) -> MessagingHub:
    """Hub publish + listener broadcast của process (mọi role trừ migrate)."""
    global _listener
    hub = MessagingHub(settings)
    set_hub(hub)
    _listener = BroadcastListener(settings, proc)
    await _listener.start()
    logger.info("messaging sẵn sàng proc=%s", proc, extra={"loc": "bus0002"})
    return hub


async def stop_messaging() -> None:
    global _listener
    if _listener is not None:
        await _listener.stop()
        _listener = None
    if has_hub():
        hub = get_hub()
        set_hub(None)
        await hub.close()


async def _wait(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), seconds)


def _want(lanes: list[str] | None, lane: str) -> bool:
    return lanes is None or lane in lanes


async def run_consume(
    settings: Settings, conns: Connections, *, stop: asyncio.Event, lanes: list[str] | None = None
) -> None:
    broker = RabbitBroker(settings.RABBITMQ_URL, logger=None)
    extras: list[RabbitQueue] = []
    count = 0
    for spec in all_subscribers():
        if _want(lanes, spec.lane):
            extras += mount_subscriber(broker, spec)
            count += 1
    for ws in all_ws():
        if _want(lanes, ws.lane):
            mount_ws(broker, ws)
            count += 1
    if _want(lanes, "default"):
        mount_unrouted(broker)
    await broker.start()
    for queue in extras:
        await broker.declare_queue(queue)
    # Khai CÙNG tham số với service realtime (realtime/src/rabbit.ts) — lệch là RabbitMQ từ chối.
    for exchange in (rt_out_exchange(), rt_in_exchange(), rt_unrouted_exchange()):
        await broker.declare_exchange(exchange)
    logger.info("consume sẵn sàng lane=%s handler=%d", lanes or "mọi lane", count, extra={"loc": "bus0001"})
    try:
        await stop.wait()
    finally:
        await broker.stop()


async def run_work(
    settings: Settings,
    conns: Connections,
    concurrency: int = 10,
    *,
    stop: asyncio.Event,
    lanes: list[str] | None = None,
) -> None:
    queues = [LANES[lane] for lane in (lanes or list(LANES))]
    broker = build_task_broker(settings.RABBITMQ_URL, queues, worker=True)
    register_tasks(broker, all_tasks())
    await broker.startup()
    receiver = asyncio.create_task(run_receiver_task(broker, max_async_tasks=concurrency))
    logger.info("work sẵn sàng queue=%s concurrency=%d", queues, concurrency, extra={"loc": "tq0001"})
    try:
        await stop.wait()
    finally:
        receiver.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await receiver
        await broker.shutdown()


async def run_schedule(settings: Settings, conns: Connections, *, stop: asyncio.Event) -> None:
    """Chờ khoá leader → chạy cron (task `cron` / `every`) + ghi nhịp tim `schedule`; mất khoá → dừng cron và quay lại
    chờ (deploy chồng lấn không kick cron hai lần)."""
    lock = LeaderLock(conns.redis.rw, key=settings.SCHEDULER_LEADER_KEY, ttl=settings.SCHEDULER_LEADER_TTL)
    beat = max(settings.SCHEDULER_LEADER_TTL / 3, 0.2)
    while not stop.is_set():
        if not await lock.acquire():
            await _wait(stop, beat)
            continue
        logger.info("giành được khoá leader scheduler", extra={"loc": "tq0002"})
        scheduler = TaskiqScheduler(await get_hub().task_broker(), [TaskScheduleSource(settings)])
        job = asyncio.create_task(run_scheduler_task(scheduler))
        try:
            while not stop.is_set():
                try:
                    await heartbeat.beat(conns.redis.rw, "schedule")
                except Exception as exc:  # noqa: BLE001 — vòng leader phải sống; lần sau ghi lại
                    logger.warning("ghi nhịp tim scheduler lỗi: %s", exc, extra={"loc": "tq0503"})
                await _wait(stop, beat)
                if not stop.is_set() and not await lock.renew():
                    logger.warning("mất khoá leader scheduler — dừng cron", extra={"loc": "tq0501"})
                    break
        finally:
            job.cancel()
            await asyncio.gather(job, return_exceptions=True)
            await lock.release()
