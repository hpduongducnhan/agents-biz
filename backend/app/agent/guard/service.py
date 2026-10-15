"""Chặn tạm user khỏi trợ lý: đọc chặn đang hiệu lực, đếm lần chạm hạn mức → tự chặn, chặn / mở tay.
Tự chặn xảy ra trong `agent.send` ngay trước khi op ném 6001 / 6002 (transaction của op rollback) → ghi bằng session
riêng rồi báo user + superadmin ngay."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlmodel import select

from app.agent.guard.models import AgentChatBlock
from app.agent.notify import CHAT_BLOCKED, CHAT_UNBLOCKED
from app.core.connections.registry import get_connections
from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.messaging.realtime import emit_to_superadmins, emit_to_user
from app.core.operations.context import OpContext
from app.core.rkeys import rkey
from app.notifications.service import notify_users
from app.system.settings_store import SystemSettings

logger = get_logger(__name__)
BLOCKS_KEY = "studio.chat_blocks"  # query key trang /sa/chat-guard
LIMITS_KEY = "agent.chat_limits"  # query key hạn mức của chính mình (màn chat)
MAX_AUTO_MINUTES = 1440


def _now() -> datetime:
    return datetime.now(UTC)


def strike_key(user_id: uuid.UUID) -> str:
    return rkey("chat", "strike", str(user_id))


def open_blocks(user_id: uuid.UUID | None = None, now: datetime | None = None):
    """Chặn đang hiệu lực: chưa mở và (không hạn hoặc chưa tới hạn)."""
    at = now or _now()
    stmt = select(AgentChatBlock).where(
        AgentChatBlock.lifted_at.is_(None),
        (AgentChatBlock.until.is_(None)) | (AgentChatBlock.until > at),
    )
    return stmt if user_id is None else stmt.where(AgentChatBlock.user_id == user_id)


async def active_block(session, user_id: uuid.UUID) -> AgentChatBlock | None:
    stmt = open_blocks(user_id).order_by(AgentChatBlock.until.desc().nulls_first())
    return (await session.exec(stmt)).first()


def blocked_error(block: AgentChatBlock) -> AppException:
    data = {
        "until": block.until.isoformat() if block.until else None,
        "reason": block.reason,
        "source": block.source,
    }
    return AppException(6022, status_code=403, data=data)


def _notice_params(block: AgentChatBlock) -> dict:
    return {"until": block.until.isoformat() if block.until else None, "reason": block.reason, "source": block.source}


async def _announce(user_id: uuid.UUID) -> None:
    await emit_to_superadmins("data:changed", {"keys": [BLOCKS_KEY]})
    await emit_to_user(user_id, "data:changed", {"keys": [LIMITS_KEY]})


async def auto_block(user_id: uuid.UUID, cfg: SystemSettings) -> AgentChatBlock:
    """Chặn tự động: lần thứ k trong 24 giờ → `T × 2^(k−1)` phút, tối đa 24 giờ. Session riêng (op sắp rollback)."""
    now = _now()
    async with get_connections().postgres.rw() as session:
        stmt = select(func.count()).where(
            AgentChatBlock.user_id == user_id,
            AgentChatBlock.source == "auto",
            AgentChatBlock.created_at > now - timedelta(hours=24),
        )
        earlier = int((await session.exec(stmt)).one())
        minutes = min(cfg.chat_autoblock_minutes * 2**earlier, MAX_AUTO_MINUTES)
        reason = f"Chạm hạn mức chat {cfg.chat_autoblock_strikes} lần trong {cfg.chat_autoblock_window_min} phút" + (
            f" (lần thứ {earlier + 1} trong 24 giờ)" if earlier else ""
        )
        block = AgentChatBlock(user_id=user_id, until=now + timedelta(minutes=minutes), reason=reason, source="auto")
        session.add(block)
        await session.flush()
    logger.warning(
        "tự chặn trợ lý user=%s %s phút (lần %s / 24 giờ)", user_id, minutes, earlier + 1, extra={"loc": "agt0901"}
    )
    await notify_users([user_id], CHAT_BLOCKED, "Tạm chặn dùng trợ lý", reason, params=_notice_params(block))
    await _announce(user_id)
    return block


async def strike(redis, user_id: uuid.UUID, cfg: SystemSettings) -> AgentChatBlock | None:
    """Một lần chạm hạn mức (6001 / 6002). Đủ N lần trong M phút → tự chặn (luật tắt → chỉ đếm cho có)."""
    if not cfg.chat_autoblock:
        return None
    key = strike_key(user_id)
    count = int(await redis.rw.incr(key))
    if count == 1:
        await redis.rw.expire(key, cfg.chat_autoblock_window_min * 60)
    if count < cfg.chat_autoblock_strikes:
        return None
    await redis.rw.delete(key)
    return await auto_block(user_id, cfg)


async def block_manual(ctx: OpContext, user_id: uuid.UUID, minutes: int | None, reason: str) -> AgentChatBlock:
    """Superadmin chặn tay; chặn đang mở của user (nếu có) được mở để chỉ còn một chặn hiệu lực."""
    now = _now()
    for old in (await ctx.session.exec(open_blocks(user_id, now).with_for_update())).all():
        old.lifted_at, old.lifted_by = now, ctx.principal.user_id
        ctx.session.add(old)
    block = AgentChatBlock(
        user_id=user_id,
        until=now + timedelta(minutes=minutes) if minutes else None,
        reason=reason,
        source="manual",
        created_by=ctx.principal.user_id,
    )
    ctx.session.add(block)
    await ctx.session.flush()
    logger.info("chặn tay trợ lý user=%s tới %s bởi %s", user_id, block.until, ctx.principal.user_id,
                extra={"loc": "agt0902"})  # fmt: skip
    ctx.notify(user_id, CHAT_BLOCKED, "Tạm chặn dùng trợ lý", reason, params=_notice_params(block))
    _invalidate(ctx, user_id)
    return block


async def lift(ctx: OpContext, block_id: uuid.UUID) -> AgentChatBlock:
    stmt = select(AgentChatBlock).where(AgentChatBlock.id == block_id).with_for_update()
    block = (await ctx.session.exec(stmt)).first()
    if block is None:
        raise AppException(1001, status_code=404, detail="Block not found")
    if block.active():
        block.lifted_at, block.lifted_by = _now(), ctx.principal.user_id
        ctx.session.add(block)
        await ctx.session.flush()
        await ctx.redis.rw.delete(strike_key(block.user_id))
        logger.info("mở chặn trợ lý user=%s bởi %s", block.user_id, ctx.principal.user_id, extra={"loc": "agt0903"})
        ctx.notify(block.user_id, CHAT_UNBLOCKED, "Đã mở chặn trợ lý", params={})
        _invalidate(ctx, block.user_id)
    return block


def _invalidate(ctx: OpContext, user_id: uuid.UUID) -> None:
    ctx.emit_to_superadmins("data:changed", {"keys": [BLOCKS_KEY]})
    ctx.invalidate((LIMITS_KEY,), (user_id,))
