"""Nhịp tim viết bằng decorator: task `system.ping` (worker) → subscriber `system.ping` (consumer);
`@on_ws("system.ping")` trả `system:pong` cho người gửi."""

import uuid
from types import SimpleNamespace

from app.core.messaging.realtime import WsContext
from app.core.security.principal import Principal
from app.system import consumers as sysc
from app.system import tasks as syst
from tests.system.test_heartbeat import FakeRedis

U1 = uuid.UUID("00000000-0000-4000-8000-000000000001")


def _conns(redis):
    return SimpleNamespace(redis=SimpleNamespace(rw=redis))


async def test_ping_task_beats_work_and_forwards_to_consumer(monkeypatch, recording_hub):
    r = FakeRedis()
    monkeypatch.setattr(syst, "get_connections", lambda: _conns(r))
    await syst.ping()
    assert "bw:hb:work" in r.data
    [msg] = recording_hub.sent
    assert msg["queue"] == "bw.system.ping" and msg["body"] == {"from": "work"}


async def test_ping_subscriber_beats_consume(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(sysc, "get_connections", lambda: _conns(r))
    await sysc.on_ping({"from": "work"})
    assert "bw:hb:consume" in r.data


async def test_ws_ping_replies_pong_to_sender(recording_hub):
    ctx = WsContext(principal=Principal(user_id=U1), sid="s1", cid="c1", event="system.ping")
    await sysc.ws_ping(ctx, sysc.PingIn(nonce="abc"))
    [(key, event, data)] = recording_hub.events()
    assert key == f"user.{U1}" and event == "system:pong" and data["nonce"] == "abc" and data["ts"].endswith("Z")
