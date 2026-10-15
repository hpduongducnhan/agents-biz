"""MessagingHub: kicker taskiq mở lười + dùng chung; đóng hub đóng cả kicker; publish mang cid của context."""

import asyncio

import aio_pika
import pytest

from app.core.cid import set_cid
from app.core.messaging.hub import get_hub
from app.core.messaging.names import RT_OUT_EXCHANGE, rt_out_exchange
from tests.conftest import get_one

pytestmark = pytest.mark.integration


async def test_task_broker_is_lazy_and_cached(messaging_env):
    hub = get_hub()
    a, b = await asyncio.gather(hub.task_broker(), hub.task_broker())
    assert a is b


async def test_close_shuts_task_broker(messaging_env):
    hub = get_hub()
    first = await hub.task_broker()
    await hub.close()
    assert await hub.task_broker() is not first


async def test_publish_to_exchange_carries_cid(messaging_env):
    hub = get_hub()
    conn = await aio_pika.connect(messaging_env.RABBITMQ_URL)
    try:
        ch = await conn.channel()
        await hub.declare_exchange(rt_out_exchange())
        q = await ch.declare_queue(exclusive=True)
        await q.bind(RT_OUT_EXCHANGE, routing_key="user.u1")
        set_cid("hubcid1")
        used = await hub.publish({"x": 1}, exchange=rt_out_exchange(), routing_key="user.u1")
        msg = await get_one(q)
    finally:
        await conn.close()
    assert used == "hubcid1" and msg.correlation_id == "hubcid1" and b'"x"' in msg.body
