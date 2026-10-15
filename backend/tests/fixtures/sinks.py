"""Sink quan sát trong bộ nhớ cho test (thay sink Mongo)."""

from __future__ import annotations


class MemoryEventLog:
    def __init__(self) -> None:
        self.entries: list = []

    async def write(self, entry) -> None:
        self.entries.append(entry)


class MemoryIssues:
    def __init__(self) -> None:
        self.items: list[dict] = []

    async def capture(self, exc, *, source, loc, cid, context) -> None:
        self.items.append({"exc": exc, "source": source, "loc": loc, "cid": cid, "context": context})
