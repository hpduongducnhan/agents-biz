"""Sink Mongo cho event log + issues — ghi NỀN qua một hàng đợi trong bộ nhớ có giới hạn (8.4)."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, timedelta
from typing import Any

from fastapi.encoders import jsonable_encoder
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.logging import get_logger
from app.core.redact import build_keys, redact_mapping
from app.observability.capture import IssueEvent, issue_event
from app.observability.schemas import EventLogRecord
from app.observability.sinks import EventLogEntry
from app.system.settings_store import cached_system_settings

logger = get_logger(__name__)
MAX_QUEUE = 1000
BATCH = 100
RECENT_LIMIT = 20
INPUT_LIMIT = 16_000  # ký tự JSON của `input` — quá thì chỉ giữ bản xem trước
TtlProvider = Callable[[], Awaitable[int]]
Alert = Callable[[dict[str, Any]], Awaitable[None]]


async def event_log_ttl_days() -> int:
    return (await cached_system_settings()).event_log_ttl_days


class _EventLogPort:
    """`EventLogSink` — chỉ xếp hàng."""

    def __init__(self, owner: MongoSinks) -> None:
        self._owner = owner

    async def write(self, entry: EventLogEntry) -> None:
        self._owner.offer(entry)


class _IssuePort:
    """`IssueSink` — chụp lỗi rồi xếp hàng."""

    def __init__(self, owner: MongoSinks) -> None:
        self._owner = owner

    async def capture(
        self, exc: BaseException, *, source: str, loc: str | None, cid: str | None, context: dict
    ) -> None:
        event = issue_event(exc, source=source, loc=loc, cid=cid, context=context, keys=self._owner.redact_keys)
        self._owner.offer(event)


class MongoSinks:
    def __init__(
        self,
        events: Any,
        issues: Any,
        *,
        ttl_days: TtlProvider,
        default_ttl_days: int = 180,
        alert: Alert | None = None,
        redact_keys: frozenset[str] = frozenset(),
        max_queue: int = MAX_QUEUE,
        batch: int = BATCH,
    ) -> None:
        self._events = events
        self._issues = issues
        self._ttl_days = ttl_days
        self._default_ttl_days = default_ttl_days
        self._alert = alert
        self.redact_keys = build_keys(redact_keys)
        self._queue: asyncio.Queue[EventLogEntry | IssueEvent] = asyncio.Queue(maxsize=max_queue)
        self._batch = batch
        self._task: asyncio.Task | None = None
        self.written = 0
        self.dropped = 0
        self.failed = 0
        self.event_log = _EventLogPort(self)
        self.issues = _IssuePort(self)

    # ── nhận: không bao giờ chờ ────────────────────────────────────────────────
    def offer(self, item: EventLogEntry | IssueEvent) -> bool:
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            self.dropped += 1
            if self.dropped == 1 or self.dropped % 100 == 0:
                logger.warning(
                    "hàng đợi log Mongo đầy (%d mục) — đã bỏ %d mục",
                    self._queue.maxsize,
                    self.dropped,
                    extra={"loc": "obs0502"},
                )
            return False
        return True

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def stats(self) -> dict[str, int]:
        return {"queued": self._queue.qsize(), "written": self.written, "dropped": self.dropped, "failed": self.failed}

    # ── task nền ──────────────────────────────────────────────────────────────
    def start(self) -> None:
        if not self.running:
            self._task = asyncio.create_task(self._run(), name="bw-observability-writer")

    async def stop(self, timeout: float = 2.0) -> None:
        """Tắt process: ghi nốt tối đa `timeout` giây rồi huỷ — không bao giờ treo lúc tắt."""
        if self._task is None:
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._queue.join(), timeout)
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        if left := self._queue.qsize():
            logger.warning("tắt khi còn %d mục log chưa ghi — bỏ", left, extra={"loc": "obs0504"})

    async def _run(self) -> None:
        while True:
            batch = [await self._queue.get()]
            while len(batch) < self._batch and not self._queue.empty():
                batch.append(self._queue.get_nowait())
            try:
                await self._flush(batch)
            finally:
                for _ in batch:
                    self._queue.task_done()

    async def _flush(self, batch: list[EventLogEntry | IssueEvent]) -> None:
        events = [item for item in batch if isinstance(item, EventLogEntry)]
        if events:
            await self._guard(len(events), self._write_events(events))
        for item in batch:
            if isinstance(item, IssueEvent):
                await self._guard(1, self._upsert_issue(item))

    async def _guard(self, count: int, work: Awaitable[None]) -> None:
        try:
            await work
        except Exception as exc:  # noqa: BLE001 — Mongo hỏng không được giết task ghi; các mục này bỏ
            self.failed += count
            logger.warning("ghi %d mục log Mongo lỗi: %s", count, exc, extra={"loc": "obs0503"})
        else:
            self.written += count

    # ── event log ─────────────────────────────────────────────────────────────
    async def _ttl(self) -> timedelta:
        try:
            days = await self._ttl_days()
        except Exception as exc:  # noqa: BLE001 — đọc cài đặt lỗi: dùng mặc định, vẫn ghi event log (R11)
            days = self._default_ttl_days
            logger.warning(
                "đọc event_log_ttl_days lỗi (%s) — dùng %d ngày; DEFAULTS_APPLIED=[event_log_ttl_days]",
                exc,
                days,
                extra={"loc": "obs0506"},
            )
        return timedelta(days=days)

    async def _write_events(self, entries: list[EventLogEntry]) -> None:
        ttl = await self._ttl()
        await self._events.insert_many([self._event_doc(e, ttl) for e in entries], ordered=False)

    def _event_doc(self, e: EventLogEntry, ttl: timedelta) -> dict[str, Any]:
        ts = e.ts if e.ts.tzinfo else e.ts.replace(tzinfo=UTC)
        record = EventLogRecord(
            ts=ts,
            cid=e.cid,
            actor_id=str(e.actor_id) if e.actor_id else None,
            actor_kind="user" if e.actor_id else "system",
            is_superadmin=bool(e.actor_sup),
            source=e.source,
            agent_run_id=str(e.agent_run_id) if e.agent_run_id else None,
            operation=e.operation,
            effect=e.effect,
            input=self._input(e.input),
            ok=e.ok,
            error_code=e.error_code,
            duration_ms=int(e.duration_ms),
            expire_at=ts + ttl,
        )
        return record.model_dump()

    def _input(self, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        plain = redact_mapping(jsonable_encoder(value), self.redact_keys)
        text = json.dumps(plain, ensure_ascii=False)
        if len(text) > INPUT_LIMIT:
            return {"_truncated": True, "preview": text[:INPUT_LIMIT]}
        return plain

    # ── issue ─────────────────────────────────────────────────────────────────
    async def _upsert_issue(self, ev: IssueEvent) -> None:
        change = {
            "$inc": {"count": 1},
            "$set": {"last_seen": ev.ts, "title": ev.title, "sample": ev.sample.model_dump()},
            "$setOnInsert": {
                "exc_type": ev.exc_type,
                "loc": ev.loc,
                "source": ev.source,
                "status": "open",
                "first_seen": ev.ts,
            },
            "$push": {"recent": {"$each": [{"cid": ev.cid, "ts": ev.ts}], "$slice": -RECENT_LIMIT}},
        }
        where = {"fingerprint": ev.fingerprint}
        try:
            before = await self._issues.find_one_and_update(
                where, change, upsert=True, return_document=ReturnDocument.BEFORE
            )
        except DuplicateKeyError:  # hai process cùng chèn issue mới — bản thua cập nhật lại
            logger.info("issue %s vừa được process khác tạo — cập nhật lại", ev.fingerprint, extra={"loc": "obs0004"})
            before = await self._issues.find_one_and_update(where, change, return_document=ReturnDocument.BEFORE)
        if before is None:
            await self._raise_alert(ev, reopened=False)
        elif before.get("status") == "resolved":
            await self._issues.update_one(
                {"fingerprint": ev.fingerprint, "status": "resolved"},
                {"$set": {"status": "open", "status_changed_at": ev.ts, "status_changed_by": None}},
            )
            await self._raise_alert(ev, reopened=True)

    async def _raise_alert(self, ev: IssueEvent, *, reopened: bool) -> None:
        if self._alert is None:
            return
        issue = {
            "fingerprint": ev.fingerprint,
            "title": ev.title,
            "loc": ev.loc,
            "source": ev.source,
            "reopened": reopened,
        }
        try:
            await self._alert(issue)
        except Exception as exc:  # noqa: BLE001 — báo superadmin hỏng không được làm mất issue đã ghi
            logger.warning("báo issue %s lỗi: %s", ev.fingerprint, exc, extra={"loc": "obs0505"})
