"""Health: live luôn 200; ready gom DB + RabbitMQ (mongo "disabled" khi tắt); pipeline theo nhịp tim."""

import logging
from datetime import UTC, datetime

import pytest

from app.core.messaging.hub import has_hub, set_hub
from app.core.settings import Settings
from app.main import create_app
from tests.conftest import asgi_client


class FakeConns:
    def __init__(self, checks: dict[str, str], beats: dict[str, str] | None = None):
        self._checks = checks
        self.redis = type("R", (), {"ro": FakeRedis(beats or {})})()

    async def health(self):
        return dict(self._checks)


class FakeRedis:
    def __init__(self, data):
        self.data = data

    async def get(self, key):
        return self.data.get(key)


class FakeHub:
    def __init__(self, status="ok"):
        self.status = status

    async def ping(self):
        return self.status


OK = {"postgres.rw": "ok", "postgres.ro": "ok", "redis.rw": "ok", "redis.ro": "ok"}


def _app(conns, hub=None, **kw):
    app = create_app(Settings(_env_file=None, **kw), connect=False)
    app.state.conns = conns
    set_hub(hub)
    return app


async def test_live_reports_service_and_version():
    async with asgi_client(_app(None, BUILD_VERSION="abc123")) as c:
        r = await c.get("/bizwithagents/api/health/live")
    assert r.status_code == 200
    assert r.json()["data"] == {"status": "ok", "service": "bizwithagents-backend", "version": "abc123"}


async def test_ready_ok_with_mongo_disabled():
    async with asgi_client(_app(FakeConns(OK), FakeHub(), MONGO_ENABLED=False)) as c:
        r = await c.get("/bizwithagents/api/health/ready")
    assert r.status_code == 200
    assert r.json()["data"] == OK | {"mongo": "disabled", "rabbitmq": "ok"}
    set_hub(None)


async def test_ready_503_when_a_channel_fails():
    checks = OK | {"redis.ro": "error: TimeoutError"}
    async with asgi_client(_app(FakeConns(checks), FakeHub())) as c:
        r = await c.get("/bizwithagents/api/health/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["success"] is False and body["code"] == 1008 and body["data"]["redis.ro"].startswith("error")
    set_hub(None)


async def test_ready_503_when_broker_down_or_not_connected():
    async with asgi_client(_app(FakeConns(OK), FakeHub("error: ConnectionError"))) as c:
        assert (await c.get("/bizwithagents/api/health/ready")).status_code == 503
    async with asgi_client(_app(None)) as c:
        assert (await c.get("/bizwithagents/api/health/ready")).status_code == 503
    set_hub(None)


async def test_pipeline_200_only_when_every_role_is_fresh():
    now = datetime.now(UTC).isoformat()
    fresh = {f"bw:hb:{r}": now for r in ("consume", "work", "schedule")}
    async with asgi_client(_app(FakeConns(OK, fresh))) as c:
        r = await c.get("/bizwithagents/api/health/pipeline")
    assert r.status_code == 200 and all(v["ok"] for v in r.json()["data"].values())
    stale = fresh | {"bw:hb:work": "2020-01-01T00:00:00+00:00"}
    async with asgi_client(_app(FakeConns(OK, stale))) as c:
        r = await c.get("/bizwithagents/api/health/pipeline")
    assert r.status_code == 503 and r.json()["data"]["work"]["ok"] is False


@pytest.mark.integration
@pytest.mark.parametrize("mongo", [True, False])
async def test_lifespan_connects_real_services_and_ready_is_200(test_settings, mongo):
    s = test_settings.model_copy(update={"MONGO_ENABLED": mongo})
    app = create_app(s)
    root = logging.getLogger()
    saved = root.handlers[:]
    try:
        async with app.router.lifespan_context(app):
            assert has_hub() and app.state.conns is not None
            async with asgi_client(app) as c:
                r = await c.get("/bizwithagents/api/health/ready")
        assert not has_hub()
    finally:
        root.handlers = saved
    assert r.status_code == 200, r.json()
    data = r.json()["data"]
    assert data["rabbitmq"] == "ok" and data["postgres.rw"] == "ok" and data["redis.ro"] == "ok"
    assert (data["mongo.rw"] == "ok") if mongo else (data["mongo"] == "disabled" and "mongo.rw" not in data)
