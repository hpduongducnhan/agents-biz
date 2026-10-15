"""Cấu hình agent đọc thành `AgentSpec` bất biến cho một lượt chạy. Cache trong process theo phiên bản `bw:agentcfg:v`
(INCR mỗi lần Studio ghi + broadcast `agent.config_changed` — cache có TTL theo phiên bản nên lỡ broadcast vẫn đúng)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlmodel import select

from app.agent.config.models import (
    Agent,
    AgentHook,
    AgentKey,
    AgentLimit,
    AgentModel,
    AgentProvider,
    AgentSystemPrompt,
    AgentToolOverride,
    AgentToolset,
)
from app.agent.router.models import OrchestratorRoute
from app.core.logging import get_logger
from app.core.messaging.broadcast import broadcast, on_broadcast
from app.core.rkeys import rkey

logger = get_logger(__name__)
VERSION_KEY = rkey("agentcfg", "v")
CHANGED = "agent.config_changed"
_cache: dict[uuid.UUID, tuple[str, AgentSpec]] = {}


@dataclass(frozen=True)
class RouteSpec:
    agent_id: uuid.UUID
    slug: str
    name: str
    intent: str
    examples: tuple[str, ...]
    position: int


@dataclass(frozen=True)
class AgentSpec:
    agent: Agent
    model: AgentModel | None
    provider: AgentProvider | None
    key_ids: tuple[uuid.UUID, ...]
    limits: AgentLimit | None
    toolsets: frozenset[str]
    overrides: dict[str, AgentToolOverride] = field(default_factory=dict)
    hooks: tuple[AgentHook, ...] = ()
    persona: str = ""
    routes: tuple[RouteSpec, ...] = ()

    @property
    def id(self) -> uuid.UUID:
        return self.agent.id

    @property
    def is_orchestrator(self) -> bool:
        return self.agent.kind == "orchestrator"


async def version(redis) -> str:
    try:
        return str(await redis.rw.get(VERSION_KEY) or "0") if redis is not None else "0"
    except Exception as exc:  # noqa: BLE001 — Redis lỗi: đọc DB mỗi lần, không làm hỏng lượt chạy
        logger.warning("đọc phiên bản cấu hình agent lỗi: %s", exc, extra={"loc": "agt0001"})
        return "nocache"


async def bump(redis) -> None:
    if redis is not None:
        await redis.rw.incr(VERSION_KEY)
    _cache.clear()
    try:
        await broadcast(CHANGED, {})
    except Exception as exc:  # noqa: BLE001 — cache theo phiên bản đã đổi; broadcast chỉ để xoá sớm
        logger.warning("broadcast %s lỗi: %s", CHANGED, exc, extra={"loc": "agt0002"})


@on_broadcast(CHANGED)
async def on_changed(data: dict) -> None:
    _cache.clear()


async def _read(session, agent: Agent) -> AgentSpec:
    model = await session.get(AgentModel, agent.model_id) if agent.model_id else None
    provider = await session.get(AgentProvider, model.provider_id) if model is not None else None
    keys = (
        await session.exec(
            select(AgentKey.credential_id).where(AgentKey.agent_id == agent.id, AgentKey.enabled.is_(True))
        )
    ).all()
    toolsets = (await session.exec(select(AgentToolset.toolset).where(AgentToolset.agent_id == agent.id))).all()
    overrides = (await session.exec(select(AgentToolOverride).where(AgentToolOverride.agent_id == agent.id))).all()
    hooks = (
        await session.exec(
            select(AgentHook)
            .where(AgentHook.agent_id == agent.id, AgentHook.enabled.is_(True))
            .order_by(AgentHook.position, AgentHook.created_at)
        )
    ).all()
    persona = await session.get(AgentSystemPrompt, "persona")
    routes: tuple[RouteSpec, ...] = ()
    if agent.kind == "orchestrator":
        rows = (
            await session.exec(
                select(OrchestratorRoute, Agent)
                .join(Agent, Agent.id == OrchestratorRoute.agent_id)
                .where(
                    OrchestratorRoute.orchestrator_id == agent.id,
                    OrchestratorRoute.enabled.is_(True),
                    Agent.is_active.is_(True),
                )
                .order_by(OrchestratorRoute.position, Agent.slug)
            )
        ).all()
        routes = tuple(
            RouteSpec(a.id, a.slug, a.name, r.intent, tuple(str(x) for x in r.examples or []), r.position)
            for r, a in rows
        )
    return AgentSpec(
        agent=agent,
        model=model,
        provider=provider,
        key_ids=tuple(sorted(keys, key=str)),
        limits=await session.get(AgentLimit, agent.id),
        toolsets=frozenset(toolsets),
        overrides={o.operation: o for o in overrides},
        hooks=tuple(hooks),
        persona=persona.content if persona is not None and agent.persona_shared else "",
        routes=routes,
    )


async def load(session, redis, agent_id: uuid.UUID) -> AgentSpec | None:
    v = await version(redis)
    hit = _cache.get(agent_id)
    if hit is not None and hit[0] == v and v != "nocache":
        return hit[1]
    agent = await session.get(Agent, agent_id)
    if agent is None:
        return None
    spec = await _read(session, agent)
    _cache[agent_id] = (v, spec)
    return spec


async def by_slug(session, redis, slug: str) -> AgentSpec | None:
    agent = (await session.exec(select(Agent).where(Agent.slug == slug))).first()
    return await load(session, redis, agent.id) if agent is not None else None
