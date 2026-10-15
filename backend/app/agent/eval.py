"""`bw agent-eval`: chạy CHỈ router của "Assistant" bằng model thật đang cấu hình trên bộ câu `tests/agent_eval/*.yaml`
(nền `intents_vi.yaml` + câu của từng module); đúng = chuyên gia bước đầu khớp (hoặc có hỏi lại khi bộ câu đòi hỏi lại).
Không chạy trong CI (cần key). Token / chi phí ghi như lượt thường dưới user cố định `EVAL_USER`."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.agent.chat.models import AgentMessage
from app.agent.config import registry
from app.agent.config.seed import ASSISTANT
from app.agent.router.service import RouteInput, decide
from app.agent.runtime.middleware import KeyRing
from app.agent.runtime.plan import Plan
from app.agent.runtime.tools import RunContext
from app.agent.trace.noop import NoopTracer
from app.core.connections.registry import get_connections
from app.core.security.principal import Principal
from app.core.settings import Settings

CASES = Path(__file__).resolve().parents[2] / "tests" / "agent_eval"  # mọi `*.yaml`: nền + từng module
EVAL_USER = uuid.UUID("00000000-0000-0000-0000-00000000e7a1")
CONTEXT = "-"  # ngữ cảnh rút gọn của router; module thêm dòng mẫu khi có bộ câu riêng
PASS_RATE = 0.95


@dataclass
class Outcome:
    text: str
    expected: list[str] | None  # None = phải hỏi lại
    got: list[str]
    clarify: str | None

    @property
    def ok(self) -> bool:
        if self.expected is None:
            return bool(self.clarify) and not self.got
        return bool(self.got) and self.got[0] == self.expected[0]

    @property
    def exact(self) -> bool:
        return self.got == (self.expected or [])


def load_cases(path: Path = CASES) -> list[dict[str, Any]]:
    """Một file hoặc cả thư mục (ghép các `*.yaml` theo tên — module thêm `<module>_{vi,en}.yaml`)."""
    files = sorted(path.glob("*.yaml")) if path.is_dir() else [path]
    return [case for f in files for case in yaml.safe_load(f.read_text(encoding="utf-8")) or []]


def _past(case: dict[str, Any], slugs: dict[str, uuid.UUID]) -> list[AgentMessage]:
    out = []
    for i, h in enumerate(case.get("history") or []):
        agent_id = slugs.get(h.get("agent", "")) if h["role"] == "assistant" else None
        out.append(
            AgentMessage(
                session_id=EVAL_USER, seq=i + 1, role=h["role"], agent_id=agent_id, content={"text": h["text"]}
            )
        )
    return out


async def run_eval(settings: Settings, *, limit: int | None = None) -> list[Outcome]:
    conns = get_connections()
    async with conns.postgres.ro() as s:
        spec = await registry.by_slug(s, conns.redis, ASSISTANT)
    if spec is None or not spec.is_orchestrator or spec.model is None:
        raise RuntimeError("'Trợ lý' chưa là orchestrator có model — cấu hình ở Studio trước")
    slugs = {r.slug: r.agent_id for r in spec.routes}
    names = {v: k for k, v in slugs.items()}
    principal = Principal(user_id=EVAL_USER, perms=frozenset(), sup=False)
    out: list[Outcome] = []
    for case in load_cases()[:limit]:
        rc = RunContext(uuid.uuid4(), EVAL_USER, {"id": str(EVAL_USER)}, principal, spec, tracer=NoopTracer())
        past = _past(case, slugs)
        last = next((h.get("agent") for h in reversed(case.get("history") or []) if h["role"] == "assistant"), None)
        totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        plan: Plan = await decide(
            rc, KeyRing(spec, settings), totals, RouteInput(case["text"], past, names, last, CONTEXT)
        )
        expected = None if case["expect"].get("clarify") else list(case["expect"]["steps"])
        out.append(Outcome(case["text"], expected, [x.slug for x in plan.steps], plan.clarify))
    return out


def report(outcomes: list[Outcome]) -> tuple[float, list[str]]:
    lines = []
    for o in outcomes:
        if not o.ok:
            want = "hỏi lại" if o.expected is None else " → ".join(o.expected)
            got = (f"hỏi lại: {o.clarify}" if o.clarify else " → ".join(o.got)) or "-"
            lines.append(f"✗ {o.text!r}: mong {want}, được {got}")
    rate = sum(o.ok for o in outcomes) / len(outcomes) if outcomes else 0.0
    return rate, lines
