"""studio.* — provider + model: CRUD, trùng, thử kết nối (LLM giả), mọi ghi bump phiên bản cấu hình."""

import uuid

import pytest

from app.agent.config import registry
from app.core.connections.registry import get_connections
from tests.agent.helpers import get_root, new_cred, setup


@pytest.fixture
async def root(api, aenv):
    return api, await get_root(api)


async def version() -> int:
    return int(await get_connections().redis.rw.get(registry.VERSION_KEY) or 0)


async def test_provider_model_crud_and_unique(root):
    api, r = root
    p = await api.post("studio.save_provider", r, name="oa", kind="openai", base_url="https://x.test/v1")
    assert p["models_count"] == 0 and p["status"] == "active"
    assert await api.err("POST", "studio.save_provider", r, json={"name": "oa", "kind": "anthropic"}) == (409, 1006)
    renamed = await api.post(
        "studio.save_provider", r, provider_id=p["id"], name="oa2", kind="openai", status="disabled"
    )
    assert renamed["name"] == "oa2" and renamed["status"] == "disabled"
    assert await api.err(
        "POST", "studio.save_provider", r, json={"provider_id": str(uuid.uuid4()), "name": "z", "kind": "openai"}
    ) == (404, 1001)
    assert (await api.err("POST", "studio.save_provider", r, json={"name": "z", "kind": "nope"}))[1] == 1002
    m = await api.post(
        "studio.save_model",
        r,
        provider_id=p["id"],
        model_id="gpt-x",
        name="GPT X",
        input_price_per_1m="2.5",
        output_price_per_1m=10,
    )
    assert m["provider_name"] == "oa2" and float(m["input_price_per_1m"]) == 2.5
    assert await api.err(
        "POST", "studio.save_model", r, json={"provider_id": p["id"], "model_id": "gpt-x", "name": "dup"}
    ) == (409, 1006)
    upd = await api.post(
        "studio.save_model",
        r,
        model_ref=m["id"],
        provider_id=p["id"],
        model_id="gpt-x",
        name="Mới",
        context_window=128000,
    )
    assert upd["id"] == m["id"] and upd["name"] == "Mới" and upd["context_window"] == 128000
    bad = {"provider_id": str(uuid.uuid4()), "model_id": "q", "name": "q"}
    assert await api.err("POST", "studio.save_model", r, json=bad) == (404, 1001)
    assert await api.err(
        "POST", "studio.save_model", r, json={**bad, "provider_id": p["id"], "model_ref": str(uuid.uuid4())}
    ) == (404, 1001)
    assert [x["models_count"] for x in await api.get("studio.list_providers", r)] == [1]
    assert [x["name"] for x in await api.get("studio.list_models", r)] == ["Mới"]
    await api.post("studio.delete_model", r, id=m["id"])
    assert await api.err("POST", "studio.delete_model", r, json={"id": m["id"]}) == (404, 1001)
    m2 = await api.post("studio.save_model", r, provider_id=p["id"], model_id="m2", name="M2")
    await api.post("studio.delete_provider", r, id=p["id"])  # model đi theo
    assert await api.get("studio.list_models", r) == [] and m2["id"]
    assert await api.err("POST", "studio.delete_provider", r, json={"id": p["id"]}) == (404, 1001)


async def test_delete_model_in_use_clears_agent_model(root, fake_llm):
    api, r = root
    stack = await setup(api, fake_llm.base_url)
    await api.post("studio.delete_model", r, id=stack.model_id)
    agent = await api.get("studio.get_agent", r, agent_id=stack.agent_id)
    assert agent["model_id"] is None and "no_model" in agent["warnings"]


async def test_writes_bump_registry_version(root):
    api, r = root
    seen = [await version()]

    async def bumped() -> bool:
        seen.append(await version())
        return seen[-1] > seen[-2]

    p = await api.post("studio.save_provider", r, name="v", kind="openai")
    assert await bumped()
    m = await api.post("studio.save_model", r, provider_id=p["id"], model_id="m", name="m")
    assert await bumped()
    await api.post("studio.save_persona", r, content="hi")
    assert await bumped()
    a = (await api.get("studio.list_agents", r))[0]
    await api.post("studio.set_toolsets", r, agent_id=a["id"], toolsets=["lookup"])
    assert await bumped()
    await api.post("studio.set_agent_limits", r, agent_id=a["id"], per_minute=3)
    assert await bumped()
    await api.post("studio.delete_model", r, id=m["id"])
    assert await bumped()
    before = await version()
    await api.get("studio.list_agents", r)  # đọc không bump
    assert await version() == before


async def test_test_provider_ok_and_lists_models(root, fake_llm):
    api, r = root
    p = await api.post("studio.save_provider", r, name="f", kind="openai_compatible", base_url=fake_llm.base_url)
    c = await new_cred(api, r, p["id"], "good", "fake-key")
    out = await api.post("studio.test_provider", r, provider_id=p["id"], credential_id=c["id"])
    assert out["ok"] is True and "fake-model" in out["models"] and out["latency_ms"] >= 0 and out["error"] is None


async def test_test_provider_reports_failure_without_500(root, fake_llm):
    api, r = root
    p = await api.post("studio.save_provider", r, name="f", kind="openai_compatible", base_url=fake_llm.base_url)
    bad = await new_cred(api, r, p["id"], "bad", "bad-key")
    out = await api.post("studio.test_provider", r, provider_id=p["id"], credential_id=bad["id"])
    assert out["ok"] is False and "401" in out["error"]
    dead = await api.post(
        "studio.save_provider", r, name="dead", kind="openai_compatible", base_url="http://127.0.0.1:1/v1"
    )
    out = await api.post("studio.test_provider", r, provider_id=dead["id"], credential_id=bad["id"])
    assert out["ok"] is False and out["error"]
    missing = {"provider_id": str(uuid.uuid4()), "credential_id": bad["id"]}
    assert await api.err("POST", "studio.test_provider", r, json=missing) == (404, 1001)
    ghost = {"provider_id": p["id"], "credential_id": str(uuid.uuid4())}
    assert await api.err("POST", "studio.test_provider", r, json=ghost) == (404, 1001)
