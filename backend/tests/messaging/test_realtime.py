"""Realtime ra: envelope v1, routing key theo đích, tên event `<miền>:<việc>`, lệnh rt:revoke; khai báo @on_ws."""

import uuid

import pytest

from app.core.cid import get_cid, set_cid
from app.core.messaging.realtime import (
    ENVELOPE_VERSION,
    all_ws,
    check_out_event,
    emit_all,
    emit_to_superadmins,
    emit_to_user,
    emit_to_users,
    envelope,
    on_ws,
    rt_revoke,
)
from tests.fixtures.fx import consumers as fxc

U1 = uuid.UUID("00000000-0000-4000-8000-000000000001")
U2 = uuid.UUID("00000000-0000-4000-8000-000000000002")


def test_envelope_v1():
    set_cid("envcid")
    env = envelope("x:y", {"a": 1})
    assert env["v"] == ENVELOPE_VERSION == 1 and env["event"] == "x:y" and env["cid"] == "envcid"
    assert env["ts"].endswith("Z")


async def test_emits_route_to_user_users_sup_all(recording_hub):
    await emit_to_user(U1, "fx:hello", {"n": 1})
    await emit_to_users([U1, U2, U1], "fx:hello", {"n": 2})
    await emit_to_superadmins("fx:hello", {"n": 3})
    await emit_all("fx:hello", {"n": 4})
    got = [(key, data["n"]) for key, _, data in recording_hub.events()]
    assert got == [(f"user.{U1}", 1), (f"user.{U1}", 2), (f"user.{U2}", 2), ("sup", 3), ("all", 4)]


async def test_envelope_and_amqp_share_one_cid(recording_hub):
    assert get_cid() is None
    await emit_to_user(U1, "fx:hello", {})
    [msg] = recording_hub.sent
    assert msg["body"]["cid"] == msg["cid"] == get_cid() and msg["cid"]


@pytest.mark.parametrize("bad", ["disconnect", "connect_error", "Fx:Hello", "fx.hello", "rt:revoke", "sys"])
async def test_bad_or_reserved_event_names_are_rejected(bad, recording_hub):
    with pytest.raises(ValueError, match="event"):
        await emit_to_user(U1, bad, {})
    with pytest.raises(ValueError):
        check_out_event(bad)
    assert recording_hub.sent == []


async def test_rt_revoke_reaches_every_instance(recording_hub):
    await rt_revoke(str(U1), before=100, until=1900)
    assert recording_hub.events() == [("all", "rt:revoke", {"sub": str(U1), "before": 100, "until": 1900})]


def test_on_ws_declaration_rules():
    with pytest.raises(ValueError):
        on_ws("Bad")
    with pytest.raises(ValueError, match="lane"):
        on_ws("fx.lost", lane="khong-co")
    with pytest.raises(TypeError, match="async"):
        on_ws("fx.sync_one")(lambda ctx, data: None)

    async def one_param(ctx): ...

    with pytest.raises(TypeError, match="2 tham số"):
        on_ws("fx.one_param")(one_param)
    with pytest.raises(ValueError, match="trùng"):
        on_ws("fx.echo")(fxc.ws_echo)
    spec = next(w for w in all_ws() if w.event == "fx.echo")
    assert (spec.permission, spec.queue, spec.lane) == ("fx.read", "bw.rt.in.fx.echo", "default")
    assert spec.model is fxc.EchoIn
