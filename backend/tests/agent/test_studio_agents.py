"""studio.* — agent: lưu, pool key theo provider, đổi model, hạn mức, toolset, override tool, danh mục tool."""

import uuid

import pytest

from app.agent.config.seed_data import specialists
from app.core.connections.registry import get_connections
from app.credentials.models import Credential
from tests.agent.helpers import get_root, new_cred, save_agent_body, setup


@pytest.fixture
async def stack(api, aenv, fake_llm):
    return await setup(api, fake_llm.base_url)


async def other_provider(stack, name="p2", kind="openai"):
    p = await stack.api.post("studio.save_provider", stack.root, name=name, kind=kind)
    m = await stack.api.post("studio.save_model", stack.root, provider_id=p["id"], model_id=f"{name}-m", name=name)
    return p, m


async def test_agent_keys_must_match_model_provider(stack):
    api, r = stack.api, stack.root
    p2, _ = await other_provider(stack)
    foreign = await new_cred(api, r, p2["id"], "foreign")
    shared = await new_cred(api, r, None, "any-provider")
    ok = {"agent_id": stack.agent_id}
    code = await api.err("POST", "studio.set_agent_keys", r, json={**ok, "keys": [{"credential_id": foreign["id"]}]})
    assert code == (422, 6020)
    body = (
        await api.call("POST", "/studio/set_agent_keys", r, json={**ok, "keys": [{"credential_id": foreign["id"]}]})
    ).json()
    assert body["data"]["mismatch"] == [foreign["id"]]
    assert await api.err(
        "POST", "studio.set_agent_keys", r, json={**ok, "keys": [{"credential_id": str(uuid.uuid4())}]}
    ) == (404, 1001)
    out = await api.post(
        "studio.set_agent_keys",
        r,
        **ok,
        keys=[{"credential_id": shared["id"]}, {"credential_id": stack.cred_id, "enabled": False}],
    )
    assert {k["name"]: k["enabled"] for k in out["keys"]} == {"any-provider": True, "k1": False}
    assert out["warnings"] == []
    await api.post("studio.set_agent_keys", r, **ok, keys=[])
    assert "no_key" in (await api.get("studio.get_agent", r, agent_id=stack.agent_id))["warnings"]


async def test_change_model_drops_mismatched_keys_with_warning(stack):
    api, r = stack.api, stack.root
    p2, m2 = await other_provider(stack)
    shared = await new_cred(api, r, None, "shared")
    await api.post(
        "studio.set_agent_keys",
        r,
        agent_id=stack.agent_id,
        keys=[{"credential_id": stack.cred_id}, {"credential_id": shared["id"]}],
    )
    current = await api.get("studio.get_agent", r, agent_id=stack.agent_id)
    out = await api.post("studio.save_agent", r, **save_agent_body(current, model_id=m2["id"]))
    assert [k["name"] for k in out["keys"]] == ["shared"]  # key của provider cũ bị bỏ, key chung ở lại
    assert out["model_name"] == "p2" and out["warnings"] == []
    onlyold = await api.post("studio.save_agent", r, **save_agent_body(out, model_id=stack.model_id))
    assert onlyold["keys"] == [] or [k["name"] for k in onlyold["keys"]] == ["shared"]
    cleared = await api.post("studio.set_agent_keys", r, agent_id=stack.agent_id, keys=[])
    assert "no_key" in cleared["warnings"]
    no_model = await api.post("studio.save_agent", r, **save_agent_body(cleared, model_id=None))
    assert no_model["warnings"][0] == "no_model"


async def test_key_provider_mismatch_warning_when_credential_provider_changes(stack):
    api, r = stack.api, stack.root
    p2, _ = await other_provider(stack)
    foreign = await new_cred(api, r, p2["id"], "f2")
    async with get_connections().postgres.rw() as s:
        cred = await s.get(Credential, uuid.UUID(stack.cred_id))
        cred.provider_id = uuid.UUID(p2["id"])
        s.add(cred)
    out = await api.get("studio.get_agent", r, agent_id=stack.agent_id)
    assert "key_provider_mismatch" in out["warnings"] and foreign["id"]


async def test_save_agent_create_validate_and_slug_unique(stack):
    api, r = stack.api, stack.root
    body = {
        "slug": "helper",
        "name": "Helper",
        "instructions": "x",
        "starters": ["a"],
        "visible_to": "roles",
        "visible_roles": ["admin"],
    }
    created = await api.post("studio.save_agent", r, **body)
    assert created["slug"] == "helper" and "history_limit" not in created and created["toolsets"] == []
    status, code = await api.err("POST", "studio.save_agent", r, json={**body, "slug": "Bad Slug"})
    assert (status, code) == (422, 1002)
    assert await api.err(
        "POST", "studio.save_agent", r, json={**body, "slug": "h2", "model_id": str(uuid.uuid4())}
    ) == (404, 1001)
    assert await api.err("POST", "studio.save_agent", r, json={**body, "agent_id": str(uuid.uuid4())}) == (404, 6003)
    assert await api.err("GET", "studio.get_agent", r, params={"agent_id": str(uuid.uuid4())}) == (404, 6003)
    slugs = {a["slug"] for a in await api.get("studio.list_agents", r)}
    assert slugs == {"assistant", "helper"} | {s.slug for s in specialists()}  # + chuyên gia của module


async def test_save_agent_duplicate_slug_is_1006(stack):
    body = {"slug": "dup", "name": "D"}
    await stack.api.post("studio.save_agent", stack.root, **body)
    assert await stack.api.err("POST", "studio.save_agent", stack.root, json=body) == (409, 1006)


async def test_limits_and_user_limits(stack):
    api, r = stack.api, stack.root
    out = await api.post(
        "studio.set_agent_limits", r, agent_id=stack.agent_id, per_minute=2, per_hour=10, tokens_per_day=1000
    )
    assert out["limits"] == {"per_minute": 2, "per_hour": 10, "per_day": None, "tokens_per_day": 1000}
    cleared = await api.post("studio.set_agent_limits", r, agent_id=stack.agent_id)
    assert cleared["limits"]["per_minute"] is None
    u = await api.as_user("limit@x.io")
    await api.post("studio.set_user_limit", r, agent_id=stack.agent_id, user_id=u.id, per_day=7)
    await api.post("studio.set_user_limit", r, agent_id=stack.agent_id, user_id=u.id, per_day=9)  # sửa, không nhân đôi
    await api.post("studio.set_user_limit", r, agent_id=stack.agent_id, user_id=u.id, remove=True)
    await api.post("studio.set_user_limit", r, agent_id=stack.agent_id, user_id=u.id, remove=True)  # xoá lần hai vô hại


async def test_tool_override_validates_op_and_params(stack):
    api, r = stack.api, stack.root
    base = {"agent_id": stack.agent_id, "operation": "notifications.list"}
    out = await api.post(
        "studio.set_tool_override",
        r,
        **base,
        policy="confirm",
        locked_params={"unread_only": True},
        default_params={"limit": 5},
    )
    (o,) = out["overrides"]
    assert (
        o["policy"] == "confirm" and o["locked_params"] == {"unread_only": True} and o["default_params"] == {"limit": 5}
    )
    for bad in (
        {"operation": "nope.nothing"},  # op không có
        {"operation": "studio.save_agent"},  # không phải tool
        {"locked_params": {"không_có_tham_số": 1}},
        {"locked_params": {"limit": "không phải số"}},
        {"default_params": {"offset": "không phải số"}},
    ):
        assert await api.err("POST", "studio.set_tool_override", r, json={**base, **bad}) == (422, 1002), bad
    await api.post("studio.set_toolsets", r, agent_id=stack.agent_id, toolsets=[])  # lookup bị gỡ
    assert await api.err("POST", "studio.set_tool_override", r, json=base) == (422, 1002)
    removed = await api.post("studio.set_tool_override", r, **base, remove=True)
    assert removed["overrides"] == []
    assert (await api.post("studio.set_tool_override", r, **base, remove=True))["overrides"] == []


async def test_toolsets_validation_and_catalog(stack):
    api, r = stack.api, stack.root
    assert await api.err(
        "POST", "studio.set_toolsets", r, json={"agent_id": stack.agent_id, "toolsets": ["lookup", "hack"]}
    ) == (422, 1002)
    out = await api.post("studio.set_toolsets", r, agent_id=stack.agent_id, toolsets=["lookup", "lookup"])
    assert out["toolsets"] == ["lookup"]
    catalog = {t["toolset"]: t for t in await api.get("studio.tool_catalog", r)}
    assert {"lookup", "tasks"} <= set(catalog)
    assert {o["name"]: o["default_policy"] for o in catalog["tasks"]["ops"]}["tasks.delete"] == "confirm"
    lookup = {o["name"]: o["default_policy"] for o in catalog["lookup"]["ops"]}
    assert lookup["notifications.list"] == "auto" and lookup["notifications.mark_all_read"] == "auto"
    assert await api.err("POST", "studio.set_toolsets", r, json={"agent_id": str(uuid.uuid4()), "toolsets": []}) == (
        404,
        6003,
    )


async def test_agent_ops_need_known_agent(stack):
    api, r = stack.api, stack.root
    ghost = str(uuid.uuid4())
    for op, extra in (
        ("studio.set_agent_keys", {"keys": []}),
        ("studio.set_agent_limits", {}),
        ("studio.set_tool_override", {"operation": "notifications.list"}),
    ):
        assert await api.err("POST", op, r, json={"agent_id": ghost, **extra}) == (404, 6003), op
    assert await get_root(api) is not None
