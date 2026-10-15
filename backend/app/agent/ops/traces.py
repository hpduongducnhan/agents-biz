"""traces.* — superadmin xem trace agent (D22): danh sách lượt (span `run`), cây span của lượt, raw HTTP tới provider.
Đọc qua `TraceSink` (R12); Mongo tắt → 200 `enabled: false` để UI hiện banner (như event log)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlmodel import select

from app.agent.config.models import Agent
from app.agent.trace.spans import SPAN, HttpRaw, RunSpan, Span
from app.auth.models import User
from app.core.operations.context import OpContext
from app.core.operations.pagination import Page, PageIn
from app.core.operations.spec import operation
from app.observability.sinks import get_sinks
from app.tenants.models import Tenant

REASON = "trace agent — chỉ superadmin trên giao diện"


class TracesIn(PageIn):
    agent_id: uuid.UUID | None = None
    tenant_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    status: Literal["running", "ok", "error", "waiting", "cancelled"] | None = None
    since: datetime | None = None
    until: datetime | None = None
    has_error: bool | None = Field(default=None, description="true = lượt lỗi hoặc có lần gọi LLM lỗi")
    model: str | None = Field(default=None, max_length=200, description="mã model phía provider")


class TracePage(Page[RunSpan]):
    enabled: bool = True
    names: dict[str, str] = Field(default_factory=dict)  # "user:<id>" / "agent:<id>" / "tenant:<id>" → tên


class RunIdIn(BaseModel):
    run_id: uuid.UUID


class TraceTree(BaseModel):
    enabled: bool = True
    spans: list[Span] = []


class RawIn(RunIdIn):
    raw_id: str


class RawOut(BaseModel):
    enabled: bool = True
    item: HttpRaw | None = None


def query_of(inp: TracesIn) -> dict:
    q: dict = {}
    for name in ("agent_id", "tenant_id", "user_id", "session_id"):
        if (value := getattr(inp, name)) is not None:
            q[name] = str(value)
    if inp.status:
        q["status"] = inp.status
    window = {k: v for k, v in (("$gte", inp.since), ("$lt", inp.until)) if v is not None}
    if window:
        q["start"] = window
    if inp.has_error is True:
        q["$or"] = [{"status": "error"}, {"llm_errors": {"$gt": 0}}]
    elif inp.has_error is False:
        q["status"] = q.get("status") or {"$ne": "error"}
        q["llm_errors"] = {"$in": [0, None]}
    if inp.model:
        q["models"] = inp.model
    return q


def _ids(values: set[str]) -> list[uuid.UUID]:
    out = []
    for v in values:
        try:
            out.append(uuid.UUID(v))
        except ValueError:
            continue
    return out


async def names_of(session, items: list[RunSpan]) -> dict[str, str]:
    """Tên user (người chat), tổ chức và agent của các lượt trong trang — UI không phải tra từng id."""
    users = {i.user_id for i in items}
    agents = {i.agent_id for i in items}
    tenants = {i.tenant_id for i in items if i.tenant_id}
    out: dict[str, str] = {}
    if tenants:
        for t in await session.exec(select(Tenant).where(Tenant.id.in_(_ids(tenants)))):
            out[f"tenant:{t.id}"] = t.name
    if users:
        for u in await session.exec(select(User).where(User.id.in_(_ids(users)))):
            out[f"user:{u.id}"] = u.name or u.email
    if agents:
        for a in await session.exec(select(Agent).where(Agent.id.in_(_ids(agents)))):
            out[f"agent:{a.id}"] = a.name
    return out


@operation(
    "traces.list",
    title="Trace agent",
    description="Superadmin: lượt chạy gần đây (span run) — lọc agent, tổ chức, user, phiên, trạng thái, thời gian, "
    "có lỗi, model",
    superadmin=True,
    agent_reason=REASON,
)
async def list_traces(ctx: OpContext, inp: TracesIn) -> TracePage:
    sink = get_sinks().traces
    if not sink.enabled:
        return TracePage(enabled=False, items=[], total=0, limit=inp.limit, offset=inp.offset)
    docs, total = await sink.list_runs(query_of(inp), limit=inp.limit, offset=inp.offset)
    items = [RunSpan.model_validate(d) for d in docs]
    names = await names_of(ctx.session, items)
    return TracePage(items=items, total=total, limit=inp.limit, offset=inp.offset, names=names)


@operation(
    "traces.get",
    title="Cây span của lượt",
    description="Superadmin: run → llm → tool → approval / hook theo thứ tự",
    superadmin=True,
    agent_reason=REASON,
)
async def get_trace(ctx: OpContext, inp: RunIdIn) -> TraceTree:
    sink = get_sinks().traces
    if not sink.enabled:
        return TraceTree(enabled=False)
    return TraceTree(spans=[SPAN.validate_python(d) for d in await sink.spans_of(str(inp.run_id))])


@operation(
    "traces.raw",
    title="Raw HTTP tới provider",
    description="Superadmin: request / response nguyên văn (đã che header + trường bí mật) của một span llm",
    superadmin=True,
    agent_reason=REASON,
)
async def get_raw(ctx: OpContext, inp: RawIn) -> RawOut:
    sink = get_sinks().traces
    if not sink.enabled:
        return RawOut(enabled=False)
    doc = await sink.get_raw(str(inp.run_id), inp.raw_id)
    return RawOut(item=HttpRaw.model_validate(doc) if doc else None)
