"""Tin nhắn của lượt: phần sau tin user cuối (resume từ checkpoint) và dạng lưu DB (bỏ tool call chưa có kết quả)."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage


def after_last_human(messages: list[BaseMessage]) -> list[BaseMessage]:
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            return [m for m in messages[i + 1 :] if isinstance(m, AIMessage | ToolMessage)]
    return []


def to_items(produced: list[BaseMessage], usage: dict[str, int] | None) -> list[dict[str, Any]]:
    """Tin nhắn của lượt để ghi DB. Tool call chưa có kết quả (lượt lỗi / bị huỷ khi tool đang chạy) bị bỏ — provider
    từ chối lịch sử có tool call không kèm kết quả."""
    answered = {m.tool_call_id for m in produced if isinstance(m, ToolMessage)}
    items: list[dict[str, Any]] = []
    for m in produced:
        if isinstance(m, AIMessage):
            calls = [
                {"id": c["id"], "name": c["name"], "args": c.get("args", {})}
                for c in m.tool_calls
                if c["id"] in answered
            ]
            if calls or m.text:
                items.append({"role": "assistant", "content": {"text": m.text, "tool_calls": calls}})
        elif isinstance(m, ToolMessage):
            text = m.content if isinstance(m.content, str) else str(m.content)
            content = {"text": text, "tool_call_id": m.tool_call_id, "name": m.name, "status": m.status}
            items.append({"role": "tool", "content": content})
    for item in reversed(items):
        if item["role"] == "assistant":
            item["content"]["usage"] = usage
            break
    return items
