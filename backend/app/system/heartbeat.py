"""Nhịp tim của process nền: mỗi role ghi `bw:hb:<role>` khi nhận việc qua đường thật
(scheduler → RabbitMQ → consumer / worker) — `GET /health/pipeline` đọc lại."""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.rkeys import rkey

ROLES = ("consume", "work", "schedule")
TTL_SECONDS = 600


def key(role: str) -> str:
    return rkey("hb", role)


async def beat(redis, role: str, now: datetime | None = None) -> None:
    await redis.set(key(role), (now or datetime.now(UTC)).isoformat(), ex=TTL_SECONDS)


async def read_all(redis, interval: float, now: datetime | None = None) -> dict[str, dict]:
    now = now or datetime.now(UTC)
    out: dict[str, dict] = {}
    for role in ROLES:
        last = await redis.get(key(role))
        age = round((now - datetime.fromisoformat(last)).total_seconds(), 1) if last else None
        out[role] = {"last": last, "age_s": age, "ok": age is not None and age <= 3 * interval}
    return out
