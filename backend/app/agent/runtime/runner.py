"""Chạy một lượt ở lane `agent-run`: CAS
`queued → running` (tối đa một lần) → dựng model / tool / prompt từ cấu hình hiện tại → `create_agent` stream → ghi tin
nhắn của lượt → kết thúc. Checkpointer chỉ để dừng chờ duyệt. Lỗi tool trả LLM (`tools.py`); lỗi của lượt (provider,
hết giờ, quá số bước, bị huỷ, process tắt) → `failed` / `cancelled` + `agent:error`."""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from langgraph.errors import GraphRecursionError
from langgraph.types import Command
from sqlalchemy import update
from sqlmodel import select

from app.agent.chat import approvals
from app.agent.chat import service as chat
from app.agent.chat.models import AgentRun
from app.agent.config import registry
from app.agent.runtime import checkpoint, context, prompt
from app.agent.runtime.items import after_last_human, to_items
from app.agent.runtime.keys import classify
from app.agent.runtime.middleware import KeyRing, RunMiddleware, TokenWatch
from app.agent.runtime.streaming import StreamCfg, load_stream_cfg
from app.agent.runtime.tools import RunContext, build_tools
from app.agent.runtime.turn_hooks import after_run, before_run
from app.agent.trace.events import RunEmitter, buffered, cancel_key
from app.agent.trace.tracer import tracer_for
from app.auth.models import User
from app.auth.rbac import active_permission_codes, role_names, user_permissions
from app.core.connections.registry import get_connections
from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.security.principal import Principal
from app.core.settings import active_settings
from app.system.settings_store import cached_system_settings

logger = get_logger(__name__)
HEARTBEAT_SEC = 15.0
CANCEL_CHECK_SEC = 0.25
MESSAGES = {
    1000: "Lỗi hệ thống khi chạy trợ lý.",
    6011: "Nhà cung cấp mô hình báo lỗi.",
    6012: "Lượt trả lời quá thời gian cho phép.",
    6013: "Lượt trả lời vượt quá số bước tối đa.",
    6015: "Lượt trả lời bị gián đoạn — hệ thống khởi động lại. Hãy gửi lại tin nhắn.",
}


class Cancelled(Exception):
    """Người chat huỷ lượt giữa chừng (cờ Redis)."""


@dataclass
class TurnState:
    """Bước đang chạy của lượt — nhánh lỗi / huỷ lưu đúng tin của bước dưới đúng agent (nhiều bước)."""

    prior: list[BaseMessage] = field(default_factory=list)  # tin các đoạn trước của bước (resume: từ checkpoint)
    produced: list[BaseMessage] = field(default_factory=list)
    agent_id: uuid.UUID | None = None
    tried: list[uuid.UUID] = field(default_factory=list)  # key đã dùng (mọi bước)
    text_mark: int = 0  # độ dài `emitter.text` khi bước bắt đầu — tính chữ dở khi huỷ
    final_id: str | None = None  # tin assistant cuối đã lưu (đường nhiều bước tự lưu từng bước)
    done: list[BaseMessage] = field(default_factory=list)  # tin các bước đã xong (hook after_run)
    steps: int = 0  # số bước của kế hoạch (xoá thread checkpoint `<run>:<i>`)
    orchestrated: bool = False
    totals: dict[str, int] = field(default_factory=dict)
    rc: Any = None  # RunContext của entry — có ngay sau `_context` để nhánh lỗi vẫn đóng span run / chạy after_run


def _now() -> datetime:
    return datetime.now(UTC)


def _totals(run: AgentRun) -> dict[str, int]:
    return {
        "input": run.tokens_in,
        "output": run.tokens_out,
        "cache_read": run.tokens_cache_read,
        "cache_write": run.tokens_cache_write,
    }


def _token_values(totals: dict[str, int]) -> dict[str, int]:
    return {
        "tokens_in": totals["input"],
        "tokens_out": totals["output"],
        "tokens_cache_read": totals["cache_read"],
        "tokens_cache_write": totals["cache_write"],
    }


async def claim(run_id: uuid.UUID, frm: str = "queued") -> AgentRun | None:
    """CAS `queued → running` (hoặc `waiting_approval → running` khi resume) — giao lại / lượt đã huỷ → None."""
    now = _now()
    values: dict[str, Any] = {"status": "running", "heartbeat_at": now}
    if frm == "queued":
        values["started_at"] = now
    async with get_connections().postgres.rw() as s:
        stmt = update(AgentRun).where(AgentRun.id == run_id, AgentRun.status == frm).values(**values)
        if (await s.exec(stmt.returning(AgentRun.id))).first() is None:
            return None
        return (await s.exec(select(AgentRun).where(AgentRun.id == run_id))).one()


async def _heartbeat(run_id: uuid.UUID) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_SEC)
        with contextlib.suppress(Exception):
            async with get_connections().postgres.rw() as s:
                stmt = update(AgentRun).where(AgentRun.id == run_id, AgentRun.status == "running")
                await s.exec(stmt.values(heartbeat_at=_now()))


async def _context(run: AgentRun, emitter: RunEmitter, tracer, stream: StreamCfg) -> tuple[RunContext, str]:
    conns = get_connections()
    async with conns.postgres.ro() as s:
        spec = await registry.load(s, conns.redis, run.entry_agent_id)
        user = await s.get(User, run.user_id)
        if spec is None or not spec.agent.is_active:
            raise AppException(6003, status_code=404)
        if spec.model is None or spec.provider is None:
            raise AppException(6009, status_code=409)
        if user is None or not user.is_active:
            raise AppException(1005, status_code=403)
        # superadmin qua trợ lý = user thường có đủ quyền hệ thống: chỉ chạm dữ liệu của mình
        perms = await active_permission_codes(s) if user.is_superadmin else await user_permissions(s, user.id)
        principal = Principal(user_id=user.id, perms=frozenset(perms), sup=False, tenant_id=user.tenant_id)
        info = {
            "id": str(user.id),
            "name": user.name or user.email,
            "tz": user.timezone,
            "locale": user.locale,
            "roles": await role_names(s, user.id),
            "is_superadmin": user.is_superadmin,
        }
    rc = RunContext(run.id, run.session_id, info, principal, spec, emitter=emitter, tracer=tracer, stream=stream)
    return rc, spec.provider.kind


def _titles(tools: list) -> dict[str, str]:
    """Tên tool → `title` op (nhãn chấm tiến trình); tool không gắn op (handoff) giữ tên."""
    return {t.name: b.spec.title for t in tools if (b := (t.metadata or {}).get("binding")) is not None}


async def _llm_done(rc: RunContext, m: AIMessage, since: float, titles: dict[str, str]) -> None:
    used = m.usage_metadata or {}
    await rc.emitter.llm(
        status="done",
        tools=[{"name": c["name"], "title": titles.get(c["name"], c["name"])} for c in m.tool_calls],
        text=bool(m.text),
        ms=int((time.monotonic() - since) * 1000),
        tokens={"input": int(used.get("input_tokens") or 0), "output": int(used.get("output_tokens") or 0)},
    )


async def _stream(
    graph,
    inp: Any,
    rc: RunContext,
    produced: list[BaseMessage],
    watch: TokenWatch,
    thread: str,
    titles: dict[str, str] | None = None,
) -> None:
    redis = get_connections().redis
    last = mark = time.monotonic()  # mark: đầu đoạn / kết quả tool cuối — mốc tính thời gian một lần gọi mô hình
    config = {
        "recursion_limit": rc.spec.agent.recursion_limit,
        "configurable": {"thread_id": thread},
        "callbacks": [watch],
    }
    modes = ["messages", "updates"] if rc.stream.on else ["updates"]  # tắt stream: chỉ nhận tin trọn
    async for mode, chunk in graph.astream(inp, config=config, stream_mode=modes, durability="exit"):
        if mode == "messages":
            piece, meta = chunk
            if isinstance(piece, AIMessageChunk) and meta.get("langgraph_node") == "model":
                if piece.text or piece.tool_call_chunks:
                    rc.tracer.first_token()
                await rc.emitter.token(piece.text)
        elif mode == "updates":
            for node, upd in (chunk or {}).items():
                for m in upd.get("messages", []) if isinstance(upd, dict) else []:
                    if isinstance(m, AIMessage | ToolMessage):
                        produced.append(m)
                    if isinstance(m, AIMessage) and node == "model":
                        if not rc.stream.on and m.text:
                            await rc.emitter.token(m.text)  # cả câu một sự kiện; `llm()` ngay sau flush trước
                        await _llm_done(rc, m, mark, titles or {})
                        mark = time.monotonic()
                    elif isinstance(m, ToolMessage):
                        mark = time.monotonic()
        if time.monotonic() - last >= CANCEL_CHECK_SEC:
            last = time.monotonic()
            if await redis.rw.exists(cancel_key(str(rc.run_id))):
                raise Cancelled


async def _leg(
    run: AgentRun,
    rc: RunContext,
    provider: str,
    ring: KeyRing,
    totals,
    prior,
    produced,
    *,
    resuming: bool,
    thread: str | None = None,
    tail: str = "",
    first: bool = True,
) -> bool:
    """Một đoạn chạy: lượt mới hoặc resume (`Command(resume=…)` cùng thread). Trả True khi lượt dừng chờ duyệt.
    `first=False` (bước chuyên gia): span run + `before_run` đã làm ở entry; `tail` = `<task>`, `<earlier>`."""
    saver = await checkpoint.get_checkpointer()
    watch = TokenWatch()
    tools = build_tools(rc)
    if first:
        await rc.tracer.start_run(spec=rc.spec, rc=rc, tools=tools)
    thread = thread or str(run.id)
    config = {"configurable": {"thread_id": thread}}
    inp: Any = None
    if not resuming:
        cfg = await cached_system_settings()
        async with get_connections().postgres.ro() as s:
            past = await chat.history(
                s, run.session_id, cfg.chat_history_limit, exclude_run=run.id, tools=cfg.chat_history_tools
            )
            text = await chat.run_input(s, run.id)
        if first:
            await before_run(rc, text)  # chặn → 6019, chưa chọn key / gọi LLM
        async with get_connections().postgres.ro() as s:
            block = await context.build(s, run.user_id, extra=rc.extra_context)
        system = prompt.system_text(rc.spec.persona, rc.spec.agent.instructions)
        inp = {"messages": prompt.build(system, past, text + tail, block, provider=provider)}
    elif saver is None:
        raise AppException(6015, status_code=409)
    middleware = RunMiddleware(rc, ring, totals, watch, can_wait=saver is not None)
    graph = create_agent(await ring.model(), tools, middleware=[middleware], checkpointer=saver)
    if resuming:
        state = await graph.aget_state(config)
        prior.extend(after_last_human(state.values.get("messages", [])))
        for a in await approvals.of_interrupts(state.interrupts):
            decided_by = str(a.decided_by) if a.decided_by else None
            await rc.emitter.decided(
                approval_id=str(a.id), call_id=a.tool_call_id, status=a.status, decided_by=decided_by, reason=a.reason
            )
        inp = Command(resume={i.id: i.value for i in state.interrupts})
    async with asyncio.timeout(rc.spec.agent.timeout_sec):  # thời gian chờ duyệt không tính — mỗi đoạn một hạn mới
        await _stream(graph, inp, rc, produced, watch, thread, _titles(tools))
    if saver is None:
        return False
    return bool((await graph.aget_state(config)).interrupts)


async def _finish(run: AgentRun, status: str, totals, tried: list, *, code=None, error=None) -> None:
    values = {"status": status, "ended_at": _now(), "error_code": code, "error": error, **_token_values(totals)}
    if tried:
        values["credential_ids"] = sorted({*run.credential_ids, *(str(k) for k in tried)})
    async with get_connections().postgres.rw() as s:
        await s.exec(update(AgentRun).where(AgentRun.id == run.id, AgentRun.status == "running").values(**values))


async def _wait(run: AgentRun, totals, tried: list) -> None:
    """`running → waiting_approval`: dừng heartbeat, giữ checkpoint; tin nhắn của bước ghi khi bước kết thúc."""
    values: dict[str, Any] = {"status": "waiting_approval", **_token_values(totals)}
    if tried:
        values["credential_ids"] = sorted({*run.credential_ids, *(str(k) for k in tried)})
    async with get_connections().postgres.rw() as s:
        await s.exec(update(AgentRun).where(AgentRun.id == run.id, AgentRun.status == "running").values(**values))


def classify_error(exc: BaseException) -> tuple[int, str]:
    if isinstance(exc, AppException):
        return exc.code, exc.message
    if isinstance(exc, TimeoutError):
        return 6012, MESSAGES[6012]
    if isinstance(exc, GraphRecursionError):
        return 6013, MESSAGES[6013]
    if classify(exc) != "other" or type(exc).__module__.split(".")[0] in ("openai", "anthropic", "google"):
        return 6011, f"{MESSAGES[6011]} ({type(exc).__name__}: {str(exc)[:300]})"
    return 1000, MESSAGES[1000]


async def _fail(run, st: TurnState, totals, code: int, message: str, emitter: RunEmitter) -> None:
    try:
        agent_id = st.agent_id or run.entry_agent_id
        await chat.append_messages(run.session_id, run.id, agent_id, to_items(st.prior + st.produced, dict(totals)))
        await _finish(run, "failed", totals, st.tried, code=code, error=message)
        await emitter.error(code, message)
    except Exception as exc:  # noqa: BLE001 — hạ tầng hỏng lúc báo lỗi; job dọn sẽ đánh lỗi lượt
        logger.warning("không ghi được lỗi run=%s: %s", run.id, exc, extra={"loc": "agt0503"})


async def _run(
    run: AgentRun, emitter: RunEmitter, st: TurnState, *, resuming: bool, stream: StreamCfg
) -> tuple[RunContext, bool]:
    rc, provider = await _context(run, emitter, tracer_for(run, resuming=resuming), stream)
    st.rc, st.agent_id = rc, rc.spec.id
    if rc.spec.is_orchestrator:
        from app.agent.runtime import steps  # defer: tránh vòng import với runner (steps dùng `_leg` của runner)

        st.orchestrated = True
        return rc, await steps.run_plan(run, rc, st, resuming=resuming)
    ring = KeyRing(rc.spec, active_settings(), stream=rc.stream.on)
    try:
        return rc, await _leg(run, rc, provider, ring, st.totals, st.prior, st.produced, resuming=resuming)
    finally:
        st.tried.extend(ring.tried)


async def _drive(run: AgentRun, emitter: RunEmitter, *, resuming: bool, stream: StreamCfg) -> bool:
    """Chạy / chạy tiếp lượt. Trả True khi lượt vừa dừng chờ duyệt mà mọi yêu cầu đã được quyết (cần resume ngay)."""
    totals = _totals(run)
    st = TurnState(totals=totals)
    rc: RunContext | None = None
    beat = asyncio.create_task(_heartbeat(run.id))
    try:
        try:
            rc, waiting = await _run(run, emitter, st, resuming=resuming, stream=stream)
        finally:
            beat.cancel()
            rc = st.rc
    except asyncio.CancelledError:  # process tắt giữa lượt (deploy) — đánh lỗi ngay, không chờ job dọn 90 s
        await _fail(run, st, totals, 6015, MESSAGES[6015], emitter)
        await checkpoint.drop(run.id, st.steps)
        raise
    except Cancelled:
        await emitter.flush()
        done_text = "".join(m.text for m in st.produced if isinstance(m, AIMessage))
        partial = emitter.text[st.text_mark + len(done_text) :]
        items = to_items(st.prior + st.produced, dict(totals))
        if partial:
            items.append({"role": "assistant", "content": {"text": partial, "tool_calls": [], "status": "cancelled"}})
        saved = await chat.append_messages(run.session_id, run.id, st.agent_id or run.entry_agent_id, items)
        await _finish(run, "cancelled", totals, st.tried, code=6014)
        await checkpoint.drop(run.id, st.steps)
        if rc is not None:
            rc.tracer.end_run("cancelled", totals)
        await after_run(rc, "cancelled", totals, st.done + st.prior + st.produced)
        final = str(saved[-1].id) if saved else st.final_id
        await emitter.end(message_id=final, usage=dict(totals), status="cancelled")
        return False
    except Exception as exc:
        code, message = classify_error(exc)
        if code == 1000:
            logger.exception("run=%s lỗi: %s", run.id, exc, extra={"loc": "agt0500"})
        elif code == 6011:
            logger.warning("run=%s provider lỗi: %s", run.id, message, extra={"loc": "agt0508"})
        await _fail(run, st, totals, code, message, emitter)
        await checkpoint.drop(run.id, st.steps)
        await after_run(rc, "failed", totals, st.done + st.prior + st.produced)
        if rc is not None:
            rc.tracer.end_run("error", totals, message)
            await rc.tracer.flush()
        return False
    if waiting:
        await _wait(run, totals, st.tried)
        rc.tracer.end_run("waiting", totals)
        await rc.tracer.flush()
        # Yêu cầu được quyết khi lượt còn chạy (tool song song chưa xong) → lần kick resume lúc đó bị bỏ vì lượt chưa
        # `waiting_approval`; hết yêu cầu chờ thì tự resume.
        return await approvals.pending_count(run.id) == 0
    await checkpoint.drop(run.id, st.steps)
    final_id = st.final_id
    if not st.orchestrated:
        saved = await chat.append_messages(
            run.session_id, run.id, rc.spec.id, to_items(st.prior + st.produced, dict(totals))
        )
        final = next((m for m in reversed(saved) if m.role == "assistant"), None)
        final_id = str(final.id) if final else None
        st.done += st.prior + st.produced
    await _finish(run, "done", totals, st.tried)
    rc.tracer.end_run("ok", totals)
    await emitter.end(message_id=final_id, usage=dict(totals))
    await after_run(rc, "done", totals, st.done)
    await rc.tracer.flush()
    return False


async def execute(run_id: uuid.UUID | str) -> bool:
    run = await claim(uuid.UUID(str(run_id)))
    if run is None:
        logger.info("bỏ qua run=%s: không còn queued", run_id, extra={"loc": "agt0101"})
        return False
    stream = await load_stream_cfg()
    emitter = RunEmitter(get_connections().redis, run.id, run.session_id, run.user_id, window=stream.window)
    await emitter.start(agent_id=str(run.entry_agent_id), stream=stream.on)
    return await _drive(run, emitter, resuming=False, stream=stream)


async def resume(run_id: uuid.UUID | str) -> bool:
    """Chạy tiếp lượt đã chờ duyệt (mọi yêu cầu đã quyết) — process bất kỳ, `seq` tiếp nối bộ đệm."""
    run = await claim(uuid.UUID(str(run_id)), frm="waiting_approval")
    if run is None:
        logger.info("bỏ qua resume run=%s: không còn chờ duyệt", run_id, extra={"loc": "agt0102"})
        return False
    redis = get_connections().redis
    events = await buffered(redis, str(run.id)) or []
    start = events[-1]["data"]["seq"] if events else 0
    stream = await load_stream_cfg()
    emitter = RunEmitter(redis, run.id, run.session_id, run.user_id, window=stream.window, start_seq=start)
    return await _drive(run, emitter, resuming=True, stream=stream)
