"""Bước sau migrate `agent.seed`: persona chung, orchestrator "Assistant" + chuyên gia đã đăng ký
(`register_specialist`) + route mặc định, chưa có model / key ở cài mới. Chạy lại không ghi đè nội dung superadmin đã
sửa (khớp theo `slug`, chỉ tạo cái thiếu); chuyên gia mới chép model + pool key của "Assistant" để chạy ngay."""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlmodel import select

from app.agent.config.models import Agent, AgentKey, AgentSystemPrompt, AgentToolset
from app.agent.config.seed_data import PREVIOUS_PERSONA, PROMPTS, SpecialistSeed, specialists
from app.agent.router.models import OrchestratorRoute
from app.core.logging import get_logger
from app.core.migrate import post_migrate_step
from app.core.settings import Settings

logger = get_logger(__name__)
ASSISTANT = "assistant"
STARTERS = ["Bạn giúp được tôi những gì?", "Tôi có thông báo nào mới không?", "Hướng dẫn tôi dùng app này"]


def prompt(name: str, folder: Path = PROMPTS) -> str:
    return (folder / f"{name}.md").read_text(encoding="utf-8").strip()


def specialist_instructions(seed: SpecialistSeed) -> str:
    return f"{prompt(seed.slug, seed.prompt_dir)}\n\n{prompt('_common')}"


async def _assistant(session, made: dict[str, object]) -> Agent:
    agent = (await session.exec(select(Agent).where(Agent.slug == ASSISTANT))).first()
    if agent is None:
        agent = Agent(
            slug=ASSISTANT,
            name="Assistant",
            kind="orchestrator",
            description="Điều phối: chọn chuyên gia cho từng tin nhắn",
            instructions=prompt("router"),
            starters=STARTERS,
        )
        session.add(agent)
        await session.flush()
        made["assistant"] = "created"
    return agent


async def _upgrade_toolsets(session, agent: Agent, seed: SpecialistSeed) -> bool:
    """Agent seed còn đúng bộ toolset của một bản seed cũ → đổi sang bộ mới; superadmin đã sửa thì giữ nguyên."""
    rows = (await session.exec(select(AgentToolset.toolset).where(AgentToolset.agent_id == agent.id))).all()
    current = frozenset(rows)
    if current == frozenset(seed.toolsets) or current not in seed.previous_toolsets:
        return False
    session.add_all(AgentToolset(agent_id=agent.id, toolset=t) for t in sorted(set(seed.toolsets) - current))
    await session.flush()
    return True


def _upgrade_instructions(session, agent: Agent, seed: SpecialistSeed) -> bool:
    """Hướng dẫn còn đúng một bản seed cũ → bản mới; superadmin đã sửa tay thì giữ và báo (bản seed mới chưa áp)."""
    old = seed.previous_instructions
    fresh = specialist_instructions(seed)
    if not old or agent.instructions == fresh:
        return False
    if hashlib.sha256(agent.instructions.encode()).hexdigest() not in old:
        logger.info("giữ hướng dẫn đã sửa tay của %s — bản seed mới chưa áp", seed.slug, extra={"loc": "agt0006"})
        return False
    agent.instructions = fresh
    session.add(agent)
    return True


def _upgrade_persona(session, row: AgentSystemPrompt) -> bool:
    """Persona chung còn đúng một bản seed cũ → bản mới; superadmin đã sửa ở Studio thì giữ và báo."""
    fresh = prompt("persona")
    if row.content.strip() == fresh:
        return False
    if hashlib.sha256(row.content.strip().encode()).hexdigest() not in PREVIOUS_PERSONA:
        logger.info("giữ persona đã sửa tay — bản seed mới chưa áp", extra={"loc": "agt0007"})
        return False
    row.content = fresh
    session.add(row)
    return True


def _upgrade_route(session, route: OrchestratorRoute, seed: SpecialistSeed) -> bool:
    """Ý định + ví dụ route còn đúng một bản seed cũ → bản mới; đã sửa ở Studio thì giữ nguyên."""
    current = (route.intent, tuple(route.examples))
    if current == (seed.intent, seed.examples) or current not in seed.previous_routes:
        return False
    route.intent, route.examples = seed.intent, list(seed.examples)
    session.add(route)
    return True


async def _specialist(session, seed: SpecialistSeed, source: Agent) -> Agent | None:
    if (await session.exec(select(Agent).where(Agent.slug == seed.slug))).first() is not None:
        return None
    agent = Agent(
        slug=seed.slug,
        name=seed.name,
        kind="specialist",
        description=seed.description,
        instructions=specialist_instructions(seed),
        visible_to="roles",
        visible_roles=[],
        model_id=source.model_id,
        key_strategy=source.key_strategy,
    )
    session.add(agent)
    await session.flush()
    session.add_all(AgentToolset(agent_id=agent.id, toolset=t) for t in seed.toolsets)
    keys = (await session.exec(select(AgentKey).where(AgentKey.agent_id == source.id))).all()
    session.add_all(AgentKey(agent_id=agent.id, credential_id=k.credential_id, enabled=k.enabled) for k in keys)
    return agent


async def seed_agents(session) -> dict[str, object]:
    made: dict[str, object] = {"persona": False, "assistant": None, "specialists": [], "routes": 0, "upgraded": []}
    persona = await session.get(AgentSystemPrompt, "persona")
    if persona is None:
        session.add(AgentSystemPrompt(key="persona", content=prompt("persona")))
        made["persona"] = True
    elif _upgrade_persona(session, persona):
        made["upgraded"].append("persona")  # type: ignore[union-attr]
    assistant = await _assistant(session, made)
    for position, seed in enumerate(specialists()):
        created = await _specialist(session, seed, assistant)
        if created is not None:
            made["specialists"].append(seed.slug)  # type: ignore[union-attr]
        else:
            existing = (await session.exec(select(Agent).where(Agent.slug == seed.slug))).one()
            if await _upgrade_toolsets(session, existing, seed):
                made["upgraded"].append(seed.slug)  # type: ignore[union-attr]
            if _upgrade_instructions(session, existing, seed):
                made["upgraded"].append(f"{seed.slug}:instructions")  # type: ignore[union-attr]
        if assistant.kind != "orchestrator":
            continue
        target = (await session.exec(select(Agent).where(Agent.slug == seed.slug))).one()
        route = await session.get(OrchestratorRoute, (assistant.id, target.id))
        if route is not None and _upgrade_route(session, route, seed):
            made["upgraded"].append(f"{seed.slug}:route")  # type: ignore[union-attr]
        if route is None:
            session.add(
                OrchestratorRoute(
                    orchestrator_id=assistant.id,
                    agent_id=target.id,
                    intent=seed.intent,
                    examples=list(seed.examples),
                    position=position,
                )
            )
            made["routes"] += 1  # type: ignore[operator]
    await session.flush()
    return made


@post_migrate_step("agent.seed", order=40)
async def seed_step(session, settings: Settings) -> dict[str, object]:
    made = await seed_agents(session)
    if made["persona"] or made["assistant"] or made["specialists"] or made["routes"] or made["upgraded"]:
        logger.info("seed agent: %s", made, extra={"loc": "agt0003"})
    return made
