"""Token + chi phí của một lần gọi LLM (giá model lúc gọi, USD / 1 triệu token) và cộng chi phí vào `agent_runs.cost`.
Usage giám sát: mỗi lần gọi một document Mongo `agent_llm_calls` do Tracer ghi."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import update

from app.agent.chat.models import AgentRun
from app.agent.config.models import AgentModel
from app.core.connections.registry import get_connections

MILLION = Decimal(1_000_000)


def tokens_of(used: dict[str, Any]) -> dict[str, int]:
    """`usage_metadata` → 4 bộ đếm. `input_tokens` của LangChain đã gồm phần cache — tách ra để tính giá."""
    details = used.get("input_token_details") or {}
    cache_read = int(details.get("cache_read") or 0)
    cache_write = int(details.get("cache_creation") or 0)
    return {
        "input_tokens": max(0, int(used.get("input_tokens") or 0) - cache_read - cache_write),
        "output_tokens": int(used.get("output_tokens") or 0),
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
    }


def cost_of(model: AgentModel, t: dict[str, int]) -> Decimal:
    total = (
        t["input_tokens"] * Decimal(model.input_price_per_1m)
        + t["output_tokens"] * Decimal(model.output_price_per_1m)
        + t["cache_read_tokens"] * Decimal(model.cache_read_price_per_1m)
        + t["cache_write_tokens"] * Decimal(model.cache_write_price_per_1m)
    )
    return (total / MILLION).quantize(Decimal("0.000001"))


async def add_run_cost(run_id: uuid.UUID, cost: Decimal) -> None:
    """Cộng chi phí ước tính vào `agent_runs.cost` (hook `after_run` đọc). Usage giám sát ghi Mongo."""
    if not cost:
        return
    async with get_connections().postgres.rw() as session:
        await session.exec(update(AgentRun).where(AgentRun.id == run_id).values(cost=AgentRun.cost + cost))
