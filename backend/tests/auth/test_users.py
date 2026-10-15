"""Tạo tài khoản: email chuẩn hoá, mặc định hồ sơ, role `user`, trùng email (cả khi song song), hồ sơ me."""

import asyncio

import pytest
from pydantic import BaseModel, ValidationError

from app.auth.rbac import role_names, user_permissions
from app.auth.users import Email, TimeZone, create_user, me_out, user_by_email
from app.core.connections.registry import get_connections
from app.core.errors import AppException
from app.tenants.models import DEFAULT_TENANT_ID
from tests.auth.factories import user_perms


class _Form(BaseModel):
    email: Email
    tz: TimeZone = "UTC"


def test_email_type_trims_and_lowercases():
    assert _Form(email="  Mai.Anh@Example.COM ").email == "mai.anh@example.com"
    assert _Form(email="dev@test.local").email == "dev@test.local"  # tên miền nội bộ vẫn hợp lệ
    for bad in ("no-at-sign", "a b@c.io", "a@b", "x" * 320 + "@a.io"):
        with pytest.raises(ValidationError):
            _Form(email=bad)


def test_timezone_is_checked():
    assert _Form(email="a@b.io", tz="Asia/Tokyo").tz == "Asia/Tokyo"
    with pytest.raises(ValidationError):
        _Form(email="a@b.io", tz="Mars/Base")


@pytest.mark.integration
async def test_create_user_defaults_and_member_role(app_env):
    async with get_connections().postgres.rw() as s:
        u = await create_user(s, app_env, email="  Mai.Anh@Example.COM ", tenant_id=DEFAULT_TENANT_ID)
        assert (u.email, u.name, u.timezone, u.locale) == (
            "mai.anh@example.com",
            "mai.anh",
            "Asia/Ho_Chi_Minh",
            "vi",
        )
        assert u.is_active and not u.is_superadmin and u.password_hash is None and u.email_verified_at is None
        assert u.tenant_id == DEFAULT_TENANT_ID
        assert await role_names(s, u.id) == ["member"]
        assert await user_permissions(s, u.id) == set(user_perms())
    async with get_connections().postgres.rw() as s:
        assert (await user_by_email(s, " MAI.ANH@example.com")).id == u.id
        with pytest.raises(AppException) as err:
            await create_user(s, app_env, email="MAI.ANH@example.com", tenant_id=DEFAULT_TENANT_ID)
    assert (err.value.code, err.value.status_code) == (2101, 409)


@pytest.mark.integration
async def test_superadmin_email_flagged_on_create(app_env):
    async with get_connections().postgres.rw() as s:
        root = await create_user(s, app_env, email=" Root@Test.Local ", name="Gốc", tenant_id=DEFAULT_TENANT_ID)
        me = await me_out(s, root)
    assert root.is_superadmin and me.is_superadmin and me.name == "Gốc"
    assert set(me.permissions) >= {"user.view", "user.manage", "tenant.invite", "agent.chat"}
    assert [r.name for r in me.roles] == ["member"] and me.has_password is False
    assert me.tenant is not None and me.tenant.slug == "default"


@pytest.mark.integration
async def test_concurrent_create_same_email_one_wins(app_env):
    async def attempt(email: str):
        async with get_connections().postgres.rw() as s:
            return await create_user(s, app_env, email=email, tenant_id=DEFAULT_TENANT_ID)

    results = await asyncio.gather(attempt("race@x.io"), attempt(" RACE@x.io"), return_exceptions=True)
    assert sorted(type(r).__name__ for r in results) == ["AppException", "User"]
    assert [r.code for r in results if isinstance(r, AppException)] == [2101]
