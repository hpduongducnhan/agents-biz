"""Runner: lượt chữ, lượt có tool, huỷ, lỗi provider / hết giờ / quá bước / bị ngắt, chạy tối đa một lần."""

import asyncio
import json
import uuid

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.errors import GraphRecursionError
from sqlalchemy import update

from app.agent.config import registry
from app.agent.config.models import Agent
from app.agent.runtime import checkpoint, runner
from app.agent.testing import fake_llm as fl
from app.auth.models import User
from app.core.connections.registry import get_connections
from app.core.errors import AppException
from tests.agent.helpers import add_notes, chat, events_of, messages, run_row, send, setup, unread
from tests.conftest import until


@pytest.fixture
async def env(api, aenv, rt, fake_llm):
    stack = await setup(api, fake_llm.base_url)
    u = await api.as_user("u@x.io")
    return api, u, rt, stack


async def patch_agent(stack, **values):
    async with get_connections().postgres.rw() as s:
        await s.exec(update(Agent).where(Agent.id == uuid.UUID(stack.agent_id)).values(**values))
    await registry.bump(get_connections().redis)


async def test_text_turn_streams_tokens_and_saves_assistant_message(env):
    api, u, rt, stack = env
    sent, run = await chat(api, u, "xin chào bạn")
    assert run.status == "done" and run.error_code is None and run.heartbeat_at and run.started_at and run.ended_at
    assert run.tokens_in > 0 and run.tokens_out > 0 and run.credential_ids == [stack.cred_id]
    user_msg, answer = await messages(sent["session_id"])
    assert (user_msg.role, answer.role) == ("user", "assistant")
    assert answer.content["text"] == "Bạn nói: xin chào bạn" and answer.content["tool_calls"] == []
    assert answer.content["usage"]["output"] > 0 and str(answer.run_id) == sent["run_id"]
    events = events_of(rt, u.id)
    names = [e for e, _ in events]
    assert names[0] == "agent:start" and names[-1] == "agent:end" and "agent:token" in names
    assert "".join(d["delta"] for e, d in events if e == "agent:token") == "Bạn nói: xin chào bạn"
    assert [d["seq"] for _, d in events] == list(range(1, len(events) + 1))
    assert events[-1][1]["message_id"] == str(answer.id) and events[-1][1]["usage"]["input"] == run.tokens_in
    sent_prompt = fl.REQUESTS[0]["body"]["messages"]
    assert sent_prompt[0]["role"] == "system" and "<context>" in sent_prompt[-1]["content"]
    assert fl.REQUESTS[0]["headers"]["authorization"] == "Bearer fake-key"


async def test_follow_up_turn_includes_history(env):
    api, u, _, _ = env
    first, _ = await chat(api, u, "câu một")
    await chat(api, u, "câu hai", session_id=first["session_id"])
    roles = [m["role"] for m in fl.REQUESTS[-1]["body"]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
    assert [m.role for m in await messages(first["session_id"])] == ["user", "assistant"] * 2


async def test_tool_turn_runs_operation_and_saves_tool_messages(env):
    api, u, rt, _ = env
    await add_notes(u.id, 3)
    sent, run = await chat(api, u, "đọc hết call:notifications_mark_all_read {}")
    assert run.status == "done" and await unread(api, u) == 0
    roles = [m.role for m in await messages(sent["session_id"])]
    assert roles == ["user", "assistant", "tool", "assistant"]
    _, call_msg, tool_msg, final = await messages(sent["session_id"])
    assert call_msg.content["tool_calls"][0]["name"] == "notifications_mark_all_read"
    assert tool_msg.content["name"] == "notifications_mark_all_read" and tool_msg.content["status"] == "success"
    assert tool_msg.content["tool_call_id"] == call_msg.content["tool_calls"][0]["id"]
    assert json.loads(tool_msg.content["text"])["updated"] == 3 and final.content["text"].startswith("Kết quả: ")
    steps = [(d["call_id"], d["status"]) for e, d in events_of(rt, u.id) if e == "agent:step"]
    cid = call_msg.content["tool_calls"][0]["id"]
    assert steps == [(cid, "running"), (cid, "done")]


async def test_tool_error_is_returned_to_llm_and_turn_continues(env):
    api, u, rt, _ = env
    sent, run = await chat(api, u, 'call:notifications_mark_read {"ids": []}')
    assert run.status == "done"
    _, _, tool_msg, final = await messages(sent["session_id"])
    assert tool_msg.content["status"] == "error" and tool_msg.content["text"].startswith("Lỗi ")
    assert [d["status"] for e, d in events_of(rt, u.id) if e == "agent:step"] == ["running", "error"]


async def test_multi_step_script_chains_tool_calls(env):
    api, u, _, _ = env
    sent, run = await chat(api, u, "call:notifications_list {}\ncall:notifications_unread_count {}")
    assert run.status == "done"
    roles = [m.role for m in await messages(sent["session_id"])]
    assert roles == ["user", "assistant", "tool", "assistant", "tool", "assistant"]


async def test_cancel_mid_stream(env):
    api, u, rt, _ = env
    sent = await send(api, u, "slow chậm thôi")
    task = asyncio.create_task(runner.execute(sent["run_id"]))
    assert await until(lambda: any(e == "agent:token" for e, _ in events_of(rt, u.id)), 10)
    await api.post("agent.cancel", u, run_id=sent["run_id"])
    await asyncio.wait_for(task, 10)
    run = await run_row(sent["run_id"])
    assert run.status == "cancelled" and run.error_code == 6014
    end = events_of(rt, u.id, "agent:end")[-1][1]
    assert end["status"] == "cancelled"
    rows = await messages(sent["session_id"])
    assert all(m.content.get("status") == "cancelled" for m in rows if m.role == "assistant")  # chữ dở gắn cờ huỷ
    assert not any(m.role == "assistant" and "w39" in m.content["text"] for m in rows)
    assert await get_connections().redis.rw.exists(f"bw:run:{sent['run_id']}:cancel")


async def test_provider_500_before_tokens_fails_with_6011_when_no_other_key(env):
    api, u, rt, _ = env
    sent, run = await chat(api, u, "fail500 đi")
    assert run.status == "failed" and run.error_code == 6011 and "Nhà cung cấp" in run.error
    err = events_of(rt, u.id, "agent:error")[0][1]
    assert err["code"] == 6011
    assert [m.role for m in await messages(sent["session_id"])] == ["user"]
    assert len(fl.REQUESTS) == 2  # thử lại một lần cùng key rồi hết key


async def test_run_executes_at_most_once(env):
    api, u, _, _ = env
    sent = await send(api, u, "một lần thôi")
    first, second = await asyncio.gather(runner.execute(sent["run_id"]), runner.execute(sent["run_id"]))
    assert (first, second) == (False, False)
    assert len(fl.REQUESTS) == 1
    assert [m.role for m in await messages(sent["session_id"])] == ["user", "assistant"]
    assert await runner.execute(sent["run_id"]) is False  # đã done → bỏ qua
    assert await runner.resume(sent["run_id"]) is False  # không chờ duyệt → bỏ qua


async def test_missing_model_user_or_agent_fail_with_code(env):
    api, u, rt, stack = env
    await patch_agent(stack, model_id=None)
    _, run = await chat(api, u, "không model")
    assert (run.status, run.error_code) == ("failed", 6009)
    await patch_agent(stack, model_id=uuid.UUID(stack.model_id))
    queued = await send(api, u, "agent tắt giữa chừng")
    await patch_agent(stack, is_active=False)
    await runner.execute(queued["run_id"])
    run = await run_row(queued["run_id"])
    assert (run.status, run.error_code) == ("failed", 6003)
    await patch_agent(stack, is_active=True, model_id=uuid.UUID(stack.model_id))
    sent = await send(api, u, "user bị khoá")
    async with get_connections().postgres.rw() as s:
        await s.exec(update(User).where(User.id == uuid.UUID(u.id)).values(is_active=False))
    await runner.execute(sent["run_id"])
    run = await run_row(sent["run_id"])
    assert (run.status, run.error_code) == ("failed", 1005)
    assert fl.REQUESTS == []


async def test_recursion_limit_is_6013_and_keeps_finished_tool_messages(env):
    api, u, _, stack = env
    await patch_agent(stack, recursion_limit=3)
    script = "\n".join(["call:notifications_list {}"] * 6)
    sent, run = await chat(api, u, script)
    assert (run.status, run.error_code) == ("failed", 6013)
    rows = await messages(sent["session_id"])
    assert rows[0].role == "user" and any(m.role == "tool" for m in rows)


async def test_timeout_is_6012(env):
    api, u, _, stack = env
    await patch_agent(stack, timeout_sec=1)
    _, run = await chat(api, u, "slow quá lâu")
    assert (run.status, run.error_code) == ("failed", 6012)


async def test_process_shutdown_marks_run_6015_and_reraises(env):
    api, u, rt, _ = env
    sent = await send(api, u, "slow bị ngắt")
    task = asyncio.create_task(runner.execute(sent["run_id"]))
    assert await until(lambda: any(e == "agent:token" for e, _ in events_of(rt, u.id)), 10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    run = await run_row(sent["run_id"])
    assert (run.status, run.error_code) == ("failed", 6015)
    assert events_of(rt, u.id, "agent:error")[-1][1]["code"] == 6015


async def test_heartbeat_updates_while_running(env, monkeypatch):
    api, u, _, _ = env
    monkeypatch.setattr(runner, "HEARTBEAT_SEC", 0.2)
    sent = await send(api, u, "slow nhịp tim")
    task = asyncio.create_task(runner.execute(sent["run_id"]))
    assert await until(lambda: task.done() is False, 1)
    await asyncio.sleep(1.0)
    beat = (await run_row(sent["run_id"])).heartbeat_at
    started = (await run_row(sent["run_id"])).started_at
    assert beat > started
    await api.post("agent.cancel", u, run_id=sent["run_id"])
    await asyncio.wait_for(task, 10)


async def test_checkpoint_is_dropped_after_turn(env):
    api, u, _, _ = env
    sent, _ = await chat(api, u, "dọn checkpoint")
    saver = await checkpoint.get_checkpointer()
    assert saver is not None
    assert [c async for c in saver.alist({"configurable": {"thread_id": sent["run_id"]}})] == []


def test_to_items_drops_unanswered_tool_calls_and_attaches_usage():
    msgs = [
        AIMessage("", tool_calls=[{"id": "a", "name": "t", "args": {"x": 1}}, {"id": "b", "name": "t", "args": {}}]),
        ToolMessage("kết quả", tool_call_id="a", name="t"),
        AIMessage("xong"),
    ]
    items = runner.to_items(msgs, {"input": 1})
    assert [i["role"] for i in items] == ["assistant", "tool", "assistant"]
    assert [c["id"] for c in items[0]["content"]["tool_calls"]] == ["a"]
    assert "usage" not in items[0]["content"] and items[2]["content"]["usage"] == {"input": 1}
    assert runner.to_items([AIMessage("", tool_calls=[{"id": "z", "name": "t", "args": {}}])], None) == []


def test_classify_error_maps_codes():
    class Boom(Exception):
        status_code = 429

    assert runner.classify_error(AppException(6009, status_code=409))[0] == 6009
    assert runner.classify_error(TimeoutError())[0] == 6012
    assert runner.classify_error(GraphRecursionError("x"))[0] == 6013
    assert runner.classify_error(Boom("limit"))[0] == 6011
    assert runner.classify_error(ValueError("lạ"))[0] == 1000
