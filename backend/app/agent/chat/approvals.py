"""Yêu cầu duyệt tool `confirm`: một dòng mỗi tool call (UNIQUE `(run_id, tool_call_id)` — resume chạy
lại tool không tạo trùng), hết hạn sau 24 giờ. Quyết định đọc lại từ DB khi resume (nguồn sự thật)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import select

from app.agent.chat.models import AgentApproval, AgentRun
from app.core.connections.registry import get_connections

TTL = timedelta(hours=24)


async def get_or_create(
    run_id: uuid.UUID, agent_id: uuid.UUID, call_id: str, operation: str, args: dict[str, Any]
) -> tuple[AgentApproval, bool]:
    row = {
        "id": uuid.uuid4(),
        "tenant_id": select(AgentRun.tenant_id).where(AgentRun.id == run_id).scalar_subquery(),  # insert Core: tự gán
        "run_id": run_id,
        "tool_call_id": call_id,
        "agent_id": agent_id,
        "operation": operation,
        "args": args,
        "status": "pending",
        "expires_at": datetime.now(UTC) + TTL,
    }
    async with get_connections().postgres.rw() as session:
        stmt = (
            insert(AgentApproval)
            .values(row)
            .on_conflict_do_nothing(index_elements=["run_id", "tool_call_id"])
            .returning(AgentApproval.id)
        )
        created = (await session.exec(stmt)).first() is not None
        found = (
            await session.exec(
                select(AgentApproval).where(AgentApproval.run_id == run_id, AgentApproval.tool_call_id == call_id)
            )
        ).one()
        return found, created


async def reload(approval_id: uuid.UUID) -> AgentApproval:
    async with get_connections().postgres.rw() as session:
        return (await session.exec(select(AgentApproval).where(AgentApproval.id == approval_id))).one()


async def pending_count(run_id: uuid.UUID) -> int:
    async with get_connections().postgres.rw() as session:
        stmt = select(func.count()).where(AgentApproval.run_id == run_id, AgentApproval.status == "pending")
        return int((await session.exec(stmt)).one())


async def of_interrupts(interrupts) -> list[AgentApproval]:
    ids = [uuid.UUID(v["approval_id"]) for i in interrupts if isinstance(v := i.value, dict) and v.get("approval_id")]
    if not ids:
        return []
    async with get_connections().postgres.rw() as session:
        return list((await session.exec(select(AgentApproval).where(AgentApproval.id.in_(ids)))).all())


def refusal_text(a: AgentApproval) -> str:
    if a.status == "expired":
        return "Yêu cầu duyệt đã hết hạn — thao tác không chạy."
    reason = f": {a.reason}" if a.reason else ""
    return f"Người dùng đã từ chối thao tác này{reason}"
