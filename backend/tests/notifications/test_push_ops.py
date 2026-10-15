"""push.config / push.subscribe / push.unsubscribe + bảng của migration 0003."""

import psycopg
import pytest
from alembic import command

from app.core.migrate import alembic_config, current_revision, run_migrations
from app.credentials import crypto
from tests.conftest import head_revision, reset_test_db
from tests.notifications.push_lib import FCM, add_sub, subs, ua_keys

pytestmark = pytest.mark.integration


@pytest.fixture
def on(app_env, monkeypatch):
    monkeypatch.setattr(app_env, "CREDENTIAL_KEYS", crypto.new_key())
    return app_env


def body(endpoint: str = FCM + "abc", **over) -> dict:
    _, p256dh, auth = ua_keys()
    return {"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}, "user_agent": "UA/1", **over}


async def test_config_disabled_without_credential_keys(app_env, api, monkeypatch):
    monkeypatch.setattr(app_env, "CREDENTIAL_KEYS", "")
    u = await api.as_user("a@x.io")
    assert await api.get("push.config", u) == {"enabled": False, "public_key": None}
    assert await api.err("GET", "push.config") == (401, 1004)


async def test_config_enabled_returns_stable_public_key(on, api):
    u = await api.as_user("a@x.io")
    first = await api.get("push.config", u)
    assert first["enabled"] is True and len(first["public_key"]) == 87
    assert await api.get("push.config", await api.as_user("b@x.io")) == first


async def test_subscribe_stores_row_for_caller(on, api):
    u = await api.as_user("a@x.io")
    got = await api.post("push.subscribe", u, **body())
    [row] = await subs(u.id)
    assert got == {"id": str(row.id)} and row.endpoint == FCM + "abc" and row.user_agent == "UA/1" and row.failures == 0


async def test_subscribe_same_endpoint_again_keeps_one_row(on, api):
    u = await api.as_user("a@x.io")
    first = await api.post("push.subscribe", u, **body())
    again = await api.post("push.subscribe", u, **body())
    assert first == again and len(await subs()) == 1


async def test_subscribe_reassigns_endpoint_to_new_user_and_resets_failures(on, api):
    a, b = await api.as_user("a@x.io"), await api.as_user("b@x.io")
    await add_sub(a.id, endpoint=FCM + "dev", failures=7)
    await api.post("push.subscribe", b, **body(FCM + "dev"))
    assert await subs(a.id) == []
    [row] = await subs(b.id)
    assert row.endpoint == FCM + "dev" and row.failures == 0


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b | {"endpoint": "http://fcm.googleapis.com/x"},
        lambda b: b | {"endpoint": "https://evil.example.com/push/abc"},
        lambda b: b | {"endpoint": "https://fcm.googleapis.com.evil.io/push"},
        lambda b: b | {"keys": b["keys"] | {"auth": "A" * 30}},
        lambda b: b | {"keys": b["keys"] | {"p256dh": "A" * 87}},
        lambda b: b | {"keys": {"p256dh": "short", "auth": "short"}},
        lambda b: {k: v for k, v in b.items() if k != "keys"},
        lambda b: b | {"endpoint": "x"},
    ],
)
async def test_subscribe_rejects_bad_input_with_1002(on, api, mutate):
    u = await api.as_user("a@x.io")
    assert await api.err("POST", "push.subscribe", u, json=mutate(body())) == (422, 1002)
    assert await subs() == []


async def test_subscribe_conflict_when_disabled_and_needs_login(app_env, api, monkeypatch):
    monkeypatch.setattr(app_env, "CREDENTIAL_KEYS", "")
    u = await api.as_user("a@x.io")
    assert await api.err("POST", "push.subscribe", u, json=body()) == (409, 1003)
    assert await api.err("POST", "push.subscribe", json=body()) == (401, 1004)
    assert await subs() == []


async def test_unsubscribe_removes_only_own_rows(on, api):
    a, b = await api.as_user("a@x.io"), await api.as_user("b@x.io")
    await add_sub(a.id, endpoint=FCM + "a")
    await add_sub(b.id, endpoint=FCM + "b")
    assert await api.post("push.unsubscribe", b, endpoint=FCM + "a") == {"removed": 0}
    assert len(await subs()) == 2
    assert await api.post("push.unsubscribe", a, endpoint=FCM + "a") == {"removed": 1}
    assert await api.post("push.unsubscribe", a, endpoint=FCM + "a") == {"removed": 0}  # đã gỡ: lặp lại vẫn ok
    assert [s.endpoint for s in await subs()] == [FCM + "b"]


async def test_unsubscribe_works_even_when_push_disabled(app_env, api, monkeypatch):
    u = await api.as_user("a@x.io")
    await add_sub(u.id, endpoint=FCM + "a")
    monkeypatch.setattr(app_env, "CREDENTIAL_KEYS", "")
    assert await api.post("push.unsubscribe", u, endpoint=FCM + "a") == {"removed": 1}


async def test_logout_all_and_change_password_drop_subscriptions(on, api):
    u = await api.as_user("a@x.io")
    await add_sub(u.id)
    other = await api.as_user("o@x.io")
    await add_sub(other.id)
    await api.post("auth.logout_all", u)
    assert await subs(u.id) == [] and len(await subs(other.id)) == 1
    v = await api.as_user("v@x.io")
    await add_sub(v.id)
    await api.post("auth.change_password", v, current_password="password123", new_password="moi-hon-123")
    assert await subs(v.id) == []


async def test_admin_lock_and_reset_password_drop_subscriptions(on, api):
    root = await api.as_user("root@test.local")
    a, b = await api.as_user("a@x.io"), await api.as_user("b@x.io")
    await add_sub(a.id)
    await add_sub(b.id)
    await api.post("admin.update_user", root, user_id=a.id, is_active=False)
    assert await subs(a.id) == [] and len(await subs(b.id)) == 1
    await api.post("admin.reset_password", root, user_id=b.id, new_password="tamthoi123")
    assert await subs(b.id) == []


def test_migration_push_tables_and_downgrade(test_settings):
    reset_test_db(test_settings)
    run_migrations(test_settings)
    dsn = test_settings.POSTGRES_RW_URL.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(dsn) as conn:
        tables = {r[0] for r in conn.execute("select tablename from pg_tables where schemaname = 'public'")}
        assert {"push_subscriptions", "push_keys"} <= tables
        on_delete = conn.execute(
            "select confdeltype from pg_constraint where conrelid = 'push_subscriptions'::regclass and contype = 'f'"
        ).fetchall()
        assert on_delete == [("c",)]
        uniq = conn.execute("select indexdef from pg_indexes where tablename = 'push_subscriptions'").fetchall()
        assert any("UNIQUE" in r[0] and "endpoint" in r[0] for r in uniq)
    command.downgrade(alembic_config(test_settings), "0002_auth_rbac")
    with psycopg.connect(dsn) as conn:
        tables = {r[0] for r in conn.execute("select tablename from pg_tables where schemaname = 'public'")}
    assert not {"push_subscriptions", "push_keys"} & tables
    run_migrations(test_settings)
    assert current_revision(test_settings) == head_revision()
