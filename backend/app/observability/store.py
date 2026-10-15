"""LogStore — chỗ duy nhất đọc / sửa Mongo cho trang Event log / Issues (R12). Chỉ được gắn khi sink Mongo chạy;
`get_store()` = None nghĩa là tính năng log đang tắt."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from pymongo import ReturnDocument
from pymongo.errors import PyMongoError

from app.core.connections.mongo import Mongo
from app.core.errors import AppException
from app.core.logging import get_logger
from app.observability import errors  # noqa: F401 — đăng ký mã 7xxx
from app.observability.schemas import EventFilter, EventLogItem, IssueRecord, IssueStatus, IssueSummary

logger = get_logger(__name__)
MONGO_TIMEOUT = 5.0  # giây — Mongo chết thì trả 7001 thay vì treo request


def _event_query(f: EventFilter) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if f.actor_id:
        query["actor_id"] = str(f.actor_id)
    if f.operation:
        query["operation"] = {"$regex": f"^{re.escape(f.operation)}"}
    if f.source:
        query["source"] = f.source
    if f.ok is not None:
        query["ok"] = f.ok
    window = {k: v for k, v in (("$gte", f.since), ("$lt", f.until)) if v is not None}
    if window:
        query["ts"] = window
    return query


class LogStore:
    def __init__(self, mongo: Mongo, *, timeout: float = MONGO_TIMEOUT) -> None:
        self._ro = mongo.ro
        self._rw = mongo.rw
        self._timeout = timeout

    async def _call(self, work: Callable[[], Awaitable[Any]]) -> Any:
        try:
            return await asyncio.wait_for(work(), self._timeout)
        except (TimeoutError, PyMongoError) as exc:
            logger.warning("Mongo của quan sát không phản hồi: %s", exc, extra={"loc": "obs0507"})
            raise AppException(7001, status_code=503) from exc

    async def list_events(self, filters: EventFilter, *, limit: int, offset: int) -> tuple[list[EventLogItem], int]:
        col, query = self._ro["event_log"], _event_query(filters)
        total = await self._call(lambda: col.count_documents(query))
        docs = await self._call(
            lambda: col.find(query).sort([("ts", -1), ("_id", -1)]).skip(offset).limit(limit).to_list()
        )
        return [EventLogItem.model_validate({**d, "id": str(d["_id"])}) for d in docs], total

    async def list_issues(
        self, status: IssueStatus | None, *, limit: int, offset: int
    ) -> tuple[list[IssueSummary], int]:
        col, query = self._ro["issues"], ({"status": status} if status else {})
        total = await self._call(lambda: col.count_documents(query))
        docs = await self._call(
            lambda: col.find(query).sort([("last_seen", -1), ("_id", -1)]).skip(offset).limit(limit).to_list()
        )
        return [IssueSummary.model_validate(d) for d in docs], total

    async def get_issue(self, fp: str) -> IssueRecord | None:
        doc = await self._call(lambda: self._ro["issues"].find_one({"fingerprint": fp}))
        return IssueRecord.model_validate(doc) if doc else None

    async def set_issue_status(self, fp: str, status: IssueStatus, *, by: str) -> IssueRecord | None:
        change = {"$set": {"status": status, "status_changed_at": datetime.now(UTC), "status_changed_by": by}}
        doc = await self._call(
            lambda: self._rw["issues"].find_one_and_update(
                {"fingerprint": fp}, change, return_document=ReturnDocument.AFTER
            )
        )
        return IssueRecord.model_validate(doc) if doc else None

    async def count_open_issues(self) -> int:
        return await self._call(lambda: self._ro["issues"].count_documents({"status": "open"}))


_store: LogStore | None = None


def get_store() -> LogStore | None:
    return _store


def bind(store: LogStore) -> None:
    global _store
    _store = store


def unbind() -> None:
    global _store
    _store = None
