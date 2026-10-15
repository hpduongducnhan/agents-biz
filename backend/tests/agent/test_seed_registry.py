"""Registry chuyên gia seed: `register_specialist` kiểm hợp lệ, thứ tự `specialists()`, seed tạo / nâng một lần."""

import hashlib

import pytest
from sqlalchemy import delete
from sqlmodel import select

from app.agent.config import seed, seed_data
from app.agent.config.models import Agent, AgentToolset
from app.agent.config.seed_data import SpecialistSeed, register_specialist, specialists
from app.agent.router.models import OrchestratorRoute
from app.core.connections.registry import get_connections
from app.domains import load_domains
from tests.agent.helpers import get_root


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def make_seed(tmp_path, slug="extra", **kw) -> SpecialistSeed:
    (tmp_path / f"{slug}.md").write_text("Hướng dẫn mới.\n", encoding="utf-8")
    fields = {
        "name": "Phụ", "description": "Mô tả", "toolsets": ("lookup",), "intent": "Intent", "examples": ("a", "b", "c"),
        "prompt_dir": tmp_path,
    }  # fmt: skip
    return SpecialistSeed(slug=slug, **(fields | kw))


@pytest.fixture
def registry_clean():
    before = dict(seed_data._SEEDS)
    yield
    seed_data._SEEDS.clear()
    seed_data._SEEDS.update(before)


def test_platform_general_plus_tasks_module_specialist():
    load_domains()  # nạp `app/tasks/agent.py`
    slugs = [s.slug for s in specialists()]
    assert slugs[-1] == "general" and "tasks" in slugs  # general (dự phòng) luôn cuối; module đứng trước
    assert dict((s.slug, s.toolsets) for s in specialists())["tasks"] == ("tasks",)
    assert specialists()[-1].toolsets == ("lookup",)


def test_register_validates_prompt_and_duplicates(registry_clean, tmp_path):
    with pytest.raises(ValueError, match="thiếu prompt"):
        register_specialist(SpecialistSeed("nopmt", "x", "x", ("lookup",), "i", (), prompt_dir=tmp_path))
    assert "nopmt" not in seed_data._SEEDS
    first = make_seed(tmp_path)
    register_specialist(first)
    register_specialist(first)  # trùng nguyên bản = vô hại
    with pytest.raises(ValueError, match="đã đăng ký"):
        register_specialist(make_seed(tmp_path, intent="khác"))


def test_specialists_keep_registration_order_with_general_last(registry_clean, tmp_path):
    load_domains()
    register_specialist(make_seed(tmp_path, "zeta"))
    register_specialist(make_seed(tmp_path, "alpha"))
    assert [s.slug for s in specialists()][-3:] == ["zeta", "alpha", "general"]


async def test_fresh_seed_creates_general_and_route(app_env):
    async with get_connections().postgres.ro() as s:
        agents = {a.slug: a for a in (await s.exec(select(Agent))).all()}
        assert set(agents) == {"assistant"} | {s.slug for s in specialists()} and "tasks" in agents
        general = agents["general"]
        assert general.kind == "specialist" and general.visible_to == "roles" and "handoff" in general.instructions
        sets = (await s.exec(select(AgentToolset.toolset).where(AgentToolset.agent_id == general.id))).all()
        assert set(sets) == {"lookup"}
        routes = (await s.exec(select(OrchestratorRoute).order_by(OrchestratorRoute.position))).all()
        assert [r.agent_id for r in routes] == [agents[s.slug].id for s in specialists()]  # general (dự phòng) cuối


async def test_specialists_hidden_from_normal_users_in_list_agents(api, aenv):
    user = await api.as_user("u@x.io")
    assert [a["slug"] for a in await api.get("agent.list_agents", user)] == ["assistant"]
    sup = await get_root(api)
    assert {a["slug"] for a in await api.get("agent.list_agents", sup)} == {"assistant"} | {
        s.slug for s in specialists()
    }


async def test_registered_specialist_is_seeded_with_route_once(app_env, registry_clean, tmp_path):
    register_specialist(make_seed(tmp_path))
    async with get_connections().postgres.rw() as s:
        made = await seed.seed_agents(s)
    assert made["specialists"] == ["extra"] and made["routes"] == 1
    async with get_connections().postgres.rw() as s:
        again = await seed.seed_agents(s)
    assert again["specialists"] == [] and again["routes"] == 0 and again["upgraded"] == []


async def _set_instructions(slug: str, text: str) -> None:
    async with get_connections().postgres.rw() as s:
        agent = (await s.exec(select(Agent).where(Agent.slug == slug))).one()
        agent.instructions = text
        s.add(agent)


async def _instructions(slug: str) -> str:
    async with get_connections().postgres.ro() as s:
        return (await s.exec(select(Agent).where(Agent.slug == slug))).one().instructions


async def test_old_instructions_upgraded_once_and_hand_edit_kept(app_env, registry_clean, tmp_path):
    old = "hướng dẫn cũ"
    spec = make_seed(tmp_path, previous_instructions=frozenset({sha(old)}))
    register_specialist(spec)
    async with get_connections().postgres.rw() as s:
        await seed.seed_agents(s)
    await _set_instructions("extra", old)
    async with get_connections().postgres.rw() as s:
        assert (await seed.seed_agents(s))["upgraded"] == ["extra:instructions"]
    assert await _instructions("extra") == seed.specialist_instructions(spec)
    async with get_connections().postgres.rw() as s:
        assert (await seed.seed_agents(s))["upgraded"] == []
    await _set_instructions("extra", old + " + sửa tay")
    async with get_connections().postgres.rw() as s:
        assert (await seed.seed_agents(s))["upgraded"] == []
    assert await _instructions("extra") == old + " + sửa tay"


async def test_old_toolsets_upgraded_and_custom_kept(app_env, registry_clean, tmp_path):
    spec = make_seed(tmp_path, toolsets=("lookup", "extra_ts"), previous_toolsets=(frozenset({"lookup"}),))
    register_specialist(spec)
    async with get_connections().postgres.rw() as s:
        await seed.seed_agents(s)
        agent = (await s.exec(select(Agent).where(Agent.slug == "extra"))).one()
        await s.exec(delete(AgentToolset).where(AgentToolset.agent_id == agent.id))
        s.add(AgentToolset(agent_id=agent.id, toolset="lookup"))
    async with get_connections().postgres.rw() as s:
        assert (await seed.seed_agents(s))["upgraded"] == ["extra"]
    async with get_connections().postgres.ro() as s:
        agent = (await s.exec(select(Agent).where(Agent.slug == "extra"))).one()
        sets = set((await s.exec(select(AgentToolset.toolset).where(AgentToolset.agent_id == agent.id))).all())
    assert sets == {"lookup", "extra_ts"}
    async with get_connections().postgres.rw() as s:  # bộ đã sửa tay (không khớp bản cũ) → giữ nguyên
        await s.exec(delete(AgentToolset).where(AgentToolset.agent_id == agent.id))
        s.add(AgentToolset(agent_id=agent.id, toolset="khac"))
    async with get_connections().postgres.rw() as s:
        assert (await seed.seed_agents(s))["upgraded"] == []


async def test_old_route_upgraded_once_and_edited_route_kept(app_env, registry_clean, tmp_path):
    old = ("Intent cũ", ("x",))
    spec = make_seed(tmp_path, previous_routes=(old,))
    register_specialist(spec)

    async def set_route(intent, examples):
        async with get_connections().postgres.rw() as s:
            agent = (await s.exec(select(Agent).where(Agent.slug == "extra"))).one()
            route = (await s.exec(select(OrchestratorRoute).where(OrchestratorRoute.agent_id == agent.id))).one()
            route.intent, route.examples = intent, list(examples)
            s.add(route)

    async with get_connections().postgres.rw() as s:
        await seed.seed_agents(s)
    await set_route(*old)
    async with get_connections().postgres.rw() as s:
        assert (await seed.seed_agents(s))["upgraded"] == ["extra:route"]
    async with get_connections().postgres.rw() as s:
        assert (await seed.seed_agents(s))["upgraded"] == []
    await set_route("Intent sửa tay", ("x",))
    async with get_connections().postgres.rw() as s:
        assert (await seed.seed_agents(s))["upgraded"] == []
