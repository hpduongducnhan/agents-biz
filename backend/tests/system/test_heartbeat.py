"""Nhịp tim process nền: key `bw:hb:<role>`, tươi khi tuổi ≤ 3 × interval."""

from datetime import UTC, datetime, timedelta

from app.system import heartbeat


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}
        self.ttl: dict[str, int] = {}

    async def set(self, key, value, ex=None):
        self.data[key], self.ttl[key] = value, ex

    async def get(self, key):
        return self.data.get(key)


async def test_beat_writes_prefixed_key_with_ttl():
    r = FakeRedis()
    now = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)
    await heartbeat.beat(r, "work", now=now)
    assert r.data == {"bw:hb:work": now.isoformat()}
    assert r.ttl["bw:hb:work"] == heartbeat.TTL_SECONDS


async def test_read_all_reports_age_and_freshness():
    r = FakeRedis()
    now = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)
    await heartbeat.beat(r, "consume", now=now - timedelta(seconds=10))
    await heartbeat.beat(r, "work", now=now - timedelta(seconds=100))
    out = await heartbeat.read_all(r, interval=15, now=now)
    assert out["consume"] == {"last": (now - timedelta(seconds=10)).isoformat(), "age_s": 10.0, "ok": True}
    assert out["work"]["ok"] is False and out["work"]["age_s"] == 100.0
    assert out["schedule"] == {"last": None, "age_s": None, "ok": False}
    assert list(out) == list(heartbeat.ROLES)
