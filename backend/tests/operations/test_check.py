"""Kiểm cấu hình operation lúc boot + hàm quyết định quyền dùng chung (runner, danh mục action)."""

import uuid

import pytest

from app.core.operations import registry
from app.core.operations.runner import check_operations, is_allowed
from app.core.operations.spec import operation
from app.core.security.principal import Principal

U1 = uuid.UUID("00000000-0000-4000-8000-000000000001")


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(registry, "_SPECS", {})


def test_check_passes_with_plain_operations():
    @operation("grpdemo.plain", title="Thường")
    async def plain(ctx) -> dict:
        return {}

    check_operations()


def test_is_allowed_matrix():
    @operation("grpdemo.read_x", title="Đọc", permission="grp.read")
    async def read_x(ctx) -> dict:
        return {}

    @operation("grpdemo.admin_x", title="Quản trị", superadmin=True)
    async def admin_x(ctx) -> dict:
        return {}

    @operation("grpdemo.open_x", title="Mở", public=True)
    async def open_x(ctx) -> dict:
        return {}

    read, admin, open_ = (registry.get_spec(f"grpdemo.{n}") for n in ("read_x", "admin_x", "open_x"))
    reader = Principal(user_id=U1, perms=frozenset({"grp.read"}))
    sup = Principal(user_id=U1, sup=True)
    assert is_allowed(read, reader) and not is_allowed(read, Principal(user_id=U1)) and not is_allowed(read, None)
    assert not is_allowed(admin, reader) and is_allowed(admin, sup) and is_allowed(read, sup)
    assert is_allowed(open_, None)
