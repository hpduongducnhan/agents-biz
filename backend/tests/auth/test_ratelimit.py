"""Rate limit cửa sổ cố định trên Redis: đếm theo khoá, 429 kèm retry_after, hết cửa sổ thì mở lại, không bao giờ
để lại khoá thiếu TTL (khoá người dùng vĩnh viễn)."""

import asyncio

import pytest

from app.auth.ratelimit import hit_rate_limit
from app.core.connections.redis import Redis
from app.core.errors import AppException
from tests.conftest import reset_test_redis

pytestmark = pytest.mark.integration
KEY = ("auth", "login", "1.2.3.4", "a@x.io")


@pytest.fixture
async def redis(test_settings):
    reset_test_redis(test_settings)
    client = Redis(test_settings)
    yield client.rw
    await client.close()


async def test_limit_per_key_with_retry_after(redis):
    for _ in range(3):
        await hit_rate_limit(redis, KEY, 3)
    with pytest.raises(AppException) as err:
        await hit_rate_limit(redis, KEY, 3)
    assert (err.value.code, err.value.status_code) == (1007, 429)
    assert 1 <= err.value.data["retry_after_sec"] <= 60
    assert 0 < await redis.ttl("bw:rl:auth:login:1.2.3.4:a@x.io") <= 60
    await hit_rate_limit(redis, ("auth", "login", "1.2.3.4", "b@x.io"), 3)  # khoá khác không bị ảnh hưởng


async def test_window_resets(redis):
    await hit_rate_limit(redis, ("w",), 1, window=1)
    with pytest.raises(AppException):
        await hit_rate_limit(redis, ("w",), 1, window=1)
    await asyncio.sleep(1.2)
    await hit_rate_limit(redis, ("w",), 1, window=1)


async def test_key_left_without_ttl_gets_one(redis):
    await redis.set("bw:rl:stuck", 5)  # khoá cũ không TTL (vd process chết giữa INCR và EXPIRE)
    with pytest.raises(AppException):
        await hit_rate_limit(redis, ("stuck",), 3)
    assert 0 < await redis.ttl("bw:rl:stuck") <= 60
