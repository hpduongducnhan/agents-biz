"""Khoá leader trên Redis: lỡ chạy 2 `bw schedule` (deploy chồng lấn) thì bản thứ hai đứng chờ."""

from __future__ import annotations

import uuid

_RENEW = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('pexpire', KEYS[1], ARGV[2]) end return 0"
_RELEASE = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end return 0"


class LeaderLock:
    """Khoá có hạn: giữ bằng `renew()` đều đặn; chết thì hết hạn sau `ttl` giây → bản khác giành."""

    def __init__(self, redis, key: str = "bw:leader:schedule", ttl: int = 15) -> None:
        self.redis = redis
        self.key = key
        self.ttl = ttl
        self.token = uuid.uuid4().hex

    async def acquire(self) -> bool:
        return bool(await self.redis.set(self.key, self.token, nx=True, px=self.ttl * 1000))

    async def renew(self) -> bool:
        return bool(await self.redis.eval(_RENEW, 1, self.key, self.token, self.ttl * 1000))

    async def release(self) -> None:
        await self.redis.eval(_RELEASE, 1, self.key, self.token)
