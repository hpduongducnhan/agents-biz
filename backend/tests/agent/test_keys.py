"""Chọn + xoay key: round-robin, auto theo trọng số, nguội khi 429, tắt khi 401, hết key → 6010."""

import uuid
from datetime import UTC, datetime

import anthropic
import httpx
import httpx2
import openai
import pytest

from app.agent.runtime import keys, runner
from app.agent.testing import fake_llm as fl
from app.core.connections.registry import get_connections
from app.core.errors import AppException
from app.core.rkeys import rkey
from app.core.settings import active_settings
from tests.agent.helpers import add_keys, chat, credential, get_root, load_spec, notes, run_row, setup


@pytest.fixture
async def env(api, aenv, rt, fake_llm, memory_sinks):
    stack = await setup(api, fake_llm.base_url)
    u = await api.as_user("u@x.io")
    return stack, u, memory_sinks


async def pick(spec, exclude=()):
    conns = get_connections()
    async with conns.postgres.rw() as s:
        return await keys.pick(s, conns.redis, active_settings(), spec, exclude=exclude)


async def test_round_robin_cycles_healthy_keys(env):
    stack, _, _ = env
    ids = await add_keys(stack, ["k-a", "k-b", "k-c"], strategy="round_robin")
    spec = await load_spec(stack.agent_id)
    order = sorted(ids)
    picked = [(await pick(spec)).id for _ in range(7)]
    assert [str(p) for p in picked] == [order[i % 3] for i in range(7)]
    secrets = {str(p.id): p.secret for p in [await pick(spec)]}
    assert list(secrets.values())[0].startswith("k-") and (await pick(spec)).masked_hint


async def test_auto_prefers_least_used_by_weight(env):
    stack, _, _ = env
    a, b = await add_keys(stack, ["k-a", "k-b"], strategy="auto", weights=[1, 5])
    spec = await load_spec(stack.agent_id)
    redis = get_connections().redis
    hour = datetime.now(UTC).strftime("%Y%m%d%H")
    await redis.rw.set(rkey("key", "req", a, hour), 10)  # 10 / 1
    await redis.rw.set(rkey("key", "req", b, hour), 30)  # 30 / 5 = 6 → ít hơn
    assert str((await pick(spec)).id) == b
    await redis.rw.set(rkey("key", "req", b, hour), 60)  # 60 / 5 = 12 > 10
    assert str((await pick(spec)).id) == a
    for _ in range(40):  # tải thật: chia theo trọng số 1 : 5
        await pick(spec)
    used = [int(await redis.rw.get(rkey("key", "req", c, hour)) or 0) for c in (a, b)]
    assert used[1] > used[0]


async def test_healthy_excludes_cooled_disabled_and_excluded(env):
    stack, _, _ = env
    a, b, c = await add_keys(stack, ["k-a", "k-b", "k-c"])
    spec = await load_spec(stack.agent_id)
    redis = get_connections().redis
    await keys.cool(redis, uuid.UUID(a), 60)
    assert await redis.rw.ttl(keys.cool_key(uuid.UUID(a))) in range(1, 61)
    await stack.api.post("credentials.update", stack.root, credential_id=b, status="disabled")
    conns = get_connections()
    async with conns.postgres.ro() as s:
        assert [str(x.id) for x in await keys.healthy(s, redis, spec)] == [c]
        assert await keys.healthy(s, redis, spec, exclude=[uuid.UUID(c)]) == []
    with pytest.raises(AppException) as exc:
        await pick(spec, exclude=[uuid.UUID(c)])
    assert exc.value.code == 6010 and exc.value.status_code == 503


_REQ = httpx2.Request("POST", "https://x/v1/chat/completions")


def _openai_in_stream():
    msg = "Our servers are currently overloaded. Please try again later."
    return openai.APIError(msg, _REQ, body={"message": msg})


def _wrapped_in_stream():
    outer = RuntimeError("bọc")
    outer.__cause__ = _openai_in_stream()
    return outer


@pytest.mark.parametrize(
    ("make", "want"),
    [
        (lambda: type("E", (Exception,), {"status_code": 429})(), "rate"),
        (lambda: type("E", (Exception,), {"status_code": 401})(), "auth"),
        (lambda: type("E", (Exception,), {"status": 403})(), "auth"),
        (lambda: type("E", (Exception,), {"status_code": 503})(), "server"),
        (lambda: type("E", (Exception,), {"response": type("R", (), {"status_code": 500})()})(), "server"),
        (lambda: httpx.ConnectError("x"), "server"),
        (lambda: TimeoutError(), "server"),
        (lambda: type("APIConnectionError", (Exception,), {})("x"), "server"),
        (lambda: ValueError("lạ"), "other"),
        (lambda: type("E", (Exception,), {"status_code": 400})(), "other"),
        (_openai_in_stream, "server"),
        (
            lambda: anthropic.APIStatusError("overloaded", response=httpx2.Response(200, request=_REQ), body=None),
            "server",
        ),
        (
            lambda: openai.BadRequestError("bad", response=httpx2.Response(400, request=_REQ), body=None),
            "other",
        ),
        (_wrapped_in_stream, "server"),
    ],
)
def test_classify(make, want):
    assert keys.classify(make()) == want


def test_classify_follows_cause_chain():
    inner = type("E", (Exception,), {"status_code": 429})()
    outer = RuntimeError("bọc")
    outer.__cause__ = inner
    assert keys.classify(outer) == "rate"


async def test_rate_limited_key_cools_down_and_switches(env):
    stack, u, _ = env
    a, b = await add_keys(stack, ["ratelimit-A", "fake-key"], strategy="round_robin")
    spec = await load_spec(stack.agent_id)
    ordered = sorted([a, b])
    await get_connections().redis.rw.set(rkey("rr", str(spec.id)), ordered.index(a))  # lần INCR kế tiếp chọn A
    sent, run = await chat(stack.api, u, "chào")
    assert run.status == "done" and sorted(run.credential_ids) == sorted([a, b])
    auths = [r["headers"]["authorization"] for r in fl.REQUESTS]
    assert auths == ["Bearer ratelimit-A", "Bearer fake-key"]
    assert await get_connections().redis.rw.ttl(keys.cool_key(uuid.UUID(a))) > 0
    assert (await credential(a)).status == "active"  # 429 chỉ làm nguội, không tắt


async def test_auth_error_disables_key_and_notifies_superadmin(env):
    stack, u, sinks = env
    a, b = await add_keys(stack, ["bad-key-A", "fake-key"], strategy="round_robin")
    spec = await load_spec(stack.agent_id)
    await get_connections().redis.rw.set(rkey("rr", str(spec.id)), sorted([a, b]).index(a))
    sent, run = await chat(stack.api, u, "chào")
    assert run.status == "done"
    bad = await credential(a)
    assert bad.status == "disabled" and "provider từ chối key" in bad.disabled_reason
    assert (await credential(b)).status == "active"
    assert [i["loc"] for i in sinks.issues.items] == ["agt0602"] and sinks.issues.items[0]["context"][
        "credential_id"
    ] == a


async def test_key_disabled_notification_reaches_superadmin(env):
    stack, u, _ = env
    a, b = await add_keys(stack, ["bad-key-A", "fake-key"], strategy="round_robin")
    spec = await load_spec(stack.agent_id)
    await get_connections().redis.rw.set(rkey("rr", str(spec.id)), sorted([a, b]).index(a))
    await chat(stack.api, u, "chào")
    root = await get_root(stack.api)
    (note,) = await notes(root.id, "agent_key_disabled")
    assert "đã bị tắt" in note.title
    assert note.action == {"kind": "link", "to": "/studio?tab=credentials"}


async def test_no_healthy_key_is_6010(env):
    stack, u, _ = env
    await add_keys(stack, [])
    sent, run = await chat(stack.api, u, "không key")
    assert (run.status, run.error_code) == ("failed", 6010) and fl.REQUESTS == []


async def test_only_key_bad_fails_with_6011_and_key_disabled(env):
    stack, u, _ = env
    (a,) = await add_keys(stack, ["bad-only"])
    sent, run = await chat(stack.api, u, "chào")
    assert (run.status, run.error_code) == ("failed", 6011)
    assert (await credential(a)).status == "disabled"


async def test_server_error_retries_same_key_once_then_rotates(env):
    stack, u, _ = env
    await add_keys(stack, ["k-a", "k-b"], strategy="round_robin")
    sent, run = await chat(stack.api, u, "fail500 cả hai")
    assert (run.status, run.error_code) == ("failed", 6011)
    auths = [r["headers"]["authorization"] for r in fl.REQUESTS]
    assert len(auths) == 4 and auths[0] == auths[1] and auths[2] == auths[3] and auths[0] != auths[2]
    assert runner.MESSAGES[6011] in run.error and len(run.credential_ids) == 2 and await run_row(sent["run_id"])
