"""studio.list_routes / save_route / delete_route: đích chỉ specialist, ≤ 20 route, superadmin, bump registry."""

import uuid

import pytest

from app.agent.router.models import MAX_ROUTES
from tests.agent.helpers import assistant_id, get_root, load_spec, save_agent_body, slug_ids


@pytest.fixture
async def env(team, api, aenv):
    root = await get_root(api)
    return api, root, str(await assistant_id()), {k: str(v) for k, v in (await slug_ids()).items()}


async def new_specialist(api, root, slug):
    return (await api.post("studio.save_agent", root, slug=slug, name=slug.upper()))["id"]


async def test_list_routes_sorted_by_position(env):
    api, root, aid, ids = env
    out = await api.get("studio.list_routes", root, orchestrator_id=aid)
    assert [r["slug"] for r in out] == ["personal", "report", "general"]
    assert out[0]["name"] == "Cá nhân" and out[0]["enabled"] and out[0]["examples"] and out[0]["intent"]
    assert await api.err("GET", "studio.list_routes", root, params={"orchestrator_id": ids["personal"]}) == (404, 6003)
    assert await api.err("GET", "studio.list_routes", root, params={"orchestrator_id": str(uuid.uuid4())}) == (
        404,
        6003,
    )


async def test_save_route_creates_updates_and_bumps_registry(env):
    api, root, aid, ids = env
    extra = await new_specialist(api, root, "extra")
    before = await load_spec(aid)
    assert "extra" not in [r.slug for r in before.routes]
    body = {"orchestrator_id": aid, "agent_id": extra, "intent": "Việc phụ", "examples": ["a", " b "], "position": 9}
    created = await api.post("studio.save_route", root, **body)
    assert created["slug"] == "extra" and created["examples"] == ["a", "b"] and created["enabled"] is True
    assert [r.slug for r in (await load_spec(aid)).routes][-1] == "extra"  # cache đã bump
    again = await api.post("studio.save_route", root, **{**body, "intent": "Đổi", "enabled": False})
    assert again["intent"] == "Đổi" and again["enabled"] is False
    rows = await api.get("studio.list_routes", root, orchestrator_id=aid)
    assert len([r for r in rows if r["slug"] == "extra"]) == 1  # sửa, không nhân đôi
    assert "extra" not in [r.slug for r in (await load_spec(aid)).routes]  # tắt → ra khỏi spec


async def test_save_route_rejects_orchestrator_target_and_limit_20(env):
    api, root, aid, ids = env
    base = {"orchestrator_id": aid, "intent": "x"}
    other_orch = (await api.post("studio.save_agent", root, slug="orch2", name="O2", kind="orchestrator"))["id"]
    for target in (other_orch, aid):
        assert await api.err("POST", "studio.save_route", root, json={**base, "agent_id": target}) == (422, 1002)
    assert await api.err("POST", "studio.save_route", root, json={**base, "agent_id": str(uuid.uuid4())}) == (
        422,
        1002,
    )
    assert await api.err(
        "POST", "studio.save_route", root, json={**base, "agent_id": ids["general"], "intent": ""}
    ) == (
        422,
        1002,
    )
    for i in range(MAX_ROUTES - 3):
        sid = await new_specialist(api, root, f"sp{i}")
        await api.post("studio.save_route", root, **base, agent_id=sid, position=20 + i)
    assert len(await api.get("studio.list_routes", root, orchestrator_id=aid)) == MAX_ROUTES
    over = await new_specialist(api, root, "over")
    assert await api.err("POST", "studio.save_route", root, json={**base, "agent_id": over}) == (422, 1002)
    await api.post("studio.save_route", root, **base, agent_id=ids["general"], position=3)  # sửa route cũ


async def test_delete_route_then_404_and_bump(env):
    api, root, aid, ids = env
    await api.post("studio.delete_route", root, orchestrator_id=aid, agent_id=ids["report"])
    assert "report" not in [r.slug for r in (await load_spec(aid)).routes]
    assert await api.err(
        "POST", "studio.delete_route", root, json={"orchestrator_id": aid, "agent_id": ids["report"]}
    ) == (404, 1001)


async def test_route_ops_superadmin_only(env):
    api, root, aid, ids = env
    admin = await api.as_user("adm@x.io", roles=("admin",))
    key = {"orchestrator_id": aid, "agent_id": ids["general"]}
    assert await api.err("GET", "studio.list_routes", admin, params={"orchestrator_id": aid}) == (403, 1005)
    assert await api.err("POST", "studio.save_route", admin, json={**key, "intent": "x"}) == (403, 1005)
    assert await api.err("POST", "studio.delete_route", admin, json=key) == (403, 1005)


async def test_save_agent_body_roundtrip_keeps_orchestrator(env):
    api, root, aid, ids = env
    current = await api.get("studio.get_agent", root, agent_id=aid)
    out = await api.post("studio.save_agent", root, **save_agent_body(current))
    assert out["kind"] == "orchestrator" and out["toolsets"] == []
