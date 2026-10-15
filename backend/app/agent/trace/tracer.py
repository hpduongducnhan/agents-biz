"""Trace của một lượt (R19 — chỗ duy nhất dựng span): cây `run → llm → tool → approval`
+ `hook`, raw HTTP của mọi lần gọi provider (`http_capture`, đã che).

- Span `run` id = `run_id`; span tool / approval id suy từ `tool_call_id` / `approval_id` → đoạn resume (process khác)
  cập nhật cùng span thay vì tạo bản trùng.
- Span `tool` là con của span `llm` sinh ra tool call đó.
- Ghi nền qua `TraceSink`; lỗi ghi chỉ log `agt0505` — trace hỏng không bao giờ làm hỏng lượt."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.errors import GraphBubbleUp

from app.agent.runtime.keys import classify
from app.agent.runtime.tools import hidden_tools
from app.agent.trace.events import redact
from app.agent.trace.noop import NoopTracer
from app.agent.trace.spans import (
    SPAN,
    AgentStepSpan,
    ApprovalSpan,
    HookSpan,
    HttpRaw,
    LlmSpan,
    RouterSpan,
    RunSpan,
    SpanBase,
    ToolSpan,
)
from app.core.cid import get_cid
from app.core.httpx_log import http_capture
from app.core.logging import get_logger
from app.core.redact import redact_text
from app.observability.sinks import get_sinks
from app.system import settings_store

logger = get_logger(__name__)
NS = uuid.UUID("0b8f4a52-6c1e-4d0b-9a57-3e2f1c9d8a64")
TEXT_LIMIT = 20_000
RESULT_LIMIT = 2_000
SPAN_TTL = timedelta(days=90)
RAW_TTL = timedelta(days=7)
ERROR_LIMIT = 500


def _tenant_of(run: Any) -> str | None:
    tid = getattr(run, "tenant_id", None)
    return str(tid) if tid is not None else None


@dataclass(frozen=True)
class CallMeta:
    """Ngữ cảnh một lần gọi LLM cho document `agent_llm_calls`: gọi ở đâu, agent, model, provider."""

    purpose: str  # router | agent
    agent_id: str
    agent_slug: str
    model_id: str  # id dòng agent_models
    model: str  # mã model phía provider
    provider_id: str
    provider_kind: str


def _now() -> datetime:
    return datetime.now(UTC)


def _ms(since: datetime) -> int:
    return int((_now() - since).total_seconds() * 1000)


def _text(m: BaseMessage) -> str:
    return m.text if hasattr(m, "text") else str(m.content)


def tracer_for(run, *, resuming: bool):
    """Mongo bật → `Tracer`; tắt → `NoopTracer` (cùng giao diện — R12)."""
    sink = get_sinks().traces
    return Tracer(run, sink, resuming=resuming) if sink.enabled else NoopTracer()


class Tracer:
    def __init__(self, run, sink, *, resuming: bool) -> None:
        self.run, self.sink, self.resuming = run, sink, resuming
        self.run_id = str(run.id)
        self._tasks: set[asyncio.Task] = set()
        self._seq = 0
        self._llm: LlmSpan | None = None
        self._llm_of_call: dict[str, str] = {}
        self._run_span: RunSpan | None = None
        self._scope = self.run_id  # span cha của llm / tool: run, hoặc router / agent đang mở
        # gom cho span run: chuỗi chuyên gia, model, chi phí, số lần gọi LLM lỗi
        self._agents: dict[int, str] = {}
        self._models: list[str] = []
        self._cost = 0.0
        self._llm_errors = 0
        self._span_ttl, self._raw_ttl = SPAN_TTL, RAW_TTL  # cài đặt `span_ttl_days` / `raw_http_ttl_days` — start_run

    # ── ghi nền ──────────────────────────────────────────────────────────────
    def _later(self, coro) -> None:
        task = asyncio.create_task(self._guard(coro))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _guard(self, coro) -> None:
        try:
            await coro
        except Exception as exc:  # noqa: BLE001 — trace hỏng không được làm hỏng lượt chạy
            logger.warning("ghi trace lỗi run=%s: %s", self.run_id, exc, extra={"loc": "agt0505"})

    def _save(self, span: SpanBase) -> None:
        self._later(self.sink.save_span(span.model_dump(mode="python")))

    async def flush(self, timeout: float = 2.0) -> None:
        if self._tasks:
            await asyncio.wait(set(self._tasks), timeout=timeout)

    def _fields(self, *, id: str | None, parent: str | None, name: str) -> dict[str, Any]:
        self._seq += 1
        run = self.run
        return {
            "id": id or str(uuid.uuid4()),
            "run_id": self.run_id,
            "parent_id": parent,
            "name": name,
            "seq": self._seq,
            "agent_id": str(run.entry_agent_id),
            "session_id": str(run.session_id),
            "user_id": str(run.user_id),
            "tenant_id": _tenant_of(run),
            "cid": get_cid(),
            "expire_at": _now() + self._span_ttl,
        }

    async def _existing(self, span_id: str):
        if not self.resuming:
            return None
        with contextlib.suppress(Exception):
            doc = await self.sink.get_span(span_id)
            return SPAN.validate_python(doc) if doc else None
        return None

    # ── run ──────────────────────────────────────────────────────────────────
    async def start_run(self, *, spec, rc, tools) -> None:
        try:
            cfg = await settings_store.cached_system_settings()
            self._span_ttl, self._raw_ttl = timedelta(days=cfg.span_ttl_days), timedelta(days=cfg.raw_http_ttl_days)
        except Exception as exc:  # noqa: BLE001 — đọc cài đặt hỏng: TTL mặc định (R11), trace vẫn ghi
            logger.warning(
                "đọc TTL trace lỗi: %s; DEFAULTS_APPLIED=[span_ttl_days=90, raw_http_ttl_days=7]",
                exc,
                extra={"loc": "agt0507"},
            )
        if self.resuming:
            with contextlib.suppress(Exception):
                self._seq = await self.sink.count_spans(self.run_id)
        span = await self._existing(self.run_id)
        if not isinstance(span, RunSpan):
            span = RunSpan(**self._fields(id=self.run_id, parent=None, name=spec.agent.name))
        span.status, span.end = "running", None
        self._agents.update(enumerate(span.agents))
        self._models.extend(m for m in span.models if m not in self._models)
        self._cost, self._llm_errors = span.cost or 0.0, span.llm_errors
        if not self._agents and not spec.is_orchestrator:
            self._agents[0] = spec.agent.slug
        if not span.input:
            span.input = {
                "agent": {"id": str(spec.id), "slug": spec.agent.slug, "name": spec.agent.name},
                "model": {
                    "model_id": spec.model.model_id,
                    "name": spec.model.name,
                    "provider": spec.provider.name,
                    "kind": spec.provider.kind,
                    "params": {**(spec.provider.default_params or {}), **(spec.agent.params_override or {})},
                },
                "user": {k: rc.user.get(k) for k in ("id", "name", "roles", "is_superadmin")},
                "tools": [{"name": t.name, "description": t.description, "schema": t.args_schema} for t in tools],
                "tools_hidden": hidden_tools(rc) if tools else {},  # tool không đưa cho LLM + lý do
                "stream": rc.stream.trace(),  # cài đặt stream của lượt (R11)
            }
        self._run_span = span
        self._save(span)

    def end_run(self, status: str, totals: dict[str, int], error: str | None = None) -> None:
        span = self._run_span
        if span is None:
            return
        span.status, span.error = status, error
        span.end = None if status == "waiting" else _now()
        span.usage = dict(totals)
        span.agents = [self._agents[i] for i in sorted(self._agents)]
        span.models = list(self._models)
        span.cost = round(self._cost, 6)
        span.llm_errors = self._llm_errors
        self._save(span)

    # ── llm ──────────────────────────────────────────────────────────────────
    @contextlib.asynccontextmanager
    async def llm(
        self, messages: list[BaseMessage], params: dict[str, Any], credential=None, call: CallMeta | None = None
    ):
        span = LlmSpan(**self._fields(id=None, parent=self._scope, name="llm"))
        span.input = {"prompt": _prompt(messages), "params": params}
        if credential is not None:
            span.credential_id, span.masked_hint = str(credential.id), credential.masked_hint
        if call is not None and call.model not in self._models:
            self._models.append(call.model)
        records: list[dict] = []
        self._llm = span
        try:
            with http_capture(records.append):
                yield span
            span.status = "ok"
        except asyncio.CancelledError:
            span.status = "cancelled"
            raise
        except BaseException as exc:
            span.status, span.error = "error", f"{type(exc).__name__}: {str(exc)[:RESULT_LIMIT]}"
            span.error_kind = classify(exc) if isinstance(exc, Exception) else "other"
            self._llm_errors += 1
            raise
        finally:
            span.end = _now()
            self._llm = None
            self._cost += span.cost or 0.0
            if call is not None:
                self._later(self.sink.save_call(self._call_doc(span, call)))
            for rec in records:
                raw = HttpRaw(
                    id=str(uuid.uuid4()),
                    span_id=span.id,
                    run_id=self.run_id,
                    method=rec.get("method", ""),
                    url=rec.get("url", ""),
                    started_at=str(rec.get("started_at") or ""),
                    ms=rec.get("ms"),
                    request=rec.get("request") or {},
                    response=rec.get("response"),
                    error=rec.get("error"),
                    expire_at=_now() + self._raw_ttl,
                )
                span.raw_ids.append(raw.id)
                self._later(self.sink.insert_raw(raw.model_dump(mode="python")))
            self._save(span)

    def _call_doc(self, span: LlmSpan, call: CallMeta) -> dict[str, Any]:
        """Một lần gọi LLM → document `agent_llm_calls` (usage giám sát). `input_tokens` không gồm phần cache."""
        u = span.usage or {}
        cache_read, cache_write = int(u.get("cache_read") or 0), int(u.get("cache_write") or 0)
        end = span.end or _now()
        return {
            "id": span.id,
            "at": span.start,
            "expire_at": _now() + self._span_ttl,
            "run_id": self.run_id,
            "session_id": str(self.run.session_id),
            "user_id": str(self.run.user_id),
            "tenant_id": _tenant_of(self.run),
            "entry_agent_id": str(self.run.entry_agent_id),
            "agent_id": call.agent_id,
            "agent_slug": call.agent_slug,
            "purpose": call.purpose,
            "model_id": call.model_id,
            "model": call.model,
            "provider_id": call.provider_id,
            "provider_kind": call.provider_kind,
            "credential_id": span.credential_id,
            "key_hint": span.masked_hint,
            "status": span.status,
            "error_kind": span.error_kind,
            "error": redact_text(span.error)[:ERROR_LIMIT] if span.error else None,
            "latency_ms": max(0, int((end - span.start).total_seconds() * 1000)),
            "ttft_ms": span.ttft_ms,
            "requests": 1,
            "input_tokens": max(0, int(u.get("input") or 0) - cache_read - cache_write),
            "output_tokens": int(u.get("output") or 0),
            "cache_read_tokens": cache_read,
            "cache_write_tokens": cache_write,
            "cost": float(span.cost or 0.0),
        }

    def llm_response(self, span: LlmSpan, message: AIMessage) -> None:
        if not isinstance(span, LlmSpan):
            return
        calls = [{"id": c["id"], "name": c["name"], "args": redact(c.get("args", {}))} for c in message.tool_calls]
        for c in calls:
            self._llm_of_call[c["id"]] = span.id
        meta = message.response_metadata or {}
        used = message.usage_metadata or {}
        details = used.get("input_token_details") or {}
        span.name = str(meta.get("model_name") or meta.get("model") or span.name)
        span.output = {
            "text": _text(message)[:TEXT_LIMIT],
            "tool_calls": calls,
            "finish_reason": meta.get("finish_reason"),
        }
        span.usage = {
            "input": int(used.get("input_tokens") or 0),
            "output": int(used.get("output_tokens") or 0),
            "cache_read": int(details.get("cache_read") or 0),
            "cache_write": int(details.get("cache_creation") or 0),
        }

    def first_token(self) -> None:
        if self._llm is not None and self._llm.ttft_ms is None:
            self._llm.ttft_ms = _ms(self._llm.start)

    # ── tool / approval / hook ───────────────────────────────────────────────
    async def _parent_llm(self, call_id: str) -> str:
        if call_id in self._llm_of_call:
            return self._llm_of_call[call_id]
        with contextlib.suppress(Exception):  # resume: llm sinh call nằm ở đoạn trước
            found = await self.sink.llm_of_call(self.run_id, call_id)
            if found:
                return found
        return self._scope

    @contextlib.asynccontextmanager
    async def tool(self, call: dict[str, Any], binding):
        span_id = str(uuid.uuid5(NS, f"{self.run_id}:tool:{call['id']}"))
        span = await self._existing(span_id)
        if not isinstance(span, ToolSpan):
            parent = await self._parent_llm(call["id"])
            span = ToolSpan(**self._fields(id=span_id, parent=parent, name=call["name"]))
        operation = binding.spec.name if binding is not None else None
        span.status, span.end = "running", None
        span.input = {**span.input, "call_id": call["id"], "args": redact(call.get("args", {})), "operation": operation}
        try:
            yield span
        except GraphBubbleUp:  # interrupt — chờ duyệt
            span.status = "waiting"
            raise
        except BaseException as exc:
            span.status, span.error = "error", f"{type(exc).__name__}: {str(exc)[:RESULT_LIMIT]}"
            raise
        finally:
            if span.status != "waiting":
                span.end = _now()
            self._save(span)

    def tool_result(self, span, result: Any, *, real_args: dict[str, Any] | None = None) -> None:
        if not isinstance(span, ToolSpan):
            return
        if real_args is not None:
            span.input = {**span.input, "real_args": redact(real_args)}
        failed = isinstance(result, ToolMessage) and result.status == "error"
        content = result.content if isinstance(result, ToolMessage) else str(result)
        text = content if isinstance(content, str) else str(content)
        span.status = "error" if failed else "ok"
        span.output = {"result": text[:RESULT_LIMIT]}
        if failed:
            span.error = text[:RESULT_LIMIT]

    def approval(self, req, *, parent: str = "") -> None:
        span_id = str(uuid.uuid5(NS, f"{self.run_id}:approval:{req.id}"))
        span = ApprovalSpan(**self._fields(id=span_id, parent=parent or self.run_id, name=req.operation))
        span.start = req.created_at
        span.input = {"approval_id": str(req.id), "args": redact(req.args), "expires_at": req.expires_at.isoformat()}
        if req.status == "pending":
            span.status = "waiting"
        else:
            decided = req.decided_at or _now()
            span.status, span.end = ("ok" if req.status == "approved" else "error"), decided
            span.output = {
                "status": req.status,
                "decided_by": str(req.decided_by) if req.decided_by else None,
                "reason": req.reason,
                "wait_ms": max(0, int((decided - req.created_at).total_seconds() * 1000)),
            }
        self._later(self._upsert_approval(span))

    async def _upsert_approval(self, span: ApprovalSpan) -> None:
        old = await self.sink.get_span(span.id)
        if old is not None:
            span.seq = old.get("seq", span.seq)
        await self.sink.save_span(span.model_dump(mode="python"))

    # ── router / bước chuyên gia ──────────────────────────────────────
    @contextlib.asynccontextmanager
    async def router(self, input: dict[str, Any]):
        span = RouterSpan(
            **self._fields(id=str(uuid.uuid5(NS, f"{self.run_id}:router")), parent=self.run_id, name="router")
        )
        span.input = input
        prev, self._scope = self._scope, span.id
        try:
            yield span
            span.status = "ok"
        except BaseException as exc:
            span.status, span.error = "error", f"{type(exc).__name__}: {str(exc)[:RESULT_LIMIT]}"
            raise
        finally:
            self._scope, span.end = prev, _now()
            self._save(span)

    @contextlib.asynccontextmanager
    async def agent(self, index: int, input: dict[str, Any]):
        span_id = str(uuid.uuid5(NS, f"{self.run_id}:agent:{index}"))
        span = await self._existing(span_id)
        if not isinstance(span, AgentStepSpan):
            span = AgentStepSpan(**self._fields(id=span_id, parent=self.run_id, name=str(input.get("slug") or "agent")))
        span.status, span.end, span.input = "running", None, input
        self._agents[index] = str(input.get("slug") or "agent")
        prev, self._scope = self._scope, span.id
        try:
            yield span
            if span.status == "running":
                span.status = "ok"
        except GraphBubbleUp:  # chờ duyệt trong bước này
            span.status = "waiting"
            raise
        except BaseException as exc:
            span.status, span.error = "error", f"{type(exc).__name__}: {str(exc)[:RESULT_LIMIT]}"
            raise
        finally:
            self._scope = prev
            if span.status != "waiting":
                span.end = _now()
            self._save(span)

    def mark_waiting(self, span) -> None:
        """Bước chuyên gia dừng chờ duyệt (`_leg` trả True, không ném) — span `agent` giữ `waiting`, chưa có `end`."""
        if isinstance(span, AgentStepSpan):
            span.status = "waiting"

    def hook(self, hook, point: str, result: dict[str, Any], *, parent: str | None = None, error: str | None = None):
        span = HookSpan(**self._fields(id=None, parent=parent or self._scope, name=hook.name or hook.action))
        span.input = {"hook_id": str(hook.id), "point": point, "action": hook.action}
        span.output = result
        span.status, span.error, span.end = ("error" if error else "ok"), error, _now()
        self._save(span)


def _prompt(messages: list[BaseMessage]) -> dict[str, Any]:
    """System + tin mới (có khối context) nguyên văn; lịch sử = số tin; phần của lượt (tool call / kết quả sau tin mới)
    ghi gọn."""
    system = next((_text(m) for m in messages if isinstance(m, SystemMessage)), "")
    last_human = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1)
    history = [m for m in messages[:last_human] if not isinstance(m, SystemMessage)]
    turn = []
    for m in messages[last_human + 1 :] if last_human >= 0 else []:
        item: dict[str, Any] = {"role": m.type, "content": _text(m)[:TEXT_LIMIT]}
        if isinstance(m, AIMessage) and m.tool_calls:
            item["tool_calls"] = [
                {"id": c["id"], "name": c["name"], "args": redact(c.get("args", {}))} for c in m.tool_calls
            ]
        if isinstance(m, ToolMessage):
            item["tool_call_id"] = m.tool_call_id
        turn.append(item)
    return {
        "system": system,
        "history_count": len(history),
        "new": _text(messages[last_human]) if last_human >= 0 else "",
        "turn": turn,
    }
