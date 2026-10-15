"""Công tắc auth hiệu lực (một chỗ — R12): chế độ đăng ký, xác thực email, Google cần đủ env + công tắc; log `auth0008`
khi giá trị đổi (R11)."""

import pytest

from app.auth import flags
from app.core.settings import Settings
from app.system import settings_store
from tests.auth.api import system_flags

FULL = {"GOOGLE_CLIENT_ID": "cid", "GOOGLE_CLIENT_SECRET": "secret", "GOOGLE_REDIRECT_URI": "http://cb"}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(flags, "_last", None)


async def test_google_needs_env_and_switch(monkeypatch):
    monkeypatch.setattr(settings_store, "get_system_settings", system_flags(google_enabled=True))
    on = await flags.auth_flags(None, Settings(_env_file=None, **FULL))
    assert (on.signup_open, on.google, on.google_missing) == (True, True, ())
    off = await flags.auth_flags(None, Settings(_env_file=None, **(FULL | {"GOOGLE_CLIENT_ID": ""})))
    assert (off.google, off.google_missing) == (False, ("GOOGLE_CLIENT_ID",))
    monkeypatch.setattr(
        settings_store, "get_system_settings", system_flags(google_enabled=False, signup_mode="invite_only")
    )
    closed = await flags.auth_flags(None, Settings(_env_file=None, **FULL))
    assert (closed.signup_open, closed.signup_mode, closed.google) == (False, "invite_only", False)


async def test_effective_values_logged_once_per_change(monkeypatch, bw_log):
    monkeypatch.setattr(settings_store, "get_system_settings", system_flags())
    s = Settings(_env_file=None, GOOGLE_CLIENT_ID="", GOOGLE_CLIENT_SECRET="", GOOGLE_REDIRECT_URI="")
    await flags.auth_flags(None, s)
    await flags.auth_flags(None, s)
    lines = [line for line in bw_log() if line.get("loc") == "auth0008"]
    assert len(lines) == 1
    assert "DEFAULTS_APPLIED=['GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'GOOGLE_REDIRECT_URI']" in lines[0]["msg"]
    monkeypatch.setattr(settings_store, "get_system_settings", system_flags(signup_mode="new_tenant"))
    await flags.auth_flags(None, s)
    assert len([line for line in bw_log() if line.get("loc") == "auth0008"]) == 2
