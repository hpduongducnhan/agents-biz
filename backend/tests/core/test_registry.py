"""Kết nối theo role + cờ MONGO_ENABLED: tắt Mongo thì không role nào cần / ping Mongo."""

import pytest

from app.core.connections.registry import ROLE_NEEDS, close_connections, init_connections, needs_for
from app.core.settings import Settings


def test_needs_for_drops_mongo_when_disabled():
    on = Settings(_env_file=None, MONGO_ENABLED=True)
    off = Settings(_env_file=None, MONGO_ENABLED=False)
    for role in ROLE_NEEDS:
        assert needs_for(role, on) == ROLE_NEEDS[role]
        assert "mongo" not in needs_for(role, off)
    assert needs_for("api", on) == frozenset({"postgres", "mongo", "redis"})
    assert needs_for("migrate", on) == frozenset({"postgres"})


def test_unknown_role_rejected():
    with pytest.raises(ValueError):
        needs_for("nope", Settings(_env_file=None))


@pytest.mark.integration
async def test_boot_without_mongo_even_if_url_is_garbage(test_settings):
    s = test_settings.model_copy(update={"MONGO_ENABLED": False, "MONGO_RW_URL": "mongodb://no-such-host:1"})
    conns = await init_connections("api", s)
    try:
        assert conns.mongo is None
        health = await conns.health()
        assert set(health) == {"postgres.rw", "postgres.ro", "redis.rw", "redis.ro"}
        assert all(v == "ok" for v in health.values())
    finally:
        await close_connections()


@pytest.mark.integration
async def test_boot_with_mongo_pings_all_channels(test_settings):
    conns = await init_connections("api", test_settings)
    try:
        health = await conns.health()
        assert {"mongo.rw", "mongo.ro"} <= set(health) and all(v == "ok" for v in health.values())
    finally:
        await close_connections()


@pytest.mark.integration
async def test_boot_fails_loudly_when_postgres_unreachable(test_settings):
    s = test_settings.model_copy(update={"POSTGRES_RW_URL": "postgresql+psycopg://x@127.0.0.1:1/bizwithagents_test"})
    with pytest.raises(RuntimeError, match="Kết nối lỗi"):
        await init_connections("migrate", s)
