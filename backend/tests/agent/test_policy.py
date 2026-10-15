"""Chính sách tool: mức theo effect, override chỉ được nâng, `deny` gỡ tool khỏi danh sách."""

from types import SimpleNamespace

from app.agent.runtime import tools
from app.core.operations.registry import get_spec
from app.domains import load_domains
from tests.agent.helpers import make_rc, setup


def ov(policy):
    return SimpleNamespace(policy=policy, locked_params={}, default_params={})


def test_policy_from_effect_and_override():
    load_domains()
    mark_all, mark_one, listing = (
        get_spec(n) for n in ("notifications.mark_all_read", "notifications.mark_read", "notifications.list")
    )
    assert tools.policy_of(mark_one, None) == "auto" and tools.policy_of(listing, None) == "auto"
    assert tools.policy_of(mark_one, ov("confirm")) == "confirm" and tools.policy_of(mark_one, ov("deny")) == "deny"
    assert tools.policy_of(mark_one, ov(None)) == "auto"
    assert tools.policy_of(mark_all, None) == "auto"  # nền tảng không khai thao tác nào cần duyệt sẵn


def test_confirm_writes_and_destructive_raise_policy(confirm_write):
    load_domains()
    mark_all, destructive = get_spec("notifications.mark_all_read"), SimpleNamespace(name="x.y", effect="destructive")
    assert tools.policy_of(mark_all, None) == "confirm"
    assert tools.policy_of(mark_all, ov("auto")) == "confirm"  # override không hạ mức
    assert tools.policy_of(mark_all, ov("deny")) == "deny"
    assert tools.policy_of(destructive, None) == "confirm"


async def test_deny_override_removes_tool_and_confirm_keeps_it(api, aenv, fake_llm):
    await setup(api, fake_llm.base_url)
    u = await api.as_user("u@x.io")
    names = {b.name: b for b in tools.bindings(await make_rc(u))}
    assert names["notifications_mark_all_read"].policy == "auto" and names["notifications_mark_read"].policy == "auto"
    rc = await make_rc(
        u, overrides={"notifications.mark_all_read": ov("deny"), "notifications.mark_read": ov("confirm")}
    )
    names = {b.name: b for b in tools.bindings(rc)}
    assert "notifications_mark_all_read" not in names and names["notifications_mark_read"].policy == "confirm"
    assert "notifications_mark_all_read" not in {t.name for t in tools.build_tools(rc)}


async def test_toolsets_filter_tools_and_permissions(api, aenv, fake_llm):
    await setup(api, fake_llm.base_url)
    u = await api.as_user("u@x.io")
    only_lookup = {b.name for b in tools.bindings(await make_rc(u, toolsets={"lookup"}))}
    assert "notifications_list" in only_lookup
    assert tools.bindings(await make_rc(u, toolsets=set())) == []
