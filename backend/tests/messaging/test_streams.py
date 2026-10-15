"""Subscriber / publish: queue `bw.<miền>.<việc>`, giữ cid, message độc → DLQ + issue, body sai → reject + log."""

import aio_pika
import pytest
from faststream.rabbit import RabbitBroker

from app.core.cid import set_cid
from app.core.messaging.consumer import mount_subscriber
from app.core.messaging.streams import all_subscribers, publish, queue_name, subscriber
from tests.conftest import get_one, reset_rabbit, until
from tests.fixtures.fx import consumers as fx

FX_EVENTS = ("fx.note_created", "fx.poison")


def test_queue_name_follows_event():
    assert queue_name("fx.note_created") == "bw.fx.note_created"


def test_declaration_rules():
    with pytest.raises(ValueError, match="trùng"):
        subscriber("fx.note_created")(fx.on_note_created)
    with pytest.raises(ValueError, match="<miền>.<việc>"):
        subscriber("NoteCreated")
    with pytest.raises(ValueError, match="lane"):
        subscriber("fx.other", lane="khong-co")
    with pytest.raises(TypeError, match="async"):
        subscriber("fx.sync_one")(lambda body: None)


async def test_publish_rejects_bad_event_name():
    with pytest.raises(ValueError):
        await publish("khongcocham", {})


async def _start(settings, events):
    broker = RabbitBroker(settings.RABBITMQ_URL, logger=None)
    extras = []
    for spec in all_subscribers():
        if spec.event in events:
            extras += mount_subscriber(broker, spec)
    await broker.start()
    for queue in extras:
        await broker.declare_queue(queue)
    return broker


@pytest.fixture
async def consumer(messaging_env):
    await reset_rabbit(messaging_env, queues=[q for e in FX_EVENTS for q in (queue_name(e), f"{queue_name(e)}.dlq")])
    fx.SEEN.clear()
    broker = await _start(messaging_env, FX_EVENTS)
    yield broker
    await broker.stop()


@pytest.mark.integration
async def test_publish_then_consume_keeps_cid(consumer):
    set_cid("streamcid1")
    assert await publish("fx.note_created", {"id": 7}) == "streamcid1"
    assert await until(lambda: fx.SEEN)
    assert fx.SEEN == [(7, "streamcid1")]


@pytest.mark.integration
async def test_poison_message_goes_to_dlq_and_issue_is_captured(consumer, messaging_env, bw_log, memory_sinks):
    await publish("fx.poison", {"bad": True})
    await publish("fx.note_created", {"id": 10})
    assert await until(lambda: fx.SEEN and memory_sinks.issues.items)
    assert any(line["loc"] == "bus0500" for line in bw_log())
    issue = memory_sinks.issues.items[0]
    assert issue["source"] == "consumer" and issue["context"] == {"subscriber": "fx.poison"}
    conn = await aio_pika.connect(messaging_env.RABBITMQ_URL)
    try:
        dlq = await (await conn.channel()).declare_queue("bw.fx.poison.dlq", passive=True)
        msg = await get_one(dlq)
    finally:
        await conn.close()
    assert b"bad" in msg.body


@pytest.mark.integration
async def test_invalid_body_is_rejected_and_logged(consumer, bw_log):
    await publish("fx.note_created", {"id": "khong-phai-so"})
    assert await until(lambda: any(line["loc"] == "bus0502" for line in bw_log()))
    assert fx.SEEN == []


@pytest.mark.integration
async def test_publish_before_consumer_starts_is_not_lost(messaging_env):
    await reset_rabbit(messaging_env, queues=["bw.fx.note_created", "bw.fx.note_created.dlq"])
    fx.SEEN.clear()
    await publish("fx.note_created", {"id": 42})
    broker = await _start(messaging_env, ("fx.note_created",))
    try:
        assert await until(lambda: fx.SEEN)
    finally:
        await broker.stop()
    assert fx.SEEN[0][0] == 42
