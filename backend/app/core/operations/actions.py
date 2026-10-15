"""Danh mục action cho agent: mọi @operation `agent=True` mà principal được phép; gọi = run_operation với
source="agent" — cùng kiểm quyền, cùng event log với web."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.core.errors import AppException
from app.core.operations.registry import all_specs, get_spec
from app.core.operations.runner import is_allowed, run_operation
from app.core.operations.spec import OperationSpec
from app.core.security.principal import Principal


@dataclass(frozen=True)
class ActionInfo:
    name: str
    title: str
    description: str
    effect: str
    toolset: str
    agent_hint: str | None
    permission: str | None
    superadmin: bool
    input_schema: dict


def action_info(spec: OperationSpec) -> ActionInfo:
    return ActionInfo(
        name=spec.name,
        title=spec.title,
        description=spec.description,
        effect=spec.effect,
        toolset=spec.toolset or "",
        agent_hint=spec.agent_hint,
        permission=spec.permission,
        superadmin=spec.superadmin,
        input_schema=spec.input_schema(),
    )


def list_actions(principal: Principal) -> list[ActionInfo]:
    """Action agent dùng được dưới `principal` — quyền nhóm kiểm lúc gọi (cần input)."""
    return [action_info(s) for s in all_specs() if s.agent and is_allowed(s, principal)]


async def call_action(name: str, principal: Principal, args: dict | None, *, agent_run_id: uuid.UUID | None) -> Any:
    spec = get_spec(name)
    if spec is None or not spec.agent:
        raise AppException(1001, status_code=404, detail=f"Không có action '{name}'")
    return await run_operation(name, principal, args, source="agent", agent_run_id=agent_run_id)
