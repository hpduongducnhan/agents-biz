"""`bw dump-chat-session` (R24): gom một phiên chat vào một JSON để debug — phiên, tin nhắn, lượt, yêu cầu duyệt
(Postgres), checkpoint LangGraph của lượt còn thread (schema `agent_lg`), span trace (Mongo qua `TraceSink`, nếu bật).
Chỉ đọc."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic_core import to_jsonable_python
from sqlmodel import select

from app.agent.chat.models import AgentApproval, AgentMessage, AgentRun, AgentSession
from app.agent.runtime import checkpoint
from app.core.connections.registry import get_connections
from app.observability.sinks import get_sinks


def _row(obj) -> dict[str, Any]:
    return obj.model_dump(mode="json")


async def _checkpoint(run_id: uuid.UUID) -> dict[str, Any] | None:
    saver = await checkpoint.get_checkpointer()
    if saver is None:
        return {"error": "checkpointer không dựng được"}
    found = await saver.aget_tuple({"configurable": {"thread_id": str(run_id)}})
    if found is None:
        return None
    return {
        "config": found.config,
        "metadata": found.metadata,
        "values": found.checkpoint.get("channel_values", {}),
        "pending_writes": found.pending_writes,
    }


async def dump_session(session_id: uuid.UUID) -> dict[str, Any]:
    async with get_connections().postgres.ro() as s:
        chat = await s.get(AgentSession, session_id)
        if chat is None:
            raise LookupError(f"không có phiên {session_id}")
        messages = (
            await s.exec(select(AgentMessage).where(AgentMessage.session_id == session_id).order_by(AgentMessage.seq))
        ).all()
        runs = (
            await s.exec(select(AgentRun).where(AgentRun.session_id == session_id).order_by(AgentRun.created_at))
        ).all()
        run_ids = [r.id for r in runs]
        approvals = (
            (
                await s.exec(
                    select(AgentApproval).where(AgentApproval.run_id.in_(run_ids)).order_by(AgentApproval.created_at)
                )
            ).all()
            if run_ids
            else []
        )
    sink = get_sinks().traces
    out_runs = []
    for r in runs:
        item = _row(r)
        item["checkpoint"] = await _checkpoint(r.id)
        item["spans"] = await sink.spans_of(str(r.id)) if sink.enabled else None
        out_runs.append(item)
    return to_jsonable_python(
        {
            "session": _row(chat),
            "messages": [_row(m) for m in messages],
            "runs": out_runs,
            "approvals": [_row(a) for a in approvals],
            "trace_enabled": sink.enabled,
        },
        fallback=str,
    )
