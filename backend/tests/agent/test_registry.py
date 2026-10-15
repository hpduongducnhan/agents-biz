"""registry: AgentSpec bất biến, cache theo `bw:agentcfg:v`, bump xoá cache + broadcast, Redis hỏng → đọc DB."""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import update

from app.agent.config import registry
from app.agent.config.models import Agent, AgentSystemPrompt
from app.core.connections.registry import get_connections
from tests.agent.helpers import assistant_id, setup


async def rename(agent_id, name: str) -> None:
    async with get_connections().postgres.rw() as s:
        await s.exec(update(Agent).where(Agent.id == agent_id).values(name=name))


async def load(agent_id):
    conns = get_connections()
    async with conns.postgres.ro() as s:
        return await registry.load(s, conns.redis, agent_id)


async def test_registry_caches_until_version_bump(api, aenv):
    aid = await assistant_id()
    first = await load(aid)
    assert first.agent.name == "Assistant"
    await rename(aid, "Đổi tên")
    assert (await load(aid)).agent.name == "Assistant"  # DB đổi mà không bump → cache cũ
    await get_connections().redis.rw.incr(registry.VERSION_KEY)  # process khác đã bump (không xoá được cache này)
    assert (await load(aid)).agent.name == "Đổi tên"
    await rename(aid, "Lần ba")
    await registry.bump(get_connections().redis)  # bump trong process: xoá cache luôn
    assert (await load(aid)).agent.name == "Lần ba"


async def test_registry_spec_content_and_missing(api, aenv, fake_llm):
    stack = await setup(api, fake_llm.base_url)
    spec = await load(uuid.UUID(stack.agent_id))
    assert spec.model.model_id == "fake-model" and spec.provider.kind == "openai_compatible"
    assert spec.key_ids == (uuid.UUID(stack.cred_id),)
    assert "lookup" in spec.toolsets
    assert spec.persona and spec.id == spec.agent.id
    assert await load(uuid.uuid4()) is None
    conns = get_connections()
    async with conns.postgres.ro() as s:
        assert (await registry.by_slug(s, conns.redis, "assistant")).id == spec.id
        assert await registry.by_slug(s, conns.redis, "nope") is None


async def test_persona_only_when_shared_and_disabled_keys_excluded(api, aenv, fake_llm):
    stack = await setup(api, fake_llm.base_url)
    aid = uuid.UUID(stack.agent_id)
    async with get_connections().postgres.rw() as s:
        await s.exec(update(Agent).where(Agent.id == aid).values(persona_shared=False))
    await registry.bump(get_connections().redis)
    assert (await load(aid)).persona == ""
    await api.post(
        "studio.set_agent_keys",
        stack.root,
        agent_id=stack.agent_id,
        keys=[{"credential_id": stack.cred_id, "enabled": False}],
    )
    assert (await load(aid)).key_ids == ()
    async with get_connections().postgres.ro() as s:
        assert (await s.get(AgentSystemPrompt, "persona")).content


async def test_redis_failure_reads_db_every_time_and_warns(api, aenv, bw_log):
    class Broken:
        class rw:  # noqa: N801 — giả client Redis hỏng
            @staticmethod
            async def get(_key):
                raise ConnectionError("redis down")

    aid = await assistant_id()
    async with get_connections().postgres.ro() as s:
        a = await registry.load(s, Broken, aid)
    await rename(aid, "Sau")
    async with get_connections().postgres.ro() as s:  # phiên mới: identity map của phiên cũ sẽ giữ bản cũ
        b = await registry.load(s, Broken, aid)
    assert a.agent.name == "Assistant" and b.agent.name == "Sau"  # không cache: mỗi lần đọc DB
    assert any(r.get("loc") == "agt0001" for r in bw_log())
    assert await registry.version(None) == "0"


async def test_bump_survives_broadcast_failure(api, aenv, monkeypatch, bw_log):
    async def boom(*_a, **_k):
        raise RuntimeError("no broker")

    monkeypatch.setattr(registry, "broadcast", boom)
    await registry.bump(get_connections().redis)
    assert any(r.get("loc") == "agt0002" for r in bw_log())
    registry._cache[uuid.uuid4()] = ("0", SimpleNamespace())
    await registry.on_changed({})
    assert registry._cache == {}


@pytest.mark.parametrize("redis", [None])
async def test_bump_without_redis_only_clears_cache(redis, aenv, monkeypatch):
    async def ok(*_a, **_k):
        return None

    monkeypatch.setattr(registry, "broadcast", ok)
    registry._cache[uuid.uuid4()] = ("0", SimpleNamespace())
    await registry.bump(redis)
    assert registry._cache == {}
