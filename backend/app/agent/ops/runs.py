"""agent.* — lượt chạy: huỷ, quyết yêu cầu duyệt (lẻ / gom), đọc sự kiện đã đệm (client bù khi hở `seq` / nối lại)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlmodel import select

from app.agent import tasks
from app.agent.chat.models import AgentApproval, AgentRun
from app.agent.ops.chat import KEYS, REASON, require_agent_on
from app.agent.runtime import checkpoint
from app.agent.trace.events import BUFFER_TTL, RunEmitter, buffered, cancel_key
from app.core.errors import AppException
from app.core.operations.context import OpContext
from app.core.operations.spec import operation


class RunIdIn(BaseModel):
    run_id: uuid.UUID


class CancelOut(BaseModel):
    run_id: uuid.UUID
    status: str


class DecideIn(BaseModel):
    approval_id: uuid.UUID
    approve: bool
    reason: str | None = Field(default=None, max_length=500)


class DecideOut(BaseModel):
    approval_id: uuid.UUID
    status: str
    run_id: uuid.UUID


class DecideManyIn(RunIdIn):
    approval_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)  # đúng những yêu cầu người dùng đang thấy
    approve: bool
    reason: str | None = Field(default=None, max_length=500)


class DecidedItem(BaseModel):
    approval_id: uuid.UUID
    status: str


class DecideManyOut(BaseModel):
    run_id: uuid.UUID
    decided: list[DecidedItem]
    skipped: list[uuid.UUID]  # đã quyết / hết hạn / không thuộc lượt này
    resumed: bool


class EventsIn(RunIdIn):
    after_seq: int = Field(default=0, ge=0)


class EventsOut(BaseModel):
    available: bool
    events: list[dict[str, Any]]


async def own_run(ctx: OpContext, run_id: uuid.UUID, *, lock: bool = False) -> AgentRun:
    stmt = select(AgentRun).where(AgentRun.id == run_id)
    run = (await ctx.session.exec(stmt.with_for_update() if lock else stmt)).first()
    if run is None or (run.user_id != ctx.principal.user_id and not ctx.principal.sup):
        raise AppException(6006, status_code=404)
    return run


def _decide(ctx: OpContext, approval: AgentApproval, approve: bool, reason: str | None, now: datetime) -> None:
    approval.status = "approved" if approve else "rejected"
    approval.decided_by, approval.decided_at, approval.reason = ctx.principal.user_id, now, reason
    ctx.session.add(approval)


async def _resume_when_done(ctx: OpContext, run: AgentRun) -> bool:
    """Hết yêu cầu chờ → chạy tiếp lượt (một lần). Gọi khi đang giữ khoá dòng run — lệnh quyết song song xếp hàng."""
    await ctx.session.flush()
    left = (
        await ctx.session.exec(
            select(AgentApproval.id).where(AgentApproval.run_id == run.id, AgentApproval.status == "pending")
        )
    ).first()
    if left is not None or run.status != "waiting_approval":
        return False
    run_id = str(run.id)

    async def kick() -> None:
        await tasks.resume_turn.kiq(run_id)

    ctx.after_commit(kick)
    return True


async def _emitter(ctx: OpContext, run: AgentRun) -> RunEmitter:
    events = await buffered(ctx.redis, str(run.id)) or []
    start = events[-1]["data"]["seq"] if events else 0
    return RunEmitter(ctx.redis, run.id, run.session_id, run.user_id, start_seq=start)


@operation(
    "agent.cancel",
    title="Huỷ lượt trả lời",
    description="Lượt đang chạy dừng ở lần kiểm kế tiếp (≤ 0,25 s); lượt chờ / chờ duyệt đóng ngay",
    effect="write",
    permission="agent.chat",
    agent_reason=REASON,
    invalidates=KEYS,
)
async def cancel(ctx: OpContext, inp: RunIdIn) -> CancelOut:
    run = await own_run(ctx, inp.run_id, lock=True)
    if run.status == "running":
        await ctx.redis.rw.set(cancel_key(str(run.id)), "1", ex=BUFFER_TTL)
        return CancelOut(run_id=run.id, status="cancelling")
    if run.status not in ("queued", "waiting_approval"):
        return CancelOut(run_id=run.id, status=run.status)
    now = datetime.now(UTC)
    run.status, run.error_code, run.ended_at = "cancelled", 6014, now
    ctx.session.add(run)
    await ctx.session.exec(
        update(AgentApproval)
        .where(AgentApproval.run_id == run.id, AgentApproval.status == "pending")
        .values(status="expired", decided_at=now, reason="lượt đã bị huỷ")
    )
    emitter = await _emitter(ctx, run)
    run_id = run.id

    async def closed() -> None:
        await checkpoint.drop(run_id)
        await emitter.end(message_id=None, usage={}, status="cancelled")

    ctx.after_commit(closed)
    ctx.invalidate(KEYS, users=[run.user_id])
    return CancelOut(run_id=run.id, status="cancelled")


@operation(
    "agent.decide_approval",
    title="Duyệt / từ chối thao tác của agent",
    description="Người chat hoặc superadmin; đã quyết / hết hạn → 6008. Hết yêu cầu chờ → lượt chạy tiếp",
    effect="write",
    permission="agent.chat",
    agent_reason=REASON,
    invalidates=KEYS,
)
async def decide_approval(ctx: OpContext, inp: DecideIn) -> DecideOut:
    await require_agent_on(ctx)
    found = (await ctx.session.exec(select(AgentApproval.run_id).where(AgentApproval.id == inp.approval_id))).first()
    if found is None:
        raise AppException(6008, status_code=404)
    # khoá run trước approval (cùng thứ tự với cancel / decide_approvals) — hai lệnh quyết song song không cùng bỏ sót
    run = (await ctx.session.exec(select(AgentRun).where(AgentRun.id == found).with_for_update())).first()
    if run is None or (run.user_id != ctx.principal.user_id and not ctx.principal.sup):
        raise AppException(1005, status_code=403)
    stmt = select(AgentApproval).where(AgentApproval.id == inp.approval_id).with_for_update()
    approval = (await ctx.session.exec(stmt)).one()
    now = datetime.now(UTC)
    if approval.status != "pending" or approval.expires_at <= now:
        raise AppException(6008, status_code=409)
    _decide(ctx, approval, inp.approve, inp.reason, now)
    await _resume_when_done(ctx, run)
    ctx.invalidate(KEYS, users=[run.user_id])
    return DecideOut(approval_id=approval.id, status=approval.status, run_id=run.id)


@operation(
    "agent.decide_approvals",
    title="Duyệt / từ chối nhiều thao tác của agent",
    description="Quyết cùng lúc các yêu cầu còn chờ trong danh sách (một lượt); đã quyết / hết hạn → bỏ qua; "
    "không cái nào quyết được → 6008. Hết yêu cầu chờ → lượt chạy tiếp",
    effect="write",
    permission="agent.chat",
    agent_reason=REASON,
    invalidates=KEYS,
)
async def decide_approvals(ctx: OpContext, inp: DecideManyIn) -> DecideManyOut:
    await require_agent_on(ctx)
    run = await own_run(ctx, inp.run_id, lock=True)
    ids = list(dict.fromkeys(inp.approval_ids))
    stmt = (
        select(AgentApproval)
        .where(AgentApproval.run_id == run.id, AgentApproval.id.in_(ids))
        .order_by(AgentApproval.id)
        .with_for_update()
    )
    rows = {a.id: a for a in (await ctx.session.exec(stmt)).all()}
    now = datetime.now(UTC)
    decided: list[DecidedItem] = []
    skipped: list[uuid.UUID] = []
    for approval_id in ids:
        approval = rows.get(approval_id)
        if approval is None or approval.status != "pending" or approval.expires_at <= now:
            skipped.append(approval_id)
            continue
        _decide(ctx, approval, inp.approve, inp.reason, now)
        decided.append(DecidedItem(approval_id=approval.id, status=approval.status))
    if not decided:
        raise AppException(6008, status_code=409, data={"skipped": [str(x) for x in skipped]})
    resumed = await _resume_when_done(ctx, run)
    ctx.invalidate(KEYS, users=[run.user_id])
    return DecideManyOut(run_id=run.id, decided=decided, skipped=skipped, resumed=resumed)


@operation(
    "agent.run_events",
    title="Sự kiện của lượt chạy",
    description="Sự kiện đã đệm có `seq > after_seq` (bộ đệm giữ 1 giờ); `available=false` → tải lại phiên",
    permission="agent.chat",
    agent_reason=REASON,
)
async def run_events(ctx: OpContext, inp: EventsIn) -> EventsOut:
    run = await own_run(ctx, inp.run_id)
    events = await buffered(ctx.redis, str(run.id), inp.after_seq)
    return EventsOut(available=events is not None, events=events or [])
