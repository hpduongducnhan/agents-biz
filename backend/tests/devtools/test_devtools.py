"""Công cụ dev: chỉ bật ở ENV dev / smoke; gây lỗi có chủ đích; chỉ superadmin; route ẩn khỏi OpenAPI, gỡ ở prod."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from app.core.errors import AppException
from app.core.operations.runner import run_operation
from app.core.security.principal import Principal
from app.core.settings import Settings
from app.devtools import ops as devtools_ops
from app.devtools.guard import DEV_ENVS, devtools_enabled, guard_devtools_routes
from app.devtools.ops import DevError, RaiseErrorIn, RunTaskIn, raise_error, run_task

BOOM = "/bizwithagents/api/devtools/raise_error"
LIVE = "/bizwithagents/api/health/live"


def test_guard_only_dev_and_smoke():
    assert DEV_ENVS == frozenset({"dev", "smoke"})
    for env in ("dev", "smoke", " Dev "):
        assert devtools_enabled(Settings(_env_file=None, ENV=env))
    for env in ("prod", "production", "staging", "test", ""):
        assert not devtools_enabled(Settings(_env_file=None, ENV=env))


async def test_raise_error_raises_dev_error_with_note():
    with pytest.raises(DevError, match="smoke-1"):
        await raise_error(SimpleNamespace(), RaiseErrorIn(note="smoke-1"))


async def test_raise_error_is_superadmin_only():
    admin = Principal(user_id=uuid.uuid4(), perms=frozenset({"user.view", "user.manage", "role.manage"}), sup=False)
    with pytest.raises(AppException) as err:
        await run_operation("devtools.raise_error", admin, {})
    assert err.value.code == 1005


async def test_run_task_runs_scheduled_task_by_name(monkeypatch):
    async def job():
        return {"n": uuid.UUID(int=1)}

    spec = SimpleNamespace(name="demo.job", func=job)
    monkeypatch.setattr(devtools_ops, "scheduled_tasks", lambda: [spec])
    out = await run_task(SimpleNamespace(), RunTaskIn(name="demo.job"))
    assert out.name == "demo.job" and out.result == {"n": str(uuid.UUID(int=1))}


async def test_run_task_unknown_name_is_404(monkeypatch):
    monkeypatch.setattr(devtools_ops, "scheduled_tasks", lambda: [])
    with pytest.raises(AppException) as err:
        await run_task(SimpleNamespace(), RunTaskIn(name="demo.none"))
    assert (err.value.code, err.value.status_code) == (1001, 404)


def test_run_task_rejects_bad_name_and_is_superadmin_only():
    with pytest.raises(ValueError):
        RunTaskIn(name="Bad Name")


async def test_run_task_denies_non_superadmin():
    admin = Principal(user_id=uuid.uuid4(), perms=frozenset({"user.view"}), sup=False)
    with pytest.raises(AppException) as err:
        await run_operation("devtools.run_task", admin, {"name": "system.ping"})
    assert err.value.code == 1005


def _app() -> FastAPI:
    app = FastAPI()
    app.add_api_route(BOOM, lambda: {}, methods=["POST"])
    app.add_api_route(LIVE, lambda: {}, methods=["GET"])
    return app


def test_guard_keeps_devtools_route_but_hides_it_from_openapi_in_dev():
    app = _app()
    guard_devtools_routes(app, Settings(_env_file=None, ENV="dev"))
    assert BOOM in {r.path for r in app.routes}
    paths = app.openapi()["paths"]
    assert BOOM not in paths and LIVE in paths


def test_guard_removes_devtools_routes_outside_dev():
    app = _app()
    guard_devtools_routes(app, Settings(_env_file=None, ENV="prod"))
    paths = {r.path for r in app.routes}
    assert BOOM not in paths and LIVE in paths
