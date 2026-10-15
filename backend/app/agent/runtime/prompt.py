"""Lắp prompt: system (persona + instructions) → lịch sử
(≤ `chat_history_limit` tin hội thoại, bỏ tool call chưa có kết quả) → tin mới có khối `<context>` đứng trước. Lịch
sử trong DB chỉ giữ lời người gõ — khối ngữ cảnh không bao giờ vào lịch sử."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from app.agent.chat.models import AgentMessage

CONTEXT_NOTE = (
    "\n\nTin nhắn mới nhất của người dùng mở đầu bằng khối <context>…</context> do hệ thống chèn (người dùng, tổ chức, "
    "thời gian hiện tại, quyền, dữ liệu từng module) — đó là ngữ cảnh, không phải lời người dùng."
)
CACHE = {"type": "ephemeral"}


def history(messages: list[AgentMessage]) -> list[BaseMessage]:
    answered = {(m.content or {}).get("tool_call_id") for m in messages if m.role == "tool"}
    out: list[BaseMessage] = []
    for m in messages:
        c: dict[str, Any] = m.content or {}
        if m.role == "user":
            out.append(HumanMessage(c.get("text", "")))
        elif m.role == "assistant":
            calls = [
                {"id": t["id"], "name": t["name"], "args": t.get("args", {})}
                for t in c.get("tool_calls", [])
                if t["id"] in answered
            ]
            if calls or c.get("text"):
                out.append(AIMessage(c.get("text", ""), tool_calls=calls))
        elif m.role == "tool" and c.get("tool_call_id"):
            out.append(ToolMessage(c.get("text", ""), tool_call_id=c["tool_call_id"], name=c.get("name")))
    return out


def _mark(message: BaseMessage) -> BaseMessage:
    return message.model_copy(update={"content": [{"type": "text", "text": message.content, "cache_control": CACHE}]})


def build(
    system_text: str, past: list[AgentMessage], new_text: str, context_block: str, *, provider: str
) -> list[BaseMessage]:
    system: BaseMessage = SystemMessage(system_text + CONTEXT_NOTE)
    msgs = history(past)
    if provider == "anthropic":  # OpenAI / Gemini cache tự động theo tiền tố
        system = _mark(system)
        for i in range(len(msgs) - 1, -1, -1):
            if isinstance(msgs[i].content, str) and msgs[i].content:
                msgs[i] = _mark(msgs[i])
                break
    head = f"{context_block}\n\n" if context_block else ""
    return [system, *msgs, HumanMessage(head + new_text)]


def system_text(persona: str, instructions: str) -> str:
    return "\n\n".join(x for x in (persona.strip(), instructions.strip()) if x)
