"""studio.* — quyền superadmin, hook (kiểm điều kiện / hành động), persona, danh mục tool."""

import uuid

import pytest

from tests.agent.helpers import assistant_id, get_root

COND = {"path": "args.amount", "op": "gt", "value": 1000}
BLOCK = {"action": "block", "message": "không được"}


@pytest.fixture
async def root(api, aenv):
    return api, await get_root(api), str(await assistant_id())


async def test_studio_superadmin_only(root):
    api, r, aid = root
    admin = await api.as_user("adm@x.io", roles=("admin",))
    ghost = str(uuid.uuid4())
    gets = [
        "studio.list_providers",
        "studio.list_models",
        "studio.list_agents",
        "studio.get_persona",
        "studio.tool_catalog",
    ]
    for op in gets:
        assert await api.err("GET", op, admin) == (403, 1005), op
    assert await api.err("GET", "studio.get_agent", admin, params={"agent_id": aid}) == (403, 1005)
    assert await api.err("GET", "studio.list_hooks", admin, params={"agent_id": aid}) == (403, 1005)
    posts = {
        "studio.save_provider": {"name": "x", "kind": "openai"},
        "studio.delete_provider": {"id": ghost},
        "studio.test_provider": {"provider_id": ghost, "credential_id": ghost},
        "studio.save_model": {"provider_id": ghost, "model_id": "m", "name": "m"},
        "studio.delete_model": {"id": ghost},
        "studio.save_agent": {"slug": "xx", "name": "x"},
        "studio.set_agent_keys": {"agent_id": aid, "keys": []},
        "studio.set_agent_limits": {"agent_id": aid},
        "studio.set_user_limit": {"agent_id": aid, "user_id": ghost},
        "studio.set_toolsets": {"agent_id": aid, "toolsets": []},
        "studio.set_tool_override": {"agent_id": aid, "operation": "notifications.list"},
        "studio.save_hook": {"agent_id": aid, "point": "before_run", "action": BLOCK},
        "studio.delete_hook": {"hook_id": ghost},
        "studio.test_hook": {"point": "before_run", "action": BLOCK},
        "studio.save_persona": {"content": "x"},
    }
    for op, body in posts.items():
        assert await api.err("POST", op, admin, json=body) == (403, 1005), op


async def test_hook_condition_validation(root):
    api, r, aid = root
    ok = await api.post(
        "studio.save_hook",
        r,
        agent_id=aid,
        name="lớn",
        point="before_tool",
        conditions=[COND],
        action={"action": "require_approval"},
        position=2,
    )
    assert (
        ok["action"] == "require_approval" and ok["action_config"] == {"action": "require_approval"} and ok["enabled"]
    )
    base = {"agent_id": aid, "point": "before_tool", "action": BLOCK}
    cases = {
        "11 mệnh đề": {"conditions": [COND] * 11},
        "op lạ": {"conditions": [{"path": "args.x", "op": "regex", "value": 1}]},
        "path sai": {"conditions": [{"path": "Args X", "op": "eq", "value": 1}]},
        "field thừa": {"conditions": [{**COND, "oops": 1}]},
        "action lạ": {"action": {"action": "explode"}},
        "thiếu message": {"action": {"action": "block"}},
        "action không hợp điểm": {"point": "before_run", "action": {"action": "require_approval"}},
        "after_run chặn": {"point": "after_run", "action": BLOCK},
        "webhook url sai": {"action": {"action": "webhook", "url": "not a url"}},
    }
    for label, over in cases.items():
        assert await api.err("POST", "studio.save_hook", r, json={**base, **over}) == (422, 6017), label
    assert await api.err("POST", "studio.save_hook", r, json={**base, "point": "later"}) == (422, 1002)
    assert await api.err("POST", "studio.save_hook", r, json={**base, "agent_id": str(uuid.uuid4())}) == (404, 6003)
    full = await api.post("studio.save_hook", r, **base, conditions=[COND] * 10)
    assert len(full["conditions"]) == 10


async def test_hook_crud_and_listing_order(root):
    api, r, aid = root
    a = await api.post("studio.save_hook", r, agent_id=aid, point="before_run", action=BLOCK, position=5)
    b = await api.post(
        "studio.save_hook",
        r,
        agent_id=aid,
        point="before_run",
        action={"action": "add_context", "text": "hi"},
        position=1,
    )
    names = [h["id"] for h in await api.get("studio.list_hooks", r, agent_id=aid)]
    assert names == [b["id"], a["id"]]
    upd = await api.post(
        "studio.save_hook",
        r,
        hook_id=a["id"],
        agent_id=aid,
        point="before_run",
        action=BLOCK,
        enabled=False,
        name="đổi",
    )
    assert upd["enabled"] is False and upd["name"] == "đổi"
    assert (await api.get("studio.get_agent", r, agent_id=aid))["hooks_count"] == 2
    other = await api.post("studio.save_agent", r, slug="other", name="O")
    wrong = {"hook_id": a["id"], "agent_id": other["id"], "point": "before_run", "action": BLOCK}
    assert await api.err("POST", "studio.save_hook", r, json=wrong) == (404, 1001)
    ghost = {"hook_id": str(uuid.uuid4()), "agent_id": aid, "point": "before_run", "action": BLOCK}
    assert await api.err("POST", "studio.save_hook", r, json=ghost) == (404, 1001)
    await api.post("studio.delete_hook", r, hook_id=a["id"])
    assert await api.err("POST", "studio.delete_hook", r, json={"hook_id": a["id"]}) == (404, 1001)
    assert len(await api.get("studio.list_hooks", r, agent_id=aid)) == 1


async def test_persona_roundtrip(root):
    api, r, _ = root
    seeded = await api.get("studio.get_persona", r)
    assert seeded["content"] and seeded["updated_at"]
    saved = await api.post("studio.save_persona", r, content="Hãy thật vui vẻ.")
    assert saved["content"] == "Hãy thật vui vẻ."
    assert (await api.get("studio.get_persona", r))["content"] == "Hãy thật vui vẻ."
    assert await api.err("POST", "studio.save_persona", r, json={"content": "x" * 20001}) == (422, 1002)
