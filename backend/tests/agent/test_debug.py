"""`bw dump-chat-session` (R24): gom phiên + tin nhắn + lượt + duyệt (+ span khi bật trace) vào một JSON."""

import json
import uuid

import pytest
from typer.testing import CliRunner

from app import cli as cli_module
from app.agent.debug import dump_session
from tests.agent.helpers import add_approval, chat, setup

runner = CliRunner()


@pytest.fixture
async def env(api, aenv, rt, fake_llm):
    stack = await setup(api, fake_llm.base_url)
    u = await api.as_user("dbg@x.io")
    return stack, u


async def test_dump_has_all_keys_with_messages_run_and_approval(env):
    stack, u = env
    sent, run = await chat(stack.api, u, "chào")
    await add_approval(run.id)
    out = await dump_session(uuid.UUID(sent["session_id"]))
    assert set(out) == {"session", "messages", "runs", "approvals", "trace_enabled"}
    assert out["session"]["id"] == sent["session_id"]
    assert len(out["messages"]) >= 2 and [m["seq"] for m in out["messages"]] == sorted(
        m["seq"] for m in out["messages"]
    )
    assert [r["id"] for r in out["runs"]] == [str(run.id)]
    assert len(out["approvals"]) == 1 and out["approvals"][0]["run_id"] == str(run.id)
    assert out["trace_enabled"] is False and out["runs"][0]["spans"] is None
    json.dumps(out)  # tuần tự hoá được


async def test_dump_unknown_session_raises_lookup_error(env):
    with pytest.raises(LookupError):
        await dump_session(uuid.uuid4())


async def test_dump_includes_spans_when_trace_enabled(env, trace_sink):
    stack, u = env
    sent, run = await chat(stack.api, u, "chào")
    out = await dump_session(uuid.UUID(sent["session_id"]))
    assert out["trace_enabled"] is True
    spans = out["runs"][0]["spans"]
    assert spans and {s["run_id"] for s in spans} == {str(run.id)} and "run" in {s["kind"] for s in spans}


def test_cli_writes_json_file(monkeypatch, tmp_path):
    sid = uuid.uuid4()
    data = {"session": {"id": str(sid)}, "messages": [{"seq": 1}], "runs": [], "approvals": [], "trace_enabled": False}

    async def fake(_s, session_id):
        assert session_id == sid
        return data

    monkeypatch.setattr(cli_module, "_dump_chat", fake)
    target = tmp_path / "out.json"
    result = runner.invoke(cli_module.cli, ["dump-chat-session", str(sid), "--out", str(target)])
    assert result.exit_code == 0 and "1 tin nhắn" in result.output
    assert json.loads(target.read_text()) == data


def test_cli_unknown_session_exits_1(monkeypatch, tmp_path):
    async def fake(_s, session_id):
        raise LookupError(f"không có phiên {session_id}")

    monkeypatch.setattr(cli_module, "_dump_chat", fake)
    result = runner.invoke(cli_module.cli, ["dump-chat-session", str(uuid.uuid4()), "--out", str(tmp_path / "x.json")])
    assert result.exit_code == 1 and "không có phiên" in result.output
