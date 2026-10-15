"""LLM giả: kịch bản text / tool call / lỗi, usage, webhook giả."""

import json

import httpx2
import pytest

from app.agent.testing import fake_llm as fl

TOOLS = [{"type": "function", "function": {"name": "wallet_list", "parameters": {"type": "object"}}}]


def body(content="xin chào", *, tools=None, stream=False, extra=None):
    out = {"model": "fake-model", "stream": stream, "messages": [{"role": "user", "content": content}]}
    if tools is not None:
        out["tools"] = tools
    return {**out, **(extra or {})}


async def post(server, payload, key="fake-key"):
    async with httpx2.AsyncClient(timeout=10) as c:
        return await c.post(
            f"{server.base_url}/chat/completions", json=payload, headers={"authorization": f"Bearer {key}"}
        )


async def test_fake_llm_text_tool_call_and_errors(fake_llm):
    text = (await post(fake_llm, body("chào bạn"))).json()
    assert text["choices"][0]["message"]["content"] == "Bạn nói: chào bạn" and text["usage"]["prompt_tokens"] >= 1
    tool = (await post(fake_llm, body('call:wallet_list {"limit": 5}', tools=TOOLS))).json()
    call = tool["choices"][0]["message"]["tool_calls"][0]["function"]
    assert call["name"] == "wallet_list" and json.loads(call["arguments"]) == {"limit": 5}
    assert tool["choices"][0]["finish_reason"] == "tool_calls"
    unknown = (await post(fake_llm, body("call:khong_co {}", tools=TOOLS))).json()
    assert unknown["choices"][0]["message"]["content"] == "Không có tool khong_co"
    assert (await post(fake_llm, body("fail500 đi"))).status_code == 500
    async with httpx2.AsyncClient() as c:
        assert (
            await c.get(f"{fake_llm.base_url}/models", headers={"authorization": "Bearer bad-key"})
        ).status_code == 401
        ok = await c.get(f"{fake_llm.base_url}/models", headers={"authorization": "Bearer good"})
    assert {m["id"] for m in ok.json()["data"]} >= {"fake-model", "fake/large"}
    assert (await post(fake_llm, body(), key="bad-key")).status_code == 401
    assert (await post(fake_llm, body(), key="ratelimit-1")).status_code == 429
    assert len(fl.REQUESTS) == 6 and fl.REQUESTS[0]["body"]["model"] == "fake-model"


async def test_context_block_stripped_and_tool_result_answered(fake_llm):
    said = (await post(fake_llm, body("<context>x: y</context>\n\nhi"))).json()
    assert said["choices"][0]["message"]["content"] == "Bạn nói: hi"
    messages = [
        {"role": "user", "content": "call:wallet_list {}"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "wallet_list", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "[]"},
    ]
    done = (await post(fake_llm, {"model": "m", "messages": messages, "tools": TOOLS})).json()
    assert done["choices"][0]["message"]["content"] == "Kết quả: []"


async def test_multi_step_script_runs_second_call_after_first_result(fake_llm):
    user = 'call:wallet_list {"a": 1}\ncall:wallet_list {"a": 2}'
    first = [{"role": "user", "content": user}]
    after_one = [
        *first,
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "wallet_list", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "ok"},
    ]
    second = (await post(fake_llm, {"model": "m", "messages": after_one, "tools": TOOLS})).json()
    assert json.loads(second["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]) == {"a": 2}


async def test_stream_sse_has_usage_and_parallel_calls(fake_llm):
    payload = body("a b c", stream=True, extra={"stream_options": {"include_usage": True}})
    async with httpx2.AsyncClient(timeout=10) as c:
        r = await c.post(f"{fake_llm.base_url}/chat/completions", json=payload, headers={"authorization": "Bearer k"})
    chunks = [json.loads(x[6:]) for x in r.text.splitlines() if x.startswith("data: ") and x != "data: [DONE]"]
    text = "".join(ch["choices"][0]["delta"].get("content") or "" for ch in chunks if ch["choices"])
    assert text == "Bạn nói: a b c" and chunks[-1]["usage"]["total_tokens"] > 0 and r.text.rstrip().endswith("[DONE]")
    fl.PARALLEL = True
    tool = body("call:wallet_list {}", tools=TOOLS, stream=True)
    async with httpx2.AsyncClient(timeout=10) as c:
        r = await c.post(f"{fake_llm.base_url}/chat/completions", json=tool, headers={"authorization": "Bearer k"})
    first = json.loads(r.text.split("\n\n")[0][6:])
    assert len(first["choices"][0]["delta"]["tool_calls"]) == 2


def test_plan_slow_and_usage_cache_split():
    plan = fl._plan(body("slow please"))
    assert plan["kind"] == "text" and plan["delay"] == 0.1 and plan["text"].startswith("w0 w1")
    usage = fl._usage({"messages": [{"role": "user", "content": "x" * 400}, {"role": "user", "content": "y" * 40}]}, 3)
    assert usage["prompt_tokens"] == 110 and usage["prompt_tokens_details"]["cached_tokens"] == 100
    assert fl._text([{"text": "a"}, {"type": "image"}, "x"]) == "a" and fl._text(None) == ""


async def test_hooks_endpoint_records_and_clears(fake_llm):
    root = fake_llm.base_url.removesuffix("/v1")
    async with httpx2.AsyncClient() as c:
        assert (await c.post(f"{root}/hooks/a/b", json={"x": 1})).json()["received"] == 1
        await c.post(f"{root}/hooks/raw", content=b"not json")
        listed = (await c.get(f"{root}/hooks", params={"clear": 1})).json()
        assert listed[0] == {"path": "/hooks/a/b", "body": {"x": 1}} and listed[1]["body"] == "not json"
        assert (await c.get(f"{root}/hooks")).json() == []


@pytest.mark.parametrize("n", [1])
def test_server_start_stop_uses_free_port(n):
    server = fl.FakeLLMServer().start()
    try:
        assert server.base_url.endswith("/v1") and server.port > 0
    finally:
        server.stop()


def test_plan_parallel_keyword_returns_all_calls_in_one_step():
    tools = [{"type": "function", "function": {"name": "wallet_list", "parameters": {"type": "object"}}}]
    script = 'parallel đi\ncall:wallet_list {"limit": 1}\ncall:wallet_list {"limit": 2}'
    plan = fl._plan(body(script, tools=tools))
    assert plan == {"kind": "tool", "calls": [("wallet_list", {"limit": 1}), ("wallet_list", {"limit": 2})]}
    done = body(script, tools=tools)
    done["messages"] += [
        {"role": "assistant", "tool_calls": [{"id": "1"}, {"id": "2"}]},
        {"role": "tool", "content": "ok"},
    ]
    assert fl._plan(done)["kind"] == "text"
    serial = fl._plan(body(script.replace("parallel", "tuần tự"), tools=tools))
    assert serial["kind"] == "tool" and "calls" not in serial
