"""Event client `bw.rt.in` → @on_ws: claims → Principal; kiểm theo thứ tự cũ (1009) → khoá (2103) → quyền (1005) →
dữ liệu (1002); handler lỗi → 1000 + issue; event không ai nhận → log; realtime / broadcast không bị trả về."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import aio_pika
import pytest
from faststream.rabbit import RabbitBroker

from app.core.connections.registry import get_connections
from app.core.messaging.broadcast import broadcast
from app.core.messaging.consumer import mount_unrouted, mount_ws
from app.core.messaging.hub import get_hub
from app.core.messaging.names import RT_IN_EXCHANGE, RT_OUT_EXCHANGE, rt_in_exchange, rt_out_exchange
from app.core.messaging.realtime import all_ws, emit_to_user
from app.core.security.principal import disabled_key
from tests.conftest import get_one, reset_rabbit, until
from tests.fixtures.fx import consumers as fx

pytestmark = pytest.mark.integration
U1 = uuid.UUID("00000000-0000-4000-8000-000000000001")
READER = {"sub": str(U1), "perms": ["fx.read"], "sup": False}
NOBODY = {"sub": str(U1), "perms": [], "sup": False}


@pytest.fixture
async def rt(messaging_env):
    await reset_rabbit(messaging_env, queues=["bw.rt.in.fx.echo", "bw.rt.in.fx.crash", "bw.rt.in.unrouted"])
    fx.WS.clear()
    hub = get_hub()
    await hub.declare_exchange(rt_out_exchange())
    await hub.declare_exchange(rt_in_exchange())
    conn = await aio_pika.connect(messaging_env.RABBITMQ_URL)
    ch = await conn.channel()
    out = await ch.declare_queue(exclusive=True)
    for key in (f"user.{U1}", "all"):
        await out.bind(RT_OUT_EXCHANGE, routing_key=key)
    broker = RabbitBroker(messaging_env.RABBITMQ_URL, logger=None)
    for spec in all_ws():
        if spec.event.startswith("fx."):
            mount_ws(broker, spec)
    mount_unrouted(broker)
    await broker.start()

    async def send(event, data, claims, *, cid="wscid1", ts=None):
        ts = ts or datetime.now(UTC).isoformat().replace("+00:00", "Z")
        body = {"v": 1, "event": event, "data": data, "claims": claims, "sid": "s1", "cid": cid, "ts": ts}
        exchange = await ch.get_exchange(RT_IN_EXCHANGE)
        await exchange.publish(aio_pika.Message(json.dumps(body).encode(), correlation_id=cid), routing_key=event)

    async def received():
        msg = await get_one(out)
        return msg.routing_key, json.loads(msg.body), msg.correlation_id

    yield send, received, out
    await broker.stop()
    await conn.close()


async def test_client_event_reaches_handler_with_claims_principal(rt):
    send, received, _ = rt
    await send("fx.echo", {"text": "chào"}, READER)
    key, body, cid = await received()
    assert key == f"user.{U1}" and body["event"] == "fx:echo" and body["data"] == {"text": "chào"}
    assert cid == "wscid1" and fx.WS == [(str(U1), "s1")]


async def test_superadmin_claims_skip_permission(rt):
    send, received, _ = rt
    await send("fx.echo", {"text": "sa"}, {"sub": str(U1), "perms": [], "sup": True})
    _, body, _ = await received()
    assert body["event"] == "fx:echo"


async def test_missing_permission_replies_1005(rt):
    send, received, _ = rt
    await send("fx.echo", {"text": "x"}, NOBODY)
    _, body, _ = await received()
    assert body["event"] == "sys:error" and body["data"] == {"code": 1005, "cid": "wscid1"} and fx.WS == []


async def test_bad_data_replies_1002(rt):
    send, received, _ = rt
    await send("fx.echo", {"text": 123}, READER)
    _, body, _ = await received()
    assert body["data"]["code"] == 1002 and fx.WS == []


async def test_disabled_account_replies_2103(rt):
    send, received, _ = rt
    await get_connections().redis.rw.set(disabled_key(U1), "1", ex=60)
    await send("fx.echo", {"text": "x"}, READER)
    _, body, _ = await received()
    assert body["event"] == "sys:error" and body["data"]["code"] == 2103 and fx.WS == []


@pytest.mark.parametrize(
    "ts",
    [
        (datetime.now(UTC) - timedelta(minutes=10)).isoformat(),  # chờ trong queue quá lâu
        "2026-01-01T00:00:00",  # thiếu múi giờ
        "khong-phai-ngay",
    ],
)
async def test_stale_or_undated_event_is_not_run(rt, ts):
    send, received, _ = rt
    await send("fx.echo", {"text": "x"}, READER, ts=ts)
    _, body, _ = await received()
    assert body["event"] == "sys:error" and body["data"]["code"] == 1009 and fx.WS == []


async def test_checks_run_in_contract_order(rt):
    send, received, _ = rt
    await get_connections().redis.rw.set(disabled_key(U1), "1", ex=60)
    old = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    await send("fx.echo", {"text": 1}, NOBODY, ts=old)  # cũ + bị khoá + thiếu quyền + sai dữ liệu
    _, body, _ = await received()
    assert body["data"]["code"] == 1009
    await send("fx.echo", {"text": 1}, NOBODY)  # bị khoá + thiếu quyền + sai dữ liệu
    _, body, _ = await received()
    assert body["data"]["code"] == 2103


async def test_handler_crash_replies_1000_and_captures_issue(rt, memory_sinks, bw_log):
    send, received, _ = rt
    await send("fx.crash", {}, READER)
    _, body, _ = await received()
    assert body["data"]["code"] == 1000
    [issue] = memory_sinks.issues.items
    assert issue["source"] == "ws" and issue["context"]["event"] == "fx.crash"
    assert any(line["loc"] == "ws0500" for line in bw_log())


async def test_bad_claims_are_dropped_without_reply(rt, bw_log):
    send, _, out = rt
    await send("fx.echo", {"text": "x"}, {"sub": "khong-phai-uuid"})
    assert await until(lambda: any(line["loc"] == "ws0103" for line in bw_log()))
    assert await out.get(fail=False) is None


async def test_unrouted_event_is_logged(rt, bw_log):
    send, _, _ = rt
    await send("ghost.event", {}, READER)
    assert await until(lambda: any(line["loc"] == "ws0101" for line in bw_log()))


async def test_outbound_without_listener_is_not_returned(rt):
    returned: list[str] = []
    broker = await get_hub().broker()
    channel = await broker.config.channel_manager.get_channel()
    channel.return_callbacks.add(lambda _sender, message: returned.append(message.routing_key))
    await emit_to_user("khong_ai_nghe", "core:probe", {})
    await broadcast("core.khong_ai_nghe", {})
    assert returned == []
    # đối chứng: publish mandatory tới exchange không có binding thì bị trả về → spy thấy được
    await get_hub().publish({"x": 1}, exchange=rt_out_exchange(), routing_key="user.doi_chung", mandatory=True)
    assert await until(lambda: returned == ["user.doi_chung"])
