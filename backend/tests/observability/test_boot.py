"""Mọi role bật / tắt sink quan sát: api qua lifespan ở cả hai chế độ; `bw work` thật khi
MONGO_ENABLED=false và URL Mongo rác — role vẫn lên, obs0001 đúng một lần, SIGTERM dừng sạch; role không có Mongo
→ Noop + obs0002 (R11)."""

import asyncio
import json
import os
import signal
import sys
from pathlib import Path

import pytest

from app import observability as obs
from app.core.migrate import run_migrations
from app.core.settings import Settings
from app.main import create_app
from app.observability import runtime
from app.observability.sinks import get_sinks
from app.observability.store import get_store
from tests.conftest import reset_test_db, reset_test_redis

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def fresh_warning_flag(monkeypatch):
    monkeypatch.setitem(obs._state, "warned", False)


async def test_role_without_mongo_handle_is_a_logged_noop(bw_log):
    sinks = await obs.init_observability(Settings(_env_file=None, MONGO_ENABLED=True), None)  # vd role schedule
    try:
        assert sinks.enabled is False and get_store() is None and runtime.current() is None
        [line] = [line for line in bw_log() if line["loc"] in ("obs0001", "obs0002")]
        assert line["loc"] == "obs0002" and "DEFAULTS_APPLIED=[sinks=noop]" in line["msg"]
    finally:
        await obs.close_observability()


@pytest.mark.integration
@pytest.mark.parametrize("mongo", [True, False], ids=["mongo-on", "mongo-off"])
async def test_api_lifespan_starts_and_stops_sinks(test_settings, mongo, bw_log):
    s = test_settings.model_copy(update={"MONGO_ENABLED": mongo})
    reset_test_db(s)
    reset_test_redis(s)
    run_migrations(s)
    app = create_app(s)
    async with app.router.lifespan_context(app):
        assert get_sinks().enabled is mongo and (get_store() is not None) is mongo
        assert (runtime.current() is not None and runtime.current().running) is mongo
    assert get_sinks().enabled is False and get_store() is None and runtime.current() is None
    locs = [line["loc"] for line in bw_log()]
    assert ("obs0003" in locs) is mongo and ("obs0001" in locs) is (not mongo)


@pytest.mark.integration
async def test_reboot_in_same_process_replaces_the_writer(mongo_stack):
    first = runtime.current()
    assert first is not None and first.running
    await obs.init_observability(mongo_stack.settings, mongo_stack.conns.mongo)
    second = runtime.current()
    assert not first.running and second is not first and second.running
    assert runtime.observability_stats()["dropped"] == 0


@pytest.mark.integration
async def test_work_role_boots_and_stops_without_mongo(test_settings):
    s = test_settings
    env = os.environ | {
        "ENV": "dev",
        "LOG_JSON": "true",
        "LOG_LEVEL": "INFO",
        "POSTGRES_RW_URL": s.POSTGRES_RW_URL,
        "POSTGRES_RO_URL": "",
        "REDIS_RW_URL": s.REDIS_RW_URL,
        "REDIS_RO_URL": "",
        "RABBITMQ_URL": s.RABBITMQ_URL,
        "MONGO_ENABLED": "false",
        "MONGO_RW_URL": "mongodb://no-such-host:1",
        "MONGO_DB_NAME": s.MONGO_DB_NAME,
        "AUTH_PRIVATE_KEY": "",
        "AUTH_PUBLIC_KEY": "",
        "AUTH_PRIVATE_KEY_FILE": s.AUTH_PRIVATE_KEY_FILE,
        "AUTH_PUBLIC_KEY_FILE": s.AUTH_PUBLIC_KEY_FILE,
        "SUPERADMIN_EMAILS": s.SUPERADMIN_EMAILS,
        "SCHEDULER_LEADER_KEY": s.SCHEDULER_LEADER_KEY,
    }
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.cli",
        "work",
        "--concurrency",
        "2",
        cwd=BACKEND,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    seen: list[dict] = []

    async def until(loc: str) -> None:
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                raise AssertionError(f"process thoát sớm, log cuối: {seen[-5:]}")
            try:
                line = json.loads(raw)
            except ValueError:
                seen.append({"raw": raw.decode(errors="replace")})
                continue
            seen.append(line)
            if line.get("loc") == loc:
                return

    try:
        await asyncio.wait_for(until("obs0001"), 30)
        await asyncio.wait_for(until("boot0004"), 30)  # role đang chạy
        proc.send_signal(signal.SIGTERM)
        await asyncio.wait_for(until("boot0005"), 20)  # dừng sạch
        assert await asyncio.wait_for(proc.wait(), 10) == 0
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
    assert [line.get("loc") for line in seen].count("obs0001") == 1
