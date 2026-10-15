"""Hạn mức theo user: cửa sổ phút / giờ / ngày (Lua), hoàn lại, trần token / ngày, ghi đè theo user."""

import uuid
from datetime import UTC, datetime

import pytest

from app.agent.config.models import AgentLimit, AgentUserLimit
from app.agent.runtime import limits
from app.agent.runtime.limits import Limits
from app.core.connections.registry import get_connections
from app.core.errors import AppException
from tests.agent.helpers import send, set_run, setup

TZ = "Asia/Ho_Chi_Minh"
AT = datetime(2026, 10, 12, 3, 30, 20, tzinfo=UTC)  # 10:30:20 VN


@pytest.fixture
def redis(aenv):
    return get_connections().redis


async def check(redis, lim: Limits, agent, user, *, now=AT, exempt=False):
    return await limits.check_and_count(redis, agent_id=agent, user_id=user, limits=lim, tz=TZ, exempt=exempt, now=now)


async def blocked(redis, lim, agent, user, **kw) -> AppException:
    with pytest.raises(AppException) as exc:
        await check(redis, lim, agent, user, **kw)
    return exc.value


async def test_rate_limit_windows_and_refund(redis):
    a, u = uuid.uuid4(), uuid.uuid4()
    lim = Limits(per_minute=2)
    c1 = await check(redis, lim, a, u)
    await check(redis, lim, a, u)
    err = await blocked(redis, lim, a, u)
    assert err.code == 6001 and err.status_code == 429
    assert err.data == {
        "window": "minute",
        "limit": 2,
        "scope": "agent",
        "retry_after_sec": 40,
    }  # 20 giây qua phút → còn 40
    await limits.refund(redis, c1)  # insert lỗi → trả lại lượt
    await check(redis, lim, a, u)
    await limits.refund(redis, None)  # không đếm thì không có gì để trả
    later = datetime(2026, 10, 12, 3, 31, 0, tzinfo=UTC)  # phút kế tiếp: bộ đếm mới
    await check(redis, lim, a, u, now=later)


async def test_hour_and_day_windows_report_their_own_retry_after(redis):
    a, u = uuid.uuid4(), uuid.uuid4()
    hour = Limits(per_hour=1)
    await check(redis, hour, a, u)
    err = await blocked(redis, hour, a, u, now=datetime(2026, 10, 12, 3, 40, 0, tzinfo=UTC))
    assert err.data["window"] == "hour" and err.data["limit"] == 1 and err.data["retry_after_sec"] == 1200
    day = Limits(per_day=1)
    await check(redis, day, a, u, now=datetime(2026, 10, 13, 5, 0, 0, tzinfo=UTC))
    err = await blocked(redis, day, a, u, now=datetime(2026, 10, 13, 6, 0, 0, tzinfo=UTC))
    assert err.data["window"] == "day" and err.data["retry_after_sec"] == 11 * 3600  # 13:00 → nửa đêm VN


async def test_exceeding_one_window_counts_none(redis):
    a, u = uuid.uuid4(), uuid.uuid4()
    lim = Limits(per_minute=1, per_hour=5)
    await check(redis, lim, a, u)
    await blocked(redis, lim, a, u)
    await blocked(redis, lim, a, u)
    hour_key = next(k for k in await redis.rw.keys(f"bw:lim:{a}:{u}:hour:*"))
    assert int(await redis.rw.get(hour_key)) == 1  # lần bị chặn không cộng giờ / ngày


async def test_no_caps_or_superadmin_means_no_counting(redis):
    a, u = uuid.uuid4(), uuid.uuid4()
    assert await check(redis, Limits(), a, u) is None
    assert await check(redis, Limits(per_minute=1), a, u, exempt=True) is None
    assert await check(redis, Limits(per_minute=1), a, u, exempt=True) is None
    assert await redis.rw.keys(f"bw:lim:{a}:*") == []


async def test_token_cap_per_day_6002(redis):
    a, u = uuid.uuid4(), uuid.uuid4()
    lim = Limits(tokens_per_day=100)
    await check(redis, lim, a, u)
    await limits.count_tokens(redis, agent_id=a, user_id=u, tokens=60, tz=TZ)
    await check(redis, lim, a, u)  # chưa tới trần
    await limits.count_tokens(redis, agent_id=a, user_id=u, tokens=60, tz=TZ)
    await limits.count_tokens(redis, agent_id=a, user_id=u, tokens=0, tz=TZ)  # 0 token: bỏ qua
    err = await blocked(redis, lim, a, u, now=None)
    assert err.code == 6002 and err.status_code == 429 and err.data["limit"] == 100 and err.data["used"] == 120
    assert err.data["retry_after_sec"] >= 1


async def test_superadmin_exempt(api, aenv, kicks, fake_llm):
    stack = await setup(api, fake_llm.base_url)
    await api.post("studio.set_agent_limits", stack.root, agent_id=stack.agent_id, per_minute=1)
    for i in range(3):
        assert (await send(api, stack.root, f"sup {i}"))["run_id"]
    u = await api.as_user("u@x.io")
    await send(api, u, "một")
    r = await api.call("POST", "/agent/send", u, json={"content": "hai", "client_msg_id": "2"})
    assert r.status_code == 429 and r.json()["code"] == 6001


def test_merge_user_limit_overrides_field_by_field():
    base = AgentLimit(agent_id=uuid.uuid4(), per_minute=5, per_hour=50, per_day=None, tokens_per_day=1000)
    user = AgentUserLimit(agent_id=base.agent_id, user_id=uuid.uuid4(), per_minute=1, per_hour=None, per_day=9)
    assert limits.merge(base, user) == Limits(per_minute=1, per_hour=50, per_day=9, tokens_per_day=1000)
    assert limits.merge(base, None) == Limits(5, 50, None, 1000) and limits.merge(None, None) == Limits()
    assert Limits(per_hour=3).caps() == (0, 3, 0)


async def test_effective_reads_user_override_and_send_honours_it(api, aenv, kicks, fake_llm):
    stack = await setup(api, fake_llm.base_url)
    u = await api.as_user("u@x.io")
    await api.post("studio.set_agent_limits", stack.root, agent_id=stack.agent_id, per_minute=1)
    await api.post("studio.set_user_limit", stack.root, agent_id=stack.agent_id, user_id=u.id, per_minute=3)
    async with get_connections().postgres.ro() as s:
        eff = await limits.effective(
            s, uuid.UUID(stack.agent_id), uuid.UUID(u.id), await s.get(AgentLimit, uuid.UUID(stack.agent_id))
        )
    assert eff.per_minute == 3
    sent = [await send(api, u, "a")]
    for i in range(2):
        await set_run(sent[-1]["run_id"], status="done")
        sent.append(await send(api, u, f"b{i}", session_id=sent[0]["session_id"]))
    await set_run(sent[-1]["run_id"], status="done")
    r = await api.call(
        "POST", "/agent/send", u, json={"content": "d", "session_id": sent[0]["session_id"], "client_msg_id": "x"}
    )
    assert r.status_code == 429 and r.json()["data"]["limit"] == 3
