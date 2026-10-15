"""Bảng route + cột `agent_runs.plan` (0011_agent_routes): khớp model, ràng buộc, cascade, downgrade sạch."""

import psycopg
import pytest
from alembic import command
from psycopg import errors as pg_errors

import app.models  # noqa: F401 — nạp mọi bảng vào metadata
from app.core.migrate import alembic_config, current_revision, make_revision, run_migrations
from tests.conftest import head_revision, plain_dsn, reset_test_db

pytestmark = pytest.mark.integration


@pytest.fixture
def conn(test_settings):
    reset_test_db(test_settings)
    run_migrations(test_settings)
    with psycopg.connect(plain_dsn(test_settings), autocommit=True) as c:
        yield c


def tables(conn) -> set[str]:
    return {r[0] for r in conn.execute("select tablename from pg_tables where schemaname = 'public'")}


def new_agent(conn, slug, kind="specialist"):
    return conn.execute(
        "insert into agents (id, slug, name, kind, key_strategy, visible_to, persona_shared, is_active)"
        " values (gen_random_uuid(), %s, 'A', %s, 'round_robin', 'all', true, true) returning id",
        (slug, kind),
    ).fetchone()[0]


def columns(conn, table) -> dict[str, tuple[str, str]]:
    rows = conn.execute(
        "select column_name, data_type, is_nullable from information_schema.columns where table_name = %s", (table,)
    )
    return {r[0]: (r[1], r[2]) for r in rows}


def test_route_table_and_plan_column_match_migration(conn, test_settings):
    assert "orchestrator_routes" in tables(conn)
    cols = columns(conn, "orchestrator_routes")
    assert cols["examples"] == ("jsonb", "NO") and cols["enabled"] == ("boolean", "NO")
    assert cols["position"][0] == "integer" and cols["intent"] == ("text", "NO")
    assert columns(conn, "agent_runs")["plan"] == ("jsonb", "YES")
    path = make_revision(test_settings, "kiểm lệch agent routes")
    try:
        body = path.read_text(encoding="utf-8")
        assert "op." not in body.split("def upgrade() -> None:")[1].split("def downgrade")[0]
    finally:
        path.unlink()


def test_route_primary_key_defaults_and_cascade(conn):
    orch, spec = new_agent(conn, "o1", "orchestrator"), new_agent(conn, "s1")
    ins = "insert into orchestrator_routes (orchestrator_id, agent_id) values (%s, %s)"
    conn.execute(ins, (orch, spec))
    row = conn.execute("select intent, examples, position, enabled from orchestrator_routes").fetchone()
    assert row == ("", [], 0, True)
    with pytest.raises(pg_errors.UniqueViolation):
        conn.execute(ins, (orch, spec))
    with pytest.raises(pg_errors.ForeignKeyViolation):
        conn.execute(ins, (orch, "00000000-0000-0000-0000-000000000001"))
    conn.execute("delete from agents where id = %s", (spec,))  # xoá chuyên gia đích → route biến mất
    assert conn.execute("select count(*) from orchestrator_routes").fetchone()[0] == 0
    conn.execute(ins, (orch, new_agent(conn, "s2")))
    conn.execute("delete from agents where id = %s", (orch,))  # xoá orchestrator → route biến mất
    assert conn.execute("select count(*) from orchestrator_routes").fetchone()[0] == 0


def test_downgrade_drops_routes_and_plan_then_upgrade_again(conn, test_settings):
    command.downgrade(alembic_config(test_settings), "0005_agent_chat")
    assert current_revision(test_settings) == "0005_agent_chat"
    assert "orchestrator_routes" not in tables(conn) and "plan" not in columns(conn, "agent_runs")
    run_migrations(test_settings)
    assert current_revision(test_settings) == head_revision()
    assert "orchestrator_routes" in tables(conn) and "plan" in columns(conn, "agent_runs")
