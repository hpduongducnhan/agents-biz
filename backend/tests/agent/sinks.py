"""Sink trace trong bộ nhớ cho test tracer (thay `MongoTraceSink` — cùng giao diện `TraceSink`)."""

from __future__ import annotations

import copy
from typing import Any

from app.observability.sinks import Sinks, noop_sinks, set_sinks
from tests.fixtures.sinks import MemoryEventLog, MemoryIssues


class MemoryTraceSink:
    enabled = True

    def __init__(self) -> None:
        self.spans: dict[str, dict[str, Any]] = {}
        self.raws: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []
        self.fail = False

    async def save_span(self, doc: dict[str, Any]) -> None:
        if self.fail:
            raise ConnectionError("sink hỏng")
        self.spans[doc["id"]] = copy.deepcopy(doc)

    async def save_call(self, doc: dict[str, Any]) -> None:
        if self.fail:
            raise ConnectionError("sink hỏng")
        self.calls.append(copy.deepcopy(doc))

    async def aggregate_calls(self, pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return []

    async def list_calls(self, match: dict[str, Any], *, limit: int, offset: int) -> tuple[list[dict], int]:
        rows = [c for c in self.calls if all(c.get(k) == v for k, v in match.items() if not isinstance(v, dict))]
        return [copy.deepcopy(r) for r in rows[offset : offset + limit]], len(rows)

    async def insert_raw(self, doc: dict[str, Any]) -> None:
        self.raws.append(copy.deepcopy(doc))

    async def get_span(self, span_id: str) -> dict[str, Any] | None:
        return copy.deepcopy(self.spans.get(span_id))

    async def count_spans(self, run_id: str) -> int:
        return sum(1 for s in self.spans.values() if s["run_id"] == run_id)

    async def llm_of_call(self, run_id: str, call_id: str) -> str | None:
        for s in self.spans.values():
            if (
                s["run_id"] == run_id
                and s["kind"] == "llm"
                and any(c["id"] == call_id for c in s["output"].get("tool_calls", []))
            ):
                return s["id"]
        return None

    async def list_runs(self, query: dict[str, Any], *, limit: int, offset: int) -> tuple[list[dict], int]:
        rows = [
            s
            for s in self.spans.values()
            if s["kind"] == "run" and all(s.get(k) == v for k, v in query.items() if not isinstance(v, dict))
        ]
        rows.sort(key=lambda s: s["start"], reverse=True)
        return [copy.deepcopy(r) for r in rows[offset : offset + limit]], len(rows)

    async def spans_of(self, run_id: str) -> list[dict[str, Any]]:
        return sorted((copy.deepcopy(s) for s in self.spans.values() if s["run_id"] == run_id), key=lambda s: s["seq"])

    async def get_raw(self, run_id: str, raw_id: str) -> dict[str, Any] | None:
        return next((copy.deepcopy(r) for r in self.raws if r["run_id"] == run_id and r["id"] == raw_id), None)

    def kinds(self, run_id: str) -> list[str]:
        return [s["kind"] for s in sorted(self.spans.values(), key=lambda s: s["seq"]) if s["run_id"] == run_id]


def install(sink: MemoryTraceSink) -> Sinks:
    sinks = Sinks(event_log=MemoryEventLog(), issues=MemoryIssues(), enabled=True, traces=sink)
    set_sinks(sinks)
    return sinks


def uninstall() -> None:
    set_sinks(noop_sinks())
