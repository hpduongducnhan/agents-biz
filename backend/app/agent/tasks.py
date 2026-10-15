"""Task của agent: chạy / chạy tiếp lượt trên lane `agent-run` (retry=0 — lượt chạy tối đa một lần, CAS trong runner) và
dọn mỗi 30 s: run `running` quá 90 s không heartbeat / `queued` quá 10 phút → `failed` 6015; duyệt quá hạn → `expired`
rồi chạy tiếp lượt (LLM nhận "hết hạn duyệt"); lượt chờ duyệt mà mọi yêu cầu đã quyết (lỡ lần kick) → chạy tiếp."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, update
from sqlmodel import select

from app.agent.chat.models import AgentApproval, AgentRun
from app.agent.runtime import checkpoint, runner
from app.agent.trace.events import RunEmitter, buffered
from app.core.connections.registry import get_connections
from app.core.logging import get_logger
from app.core.messaging.tasks import task

logger = get_logger(__name__)
AGENT_LANE = "agent-run"
STALE_RUNNING = timedelta(seconds=90)
STALE_QUEUED = timedelta(minutes=10)


@task("agent.run", lane=AGENT_LANE, retry=0)
async def run_turn(run_id: str) -> None:
    if await runner.execute(run_id):
        await resume_turn.kiq(run_id)


@task("agent.resume", lane=AGENT_LANE, retry=0)
async def resume_turn(run_id: str) -> None:
    if await runner.resume(run_id):
        await resume_turn.kiq(run_id)


async def _fail_stale(now: datetime) -> list[AgentRun]:
    stale = ((AgentRun.status == "running") & (AgentRun.heartbeat_at < now - STALE_RUNNING)) | (
        (AgentRun.status == "queued") & (AgentRun.created_at < now - STALE_QUEUED)
    )
    async with get_connections().postgres.rw() as s:
        stmt = (
            update(AgentRun)
            .where(stale)
            .values(status="failed", error_code=6015, error=runner.MESSAGES[6015], ended_at=now)
            .returning(AgentRun)
        )
        return list((await s.exec(stmt)).scalars().all())


async def _expire_approvals(now: datetime) -> set[uuid.UUID]:
    async with get_connections().postgres.rw() as s:
        stmt = (
            update(AgentApproval)
            .where(AgentApproval.status == "pending", AgentApproval.expires_at < now)
            .values(status="expired", decided_at=now)
            .returning(AgentApproval.run_id)
        )
        return set((await s.exec(stmt)).scalars().all())


async def _ready_to_resume() -> list[uuid.UUID]:
    pending = exists().where(AgentApproval.run_id == AgentRun.id, AgentApproval.status == "pending")
    async with get_connections().postgres.ro() as s:
        stmt = select(AgentRun.id).where(AgentRun.status == "waiting_approval", ~pending)
        return list((await s.exec(stmt)).all())


@task("agent.sweep_runs", every=30)
async def sweep_runs() -> dict:
    now = datetime.now(UTC)
    redis = get_connections().redis
    failed = await _fail_stale(now)
    for run in failed:
        events = await buffered(redis, str(run.id)) or []
        start = events[-1]["data"]["seq"] if events else 0
        await RunEmitter(redis, run.id, run.session_id, run.user_id, start_seq=start).error(6015, runner.MESSAGES[6015])
        await checkpoint.drop(run.id)
    expired = await _expire_approvals(now)
    ready = await _ready_to_resume()
    for run_id in ready:
        await resume_turn.kiq(str(run_id))
    if failed or expired or ready:
        logger.info(
            "dọn lượt agent: %s lỗi treo, %s lượt có duyệt hết hạn, %s lượt chạy tiếp",
            len(failed),
            len(expired),
            len(ready),
            extra={"loc": "agt0103"},
        )
    return {"failed": len(failed), "expired": len(expired), "resumed": len(ready)}
