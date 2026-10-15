"""Interface ghi log quan sát (event log, issues) + bản Noop. Lúc boot cài bản Mongo qua `set_sinks` khi bật cờ."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from app.core.cid import get_cid
from app.core.logging import get_logger
from app.observability.traces import NoopTraceSink, TraceSink

logger = get_logger(__name__)


@dataclass
class EventLogEntry:
    ts: datetime
    cid: str | None
    actor_id: uuid.UUID | None
    actor_sup: bool
    source: str
    agent_run_id: uuid.UUID | None
    operation: str
    effect: str
    input: dict | None
    ok: bool
    error_code: int | None
    duration_ms: int


class EventLogSink(Protocol):
    async def write(self, entry: EventLogEntry) -> None: ...


class IssueSink(Protocol):
    async def capture(
        self, exc: BaseException, *, source: str, loc: str | None, cid: str | None, context: dict
    ) -> None: ...


@dataclass
class Sinks:
    event_log: EventLogSink
    issues: IssueSink
    enabled: bool
    traces: TraceSink = field(default_factory=NoopTraceSink)


class NoopEventLogSink:
    async def write(self, entry: EventLogEntry) -> None:
        return None


class NoopIssueSink:
    async def capture(
        self, exc: BaseException, *, source: str, loc: str | None, cid: str | None, context: dict
    ) -> None:
        return None


def noop_sinks() -> Sinks:
    return Sinks(event_log=NoopEventLogSink(), issues=NoopIssueSink(), enabled=False)


_sinks: Sinks = noop_sinks()


def get_sinks() -> Sinks:
    return _sinks


def set_sinks(sinks: Sinks) -> None:
    global _sinks
    _sinks = sinks


async def capture_issue(
    exc: BaseException, *, source: str, loc: str | None = None, context: dict | None = None
) -> None:
    """Ghi issue cho lỗi hệ thống (task / consumer / ws / HTTP 5xx) — không bao giờ ném."""
    try:
        await get_sinks().issues.capture(exc, source=source, loc=loc, cid=get_cid(), context=context or {})
    except Exception as err:  # noqa: BLE001 — ghi issue hỏng không được làm hỏng luồng đang xử lý lỗi
        logger.warning("ghi issue lỗi (%s): %s", source, err, extra={"loc": "obs0501"})
