"""usage.* — superadmin giám sát LLM của agent: gộp document `agent_llm_calls` (Mongo, qua `TraceSink`) theo
provider / model / agent / nơi gọi / tổ chức / user / key / phiên / ngày / giờ, lọc chéo; danh sách lần gọi lỗi.
Mongo tắt → `enabled: false` (banner như trace)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel
from sqlmodel import select

from app.agent.chat.models import AgentSession
from app.agent.config.models import Agent, AgentModel, AgentProvider
from app.auth.models import User
from app.core.errors import AppException
from app.core.operations.context import OpContext
from app.core.operations.pagination import PageIn
from app.core.operations.spec import operation
from app.credentials.models import Credential
from app.observability.sinks import get_sinks
from app.tenants.models import Tenant

REASON = "giám sát LLM — chỉ superadmin trên giao diện"
MAX_DAYS = 400
MAX_ROWS = 200
GroupBy = Literal["provider", "model", "agent", "purpose", "tenant", "user", "key", "session", "day", "hour"]
ErrorKind = Literal["rate", "auth", "server", "other"]
KINDS = ("rate", "auth", "server", "other")
FIELD = {
    "provider": "$provider_id",
    "model": "$model_id",
    "agent": "$agent_id",
    "purpose": "$purpose",
    "tenant": {"$ifNull": ["$tenant_id", "none"]},
    "user": "$user_id",
    "key": {"$ifNull": ["$credential_id", "none"]},
    "session": "$session_id",
}
TIME_FORMAT = {"day": "%Y-%m-%d", "hour": "%Y-%m-%d %H:00"}
FILTERS = ("agent_id", "model_id", "provider_id", "tenant_id", "user_id", "credential_id", "session_id")
SUMS = ("requests", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "cost")


class UsageFilter(BaseModel):
    since: datetime | None = None
    until: datetime | None = None
    agent_id: uuid.UUID | None = None
    model_id: uuid.UUID | None = None
    provider_id: uuid.UUID | None = None
    tenant_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    credential_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    purpose: Literal["router", "agent"] | None = None


class SummaryIn(UsageFilter):
    group_by: GroupBy = "model"


class Prices(BaseModel):
    input: Decimal
    output: Decimal
    cache_read: Decimal
    cache_write: Decimal


class UsageRow(BaseModel):
    key: str
    name: str | None = None
    sub: str | None = None  # dòng phụ: loại provider / mã model / slug / email / gợi ý key
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost: float = 0.0
    errors: int = 0
    errors_rate: int = 0
    errors_auth: int = 0
    errors_server: int = 0
    errors_other: int = 0
    latency_avg_ms: int | None = None
    prices: Prices | None = None


class UsageSummary(BaseModel):
    enabled: bool = True
    since: datetime
    until: datetime
    group_by: str
    tz: str
    rows: list[UsageRow]
    total: UsageRow | None


class ErrorsIn(UsageFilter, PageIn):
    kind: ErrorKind | None = None


class LlmError(BaseModel):
    id: str
    at: datetime
    kind: str | None
    error: str | None
    run_id: str
    purpose: str | None
    agent: str | None
    model: str | None
    model_code: str | None
    provider_kind: str | None
    user: str | None
    key: str | None
    latency_ms: int | None


class ErrorPage(BaseModel):
    enabled: bool = True
    items: list[LlmError]
    total: int
    limit: int
    offset: int


def window(inp: UsageFilter) -> tuple[datetime, datetime]:
    until = inp.until or datetime.now(UTC)
    since = inp.since or until - timedelta(days=30)
    if until <= since:
        raise AppException(1002, status_code=422, detail="until must be after since")
    if until - since > timedelta(days=MAX_DAYS):
        raise AppException(1002, status_code=422, detail=f"window longer than {MAX_DAYS} days")
    return since, until


def match_of(inp: UsageFilter, since: datetime, until: datetime) -> dict[str, Any]:
    m: dict[str, Any] = {"at": {"$gte": since, "$lt": until}}
    for name in FILTERS:
        if (value := getattr(inp, name)) is not None:
            m[name] = str(value)
    if inp.purpose:
        m["purpose"] = inp.purpose
    return m


def _err(kind: str | None = None) -> dict[str, Any]:
    cond: list[Any] = [{"$eq": ["$status", "error"]}]
    if kind:
        cond.append({"$eq": ["$error_kind", kind]})
    return {"$sum": {"$cond": [{"$and": cond}, 1, 0]}}


def _sums() -> dict[str, Any]:
    out: dict[str, Any] = {c: {"$sum": f"${c}"} for c in SUMS}
    out["errors"] = _err()
    out.update({f"errors_{k}": _err(k) for k in KINDS})
    out["ok"] = {"$sum": {"$cond": [{"$eq": ["$status", "ok"]}, 1, 0]}}
    out["latency_ok"] = {"$sum": {"$cond": [{"$eq": ["$status", "ok"]}, "$latency_ms", 0]}}
    out["hint"] = {"$last": "$key_hint"}
    out["code"] = {"$last": "$model"}
    out["slug"] = {"$last": "$agent_slug"}
    out["pkind"] = {"$last": "$provider_kind"}
    return out


def pipeline(match: dict[str, Any], group_by: str, tz: str) -> list[dict[str, Any]]:
    timed = group_by in TIME_FORMAT
    key = (
        {"$dateToString": {"format": TIME_FORMAT[group_by], "date": "$at", "timezone": tz}}
        if timed
        else FIELD[group_by]
    )
    order = {"_id": 1} if timed else {"cost": -1, "requests": -1}
    return [
        {"$match": match},
        {
            "$facet": {
                "rows": [{"$group": {"_id": key, **_sums()}}, {"$sort": order}, {"$limit": MAX_ROWS}],
                "total": [{"$group": {"_id": None, **_sums()}}],
            }
        },
    ]


def _row(doc: dict[str, Any], key: str) -> UsageRow:
    ok = int(doc.get("ok") or 0)
    counters = {c: int(doc.get(c) or 0) for c in (*SUMS[:-1], "errors", *(f"errors_{k}" for k in KINDS))}
    return UsageRow(
        key=key,
        **counters,
        cost=round(float(doc.get("cost") or 0.0), 6),
        latency_avg_ms=int((doc.get("latency_ok") or 0) / ok) if ok else None,
    )


def _uuids(values: list[str]) -> list[uuid.UUID]:
    out = []
    for v in values:
        try:
            out.append(uuid.UUID(str(v)))
        except ValueError:
            continue
    return out


async def _label(session, group_by: str, rows: list[UsageRow], docs: dict[str, dict]) -> None:
    """Tên + dòng phụ cho từng dòng: tra Postgres (tên hiện tại), thiếu thì dùng giá trị ghi trong document."""
    ids = _uuids([r.key for r in rows])
    by_id: dict[str, Any] = {}
    if group_by == "provider" and ids:
        by_id = {str(p.id): p for p in (await session.exec(select(AgentProvider).where(AgentProvider.id.in_(ids))))}
    elif group_by == "model" and ids:
        by_id = {str(m.id): m for m in (await session.exec(select(AgentModel).where(AgentModel.id.in_(ids))))}
    elif group_by == "agent" and ids:
        by_id = {str(a.id): a for a in (await session.exec(select(Agent).where(Agent.id.in_(ids))))}
    elif group_by == "tenant" and ids:
        by_id = {str(t.id): t for t in (await session.exec(select(Tenant).where(Tenant.id.in_(ids))))}
    elif group_by == "user" and ids:
        by_id = {str(u.id): u for u in (await session.exec(select(User).where(User.id.in_(ids))))}
    elif group_by == "key" and ids:
        by_id = {str(c.id): c for c in (await session.exec(select(Credential).where(Credential.id.in_(ids))))}
    elif group_by == "session" and ids:
        by_id = {str(s.id): s for s in (await session.exec(select(AgentSession).where(AgentSession.id.in_(ids))))}
    for r in rows:
        d, hit = docs.get(r.key, {}), by_id.get(r.key)
        if group_by == "provider":
            r.name, r.sub = (hit.name if hit else None), (hit.kind if hit else d.get("pkind"))
        elif group_by == "model":
            r.name, r.sub = (hit.name if hit else d.get("code")), d.get("code")
            if hit is not None:
                r.prices = Prices(
                    input=hit.input_price_per_1m,
                    output=hit.output_price_per_1m,
                    cache_read=hit.cache_read_price_per_1m,
                    cache_write=hit.cache_write_price_per_1m,
                )
        elif group_by == "agent":
            r.name, r.sub = (hit.name if hit else d.get("slug")), d.get("slug")
        elif group_by == "tenant":
            r.name, r.sub = (hit.name if hit else None), (hit.slug if hit else None)
        elif group_by == "user":
            r.name, r.sub = ((hit.name or hit.email) if hit else None), (hit.email if hit else None)
        elif group_by == "key":
            r.name, r.sub = (hit.name if hit else None), d.get("hint")
        elif group_by == "session":
            r.name = hit.title if hit else None


@operation(
    "usage.summary",
    title="Usage agent",
    description="Superadmin: request, token (vào / ra / cache), chi phí ước tính, lỗi, độ trễ của các lần gọi LLM — "
    "gộp theo provider / model / agent / nơi gọi / tổ chức / user / key / phiên / ngày / giờ, lọc chéo; "
    "mặc định 30 ngày",
    superadmin=True,
    agent_reason=REASON,
)
async def summary(ctx: OpContext, inp: SummaryIn) -> UsageSummary:
    since, until = window(inp)
    tz = ctx.settings.APP_TIMEZONE
    sink = get_sinks().traces
    if not sink.enabled:
        return UsageSummary(enabled=False, since=since, until=until, group_by=inp.group_by, tz=tz, rows=[], total=None)
    found = await sink.aggregate_calls(pipeline(match_of(inp, since, until), inp.group_by, tz))
    facet = found[0] if found else {"rows": [], "total": []}
    docs = {str(d["_id"]): d for d in facet.get("rows", [])}
    rows = [_row(d, k) for k, d in docs.items()]
    await _label(ctx.session, inp.group_by, rows, docs)
    total = _row(facet["total"][0], "total") if facet.get("total") else None
    return UsageSummary(since=since, until=until, group_by=inp.group_by, tz=tz, rows=rows, total=total)


@operation(
    "usage.errors",
    title="Lỗi gọi LLM",
    description="Superadmin: các lần gọi LLM lỗi gần nhất (rate limit / key sai / lỗi server / khác) — cùng bộ lọc với "
    "usage.summary",
    superadmin=True,
    agent_reason=REASON,
)
async def errors(ctx: OpContext, inp: ErrorsIn) -> ErrorPage:
    since, until = window(inp)
    sink = get_sinks().traces
    if not sink.enabled:
        return ErrorPage(enabled=False, items=[], total=0, limit=inp.limit, offset=inp.offset)
    match = {**match_of(inp, since, until), "status": "error", **({"error_kind": inp.kind} if inp.kind else {})}
    docs, total = await sink.list_calls(match, limit=inp.limit, offset=inp.offset)
    s = ctx.session
    agents = {
        str(a.id): a.name
        for a in await s.exec(select(Agent).where(Agent.id.in_(_uuids([d.get("agent_id") for d in docs]))))
    }
    models = {
        str(m.id): m.name
        for m in await s.exec(select(AgentModel).where(AgentModel.id.in_(_uuids([d.get("model_id") for d in docs]))))
    }
    users = {
        str(u.id): u.name or u.email
        for u in await s.exec(select(User).where(User.id.in_(_uuids([d.get("user_id") for d in docs]))))
    }
    keys = {
        str(c.id): c.name
        for c in await s.exec(
            select(Credential).where(Credential.id.in_(_uuids([d.get("credential_id") for d in docs])))
        )
    }
    items = [
        LlmError(
            id=d["id"],
            at=d["at"],
            kind=d.get("error_kind"),
            error=d.get("error"),
            run_id=str(d.get("run_id") or ""),
            purpose=d.get("purpose"),
            agent=agents.get(d.get("agent_id")) or d.get("agent_slug"),
            model=models.get(d.get("model_id")) or d.get("model"),
            model_code=d.get("model"),
            provider_kind=d.get("provider_kind"),
            user=users.get(d.get("user_id")),
            key=keys.get(d.get("credential_id")) or d.get("key_hint"),
            latency_ms=d.get("latency_ms"),
        )
        for d in docs
    ]
    return ErrorPage(items=items, total=total, limit=inp.limit, offset=inp.offset)
