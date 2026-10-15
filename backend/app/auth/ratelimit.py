"""Rate limit cửa sổ cố định trên Redis (đăng nhập / đăng ký). Key `bw:rl:<phần…>`."""

from __future__ import annotations

from app.core.errors import AppException
from app.core.rkeys import rkey

_HIT = """
local n = redis.call('INCR', KEYS[1])
local ttl = redis.call('TTL', KEYS[1])
if ttl < 0 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
  ttl = tonumber(ARGV[1])
end
return {n, ttl}
"""


async def hit_rate_limit(redis, parts: tuple[str, ...], limit: int, window: int = 60) -> None:
    """Đếm một lần thử cho `parts`; quá `limit` lần trong `window` giây → 429 mã 1007 kèm `retry_after_sec`."""
    count, ttl = await redis.eval(_HIT, 1, rkey("rl", *parts), window)
    if int(count) > limit:
        raise AppException(
            1007,
            status_code=429,
            detail="Too many attempts, try again later",
            data={"retry_after_sec": max(int(ttl), 1)},
        )
