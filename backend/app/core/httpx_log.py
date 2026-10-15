"""Vá `send` của httpx2 / httpx để ghi log mọi lời gọi HTTP ra ngoài (kể cả SDK bên thứ ba)."""

from __future__ import annotations

import functools
import importlib
import json
import logging
import time
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from types import ModuleType

from app.core.cid import CID_HEADER, get_cid
from app.core.http_rules import HttpLogRule, HttpLogRules
from app.core.logging import get_logger
from app.core.redact import DEFAULT_REDACT_KEYS, redact_headers, redact_mapping, redact_url, render_body

logger = get_logger(__name__)
LIBS = ("httpx2", "httpx")
_originals: dict[tuple[str, str], object] = {}
_config: dict = {"rules": HttpLogRules.empty(), "keys": frozenset()}
CAPTURE_MAX_BYTES = 15 * 1024 * 1024  # trần document Mongo 16 MB — body lớn hơn bị cắt (cờ truncated)
_capture: ContextVar[Callable[[dict], None] | None] = ContextVar("bw_http_capture", default=None)


@contextmanager
def http_capture(sink: Callable[[dict], None]):
    """Trong khối này, mỗi request httpx / httpx2 gửi đúng một bản ghi đầy đủ (đã che) cho `sink`:
    response thường khi nhận xong, response stream khi đóng, lỗi mạng khi ném — dùng cho raw HTTP của trace."""
    token = _capture.set(sink)
    try:
        yield
    finally:
        _capture.reset(token)


def install_httpx_logging(rules: HttpLogRules, keys: frozenset[str], *, log: bool = True) -> list[str]:
    """Vá `send` của httpx2 / httpx: log HTTP ra (khi `log`) + `http_capture` (luôn). Cài ở mọi process."""
    _config["rules"] = rules
    _config["keys"] = keys
    _config["log"] = log
    patched = []
    for name in LIBS:
        try:
            mod = importlib.import_module(name)
        except ImportError:
            continue  # lib không có trong môi trường → không có gì để vá
        _patch(mod, "AsyncClient", is_async=True)
        _patch(mod, "Client", is_async=False)
        patched.append(name)
    return patched


def uninstall_httpx_logging() -> None:
    for (modname, clsname), original in list(_originals.items()):
        getattr(importlib.import_module(modname), clsname).send = original
    _originals.clear()


def _patch(mod: ModuleType, clsname: str, *, is_async: bool) -> None:
    cls = getattr(mod, clsname)
    if getattr(cls.send, "_bw_patched", False):
        return
    original = cls.send

    if is_async:

        @functools.wraps(original)
        async def send(self, request, *args, **kwargs):
            rule, start = _before(request)
            sink, started = _capture.get(), datetime.now(UTC)
            try:
                response = await original(self, request, *args, **kwargs)
            except Exception as exc:
                _log_failure(mod, request, start, exc)
                if sink is not None:
                    _emit(sink, _record(mod, request, None, None, started, start, exc))
                raise
            stream = bool(kwargs.get("stream", False))
            _safe_log_response(mod, request, response, start, rule, stream)
            if sink is not None:
                _attach_capture(mod, sink, request, response, started, start, stream, is_async=True)
            return response

    else:

        @functools.wraps(original)
        def send(self, request, *args, **kwargs):
            rule, start = _before(request)
            sink, started = _capture.get(), datetime.now(UTC)
            try:
                response = original(self, request, *args, **kwargs)
            except Exception as exc:
                _log_failure(mod, request, start, exc)
                if sink is not None:
                    _emit(sink, _record(mod, request, None, None, started, start, exc))
                raise
            stream = bool(kwargs.get("stream", False))
            _safe_log_response(mod, request, response, start, rule, stream)
            if sink is not None:
                _attach_capture(mod, sink, request, response, started, start, stream, is_async=False)
            return response

    send._bw_patched = True
    _originals[(mod.__name__, clsname)] = original
    cls.send = send


def _before(request) -> tuple[HttpLogRule, float]:
    rule = _config["rules"].outbound_for(str(request.url).split("?", 1)[0])
    cid = get_cid()
    if rule.propagate_cid and cid:
        request.headers[CID_HEADER] = cid
    return rule, time.perf_counter()


def _request_body(mod: ModuleType, request) -> bytes | None:
    try:
        return request.content
    except mod.RequestNotRead:
        return None  # body dạng stream chưa đọc — không đụng vào


def _safe_log_response(mod: ModuleType, request, response, start: float, rule: HttpLogRule, stream: bool) -> None:
    if not _config.get("log", True):
        return
    try:
        _log_response(mod, request, response, start, rule, stream)
    except Exception as exc:  # noqa: BLE001 — log hỏng không được làm hỏng lời gọi HTTP đã thành công
        logger.warning("không ghi được log HTTP ra %s: %s", request.method, exc, extra={"loc": "hout0501"})


def _log_response(mod: ModuleType, request, response, start: float, rule: HttpLogRule, stream: bool) -> None:
    keys = _config["keys"]
    max_body = _config["rules"].max_body
    ms = (time.perf_counter() - start) * 1000
    status = response.status_code
    body = _request_body(mod, request)
    http: dict = {
        "dir": "out",
        "lib": mod.__name__,
        "method": request.method,
        "url": redact_url(str(request.url), keys),
        "status": status,
        "ms": round(ms, 1),
        "req_bytes": len(body) if body is not None else None,
    }
    if not stream:
        http["resp_bytes"] = len(response.content)
    if rule.req_headers:
        http["req_headers"] = redact_headers(request.headers.multi_items())
    if rule.req_body and body:
        http["req_body"] = render_body(body, request.headers.get("content-type"), keys, max_body)
    if rule.resp_headers:
        http["resp_headers"] = redact_headers(response.headers.multi_items())
    if rule.resp_body and not stream:
        http["resp_body"] = render_body(response.content, response.headers.get("content-type"), keys, max_body)
    level = logging.ERROR if status >= 500 else logging.WARNING if status >= 400 else logging.INFO
    logger.log(
        level, "→ %s %s %s %dms", request.method, http["url"], status, ms, extra={"loc": "hout0001", "http": http}
    )


def _log_failure(mod: ModuleType, request, start: float, exc: Exception) -> None:
    if not _config.get("log", True):
        return
    url = redact_url(str(request.url), _config["keys"])
    ms = (time.perf_counter() - start) * 1000
    logger.warning(
        "→ %s %s lỗi %s: %s",
        request.method,
        url,
        type(exc).__name__,
        exc,
        extra={
            "loc": "hout0500",
            "http": {
                "dir": "out",
                "lib": mod.__name__,
                "method": request.method,
                "url": url,
                "ms": round(ms, 1),
                "error": type(exc).__name__,
            },
        },
    )


# ── bắt HTTP theo ngữ cảnh (http_capture — raw HTTP cho trace agent) ──


def _capture_keys() -> frozenset[str]:
    return DEFAULT_REDACT_KEYS | _config["keys"]


def _capture_body(raw: bytes | None, content_type: str | None) -> tuple[str | None, bool]:
    if not raw:
        return None, False
    truncated = len(raw) > CAPTURE_MAX_BYTES
    raw = raw[:CAPTURE_MAX_BYTES]
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    if not truncated and (ct == "application/json" or ct.endswith("+json")):
        try:
            return json.dumps(redact_mapping(json.loads(raw), _capture_keys()), ensure_ascii=False), False
        except ValueError:
            pass  # JSON hỏng → giữ nguyên văn bên dưới
    textual = not ct or ct.startswith("text/") or ct.endswith(("json", "xml")) or ct == "application/x-ndjson"
    if not textual:
        return f"<binary {len(raw)} bytes>", truncated
    return raw.decode("utf-8", "replace"), truncated


def _record(mod: ModuleType, request, response, raw: bytes | None, started: datetime, start: float, error) -> dict:
    keys = _capture_keys()
    req_raw = _request_body(mod, request)
    req_body, req_cut = _capture_body(req_raw, request.headers.get("content-type"))
    out: dict = {
        "method": request.method,
        "url": redact_url(str(request.url), keys),
        "started_at": started.isoformat(),
        "ms": round((time.perf_counter() - start) * 1000, 1),
        "request": {
            "headers": redact_headers(request.headers.multi_items()),
            "body": req_body,
            "bytes": len(req_raw) if req_raw is not None else None,
            "truncated": req_cut,
        },
        "response": None,
        "error": f"{type(error).__name__}: {error}" if error is not None else None,
    }
    if response is not None:
        body, cut = _capture_body(raw, response.headers.get("content-type"))
        out["response"] = {
            "status": response.status_code,
            "headers": redact_headers(response.headers.multi_items()),
            "body": body,
            "bytes": len(raw or b""),
            "truncated": cut,
        }
    return out


def _emit(sink: Callable[[dict], None], record: dict) -> None:
    try:
        sink(record)
    except Exception as exc:  # noqa: BLE001 — sink hỏng không được làm hỏng lời gọi HTTP
        logger.warning("sink http_capture lỗi: %s", exc, extra={"loc": "hout0502"})


class _AsyncTee:
    """Bọc stream của response: gom byte đã đọc, phát bản ghi đúng một lần khi đóng (kể cả đóng sớm)."""

    def __init__(self, inner, done: Callable[[bytes], None]) -> None:
        self._inner, self._done, self._buf, self._fired = inner, done, bytearray(), False

    def _keep(self, chunk: bytes) -> None:
        if len(self._buf) <= CAPTURE_MAX_BYTES:
            self._buf.extend(chunk)

    def _fire(self) -> None:
        if not self._fired:
            self._fired = True
            self._done(bytes(self._buf))

    async def __aiter__(self):
        async for chunk in self._inner:
            self._keep(chunk)
            yield chunk

    async def aclose(self) -> None:
        try:
            await self._inner.aclose()
        finally:
            self._fire()


class _SyncTee(_AsyncTee):
    def __iter__(self):
        for chunk in self._inner:
            self._keep(chunk)
            yield chunk

    def close(self) -> None:
        try:
            self._inner.close()
        finally:
            self._fire()


_tee_classes: dict[tuple[str, bool], type] = {}


def _tee_class(mod: ModuleType, is_async: bool) -> type:
    """httpx kiểm `isinstance(stream, AsyncByteStream)` khi đọc → lớp bọc phải là lớp con theo đúng thư viện."""
    key = (mod.__name__, is_async)
    if key not in _tee_classes:
        base = mod.AsyncByteStream if is_async else mod.SyncByteStream
        mixin = _AsyncTee if is_async else _SyncTee
        _tee_classes[key] = type(f"_{'Async' if is_async else 'Sync'}CaptureTee", (mixin, base), {})
    return _tee_classes[key]


def _already_read(mod: ModuleType, response) -> bool:
    try:
        response.content  # noqa: B018 — chỉ để biết body đã đọc sẵn chưa
    except mod.ResponseNotRead:
        return False
    return True


def _attach_capture(mod, sink, request, response, started, start, stream: bool, *, is_async: bool) -> None:
    try:
        if not stream or getattr(response, "is_stream_consumed", False) or _already_read(mod, response):
            _emit(sink, _record(mod, request, response, response.content, started, start, None))
            return

        def done(raw: bytes) -> None:
            _emit(sink, _record(mod, request, response, raw, started, start, None))

        response.stream = _tee_class(mod, is_async)(response.stream, done)
    except Exception as exc:  # noqa: BLE001 — bắt hỏng không được làm hỏng lời gọi HTTP
        logger.warning("không gắn được http_capture: %s", exc, extra={"loc": "hout0503"})
