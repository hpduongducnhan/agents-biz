"""Trợ lý theo tenant (D22): phiên / tin / lượt / duyệt mang tenant của người chat; tenant khác không đọc / quyết được
(404); tổ chức tắt trợ lý → `agent.send` / duyệt 6023, danh sách agent rỗng, `auth.me` báo; superadmin không bị chặn;
đổi chính sách → `data:changed` tới phòng tenant."""

import uuid

import pytest

from app.agent.chat.models import AgentSession
from app.core.connections.registry import get_connections
from app.tenants.models import DEFAULT_TENANT_ID, Tenant
from tests.agent.helpers import add_approval, chat, get_root, messages, run_row, send, setup
from tests.auth.api import data_of
from tests.auth.factories import make_tenant, make_user
from tests.conftest import until

pytestmark = pytest.mark.integration


@pytest.fixture
async def env(api, aenv, kicks, fake_llm):
    stack = await setup(api, fake_llm.base_url)
    async with get_connections().postgres.rw() as s:
        acme = await make_tenant(s, "Acme")
        await make_user(s, "far@acme.io", tenant_id=acme.id, roles=("member",))
    far = await api.login("far@acme.io")
    near = await api.as_user("near@x.io")
    return api, near, far, acme, stack


async def set_agent(api, tenant_id, enabled: bool | None) -> None:
    root = await get_root(api)
    await api.post("tenants.update", root, tenant_id=str(tenant_id), policies={"agent_enabled": enabled})


async def test_send_stamps_tenant_on_session_run_and_messages(env):
    api, near, far, acme, _ = env
    mine = await send(api, near, "xin chào")
    theirs = await send(api, far, "hello")
    assert (await run_row(mine["run_id"])).tenant_id == DEFAULT_TENANT_ID
    assert (await run_row(theirs["run_id"])).tenant_id == acme.id
    assert {m.tenant_id for m in await messages(theirs["session_id"])} == {acme.id}
    async with get_connections().postgres.ro() as s:
        row = await s.get(AgentSession, uuid.UUID(theirs["session_id"]))
    assert row.tenant_id == acme.id
    approval = await add_approval(theirs["run_id"])
    assert approval.tenant_id == acme.id


async def test_other_tenant_cannot_read_or_decide(env):
    api, near, far, _, _ = env
    theirs = await send(api, far, "bí mật")
    approval = await add_approval(theirs["run_id"])
    sid = theirs["session_id"]
    assert await api.err("GET", "agent.get_session", near, params={"session_id": sid}) == (404, 6004)
    assert await api.err("GET", "agent.run_events", near, params={"run_id": theirs["run_id"]}) == (404, 6006)
    body = {"approval_id": str(approval.id), "approve": True}
    assert await api.err("POST", "agent.decide_approval", near, json=body) == (404, 6008)
    listed = await api.get("agent.list_sessions", near)
    assert sid not in {s["id"] for s in listed["items"]}


async def test_tenant_with_agent_off(env, rt):
    api, near, far, acme, _ = env
    assert (await api.refresh(far)).user["tenant"]["agent_enabled"] is True
    before = len(data_of(rt, f"tenant.{acme.id}", "data:changed"))
    await set_agent(api, acme.id, False)
    assert await until(lambda: len(data_of(rt, f"tenant.{acme.id}", "data:changed")) > before)
    keys = data_of(rt, f"tenant.{acme.id}", "data:changed")[-1]["keys"]
    assert {"auth.me", "agent.agents", "agent.chat_limits"} <= set(keys)
    assert (await api.get("auth.me", far))["tenant"]["agent_enabled"] is False
    assert await api.get("agent.list_agents", far) == []
    body = {"content": "hi", "client_msg_id": "c1"}
    assert await api.err("POST", "agent.send", far, json=body) == (403, 6023)
    assert await api.get("agent.list_agents", near)  # tổ chức khác không bị ảnh hưởng
    await send(api, near, "vẫn chat được")
    await set_agent(api, acme.id, None)
    assert (await api.get("auth.me", far))["tenant"]["agent_enabled"] is True
    await send(api, far, "bật lại")


async def test_pending_approval_cannot_be_decided_after_agent_off(env):
    api, _, far, acme, _ = env
    theirs = await send(api, far, "xoá giúp")
    approval = await add_approval(theirs["run_id"])
    await set_agent(api, acme.id, False)
    body = {"approval_id": str(approval.id), "approve": True}
    assert await api.err("POST", "agent.decide_approval", far, json=body) == (403, 6023)
    many = {"run_id": theirs["run_id"], "approval_ids": [str(approval.id)], "approve": True}
    assert await api.err("POST", "agent.decide_approvals", far, json=many) == (403, 6023)


async def test_superadmin_is_not_blocked_by_tenant_policy(env):
    api, *_ = env
    root = await get_root(api)
    await set_agent(api, DEFAULT_TENANT_ID, False)
    async with get_connections().postgres.ro() as s:
        assert (await s.get(Tenant, DEFAULT_TENANT_ID)).policies == {"agent_enabled": False}
    assert await api.get("agent.list_agents", root)
    await send(api, root, "superadmin vẫn chat")


async def test_trace_spans_and_llm_calls_carry_tenant(env, trace_sink):
    api, _, far, acme, _ = env
    sent, run = await chat(api, far, "call:notifications_list {}")
    assert run.status == "done"
    spans = [d for d in trace_sink.spans.values() if d["run_id"] == sent["run_id"]]
    assert spans and {d["tenant_id"] for d in spans} == {str(acme.id)}
    calls = [d for d in trace_sink.calls if d["run_id"] == sent["run_id"]]
    assert calls and {d["tenant_id"] for d in calls} == {str(acme.id)}
