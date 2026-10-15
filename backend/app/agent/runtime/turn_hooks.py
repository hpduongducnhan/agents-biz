"""Hook mức lượt: `before_run` (chặn → 6019, `add_context`) trước khi gọi LLM; `after_run`
(notify / webhook) khi lượt kết thúc — lỗi chỉ log."""

from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage
from sqlmodel import select

from app.agent.chat.models import AgentRun
from app.agent.hooks import engine
from app.agent.runtime.tools import RunContext
from app.core.connections.registry import get_connections
from app.core.errors import AppException
from app.core.logging import get_logger

logger = get_logger(__name__)


async def before_run(rc: RunContext, text: str) -> None:
    if not rc.spec.hooks:
        return
    data = {
        "user": rc.user,
        "agent": {"id": str(rc.spec.id), "slug": rc.spec.agent.slug},
        "message": {"text": text},
        "session": {"id": str(rc.session_id)},
    }
    out = await engine.run("before_run", rc.spec.hooks, data, tracer=rc.tracer, run_id=rc.run_id)
    if out.blocked:
        raise AppException(6019, status_code=403, detail=out.message)
    rc.extra_context.extend(out.context)


async def after_run(rc: RunContext | None, status: str, totals, produced: list[BaseMessage]) -> None:
    """Hook `after_run` (chỉ notify / webhook) — lỗi chỉ log, lượt đã kết thúc."""
    if rc is None or not rc.spec.hooks:
        return
    try:
        async with get_connections().postgres.ro() as s:
            cost = (await s.exec(select(AgentRun.cost).where(AgentRun.id == rc.run_id))).first()
        tools = [c["name"] for m in produced if isinstance(m, AIMessage) for c in m.tool_calls]
        data = {
            "user": rc.user,
            "agent": {"id": str(rc.spec.id), "slug": rc.spec.agent.slug},
            "run": {"id": str(rc.run_id), "status": status, "tokens": dict(totals), "cost": cost, "tools": tools},
        }
        await engine.run("after_run", rc.spec.hooks, data, tracer=rc.tracer, run_id=rc.run_id)
    except Exception as exc:  # noqa: BLE001 — hook sau lượt hỏng không đổi kết quả lượt
        logger.warning("hook after_run run=%s lỗi: %s", rc.run_id, exc, extra={"loc": "agt0705"})
