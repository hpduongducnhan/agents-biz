"""Miền nạp ở một chỗ: đúng hợp đồng, nạp lại vô hại, thiếu package thì lỗi; nhịp tim đăng ký bằng decorator."""

from dataclasses import replace

import pytest

from app import domains
from app.core.messaging.realtime import all_ws
from app.core.messaging.streams import all_subscribers
from app.core.messaging.tasks import all_tasks
from app.core.operations import registry
from app.core.operations.registry import get_spec
from app.core.settings import Settings

CORE = ("system", "auth", "tenants", "mail", "observability", "notifications", "credentials", "agent")


def test_domains_follow_the_contract():
    """Lõi đứng đầu theo thứ tự cố định; sau đó là module nghiệp vụ (module mẫu `tasks` + module `make new-module`)."""
    assert domains.DOMAINS[: len(CORE)] == CORE
    modules = domains.DOMAINS[len(CORE) :]
    assert "tasks" in modules and len(set(modules)) == len(modules) and not set(modules) & set(CORE)


def test_load_domains_registers_heartbeat_and_is_idempotent():
    domains.load_domains()
    domains.load_domains()
    assert "system.ping" in {t.name for t in all_tasks()}
    assert "system.ping" in {s.event for s in all_subscribers()}
    assert "system.ping" in {w.event for w in all_ws()}


def test_missing_domain_package_fails_loudly(monkeypatch):
    monkeypatch.setattr(domains, "DOMAINS", ("system", "khong_co_mien"))
    with pytest.raises(ModuleNotFoundError):
        domains.load_domains()


def test_heartbeat_interval_follows_settings():
    domains.load_domains()
    spec = next(t for t in all_tasks() if t.name == "system.ping")
    assert spec.interval(Settings(_env_file=None, HEARTBEAT_INTERVAL=15.0)) == 15
    assert spec.interval(Settings(_env_file=None, HEARTBEAT_INTERVAL=0.2)) == 1
    assert spec.retry == 0 and spec.lane == "default"


def test_domain_for_path_maps_namespace_to_package(monkeypatch):
    moved = replace(get_spec("fx.ping"), name="admin.list_users", source="app.auth.ops")
    monkeypatch.setitem(registry._SPECS, moved.name, moved)
    prefix = "/bizwithagents/api"
    assert domains.domain_for_path(f"{prefix}/admin/list_users", prefix) == "auth"
    assert domains.domain_for_path(f"{prefix}/fx/create_note", prefix) == "fx"
    assert domains.domain_for_path(f"{prefix}/system/khac", prefix) == "system"
    assert domains.domain_for_path(f"{prefix}/khong-co/x", prefix) == "core"
    assert domains.domain_for_path("/khac/hoan-toan", prefix) == "core"
