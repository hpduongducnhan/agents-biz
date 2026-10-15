import re

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import StreamingResponse

from app.core.exception_handlers import register_exception_handlers
from app.core.http_log import HttpLogMiddleware
from app.core.http_rules import HttpLogRule, HttpLogRules
from app.core.response import ApiResponse
from app.core.settings import Settings
from tests.conftest import asgi_client

HEX32 = re.compile(r"^[0-9a-f]{32}$")
SSE = "data: 0\n\ndata: 1\n\ndata: 2\n\n"


def make_app(rules: HttpLogRules | None = None, **settings_kw) -> FastAPI:
    s = Settings(_env_file=None, SERVICE_PATH="bizwithagents", **settings_kw)
    app = FastAPI()
    register_exception_handlers(app)
    r = APIRouter(prefix=s.api_prefix)

    @r.get("/items/{uid}")
    async def item(uid: str, request: Request):
        request.state.user_id = "u1"
        return ApiResponse.ok({"uid": uid})

    @r.post("/echo")
    async def echo(body: dict):
        return ApiResponse.ok(body)

    @r.get("/boom")
    async def boom():
        raise RuntimeError("x")

    @r.get("/stream")
    async def stream():
        async def gen():
            for i in range(3):
                yield f"data: {i}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    @r.get("/health")
    async def health():
        return {"ok": True}

    app.include_router(r)
    app.add_middleware(HttpLogMiddleware, settings=s, rules=rules or HttpLogRules.empty())
    return app


def http_lines(bw_log, loc: str = "http0001") -> list[dict]:
    return [line for line in bw_log() if line["loc"] == loc]


async def test_logs_one_line_with_route_template_and_echoes_cid(bw_log):
    async with asgi_client(make_app()) as c:
        r = await c.get("/bizwithagents/api/items/42?api_key=zzz&q=1", headers={"X-Correlation-ID": "abc-123"})
    assert r.headers["x-correlation-id"] == "abc-123"
    assert r.json()["correlation_id"] == "abc-123"
    lines = http_lines(bw_log)
    assert len(lines) == 1
    line = lines[0]
    assert line["level"] == "INFO" and line["cid"] == "abc-123"
    h = line["http"]
    assert h["route"] == "/bizwithagents/api/items/{uid}" and h["status"] == 200 and h["user"] == "u1"
    assert "zzz" not in h["query"] and "q=1" in h["query"]


async def test_invalid_cid_header_is_replaced():
    async with asgi_client(make_app()) as c:
        r = await c.get("/bizwithagents/api/items/1", headers={"X-Correlation-ID": "evil value<script>" + "x" * 70})
    assert HEX32.match(r.headers["x-correlation-id"])
    assert r.json()["correlation_id"] == r.headers["x-correlation-id"]


async def test_client_errors_warn_and_server_errors_error(bw_log):
    async with asgi_client(make_app()) as c:
        await c.get("/bizwithagents/api/nope")
        r = await c.get("/bizwithagents/api/boom")
    assert r.status_code == 500
    levels = {line["http"]["status"]: line["level"] for line in http_lines(bw_log)}
    assert levels == {404: "WARNING", 500: "ERROR"}


async def test_unhandled_500_carries_cid_header():
    async with asgi_client(make_app()) as c:
        r = await c.get("/bizwithagents/api/boom", headers={"X-Correlation-ID": "abc-500"})
    assert r.status_code == 500
    assert r.headers.get("x-correlation-id") == "abc-500"
    assert r.json()["correlation_id"] == "abc-500"


async def test_health_is_not_logged_but_gets_cid(bw_log):
    async with asgi_client(make_app()) as c:
        r = await c.get("/bizwithagents/api/health")
    assert HEX32.match(r.headers["x-correlation-id"])
    assert http_lines(bw_log) == []


async def test_body_capture_with_rule_redacts_secrets(bw_log):
    rules = HttpLogRules(
        inbound=[HttpLogRule(match="/bizwithagents/api/echo", req_body=True, resp_body=True, req_headers=True)],
        outbound=[],
    )
    async with asgi_client(make_app(rules)) as c:
        r = await c.post(
            "/bizwithagents/api/echo",
            json={"name": "a", "password": "s3cret"},
            headers={"Authorization": "Bearer abcdefghijkl"},
        )
    assert r.json()["data"] == {"name": "a", "password": "s3cret"}  # handler nhận body gốc
    h = http_lines(bw_log)[0]["http"]
    assert "s3cret" not in h["req_body"] and "[REDACTED]" in h["req_body"]
    assert "s3cret" not in h["resp_body"]
    assert h["req_headers"]["authorization"] == "[REDACTED]"


async def test_no_body_captured_without_rule(bw_log):
    async with asgi_client(make_app()) as c:
        await c.post("/bizwithagents/api/echo", json={"password": "s3cret"})
    h = http_lines(bw_log)[0]["http"]
    assert "req_body" not in h and "resp_body" not in h and h["req_bytes"] > 0


async def test_sse_stream_passes_through_and_body_not_logged(bw_log):
    rules = HttpLogRules(inbound=[HttpLogRule(match="/bizwithagents/api/stream", resp_body=True)], outbound=[])
    async with asgi_client(make_app(rules)) as c:
        async with c.stream("GET", "/bizwithagents/api/stream") as r:
            text = "".join([chunk async for chunk in r.aiter_text()])
    assert text == SSE
    h = http_lines(bw_log)[0]["http"]
    assert "resp_body" not in h and h["resp_bytes"] == len(SSE.encode())


async def test_slow_request_is_warning_http0002(bw_log):
    async with asgi_client(make_app(LOG_HTTP_SLOW_MS=-1)) as c:
        await c.get("/bizwithagents/api/items/1")
    lines = http_lines(bw_log, "http0002")
    assert len(lines) == 1 and lines[0]["level"] == "WARNING"


async def test_disabled_logging_still_sets_cid(bw_log):
    s = Settings(_env_file=None)
    app = FastAPI()

    @app.get("/bizwithagents/api/x")
    async def x():
        return ApiResponse.ok()

    app.add_middleware(HttpLogMiddleware, settings=s, rules=HttpLogRules.empty(), enabled=False)
    async with asgi_client(app) as c:
        r = await c.get("/bizwithagents/api/x", headers={"X-Correlation-ID": "k1"})
    assert r.headers["x-correlation-id"] == "k1" and r.json()["correlation_id"] == "k1"
    assert http_lines(bw_log) == []


async def test_logging_failure_never_breaks_the_response(monkeypatch, bw_log):
    def boom(self, *args, **kwargs):
        raise RuntimeError("log hỏng")

    monkeypatch.setattr(HttpLogMiddleware, "_log", boom)
    async with asgi_client(make_app()) as c:
        r = await c.get("/bizwithagents/api/items/7")
    assert r.status_code == 200 and r.json()["data"] == {"uid": "7"}
    assert any(line["loc"] == "http0500" for line in bw_log())


async def test_route_template_keeps_include_time_prefix(bw_log):
    s = Settings(_env_file=None, SERVICE_PATH="bizwithagents")
    inner = APIRouter(prefix="/mod")

    @inner.get("/things/{tid}")
    async def thing(tid: str):
        return ApiResponse.ok({"tid": tid})

    app = FastAPI()
    app.include_router(inner, prefix=s.api_prefix)  # prefix lúc include (cách lõi gắn router module)
    app.add_middleware(HttpLogMiddleware, settings=s, rules=HttpLogRules.empty())
    async with asgi_client(app) as c:
        await c.get("/bizwithagents/api/mod/things/7")
    assert http_lines(bw_log)[0]["http"]["route"] == "/bizwithagents/api/mod/things/{tid}"
