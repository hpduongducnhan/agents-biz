"""Toolset theo việc: mọi op `agent=True` có toolset thuộc bảng; mỗi toolset có op; mức mặc định theo effect."""

import pytest

from app.agent.config.toolsets import agent_specs, default_policy, ops_of, toolsets
from app.core.operations.registry import all_specs, get_spec
from app.domains import load_domains

EXPECTED = {
    "lookup": {
        "notifications.list",
        "notifications.unread_count",
        "notifications.mark_read",
        "notifications.mark_all_read",
    },
    "tasks": {  # module mẫu
        "tasks.list",
        "tasks.get",
        "tasks.create",
        "tasks.update",
        "tasks.assign",
        "tasks.set_status",
        "tasks.delete",
        "tasks.add_comment",
        "tasks.summary",
        "tasks.people",
    },
}


@pytest.fixture(autouse=True)
def domains():
    load_domains()


def app_specs():
    return [s for s in agent_specs() if s.source.startswith("app.")]  # bỏ op giả của tests/fixtures


def test_toolsets_cover_agent_ops():
    for spec in app_specs():
        assert spec.toolset in toolsets(), f"{spec.name}: toolset {spec.toolset!r} chưa register_toolset"
    for toolset in toolsets():
        assert ops_of(toolset), f"toolset {toolset} rỗng"


def test_platform_ops_exist_and_agent_enabled():
    assert set(EXPECTED) <= set(toolsets())  # + toolset của module khác
    for toolset, names in EXPECTED.items():
        for name in names:
            spec = get_spec(name)
            assert spec is not None and spec.agent is True, name
            assert spec.toolset == toolset, f"{name}: {spec.toolset} != {toolset}"
        assert names <= {s.name for s in ops_of(toolset)}


def test_default_policy_follows_effect():
    assert default_policy(get_spec("notifications.list")) == "auto"
    assert default_policy(get_spec("notifications.mark_all_read")) == "auto"  # nền không khai op nào phải duyệt
    destructive = next(s for s in all_specs() if s.effect == "destructive")
    assert default_policy(destructive) == "confirm"


def test_agent_chat_and_studio_write_ops_are_not_tools():
    for s in all_specs():
        if s.name.split(".")[0] in {"studio", "credentials", "traces", "usage", "agent"} and s.effect != "read":
            assert not s.agent and (s.agent_reason or "").strip(), s.name
