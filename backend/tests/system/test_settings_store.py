"""Cài đặt hệ thống: mặc định có DEFAULTS_APPLIED (R11), chỉ lưu khoá đã cấu hình, validate, cache Redis 60 giây dùng
chung mọi process, ghi sau commit + broadcast xoá cache."""

import pytest
from sqlalchemy import text

from app.core.errors import AppException
from app.system import settings_store as store
from app.system.settings_store import (
    BROADCAST_TOPIC,
    CACHE_KEY,
    CACHE_TTL,
    SettingsSnapshot,
    SystemSettings,
    cached_system_settings,
    on_settings_changed,
    settings_snapshot,
    update_system_settings,
)

pytestmark = pytest.mark.integration
ALL_KEYS = [
    "signup_mode",
    "email_verification",
    "user_limit_default",
    "google_enabled",
    "event_log_ttl_days",
    "span_ttl_days",
    "raw_http_ttl_days",
    "chat_session_idle_min",
    "chat_history_limit",
    "chat_history_tools",
    "chat_stream",
    "chat_stream_flush_ms",
    "chat_per_minute",
    "chat_per_hour",
    "chat_per_day",
    "chat_autoblock",
    "chat_autoblock_strikes",
    "chat_autoblock_window_min",
    "chat_autoblock_minutes",
]


@pytest.fixture(autouse=True)
def fresh_effective_log(monkeypatch):
    monkeypatch.setattr(store, "_last_logged", None)


async def _snap(stack) -> SettingsSnapshot:
    async with stack.conns.postgres.ro() as session:
        return await settings_snapshot(session)


async def _data(stack) -> dict:
    async with stack.conns.postgres.ro() as session:
        (data,) = (await session.exec(text("select data from system_settings where id = 1"))).one()
    return data


async def test_defaults_are_reported_and_cached(plain_stack, bw_log, monkeypatch):
    await plain_stack.conns.redis.rw.delete(CACHE_KEY)  # bước dựng môi trường có thể đã đọc + cache cài đặt
    monkeypatch.setattr(store, "_last_logged", None)
    snap = await _snap(plain_stack)
    assert snap.values == SystemSettings() and snap.defaults_applied == ALL_KEYS
    assert snap.values.model_dump() == {
        "signup_mode": "default_tenant",
        "email_verification": "soft",
        "user_limit_default": 0,
        "google_enabled": False,
        "event_log_ttl_days": 180,
        "span_ttl_days": 90,
        "raw_http_ttl_days": 7,
        "chat_session_idle_min": 30,
        "chat_history_limit": 20,
        "chat_history_tools": True,
        "chat_stream": True,
        "chat_stream_flush_ms": 50,
        "chat_per_minute": 10,
        "chat_per_hour": 100,
        "chat_per_day": 400,
        "chat_autoblock": True,
        "chat_autoblock_strikes": 5,
        "chat_autoblock_window_min": 10,
        "chat_autoblock_minutes": 30,
    }
    [line] = [line for line in bw_log() if line["loc"] == "sys0701"]
    assert "DEFAULTS_APPLIED=[signup_mode, email_verification, user_limit_default, google_enabled" in line["msg"]
    redis = plain_stack.conns.redis.rw
    assert SettingsSnapshot.model_validate_json(await redis.get(CACHE_KEY)) == snap
    assert 0 < await redis.ttl(CACHE_KEY) <= CACHE_TTL
    await redis.delete(CACHE_KEY)
    await _snap(plain_stack)  # đọc DB lần nữa, giá trị không đổi → không log lại
    assert [line["loc"] for line in bw_log()].count("sys0701") == 1


async def test_update_stores_only_configured_keys_and_validates(plain_stack):
    async with plain_stack.conns.postgres.rw() as session:
        out = await update_system_settings(session, {"signup_mode": "invite_only", "event_log_ttl_days": 30, "la": 1})
    assert (out.signup_mode, out.event_log_ttl_days) == ("invite_only", 30)
    assert await _data(plain_stack) == {"signup_mode": "invite_only", "event_log_ttl_days": 30}  # khoá lạ bị bỏ
    async with plain_stack.conns.postgres.rw() as session:
        await update_system_settings(session, {"google_enabled": True})
    assert await _data(plain_stack) == {"signup_mode": "invite_only", "event_log_ttl_days": 30, "google_enabled": True}
    snap = await _snap(plain_stack)
    left = ("signup_mode", "event_log_ttl_days", "google_enabled")
    assert snap.defaults_applied == [k for k in ALL_KEYS if k not in left]
    with pytest.raises(AppException) as err:
        async with plain_stack.conns.postgres.rw() as session:
            await update_system_settings(session, {"event_log_ttl_days": 0})
    assert err.value.code == 1002 and err.value.status_code == 422
    assert (await _snap(plain_stack)).values.event_log_ttl_days == 30


async def test_update_is_visible_across_processes_and_broadcast_clears_stale_fill(plain_stack):
    """Process B đã cache giá trị cũ; process A lưu → B đọc thấy ngay. Một process chậm ghi lại giá trị cũ vào cache
    sau commit → broadcast `system.settings_changed` (tới mọi process) xoá đi."""
    old = await _snap(plain_stack)  # B: cache đang giữ giá trị cũ
    async with plain_stack.conns.postgres.rw() as session:  # A
        await update_system_settings(session, {"signup_mode": "invite_only"})
    assert (await _snap(plain_stack)).values.signup_mode == "invite_only"  # không phải chờ hết 60 giây
    await plain_stack.conns.redis.rw.set(CACHE_KEY, old.model_dump_json(), ex=CACHE_TTL)  # process chậm ghi đè
    await on_settings_changed({})  # broadcast tới process đó
    assert (await _snap(plain_stack)).values.signup_mode == "invite_only"
    assert (await cached_system_settings()).signup_mode == "invite_only"


async def test_cache_and_broadcast_only_after_commit(plain_stack, monkeypatch):
    sent: list[str] = []

    async def fake_broadcast(topic: str, data: dict | None = None) -> None:
        sent.append(topic)

    monkeypatch.setattr(store, "broadcast", fake_broadcast)
    with pytest.raises(RuntimeError):
        async with plain_stack.conns.postgres.rw() as session:
            await update_system_settings(session, {"signup_mode": "invite_only"})
            raise RuntimeError("rollback")
    assert sent == [] and (await _snap(plain_stack)).values.signup_mode == "default_tenant"
    async with plain_stack.conns.postgres.rw() as session:
        await update_system_settings(session, {"signup_mode": "invite_only"})
    assert sent == [BROADCAST_TOPIC] and (await _snap(plain_stack)).values.signup_mode == "invite_only"


async def test_redis_down_falls_back_to_db(plain_stack, monkeypatch, bw_log):
    async def down(*args, **kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr(plain_stack.conns.redis.rw, "get", down)
    monkeypatch.setattr(plain_stack.conns.redis.rw, "set", down)
    assert (await _snap(plain_stack)).values == SystemSettings()
    locs = [line["loc"] for line in bw_log()]
    assert "sys0703" in locs and "sys0704" in locs


async def test_bad_stored_value_defaults_only_that_key_and_can_be_fixed(plain_stack, bw_log):
    async with plain_stack.conns.postgres.rw() as session:
        stored = """'{"event_log_ttl_days": 0, "signup_mode": "invite_only"}'"""
        await session.exec(text(f"update system_settings set data = {stored}"))
    snap = await _snap(plain_stack)
    assert snap.values.signup_mode == "invite_only" and snap.values.event_log_ttl_days == 180
    assert "event_log_ttl_days" in snap.defaults_applied and "sys0702" in [line["loc"] for line in bw_log()]
    async with plain_stack.conns.postgres.rw() as session:
        await update_system_settings(session, {"google_enabled": True})  # khoá hỏng không chặn việc lưu
    assert await _data(plain_stack) == {"signup_mode": "invite_only", "google_enabled": True}


async def test_fresh_read_skips_cache_and_corrupt_cache_is_replaced(plain_stack, bw_log):
    await plain_stack.conns.redis.rw.set(CACHE_KEY, "không phải json", ex=CACHE_TTL)
    assert (await _snap(plain_stack)).values == SystemSettings()
    assert "sys0705" in [line["loc"] for line in bw_log()]
    cached = await plain_stack.conns.redis.rw.get(CACHE_KEY)
    assert SettingsSnapshot.model_validate_json(cached).values == SystemSettings()
    async with plain_stack.conns.postgres.rw() as session:
        await update_system_settings(session, {"signup_mode": "invite_only"})
        assert (
            await settings_snapshot(session, fresh=True)
        ).values.signup_mode == "invite_only"  # thấy bản chưa commit
