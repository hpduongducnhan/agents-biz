"""Đồ giả cho test quan sát: EventLogEntry mẫu, Mongo "chết"."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pymongo.errors import ServerSelectionTimeoutError

from app.observability.sinks import EventLogEntry


def make_entry(**kw: Any) -> EventLogEntry:
    base: dict[str, Any] = {
        "ts": datetime.now(UTC),
        "cid": "cid-test",
        "actor_id": None,
        "actor_sup": False,
        "source": "web",
        "agent_run_id": None,
        "operation": "test.op",
        "effect": "write",
        "input": {},
        "ok": True,
        "error_code": None,
        "duration_ms": 3,
    }
    return EventLogEntry(**(base | kw))


class DownMongoDb:
    """Thay database Mongo (`mongo.ro` / `mongo.rw`): mọi lệnh ném lỗi chọn server như khi Mongo chết."""

    def __getitem__(self, name: str) -> DownMongoDb:
        return self

    def find(self, *args: Any, **kwargs: Any) -> Any:
        raise ServerSelectionTimeoutError("mongo down")

    async def find_one(self, *args: Any, **kwargs: Any) -> Any:
        raise ServerSelectionTimeoutError("mongo down")

    async def find_one_and_update(self, *args: Any, **kwargs: Any) -> Any:
        raise ServerSelectionTimeoutError("mongo down")

    async def count_documents(self, *args: Any, **kwargs: Any) -> int:
        raise ServerSelectionTimeoutError("mongo down")
