"""Registry toolset: op `agent=True` phải gắn toolset đã đăng ký; op "phải duyệt" là op agent của đúng toolset đó;
module mới khai toolset bằng `register_toolset` là đủ (quyền `agent.<toolset>` tự vào catalog + role có sẵn)."""

import pytest

from app.agent.config import toolsets
from app.agent.config.toolsets import register_toolset
from app.auth import rbac
from app.core.operations.registry import all_specs, get_spec
from app.domains import load_domains


@pytest.fixture
def scratch_registry(monkeypatch):
    """Đăng ký thử trong test không rò sang test khác."""
    monkeypatch.setattr(toolsets, "_TOOLSETS", dict(toolsets._TOOLSETS))
    monkeypatch.setattr(rbac, "_DECLARED", dict(rbac._DECLARED))
    monkeypatch.setattr(rbac, "_ROLE_GRANTS", {k: set(v) for k, v in rbac._ROLE_GRANTS.items()})
    monkeypatch.setattr(rbac, "AGENT_TOOLSET_PERMS", dict(rbac.AGENT_TOOLSET_PERMS))


def test_every_agent_op_has_known_toolset():
    load_domains()
    specs = [s for s in all_specs() if s.agent and s.source.startswith("app.")]
    assert specs, "không có op agent nào"
    bad = {s.name: s.toolset for s in specs if s.toolset not in toolsets.toolsets()}
    assert bad == {}


def test_confirm_writes_are_agent_ops_of_their_toolset():
    load_domains()
    for ts in toolsets.registered():
        for name in ts.confirm_writes:
            spec = get_spec(name)
            assert spec is not None and spec.agent and spec.toolset == ts.name, (ts.name, name)


def test_non_agent_ops_explain_why_for_writes():
    load_domains()
    for s in all_specs():
        if s.source.startswith("app.agent") and s.effect != "read":
            assert not s.agent and (s.agent_reason or "").strip(), s.name


def test_platform_lookup_plus_tasks_module_toolsets():
    assert {"lookup", "tasks"} <= set(toolsets.toolsets())
    assert rbac.AGENT_TOOLSET_PERMS["agent.lookup"] == "Trợ lý: tra cứu chung (thông báo)"
    assert set(rbac.AGENT_TOOLSET_PERMS) == {toolsets.perm_of(n) for n in toolsets.toolsets()}


def test_register_toolset_declares_permission_for_chosen_roles(scratch_registry):
    register_toolset("crm", "Khách hàng: tra cứu, ghi chú", confirm_writes={"crm.delete"}, roles=("admin", "member"))
    register_toolset("crm", "Khách hàng: tra cứu, ghi chú", confirm_writes={"crm.delete"}, roles=("admin", "member"))
    assert toolsets.toolsets()["crm"] == "Khách hàng: tra cứu, ghi chú"
    assert "crm.delete" in toolsets.confirm_writes()
    assert rbac.declared_permissions()["agent.crm"] == ("agent", "Trợ lý: khách hàng (tra cứu, ghi chú)")
    grants = {name: perms for name, (_, perms) in rbac.builtin_roles().items()}
    assert "agent.crm" in grants["admin"] and "agent.crm" in grants["member"] and "agent.crm" not in grants["viewer"]
    assert "agent.crm" in rbac.AGENT_TOOLSET_PERMS  # role tự tạo có agent.chat nhận quyền này lần migrate đầu


def test_register_toolset_rejects_bad_name_and_conflicts(scratch_registry):
    with pytest.raises(ValueError, match="chữ thường"):
        register_toolset("CRM", "x")
    register_toolset("zz_probe", "Thử")
    with pytest.raises(ValueError, match="nội dung khác"):
        register_toolset("zz_probe", "Thử khác")
    with pytest.raises(ValueError, match="không tồn tại"):
        register_toolset("files", "Tệp", roles=("owner",))
    assert "files" not in toolsets.toolsets()
