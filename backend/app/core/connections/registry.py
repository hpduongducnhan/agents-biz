"""Tạo kết nối theo process role trong lifespan; health; đóng khi tắt. Mongo theo cờ MONGO_ENABLED."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.core.connections.mongo import Mongo
from app.core.connections.postgres import Postgres
from app.core.connections.redis import Redis
from app.core.logging import get_logger
from app.core.redact import redact_dsn
from app.core.settings import Settings

logger = get_logger(__name__)
_ALL = frozenset({"postgres", "mongo", "redis"})
ROLE_NEEDS: dict[str, frozenset[str]] = {
    "api": _ALL,
    "consume": _ALL,
    "work": _ALL,
    "schedule": frozenset({"postgres", "redis"}),
    "migrate": frozenset({"postgres"}),
}
CHANNELS = ("rw", "ro")


def needs_for(role: str, settings: Settings) -> frozenset[str]:
    if role not in ROLE_NEEDS:
        raise ValueError(f"role không hợp lệ: {role}")
    needs = ROLE_NEEDS[role]
    return needs if settings.MONGO_ENABLED else needs - {"mongo"}


@dataclass
class Connections:
    postgres: Postgres | None = None
    mongo: Mongo | None = None
    redis: Redis | None = None

    def resources(self) -> dict[str, Postgres | Mongo | Redis]:
        pairs = (("postgres", self.postgres), ("mongo", self.mongo), ("redis", self.redis))
        return {name: res for name, res in pairs if res is not None}

    async def health(self, timeout: float = 2.0) -> dict[str, str]:
        out: dict[str, str] = {}
        for name, res in self.resources().items():
            for channel in CHANNELS:
                try:
                    await asyncio.wait_for(res.ping(channel), timeout)
                    out[f"{name}.{channel}"] = "ok"
                except Exception as exc:  # noqa: BLE001 — health phải trả kết quả, không được nổ
                    logger.warning("health %s.%s lỗi: %s", name, channel, exc, extra={"loc": "db0500"})
                    out[f"{name}.{channel}"] = f"error: {type(exc).__name__}"
        return out

    async def close(self) -> None:
        for res in self.resources().values():
            await res.close()


_current: Connections | None = None


def _describe(settings: Settings, needs: frozenset[str]) -> dict[str, str]:
    urls = {
        "postgres.rw": settings.POSTGRES_RW_URL,
        "postgres.ro": settings.postgres_ro_url,
        "mongo.rw": settings.MONGO_RW_URL,
        "mongo.ro": settings.mongo_ro_url,
        "redis.rw": settings.REDIS_RW_URL,
        "redis.ro": settings.redis_ro_url,
    }
    return {k: redact_dsn(v) for k, v in urls.items() if k.split(".")[0] in needs}


async def init_connections(role: str, settings: Settings) -> Connections:
    """Tạo kết nối role cần + ping đủ mọi kênh; lỗi → đóng hết và dừng boot."""
    global _current
    needs = needs_for(role, settings)
    conns = Connections(
        postgres=Postgres(settings) if "postgres" in needs else None,
        mongo=Mongo(settings) if "mongo" in needs else None,
        redis=Redis(settings) if "redis" in needs else None,
    )
    health = await conns.health()
    failed = {k: v for k, v in health.items() if v != "ok"}
    if failed:
        await conns.close()
        logger.error("không kết nối được lúc khởi động: %s", failed, extra={"loc": "db0501"})
        raise RuntimeError(f"Kết nối lỗi lúc khởi động: {failed}")
    logger.info("kết nối sẵn sàng role=%s", role, extra={"loc": "db0001", "conns": _describe(settings, needs)})
    _current = conns
    return conns


def get_connections() -> Connections:
    if _current is None:
        raise RuntimeError("Chưa init_connections — kết nối chỉ có sau lifespan của process")
    return _current


async def close_connections() -> None:
    global _current
    if _current is not None:
        await _current.close()
        _current = None
        logger.info("đã đóng kết nối", extra={"loc": "db0002"})
