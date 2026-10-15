"""studio.* — agent: lưu cấu hình, pool key, hạn mức (chung / theo user), toolset, override tool, danh mục tool."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.agent.config import registry
from app.agent.config.models import (
    Agent,
    AgentKey,
    AgentLimit,
    AgentModel,
    AgentToolOverride,
    AgentToolset,
    AgentUserLimit,
)
from app.agent.config.service import AgentOut, agent_out, check_keys, check_override, check_toolsets
from app.agent.config.toolsets import default_policy, ops_of, toolsets
from app.core.errors import AppException
from app.core.operations.context import OpContext
from app.core.operations.spec import operation
from app.credentials.models import Credential

REASON = "cấu hình agent — chỉ trên giao diện"
KEYS = ("studio.agents", "studio.agent", "agent.agents")
Slug = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class SaveAgentIn(BaseModel):
    agent_id: uuid.UUID | None = None
    slug: Slug
    name: Name
    kind: Literal["specialist", "orchestrator"] = "specialist"
    description: str = Field(default="", max_length=2000)
    instructions: str = Field(default="", max_length=60000)
    persona_shared: bool = True
    starters: list[str] = Field(default_factory=list, max_length=8)
    model_id: uuid.UUID | None = None
    params_override: dict = Field(default_factory=dict)
    recursion_limit: int = Field(default=25, ge=3, le=200)
    timeout_sec: int = Field(default=90, ge=10, le=900)
    key_strategy: Literal["round_robin", "auto"] = "round_robin"
    key_cooldown_sec: int = Field(default=300, ge=10, le=86400)
    visible_to: Literal["all", "roles"] = "all"
    visible_roles: list[str] = Field(default_factory=list, max_length=50)
    is_active: bool = True


class AgentIdIn(BaseModel):
    agent_id: uuid.UUID


class KeyIn(BaseModel):
    credential_id: uuid.UUID
    enabled: bool = True


class SetKeysIn(AgentIdIn):
    keys: list[KeyIn] = Field(max_length=50)


class LimitsIn(BaseModel):
    per_minute: int | None = Field(default=None, ge=1)
    per_hour: int | None = Field(default=None, ge=1)
    per_day: int | None = Field(default=None, ge=1)
    tokens_per_day: int | None = Field(default=None, ge=1)


class SetLimitsIn(AgentIdIn, LimitsIn):
    pass


class SetUserLimitIn(AgentIdIn, LimitsIn):
    user_id: uuid.UUID
    remove: bool = False


class SetToolsetsIn(AgentIdIn):
    toolsets: list[str] = Field(max_length=20)


class SetOverrideIn(AgentIdIn):
    operation: str = Field(max_length=128)
    policy: Literal["auto", "confirm", "deny"] | None = None
    locked_params: dict = Field(default_factory=dict)
    default_params: dict = Field(default_factory=dict)
    remove: bool = False


class ToolOut(BaseModel):
    name: str
    title: str
    description: str
    effect: str
    default_policy: str


class ToolsetOut(BaseModel):
    toolset: str
    description: str
    ops: list[ToolOut]


def _studio(name: str, title: str, description: str, effect: str = "write"):
    return operation(name, title=title, description=description, effect=effect, superadmin=True, agent_reason=REASON,
                     invalidates=KEYS)  # fmt: skip


async def _agent(ctx: OpContext, agent_id: uuid.UUID) -> Agent:
    a = await ctx.session.get(Agent, agent_id)
    if a is None:
        raise AppException(6003, status_code=404)
    return a


async def _done(ctx: OpContext, a: Agent) -> AgentOut:
    try:
        async with ctx.session.begin_nested():
            await ctx.session.flush()
    except IntegrityError as exc:
        raise AppException(1006, status_code=409, detail="Agent slug already exists") from exc
    await registry.bump(ctx.redis)
    return await agent_out(ctx.session, a)


@operation("studio.list_agents", title="Agent", description="Mọi agent + cảnh báo cấu hình", superadmin=True)
async def list_agents(ctx: OpContext) -> list[AgentOut]:
    rows = (await ctx.session.exec(select(Agent).order_by(Agent.kind.desc(), Agent.name))).all()
    return [await agent_out(ctx.session, a) for a in rows]


@operation("studio.get_agent", title="Chi tiết agent", description="Cấu hình đầy đủ một agent", superadmin=True)
async def get_agent(ctx: OpContext, inp: AgentIdIn) -> AgentOut:
    return await agent_out(ctx.session, await _agent(ctx, inp.agent_id))


@_studio(
    "studio.save_agent", "Lưu agent", "Tạo / sửa agent: hướng dẫn, model, giới hạn bước / thời gian, chiến lược key"
)
async def save_agent(ctx: OpContext, inp: SaveAgentIn) -> AgentOut:
    a = await _agent(ctx, inp.agent_id) if inp.agent_id else Agent(slug=inp.slug, name=inp.name)
    if inp.model_id is not None and await ctx.session.get(AgentModel, inp.model_id) is None:
        raise AppException(1001, status_code=404, detail="Model not found")
    model_changed = a.model_id != inp.model_id
    for k, v in inp.model_dump(exclude={"agent_id"}).items():
        setattr(a, k, v)
    ctx.session.add(a)
    try:
        async with ctx.session.begin_nested():
            await ctx.session.flush()
    except IntegrityError as exc:
        raise AppException(1006, status_code=409, detail="Agent slug already exists") from exc
    if model_changed and inp.model_id is not None:  # bỏ key không còn thuộc provider của model mới
        model = await ctx.session.get(AgentModel, inp.model_id)
        rows = (await ctx.session.exec(select(AgentKey).where(AgentKey.agent_id == a.id))).all()
        for k in rows:
            cred = await ctx.session.get(Credential, k.credential_id)
            if cred is not None and cred.provider_id not in (None, model.provider_id):
                await ctx.session.delete(k)
    return await _done(ctx, a)


@_studio(
    "studio.set_agent_keys", "Gắn key cho agent", "Thay toàn bộ pool key của agent (key phải thuộc provider của model)"
)
async def set_agent_keys(ctx: OpContext, inp: SetKeysIn) -> AgentOut:
    a = await _agent(ctx, inp.agent_id)
    await check_keys(ctx.session, a.model_id, [k.credential_id for k in inp.keys])
    await ctx.session.exec(delete(AgentKey).where(AgentKey.agent_id == a.id))
    ctx.session.add_all(AgentKey(agent_id=a.id, credential_id=k.credential_id, enabled=k.enabled) for k in inp.keys)
    return await _done(ctx, a)


class ConfigureAllIn(BaseModel):
    model_id: uuid.UUID
    credential_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)


class ConfigureAllOut(BaseModel):
    agents: int


@_studio(
    "studio.configure_all",
    "Gắn model + key cho mọi agent",
    "Đặt cùng một model và pool key cho orchestrator + mọi chuyên gia (key phải thuộc provider của model)",
)
async def configure_all(ctx: OpContext, inp: ConfigureAllIn) -> ConfigureAllOut:
    if await ctx.session.get(AgentModel, inp.model_id) is None:
        raise AppException(1001, status_code=404, detail="Model not found")
    await check_keys(ctx.session, inp.model_id, inp.credential_ids)
    agents = (await ctx.session.exec(select(Agent))).all()
    for a in agents:
        a.model_id = inp.model_id
        ctx.session.add(a)
        await ctx.session.exec(delete(AgentKey).where(AgentKey.agent_id == a.id))
        ctx.session.add_all(
            AgentKey(agent_id=a.id, credential_id=c, enabled=True) for c in dict.fromkeys(inp.credential_ids)
        )
    await ctx.session.flush()
    await registry.bump(ctx.redis)
    return ConfigureAllOut(agents=len(agents))


@_studio("studio.set_agent_limits", "Hạn mức agent", "Số lượt / phút, giờ, ngày và trần token / ngày cho mỗi user")
async def set_agent_limits(ctx: OpContext, inp: SetLimitsIn) -> AgentOut:
    a = await _agent(ctx, inp.agent_id)
    row = await ctx.session.get(AgentLimit, a.id) or AgentLimit(agent_id=a.id)
    for k in ("per_minute", "per_hour", "per_day", "tokens_per_day"):
        setattr(row, k, getattr(inp, k))
    ctx.session.add(row)
    return await _done(ctx, a)


@_studio(
    "studio.set_user_limit", "Hạn mức riêng của user", "Ghi đè hạn mức của agent cho một user (remove = bỏ ghi đè)"
)
async def set_user_limit(ctx: OpContext, inp: SetUserLimitIn) -> AgentOut:
    a = await _agent(ctx, inp.agent_id)
    row = await ctx.session.get(AgentUserLimit, (a.id, inp.user_id))
    if inp.remove:
        if row is not None:
            await ctx.session.delete(row)
    else:
        row = row or AgentUserLimit(agent_id=a.id, user_id=inp.user_id)
        for k in ("per_minute", "per_hour", "per_day", "tokens_per_day"):
            setattr(row, k, getattr(inp, k))
        ctx.session.add(row)
    return await _done(ctx, a)


@_studio("studio.set_toolsets", "Toolset của agent", "Chọn các nhóm tool agent được dùng")
async def set_toolsets(ctx: OpContext, inp: SetToolsetsIn) -> AgentOut:
    a = await _agent(ctx, inp.agent_id)
    names = check_toolsets(inp.toolsets)
    await ctx.session.exec(delete(AgentToolset).where(AgentToolset.agent_id == a.id))
    ctx.session.add_all(AgentToolset(agent_id=a.id, toolset=n) for n in names)
    return await _done(ctx, a)


@_studio(
    "studio.set_tool_override",
    "Ghi đè tool",
    "Đổi chính sách (tự chạy / hỏi duyệt / cấm), khoá hoặc đặt mặc định tham số",
)
async def set_tool_override(ctx: OpContext, inp: SetOverrideIn) -> AgentOut:
    a = await _agent(ctx, inp.agent_id)
    row = await ctx.session.get(AgentToolOverride, (a.id, inp.operation))
    if inp.remove:
        if row is not None:
            await ctx.session.delete(row)
        return await _done(ctx, a)
    toolsets = list((await ctx.session.exec(select(AgentToolset.toolset).where(AgentToolset.agent_id == a.id))).all())
    check_override(inp.operation, toolsets, inp.locked_params, inp.default_params)
    row = row or AgentToolOverride(agent_id=a.id, operation=inp.operation)
    row.policy, row.locked_params, row.default_params = inp.policy, inp.locked_params, inp.default_params
    ctx.session.add(row)
    return await _done(ctx, a)


@operation(
    "studio.tool_catalog", title="Danh mục tool", description="Toolset và các op agent gọi được", superadmin=True
)
async def tool_catalog(ctx: OpContext) -> list[ToolsetOut]:
    return [
        ToolsetOut(
            toolset=name,
            description=desc,
            ops=[
                ToolOut(
                    name=s.name,
                    title=s.title,
                    description=s.description,
                    effect=s.effect,
                    default_policy=default_policy(s),
                )
                for s in ops_of(name)
            ],
        )
        for name, desc in toolsets().items()
    ]
