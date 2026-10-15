"""studio.* — hook vòng đời của agent (điều kiện + hành động) + chạy thử trên dữ liệu mẫu (`studio.test_hook`)."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field
from sqlmodel import select

from app.agent.config import registry
from app.agent.config.models import Agent, AgentHook
from app.agent.config.service import check_hook
from app.agent.hooks import engine
from app.agent.hooks.schemas import Point
from app.core.errors import AppException
from app.core.operations.context import OpContext
from app.core.operations.spec import operation

REASON = "cấu hình agent — chỉ trên giao diện"
KEYS = ("studio.hooks", "studio.agent")


class HookOut(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    name: str
    point: str
    conditions: list
    action: str
    action_config: dict
    position: int
    enabled: bool


class ListHooksIn(BaseModel):
    agent_id: uuid.UUID


class SaveHookIn(BaseModel):
    hook_id: uuid.UUID | None = None
    agent_id: uuid.UUID
    name: str = Field(default="", max_length=100)
    point: Point
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    action: dict[str, Any]
    position: int = Field(default=0, ge=0, le=1000)
    enabled: bool = True


class HookIdIn(BaseModel):
    hook_id: uuid.UUID


def out(h: AgentHook) -> HookOut:
    return HookOut.model_validate(h, from_attributes=True)


@operation("studio.list_hooks", title="Hook của agent", description="Hook theo điểm móc + thứ tự", superadmin=True)
async def list_hooks(ctx: OpContext, inp: ListHooksIn) -> list[HookOut]:
    stmt = select(AgentHook).where(AgentHook.agent_id == inp.agent_id).order_by(AgentHook.point, AgentHook.position)
    return [out(h) for h in (await ctx.session.exec(stmt)).all()]


@operation(
    "studio.save_hook",
    title="Lưu hook",
    description="Tạo / sửa hook: điểm móc, điều kiện (AND, ≤ 10), hành động",
    effect="write",
    superadmin=True,
    agent_reason=REASON,
    invalidates=KEYS,
)
async def save_hook(ctx: OpContext, inp: SaveHookIn) -> HookOut:
    if await ctx.session.get(Agent, inp.agent_id) is None:
        raise AppException(6003, status_code=404)
    conditions, action = check_hook(inp.point, inp.conditions, inp.action)
    h = (
        await ctx.session.get(AgentHook, inp.hook_id)
        if inp.hook_id
        else AgentHook(agent_id=inp.agent_id, point=inp.point, action="")
    )
    if h is None or h.agent_id != inp.agent_id:
        raise AppException(1001, status_code=404, detail="Hook not found")
    h.name, h.point, h.conditions, h.position, h.enabled = inp.name, inp.point, conditions, inp.position, inp.enabled
    h.action, h.action_config = action["action"], action
    ctx.session.add(h)
    await ctx.session.flush()
    await registry.bump(ctx.redis)
    return out(h)


@operation(
    "studio.delete_hook",
    title="Xoá hook",
    description="Xoá một hook",
    effect="destructive",
    superadmin=True,
    agent_reason=REASON,
    invalidates=KEYS,
)
async def delete_hook(ctx: OpContext, inp: HookIdIn) -> None:
    h = await ctx.session.get(AgentHook, inp.hook_id)
    if h is None:
        raise AppException(1001, status_code=404, detail="Hook not found")
    await ctx.session.delete(h)
    await ctx.session.flush()
    await registry.bump(ctx.redis)


class TestHookIn(BaseModel):
    point: Point
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    action: dict[str, Any]
    sample: dict[str, Any] = Field(default_factory=dict)


class TestHookOut(BaseModel):
    matched: bool
    blocked: bool
    message: str | None
    approval: bool
    context: list[str]
    results: list[dict[str, Any]]


@operation(
    "studio.test_hook",
    title="Chạy thử hook",
    http=("POST", "/studio/test_hook"),  # input lồng nhau (điều kiện, hành động, mẫu) — body JSON, không ghi gì
    description="Chạy hook trên dữ liệu mẫu — không gửi thông báo / webhook thật (trả request sẽ gửi)",
    superadmin=True,
    agent_reason=REASON,
)
async def test_hook(ctx: OpContext, inp: TestHookIn) -> TestHookOut:
    conditions, action = check_hook(inp.point, inp.conditions, inp.action)
    hook = AgentHook(
        id=uuid.UUID(int=0), agent_id=uuid.UUID(int=0), name="test", point=inp.point, conditions=conditions,
        action=action["action"], action_config=action,
    )  # fmt: skip
    out = await engine.run(inp.point, [hook], inp.sample, dry=True)
    return TestHookOut(
        matched=bool(out.results),
        blocked=out.blocked,
        message=out.message,
        approval=out.approval,
        context=out.context,
        results=out.results,
    )
