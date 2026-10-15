"""Hạn mức chat: Lua 6 khoá (agent + tài khoản) — vượt khoá nào thì không cộng khoá nào; `scope` trong 6001."""

import uuid
from datetime import UTC, datetime

import pytest

from app.agent.runtime import limits
from app.agent.runtime.limits import Limits
from app.core.connections.registry import get_connections
from app.core.errors import AppException

TZ = "Asia/Ho_Chi_Minh"
AT = datetime(2026, 10, 12, 3, 30, 20, tzinfo=UTC)


@pytest.fixture
def redis(aenv):
    return get_connections().redis


async def check(redis, lim, agent, user, account=(0, 0, 0)):
    return await limits.check_and_count(
        redis, agent_id=agent, user_id=user, limits=lim, tz=TZ, exempt=False, account=account, now=AT
    )


async def values(redis, counted):
    return [int(await redis.rw.get(k) or 0) for k in counted_keys(counted)]


def counted_keys(counted):
    return counted.keys


async def test_account_cap_hit_is_scope_account_and_counts_nothing(redis):
    a, u = uuid.uuid4(), uuid.uuid4()
    lim = Limits(per_minute=5)
    ok = await check(redis, lim, a, u, account=(1, 0, 0))
    assert await values(redis, ok) == [1, 1, 1, 1, 1, 1]
    with pytest.raises(AppException) as exc:
        await check(redis, lim, a, u, account=(1, 0, 0))
    assert exc.value.code == 6001 and exc.value.status_code == 429
    assert exc.value.data["scope"] == "account" and exc.value.data["window"] == "minute"
    assert exc.value.data["limit"] == 1
    assert await values(redis, ok) == [1, 1, 1, 1, 1, 1]  # không khoá nào tăng, kể cả của agent


async def test_agent_cap_hit_is_scope_agent(redis):
    a, u = uuid.uuid4(), uuid.uuid4()
    lim = Limits(per_hour=1)
    ok = await check(redis, lim, a, u, account=(0, 10, 0))
    with pytest.raises(AppException) as exc:
        await check(redis, lim, a, u, account=(0, 10, 0))
    assert exc.value.data["scope"] == "agent" and exc.value.data["window"] == "hour"
    assert await values(redis, ok) == [1, 1, 1, 1, 1, 1]


async def test_account_day_window_reports_day(redis):
    a, u = uuid.uuid4(), uuid.uuid4()
    await check(redis, Limits(), a, u, account=(0, 0, 1))
    with pytest.raises(AppException) as exc:
        await check(redis, Limits(), a, u, account=(0, 0, 1))
    assert (exc.value.data["scope"], exc.value.data["window"]) == ("account", "day")


async def test_all_zero_returns_none_and_counts_nothing(redis):
    a, u = uuid.uuid4(), uuid.uuid4()
    assert await check(redis, Limits(), a, u, account=(0, 0, 0)) is None
    assert await redis.rw.keys(f"bw:lim:user:{u}:*") == []


async def test_refund_decrements_all_six_keys(redis):
    a, u = uuid.uuid4(), uuid.uuid4()
    counted = await check(redis, Limits(per_minute=3, per_hour=3, per_day=3), a, u, account=(3, 3, 3))
    assert len(counted.keys) == 6 and await values(redis, counted) == [1] * 6
    await limits.refund(redis, counted)
    assert await values(redis, counted) == [0] * 6


async def test_account_used_reads_account_windows_only(redis):
    a, u = uuid.uuid4(), uuid.uuid4()
    await check(redis, Limits(), a, u, account=(5, 5, 5))
    await check(redis, Limits(), a, u, account=(5, 5, 5))
    assert await limits.account_used(redis, u, TZ, AT) == (2, 2, 2)
