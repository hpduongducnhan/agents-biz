"""Bảng auth + RBAC (0002_auth_rbac): đủ bảng, email / tên role không phân biệt hoa thường, role đang gán không xoá
được ở mức DB, model khớp migration, mã lỗi auth cố định và đúng dải."""

import psycopg
import pytest

from app.auth.errors import AUTH_ERRORS
from app.core.errors import error_message
from app.core.migrate import make_revision, run_migrations
from tests.conftest import reset_test_db

AUTH_TABLES = {
    "tenants", "users", "oauth_accounts", "refresh_tokens", "permissions", "roles", "role_permissions", "user_roles",
    "auth_tokens",
}  # fmt: skip


def _dsn(settings) -> str:
    return settings.POSTGRES_RW_URL.replace("postgresql+psycopg://", "postgresql://", 1)


def _user(conn, email: str):
    return conn.execute(
        "insert into users (id, tenant_id, email, name, timezone, locale, is_active, is_superadmin,"
        " must_change_password) values (gen_random_uuid(), '00000000-0000-4000-8000-000000000001', %s, '',"
        " 'Asia/Ho_Chi_Minh', 'vi', true, false, false) returning id",
        (email,),
    ).fetchone()[0]


def _role(conn, name: str):
    return conn.execute(
        "insert into roles (id, name, description, is_builtin) values (gen_random_uuid(), %s, '', false) returning id",
        (name,),
    ).fetchone()[0]


@pytest.fixture
def db(test_settings):
    reset_test_db(test_settings)
    run_migrations(test_settings)
    return test_settings


def test_auth_error_codes_fixed_and_in_range():
    assert set(AUTH_ERRORS) == {*range(2101, 2109), *range(2201, 2207)}
    assert all(2000 <= code <= 2999 for code in AUTH_ERRORS)
    assert error_message(2205) == AUTH_ERRORS[2205]
    assert error_message(2103) == "Account is disabled"


@pytest.mark.integration
def test_migration_creates_auth_tables(db):
    with psycopg.connect(_dsn(db)) as conn:
        tables = {r[0] for r in conn.execute("select tablename from pg_tables where schemaname = 'public'")}
    assert AUTH_TABLES <= tables


@pytest.mark.integration
def test_email_and_role_name_unique_ignoring_case(db):
    with psycopg.connect(_dsn(db), autocommit=True) as conn:
        _user(conn, "a@x.io")
        with pytest.raises(psycopg.errors.UniqueViolation):
            _user(conn, "A@X.IO")
        _role(conn, "Ke toan")
        with pytest.raises(psycopg.errors.UniqueViolation):
            _role(conn, "KE TOAN")


@pytest.mark.integration
def test_role_in_use_is_protected_by_db(db):
    with psycopg.connect(_dsn(db), autocommit=True) as conn:
        uid, rid = _user(conn, "r@x.io"), _role(conn, "Ke toan")
        conn.execute("insert into permissions (codename, domain) values ('user.view', 'auth')")
        conn.execute("insert into role_permissions (role_id, permission) values (%s, 'user.view')", (rid,))
        conn.execute("insert into user_roles (user_id, role_id) values (%s, %s)", (uid, rid))
        with pytest.raises((psycopg.errors.RestrictViolation, psycopg.errors.ForeignKeyViolation)):
            # role đang gán → DB chặn (2205 kể cả khi song song); RESTRICT báo 23001
            conn.execute("delete from roles where id = %s", (rid,))
        conn.execute("delete from users where id = %s", (uid,))  # xoá user kéo theo user_roles
        conn.execute("delete from roles where id = %s", (rid,))
        assert conn.execute("select count(*) from role_permissions").fetchone()[0] == 0  # quyền của role đi theo role


@pytest.mark.integration
def test_models_match_migration(db):
    path = make_revision(db, "kiểm lệch")
    try:
        body = path.read_text(encoding="utf-8")
        upgrade = body.split("def upgrade() -> None:")[1].split("def downgrade")[0]
        assert "op." not in upgrade, upgrade
    finally:
        path.unlink()
