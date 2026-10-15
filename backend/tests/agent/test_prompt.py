"""Lắp prompt: persona + instructions, lịch sử bỏ tool call mồ côi, giới hạn lịch sử, cache_control cho Anthropic."""

import uuid

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.agent.chat import service as chat
from app.agent.chat.models import AgentMessage
from app.agent.runtime import prompt
from app.core.connections.registry import get_connections
from tests.agent.helpers import send, set_run, setup


def msg(seq: int, role: str, **content) -> AgentMessage:
    return AgentMessage(session_id=uuid.uuid4(), seq=seq, role=role, content=content)


def test_system_text_joins_persona_and_instructions():
    assert prompt.system_text("  P  ", "I\n") == "P\n\nI"
    assert prompt.system_text("", "I") == "I" and prompt.system_text("", "") == ""


def test_history_drops_orphan_tool_calls_and_respects_limit_shape():
    rows = [
        msg(1, "user", text="chi 50k"),
        msg(
            2,
            "assistant",
            text="",
            tool_calls=[
                {"id": "a", "name": "wallet_x", "args": {"n": 1}},
                {"id": "orphan", "name": "wallet_y", "args": {}},
            ],
        ),
        msg(3, "tool", text="ok", tool_call_id="a", name="wallet_x"),
        msg(
            4, "assistant", text="", tool_calls=[{"id": "gone", "name": "wallet_z", "args": {}}]
        ),  # không có kết quả, không có chữ
        msg(5, "assistant", text="xong rồi", tool_calls=[]),
        msg(6, "tool", text="mồ côi", name="x"),  # tool không có tool_call_id
    ]
    out = prompt.history(rows)
    assert [type(m) for m in out] == [HumanMessage, AIMessage, ToolMessage, AIMessage]
    assert [c["id"] for c in out[1].tool_calls] == ["a"] and out[3].content == "xong rồi"
    assert out[2].tool_call_id == "a"


def test_build_puts_context_before_new_message_and_system_first():
    out = prompt.build(
        "SYS",
        [msg(1, "user", text="cũ"), msg(2, "assistant", text="trả lời")],
        "mới",
        "<context>c</context>",
        provider="openai",
    )
    assert isinstance(out[0], SystemMessage) and out[0].content.startswith("SYS") and "<context>" in out[0].content
    assert [type(m) for m in out[1:]] == [HumanMessage, AIMessage, HumanMessage]
    assert out[-1].content == "<context>c</context>\n\nmới" and out[1].content == "cũ"
    assert prompt.build("S", [], "chỉ tin", "", provider="openai")[-1].content == "chỉ tin"


def test_anthropic_gets_cache_control_on_system_and_last_history_message():
    out = prompt.build(
        "SYS", [msg(1, "user", text="cũ"), msg(2, "assistant", text="đáp")], "mới", "<context/>", provider="anthropic"
    )
    assert out[0].content[0]["cache_control"] == {"type": "ephemeral"}
    assert out[1].content == "cũ" or isinstance(out[1].content, str)
    assert out[2].content[0]["cache_control"] == {"type": "ephemeral"} and out[2].content[0]["text"] == "đáp"
    assert out[-1].content == "<context/>\n\nmới"
    plain = prompt.build("SYS", [msg(1, "user", text="cũ")], "mới", "", provider="google_genai")
    assert isinstance(plain[0].content, str) and isinstance(plain[1].content, str)


async def test_history_service_limit_starts_at_user_and_excludes_current_run(api, aenv, kicks, fake_llm):
    await setup(api, fake_llm.base_url)
    u = await api.as_user("h@x.io")
    first = await send(api, u, "một")
    sid = first["session_id"]
    await set_run(first["run_id"], status="done")
    runs = [first["run_id"]]
    for text in ("hai", "ba", "bốn"):
        sent = await send(api, u, text, session_id=sid)
        await set_run(sent["run_id"], status="done")
        runs.append(sent["run_id"])
    async with get_connections().postgres.ro() as s:
        past = await chat.history(s, uuid.UUID(sid), 10, exclude_run=uuid.UUID(runs[-1]))
        assert [m.content["text"] for m in past] == ["một", "hai", "ba"]
        short = await chat.history(s, uuid.UUID(sid), 2, exclude_run=uuid.UUID(runs[-1]))
        assert [m.content["text"] for m in short] == ["hai", "ba"]
        assert await chat.run_input(s, uuid.UUID(runs[1])) == "hai" and await chat.run_input(s, uuid.uuid4()) == ""
