"""`bw migrate`: một chuỗi Alembic; chạy lại không làm gì (Coolify chạy migrate mỗi lần deploy)."""

import psycopg
import pytest

from app.core import migrate as migrate_mod
from app.core.migrate import current_revision, run_migrations
from tests.conftest import head_revision, reset_test_db

pytestmark = pytest.mark.integration


def _dsn(s) -> str:
    return s.POSTGRES_RW_URL.replace("postgresql+psycopg://", "postgresql://", 1)


def test_upgrade_twice_is_noop_and_creates_citext(test_settings):
    reset_test_db(test_settings)
    run_migrations(test_settings)
    assert current_revision(test_settings) == head_revision()
    run_migrations(test_settings)
    assert current_revision(test_settings) == head_revision()
    with psycopg.connect(_dsn(test_settings)) as conn:
        assert conn.execute("select 1 from pg_extension where extname = 'citext'").fetchone() == (1,)
        assert conn.execute("select version_num from alembic_version").fetchone() == (head_revision(),)


def test_current_revision_none_on_empty_db(test_settings):
    reset_test_db(test_settings)
    assert current_revision(test_settings) is None


async def test_post_migrate_steps_run_in_order(test_settings, monkeypatch):
    reset_test_db(test_settings)
    run_migrations(test_settings)
    calls: list[str] = []
    monkeypatch.setattr(migrate_mod, "_STEPS", {})

    @migrate_mod.post_migrate_step("b.second", order=20)
    async def second(session, settings):
        calls.append("b")
        return {"n": 2}

    @migrate_mod.post_migrate_step("a.first", order=10)
    async def first(session, settings):
        calls.append("a")

    assert await migrate_mod.run_post_migrate(test_settings) == {"a.first": None, "b.second": {"n": 2}}
    assert calls == ["a", "b"]
