"""Bảng cấu hình agent (0008_agent_config): đủ bảng, ràng buộc, model khớp migration, downgrade sạch."""

import psycopg
import pytest
from alembic import command
from psycopg import errors as pg_errors

import app.models  # noqa: F401 — nạp mọi bảng vào metadata
from app.core.migrate import alembic_config, current_revision, make_revision, run_migrations
from tests.conftest import head_revision, plain_dsn, reset_test_db

pytestmark = pytest.mark.integration
TABLES = {
    "credentials", "agent_providers", "agent_models", "agents", "agent_keys", "agent_limits",
    "agent_user_limits", "agent_toolsets", "agent_tool_overrides", "agent_hooks", "agent_system_prompts",
}  # fmt: skip


@pytest.fixture
def conn(test_settings):
    reset_test_db(test_settings)
    run_migrations(test_settings)
    with psycopg.connect(plain_dsn(test_settings), autocommit=True) as c:
        yield c


def tables(conn) -> set[str]:
    return {r[0] for r in conn.execute("select tablename from pg_tables where schemaname = 'public'")}


def agent(conn, slug="a1"):
    return conn.execute(
        "insert into agents (id, slug, name, kind, key_strategy, visible_to, persona_shared, is_active)"
        " values (gen_random_uuid(), %s, 'A',"
        " 'specialist', 'round_robin', 'all', true, true) returning id",
        (slug,),
    ).fetchone()[0]


def credential(conn, name="c1"):
    return conn.execute(
        "insert into credentials (id, name, secret_ciphertext, key_id, masked_hint, weight, status) values"
        " (gen_random_uuid(), %s, 'x', 'k', 'h', 1, 'active') returning id",
        (name,),
    ).fetchone()[0]


def test_config_tables_exist_and_models_match_migration(conn, test_settings):
    assert TABLES <= tables(conn)
    path = make_revision(test_settings, "kiểm lệch agent config")
    try:
        body = path.read_text(encoding="utf-8")
        upgrade = body.split("def upgrade() -> None:")[1].split("def downgrade")[0]
        assert "op." not in upgrade, upgrade
    finally:
        path.unlink()


def test_agent_slug_unique_and_key_pk(conn):
    a = agent(conn)
    with pytest.raises(pg_errors.UniqueViolation):
        agent(conn)
    c = credential(conn)
    conn.execute("insert into agent_keys (agent_id, credential_id, enabled) values (%s, %s, true)", (a, c))
    with pytest.raises(pg_errors.UniqueViolation):
        conn.execute("insert into agent_keys (agent_id, credential_id, enabled) values (%s, %s, true)", (a, c))
    with pytest.raises(pg_errors.RestrictViolation):  # credential đang gắn agent: RESTRICT
        conn.execute("delete from credentials where id = %s", (c,))
    conn.execute("delete from agents where id = %s", (a,))  # xoá agent kéo theo agent_keys
    assert conn.execute("select count(*) from agent_keys").fetchone()[0] == 0


@pytest.mark.parametrize(
    "sql",
    [
        "insert into agent_providers (id, name, kind, status) values (gen_random_uuid(), 'p', 'weird', 'active')",
        "insert into agent_providers (id, name, kind, status) values (gen_random_uuid(), 'p', 'openai', 'x')",
        "insert into credentials (id, name, secret_ciphertext, key_id, masked_hint, weight, status)"
        " values (gen_random_uuid(), 'w', 'x', 'k', 'h', 0, 'active')",
        "insert into agents (id, slug, name, kind, key_strategy, visible_to, persona_shared, is_active)"
        " values (gen_random_uuid(), 's', 'A',"
        " 'boss', 'round_robin', 'all', true, true)",
    ],
)
def test_check_constraints(conn, sql):
    with pytest.raises(pg_errors.CheckViolation):
        conn.execute(sql)


def test_model_unique_per_provider(conn):
    pid = conn.execute(
        "insert into agent_providers (id, name, kind, status) values (gen_random_uuid(), 'p', 'openai', 'active')"
        " returning id"
    ).fetchone()[0]
    ins = (
        "insert into agent_models (id, provider_id, model_id, name, status) values (gen_random_uuid(), %s, 'm', 'M',"
        " 'active')"
    )
    conn.execute(ins, (pid,))
    with pytest.raises(pg_errors.UniqueViolation):
        conn.execute(ins, (pid,))


def test_downgrade_to_notifications_then_upgrade_again(conn, test_settings):
    command.downgrade(alembic_config(test_settings), "0003_notifications_system")
    assert current_revision(test_settings) == "0003_notifications_system"
    assert not TABLES & tables(conn)
    run_migrations(test_settings)
    assert current_revision(test_settings) == head_revision()
    assert TABLES <= tables(conn)
