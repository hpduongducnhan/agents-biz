"""CLI `bw`: đủ lệnh; check-config báo thiếu và trả mã lỗi."""

import asyncio
import logging
import sys
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from app import cli as cli_module
from app.cli import cli, main
from app.core.httpx_log import uninstall_httpx_logging
from app.core.messaging.hub import has_hub
from app.core.messaging.tasks import all_tasks
from app.core.migrate import current_revision
from app.core.settings import get_settings
from app.observability.sinks import get_sinks
from tests.conftest import head_revision, reset_test_db

runner = CliRunner()


def test_help_lists_all_roles():
    out = runner.invoke(cli, ["--help"]).output
    for cmd in ("api", "keys", "migrate", "revision", "check-config", "seed-test-users", "consume", "work", "schedule"):
        assert cmd in out


def test_check_config_fails_on_missing_broker(monkeypatch):
    monkeypatch.setenv("RABBITMQ_URL", "")
    monkeypatch.setenv("MONGO_ENABLED", "false")
    get_settings.cache_clear()
    try:
        result = runner.invoke(cli, ["check-config"])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 1 and "RABBITMQ_URL" in result.output


def test_check_config_ok(monkeypatch):
    monkeypatch.setenv("RABBITMQ_URL", "amqp://u:p@h/bizwithagents")
    monkeypatch.setenv("MONGO_ENABLED", "false")
    monkeypatch.setenv("AUTH_PRIVATE_KEY_FILE", "/k/a.pem")
    monkeypatch.setenv("AUTH_PUBLIC_KEY_FILE", "/k/b.pem")
    monkeypatch.setenv("ENV", "dev")
    get_settings.cache_clear()
    try:
        result = runner.invoke(cli, ["check-config"])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 0 and "cấu hình hợp lệ" in result.output


@pytest.fixture
def test_env(monkeypatch, test_settings, tmp_path):
    """Env trỏ vào tài nguyên *_test + thư mục khoá tạm; trả lại handler root mà configure_logging đã thay."""
    env = {
        "POSTGRES_RW_URL": test_settings.POSTGRES_RW_URL,
        "POSTGRES_RO_URL": "",
        "REDIS_RW_URL": test_settings.REDIS_RW_URL,
        "REDIS_RO_URL": "",
        "RABBITMQ_URL": test_settings.RABBITMQ_URL,
        "MONGO_ENABLED": "false",
        "AUTH_PRIVATE_KEY": "",
        "AUTH_PUBLIC_KEY": "",
        "AUTH_PRIVATE_KEY_FILE": str(tmp_path / "keys" / "jwt_private.pem"),
        "AUTH_PUBLIC_KEY_FILE": str(tmp_path / "keys" / "jwt_public.pem"),
        "ENV": "dev",
        "LOG_JSON": "true",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    root = logging.getLogger()
    saved = root.handlers[:]
    yield tmp_path / "keys"
    root.handlers = saved
    get_settings.cache_clear()


def test_keys_generates_then_reports_exists(test_env):
    first = runner.invoke(cli, ["keys"])
    assert first.exit_code == 0 and "khoá JWT: generated" in first.output
    assert (test_env / "jwt_private.pem").is_file() and (test_env / "jwt_public.pem").is_file()
    second = runner.invoke(cli, ["keys"])
    assert second.exit_code == 0 and "khoá JWT: exists" in second.output


def test_keys_print_outputs_env_lines_and_writes_nothing(test_env):
    result = runner.invoke(cli, ["keys", "--print"])
    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert len(lines) == 2 and lines[0].startswith("AUTH_PRIVATE_KEY=-----BEGIN PRIVATE KEY-----\\n")
    assert lines[1].startswith("AUTH_PUBLIC_KEY=-----BEGIN PUBLIC KEY-----\\n")
    assert not test_env.exists()


@pytest.mark.integration
def test_migrate_runs_to_head_and_stops_on_bad_config(test_env, test_settings, monkeypatch):
    reset_test_db(test_settings)
    result = runner.invoke(cli, ["migrate"])
    assert result.exit_code == 0, result.output
    assert current_revision(test_settings) == head_revision()
    monkeypatch.setenv("RABBITMQ_URL", "")
    get_settings.cache_clear()
    assert runner.invoke(cli, ["migrate"]).exit_code == 1


def test_revision_passes_message_and_flag(test_env, monkeypatch):
    calls = []

    def fake_revision(settings, message, *, autogenerate):
        calls.append((message, autogenerate))
        return Path("/tmp/0002_x.py")

    monkeypatch.setattr(cli_module, "make_revision", fake_revision)
    result = runner.invoke(cli, ["revision", "-m", "thêm bảng", "--no-autogenerate"])
    assert result.exit_code == 0 and "0002_x.py" in result.output
    assert calls == [("thêm bảng", False)]


def test_api_runs_uvicorn_factory(test_env, monkeypatch):
    calls = []
    monkeypatch.setattr(cli_module.uvicorn, "run", lambda app, **kw: calls.append((app, kw)))
    assert runner.invoke(cli, ["api", "--port", "9999"]).exit_code == 0
    app, kw = calls[0]
    assert app == "app.main:create_app" and kw["factory"] is True and kw["port"] == 9999 and kw["reload"] is False


@pytest.mark.integration
@pytest.mark.parametrize("role", ["consume", "work", "schedule"])
def test_background_roles_boot_and_shut_down_cleanly(test_env, monkeypatch, role):
    seen = {}

    async def fake_run(settings, conns, *args, stop, **_kwargs):
        seen.update(role=role, args=args, redis=conns.redis is not None, stop=stop.is_set())

    monkeypatch.setattr(cli_module, f"run_{role}", fake_run)
    args = [role, "--concurrency", "3"] if role == "work" else [role]
    result = runner.invoke(cli, args)
    assert result.exit_code == 0, result.output
    assert seen == {"role": role, "args": (3,) if role == "work" else (), "redis": True, "stop": False}


def test_main_entrypoint_shows_help(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["bw", "--help"])
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 0


def test_consume_and_work_accept_lanes():
    for cmd in ("consume", "work"):
        assert "--lanes" in runner.invoke(cli, [cmd, "--help"]).output


def test_unknown_lane_is_rejected_before_boot():
    assert runner.invoke(cli, ["work", "--lanes", "khong-co"]).exit_code == 2


WORK_LANES = [([], True), (["--lanes", "agent-run"], True), (["--lanes", "default"], False)]


@pytest.mark.parametrize(("lanes", "warm"), WORK_LANES)
def test_work_warms_llm_providers_only_with_agent_lane(monkeypatch, lanes, warm):
    calls: list = []
    monkeypatch.setattr(cli_module, "_serve", lambda role, run: calls.append(("serve", role, run)))
    monkeypatch.setattr(cli_module, "warm_providers", lambda: calls.append(("warm",)))

    async def fake_work(settings, conns, concurrency, *, stop, lanes):
        calls.append(("work", lanes))

    monkeypatch.setattr(cli_module, "run_work", fake_work)
    assert runner.invoke(cli, ["work", *lanes]).exit_code == 0
    (_, role, run), *_ = calls
    asyncio.run(run(None, None, asyncio.Event()))
    assert role == "work" and (("warm",) in calls) is warm and calls[-1][0] == "work"


def test_background_processes_install_the_patch(monkeypatch):
    calls = []
    monkeypatch.setattr(cli_module, "install_httpx_logging", lambda rules, keys, *, log: calls.append(log) or [])
    cli_module.install_outbound(cli_module.get_settings())
    assert calls == [cli_module.get_settings().LOG_HTTP_OUT]


@pytest.mark.integration
def test_serve_boots_a_background_role_and_shuts_down(test_settings, monkeypatch, bw_log):
    s = test_settings.model_copy(update={"MONGO_ENABLED": False})
    monkeypatch.setattr(cli_module, "get_settings", lambda: s)
    seen: dict = {}

    async def run(settings, conns, stop):
        seen.update(hub=has_hub(), sinks=get_sinks().enabled, tasks={t.name for t in all_tasks()})

    try:
        cli_module._serve("work", run)
    finally:
        logging.getLogger().handlers.clear()
        uninstall_httpx_logging()
    assert seen["hub"] is True and seen["sinks"] is False and "system.ping" in seen["tasks"]
    assert not has_hub()
    locs = [line["loc"] for line in bw_log()]
    assert "boot0004" in locs and "boot0005" in locs


@pytest.mark.integration
def test_migrate_command_runs_post_migrate_steps(test_settings, monkeypatch):
    reset_test_db(test_settings)
    for name in (
        "POSTGRES_RW_URL",
        "RABBITMQ_URL",
        "AUTH_PRIVATE_KEY_FILE",
        "AUTH_PUBLIC_KEY_FILE",
        "SUPERADMIN_EMAILS",
    ):
        monkeypatch.setenv(name, str(getattr(test_settings, name)))
    monkeypatch.setenv("MONGO_ENABLED", "false")
    monkeypatch.setenv("ENV", "dev")
    get_settings.cache_clear()
    try:
        result = runner.invoke(cli, ["migrate"])
    finally:
        get_settings.cache_clear()
        logging.getLogger().handlers.clear()
    assert result.exit_code == 0, result.output
    dsn = test_settings.POSTGRES_RW_URL.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(dsn) as conn:
        assert conn.execute("select count(*) from permissions where deprecated_at is null").fetchone()[0] >= 5
        assert {r[0] for r in conn.execute("select name from roles where is_builtin")} == {"admin", "member", "viewer"}
