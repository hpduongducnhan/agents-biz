"""RunEmitter: gom chữ 50 ms, `seq` liên tục, bộ đệm Redis (TTL, trần), bù `after_seq`, realtime best-effort."""

import asyncio
import uuid

from app.agent.trace import events
from app.agent.trace.events import RunEmitter, buffered, redact
from app.core.connections.registry import get_connections


def make(window: float = 0.05, **kw) -> RunEmitter:
    return RunEmitter(get_connections().redis, uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), window=window, **kw)


async def test_emitter_batches_tokens_50ms_and_buffers_with_seq(aenv, rt):
    em = make(window=0.05)
    await em.start(agent_id="a")
    for piece in ("xin ", "chào ", "bạn"):
        await em.token(piece)  # trong cùng cửa sổ → chưa phát (lần đầu phát ngay vì _last = 0)
    await asyncio.sleep(0.07)
    await em.token("!")
    await em.end(message_id="m1", usage={"input": 3})
    seen = [(e, d) for _, e, d in rt.events() if d.get("run_id") == em.run_id]
    assert [e for e, _ in seen] == ["agent:start", "agent:token", "agent:token", "agent:end"]
    deltas = [d["delta"] for e, d in seen if e == "agent:token"]
    assert deltas == ["xin ", "chào bạn!"]  # token đầu phát ngay; hai mảnh sau gom lại tới khi hết cửa sổ
    assert [d["seq"] for _, d in seen] == [1, 2, 3, 4] and em.seq == 4 and em.text == "xin chào bạn!"
    stored = await buffered(get_connections().redis, em.run_id)
    assert [e["data"]["seq"] for e in stored] == [1, 2, 3, 4]
    assert [e["data"]["seq"] for e in await buffered(get_connections().redis, em.run_id, 3)] == [4]
    ttl = await get_connections().redis.rw.ttl(events.buffer_key(em.run_id))
    assert 0 < ttl <= events.BUFFER_TTL
    assert stored[-1]["data"]["usage"] == {"input": 3} and stored[-1]["data"]["status"] == "done"


async def test_flush_empty_and_empty_delta_emit_nothing(aenv, rt):
    em = make()
    await em.token("")
    await em.flush()
    assert rt.events() == [] and em.seq == 0
    assert await buffered(get_connections().redis, em.run_id) is None


async def test_buffer_cap_drops_tokens_keeps_steps(aenv, rt, monkeypatch):
    monkeypatch.setattr(events, "BUFFER_CAP", 3)
    em = make(window=0)
    for i in range(6):
        await em.token(f"t{i}")
    await em.step(call_id="c", name="tool", status="running")
    await em.approval(approval_id="a", call_id="c")
    await em.error(6011, "lỗi")
    stored = [e["event"] for e in await buffered(get_connections().redis, em.run_id)]
    assert stored.count("agent:token") == 3 and stored[-3:] == ["agent:step", "agent:approval", "agent:error"]
    live = [e for _, e, d in rt.events() if d["run_id"] == em.run_id]
    assert live.count("agent:token") == 6  # realtime vẫn nhận đủ; chỉ bộ đệm bị cắt


async def test_resume_emitter_continues_seq(aenv, rt):
    first = make()
    await first.start(agent_id="a")
    await first.step(call_id="c", name="t", status="running")
    again = RunEmitter(get_connections().redis, first.run_id, first.session_id, first.user_id, start_seq=first.seq)
    await again.decided(approval_id="x", status="approved")
    await again.end(message_id=None, usage={}, status="cancelled")
    seqs = [e["data"]["seq"] for e in await buffered(get_connections().redis, first.run_id)]
    assert seqs == [1, 2, 3, 4]


async def test_emit_failure_is_swallowed_and_logged(aenv, bw_log, monkeypatch):
    class Broken:
        class rw:  # noqa: N801
            @staticmethod
            async def rpush(*_a):
                raise ConnectionError("redis down")

    em = RunEmitter(Broken, uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    await em.start(agent_id="a")
    assert em.seq == 1 and any(r.get("loc") == "agt0201" for r in bw_log())


def test_redact_masks_secret_keys_recursively():
    out = redact({"amount": 5, "secret": "x", "nested": [{"password": "p", "ok": 1}], "api_key": "k"})
    assert out["amount"] == 5 and out["secret"] == "***" and out["api_key"] == "***"
    assert out["nested"] == [{"password": "***", "ok": 1}]
    assert redact("plain") == "plain"
