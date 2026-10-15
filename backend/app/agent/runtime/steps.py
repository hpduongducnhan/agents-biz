"""Lượt có router: `before_run` của entry → router → `agent:route` → chạy lần lượt các bước chuyên gia (mỗi bước
một `create_agent`, thread checkpoint `<run_id>:<i>`, key ring + hook riêng) → lưu tin từng bước dưới agent của bước.
`agent_runs.plan` lưu sau quyết định + sau mỗi bước — chờ duyệt ở bước i thì resume chạy tiếp bước i rồi các bước sau.
`handoff` chèn bước mới ngay sau bước hiện tại (≤ 2 / lượt)."""

from __future__ import annotations

import uuid

from sqlalchemy import update
from sqlmodel import select

from app.agent.chat import service as chat
from app.agent.chat.models import AgentMessage, AgentRun, AgentSession
from app.agent.config import registry
from app.agent.config.models import Agent
from app.agent.config.registry import AgentSpec
from app.agent.router import prompt as router_prompt
from app.agent.router.service import RouteInput, decide
from app.agent.runtime import runner
from app.agent.runtime.items import to_items
from app.agent.runtime.middleware import KeyRing
from app.agent.runtime.plan import MAX_HANDOFFS, Plan, PlanStep, load
from app.agent.runtime.tools import HandoffState, RunContext, hidden_tools
from app.agent.runtime.turn_hooks import before_run
from app.core.connections.registry import get_connections
from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.settings import active_settings
from app.system.settings_store import cached_system_settings

logger = get_logger(__name__)
EARLIER_CAP = 1500
NO_REPLIES = {
    "vi": "Mình chưa làm xong việc này. Bạn nói rõ hơn giúp mình (việc gì, của ai, khi nào…) hoặc thử lại nhé.",
    "en": "I couldn't finish this one. Could you say a bit more (what, whose, when…) or try again?",
}
NO_REPLY = NO_REPLIES["vi"]


def no_reply_text(locale: str | None) -> str:
    """Câu dự phòng theo ngôn ngữ của người chat (persona trung tính — D7)."""
    return NO_REPLIES.get(str(locale or "vi"), NO_REPLY)


HISTORY_FOR_ROUTER = 12


async def save_plan(run_id: uuid.UUID, plan: Plan) -> None:
    async with get_connections().postgres.rw() as s:
        await s.exec(update(AgentRun).where(AgentRun.id == run_id).values(plan=plan.dump()))


async def _spec(agent_id: uuid.UUID) -> AgentSpec:
    conns = get_connections()
    async with conns.postgres.ro() as s:
        spec = await registry.load(s, conns.redis, agent_id)
    if spec is None or not spec.agent.is_active:
        raise AppException(6003, status_code=404)
    if spec.model is None or spec.provider is None:
        raise AppException(6009, status_code=409)
    return spec


def _step_context(entry: RunContext, spec: AgentSpec, plan: Plan, step: PlanStep) -> RunContext:
    rc = RunContext(
        entry.run_id,
        entry.session_id,
        entry.user,
        entry.principal,
        spec,
        emitter=entry.emitter,
        tracer=entry.tracer,
        entry_id=entry.spec.id,
        stream=entry.stream,
    )
    targets = {r.slug: r for r in entry.spec.routes}
    came_from = plan.steps[plan.cursor - 1].slug if step.via == "handoff" and plan.cursor > 0 else None
    rc.handoff = HandoffState(
        targets=targets, left=MAX_HANDOFFS - plan.handoffs, current=step.slug, came_from=came_from
    )
    return rc


async def _route(run: AgentRun, entry: RunContext, st: runner.TurnState) -> Plan:
    conns = get_connections()
    limit = min(HISTORY_FOR_ROUTER, (await cached_system_settings()).chat_history_limit)
    async with conns.postgres.ro() as s:
        text = await chat.run_input(s, run.id)
        past = await chat.history(s, run.session_id, limit, exclude_run=run.id, tools=False)
        session = await s.get(AgentSession, run.session_id)
        ids = {m.agent_id for m in past if m.agent_id} | (
            {session.last_agent_id} if session and session.last_agent_id else set()
        )
        rows = (await s.exec(select(Agent.id, Agent.slug).where(Agent.id.in_(ids)))).all() if ids else []
        names = dict(rows)
        ctx = await router_prompt.short_context(s, run.user_id)
    await before_run(entry, text)
    last = names.get(session.last_agent_id) if session and session.last_agent_id else None
    ring = KeyRing(entry.spec, active_settings(), stream=entry.stream.on)
    try:
        plan = await decide(
            entry, ring, st.totals, RouteInput(text=text, past=past, names=names, last_agent=last, context=ctx)
        )
    finally:
        st.tried.extend(ring.tried)
    return plan


async def _clarify(run: AgentRun, entry: RunContext, st: runner.TurnState, question: str) -> None:
    await entry.emitter.token(question)
    await entry.emitter.flush()
    item = {"role": "assistant", "content": {"text": question, "tool_calls": [], "kind": "clarify"}}
    saved = await chat.append_messages(run.session_id, run.id, entry.spec.id, [item])
    st.final_id = str(saved[-1].id) if saved else None


async def _answered(run_id: uuid.UUID) -> bool:
    """Lượt đã có ít nhất một câu trả lời bằng chữ (của bước nào cũng được)?"""
    stmt = select(AgentMessage.content).where(AgentMessage.run_id == run_id, AgentMessage.role == "assistant")
    async with get_connections().postgres.ro() as s:
        rows = (await s.exec(stmt)).all()
    return any(((c or {}).get("text") or "").strip() for c in rows)


async def _no_reply(run: AgentRun, entry: RunContext, st: runner.TurnState) -> None:
    """Mọi bước kết thúc mà không có chữ (vd bước cuối dừng ở lỗi tool) → câu dự phòng, người dùng không bị bỏ lửng."""
    logger.warning(
        "run=%s kết thúc không có câu trả lời — gửi câu dự phòng; DEFAULTS_APPLIED=[reply=fallback]",
        run.id,
        extra={"loc": "agt0104"},
    )
    text = no_reply_text(entry.user.get("locale"))
    await entry.emitter.token(text)
    await entry.emitter.flush()
    item = {"role": "assistant", "content": {"text": text, "tool_calls": [], "kind": "fallback"}}
    saved = await chat.append_messages(run.session_id, run.id, entry.spec.id, [item])
    st.final_id = str(saved[-1].id) if saved else st.final_id


async def _earlier(run_id: uuid.UUID, names: dict[uuid.UUID, str]) -> str:
    """Tin các bước trước trong lượt (chữ + kết quả tool rút gọn) → khối `<earlier>` cho bước sau."""
    async with get_connections().postgres.ro() as s:
        stmt = select(AgentMessage).where(AgentMessage.run_id == run_id, AgentMessage.role != "user")
        rows = (await s.exec(stmt.order_by(AgentMessage.seq))).all()
    lines = []
    for m in rows:
        c = m.content or {}
        who = names.get(m.agent_id, "?")
        if m.role == "assistant" and c.get("text"):
            lines.append(f"[{who}] {c['text'][:EARLIER_CAP]}")
        elif m.role == "tool":
            lines.append(f"[{who} → {c.get('name')}] {(c.get('text') or '')[:EARLIER_CAP]}")
    return "\n".join(lines)


SCOPE = (
    "<scope>Lượt này chia {n} bước, bạn làm bước {i}. Chỉ làm đúng việc trong <task>: phần việc khác của tin nhắn "
    "đã giao cho chuyên gia khác ở bước khác — không làm thay, không ghi sổ ngoài phạm vi <task>. Việc đã làm trong "
    "<earlier> thì không làm lại; thấy trùng thì báo người dùng thay vì ghi thêm.</scope>"
)


def _tail(step: PlanStep, earlier: str, *, index: int = 0, total: int = 1) -> str:
    out = f"\n\n<task>{step.task}</task>" if step.task else ""
    if total > 1:
        out += "\n\n" + SCOPE.format(n=total, i=index + 1)
    if earlier:
        out += f"\n\n<earlier>\n{earlier}\n</earlier>"
    return out


async def run_plan(run: AgentRun, entry: RunContext, st: runner.TurnState, *, resuming: bool) -> bool:
    """Trả True khi lượt dừng chờ duyệt (plan đã lưu, `cursor` = bước đang chờ)."""
    plan = load(run.plan) if resuming else None
    await entry.tracer.start_run(spec=entry.spec, rc=entry, tools=[])
    if plan is None:
        plan = await _route(run, entry, st)
        await save_plan(run.id, plan)
        steps = [{"agent_id": str(x.agent_id), "slug": x.slug, "name": x.name, "task": x.task} for x in plan.steps]
        await entry.emitter.route(steps=steps, clarify=plan.clarify)
        if plan.clarify:
            await _clarify(run, entry, st, plan.clarify)
            return False
    names = {x.agent_id: x.name for x in plan.steps}
    resume_at = plan.cursor if resuming else -1
    while not plan.done:
        i, step = plan.cursor, plan.current
        st.steps = max(st.steps, len(plan.steps))
        rc = _step_context(entry, await _spec(step.agent_id), plan, step)
        await entry.emitter.flush()  # chữ còn gom của bước trước giữ `by` cũ
        st.prior, st.produced, st.agent_id, st.text_mark = [], [], step.agent_id, len(entry.emitter.text)
        entry.emitter.by = {"agent_id": str(step.agent_id), "slug": step.slug, "name": step.name}
        earlier = "" if i == resume_at else await _earlier(run.id, names)
        ring = KeyRing(rc.spec, active_settings(), stream=rc.stream.on)
        trace_in = {
            "agent_id": str(step.agent_id),
            "slug": step.slug,
            "task": step.task,
            "via": step.via,
            "tools_hidden": hidden_tools(rc),
        }
        try:
            async with entry.tracer.agent(i, trace_in) as span:
                waiting = await runner._leg(
                    run,
                    rc,
                    rc.spec.provider.kind,
                    ring,
                    st.totals,
                    st.prior,
                    st.produced,
                    resuming=i == resume_at,
                    thread=f"{run.id}:{i}",
                    tail=_tail(step, earlier, index=i, total=len(plan.steps)),
                    first=False,
                )
                if waiting:
                    entry.tracer.mark_waiting(span)
        finally:
            st.tried.extend(ring.tried)
        if waiting:
            await save_plan(run.id, plan)
            return True
        saved = await chat.append_messages(
            run.session_id, run.id, step.agent_id, to_items(st.prior + st.produced, dict(st.totals))
        )
        final = next((m for m in reversed(saved) if m.role == "assistant"), None)
        st.final_id = str(final.id) if final else st.final_id
        st.done += st.prior + st.produced
        st.prior, st.produced = [], []
        handoff = rc.handoff
        if handoff.to and handoff.to in handoff.targets:
            target = handoff.targets[handoff.to]
            nxt = PlanStep(
                agent_id=target.agent_id, slug=target.slug, name=target.name, task=handoff.reason, via="handoff"
            )
            plan.insert_after_current(nxt)
            names[target.agent_id] = target.name
        plan.cursor = i + 1
        await save_plan(run.id, plan)
    await entry.emitter.flush()
    entry.emitter.by = None
    st.steps = max(st.steps, len(plan.steps))
    if not await _answered(run.id):
        await _no_reply(run, entry, st)
    return False
