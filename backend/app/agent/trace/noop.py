"""Tracer rỗng — cùng giao diện với `Tracer` (sp3a3) để runner / middleware gọi một kiểu dù trace bật hay không."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any


class NoopSpan:
    id = ""


class NoopTracer:
    async def start_run(self, **_: Any) -> None:
        return None

    @contextlib.asynccontextmanager
    async def llm(
        self, messages: Any, params: Any, credential: Any = None, call: Any = None
    ) -> AsyncIterator[NoopSpan]:
        yield NoopSpan()

    def llm_response(self, span: Any, message: Any) -> None:
        return None

    def first_token(self) -> None:
        return None

    @contextlib.asynccontextmanager
    async def tool(self, call: Any, binding: Any) -> AsyncIterator[NoopSpan]:
        yield NoopSpan()

    def tool_result(self, span: Any, result: Any, *, real_args: Any = None) -> None:
        return None

    def approval(self, req: Any, *, parent: str = "") -> None:
        return None

    def end_run(self, status: str, totals: dict[str, int], error: str | None = None) -> None:
        return None

    async def flush(self) -> None:
        return None

    def hook(
        self, hook: Any, point: str, result: dict[str, Any], *, parent: str | None = None, error: str | None = None
    ):
        return None

    @contextlib.asynccontextmanager
    async def router(self, input: Any) -> AsyncIterator[NoopSpan]:
        yield NoopSpan()

    @contextlib.asynccontextmanager
    async def agent(self, index: int, input: Any) -> AsyncIterator[NoopSpan]:
        yield NoopSpan()

    def mark_waiting(self, span: Any) -> None:
        return None
