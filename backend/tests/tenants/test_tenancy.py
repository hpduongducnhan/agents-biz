"""Lõi tách dữ liệu (D11): session đã scope chỉ thấy / sửa / xoá dữ liệu tenant mình, đối tượng mới tự gắn tenant,
ghi đối tượng tenant khác → 1005; session chưa scope thấy hết; `ctx.cross_tenant()` chỉ cho superadmin."""

import uuid

import pytest
from sqlalchemy import delete, update
from sqlmodel import select

from app.auth.models import User
from app.core.connections.registry import get_connections
from app.core.errors import AppException
from app.core.operations.context import OpContext
from app.core.security.principal import Principal
from app.core.tenancy import ALL_TENANTS, scope_session, scoped_models, session_tenant, tenant_session
from app.tenants.models import DEFAULT_TENANT_ID
from tests.auth.factories import make_tenant, make_user

pytestmark = pytest.mark.integration


@pytest.fixture
async def two_tenants(app_env):
    async with get_connections().postgres.rw() as s:
        acme = await make_tenant(s, "Acme")
        a = await make_user(s, "a@default.io")
        b = await make_user(s, "b@acme.io", tenant_id=acme.id)
    return acme.id, a.id, b.id


def test_user_is_a_scoped_model():
    assert User in scoped_models()


async def test_scoped_session_sees_only_its_tenant(two_tenants):
    acme, a, b = two_tenants
    async with get_connections().postgres.ro() as s:
        scope_session(s, DEFAULT_TENANT_ID)
        assert session_tenant(s) == DEFAULT_TENANT_ID
        emails = set((await s.exec(select(User.email))).all())
        assert "a@default.io" in emails and "b@acme.io" not in emails
        assert await s.get(User, b) is None and (await s.get(User, a)) is not None
        unfiltered = (await s.exec(select(User.email).execution_options(**{ALL_TENANTS: True}))).all()
        assert "b@acme.io" in unfiltered
    async with get_connections().postgres.ro() as s:  # chưa scope → thấy mọi tenant
        assert {"a@default.io", "b@acme.io"} <= set((await s.exec(select(User.email))).all())


async def test_update_and_delete_never_cross_tenant(two_tenants):
    acme, a, b = two_tenants
    async with tenant_session(DEFAULT_TENANT_ID) as s:
        await s.exec(update(User).where(User.id == b).values(name="hacked"))
        await s.exec(delete(User).where(User.id == b))
    async with get_connections().postgres.ro() as s:
        other = await s.get(User, b)
    assert other is not None and other.name != "hacked"


async def test_new_rows_are_stamped_and_foreign_rows_rejected(two_tenants):
    acme, a, b = two_tenants
    async with tenant_session(acme) as s:
        u = User(email="new@acme.io", name="N", timezone="UTC")
        s.add(u)
        await s.flush()
        assert u.tenant_id == acme
    with pytest.raises(AppException) as exc:
        async with tenant_session(acme) as s:
            s.add(User(email="x@default.io", name="X", timezone="UTC", tenant_id=DEFAULT_TENANT_ID))
            await s.flush()
    assert exc.value.code == 1005


def _ctx(session, settings, principal: Principal) -> OpContext:
    conns = get_connections()
    return OpContext(principal, settings, session, conns.redis, None, "cid", "web")


async def test_cross_tenant_only_for_superadmin(two_tenants, app_env, bw_log):
    acme, a, b = two_tenants
    async with get_connections().postgres.ro() as s:
        scope_session(s, DEFAULT_TENANT_ID)
        member = _ctx(s, app_env, Principal(user_id=a, tenant_id=DEFAULT_TENANT_ID))
        assert member.tenant_id == DEFAULT_TENANT_ID
        with pytest.raises(AppException) as exc, member.cross_tenant():
            pass
        assert exc.value.code == 1005
        sup = _ctx(s, app_env, Principal(user_id=uuid.uuid4(), sup=True, tenant_id=DEFAULT_TENANT_ID))
        with sup.cross_tenant() as raw:
            assert await raw.get(User, b) is not None
        assert session_tenant(s) == DEFAULT_TENANT_ID  # khôi phục scope sau khối
    assert any(line.get("loc") == "sys0601" for line in bw_log())
