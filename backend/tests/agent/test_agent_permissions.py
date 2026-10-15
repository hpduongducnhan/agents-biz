"""Quyền của user khi chat với trợ lý: lọc tool theo `agent.<toolset>`, duyệt ghi rủi ro,
`tools_hidden` ở trace, user thường / superadmin chỉ chạm dữ liệu của mình."""

import json
from dataclasses import replace

import pytest

from app.agent.config import toolsets
from app.agent.runtime import tools
from app.core.connections.registry import get_connections
from app.core.operations.registry import get_spec
from app.domains import load_domains
from tests.agent.helpers import add_notes, approvals, chat, get_root, make_rc, messages, run_row, setup, unread
from tests.auth.factories import make_role

LOOKUP_TOOLS = {
    "notifications_list",
    "notifications_mark_all_read",
    "notifications_mark_read",
    "notifications_unread_count",
}


class _Ov:
    def __init__(self, policy):
        self.policy, self.locked_params, self.default_params = policy, {}, {}


@pytest.fixture
async def env(api, aenv, rt, kicks, fake_llm):
    stack = await setup(api, fake_llm.base_url)
    return api, stack


def names_of(rc) -> set[str]:
    return {b.name for b in tools.bindings(rc)}


def test_no_confirm_writes_by_default_and_override_cannot_lower(monkeypatch):
    load_domains()
    assert toolsets.confirm_writes() == frozenset()
    spec = get_spec("notifications.mark_all_read")
    assert toolsets.default_policy(spec) == "auto" and tools.policy_of(spec, _Ov("deny")) == "deny"
    lookup = replace(toolsets._TOOLSETS["lookup"], confirm_writes=frozenset({spec.name}))
    monkeypatch.setitem(toolsets._TOOLSETS, "lookup", lookup)
    assert toolsets.default_policy(spec) == "confirm" and tools.policy_of(spec, None) == "confirm"
    assert tools.policy_of(spec, _Ov("auto")) == "confirm" and tools.policy_of(spec, _Ov("deny")) == "deny"
    assert toolsets.default_policy(get_spec("notifications.list")) == "auto"


def test_toolset_permission_and_op_listing():
    load_domains()
    assert toolsets.perm_of("lookup") == "agent.lookup"
    assert {tools.tool_name(op.name) for op in toolsets.ops_of("lookup")} >= LOOKUP_TOOLS
    assert [s.name for s in toolsets.agent_specs()] == sorted(s.name for s in toolsets.agent_specs())


async def test_full_user_gets_every_lookup_tool_and_nothing_hidden(env):
    api, _ = env
    u = await api.as_user("full@x.io", roles=("admin",))  # admin có mọi quyền module (vd tasks.delete)
    rc = await make_rc(u)
    assert LOOKUP_TOOLS <= names_of(rc) and tools.hidden_tools(rc) == {}


async def test_chat_only_role_loses_lookup_tools(env):
    api, _ = env
    async with get_connections().postgres.rw() as s:
        await make_role(s, "chat_only", ["agent.chat"])
    u = await api.as_user("chat@x.io", roles=("chat_only",))
    rc = await make_rc(u)
    assert not (LOOKUP_TOOLS & names_of(rc))
    hidden = tools.hidden_tools(rc)
    assert set(hidden) >= LOOKUP_TOOLS and {hidden[t] for t in LOOKUP_TOOLS} == {"thiếu quyền agent.lookup"}


async def test_lookup_role_gets_lookup_tools(env):
    api, _ = env
    async with get_connections().postgres.rw() as s:
        await make_role(s, "lookup_only", ["agent.chat", "agent.lookup"])
    u = await api.as_user("look@x.io", roles=("lookup_only",))
    rc = await make_rc(u)
    assert LOOKUP_TOOLS <= names_of(rc) and not set(tools.hidden_tools(rc)) & LOOKUP_TOOLS


async def test_confirm_write_waits_for_approval(env, confirm_write):
    api, _ = env
    u = await api.as_user("arch@x.io")
    await add_notes(u.id, 2)
    sent, run = await chat(api, u, "đọc hết call:notifications_mark_all_read {}")
    assert run.status == "waiting_approval"
    (req,) = await approvals(sent["run_id"])
    assert req.operation == "notifications.mark_all_read" and req.status == "pending"
    assert await unread(api, u) == 2  # chưa chạy


async def test_agent_only_sees_own_notifications_even_for_superadmin(env):
    api, _ = env
    other = await api.as_user("victim@x.io")
    await add_notes(other.id, 2)
    root = await get_root(api)
    await add_notes(root.id, 1)
    sent, run = await chat(api, root, "xem call:notifications_list {}")
    assert run.status == "done"
    (tool,) = [m for m in await messages(sent["session_id"]) if m.role == "tool"]
    assert json.loads(tool.content["text"])["total"] == 1
    sent, _ = await chat(api, root, "đọc hết call:notifications_mark_all_read {}")
    assert await unread(api, other) == 2  # trợ lý của superadmin không chạm dữ liệu người khác


async def test_run_span_input_lists_tools_and_hidden_is_empty_without_tools(env, trace_sink):
    api, _ = env
    async with get_connections().postgres.rw() as s:
        await make_role(s, "chat_only", ["agent.chat"])
    full = await api.as_user("trace@x.io", roles=("admin",))
    limited = await api.as_user("limited@x.io", roles=("chat_only",))
    spans = {}
    for who in (full, limited):
        sent, _ = await chat(api, who, "chào")
        (span,) = [s for s in trace_sink.spans.values() if s["kind"] == "run" and s["run_id"] == sent["run_id"]]
        spans[who.email] = span["input"]
        assert (await run_row(sent["run_id"])).status == "done"
    assert LOOKUP_TOOLS <= {t["name"] for t in spans[full.email]["tools"]} and spans[full.email]["tools_hidden"] == {}
    assert spans[limited.email]["tools"] == [] and spans[limited.email]["tools_hidden"] == {}  # không tool → không ghi
