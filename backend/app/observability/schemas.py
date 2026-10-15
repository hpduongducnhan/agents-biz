"""Kiểu dữ liệu của quan sát (R13): document event log / issue và dạng trả về của operation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.core.operations.pagination import Page

IssueStatus = Literal["open", "resolved", "ignored"]


class EventLogRecord(BaseModel):
    """Một thao tác ghi. `expire_at` = `ts` + `event_log_ttl_days` lúc ghi."""

    ts: datetime
    cid: str | None = None
    actor_id: str | None = None
    actor_kind: Literal["user", "system"] = "system"
    is_superadmin: bool = False
    source: str
    agent_run_id: str | None = None
    agent_slug: str | None = None
    operation: str
    effect: str
    input: dict[str, Any] | None = None
    ok: bool
    error_code: int | None = None
    duration_ms: int = 0
    expire_at: datetime


class IssueSampleBrief(BaseModel):
    cid: str | None = None
    source: str
    operation: str | None = None
    path: str | None = None
    user_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class IssueSample(IssueSampleBrief):
    traceback: str = ""  # đã che, ≤ 20 KB


class IssueOccurrence(BaseModel):
    cid: str | None = None
    ts: datetime


class IssueSummary(BaseModel):
    fingerprint: str
    title: str
    exc_type: str
    loc: str | None = None
    source: str
    status: IssueStatus = "open"
    count: int = 0
    first_seen: datetime
    last_seen: datetime
    status_changed_at: datetime | None = None
    status_changed_by: str | None = None
    sample: IssueSampleBrief


class IssueRecord(IssueSummary):
    """Document `issues` đầy đủ."""

    sample: IssueSample
    recent: list[IssueOccurrence] = Field(default_factory=list)  # ≤ 20 lần gần nhất


class EventFilter(BaseModel):
    actor_id: uuid.UUID | None = None
    operation: str | None = Field(default=None, max_length=128)  # tiền tố, vd "auth."
    source: str | None = Field(default=None, max_length=16)
    ok: bool | None = None
    since: datetime | None = None
    until: datetime | None = None

    @field_validator("since", "until")
    @classmethod
    def _as_utc(cls, value: datetime | None) -> datetime | None:
        return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


class EventLogItem(EventLogRecord):
    id: str


class EventLogPage(Page[EventLogItem]):
    enabled: bool = True


class IssuePage(Page[IssueSummary]):
    enabled: bool = True


class IssueResult(BaseModel):
    enabled: bool
    item: IssueRecord | None = None
