"""TraceSink — chỗ duy nhất ghi / đọc trace agent ở Mongo (R12, R19): `agent_spans` (cây span của lượt),
`agent_http_raw` (raw HTTP tới provider, đã che) và `agent_llm_calls` (mỗi lần gọi LLM một document — usage giám sát).
 Mongo tắt → `NoopTraceSink` (ghi bỏ, đọc trả rỗng, `enabled=False`; cảnh báo một lần đã có ở `obs0001`).
Mọi collection có TTL theo `expire_at`."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from pymongo import ASCENDING, DESCENDING
from pymongo.errors import PyMongoError

from app.core.connections.mongo import Mongo
from app.core.errors import AppException
from app.core.logging import get_logger

logger = get_logger(__name__)
SPANS, RAW, CALLS = "agent_spans", "agent_http_raw", "agent_llm_calls"
TIMEOUT = 5.0


class TraceSink(Protocol):
    enabled: bool

    async def save_span(self, doc: dict[str, Any]) -> None: ...
    async def insert_raw(self, doc: dict[str, Any]) -> None: ...
    async def get_span(self, span_id: str) -> dict[str, Any] | None: ...
    async def count_spans(self, run_id: str) -> int: ...
    async def llm_of_call(self, run_id: str, call_id: str) -> str | None: ...
    async def list_runs(self, query: dict[str, Any], *, limit: int, offset: int) -> tuple[list[dict], int]: ...
    async def spans_of(self, run_id: str) -> list[dict[str, Any]]: ...
    async def get_raw(self, run_id: str, raw_id: str) -> dict[str, Any] | None: ...
    async def save_call(self, doc: dict[str, Any]) -> None: ...
    async def aggregate_calls(self, pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]: ...
    async def list_calls(self, match: dict[str, Any], *, limit: int, offset: int) -> tuple[list[dict], int]: ...


class NoopTraceSink:
    enabled = False

    async def save_span(self, doc: dict[str, Any]) -> None:
        return None

    async def insert_raw(self, doc: dict[str, Any]) -> None:
        return None

    async def get_span(self, span_id: str) -> dict[str, Any] | None:
        return None

    async def count_spans(self, run_id: str) -> int:
        return 0

    async def llm_of_call(self, run_id: str, call_id: str) -> str | None:
        return None

    async def list_runs(self, query: dict[str, Any], *, limit: int, offset: int) -> tuple[list[dict], int]:
        return [], 0

    async def spans_of(self, run_id: str) -> list[dict[str, Any]]:
        return []

    async def get_raw(self, run_id: str, raw_id: str) -> dict[str, Any] | None:
        return None

    async def save_call(self, doc: dict[str, Any]) -> None:
        return None

    async def aggregate_calls(self, pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return []

    async def list_calls(self, match: dict[str, Any], *, limit: int, offset: int) -> tuple[list[dict], int]:
        return [], 0


class MongoTraceSink:
    enabled = True

    def __init__(self, mongo: Mongo, *, timeout: float = TIMEOUT) -> None:
        self._rw, self._ro, self._timeout = mongo.rw, mongo.ro, timeout

    async def ensure_indexes(self) -> None:
        spans, raw, calls = self._rw[SPANS], self._rw[RAW], self._rw[CALLS]
        await spans.create_index([("expire_at", ASCENDING)], expireAfterSeconds=0)
        await spans.create_index([("run_id", ASCENDING), ("seq", ASCENDING)])
        await spans.create_index([("kind", ASCENDING), ("start", DESCENDING)])
        for field in ("user_id", "session_id", "status", "tenant_id"):  # lọc trace
            await spans.create_index([("kind", ASCENDING), (field, ASCENDING), ("start", DESCENDING)])
        await raw.create_index([("expire_at", ASCENDING)], expireAfterSeconds=0)
        await raw.create_index([("run_id", ASCENDING)])
        await calls.create_index([("expire_at", ASCENDING)], expireAfterSeconds=0)
        await calls.create_index([("at", DESCENDING)])
        for field in ("user_id", "model_id", "credential_id", "status", "tenant_id"):
            await calls.create_index([(field, ASCENDING), ("at", DESCENDING)])

    async def _call(self, work: Callable[[], Awaitable[Any]]) -> Any:
        try:
            return await asyncio.wait_for(work(), self._timeout)
        except (TimeoutError, PyMongoError) as exc:
            logger.warning("Mongo của trace không phản hồi: %s", exc, extra={"loc": "obs0508"})
            raise AppException(7001, status_code=503) from exc

    async def save_span(self, doc: dict[str, Any]) -> None:
        body = {k: v for k, v in doc.items() if k != "id"}
        await self._rw[SPANS].replace_one({"_id": doc["id"]}, body, upsert=True)

    async def insert_raw(self, doc: dict[str, Any]) -> None:
        await self._rw[RAW].insert_one({"_id": doc["id"], **{k: v for k, v in doc.items() if k != "id"}})

    async def get_span(self, span_id: str) -> dict[str, Any] | None:
        doc = await self._rw[SPANS].find_one({"_id": span_id})
        return _out(doc) if doc else None

    async def count_spans(self, run_id: str) -> int:
        return await self._rw[SPANS].count_documents({"run_id": run_id})

    async def llm_of_call(self, run_id: str, call_id: str) -> str | None:
        doc = await self._rw[SPANS].find_one({"run_id": run_id, "kind": "llm", "output.tool_calls.id": call_id})
        return str(doc["_id"]) if doc else None

    async def list_runs(self, query: dict[str, Any], *, limit: int, offset: int) -> tuple[list[dict], int]:
        col, q = self._ro[SPANS], {"kind": "run", **query}
        total = await self._call(lambda: col.count_documents(q))
        docs = await self._call(lambda: col.find(q).sort([("start", -1)]).skip(offset).limit(limit).to_list())
        return [_out(d) for d in docs], total

    async def spans_of(self, run_id: str) -> list[dict[str, Any]]:
        docs = await self._call(lambda: self._ro[SPANS].find({"run_id": run_id}).sort([("seq", 1)]).to_list())
        return [_out(d) for d in docs]

    async def get_raw(self, run_id: str, raw_id: str) -> dict[str, Any] | None:
        doc = await self._call(lambda: self._ro[RAW].find_one({"_id": raw_id, "run_id": run_id}))
        return _out(doc) if doc else None

    async def save_call(self, doc: dict[str, Any]) -> None:
        await self._rw[CALLS].insert_one({"_id": doc["id"], **{k: v for k, v in doc.items() if k != "id"}})

    async def aggregate_calls(self, pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
        async def run() -> list[dict[str, Any]]:
            cursor = await self._ro[CALLS].aggregate(pipeline)
            return await cursor.to_list()

        return await self._call(run)

    async def list_calls(self, match: dict[str, Any], *, limit: int, offset: int) -> tuple[list[dict], int]:
        col = self._ro[CALLS]
        total = await self._call(lambda: col.count_documents(match))
        docs = await self._call(lambda: col.find(match).sort([("at", -1)]).skip(offset).limit(limit).to_list())
        return [_out(d) for d in docs], total


def _out(doc: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(doc["_id"]), **{k: v for k, v in doc.items() if k != "_id"}}
