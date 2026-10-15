"""Dạng trả về của Studio + luật cấu hình: key thuộc provider của model, override hợp op, hook hợp điểm móc."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlmodel import select

from app.agent.config.models import Agent, AgentHook, AgentKey, AgentLimit, AgentModel, AgentToolOverride, AgentToolset
from app.agent.config.toolsets import toolsets
from app.agent.hooks.schemas import ALLOWED, MAX_CONDITIONS, Condition, HookAction
from app.core.errors import AppException
from app.core.operations.registry import get_spec
from app.credentials.models import Credential


class KeyOut(BaseModel):
    credential_id: uuid.UUID
    name: str
    masked_hint: str
    weight: int
    enabled: bool
    status: str


class LimitsOut(BaseModel):
    per_minute: int | None = None
    per_hour: int | None = None
    per_day: int | None = None
    tokens_per_day: int | None = None


class OverrideOut(BaseModel):
    operation: str
    policy: str | None
    locked_params: dict
    default_params: dict


class AgentOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    kind: str
    description: str
    instructions: str
    persona_shared: bool
    starters: list
    model_id: uuid.UUID | None
    model_name: str | None
    params_override: dict
    recursion_limit: int
    timeout_sec: int
    key_strategy: str
    key_cooldown_sec: int
    visible_to: str
    visible_roles: list
    is_active: bool
    keys: list[KeyOut]
    limits: LimitsOut
    toolsets: list[str]
    overrides: list[OverrideOut]
    hooks_count: int
    warnings: list[str]


async def agent_out(session, a: Agent) -> AgentOut:
    model = await session.get(AgentModel, a.model_id) if a.model_id else None
    rows = (
        await session.exec(
            select(AgentKey, Credential)
            .join(Credential, Credential.id == AgentKey.credential_id)
            .where(AgentKey.agent_id == a.id)
        )
    ).all()
    keys = [
        KeyOut(
            credential_id=c.id,
            name=c.name,
            masked_hint=c.masked_hint,
            weight=c.weight,
            enabled=k.enabled,
            status=c.status,
        )
        for k, c in rows
    ]
    limits = await session.get(AgentLimit, a.id)
    toolsets = sorted((await session.exec(select(AgentToolset.toolset).where(AgentToolset.agent_id == a.id))).all())
    overrides = (await session.exec(select(AgentToolOverride).where(AgentToolOverride.agent_id == a.id))).all()
    hooks = (await session.exec(select(AgentHook.id).where(AgentHook.agent_id == a.id))).all()
    warnings = []
    if model is None:
        warnings.append("no_model")
    if not any(k.enabled and k.status == "active" for k in keys):
        warnings.append("no_key")
    if model is not None and any(c.provider_id not in (None, model.provider_id) for _, c in rows):
        warnings.append("key_provider_mismatch")
    return AgentOut(
        **a.model_dump(
            include={
                "id",
                "slug",
                "name",
                "kind",
                "description",
                "instructions",
                "persona_shared",
                "starters",
                "model_id",
                "params_override",
                "recursion_limit",
                "timeout_sec",
                "key_strategy",
                "key_cooldown_sec",
                "visible_to",
                "visible_roles",
                "is_active",
            }
        ),  # fmt: skip
        model_name=model.name if model is not None else None,
        keys=keys,
        limits=LimitsOut.model_validate(limits, from_attributes=True) if limits else LimitsOut(),
        toolsets=toolsets,
        overrides=[OverrideOut.model_validate(o, from_attributes=True) for o in overrides],
        hooks_count=len(hooks),
        warnings=warnings,
    )


async def check_keys(session, model_id: uuid.UUID | None, credential_ids: list[uuid.UUID]) -> None:
    model = await session.get(AgentModel, model_id) if model_id else None
    creds = (
        (await session.exec(select(Credential).where(Credential.id.in_(credential_ids)))).all()
        if credential_ids
        else []
    )
    if len(creds) != len(set(credential_ids)):
        raise AppException(1001, status_code=404, detail="Credential not found")
    mismatch = [str(c.id) for c in creds if model is not None and c.provider_id not in (None, model.provider_id)]
    if mismatch:
        raise AppException(6020, status_code=422, data={"mismatch": mismatch})


def check_toolsets(names: list[str]) -> list[str]:
    known = toolsets()
    unknown = [n for n in names if n not in known]
    if unknown:
        raise AppException(
            1002,
            status_code=422,
            data=[{"loc": ["toolsets"], "msg": f"unknown toolset {unknown}", "type": "value_error"}],
        )
    return sorted(set(names))


def check_override(operation: str, toolsets: list[str], locked: dict[str, Any], defaults: dict[str, Any]) -> None:
    spec = get_spec(operation)
    if spec is None or not spec.agent or spec.toolset not in toolsets:
        raise AppException(
            1002,
            status_code=422,
            data=[{"loc": ["operation"], "msg": "not a tool of this agent", "type": "value_error"}],
        )
    if spec.input_model is None:
        return
    fields = set(spec.input_model.model_fields)
    extra = sorted((set(locked) | set(defaults)) - fields)
    if extra:
        raise AppException(
            1002, status_code=422, data=[{"loc": ["params"], "msg": f"unknown params {extra}", "type": "value_error"}]
        )
    for name, value in {**defaults, **locked}.items():
        try:
            spec.input_model.__pydantic_validator__.validate_assignment(spec.input_model.model_construct(), name, value)
        except ValidationError as exc:
            raise AppException(1002, status_code=422, data=exc.errors(include_url=False)) from exc


def check_hook(point: str, conditions: list[dict], action: dict) -> tuple[list[dict], dict]:
    if len(conditions) > MAX_CONDITIONS:
        raise AppException(6017, status_code=422, detail=f"At most {MAX_CONDITIONS} conditions")
    try:
        conds = [Condition.model_validate(c).model_dump(mode="json") for c in conditions]
        parsed = HookActionHolder.model_validate({"value": action}).value
    except ValidationError as exc:
        raise AppException(6017, status_code=422, data=exc.errors(include_url=False)) from exc
    if parsed.action not in ALLOWED[point]:
        raise AppException(6017, status_code=422, detail=f"'{parsed.action}' is not allowed at {point}")
    return conds, parsed.model_dump(mode="json")


class HookActionHolder(BaseModel):
    value: HookAction
