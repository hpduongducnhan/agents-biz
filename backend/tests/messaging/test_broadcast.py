"""Broadcast: mọi process nhận (kèm cid), handler hỏng không chặn handler khác, topic sai dạng bị từ chối."""

import pytest

from app.core.cid import set_cid
from app.core.messaging.broadcast import BroadcastListener, broadcast, broadcast_handlers, on_broadcast
from tests.conftest import until
from tests.fixtures.fx import consumers as fx


def test_topic_rules():
    with pytest.raises(ValueError, match="<miền>.<việc>"):
        on_broadcast("CacheChanged")
    with pytest.raises(TypeError, match="async"):
        on_broadcast("fx.sync_one")(lambda data: None)
    assert [f.__name__ for f in broadcast_handlers()["fx.cache_changed"]] == ["on_cache_changed", "broken_listener"]


async def test_broadcast_rejects_bad_topic():
    with pytest.raises(ValueError):
        await broadcast("khongcocham")


@pytest.fixture
async def listeners(messaging_env):
    fx.BCAST.clear()
    started = [BroadcastListener(messaging_env, proc) for proc in ("api", "work")]
    for listener in started:
        await listener.start()
    yield started
    for listener in started:
        await listener.stop()


@pytest.mark.integration
async def test_every_process_receives_broadcast_with_cid(listeners, bw_log):
    set_cid("bcastcid1")
    await broadcast("fx.cache_changed", {"id": 1})
    assert await until(lambda: len(fx.BCAST) == 2)
    assert fx.BCAST == [({"id": 1}, "bcastcid1")] * 2
    assert await until(lambda: [line["loc"] for line in bw_log()].count("bus0401") == 2)


@pytest.mark.integration
async def test_each_process_has_its_own_queue(listeners):
    names = {listener.queue_name for listener in listeners}
    assert len(names) == 2 and all(n.startswith("bw.sys.bcast.") for n in names)
