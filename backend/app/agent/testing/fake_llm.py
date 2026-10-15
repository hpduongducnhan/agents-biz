"""Server LLM giả kiểu OpenAI (`/v1/chat/completions`, stream SSE + tool call) cho test và E2E — kịch bản cố định:

- tin user có `call:<tên> <json một dòng>` và `<tên>` nằm trong `tools` của request → trả tool call; nhiều dòng `call:`
  = nhiều bước nối nhau (sau kết quả tool thứ k gọi call thứ k + 1; nhiều call được nằm chung một dòng); có thêm chữ
  `parallel` → mọi `call:` trả cùng lúc trong một bước (tool call song song — E2E thẻ gom duyệt);
- tin cuối là kết quả tool và không còn dòng `call:` nào → trả chữ `Kết quả: <200 ký tự đầu của kết quả>`;
- có `fail500` → HTTP 500; có `slow` → 40 cụm chữ cách nhau 0,1 giây;
- còn lại → stream `Bạn nói: <nội dung>` từng từ (bỏ khối `<context>…</context>`).
- router (request có tool `RouteDecision`): `route:a,b việc 1 | việc 2` → các bước; `clarify:<câu>` → hỏi lại;
  `routefail` → trả chữ; còn lại → `personal` (chuyên gia thử) nếu có trong bảng route, không thì `general`.
  Bước chuyên gia có `<task>` → chỉ đọc kịch bản trong khối task (vd `route:tasks call:tasks_list {}`).

Usage: ~4 ký tự một token; `cached_tokens` = phần tiền tố (mọi message trừ tin cuối).

`/hooks/<đường dẫn>` (POST): ghi body nhận được — webhook giả cho E2E hook; `GET /hooks` trả mọi body đã nhận
(`?clear=1` xoá sau khi đọc).

`GET /v1/models`: `fake-model`, `fake-embed`, `fake/large` (kèm context + giá kiểu OpenRouter). Key chứa `bad` → 401
(cả `/v1/models` lẫn chat), chứa `ratelimit` → 429 ở chat (test xoay key).

Chạy riêng: `make fake-llm` (= `python -m app.agent.testing.fake_llm --port 8799`).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import socket
import threading
import time
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

REQUESTS: list[dict[str, Any]] = []  # mọi request nhận được (body + header) — test đọc để kiểm prompt / tham số
PARALLEL = False  # True: tool call trả hai lần trong cùng một bước (hai call song song)
CALL_RE = re.compile(r"call:([A-Za-z0-9_-]+)[ \t]+(?=\{)")
JSON = json.JSONDecoder()
CONTEXT_RE = re.compile(r"<context>.*?</context>\s*", re.S)
EARLIER_RE = re.compile(r"<earlier>.*?</earlier>\s*", re.S)
TASK_RE = re.compile(r"<task>(.*?)</task>", re.S)
ROUTE_RE = re.compile(r"route:([A-Za-z0-9_,-]+)[ \t]*([^\n]*)")
CLARIFY_RE = re.compile(r"clarify:([^\n]+)")
PARALLEL_RE = re.compile(r"\bparallel\b")


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


def _route(body: dict, said: str) -> dict:
    """Router (tool `RouteDecision`): `route:a,b việc 1 | việc 2` → các bước; `clarify:<câu>` → hỏi lại;
    `routefail` → trả chữ (không có quyết định); còn lại → `personal` nếu có trong bảng route, không thì `general`."""
    said = said.split("Tin nhắn mới:", 1)[-1].strip()
    if "routefail" in said:
        return {"kind": "text", "text": "không phải JSON", "delay": 0.0}
    found = CLARIFY_RE.search(said)
    if found:
        return {"kind": "tool", "name": "RouteDecision", "args": {"steps": [], "clarify": found.group(1).strip()}}
    found = ROUTE_RE.search(said)
    if found:
        slugs = [x for x in found.group(1).split(",") if x]
        tasks = [t.strip() for t in found.group(2).split("|")]
        steps = [{"agent": slug, "task": tasks[i] if i < len(tasks) else ""} for i, slug in enumerate(slugs)]
        return {"kind": "tool", "name": "RouteDecision", "args": {"steps": steps, "clarify": None}}
    system = _text((body.get("messages") or [{}])[0].get("content"))
    slug = "personal" if "`personal`" in system else "general"
    return {"kind": "tool", "name": "RouteDecision", "args": {"steps": [{"agent": slug, "task": ""}], "clarify": None}}


def _calls(said: str) -> list[tuple[str, dict]]:
    """Mọi `call:<tên> {json}` theo thứ tự — JSON đọc tới hết object, nên một dòng chứa được nhiều call (task của router
    chỉ một dòng). JSON hỏng → dừng ở call đó."""
    out: list[tuple[str, dict]] = []
    for m in CALL_RE.finditer(said):
        try:
            args, _ = JSON.raw_decode(said, m.end())
        except json.JSONDecodeError:
            break
        out.append((m.group(1), args))
    return out


def _plan(body: dict) -> dict:
    """Quyết định trả lời: {"kind": "text", "text", "delay"} | {"kind": "tool", "name", "args"} | {"kind": "tool",
    "calls": [(name, args), …]} (song song) | {"kind": "error"}.
    Tin có `<task>…</task>` (bước chuyên gia) → chỉ đọc kịch bản trong khối task."""
    messages = body.get("messages", [])
    last = messages[-1] if messages else {}
    at = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
    user = messages[at] if at >= 0 else {}
    raw = _text(user.get("content"))
    task = TASK_RE.search(raw)
    said = task.group(1).strip() if task else EARLIER_RE.sub("", CONTEXT_RE.sub("", raw)).strip()
    if "RouteDecision" in {t.get("function", {}).get("name") for t in body.get("tools") or []}:
        return _route(body, said)
    steps = _calls(said)
    done = sum(1 for m in messages[at + 1 :] if m.get("role") == "assistant" and m.get("tool_calls"))
    batch = len(steps) > 1 and PARALLEL_RE.search(said) is not None
    if last.get("role") == "tool" and (done >= len(steps) or (batch and done >= 1)):
        return {"kind": "text", "text": "Kết quả: " + _text(last.get("content"))[:200], "delay": 0.0}
    tools = {t.get("function", {}).get("name") for t in body.get("tools") or []}
    if batch and done == 0:
        missing = [name for name, _ in steps if name not in tools]
        if missing:
            return {"kind": "text", "text": f"Không có tool {missing[0]}", "delay": 0.0}
        return {"kind": "tool", "calls": steps}
    found = steps[done] if done < len(steps) else None
    if found:  # trước `fail500`: tin giao việc cho agent con có thể chứa kịch bản lỗi của agent con
        name, args = found
        if name not in tools:
            return {"kind": "text", "text": f"Không có tool {name}", "delay": 0.0}
        return {"kind": "tool", "name": name, "args": args}
    if "fail500" in said:
        return {"kind": "error"}
    if "slow" in said:
        return {"kind": "text", "text": " ".join(f"w{i}" for i in range(40)), "delay": 0.1}
    return {"kind": "text", "text": f"Bạn nói: {said}", "delay": 0.0}


def _usage(body: dict, completion: int) -> dict:
    """~4 ký tự một token; tiền tố (mọi message trừ tin cuối) coi như provider đã cache — như cache tiền tố thật."""
    messages = body.get("messages", [])
    prompt = max(1, sum(len(_text(m.get("content"))) for m in messages) // 4)
    cached = min(prompt, sum(len(_text(m.get("content"))) for m in messages[:-1]) // 4)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "prompt_tokens_details": {"cached_tokens": cached},
    }


def _chunk(model: str, delta: dict, finish: str | None = None) -> str:
    data = {
        "id": "chatcmpl-fake",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream(body: dict, plan: dict):
    model = body.get("model", "fake")
    if plan["kind"] == "tool":
        wanted = plan.get("calls") or [(plan["name"], plan["args"])] * (2 if PARALLEL else 1)
        calls = [
            {
                "index": i,
                "id": f"call_{len(REQUESTS)}_{i}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
            }
            for i, (name, args) in enumerate(wanted)
        ]
        yield _chunk(model, {"role": "assistant", "content": None, "tool_calls": calls})
        yield _chunk(model, {}, "tool_calls")
        completion = 5
    else:
        words = plan["text"].split(" ")
        yield _chunk(model, {"role": "assistant", "content": ""})
        for i, word in enumerate(words):
            if plan["delay"]:
                await asyncio.sleep(plan["delay"])
            yield _chunk(model, {"content": word if i == 0 else f" {word}"})
        yield _chunk(model, {}, "stop")
        completion = len(words)
    if (body.get("stream_options") or {}).get("include_usage"):
        usage = {"id": "chatcmpl-fake", "object": "chat.completion.chunk", "model": model, "choices": []}
        usage["usage"] = _usage(body, completion)
        yield f"data: {json.dumps(usage)}\n\n"
    yield "data: [DONE]\n\n"


async def completions(request: Request):
    body = await request.json()
    REQUESTS.append({"body": body, "headers": dict(request.headers)})
    auth = request.headers.get("authorization", "")
    if "bad" in auth:
        return JSONResponse({"error": {"message": "Incorrect API key provided", "type": "invalid_request_error"}}, 401)
    if "ratelimit" in auth:
        return JSONResponse({"error": {"message": "Rate limit reached", "type": "rate_limit_error"}}, 429)
    plan = _plan(body)
    if plan["kind"] == "error":
        return JSONResponse({"error": {"message": "boom", "type": "server_error"}}, status_code=500)
    if body.get("stream"):
        return StreamingResponse(_stream(body, plan), media_type="text/event-stream")
    message: dict[str, Any] = {"role": "assistant", "content": plan.get("text")}
    finish, completion = "stop", len(plan.get("text", "").split())
    if plan["kind"] == "tool":
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": f"call_{len(REQUESTS)}",
                    "type": "function",
                    "function": {"name": plan["name"], "arguments": json.dumps(plan["args"])},
                }
            ],
        }
        finish, completion = "tool_calls", 5
    return JSONResponse(
        {
            "id": "chatcmpl-fake",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.get("model", "fake"),
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": _usage(body, completion),
        }
    )


HOOK_CALLS: list[dict[str, Any]] = []


async def hook_in(request: Request):
    try:
        body = await request.json()
    except ValueError:
        body = (await request.body()).decode(errors="replace")
    HOOK_CALLS.append({"path": request.url.path, "body": body})
    return JSONResponse({"ok": True, "received": len(HOOK_CALLS)})


async def hook_list(request: Request):
    out = list(HOOK_CALLS)
    if request.query_params.get("clear"):
        HOOK_CALLS.clear()
    return JSONResponse(out)


MODEL_LIST = [
    {"id": "fake-model", "object": "model"},
    {"id": "fake-embed", "object": "model"},
    {
        "id": "fake/large",
        "object": "model",
        "name": "Fake Large",
        "context_length": 128000,
        "pricing": {"prompt": "0.000002", "completion": "0.000008", "input_cache_read": "0.0000005"},
    },
]


async def models(request: Request):
    """Danh sách model kiểu OpenAI / OpenRouter; key chứa `bad` → 401 (câu lỗi kiểu OpenAI)."""
    if "bad" in request.headers.get("authorization", ""):
        return JSONResponse({"error": {"message": "Incorrect API key provided", "type": "invalid_request_error"}}, 401)
    return JSONResponse({"object": "list", "data": MODEL_LIST})


app = Starlette(
    routes=[
        Route("/v1/chat/completions", completions, methods=["POST"]),
        Route("/v1/models", models),
        Route("/hooks", hook_list),
        Route("/hooks/{path:path}", hook_in, methods=["POST"]),
    ]
)


class FakeLLMServer:
    """Chạy `app` bằng uvicorn trong thread riêng trên cổng trống — `base_url` = `http://127.0.0.1:<port>/v1`."""

    def __init__(self) -> None:
        self._sock = socket.socket()
        self._sock.bind(("127.0.0.1", 0))
        self.port = self._sock.getsockname()[1]
        self._server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
        self._thread = threading.Thread(target=self._server.run, kwargs={"sockets": [self._sock]}, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def start(self) -> FakeLLMServer:
        self._thread.start()
        deadline = time.monotonic() + 10
        while not self._server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("fake LLM không khởi động được")
            time.sleep(0.02)
        return self

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5)


if __name__ == "__main__":  # pragma: no cover — chạy tay cho E2E
    parser = argparse.ArgumentParser(description="Server LLM giả kiểu OpenAI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8799)
    opts = parser.parse_args()
    uvicorn.run(app, host=opts.host, port=opts.port, log_level="info")
