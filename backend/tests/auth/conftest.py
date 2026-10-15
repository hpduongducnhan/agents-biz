"""Fixture riêng của test auth: DB test đã Alembic tới head (chưa chạy bước sau migrate)."""

import pytest

import app.auth.ops  # noqa: F401 — nạp miền auth: catalog quyền + bước sau migrate
from app.core.connections.postgres import Postgres
from app.core.migrate import run_migrations
from tests.conftest import reset_test_db


@pytest.fixture
async def pg(test_settings):
    """DB test sạch, đã Alembic tới head; trả Postgres (`.rw()` / `.ro()`) — test tự gọi run_post_migrate."""
    reset_test_db(test_settings)
    run_migrations(test_settings)
    p = Postgres(test_settings)
    yield p
    await p.close()
