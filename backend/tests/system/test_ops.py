"""system.* qua REST thật: thông tin công khai (không đăng nhập), cài đặt (superadmin, DEFAULTS_APPLIED), trạng thái."""

import pytest

from app.observability.sinks import capture_issue
from app.observability.store import get_store
from app.system.settings_store import SystemSettings
from tests.observability.fakes import DownMongoDb
from tests.platform_env import eventually, platform_env, rt_listener, superadmin

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
GOOGLE = {
    "GOOGLE_CLIENT_ID": "id.apps.googleusercontent.com",
    "GOOGLE_CLIENT_SECRET": "bi-mat-test",
    "GOOGLE_REDIRECT_URI": "http://t/bizwithagents/api/auth/google/callback",
}


async def test_public_info_without_login(stack):
    assert await stack.api.get("system.public_info") == {
        "name": "BizWithAgents",
        "signup_open": True,
        "signup_mode": "default_tenant",
        "email_verification": "soft",
        "google_enabled": False,
        "version": stack.settings.BUILD_VERSION,
    }


async def test_google_enabled_needs_switch_and_full_client_config(test_settings):
    async with platform_env(test_settings, mongo=False) as env:
        sa = await superadmin(env)
        await env.api.post("system.update_settings", sa, google_enabled=True)
        assert (await env.api.get("system.public_info"))["google_enabled"] is False  # chưa cấu hình client
        assert (await env.api.get("system.get_settings", sa))["google_configured"] is False
    async with platform_env(test_settings, mongo=False, **GOOGLE) as env:
        sa = await superadmin(env)
        assert (await env.api.get("system.public_info"))["google_enabled"] is False  # công tắc chưa bật
        await env.api.post("system.update_settings", sa, google_enabled=True)
        assert (await env.api.get("system.public_info"))["google_enabled"] is True
        assert (await env.api.get("system.get_settings", sa))["google_configured"] is True


async def test_settings_superadmin_only_and_roundtrip(stack):
    api, sa = stack.api, await superadmin(stack)
    user = await api.as_user("u@x.io")
    for method, op, kw in (
        ("GET", "system.get_settings", {}),
        ("POST", "system.update_settings", {"json": {"signup_mode": "invite_only"}}),
        ("GET", "system.status", {}),
    ):
        assert await api.err(method, op, user, **kw) == (403, 1005), op
    assert await api.get("system.get_settings", sa) == {
        **SystemSettings().model_dump(),
        "google_configured": False,
        "defaults_applied": ALL_KEYS,
    }
    async with rt_listener(stack) as rt:
        await rt.bind("sup")
        out = await api.post("system.update_settings", sa, signup_mode="invite_only", event_log_ttl_days=30)
        refresh = await eventually(lambda: rt.data("sup", "data:changed"))
    assert {"keys": ["system"]} in refresh
    assert (out["signup_mode"], out["event_log_ttl_days"]) == ("invite_only", 30)
    assert out["defaults_applied"] == [k for k in ALL_KEYS if k not in ("signup_mode", "event_log_ttl_days")]
    info = await api.get("system.public_info")  # cache đặt lại ngay sau commit
    assert (info["signup_open"], info["signup_mode"]) == (False, "invite_only")
    for bad in ({"event_log_ttl_days": 0}, {"raw_http_ttl_days": 366}, {"signup_mode": "open"}):
        assert await api.err("POST", "system.update_settings", sa, json=bad) == (422, 1002)


async def test_status_snapshot(stack):
    api, sa = stack.api, await superadmin(stack)
    if stack.settings.MONGO_ENABLED:
        await capture_issue(ValueError("x"), source="test", loc="obs0931")
        await eventually(lambda: stack.conns.mongo.rw["issues"].find_one({}))
    out = await api.get("system.status", sa)
    assert out["version"] == stack.settings.BUILD_VERSION and out["mongo_enabled"] is stack.settings.MONGO_ENABLED
    assert set(out["pipeline"]) == {"consume", "work", "schedule"} and isinstance(out["pipeline_ok"], bool)
    assert out["checks"]["postgres.rw"] == "ok" and out["checks"]["rabbitmq"] == "ok" and out["ready"] is True
    assert out["settings_defaults"] == ALL_KEYS
    obs = out["observability"]
    assert obs["enabled"] is stack.settings.MONGO_ENABLED
    assert {"queued", "written", "dropped", "failed", "open_issues", "open_issues_error"} <= set(obs)
    if stack.settings.MONGO_ENABLED:
        assert out["checks"]["mongo.rw"] == "ok" and obs["open_issues"] == 1
    else:
        assert out["checks"]["mongo"] == "disabled" and obs["open_issues"] is None


async def test_status_survives_mongo_read_failure(mongo_stack, monkeypatch):
    sa = await superadmin(mongo_stack)
    monkeypatch.setattr(get_store(), "_ro", DownMongoDb())
    obs = (await mongo_stack.api.get("system.status", sa))["observability"]
    assert obs["open_issues"] is None and obs["open_issues_error"] == "7001"


async def test_chat_stream_settings_validated_and_persisted(stack):
    api, sa = stack.api, await superadmin(stack)
    before = await api.get("system.get_settings", sa)
    assert before["chat_stream"] is True and before["chat_stream_flush_ms"] == 50
    assert {"chat_stream", "chat_stream_flush_ms"} <= set(before["defaults_applied"])
    for bad in (19, 1001, 0):
        assert await api.err("POST", "system.update_settings", sa, json={"chat_stream_flush_ms": bad}) == (422, 1002)
    out = await api.post("system.update_settings", sa, chat_stream=False, chat_stream_flush_ms=1000)
    assert (out["chat_stream"], out["chat_stream_flush_ms"]) == (False, 1000)
    assert not {"chat_stream", "chat_stream_flush_ms"} & set(out["defaults_applied"])
    again = await api.get("system.get_settings", sa)
    assert (again["chat_stream"], again["chat_stream_flush_ms"]) == (False, 1000)
    low = await api.post("system.update_settings", sa, chat_stream_flush_ms=20)
    assert low["chat_stream_flush_ms"] == 20 and low["chat_stream"] is False
