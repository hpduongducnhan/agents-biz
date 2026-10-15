"""Tool của agent = `@operation(agent=True)` thuộc toolset của agent mà user dùng được: quyền hệ thống của op + quyền
`agent.<toolset>`. Tool gọi `run_operation(..., source="agent")` — cùng kiểm quyền, event log, realtime như web. Lỗi
nghiệp vụ trả LLM dạng chữ để nó tự sửa."""

from __future__ import annotations

import hashlib
import json
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool, ToolException
from pydantic_core import to_jsonable_python

from app.agent.config.registry import AgentSpec
from app.agent.config.toolsets import default_policy, ops_of, perm_of
from app.agent.runtime.streaming import StreamCfg
from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.operations.rest import _inline_defs
from app.core.operations.runner import is_allowed, run_operation
from app.core.operations.spec import OperationSpec
from app.core.security.principal import Principal

logger = get_logger(__name__)
RESULT_LIMIT = 20_000
IDEMPOTENCY_ARG = "idempotency_key"
CONFIRM_TEXT = "Thao tác này cần được duyệt trước khi chạy."
APPROVED_BY: ContextVar[str | None] = ContextVar("agent_approved_by", default=None)
APPROVED_ARGS: ContextVar[dict[str, Any] | None] = ContextVar("agent_approved_args", default=None)
CALL_ID: ContextVar[str | None] = ContextVar("agent_call_id", default=None)


@dataclass
class RunContext:
    run_id: uuid.UUID
    session_id: uuid.UUID
    user: dict[str, Any]  # id, name, tz, locale, roles, is_superadmin
    principal: Principal
    spec: AgentSpec
    emitter: Any = None
    tracer: Any = None
    extra_context: list[str] = field(default_factory=list)  # hook `add_context`
    entry_id: uuid.UUID | None = None  # agent của phiên (hạn mức / token tính ở đây); None = chính `spec`
    handoff: Any = None  # trạng thái handoff của bước (`runtime/steps.py`)
    stream: StreamCfg = field(default_factory=StreamCfg)  # cài đặt stream của lượt (D23)

    @property
    def limit_agent_id(self) -> uuid.UUID:
        return self.entry_id or self.spec.id


@dataclass
class HandoffState:
    """Handoff trong một bước chuyên gia: đích hợp lệ = chuyên gia khác trong route của orchestrator."""

    targets: dict[str, Any]  # slug → RouteSpec
    left: int
    current: str
    came_from: str | None = None  # chuyên gia vừa chuyển sang bước này — không chuyển ngược lại (A → B → A)
    to: str | None = None
    reason: str = ""

    @property
    def choices(self) -> list[str]:
        return sorted(k for k in self.targets if k not in (self.current, self.came_from))


@dataclass(frozen=True)
class ToolBinding:
    spec: OperationSpec
    name: str
    policy: str
    locked: dict[str, Any]
    defaults: dict[str, Any]


def tool_name(op: str) -> str:
    return op.replace(".", "_")


def llm_schema(op: OperationSpec, *, locked: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """Schema LLM thấy: `$defs` inline (Gemini / OpenAI strict), bỏ tham số khoá + `idempotency_key` (runtime điền),
    tham số mặc định hiện `default`."""
    schema = _inline_defs(op.input_schema())
    props = {}
    for name, prop in (schema.get("properties") or {}).items():
        if name in locked or name == IDEMPOTENCY_ARG:
            continue
        props[name] = {**prop, "default": defaults[name]} if name in defaults else prop
    out: dict[str, Any] = {"type": "object", "properties": props}
    required = [r for r in schema.get("required", []) if r in props and r not in defaults]
    if required:
        out["required"] = required
    return out


def policy_of(op: OperationSpec, override) -> str:
    """`read` / `write` → auto, `destructive` → confirm; override chỉ được NÂNG (auto → confirm / deny)."""
    base = default_policy(op)
    wanted = getattr(override, "policy", None)
    rank = {"auto": 0, "confirm": 1, "deny": 2}
    return wanted if wanted and rank[wanted] > rank[base] else base


def render_result(value: Any) -> str:
    """Kết quả op → JSON (model / list model / dict lồng đều qua `to_jsonable_python` — không `str(model)`)."""
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(to_jsonable_python(value, by_alias=True, fallback=str), ensure_ascii=False)
    if len(text) <= RESULT_LIMIT:
        return text
    return f"{text[:RESULT_LIMIT]}… (đã cắt, tổng {len(text)} ký tự)"


def error_text(exc: AppException) -> str:
    text = f"Lỗi {exc.code}: {exc.message}"
    if exc.data:
        text += " — " + json.dumps(exc.data, ensure_ascii=False, default=str)[:2000]
    return text


def real_args(b: ToolBinding, llm_args: dict[str, Any], rc: RunContext) -> dict[str, Any]:
    args = {**b.defaults, **llm_args, **b.locked}
    if (
        b.spec.input_model is not None
        and IDEMPOTENCY_ARG in b.spec.input_model.model_fields
        and not args.get(IDEMPOTENCY_ARG)
    ):
        digest = hashlib.sha256(f"{rc.run_id}:{CALL_ID.get()}".encode()).hexdigest()[:40]
        args[IDEMPOTENCY_ARG] = f"agent-{digest}"
    return args


def hidden_reason(op: OperationSpec, rc: RunContext) -> str | None:
    """Vì sao user không được dùng tool này qua trợ lý; None = dùng được."""
    if not is_allowed(op, rc.principal):
        return f"thiếu quyền {op.permission or 'superadmin'}"
    if op.toolset and not rc.principal.can(perm_of(op.toolset)):
        return f"thiếu quyền {perm_of(op.toolset)}"
    return None


def hidden_tools(rc: RunContext) -> dict[str, str]:
    """Tool thuộc toolset của agent nhưng không đưa cho LLM → lý do (ghi vào trace — R11 / R19)."""
    out: dict[str, str] = {}
    for toolset in sorted(rc.spec.toolsets):
        for op in ops_of(toolset):
            reason = hidden_reason(op, rc)
            if reason is not None:
                out[tool_name(op.name)] = reason
    return out


def bindings(rc: RunContext) -> list[ToolBinding]:
    out = []
    for toolset in sorted(rc.spec.toolsets):
        for op in ops_of(toolset):
            if hidden_reason(op, rc) is not None:
                continue
            override = rc.spec.overrides.get(op.name)
            policy = policy_of(op, override)
            if policy == "deny":
                continue
            out.append(
                ToolBinding(
                    spec=op,
                    name=tool_name(op.name),
                    policy=policy,
                    locked=dict(getattr(override, "locked_params", None) or {}),
                    defaults=dict(getattr(override, "default_params", None) or {}),
                )
            )
    return out


async def run_tool(b: ToolBinding, args: dict[str, Any], rc: RunContext) -> str:
    if b.policy == "confirm" and APPROVED_BY.get() is None:  # khoá lớp hai sau middleware duyệt
        raise ToolException(CONFIRM_TEXT)
    try:
        out = await run_operation(b.spec.name, rc.principal, args, source="agent", agent_run_id=rc.run_id)
    except AppException as exc:
        raise ToolException(error_text(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — lỗi hệ thống của tool → LLM nhận chữ, issue đã ghi ở runner REST / log
        logger.warning("tool %s lỗi: %s", b.name, exc, extra={"loc": "agt0301"})
        raise ToolException(f"Lỗi 1000: lỗi hệ thống ({type(exc).__name__})") from exc
    return render_result(out)


def make_tool(b: ToolBinding, rc: RunContext) -> BaseTool:
    async def run(**llm_args: Any) -> str:
        approved = APPROVED_ARGS.get()
        args = dict(approved) if approved is not None else real_args(b, llm_args, rc)
        return await run_tool(b, args, rc)

    description = (b.spec.title + (" — " + b.spec.description if b.spec.description else "")).strip()
    return StructuredTool(
        name=b.name,
        description=description[:1000],
        args_schema=llm_schema(b.spec, locked=b.locked, defaults=b.defaults),
        coroutine=run,
        handle_tool_error=True,
        metadata={"binding": b},
    )


HANDOFF = "handoff"


def make_handoff(rc: RunContext) -> BaseTool:
    """Tool `handoff(to, reason)`: kết thúc bước này (`return_direct`) và chuyển việc cho chuyên gia `to`."""
    state: HandoffState = rc.handoff
    choices = state.choices

    async def run(to: str, reason: str = "") -> str:
        if state.left <= 0:
            raise ToolException("Lỗi 6021: lượt này đã chuyển chuyên gia đủ số lần cho phép — tự trả lời người dùng.")
        if to not in choices:
            raise ToolException(f"Lỗi 1002: không có chuyên gia '{to}' — chọn trong: {', '.join(choices)}")
        state.to, state.reason = to, reason.strip()
        return f"Đã chuyển cho {state.targets[to].name}" + (f": {state.reason}" if state.reason else "")

    schema = {
        "type": "object",
        "properties": {
            "to": {"type": "string", "enum": choices, "description": "mã chuyên gia nhận việc"},
            "reason": {"type": "string", "description": "việc cần làm, ngắn gọn"},
        },
        "required": ["to"],
    }
    return StructuredTool(
        name=HANDOFF,
        description="Chuyển phần việc còn lại cho chuyên gia khác khi việc không thuộc phạm vi của bạn",
        args_schema=schema,
        coroutine=run,
        handle_tool_error=True,
        return_direct=True,
    )


def build_tools(rc: RunContext) -> list[BaseTool]:
    tools = [make_tool(b, rc) for b in bindings(rc)]
    # hết lượt chuyển / không còn ai để chuyển → không có tool: `handoff` là return_direct, gọi mà bị từ chối thì
    # bước kết thúc ngay sau lỗi, người dùng không nhận được câu trả lời
    if rc.handoff is not None and rc.handoff.left > 0 and rc.handoff.choices:
        tools.append(make_handoff(rc))
    return tools
