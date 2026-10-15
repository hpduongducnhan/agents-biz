"""Prompt của router: bảng route (mã — ý định — ví dụ) + luật trong system; tin người dùng kèm 6 tin gần nhất, chuyên
gia lượt trước, cờ "lượt trước đang hỏi lại", ngữ cảnh rút gọn (dòng `router=True` của module — không số liệu)."""

from __future__ import annotations

import uuid

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from app.agent.chat.models import AgentMessage
from app.agent.config.registry import RouteSpec
from app.agent.runtime import context

RECENT = 6
TEXT_CAP = 400


def routes_table(routes: tuple[RouteSpec, ...]) -> str:
    lines = ["| mã | chuyên gia | phụ trách | ví dụ |", "|---|---|---|---|"]
    for r in routes:
        examples = "; ".join(f'"{x}"' for x in r.examples[:5])
        lines.append(f"| `{r.slug}` | {r.name} | {r.intent} | {examples} |")
    return "\n".join(lines)


async def short_context(session, user_id: uuid.UUID) -> str:
    return await context.short(session, user_id)


def recent_lines(past: list[AgentMessage], names: dict[uuid.UUID, str]) -> list[str]:
    out = []
    for m in past:
        text = ((m.content or {}).get("text") or "").strip()
        if m.role == "tool" or not text:
            continue
        who = "user" if m.role == "user" else f"assistant({names.get(m.agent_id, '-')})"
        out.append(f"{who}: {text[:TEXT_CAP]}")
    return out[-RECENT:]


def build(
    instructions: str,
    routes: tuple[RouteSpec, ...],
    *,
    text: str,
    recent: list[str],
    last_agent: str | None,
    asked_back: bool,
    context: str,
) -> list[BaseMessage]:
    system = f"{instructions.strip()}\n\n## Chuyên gia\n{routes_table(routes)}"
    asked = "có" if asked_back else "không"
    state = f"chuyên gia lượt trước: {last_agent or '-'} · lượt trước kết thúc bằng câu hỏi lại: {asked}"
    body = "\n".join(
        [
            "<recent>",
            *recent,
            "</recent>",
            f"<state>{state}</state>",
            f"<context>\n{context}\n</context>",
            f"Tin nhắn mới: {text}",
        ]
    )
    return [SystemMessage(system), HumanMessage(body)]
