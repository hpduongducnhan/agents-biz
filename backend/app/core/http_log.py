"""Middleware ASGI thuần: gắn cid cho mỗi request, echo header, ghi 1 dòng log khi xong.

ASGI thuần (không BaseHTTPMiddleware) để không phá streaming / SSE và đọc body mà
handler vẫn nhận đủ.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.cid import CID_HEADER, set_cid
from app.core.http_rules import HttpLogRule, HttpLogRules
from app.core.logging import get_logger
from app.core.redact import build_keys, is_text_content, redact_headers, redact_url, render_body
from app.core.settings import Settings

logger = get_logger(__name__)
_CID_KEY = CID_HEADER.lower().encode()


@dataclass
class _Exchange:
    status: int | None = None
    resp_headers: list[tuple[bytes, bytes]] = field(default_factory=list)
    resp_type: str = ""
    req_bytes: int = 0
    resp_bytes: int = 0
    req_body: bytearray = field(default_factory=bytearray)
    resp_body: bytearray = field(default_factory=bytearray)


def _with_cid(message: Message, cid: str) -> Message:
    headers = [h for h in message.get("headers", []) if h[0].lower() != _CID_KEY]
    headers.append((_CID_KEY, cid.encode()))
    return {**message, "headers": headers}


def _route_template(scope: Scope) -> str:
    """Template route ĐẦY ĐỦ. FastAPI ≥ 0.141 gắn router lười: `scope["route"].path` thiếu prefix lúc
    include, bản đầy đủ nằm ở `scope["fastapi"]["effective_route_context"].path`."""
    effective = (scope.get("fastapi") or {}).get("effective_route_context")
    return getattr(effective, "path", None) or getattr(scope.get("route"), "path", None) or scope.get("path", "")


class HttpLogMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        settings: Settings,
        rules: HttpLogRules,
        enabled: bool = True,
        resolve_module: Callable[[str], str] | None = None,
    ) -> None:
        self.app = app
        self.rules = rules
        self.enabled = enabled
        self.keys = build_keys(settings.extra_redact_keys)
        self.slow_ms = settings.LOG_HTTP_SLOW_MS
        p = settings.api_prefix
        self.skip = (f"{p}/health", f"{p}/docs", f"{p}/openapi.json")
        self.resolve_module = resolve_module or (lambda _path: "core")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        cid = set_cid(headers.get(CID_HEADER.lower()))
        scope.setdefault("state", {})
        path = scope.get("path", "")

        if not self.enabled or path.startswith(self.skip):

            async def send_cid(message: Message) -> None:
                await send(_with_cid(message, cid) if message["type"] == "http.response.start" else message)

            await self.app(scope, receive, send_cid)
            return

        rule = self.rules.inbound_for(path)
        limit = self.rules.max_body + 1
        capture_req = rule.req_body and is_text_content(headers.get("content-type"))
        ex = _Exchange()

        async def recv() -> Message:
            message = await receive()
            if message["type"] == "http.request":
                chunk = message.get("body", b"")
                ex.req_bytes += len(chunk)
                if capture_req and len(ex.req_body) < limit:
                    ex.req_body.extend(chunk[: limit - len(ex.req_body)])
            return message

        async def snd(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = _with_cid(message, cid)
                ex.status = message["status"]
                ex.resp_headers = list(message["headers"])
                ex.resp_type = next(
                    (v.decode("latin-1") for k, v in ex.resp_headers if k.lower() == b"content-type"), ""
                )
            elif message["type"] == "http.response.body":
                chunk = message.get("body", b"")
                ex.resp_bytes += len(chunk)
                if rule.resp_body and is_text_content(ex.resp_type) and len(ex.resp_body) < limit:
                    ex.resp_body.extend(chunk[: limit - len(ex.resp_body)])
            await send(message)

        start = time.perf_counter()
        try:
            await self.app(scope, recv, snd)
        except Exception:
            ex.status = 500
            raise
        finally:
            self._safe_log(scope, headers, rule, ex, (time.perf_counter() - start) * 1000)

    def _safe_log(self, scope: Scope, headers: dict[str, str], rule: HttpLogRule, ex: _Exchange, ms: float) -> None:
        try:
            self._log(scope, headers, rule, ex, ms)
        except Exception as exc:  # noqa: BLE001 — log hỏng không được làm hỏng response
            logger.warning("không ghi được log HTTP vào: %s", exc, extra={"loc": "http0500"})

    def _log(self, scope: Scope, headers: dict[str, str], rule: HttpLogRule, ex: _Exchange, ms: float) -> None:
        status = ex.status if ex.status is not None else 499  # 499 = client đóng trước khi có response
        route = _route_template(scope)
        state = scope.get("state") or {}
        http: dict = {
            "dir": "in",
            "method": scope.get("method"),
            "route": route,
            "path": scope.get("path"),
            "status": status,
            "ms": round(ms, 1),
            "req_bytes": ex.req_bytes,
            "resp_bytes": ex.resp_bytes,
            "ip": (scope.get("client") or ("-",))[0],
            "user": state.get("user_id"),
        }
        qs = scope.get("query_string", b"").decode("latin-1")
        if qs:
            http["query"] = redact_url(f"?{qs}", self.keys).lstrip("?")
        if rule.req_headers:
            http["req_headers"] = redact_headers(headers.items())
        if rule.resp_headers:
            http["resp_headers"] = redact_headers(
                (k.decode("latin-1"), v.decode("latin-1")) for k, v in ex.resp_headers
            )
        if rule.req_body and ex.req_body:
            http["req_body"] = render_body(
                bytes(ex.req_body), headers.get("content-type"), self.keys, self.rules.max_body, ex.req_bytes
            )
        if rule.resp_body and ex.resp_body:
            http["resp_body"] = render_body(
                bytes(ex.resp_body), ex.resp_type, self.keys, self.rules.max_body, ex.resp_bytes
            )
        if status >= 500:
            level, loc = logging.ERROR, "http0001"
        elif status >= 400:
            level, loc = logging.WARNING, "http0001"
        elif ms > self.slow_ms:
            level, loc = logging.WARNING, "http0002"
        else:
            level, loc = logging.INFO, "http0001"
        logger.log(
            level,
            "%s %s %s %dms",
            http["method"],
            route,
            status,
            ms,
            extra={"loc": loc, "http": http, "bw_module": self.resolve_module(scope.get("path", ""))},
        )
