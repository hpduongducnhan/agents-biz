"""Runtime đầy đủ: nhịp tim đi đường thật scheduler (cron taskiq, khoá leader) → worker → consumer; exchange realtime
khai cùng tham số service Node; deploy chồng lấn không kick cron hai lần; consume lọc theo lane."""

import asyncio

import aio_pika
import pytest

from app.core.connections.registry import close_connections, init_connections
from app.core.messaging import names
from app.core.messaging.realtime import all_ws
from app.core.messaging.runtime import run_consume, run_schedule, run_work, start_messaging, stop_messaging
from app.core.messaging.streams import all_subscribers
from app.core.settings import use_settings
from app.domains import load_domains
from app.system import heartbeat
from tests.conftest import reset_rabbit, reset_test_redis
from tests.fixtures.fx import tasks as fxt

pytestmark = pytest.mark.integration
QUEUES = [
    "bw.system.ping",
    "bw.system.ping.dlq",
    names.TQ_DEFAULT_QUEUE,
    "bw.tq.agent-run",
    names.RT_UNROUTED_QUEUE,
    "bw.rt.in.system.ping",
]


@pytest.fixture
async def env(test_settings):
    load_domains()
    s = test_settings.model_copy(update={"MONGO_ENABLED": False})
    use_settings(s)
    reset_test_redis(s)
    await reset_rabbit(
        s, queues=QUEUES, exchanges=[names.RT_IN_EXCHANGE, names.RT_OUT_EXCHANGE, names.RT_UNROUTED_EXCHANGE]
    )
    conns = await init_connections("api", s)
    await start_messaging(s, "test")
    yield s, conns
    await stop_messaging()
    await close_connections()
    use_settings(None)


async def test_pipeline_heartbeats_flow_end_to_end(env):
    s, conns = env
    stop = asyncio.Event()
    jobs = [
        asyncio.create_task(run_consume(s, conns, stop=stop)),
        asyncio.create_task(run_work(s, conns, 4, stop=stop)),
        asyncio.create_task(run_schedule(s, conns, stop=stop)),
    ]
    try:
        beats: dict = {}
        for _ in range(100):
            beats = await heartbeat.read_all(conns.redis.rw, s.HEARTBEAT_INTERVAL)
            if all(v["ok"] for v in beats.values()):
                break
            await asyncio.sleep(0.1)
        assert all(v["ok"] for v in beats.values()), beats

        conn = await aio_pika.connect(s.RABBITMQ_URL)
        try:
            ch = await conn.channel()
            # Khai lại y hệt service realtime (Node) — khác tham số thì RabbitMQ đóng kênh (PRECONDITION_FAILED).
            await ch.declare_exchange(
                names.RT_IN_EXCHANGE,
                aio_pika.ExchangeType.TOPIC,
                durable=True,
                arguments={"alternate-exchange": names.RT_UNROUTED_EXCHANGE},
            )
            await ch.declare_exchange(names.RT_OUT_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True)
        finally:
            await conn.close()
    finally:
        stop.set()
        await asyncio.gather(*jobs)


async def test_two_schedulers_kick_every_task_once_per_interval(env):
    s, conns = env
    fxt.SEEN.clear()
    stop = asyncio.Event()
    jobs = [
        asyncio.create_task(run_work(s, conns, 4, stop=stop)),
        asyncio.create_task(run_schedule(s, conns, stop=stop)),
        asyncio.create_task(run_schedule(s, conns, stop=stop)),  # deploy chồng lấn
    ]
    try:
        await asyncio.sleep(4.0)
    finally:
        stop.set()
        await asyncio.gather(*jobs)
    ticks = [cid for name, _, cid in fxt.SEEN if name == "tick"]
    assert 2 <= len(ticks) <= 5, ticks  # một leader: ~1 lần / giây; hai bản cùng kick → ≥ 7
    assert len(set(ticks)) == len(ticks)  # mỗi lần cron một cid mới


async def test_consume_mounts_only_requested_lanes(env, bw_log):
    s, conns = env
    expected = len([x for x in all_subscribers() if x.lane == "agent-run"]) + len(
        [w for w in all_ws() if w.lane == "agent-run"]
    )
    stop = asyncio.Event()
    job = asyncio.create_task(run_consume(s, conns, stop=stop, lanes=["agent-run"]))
    try:
        for _ in range(50):
            if any(line["loc"] == "bus0001" for line in bw_log()):
                break
            await asyncio.sleep(0.1)
    finally:
        stop.set()
        await job
    line = next(line for line in bw_log() if line["loc"] == "bus0001")
    assert f"handler={expected}" in line["msg"]
