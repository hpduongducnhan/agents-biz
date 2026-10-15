"""`bw seed-test-users`: 2 tenant + 7 user test, role đúng, mật khẩu SEED_PASSWORD, chạy lại không trùng mà đặt lại
trạng thái; từ chối ở prod; cảnh báo khi superadmin@test.local không có trong SUPERADMIN_EMAILS."""

import asyncio
import logging

import pytest
from sqlalchemy import text
from typer.testing import CliRunner

from app.auth.seed import SEED_USERS, seed_target_problem, seed_test_users
from app.cli import cli
from app.core.connections.registry import get_connections
from app.core.migrate import run_migrations, run_post_migrate
from app.core.settings import get_settings
from app.domains import load_domains
from tests.conftest import reset_test_db

runner = CliRunner()
EMAILS = [email for email, *_ in SEED_USERS]


def test_cli_refuses_in_prod(monkeypatch):
    monkeypatch.setenv("ENV", "prod")
    get_settings.cache_clear()
    try:
        result = runner.invoke(cli, ["seed-test-users"])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 1 and "prod" in result.output


async def test_seed_function_refuses_prod(test_settings):
    with pytest.raises(RuntimeError, match="prod"):
        await seed_test_users(test_settings.model_copy(update={"ENV": "prod"}))


@pytest.mark.integration
async def test_seed_creates_users_once_and_restores_state(api, app_env, bw_log):
    first = await seed_test_users(app_env)
    assert [r["email"] for r in first] == EMAILS and all(r["created"] for r in first)
    assert any(line.get("loc") == "auth0402" for line in bw_log())  # superadmin@test.local chưa có trong env test
    admin = await api.login("admin@test.local")
    assert sorted(r["name"] for r in admin.user["roles"]) == ["admin"]
    assert admin.user["tenant"]["slug"] == "default" and admin.user["email_verified"] is True
    acme = await api.login("acme1@test.local")
    assert acme.user["tenant"]["slug"] == "acme"
    u1 = await api.login("user1@test.local")
    await api.post("auth.change_password", u1, current_password="password123", new_password="doi-roi-123")
    again = await seed_test_users(app_env)
    assert not any(r["created"] for r in again)
    await api.login("user1@test.local")  # mật khẩu về lại SEED_PASSWORD
    async with get_connections().postgres.ro() as s:
        n = (await s.exec(text("select count(*) from users where email like '%@test.local'"))).one()[0]
        tenants = (await s.exec(text("select count(*) from tenants where slug in ('default', 'acme')"))).one()[0]
    assert n == 7 and tenants == 2


@pytest.mark.integration
async def test_superadmin_seed_follows_env(api, app_env, monkeypatch):
    monkeypatch.setattr(app_env, "SUPERADMIN_EMAILS", "root@test.local,superadmin@test.local")
    rows = {r["email"]: r for r in await seed_test_users(app_env)}
    assert rows["superadmin@test.local"]["superadmin"] and not rows["admin@test.local"]["superadmin"]
    assert (await api.login("superadmin@test.local")).user["is_superadmin"] is True


@pytest.mark.integration
def test_cli_seeds_on_dev(test_settings, monkeypatch):
    reset_test_db(test_settings)
    load_domains()
    run_migrations(test_settings)
    asyncio.run(run_post_migrate(test_settings))
    for name in ("POSTGRES_RW_URL", "RABBITMQ_URL", "AUTH_PRIVATE_KEY_FILE", "AUTH_PUBLIC_KEY_FILE"):
        monkeypatch.setenv(name, str(getattr(test_settings, name)))
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("SUPERADMIN_EMAILS", "superadmin@test.local")
    get_settings.cache_clear()
    try:
        result = runner.invoke(cli, ["seed-test-users"])
    finally:
        get_settings.cache_clear()
        logging.getLogger().handlers.clear()
    assert result.exit_code == 0, result.output
    assert "+ superadmin@test.local roles=member superadmin" in result.output
    assert "+ admin@test.local roles=admin" in result.output
    assert "+ acme1@test.local roles=member" in result.output


@pytest.mark.integration
async def test_seed_refuses_db_without_test_suffix(app_env):
    real = app_env.model_copy(update={"POSTGRES_RW_URL": app_env.POSTGRES_RW_URL.rsplit("/", 1)[0] + "/bizwithagents"})
    assert seed_target_problem(real) and "bizwithagents" in seed_target_problem(real)
    assert seed_target_problem(app_env) is None
    with pytest.raises(RuntimeError, match="dữ liệu thật"):
        await seed_test_users(real)
    async with get_connections().postgres.ro() as s:
        assert (await s.exec(text("select count(*) from users"))).one()[0] == 0


@pytest.mark.integration
async def test_cli_refuses_db_without_test_suffix(app_env, monkeypatch):
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("POSTGRES_RW_URL", app_env.POSTGRES_RW_URL.rsplit("/", 1)[0] + "/bizwithagents")
    get_settings.cache_clear()
    try:
        result = runner.invoke(cli, ["seed-test-users"])
    finally:
        get_settings.cache_clear()
        logging.getLogger().handlers.clear()
    assert result.exit_code == 1 and "✗ từ chối" in result.output and "bizwithagents" in result.output
    async with get_connections().postgres.ro() as s:
        assert (await s.exec(text("select count(*) from users"))).one()[0] == 0
