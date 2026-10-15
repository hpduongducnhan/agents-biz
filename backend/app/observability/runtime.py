"""Sink Mongo + LogStore của process: bật lúc boot (khi MONGO_ENABLED và role có kết nối Mongo), tắt lúc dừng."""

from __future__ import annotations

from functools import partial

from app.core.connections.documents import init_documents
from app.core.connections.mongo import Mongo
from app.core.connections.registry import get_connections
from app.core.settings import Settings
from app.observability import store
from app.observability.alerts import notify_new_issue
from app.observability.documents import MODELS, EventLogDoc, IssueDoc
from app.observability.mongo_sinks import MongoSinks, event_log_ttl_days
from app.observability.sinks import Sinks
from app.observability.traces import MongoTraceSink
from app.system.settings_store import SystemSettings

_current: MongoSinks | None = None
_ZERO = {"queued": 0, "written": 0, "dropped": 0, "failed": 0}


def current() -> MongoSinks | None:
    return _current


def observability_stats() -> dict[str, int]:
    """Bộ đếm sink của process này (trang Trạng thái); không có sink Mongo → toàn 0."""
    return _current.stats() if _current is not None else dict(_ZERO)


async def start(settings: Settings, mongo: Mongo) -> Sinks:
    """Gắn Beanie (tạo index: TTL `event_log.expire_at`, `issues.fingerprint` duy nhất), chạy task ghi, gắn store."""
    global _current
    await init_documents(mongo, MODELS)
    sinks = MongoSinks(
        EventLogDoc.get_pymongo_collection(),
        IssueDoc.get_pymongo_collection(),
        ttl_days=event_log_ttl_days,
        default_ttl_days=SystemSettings().event_log_ttl_days,
        alert=partial(notify_new_issue, get_connections().redis.rw),
        redact_keys=settings.extra_redact_keys,
    )
    sinks.start()
    _current = sinks
    store.bind(store.LogStore(mongo))
    traces = MongoTraceSink(mongo)
    await traces.ensure_indexes()
    return Sinks(event_log=sinks.event_log, issues=sinks.issues, enabled=True, traces=traces)


async def stop(timeout: float = 2.0) -> None:
    global _current
    store.unbind()
    if _current is not None:
        sinks, _current = _current, None
        await sinks.stop(timeout)
