"""Phiên + tin nhắn chat (nguồn sự thật lịch sử). `seq` cấp trong khoá dòng phiên (`FOR UPDATE`) — gửi tin và
runner ghi kết quả không chen số nhau."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlmodel import select

from app.agent.chat.models import OPEN_STATUSES, AgentMessage, AgentRun, AgentSession
from app.core.connections.registry import get_connections
from app.core.errors import AppException

TITLE_LEN = 60


def title_of(text: str) -> str:
    one = " ".join(text.split())
    return one if len(one) <= TITLE_LEN else one[: TITLE_LEN - 1].rstrip() + "…"


async def lock_session(session, session_id: uuid.UUID) -> AgentSession:
    row = (await session.exec(select(AgentSession).where(AgentSession.id == session_id).with_for_update())).first()
    if row is None:
        raise AppException(6004, status_code=404)
    return row


async def _next_seq(session, session_id: uuid.UUID) -> int:
    stmt = select(func.coalesce(func.max(AgentMessage.seq), 0)).where(AgentMessage.session_id == session_id)
    return int((await session.exec(stmt)).one()) + 1


async def add_messages(
    session, chat: AgentSession, run_id: uuid.UUID | None, agent_id: uuid.UUID | None, items: list[dict[str, Any]]
) -> list[AgentMessage]:
    """Ghi tin nhắn (đã khoá phiên) — item = `{role, content, client_msg_id?}`."""
    seq = await _next_seq(session, chat.id)
    rows = []
    for i, item in enumerate(items):
        rows.append(
            AgentMessage(
                tenant_id=chat.tenant_id,  # worker ghi bằng session chưa scope — lấy tenant của phiên
                session_id=chat.id,
                seq=seq + i,
                role=item["role"],
                agent_id=agent_id if item["role"] != "user" else None,
                content=item["content"],
                run_id=run_id,
                client_msg_id=item.get("client_msg_id"),
            )
        )
    session.add_all(rows)
    chat.updated_at = datetime.now(UTC)
    if agent_id is not None and items and items[-1]["role"] != "user":
        chat.last_agent_id = agent_id
    session.add(chat)
    await session.flush()
    return rows


async def append_messages(
    session_id: uuid.UUID, run_id: uuid.UUID, agent_id: uuid.UUID, items: list[dict[str, Any]]
) -> list[AgentMessage]:
    if not items:
        return []
    async with get_connections().postgres.rw() as session:
        chat = await lock_session(session, session_id)
        rows = await add_messages(session, chat, run_id, agent_id, items)
        for r in rows:
            await session.refresh(r)
        return rows


def _talk():
    """Tin hội thoại: tin user hoặc trả lời có chữ — tool call / kết quả tool không tính vào giới hạn lịch sử."""
    text_of = func.coalesce(AgentMessage.content["text"].astext, "")
    return (AgentMessage.role == "user") | ((AgentMessage.role == "assistant") & (text_of != ""))


async def history(
    session, session_id: uuid.UUID, limit: int, *, exclude_run: uuid.UUID, tools: bool = True
) -> list[AgentMessage]:
    """≤ `limit` tin hội thoại gần nhất trước lượt này, mở đầu bằng tin user. `tools=True` kèm tool call + kết quả nằm
    giữa các tin đó; `False` chỉ giữ chữ (tool call không kết quả bị `prompt.history` bỏ)."""
    before = (AgentMessage.session_id == session_id) & (
        (AgentMessage.run_id.is_(None)) | (AgentMessage.run_id != exclude_run)
    )
    recent = select(AgentMessage.seq).where(before, _talk()).order_by(AgentMessage.seq.desc()).limit(limit)
    floor = (await session.exec(select(func.min(recent.subquery().c.seq)))).one()
    if floor is None:
        return []
    stmt = select(AgentMessage).where(before, AgentMessage.seq >= floor)
    if not tools:
        stmt = stmt.where(_talk())
    rows = list((await session.exec(stmt.order_by(AgentMessage.seq))).all())
    while rows and rows[0].role != "user":
        rows.pop(0)
    return rows


async def current_session(
    session, user_id: uuid.UUID, agent_id: uuid.UUID, idle_min: int
) -> tuple[AgentSession | None, AgentSession | None]:
    """Phiên đang mở của user với agent — tin cuối trong `idle_min` phút hoặc còn lượt mở — và phiên ngay trước
    nó. Quá hạn → `(None, phiên mới nhất)`: tin tiếp theo mở phiên mới."""
    stmt = (
        select(AgentSession)
        .where(AgentSession.user_id == user_id, AgentSession.entry_agent_id == agent_id)
        .order_by(AgentSession.updated_at.desc())
        .limit(2)
    )
    rows = list((await session.exec(stmt)).all())
    if not rows:
        return None, None
    latest = rows[0]
    fresh = latest.updated_at >= datetime.now(UTC) - timedelta(minutes=idle_min)
    if fresh or await open_run(session, latest.id) is not None:
        return latest, rows[1] if len(rows) > 1 else None
    return None, latest


async def run_input(session, run_id: uuid.UUID) -> str:
    stmt = select(AgentMessage).where(AgentMessage.run_id == run_id, AgentMessage.role == "user")
    row = (await session.exec(stmt.order_by(AgentMessage.seq))).first()
    return (row.content or {}).get("text", "") if row is not None else ""


async def open_run(session, session_id: uuid.UUID) -> AgentRun | None:
    stmt = select(AgentRun).where(AgentRun.session_id == session_id, AgentRun.status.in_(OPEN_STATUSES))
    return (await session.exec(stmt)).first()
