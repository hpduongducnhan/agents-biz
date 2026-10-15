"""Bảng chat (0005_agent_chat): theo tenant (D22), ràng buộc, schema checkpointer, downgrade sạch."""

import psycopg
import pytest
from alembic import command
from psycopg import errors as pg_errors

import app.models  # noqa: F401 — nạp mọi bảng vào metadata
from app.core.migrate import alembic_config, current_revision, make_revision, run_migrations
from tests.conftest import head_revision, plain_dsn, reset_test_db

pytestmark = pytest.mark.integration
CHAT = {"agent_sessions", "agent_messages", "agent_runs", "agent_approvals"}
T = "00000000-0000-4000-8000-000000000001"  # tenant default (migration 0002)


@pytest.fixture
def conn(test_settings):
    reset_test_db(test_settings)
    run_migrations(test_settings)
    with psycopg.connect(plain_dsn(test_settings), autocommit=True) as c:
        yield c


def tables(conn) -> set[str]:
    return {r[0] for r in conn.execute("select tablename from pg_tables where schemaname = 'public'")}


def seed(conn):
    uid = conn.execute(
        "insert into users (id, tenant_id, email, name, timezone, locale, is_active, is_superadmin,"
        " must_change_password) values (gen_random_uuid(), %s, 'a@x.io', '', 'UTC', 'vi', true, false, false)"
        " returning id",
        (T,),
    ).fetchone()[0]
    aid = conn.execute("select id from agents where slug = 'assistant'").fetchone()
    aid = (
        aid[0]
        if aid
        else conn.execute(
            "insert into agents (id, slug, name, kind, key_strategy, visible_to, persona_shared, is_active)"
            " values (gen_random_uuid(), 'x', 'A',"
            " 'specialist', 'round_robin', 'all', true, true) returning id"
        ).fetchone()[0]
    )
    sid = conn.execute(
        "insert into agent_sessions (id, tenant_id, user_id, entry_agent_id, title)"
        " values (gen_random_uuid(), %s, %s, %s, 't') returning id",
        (T, uid, aid),
    ).fetchone()[0]
    return uid, aid, sid


def run(conn, uid, aid, sid, status):
    return conn.execute(
        "insert into agent_runs (id, tenant_id, session_id, user_id, entry_agent_id, status)"
        " values (gen_random_uuid(), %s, %s, %s, %s, %s) returning id",
        (T, sid, uid, aid, status),
    ).fetchone()[0]


def test_chat_tables_exist_and_models_match_migration(conn, test_settings):
    assert CHAT <= tables(conn) and "agent_usage_hourly" not in tables(conn)
    not_null = {
        r[0]
        for r in conn.execute(
            "select table_name from information_schema.columns where column_name = 'tenant_id' and is_nullable = 'NO'"
        )
    }
    assert CHAT <= not_null
    schemas = {r[0] for r in conn.execute("select schema_name from information_schema.schemata")}
    assert "agent_lg" in schemas
    path = make_revision(test_settings, "kiểm lệch agent chat")
    try:
        body = path.read_text(encoding="utf-8")
        assert "op." not in body.split("def upgrade() -> None:")[1].split("def downgrade")[0]
    finally:
        path.unlink()


def test_one_open_run_per_session_index(conn):
    uid, aid, sid = seed(conn)
    run(conn, uid, aid, sid, "done")
    run(conn, uid, aid, sid, "failed")  # nhiều run đã đóng thì được
    first = run(conn, uid, aid, sid, "queued")
    for status in ("queued", "running", "waiting_approval"):
        with pytest.raises(pg_errors.UniqueViolation):
            run(conn, uid, aid, sid, status)
    conn.execute("update agent_runs set status = 'done' where id = %s", (first,))
    run(conn, uid, aid, sid, "running")


def test_message_and_approval_uniques_and_checks(conn):
    uid, aid, sid = seed(conn)
    rid = run(conn, uid, aid, sid, "done")
    msg = (
        "insert into agent_messages (id, tenant_id, session_id, seq, role, content, client_msg_id)"
        f" values (gen_random_uuid(), '{T}', %s, %s, %s, '{{}}', %s)"
    )
    conn.execute(msg, (sid, 1, "user", "c1"))
    with pytest.raises(pg_errors.UniqueViolation):
        conn.execute(msg, (sid, 1, "user", "c2"))
    with pytest.raises(pg_errors.UniqueViolation):
        conn.execute(msg, (sid, 2, "user", "c1"))
    conn.execute(msg, (sid, 2, "assistant", None))
    conn.execute(msg, (sid, 3, "assistant", None))  # client_msg_id NULL không đụng nhau
    with pytest.raises(pg_errors.CheckViolation):
        conn.execute(msg, (sid, 4, "robot", None))
    with pytest.raises(pg_errors.NotNullViolation):  # thiếu tenant
        conn.execute(msg.replace("tenant_id, ", "").replace(f"'{T}', ", ""), (sid, 5, "user", None))
    with pytest.raises(pg_errors.CheckViolation):
        run(conn, uid, aid, sid, "zombie")
    ins = (
        "insert into agent_approvals (id, tenant_id, run_id, tool_call_id, operation, args, status, expires_at) values"
        f" (gen_random_uuid(), '{T}', %s, 'c1', 'notifications.mark_all_read', '{{}}', %s, now())"
    )
    conn.execute(ins, (rid, "pending"))
    with pytest.raises(pg_errors.UniqueViolation):
        conn.execute(ins, (rid, "pending"))
    with pytest.raises(pg_errors.CheckViolation):
        conn.execute(ins.replace("'c1'", "'c2'"), (rid, "maybe"))


def test_deleting_session_cascades(conn):
    uid, aid, sid = seed(conn)
    rid = run(conn, uid, aid, sid, "done")
    conn.execute(
        "insert into agent_messages (id, tenant_id, session_id, seq, role, content, run_id)"
        " values (gen_random_uuid(), %s, %s, 1, 'user', '{}', %s)",
        (T, sid, rid),
    )
    conn.execute("delete from agent_sessions where id = %s", (sid,))
    assert conn.execute("select count(*) from agent_runs").fetchone()[0] == 0
    assert conn.execute("select count(*) from agent_messages").fetchone()[0] == 0


def test_downgrade_chat_then_upgrade_again(conn, test_settings):
    command.downgrade(alembic_config(test_settings), "0005_agent_chat")
    assert CHAT <= tables(conn)
    command.downgrade(alembic_config(test_settings), "0004_agent_config")
    assert current_revision(test_settings) == "0004_agent_config"
    assert not (CHAT & tables(conn))
    schemas = {r[0] for r in conn.execute("select schema_name from information_schema.schemata")}
    assert "agent_lg" not in schemas
    run_migrations(test_settings)
    assert current_revision(test_settings) == head_revision()
    assert CHAT <= tables(conn)
