"""Hạn mức tin nhắn: theo user cho mỗi agent (`agent_user_limits` từng trường ưu tiên
`agent_limits`) và theo tài khoản cộng chung mọi agent (mặc định hệ thống → role → user). Số tin / phút · giờ ·
ngày kiểm trong một lần Lua cho cả hai tầng — vượt khoá nào thì không cộng khoá nào; trần token / ngày theo agent. Mốc
cửa sổ theo `APP_TIMEZONE`; superadmin miễn. Insert run lỗi sau khi đã cộng → `refund`."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.agent.config.models import AgentLimit, AgentUserLimit
from app.auth.models import User
from app.auth.policies import CHAT_KEYS, EffectiveLimit, LimitKey, effective_limits
from app.core.dates import zone
from app.core.errors import AppException
from app.core.rkeys import rkey
from app.system.settings_store import SystemSettings

LUA = (Path(__file__).with_name("limits.lua")).read_text(encoding="utf-8")
WINDOWS: tuple[tuple[str, str, int], ...] = (
    ("minute", "%Y%m%d%H%M", 120),
    ("hour", "%Y%m%d%H", 2 * 3600),
    ("day", "%Y%m%d", 2 * 86400),
)
TOKEN_TTL = 2 * 86400


@dataclass(frozen=True)
class Limits:
    per_minute: int | None = None
    per_hour: int | None = None
    per_day: int | None = None
    tokens_per_day: int | None = None

    def caps(self) -> tuple[int, int, int]:
        return (self.per_minute or 0, self.per_hour or 0, self.per_day or 0)


@dataclass(frozen=True)
class Counted:
    keys: tuple[str, ...]


SCOPES = ("agent", "account")


def account_keys(user_id: uuid.UUID, at: datetime) -> tuple[str, ...]:
    return tuple(rkey("lim", "user", str(user_id), w, at.strftime(fmt)) for w, fmt, _ in WINDOWS)


def merge(agent: AgentLimit | None, user: AgentUserLimit | None) -> Limits:
    fields = ("per_minute", "per_hour", "per_day", "tokens_per_day")
    pick = {
        f: getattr(user, f, None) if getattr(user, f, None) is not None else getattr(agent, f, None) for f in fields
    }
    return Limits(**pick)


async def effective(session, agent_id: uuid.UUID, user_id: uuid.UUID, agent_limits: AgentLimit | None) -> Limits:
    return merge(agent_limits, await session.get(AgentUserLimit, (agent_id, user_id)))


async def account_limits(session, user: User, cfg: SystemSettings) -> dict[LimitKey, EffectiveLimit]:
    """Hạn mức tin / phút · giờ · ngày theo tài khoản: mặc định hệ thống → role lớn nhất (0 thắng) → user."""
    return await effective_limits(session, user, {k: getattr(cfg, k) for k in CHAT_KEYS}, zero_unlimited=True)


def account_caps(eff: dict[LimitKey, EffectiveLimit]) -> tuple[int, int, int]:
    return tuple(eff[k].value or 0 for k in CHAT_KEYS)  # type: ignore[return-value]


def _local(now: datetime | None, tz: str) -> datetime:
    return (now or datetime.now(UTC)).astimezone(zone(tz))


def _retry_after(window: str, at: datetime) -> int:
    if window == "minute":
        end = at.replace(second=0, microsecond=0) + timedelta(minutes=1)
    elif window == "hour":
        end = at.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        end = at.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return max(1, int((end - at).total_seconds()))


def _token_key(agent_id: uuid.UUID, user_id: uuid.UUID, at: datetime) -> str:
    return rkey("tok", str(agent_id), str(user_id), at.strftime("%Y%m%d"))


async def check_and_count(
    redis,
    *,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    limits: Limits,
    tz: str,
    exempt: bool,
    account: tuple[int, int, int] = (0, 0, 0),
    now: datetime | None = None,
) -> Counted | None:
    """Vượt cửa sổ → 429 6001 `{window, limit, retry_after_sec}`; vượt trần token hôm nay → 429 6002. Không trần nào /
    superadmin → None (không đếm)."""
    if exempt:
        return None
    at = _local(now, tz)
    if limits.tokens_per_day:
        used = int(await redis.rw.get(_token_key(agent_id, user_id, at)) or 0)
        if used >= limits.tokens_per_day:
            data = {"limit": limits.tokens_per_day, "used": used, "retry_after_sec": _retry_after("day", at)}
            raise AppException(6002, status_code=429, data=data)
    caps = (*limits.caps(), *account)
    if not any(caps):
        return None
    keys = (
        *(rkey("lim", str(agent_id), str(user_id), w, at.strftime(fmt)) for w, fmt, _ in WINDOWS),
        *account_keys(user_id, at),
    )
    ttls = [ttl for _, _, ttl in WINDOWS] * 2
    hit = int(await redis.rw.eval(LUA, len(keys), *keys, *caps, *ttls))
    if hit:
        window = WINDOWS[(hit - 1) % len(WINDOWS)][0]
        scope = SCOPES[(hit - 1) // len(WINDOWS)]
        data = {"window": window, "limit": caps[hit - 1], "scope": scope, "retry_after_sec": _retry_after(window, at)}
        raise AppException(6001, status_code=429, data=data)
    return Counted(keys)


async def account_used(redis, user_id: uuid.UUID, tz: str, now: datetime | None = None) -> tuple[int, int, int]:
    """Số tin đã đếm trong phút / giờ / ngày hiện tại (tầng tài khoản) — màn chat hiện "còn N tin"."""
    values = await redis.rw.mget(account_keys(user_id, _local(now, tz)))
    return tuple(int(v or 0) for v in values)  # type: ignore[return-value]


async def refund(redis, counted: Counted | None) -> None:
    if counted is not None:
        for key in counted.keys:
            await redis.rw.decr(key)


async def count_tokens(redis, *, agent_id: uuid.UUID, user_id: uuid.UUID, tokens: int, tz: str) -> None:
    if tokens > 0:
        key = _token_key(agent_id, user_id, _local(None, tz))
        await redis.rw.incrby(key, tokens)
        await redis.rw.expire(key, TOKEN_TTL)
