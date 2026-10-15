"""Luật quyền trợ lý: mỗi toolset có đúng một quyền `agent.<toolset>` khai trong catalog; ghi rủi ro qua
trợ lý là op có thật và nằm trong toolset ghi."""

from app.agent.config.toolsets import confirm_writes, perm_of, toolsets
from app.auth import rbac
from app.core.operations.registry import get_spec
from app.domains import load_domains


def test_every_toolset_has_a_declared_agent_permission():
    declared = rbac.declared_permissions()
    for key in toolsets():
        assert perm_of(key) == f"agent.{key}" and perm_of(key) in declared, key
        assert declared[perm_of(key)][0] == "agent", key


def test_no_orphan_agent_permission_without_toolset():
    toolset_perms = {perm_of(k) for k in toolsets()}
    assert set(rbac.AGENT_TOOLSET_PERMS) == toolset_perms


def test_builtin_roles_grant_every_toolset_permission():
    for name in ("member", "admin"):
        assert {perm_of(k) for k in toolsets()} <= rbac.builtin_roles()[name][1], name


def test_confirm_writes_are_real_agent_ops():
    load_domains()
    for name in confirm_writes():
        spec = get_spec(name)
        assert spec.agent and spec.effect != "read" and spec.toolset in toolsets(), name
