"""Quyền `agent.<toolset>`: có trong catalog, role có sẵn nhận đủ, role tự tạo có `agent.chat` được cấp 1 lần."""

import pytest
from sqlalchemy import text
from sqlmodel import select

from app.auth import rbac
from app.auth.models import Permission
from app.core.migrate import run_post_migrate
from tests.auth.factories import agent_toolset_codes, make_role
from tests.auth.test_rbac_sync import role_perms


def test_agent_perms_declared_in_agent_domain():
    declared = rbac.declared_permissions()
    assert sorted(rbac.AGENT_TOOLSET_PERMS) == agent_toolset_codes()
    for code in agent_toolset_codes():
        domain, description = declared[code]
        assert domain == "agent" and description.startswith("Trợ lý:"), code


def test_builtin_roles_have_all_agent_perms():
    for name in ("member", "admin", "viewer"):
        assert set(agent_toolset_codes()) | {"agent.chat"} <= rbac.builtin_roles()[name][1], name


@pytest.mark.integration
async def test_builtin_roles_have_agent_perms_after_sync(pg, test_settings):
    await run_post_migrate(test_settings)
    async with pg.ro() as s:
        for name in ("member", "admin"):
            assert set(agent_toolset_codes()) <= await role_perms(s, name), name
        rows = (await s.exec(select(Permission).where(Permission.codename.in_(agent_toolset_codes())))).all()
        assert {r.codename: r.domain for r in rows} == dict.fromkeys(agent_toolset_codes(), "agent")


async def drop_agent_perms(pg) -> None:
    """Giả lập DB cũ: quyền `agent.<toolset>` chưa từng có trong catalog."""
    async with pg.rw() as s:
        await s.exec(
            text("delete from role_permissions where permission like 'agent.%' and permission <> 'agent.chat'")
        )
        await s.exec(text("delete from permissions where codename like 'agent.%' and codename <> 'agent.chat'"))


@pytest.mark.integration
async def test_sync_grants_custom_role_with_agent_chat_once(pg, test_settings):
    await run_post_migrate(test_settings)
    async with pg.rw() as s:
        await make_role(s, "co_chat", ["agent.chat", "user.view"])
        await make_role(s, "khong_chat", ["user.view"])
    await drop_agent_perms(pg)
    result = (await run_post_migrate(test_settings))["auth.catalog"]
    assert set(agent_toolset_codes()) <= set(result["added"]) and result["agent_perms_granted"] == ["co_chat"]
    async with pg.ro() as s:
        assert await role_perms(s, "co_chat") == {"agent.chat", "user.view", *agent_toolset_codes()}
        assert await role_perms(s, "khong_chat") == {"user.view"}
    async with pg.rw() as s:  # quản trị bỏ bớt quyền → lần sync sau không cấp lại
        await s.exec(
            text(
                "delete from role_permissions using roles"
                " where roles.id = role_id and roles.name = 'co_chat' and permission = 'agent.lookup'"
            )
        )
    again = (await run_post_migrate(test_settings))["auth.catalog"]
    assert again["added"] == [] and again["agent_perms_granted"] == []
    async with pg.ro() as s:
        assert "agent.lookup" not in await role_perms(s, "co_chat")


@pytest.mark.integration
async def test_grant_function_only_acts_on_new_agent_perms(pg, test_settings):
    await run_post_migrate(test_settings)
    async with pg.rw() as s:
        await make_role(s, "chat_only", ["agent.chat"])
        await make_role(s, "no_chat", ["user.view"])
        assert await rbac.grant_new_agent_perms(s, ["user.view", "role.manage"]) == []  # không phải quyền agent
        assert await rbac.grant_new_agent_perms(s, []) == []
    async with pg.ro() as s:
        assert await role_perms(s, "chat_only") == {"agent.chat"}
    async with pg.rw() as s:
        granted = await rbac.grant_new_agent_perms(s, ["agent.lookup", "agent.extra", "agent.chat"])
        assert granted == ["chat_only"]
    async with pg.ro() as s:
        assert await role_perms(s, "chat_only") == {"agent.chat", "agent.lookup"}
        assert await role_perms(s, "no_chat") == {"user.view"}
