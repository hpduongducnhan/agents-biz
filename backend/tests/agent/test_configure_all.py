"""studio.configure_all: một model + pool key cho orchestrator và mọi chuyên gia trong một lần."""

import uuid

import pytest
from sqlmodel import select

from app.agent.config.models import Agent, AgentKey
from app.core.connections.registry import get_connections
from tests.agent.helpers import new_cred, setup


@pytest.fixture
async def stack(api, aenv, fake_llm):
    return await setup(api, fake_llm.base_url)


async def key_map() -> dict[uuid.UUID, set[uuid.UUID]]:
    async with get_connections().postgres.ro() as s:
        agents = (await s.exec(select(Agent))).all()
        keys = (await s.exec(select(AgentKey))).all()
    return {a.id: {k.credential_id for k in keys if k.agent_id == a.id} for a in agents}


async def models_of() -> dict[str, uuid.UUID | None]:
    async with get_connections().postgres.ro() as s:
        return {a.slug: a.model_id for a in (await s.exec(select(Agent))).all()}


async def test_configure_all_sets_model_and_keys_for_every_agent(stack):
    api, root = stack.api, stack.root
    extra = await new_cred(api, root, stack.provider_id, "k2")
    out = await api.post(
        "studio.configure_all", root, model_id=stack.model_id, credential_ids=[stack.cred_id, extra["id"]]
    )
    models = await models_of()
    assert out["agents"] == len(models) >= 2  # orchestrator + chuyên gia `general`
    assert set(models.values()) == {uuid.UUID(stack.model_id)}
    want = {uuid.UUID(stack.cred_id), uuid.UUID(extra["id"])}
    assert all(keys == want for keys in (await key_map()).values())
    got = await api.get("studio.get_agent", root, agent_id=stack.agent_id)
    assert got["model_id"] == stack.model_id and {k["credential_id"] for k in got["keys"]} == {str(c) for c in want}
    assert all(k["enabled"] for k in got["keys"])


async def test_configure_all_replaces_previous_keys_and_is_repeatable(stack):
    api, root = stack.api, stack.root
    other = await new_cred(api, root, None, "shared-any")
    await api.post("studio.configure_all", root, model_id=stack.model_id, credential_ids=[stack.cred_id])
    again = await api.post("studio.configure_all", root, model_id=stack.model_id, credential_ids=[other["id"]])
    assert again["agents"] > 0
    assert all(keys == {uuid.UUID(other["id"])} for keys in (await key_map()).values())
    await api.post("studio.configure_all", root, model_id=stack.model_id, credential_ids=[other["id"]] * 3)
    async with get_connections().postgres.ro() as s:
        rows = (await s.exec(select(AgentKey))).all()
    assert len(rows) == again["agents"]  # trùng id trong danh sách → một dòng mỗi agent


async def test_configure_all_rejects_key_of_another_provider_with_6020_and_changes_nothing(stack):
    api, root = stack.api, stack.root
    p2 = await api.post("studio.save_provider", root, name="p2", kind="openai")
    foreign = await new_cred(api, root, p2["id"], "foreign")
    before = (await models_of(), await key_map())
    body = {"model_id": stack.model_id, "credential_ids": [stack.cred_id, foreign["id"]]}
    r = await api.call("POST", "/studio/configure_all", root, json=body)
    assert (r.status_code, r.json()["code"]) == (422, 6020) and r.json()["data"]["mismatch"] == [foreign["id"]]
    assert (await models_of(), await key_map()) == before


async def test_configure_all_unknown_model_or_key_is_404_and_empty_keys_422(stack):
    api, root = stack.api, stack.root
    ghost = str(uuid.uuid4())
    for body in (
        {"model_id": ghost, "credential_ids": [stack.cred_id]},
        {"model_id": stack.model_id, "credential_ids": [ghost]},
    ):
        assert await api.err("POST", "studio.configure_all", root, json=body) == (404, 1001)
    assert (
        await api.err("POST", "studio.configure_all", root, json={"model_id": stack.model_id, "credential_ids": []})
    )[0] == 422
    assert (await api.err("POST", "studio.configure_all", root, json={"credential_ids": [stack.cred_id]}))[0] == 422


async def test_configure_all_is_superadmin_only(stack):
    api = stack.api
    admin = await api.as_user("adm@x.io", roles=("admin",))
    body = {"model_id": stack.model_id, "credential_ids": [stack.cred_id]}
    assert await api.err("POST", "studio.configure_all", admin, json=body) == (403, 1005)
    assert (await api.err("POST", "studio.configure_all", None, json=body))[0] == 401
