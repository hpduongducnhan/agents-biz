"""Redis — CHỈ cache / KV; 2 client RW / RO, client RO chỉ lộ lệnh đọc."""

from __future__ import annotations

import redis.asyncio as aioredis

from app.core.settings import Settings

READ_COMMANDS = frozenset(
    {
        "get",
        "mget",
        "exists",
        "ttl",
        "pttl",
        "type",
        "strlen",
        "hget",
        "hmget",
        "hgetall",
        "hexists",
        "hlen",
        "hkeys",
        "hvals",
        "smembers",
        "sismember",
        "scard",
        "zrange",
        "zrangebyscore",
        "zscore",
        "zcard",
        "zrank",
        "lrange",
        "llen",
        "lindex",
        "scan_iter",
        "hscan_iter",
        "sscan_iter",
        "zscan_iter",
        "ping",
    }
)


class ReadOnlyRedis:
    def __init__(self, client: aioredis.Redis) -> None:
        self._c = client

    def __getattr__(self, name: str):
        if name in READ_COMMANDS:
            return getattr(self._c, name)
        raise AttributeError(f"Redis RO không cho lệnh '{name}' — dùng kênh RW")


class Redis:
    def __init__(self, settings: Settings) -> None:
        self.rw: aioredis.Redis = aioredis.Redis.from_url(settings.REDIS_RW_URL, decode_responses=True)
        self._ro_raw: aioredis.Redis = aioredis.Redis.from_url(settings.redis_ro_url, decode_responses=True)
        self.ro = ReadOnlyRedis(self._ro_raw)

    async def ping(self, channel: str) -> None:
        await (self.rw if channel == "rw" else self._ro_raw).ping()

    async def close(self) -> None:
        await self.rw.aclose()
        await self._ro_raw.aclose()
