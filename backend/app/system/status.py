"""system.status — ảnh chụp cho trang Trạng thái của superadmin: sẵn sàng, nhịp tim, phiên bản, quan sát, mặc định."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from app.core.connections.registry import get_connections
from app.core.errors import AppException
from app.core.operations.context import OpContext
from app.observability.runtime import observability_stats
from app.observability.sinks import get_sinks
from app.observability.store import get_store
from app.system import heartbeat
from app.system.health import is_ready, readiness
from app.system.settings_store import settings_snapshot


class HeartbeatOut(BaseModel):
    last: str | None
    age_s: float | None
    ok: bool


class ObservabilityOut(BaseModel):
    enabled: bool
    queued: int
    written: int
    dropped: int
    failed: int
    open_issues: int | None = None
    open_issues_error: str | None = None


class StatusOut(BaseModel):
    version: str
    env: str
    mongo_enabled: bool
    ready: bool
    checks: dict[str, str]
    pipeline_ok: bool
    pipeline: dict[str, HeartbeatOut]
    observability: ObservabilityOut
    settings_defaults: list[str]
    time: datetime


async def _observability() -> ObservabilityOut:
    out = ObservabilityOut(enabled=get_sinks().enabled, **observability_stats())
    store = get_store()
    if store is not None:
        try:
            out.open_issues = await store.count_open_issues()
        except AppException as exc:  # store đã log obs0507; trạng thái vẫn phải trả được
            out.open_issues_error = str(exc.code)
    return out


async def collect_status(ctx: OpContext) -> StatusOut:
    s = ctx.settings
    checks = await readiness(s, get_connections())
    pipeline = await heartbeat.read_all(ctx.redis.ro, s.HEARTBEAT_INTERVAL)
    snap = await settings_snapshot(ctx.session)
    return StatusOut(
        version=s.BUILD_VERSION,
        env=s.ENV,
        mongo_enabled=s.MONGO_ENABLED,
        ready=is_ready(checks),
        checks=checks,
        pipeline_ok=all(v["ok"] for v in pipeline.values()),
        pipeline={role: HeartbeatOut(**beat) for role, beat in pipeline.items()},
        observability=await _observability(),
        settings_defaults=snap.defaults_applied,
        time=datetime.now(UTC),
    )
