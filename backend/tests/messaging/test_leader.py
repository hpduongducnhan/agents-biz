"""Khoá leader scheduler: chỉ một bản giữ; nhả / hết hạn → bản khác giành (deploy chồng lấn trên Coolify)."""

import asyncio

import pytest
import redis.asyncio as aioredis

from app.core.messaging.leader import LeaderLock
from tests.conftest import reset_test_redis

pytestmark = pytest.mark.integration


@pytest.fixture
async def r(test_settings):
    reset_test_redis(test_settings)
    client = aioredis.Redis.from_url(test_settings.REDIS_RW_URL, decode_responses=True)
    yield client
    await client.aclose()


async def test_only_one_holder_and_handover_on_release(r):
    a, b = LeaderLock(r, key="bw:test:leader", ttl=5), LeaderLock(r, key="bw:test:leader", ttl=5)
    assert await a.acquire() is True
    assert await b.acquire() is False
    assert await a.renew() is True and await b.renew() is False
    await b.release()  # không phải chủ → không xoá được khoá của a
    assert await r.get("bw:test:leader") == a.token
    await a.release()
    assert await b.acquire() is True


async def test_lock_expires_when_holder_dies(r):
    a, b = LeaderLock(r, key="bw:test:leader", ttl=1), LeaderLock(r, key="bw:test:leader", ttl=1)
    assert await a.acquire()
    await asyncio.sleep(1.2)
    assert await b.acquire()
    assert await a.renew() is False
