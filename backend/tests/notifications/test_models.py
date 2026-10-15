"""Bảng thông báo + cài đặt hệ thống: migration 0003 nối sau auth, đúng bảng / index / ràng buộc, khớp model,
downgrade sạch."""

import psycopg
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, pool
from sqlmodel import SQLModel

import app.models  # noqa: F401 — nạp mọi bảng vào metadata
from app.core.migrate import alembic_config, current_revision, run_migrations
from app.core.settings import Settings
from tests.conftest import head_revision, reset_test_db

MINE_REV = "0003_notifications_system"
MINE = ("notifications", "system_settings")


def _dsn(s) -> str:
    return s.POSTGRES_RW_URL.replace("postgresql+psycopg://", "postgresql://", 1)


def test_single_head_chains_after_auth():
    script = ScriptDirectory.from_config(alembic_config(Settings(_env_file=None)))
    assert script.get_heads() == [head_revision()]
    down = script.get_revision(script.get_revision(MINE_REV).down_revision)
    chain = [
        MINE_REV, "0004_agent_config", "0005_agent_chat", "0007_agent_routes", "0008_chat_blocks",
    ]  # fmt: skip
    assert [script.get_revision(r).down_revision for r in chain[1:]] == chain[:-1]
    assert down.revision != "0001"  # nối sau auth (bảng users), không nối thẳng baseline


@pytest.mark.integration
def test_upgrade_creates_tables_seed_row_and_constraints(test_settings):
    reset_test_db(test_settings)
    run_migrations(test_settings)
    assert current_revision(test_settings) == head_revision()
    with psycopg.connect(_dsn(test_settings)) as conn:
        assert conn.execute("select id, data from system_settings").fetchall() == [(1, {})]
        idx = {r[0] for r in conn.execute("select indexname from pg_indexes where tablename = 'notifications'")}
        assert {"ix_notifications_inbox", "ix_notifications_created_at"} <= idx
        ondelete = conn.execute(
            "select confdeltype from pg_constraint where conrelid = 'notifications'::regclass and contype = 'f'"
        ).fetchall()
        assert ondelete == [("c",)]  # xoá user → xoá inbox của user đó
    with psycopg.connect(_dsn(test_settings)) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("insert into system_settings (id, data) values (2, '{}'::jsonb)")


@pytest.mark.integration
def test_models_match_migration(test_settings):
    reset_test_db(test_settings)
    run_migrations(test_settings)
    engine = create_engine(test_settings.POSTGRES_RW_URL, poolclass=pool.NullPool)
    try:
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), SQLModel.metadata)
    finally:
        engine.dispose()
    assert [d for d in diff if any(name in str(d) for name in MINE)] == []


@pytest.mark.integration
def test_downgrade_then_upgrade_again(test_settings):
    reset_test_db(test_settings)
    run_migrations(test_settings)
    command.downgrade(alembic_config(test_settings), "0002_auth_rbac")  # lùi qua cả 0003
    with psycopg.connect(_dsn(test_settings)) as conn:
        tables = {r[0] for r in conn.execute("select tablename from pg_tables where schemaname = 'public'")}
    assert not set(MINE) & tables
    run_migrations(test_settings)
    assert current_revision(test_settings) == head_revision()
