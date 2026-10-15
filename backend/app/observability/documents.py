"""Collection Mongo của quan sát — chỉ khi MONGO_ENABLED. Trường lấy từ record có kiểu (`schemas.py`)."""

from __future__ import annotations

from beanie import Document
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.observability.schemas import EventLogRecord, IssueRecord


class EventLogDoc(Document, EventLogRecord):
    class Settings:
        name = "event_log"
        indexes = [
            IndexModel([("ts", DESCENDING)], name="ts_desc"),
            IndexModel([("actor_id", ASCENDING), ("ts", DESCENDING)], name="actor_ts"),
            IndexModel([("operation", ASCENDING), ("ts", DESCENDING)], name="operation_ts"),
            IndexModel([("expire_at", ASCENDING)], expireAfterSeconds=0, name="ttl_expire_at"),
        ]


class IssueDoc(Document, IssueRecord):
    class Settings:
        name = "issues"
        indexes = [
            IndexModel([("fingerprint", ASCENDING)], unique=True, name="uniq_fingerprint"),
            IndexModel([("status", ASCENDING), ("last_seen", DESCENDING)], name="status_last_seen"),
        ]


MODELS: list[type[Document]] = [EventLogDoc, IssueDoc]
