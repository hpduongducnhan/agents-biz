"""`RunMiddleware` (R19): quanh mỗi lần gọi model — đếm token + hạn mức + span
llm, lỗi provider TRƯỚC khi có chữ nào → xoay key (`KeyRing`); quanh mỗi tool — duyệt (`interrupt`) cho tool `confirm`,
`agent:step` running → done / error, span tool."""

from __future__ import annotations

import re
import uuid
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelResponse
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import interrupt

from app.agent.chat import approvals
from app.agent.config.registry import AgentSpec
from app.agent.hooks import engine
from app.agent.hooks.engine import HookOutcome
from app.agent.runtime import keys, limits
from app.agent.runtime.llm import build_chat_model
from app.agent.runtime.tools import APPROVED_ARGS, APPROVED_BY, CALL_ID, RunContext, ToolBinding, real_args
from app.agent.trace import usage
from app.agent.trace.events import redact
from app.agent.trace.tracer import CallMeta
from app.core.connections.registry import get_connections
from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.settings import Settings

logger = get_logger(__name__)
ERROR_RE = re.compile(r"^Lỗi (\d{4}):")
NO_CHECKPOINTER = "Lỗi 6007: chưa duyệt được thao tác lúc này (hệ thống chưa sẵn sàng lưu lượt chờ duyệt)."
PREVIEW = 500


def error_code_of(text: str) -> int | None:
    m = ERROR_RE.match(text)
    return int(m.group(1)) if m else None


class TokenWatch(AsyncCallbackHandler):
    """Đếm chunk có nội dung của model — lỗi provider sau khi đã có chữ thì không thử key khác (chữ đã tới người)."""

    run_inline = True

    def __init__(self) -> None:
        self.count = 0

    async def on_llm_new_token(self, token: str, *, chunk: Any = None, **_: Any) -> None:
        message = getattr(chunk, "message", None)
        if token or getattr(message, "tool_call_chunks", None):
            self.count += 1


class KeyRing:
    """Key đang dùng của lượt + các key đã thử (ghi `agent_runs.credential_ids`)."""

    def __init__(self, spec: AgentSpec, settings: Settings, *, stream: bool = True) -> None:
        self.spec, self.settings, self.stream = spec, settings, stream
        self.current: keys.PickedKey | None = None
        self.tried: list[uuid.UUID] = []

    async def model(self) -> BaseChatModel:
        conns = get_connections()
        async with conns.postgres.rw() as session:
            self.current = await keys.pick(session, conns.redis, self.settings, self.spec, exclude=self.tried)
        self.tried.append(self.current.id)
        return build_chat_model(self.spec, api_key=self.current.secret, stream=self.stream)

    async def rotate(self, kind: str, exc: BaseException) -> BaseChatModel:
        """Phạt key hiện tại theo loại lỗi rồi lấy key khác; hết key → ném lại lỗi provider gốc (→ 6011)."""
        cur = self.current
        if cur is not None and kind == "rate":
            await keys.cool(get_connections().redis, cur.id, self.spec.agent.key_cooldown_sec)
        elif cur is not None and kind == "auth":
            await keys.disable(cur.id, cur.name, exc)
        try:
            return await self.model()
        except AppException as err:
            if err.code == 6010:
                raise exc from None
            raise


class RunMiddleware(AgentMiddleware):
    def __init__(
        self,
        rc: RunContext,
        ring: KeyRing,
        totals: dict[str, int],
        watch: TokenWatch,
        *,
        can_wait: bool,
        purpose: str = "agent",
    ):
        super().__init__()
        self.rc, self.ring, self.totals, self.watch, self.can_wait = rc, ring, totals, watch, can_wait
        self.params = {**(rc.spec.provider.default_params or {}), **(rc.spec.agent.params_override or {})}
        spec = rc.spec
        self.call = CallMeta(  # usage giám sát: "gọi ở đâu" = router hay agent / chuyên gia
            purpose=purpose,
            agent_id=str(spec.id),
            agent_slug=spec.agent.slug,
            model_id=str(spec.model.id) if spec.model else "",
            model=spec.model.model_id if spec.model else "",
            provider_id=str(spec.provider.id) if spec.provider else "",
            provider_kind=spec.provider.kind if spec.provider else "",
        )

    async def awrap_model_call(self, request, handler):
        retried_same = False
        while True:
            seen = self.watch.count
            try:
                async with self.rc.tracer.llm(request.messages, self.params, self.ring.current, self.call) as span:
                    response = await handler(request)
                    if not self.rc.stream.on:
                        self.rc.tracer.first_token()  # gọi một lần: chữ đầu tới cùng lúc cả câu
                    found = response.result if isinstance(response, ModelResponse) else [response]
                    for m in found:
                        if isinstance(m, AIMessage):
                            self.rc.tracer.llm_response(span, m)
                            if m.usage_metadata:
                                await self._count(m.usage_metadata, span)
                return response
            except AppException:
                raise
            except Exception as exc:
                kind = keys.classify(exc)
                if kind == "other" or self.watch.count != seen:
                    raise
                logger.warning(
                    "provider lỗi (%s) run=%s key=%s: %s",
                    kind,
                    self.rc.run_id,
                    self.ring.current.id if self.ring.current else None,
                    exc,
                    extra={"loc": "agt0501"},
                )
                if kind == "server" and not retried_same:
                    retried_same = True
                    continue
                retried_same = False
                request = request.override(model=await self.ring.rotate(kind, exc))

    async def _count(self, used: dict[str, Any], span: Any = None) -> None:
        details = used.get("input_token_details") or {}
        self.totals["input"] += int(used.get("input_tokens") or 0)
        self.totals["output"] += int(used.get("output_tokens") or 0)
        self.totals["cache_read"] += int(details.get("cache_read") or 0)
        self.totals["cache_write"] += int(details.get("cache_creation") or 0)
        spec, me = self.rc.spec, self.rc.principal.user_id
        try:
            await limits.count_tokens(
                get_connections().redis,
                agent_id=self.rc.limit_agent_id,
                user_id=me,
                tokens=int(used.get("input_tokens") or 0) + int(used.get("output_tokens") or 0),
                tz=self.ring.settings.APP_TIMEZONE,
            )
        except Exception as exc:  # noqa: BLE001 — đếm hạn mức hỏng không được làm hỏng câu trả lời
            logger.warning("đếm token lỗi run=%s: %s", self.rc.run_id, exc, extra={"loc": "agt0502"})
        if spec.model is None:
            return
        cost = usage.cost_of(spec.model, usage.tokens_of(used))
        if span is not None and hasattr(span, "cost"):
            span.cost = float(cost) + (span.cost or 0.0)
        try:
            await usage.add_run_cost(self.rc.run_id, cost)
        except Exception as exc:  # noqa: BLE001 — số liệu báo cáo hỏng không được làm hỏng câu trả lời
            logger.warning("ghi chi phí lượt lỗi run=%s: %s", self.rc.run_id, exc, extra={"loc": "agt0506"})

    async def awrap_tool_call(self, request, handler):
        call = request.tool_call
        binding: ToolBinding | None = (request.tool.metadata or {}).get("binding") if request.tool else None
        call_token = CALL_ID.set(call["id"])
        try:
            async with self.rc.tracer.tool(call, binding) as span:
                approved, real = None, None
                before = await self._hooks("before_tool", self._tool_data(call, binding), span.id)
                if before.blocked:
                    blocked = ToolMessage(
                        before.message or "", tool_call_id=call["id"], name=call["name"], status="error"
                    )
                    self.rc.tracer.tool_result(span, blocked)
                    return blocked
                if binding is not None and (binding.policy == "confirm" or before.approval):
                    req, refused = await self._approval(call, binding, span.id)
                    if refused is not None:
                        self.rc.tracer.tool_result(span, refused, real_args=req.args if req else None)
                        return refused
                    approved = (APPROVED_BY.set(str(req.decided_by)), APPROVED_ARGS.set(dict(req.args)))
                    real = req.args
                elif binding is not None:
                    real = real_args(binding, call.get("args") or {}, self.rc)
                try:
                    result = await self._run_step(request, handler, call, binding)
                finally:
                    if approved is not None:
                        APPROVED_BY.reset(approved[0])
                        APPROVED_ARGS.reset(approved[1])
                self.rc.tracer.tool_result(span, result, real_args=real)
                await self._hooks("after_tool", self._tool_data(call, binding, result), span.id)
                return result
        finally:
            CALL_ID.reset(call_token)

    async def _hooks(self, point: str, data: dict[str, Any], parent: str) -> HookOutcome:
        if not self.rc.spec.hooks:
            return HookOutcome()
        return await engine.run(
            point, self.rc.spec.hooks, data, tracer=self.rc.tracer, parent=parent, run_id=self.rc.run_id
        )

    def _tool_data(self, call: dict[str, Any], binding: ToolBinding | None, result: Any = None) -> dict[str, Any]:
        op = binding.spec if binding is not None else None
        data = {
            "user": self.rc.user,
            "agent": {"id": str(self.rc.spec.id), "slug": self.rc.spec.agent.slug},
            "tool": {
                "name": call["name"],
                "operation": op.name if op else None,
                "toolset": op.toolset if op else None,
                "effect": op.effect if op else None,
            },
            "args": call.get("args") or {},
        }
        if isinstance(result, ToolMessage):
            text = result.content if isinstance(result.content, str) else str(result.content)
            data["result"] = {"ok": result.status != "error", "error_code": error_code_of(text), "text": text[:2000]}
        return data

    async def _approval(self, call: dict[str, Any], binding: ToolBinding, span_id: str):
        """Tạo / lấy yêu cầu duyệt → `interrupt` (graph dừng, checkpoint giữ). Resume chạy lại hàm này: yêu cầu đã có
        thì không tạo mới, quyết định đọc lại từ DB."""
        if not self.can_wait:
            return None, ToolMessage(NO_CHECKPOINTER, tool_call_id=call["id"], name=call["name"], status="error")
        args = real_args(binding, call.get("args") or {}, self.rc)
        req, created = await approvals.get_or_create(
            self.rc.run_id, self.rc.spec.id, call["id"], binding.spec.name, args
        )
        if created:
            await self.rc.emitter.approval(
                approval_id=str(req.id),
                call_id=call["id"],
                name=call["name"],
                operation=binding.spec.name,
                title=binding.spec.title,
                args=redact(args),
                expires_at=req.expires_at.isoformat(),
            )
        self.rc.tracer.approval(req, parent=span_id)
        if req.status == "pending":
            interrupt({"approval_id": str(req.id)})
            req = await approvals.reload(req.id)
            self.rc.tracer.approval(req, parent=span_id)
        if req.status == "approved":
            return req, None
        text = approvals.refusal_text(req)
        return req, ToolMessage(text, tool_call_id=call["id"], name=call["name"], status="error")

    async def _run_step(self, request, handler, call: dict[str, Any], binding: ToolBinding | None):
        emitter, title = self.rc.emitter, binding.spec.title if binding is not None else call["name"]
        args = redact(call.get("args") or {})
        await emitter.step(call_id=call["id"], name=call["name"], title=title, status="running", args=args)
        result = await handler(request)
        failed = isinstance(result, ToolMessage) and result.status == "error"
        content = result.content if isinstance(result, ToolMessage) else ""
        preview = content[:PREVIEW] if isinstance(content, str) else ""
        status = "error" if failed else "done"
        await emitter.step(call_id=call["id"], name=call["name"], title=title, status=status, preview=preview)
        return result
