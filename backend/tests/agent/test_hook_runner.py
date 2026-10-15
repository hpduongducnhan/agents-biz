"""Hook vòng đời trong lượt chạy thật (LLM giả): before_run / before_tool / after_tool / after_run."""

import json
import uuid

import pytest
from sqlalchemy import update

from app.agent.config import registry
from app.agent.config.models import AgentHook
from app.agent.hooks import webhook
from app.agent.runtime import runner
from app.agent.testing import fake_llm as fl
from app.core.connections.registry import get_connections
from tests.agent.helpers import (
    add_notes,
    approvals,
    chat,
    events_of,
    get_root,
    messages,
    notes,
    run_row,
    setup,
    unread,
)


@pytest.fixture
async def env(api, aenv, rt, kicks, fake_llm, memory_sinks):
    stack = await setup(api, fake_llm.base_url)
    u = await api.as_user("u@x.io")
    await add_notes(u.id, 3)
    return stack, u, rt


async def add_hook(stack, point, action, conditions=(), **kw):
    return await stack.api.post(
        "studio.save_hook",
        stack.root,
        agent_id=stack.agent_id,
        point=point,
        action=action,
        conditions=list(conditions),
        **kw,
    )


def look(limit):
    return f"call:notifications_list {json.dumps({'limit': limit})}"


MARK = "call:notifications_mark_all_read {}"


async def test_before_tool_amount_gt_requires_approval(env):
    stack, u, _ = env
    await add_hook(
        stack,
        "before_tool",
        {"action": "require_approval"},
        [
            {"path": "args.limit", "op": "gt", "value": 20},
            {"path": "tool.operation", "op": "eq", "value": "notifications.list"},
        ],
    )
    small, run = await chat(stack.api, u, look(5))
    assert run.status == "done"
    big, run = await chat(stack.api, u, look(50))
    assert run.status == "waiting_approval"
    (req,) = await approvals(big["run_id"])
    assert req.operation == "notifications.list" and req.args["limit"] == 50
    await stack.api.post("agent.decide_approval", u, approval_id=str(req.id), approve=True)
    await runner.resume(big["run_id"])
    assert (await run_row(big["run_id"])).status == "done" and small


async def test_before_tool_block_gives_llm_the_message_and_skips_the_tool(env):
    stack, u, _ = env
    await add_hook(
        stack,
        "before_tool",
        {"action": "block", "message": "Chặn thao tác {{tool.operation}}"},
        [{"path": "tool.operation", "op": "eq", "value": "notifications.mark_all_read"}],
    )
    sent, run = await chat(stack.api, u, MARK)
    assert run.status == "done" and await unread(stack.api, u) == 3
    tool = [m for m in await messages(sent["session_id"]) if m.role == "tool"][0]
    assert tool.content["status"] == "error" and tool.content["text"] == "Chặn thao tác notifications.mark_all_read"


async def test_before_run_block_stops_run_without_llm_call(env):
    stack, u, rt = env
    await add_hook(
        stack,
        "before_run",
        {"action": "block", "message": "Hệ thống đang bảo trì"},
        [{"path": "message.text", "op": "contains", "value": "chi"}],
    )
    sent, run = await chat(stack.api, u, "chi 50k")
    assert (run.status, run.error_code) == ("failed", 6019) and "bảo trì" in run.error
    assert fl.REQUESTS == [] and [m.role for m in await messages(sent["session_id"])] == ["user"]
    assert events_of(rt, u.id, "agent:error")[0][1]["code"] == 6019
    ok, run2 = await chat(stack.api, u, "xin chào")  # điều kiện không khớp → chạy bình thường
    assert run2.status == "done" and len(fl.REQUESTS) == 1 and ok


async def test_add_context_appends_to_context_block(env):
    stack, u, _ = env
    await add_hook(stack, "before_run", {"action": "add_context", "text": "{{user.name}} là khách VIP, luôn lịch sự."})
    await chat(stack.api, u, "chào")
    sent_user = fl.REQUESTS[0]["body"]["messages"][-1]["content"]
    block = sent_user.split("</context>")[0]
    assert block.rstrip().endswith("u là khách VIP, luôn lịch sự.")
    assert sent_user.endswith("chào")


async def test_after_run_notify_webhook_and_after_tool_hooks(env, monkeypatch):
    stack, u, _ = env
    queued = []

    async def kiq(*args):
        queued.append(args)

    monkeypatch.setattr(webhook.send_webhook, "kiq", kiq)
    await add_hook(
        stack, "after_run", {"action": "notify", "to": "user", "text": "Lượt {{run.status}} dùng {{run.tools.0}}"}
    )
    await add_hook(stack, "after_run", {"action": "webhook", "url": "https://hook.test/done"}, position=1)
    await add_hook(
        stack,
        "after_tool",
        {
            "action": "notify",
            "to": "superadmins",
            "text": "Tool {{tool.name}} ok={{result.ok}} lỗi={{result.error_code}}",
        },
    )
    sent, run = await chat(stack.api, u, look(10))
    assert run.status == "done"
    (mine,) = await notes(u.id, "agent_hook")
    assert mine.title == "Lượt done dùng notifications_list"
    (call,) = queued
    assert (
        call[1] == "https://hook.test/done"
        and call[2]["point"] == "after_run"
        and call[2]["data"]["run"]["status"] == "done"
    )
    assert call[2]["data"]["run"]["tools"] == ["notifications_list"] and call[4] == sent["run_id"]
    root = await get_root(stack.api)
    (sup,) = await notes(root.id, "agent_hook")
    assert sup.title == "Tool notifications_list ok=true lỗi="


async def test_failed_run_still_triggers_after_run_hook(env):
    stack, u, _ = env
    await add_hook(stack, "after_run", {"action": "notify", "to": "user", "text": "Kết thúc {{run.status}}"})
    sent, run = await chat(stack.api, u, "fail500")
    assert run.status == "failed"
    assert [n.title for n in await notes(u.id, "agent_hook")] == ["Kết thúc failed"]


async def test_broken_hook_config_never_breaks_the_run(env):
    stack, u, _ = env
    hook = await add_hook(stack, "before_run", {"action": "add_context", "text": "x"})
    async with get_connections().postgres.rw() as s:
        await s.exec(
            update(AgentHook).where(AgentHook.id == uuid.UUID(hook["id"])).values(action_config={"action": "explode"})
        )
    await registry.bump(get_connections().redis)
    sent, run = await chat(stack.api, u, "vẫn chạy")
    assert run.status == "done"


async def test_hook_spans_recorded_when_tracing(env, trace_sink):
    stack, u, _ = env
    await add_hook(stack, "before_run", {"action": "add_context", "text": "ngữ cảnh thêm"}, name="ctx")
    sent, _ = await chat(stack.api, u, "chào")
    hooks = [s for s in trace_sink.spans.values() if s["kind"] == "hook"]
    assert len(hooks) == 1 and hooks[0]["name"] == "ctx" and hooks[0]["input"]["point"] == "before_run"
    assert (
        hooks[0]["output"]["text"] == "ngữ cảnh thêm"
        and hooks[0]["status"] == "ok"
        and hooks[0]["parent_id"] == sent["run_id"]
    )
