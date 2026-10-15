"""Span trace của agent (R13 — discriminated union theo `kind`): `run` → `llm` → `tool` → `approval`, `hook`. Ghi Mongo
`agent_spans` qua `TraceSink` (R12); TTL theo `expire_at`."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter

SpanStatus = Literal["running", "ok", "error", "waiting", "cancelled"]


def _now() -> datetime:
    return datetime.now(UTC)


class SpanBase(BaseModel):
    id: str
    run_id: str
    parent_id: str | None = None
    name: str
    seq: int = 0
    agent_id: str
    session_id: str
    user_id: str
    tenant_id: str | None = None  # tenant của người chat (D22) — span cũ không có
    cid: str | None = None
    status: SpanStatus = "running"
    error: str | None = None
    start: datetime = Field(default_factory=_now)
    end: datetime | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    expire_at: datetime


class RunSpan(SpanBase):
    kind: Literal["run"] = "run"
    usage: dict[str, int] = Field(default_factory=dict)
    # ghi khi lượt kết thúc; lượt cũ không có
    agents: list[str] = Field(default_factory=list)  # chuỗi slug: router → chuyên gia
    models: list[str] = Field(default_factory=list)
    cost: float | None = None  # USD ước tính
    llm_errors: int = 0


class LlmSpan(SpanBase):
    kind: Literal["llm"] = "llm"
    usage: dict[str, int] = Field(default_factory=dict)
    ttft_ms: int | None = None
    raw_ids: list[str] = Field(default_factory=list)
    credential_id: str | None = None
    masked_hint: str | None = None
    cost: float | None = None  # USD ước tính
    error_kind: str | None = None  # rate | auth | server | other


class ToolSpan(SpanBase):
    kind: Literal["tool"] = "tool"


class ApprovalSpan(SpanBase):
    kind: Literal["approval"] = "approval"


class HookSpan(SpanBase):
    kind: Literal["hook"] = "hook"


class RouterSpan(SpanBase):
    """Bước router: input = tin nhắn + route; output = quyết định, `fallback` khi rơi về `general`."""

    kind: Literal["router"] = "router"


class AgentStepSpan(SpanBase):
    """Một bước chuyên gia trong lượt có router: input = `{agent_id, slug, task, via}`."""

    kind: Literal["agent"] = "agent"


Span = Annotated[
    RunSpan | LlmSpan | ToolSpan | ApprovalSpan | HookSpan | RouterSpan | AgentStepSpan, Field(discriminator="kind")
]
SPAN = TypeAdapter(Span)


class HttpRaw(BaseModel):
    id: str
    span_id: str
    run_id: str
    method: str = ""
    url: str = ""
    started_at: str = ""
    ms: float | None = None
    request: dict[str, Any] = Field(default_factory=dict)
    response: dict[str, Any] | None = None
    error: str | None = None
    expire_at: datetime
