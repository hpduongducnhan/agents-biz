"""Catalog quyền khai trong code → bảng permissions (deprecate, không xoá); role có sẵn đúng quyền như code;
quyền của user = hợp các role, bỏ quyền deprecated; ai cần thấy thay đổi (audience)."""

import pytest
from sqlalchemy import text
from sqlmodel import select

from app.auth import rbac
from app.auth.models import Permission, Role, RolePermission
from app.core.migrate import run_post_migrate
from tests.auth.factories import grant_role, make_role, make_tenant, make_user, role_perms_in_code, user_perms

# quyền của lõi + module mẫu; module `make new-module` thêm quyền của mình — so với catalog code chứ không liệt kê cứng
CORE = {"user.view", "user.manage", "tenant.settings", "tenant.invite", "agent.chat", "agent.lookup"}
TASKS = {"tasks.view", "tasks.edit", "tasks.delete", "agent.tasks"}


async def role_perms(session, name: str) -> set[str]:
    role = (await session.exec(select(Role).where(Role.name == name))).one()
    rows = await session.exec(select(RolePermission.permission).where(RolePermission.role_id == role.id))
    return set(rows.all())


def test_catalog_declared_in_code():
    declared = rbac.declared_permissions()
    assert CORE | TASKS <= set(declared)
    assert declared["user.view"][0] == "auth"
    assert declared["agent.chat"][0] == "agent"


def test_same_codename_in_another_domain_is_a_config_error():
    with pytest.raises(ValueError, match="đã khai"):
        rbac.declare_permissions("fx", {"user.view": "trùng"})


@pytest.mark.integration
async def test_post_migrate_seeds_catalog_and_builtin_roles_once(pg, test_settings):
    first = await run_post_migrate(test_settings)
    assert set(rbac.declared_permissions()) == set(first["auth.catalog"]["added"])
    async with pg.ro() as s:
        assert await role_perms(s, "admin") == set(rbac.declared_permissions())  # admin có mọi quyền khai
        for role in ("admin", "member", "viewer"):
            assert await role_perms(s, role) == set(role_perms_in_code(role)), role
        assert CORE | TASKS <= await role_perms(s, "admin")
        assert "tasks.view" in await role_perms(s, "viewer") and "tasks.edit" not in await role_perms(s, "viewer")
        roles = {r.name: r.is_builtin for r in (await s.exec(select(Role))).all()}
    assert roles == {"admin": True, "member": True, "viewer": True}  # superadmin là cờ users.is_superadmin
    again = await run_post_migrate(test_settings)
    assert again["auth.catalog"] == {"added": [], "deprecated": [], "roles_changed": [], "agent_perms_granted": []}


@pytest.mark.integration
async def test_builtin_role_grants_are_restored_from_code(pg, test_settings):
    await run_post_migrate(test_settings)
    async with pg.rw() as s:
        await s.exec(
            text("delete from role_permissions using roles where roles.id = role_id and roles.name = 'member'")
        )
        await s.exec(text("insert into role_permissions select id, 'user.manage' from roles where name = 'member'"))
    result = await run_post_migrate(test_settings)
    assert result["auth.catalog"]["roles_changed"] == ["member"]
    async with pg.ro() as s:
        assert await role_perms(s, "member") == set(user_perms())


@pytest.mark.integration
async def test_dropped_permission_is_deprecated_not_deleted(pg, test_settings, monkeypatch):
    monkeypatch.setitem(rbac._DECLARED, "fx.temp", ("fx", "quyền tạm"))
    await run_post_migrate(test_settings)
    async with pg.rw() as s:
        u = await make_user(s, "fx@x.io")
        await grant_role(s, u, await make_role(s, "fx", ["fx.temp", "user.view"]))
        uid = u.id
    monkeypatch.delitem(rbac._DECLARED, "fx.temp")
    result = await run_post_migrate(test_settings)
    assert result["auth.catalog"]["deprecated"] == ["fx.temp"]
    async with pg.ro() as s:
        perm = await s.get(Permission, "fx.temp")
        assert perm is not None and perm.deprecated_at is not None  # không xoá
        assert await rbac.user_permissions(s, uid) == {"user.view", *user_perms()}
        assert "fx.temp" not in await rbac.active_permission_codes(s)
    monkeypatch.setitem(rbac._DECLARED, "fx.temp", ("fx", "quyền tạm"))
    await run_post_migrate(test_settings)  # khai lại → hết deprecated
    async with pg.ro() as s:
        assert (await s.get(Permission, "fx.temp")).deprecated_at is None


@pytest.mark.integration
async def test_audience_holders_and_role_names(pg, test_settings):
    await run_post_migrate(test_settings)
    async with pg.rw() as s:
        admin = await make_user(s, "a@x.io", roles=("member", "admin"))
        viewer = await make_role(s, "auditor", ["user.view"])
        v = await make_user(s, "v@x.io", roles=("member",))
        await grant_role(s, v, viewer)
        await make_user(s, "p@x.io")
        await make_user(s, "off@x.io", roles=("member", "admin"), is_active=False)
        sup = await make_user(s, "root@test.local", is_superadmin=True)
    async with pg.ro() as s:
        assert set(await rbac.audience(s, "user.view")) == {admin.id, v.id, sup.id}
        assert set(await rbac.audience(s, "tenant.invite")) == {admin.id, sup.id}
        assert await rbac.role_holders(s, viewer.id) == [v.id]
        assert await rbac.role_names(s, admin.id) == ["admin", "member"]


def test_role_grants_are_validated_at_declaration():
    with pytest.raises(ValueError, match="không tồn tại"):
        rbac.declare_permissions("fx", {"fx.a": "a"}, roles={"owner": ["fx.a"]})
    with pytest.raises(ValueError, match="chưa khai"):
        rbac.declare_permissions("fx", {"fx.b": "b"}, roles={"member": ["fx.c"]})


@pytest.mark.integration
async def test_audience_can_be_limited_to_one_tenant(pg, test_settings):
    await run_post_migrate(test_settings)
    async with pg.rw() as s:
        acme = await make_tenant(s, "Acme")
        here = await make_user(s, "a@x.io", roles=("admin",))
        await make_user(s, "b@acme.io", roles=("admin",), tenant_id=acme.id)
        sup = await make_user(s, "root@test.local", is_superadmin=True, tenant_id=acme.id)
    async with pg.ro() as s:
        assert set(await rbac.audience(s, "user.view", tenant_id=here.tenant_id)) == {here.id, sup.id}
