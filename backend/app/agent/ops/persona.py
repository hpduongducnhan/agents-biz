"""studio.get_persona / save_persona — "tính cách chung" ghép vào mọi agent có `persona_shared`."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.agent.config import registry
from app.agent.config.models import AgentSystemPrompt
from app.core.operations.context import OpContext
from app.core.operations.spec import operation


class PersonaOut(BaseModel):
    content: str
    updated_at: datetime | None


class SavePersonaIn(BaseModel):
    content: str = Field(max_length=20000)


@operation(
    "studio.get_persona", title="Persona chung", description="Phần tính cách chung của mọi agent", superadmin=True
)
async def get_persona(ctx: OpContext) -> PersonaOut:
    row = await ctx.session.get(AgentSystemPrompt, "persona")
    return PersonaOut(content=row.content if row else "", updated_at=row.updated_at if row else None)


@operation(
    "studio.save_persona",
    title="Lưu persona",
    description="Sửa phần tính cách chung (áp cho agent bật persona_shared)",
    effect="write",
    superadmin=True,
    agent_reason="cấu hình agent — chỉ trên giao diện",
    invalidates=("studio.persona",),
)
async def save_persona(ctx: OpContext, inp: SavePersonaIn) -> PersonaOut:
    row = await ctx.session.get(AgentSystemPrompt, "persona") or AgentSystemPrompt(key="persona")
    row.content = inp.content
    ctx.session.add(row)
    await ctx.session.flush()
    await registry.bump(ctx.redis)
    return PersonaOut(content=row.content, updated_at=row.updated_at)
