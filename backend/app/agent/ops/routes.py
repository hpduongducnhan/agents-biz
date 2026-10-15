"""studio.* — route của orchestrator: chuyên gia đích + ý định + ví dụ cho router, thứ tự, bật / tắt."""

from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import func
from sqlmodel import select

from app.agent.config import registry
from app.agent.config.models import Agent
from app.agent.router.models import MAX_ROUTES, OrchestratorRoute
from app.core.errors import AppException
from app.core.operations.context import OpContext
from app.core.operations.spec import operation

REASON = "cấu hình agent — chỉ trên giao diện"
KEYS = ("studio.routes", "studio.agent")
Example = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class RouteOut(BaseModel):
    orchestrator_id: uuid.UUID
    agent_id: uuid.UUID
    slug: str
    name: str
    intent: str
    examples: list[str]
    position: int
    enabled: bool


class OrchestratorIn(BaseModel):
    orchestrator_id: uuid.UUID


class RouteKeyIn(OrchestratorIn):
    agent_id: uuid.UUID


class SaveRouteIn(RouteKeyIn):
    intent: str = Field(min_length=1, max_length=1000)
    examples: list[Example] = Field(default_factory=list, max_length=20)
    position: int = Field(default=0, ge=0, le=1000)
    enabled: bool = True


def route_out(r: OrchestratorRoute, a: Agent) -> RouteOut:
    return RouteOut(**r.model_dump(), slug=a.slug, name=a.name)


async def _orchestrator(ctx: OpContext, agent_id: uuid.UUID) -> Agent:
    a = await ctx.session.get(Agent, agent_id)
    if a is None or a.kind != "orchestrator":
        raise AppException(6003, status_code=404, detail="Orchestrator not found")
    return a


@operation(
    "studio.list_routes",
    title="Route của orchestrator",
    description="Chuyên gia đích + ý định + ví dụ, theo thứ tự",
    superadmin=True,
    agent_reason=REASON,
)
async def list_routes(ctx: OpContext, inp: OrchestratorIn) -> list[RouteOut]:
    await _orchestrator(ctx, inp.orchestrator_id)
    stmt = (
        select(OrchestratorRoute, Agent)
        .join(Agent, Agent.id == OrchestratorRoute.agent_id)
        .where(OrchestratorRoute.orchestrator_id == inp.orchestrator_id)
        .order_by(OrchestratorRoute.position, Agent.slug)
    )
    return [route_out(r, a) for r, a in (await ctx.session.exec(stmt)).all()]


@operation(
    "studio.save_route",
    title="Lưu route",
    description="Tạo / sửa route: chuyên gia đích (specialist), ý định, ví dụ, thứ tự, bật / tắt (≤ 20 route)",
    effect="write",
    superadmin=True,
    agent_reason=REASON,
    invalidates=KEYS,
)
async def save_route(ctx: OpContext, inp: SaveRouteIn) -> RouteOut:
    await _orchestrator(ctx, inp.orchestrator_id)
    target = await ctx.session.get(Agent, inp.agent_id)
    if target is None or target.kind != "specialist":
        raise AppException(1002, status_code=422, detail="Route target must be a specialist agent")
    row = await ctx.session.get(OrchestratorRoute, (inp.orchestrator_id, inp.agent_id))
    if row is None:
        count = (
            await ctx.session.exec(select(func.count()).where(OrchestratorRoute.orchestrator_id == inp.orchestrator_id))
        ).one()
        if count >= MAX_ROUTES:
            raise AppException(1002, status_code=422, detail=f"At most {MAX_ROUTES} routes")
        row = OrchestratorRoute(orchestrator_id=inp.orchestrator_id, agent_id=inp.agent_id)
    row.intent, row.examples, row.position, row.enabled = inp.intent, list(inp.examples), inp.position, inp.enabled
    ctx.session.add(row)
    await ctx.session.flush()
    await registry.bump(ctx.redis)
    return route_out(row, target)


@operation(
    "studio.delete_route",
    title="Xoá route",
    description="Bỏ một chuyên gia khỏi router",
    effect="destructive",
    superadmin=True,
    agent_reason=REASON,
    invalidates=KEYS,
)
async def delete_route(ctx: OpContext, inp: RouteKeyIn) -> None:
    row = await ctx.session.get(OrchestratorRoute, (inp.orchestrator_id, inp.agent_id))
    if row is None:
        raise AppException(1001, status_code=404, detail="Route not found")
    await ctx.session.delete(row)
    await ctx.session.flush()
    await registry.bump(ctx.redis)
