"""http_capture: bản ghi request / response đầy đủ (đã che) theo ngữ cảnh — cho raw HTTP của trace."""

import asyncio
import json

import httpx
import httpx2
import pytest

from app.core.http_rules import HttpLogRules
from app.core.httpx_log import http_capture, install_httpx_logging, uninstall_httpx_logging


@pytest.fixture(autouse=True)
def _patch():
    install_httpx_logging(HttpLogRules.empty(), frozenset())
    yield
    uninstall_httpx_logging()


@pytest.mark.parametrize("lib", [httpx2, httpx])
async def test_captures_request_and_response_redacted(lib):
    seen = []
    handler = lambda r: lib.Response(200, json={"ok": True, "api_key": "zzz"})  # noqa: E731
    async with lib.AsyncClient(transport=lib.MockTransport(handler)) as c:
        with http_capture(seen.append):
            await c.post(
                "https://llm.test/v1/chat?key=AIza123&alt=sse",
                json={"messages": [{"content": "xin chào"}]},
                headers={"Authorization": "Bearer sk-secret-123456789", "x-goog-api-key": "g", "api-key": "a"},
            )
    [rec] = seen
    assert rec["method"] == "POST" and "AIza123" not in rec["url"] and "alt=sse" in rec["url"]
    headers = rec["request"]["headers"]
    assert headers["authorization"] == headers["x-goog-api-key"] == headers["api-key"] == "[REDACTED]"
    assert json.loads(rec["request"]["body"])["messages"][0]["content"] == "xin chào"
    assert rec["response"]["status"] == 200 and json.loads(rec["response"]["body"])["api_key"] == "[REDACTED]"
    assert rec["error"] is None and rec["ms"] >= 0 and rec["started_at"]


async def _chunks(*parts: bytes):
    for part in parts:
        yield part


@pytest.mark.parametrize("lib", [httpx2, httpx])
async def test_stream_captured_once_on_close_with_full_body(lib):
    seen = []
    sse = b"data: 1\n\ndata: 2\n\ndata: [DONE]\n\n"

    def handler(request):
        return lib.Response(200, content=_chunks(sse[:9], sse[9:]), headers={"content-type": "text/event-stream"})

    async with lib.AsyncClient(transport=lib.MockTransport(handler)) as c:
        with http_capture(seen.append):
            async with c.stream("POST", "https://llm.test/stream", json={}) as resp:
                assert seen == []  # chưa đọc xong → chưa phát
                body = b"".join([chunk async for chunk in resp.aiter_raw()])
    assert len(seen) == 1 and seen[0]["response"]["body"] == sse.decode() and body == sse
    assert seen[0]["response"]["bytes"] == len(sse)


async def test_stream_closed_early_still_emits_partial():
    seen = []

    def handler(request):
        return httpx2.Response(200, content=_chunks(*[b"a" * 1000] * 10), headers={"content-type": "text/plain"})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as c:
        with http_capture(seen.append):
            async with c.stream("GET", "https://llm.test/x") as resp:
                async for _ in resp.aiter_raw():
                    break
    assert len(seen) == 1 and 0 < seen[0]["response"]["bytes"] < 10000


async def test_stream_request_on_already_read_response_emits_immediately():
    seen = []
    handler = lambda r: httpx2.Response(200, text="đã đọc sẵn")  # noqa: E731
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as c:
        with http_capture(seen.append):
            async with c.stream("GET", "https://llm.test/read") as resp:
                assert len(seen) == 1
                await resp.aread()
    assert len(seen) == 1 and seen[0]["response"]["body"] == "đã đọc sẵn"


async def test_error_is_captured():
    seen = []

    def boom(request):
        raise httpx2.ConnectError("no route")

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(boom)) as c:
        with http_capture(seen.append):
            with pytest.raises(httpx2.ConnectError):
                await c.get("https://llm.test/")
    assert seen[0]["response"] is None and "ConnectError" in seen[0]["error"]


async def test_no_sink_no_capture_and_tasks_isolated():
    a, b, none = [], [], []

    async def call(sink, path):
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(lambda r: httpx2.Response(204))) as c:
            with http_capture(sink.append):
                await c.get(f"https://llm.test/{path}")

    await asyncio.gather(call(a, "a"), call(b, "b"))
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(lambda r: httpx2.Response(204))) as c:
        await c.get("https://llm.test/none")
    assert [r["url"] for r in a] == ["https://llm.test/a"] and [r["url"] for r in b] == ["https://llm.test/b"]
    assert none == []


async def test_broken_sink_does_not_break_request(bw_log):
    def bad(record):
        raise RuntimeError("sink hỏng")

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(lambda r: httpx2.Response(200, text="ok"))) as c:
        with http_capture(bad):
            r = await c.get("https://llm.test/")
    assert r.text == "ok"
    assert any(line["loc"] == "hout0502" for line in bw_log())


def test_sync_client_captured():
    seen = []
    with httpx2.Client(transport=httpx2.MockTransport(lambda r: httpx2.Response(200, text="xin chào"))) as c:
        with http_capture(seen.append):
            c.get("https://llm.test/sync")
    assert seen[0]["response"]["body"] == "xin chào"


async def test_binary_body_is_summarised():
    seen = []
    handler = lambda r: httpx2.Response(200, content=b"\x89PNG....", headers={"content-type": "image/png"})  # noqa: E731
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as c:
        with http_capture(seen.append):
            await c.get("https://llm.test/img")
    assert seen[0]["response"]["body"].startswith("<binary")


def test_sync_stream_captured_on_close():
    seen = []

    def parts():
        yield b"mot "
        yield b"hai"

    with httpx2.Client(transport=httpx2.MockTransport(lambda r: httpx2.Response(200, content=parts()))) as c:
        with http_capture(seen.append):
            with c.stream("GET", "https://llm.test/sync-stream") as resp:
                assert b"".join(resp.iter_raw()) == b"mot hai"
    assert len(seen) == 1 and seen[0]["response"]["body"] == "mot hai"


async def test_capture_works_with_http_logging_off(bw_log):
    """`LOG_HTTP_OUT=false` chỉ tắt dòng log — bản vá vẫn cài, trace vẫn bắt được raw."""
    uninstall_httpx_logging()
    install_httpx_logging(HttpLogRules.empty(), frozenset(), log=False)
    seen = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(204))) as c:
        with http_capture(seen.append):
            await c.get("https://llm.test/ping")
    assert len(seen) == 1 and seen[0]["response"]["status"] == 204
    assert not [line for line in bw_log() if line["loc"].startswith("hout")]
