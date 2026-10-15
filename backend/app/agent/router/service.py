"""Chọn chuyên gia cho tin nhắn: router = `create_agent(model orchestrator, tools=[],
response_format=ToolStrategy(RouteDecision))` qua `RunMiddleware` + `Tracer` (R19) — key ring của orchestrator, token
tính vào entry. Slug lạ bị bỏ; không có bước + không hỏi lại / lỗi → `general` (R11: WARNING + `fallback` trên span);
lượt trước hỏi lại + router chỉ ra `general` → giữ chuyên gia lượt trước (luật bám)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy

from app.agent.chat.models import AgentMessage
from app.agent.config.registry import RouteSpec
from app.agent.router import prompt
from app.agent.router.schemas import RouteDecision, RouteStep
from app.agent.runtime.middleware import KeyRing, RunMiddleware, TokenWatch
from app.agent.runtime.plan import Plan, PlanStep
from app.agent.runtime.tools import RunContext
from app.core.logging import get_logger

logger = get_logger(__name__)
GENERAL = "general"
RECURSION = 6


@dataclass
class RouteInput:
    text: str
    past: list[AgentMessage]
    names: dict[uuid.UUID, str]  # agent_id → slug (tin assistant cũ)
    last_agent: str | None
    context: str


def asked_back(past: list[AgentMessage]) -> bool:
    for m in reversed(past):
        if m.role == "assistant" and (text := ((m.content or {}).get("text") or "").strip()):
            return text.endswith("?")
        if m.role == "user":
            return False
    return False


def _fallback(routes: dict[str, RouteSpec]) -> RouteSpec | None:
    return routes.get(GENERAL) or next(iter(routes.values()), None)


def sanitize(
    decision: RouteDecision | None, routes: dict[str, RouteSpec], *, last_agent: str | None, sticky_ok: bool
) -> tuple[list[RouteStep], str | None, dict[str, Any]]:
    """(bước hợp lệ, câu hỏi lại, ghi chú cho trace) — không bao giờ trả rỗng cả hai khi có route."""
    note: dict[str, Any] = {}
    steps = [s for s in (decision.steps if decision else []) if s.agent in routes][:3]
    clarify = (decision.clarify or "").strip() or None if decision and not steps else None
    if decision is None:
        note["fallback"] = "no_decision"
    elif decision.steps and not steps:
        note["fallback"] = "unknown_agent"
    if sticky_ok and last_agent in routes and [s.agent for s in steps] in ([], [GENERAL]) and not clarify:
        steps, note["sticky"] = [RouteStep(agent=last_agent, task="")], last_agent
        note.pop("fallback", None)
    if not steps and not clarify:
        general = _fallback(routes)
        if general is not None:
            steps = [RouteStep(agent=general.slug, task="")]
            note.setdefault("fallback", "empty")
    return steps, clarify, note


async def decide(rc: RunContext, ring: KeyRing, totals: dict[str, int], inp: RouteInput) -> Plan:
    routes = {r.slug: r for r in rc.spec.routes}
    back = asked_back(inp.past)
    messages = prompt.build(
        rc.spec.agent.instructions,
        rc.spec.routes,
        text=inp.text,
        recent=prompt.recent_lines(inp.past, inp.names),
        last_agent=inp.last_agent,
        asked_back=back,
        context=inp.context,
    )
    trace_in = {"text": inp.text[:2000], "routes": list(routes), "last_agent": inp.last_agent, "asked_back": back}
    decision: RouteDecision | None = None
    failed = False
    async with rc.tracer.router(trace_in) as span:
        watch = TokenWatch()
        try:
            graph = create_agent(
                await ring.model(),
                [],
                middleware=[RunMiddleware(rc, ring, totals, watch, can_wait=False, purpose="router")],
                response_format=ToolStrategy(RouteDecision),
            )
            out = await graph.ainvoke(
                {"messages": messages}, config={"callbacks": [watch], "recursion_limit": RECURSION}
            )
            found = out.get("structured_response")
            decision = found if isinstance(found, RouteDecision) else None
        except Exception as exc:  # noqa: BLE001 — router hỏng không chặn lượt: rơi về general (R11)
            failed = True
            logger.warning(
                "router run=%s lỗi: %s; DEFAULTS_APPLIED=[route=general]", rc.run_id, exc, extra={"loc": "agt0801"}
            )
        steps, clarify, note = sanitize(decision, routes, last_agent=inp.last_agent, sticky_ok=back)
        if note.get("fallback") and not failed:
            logger.warning(
                "router run=%s rơi về %s (%s); DEFAULTS_APPLIED=[route]",
                rc.run_id,
                steps[0].agent if steps else "-",
                note["fallback"],
                extra={"loc": "agt0802"},
            )
        raw = decision.model_dump() if decision else None
        if hasattr(span, "output"):
            span.output = {"decision": raw, "steps": [s.model_dump() for s in steps], "clarify": clarify, **note}
    plan_steps = [
        PlanStep(agent_id=routes[s.agent].agent_id, slug=s.agent, name=routes[s.agent].name, task=s.task) for s in steps
    ]
    return Plan(steps=plan_steps, clarify=clarify, router={"decision": raw, **note})
