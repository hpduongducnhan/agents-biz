"""Logging lõi: một logger `bw`, cid + proc + miền trên mọi dòng, JSON hoặc text."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

from app.core.cid import get_cid
from app.core.redact import redact_text
from app.core.settings import Settings, get_settings

LOGGER_NAME = "bw"
# Tiền tố mã `loc` theo miền — test luật kiểm mọi mã thuộc tập này
LOG_PREFIXES: dict[str, frozenset[str]] = {
    "core": frozenset({"boot", "http", "hout", "bus", "tq", "ws", "db", "sys", "exc"}),
    "auth": frozenset({"auth"}),
    "agent": frozenset({"agt"}),
    "observability": frozenset({"obs"}),
    "notifications": frozenset({"ntf"}),
    "credentials": frozenset({"cred"}),
    "mail": frozenset({"mail"}),
    "tenants": frozenset({"tnt"}),
    "tasks": frozenset({"tsk"}),
}
CORE_LOG_PREFIXES = LOG_PREFIXES["core"]
ALL_LOG_PREFIXES = frozenset().union(*LOG_PREFIXES.values())
NOISY_LIB_LOGGERS = (
    "httpx",
    "httpx2",
    "httpcore",
    "sqlalchemy.engine",
    "pymongo",
    "redis",
    "faststream",
    "aio_pika",
    "aiormq",
    "uvicorn.access",
    "asyncio",
)

_state = {"proc": "-", "redaction": False}
_STD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime"}
_OWN_ATTRS = frozenset({"proc", "cid", "loc", "bw_module"})


def module_of(name: str) -> str:
    """`app.<miền>.…` → `<miền>` (vd `app.tasks.service` → `tasks`); `app.core…`, `app.main`, còn lại → `core`."""
    parts = name.split(".")
    if len(parts) >= 3 and parts[0] == "app" and parts[1] != "core":
        return parts[1]
    return "core"


class AppLogger(logging.LoggerAdapter):
    """Adapter gắn sẵn `bw_module`, GỘP `extra` của lời gọi (mặc định LoggerAdapter đè mất)."""

    def process(self, msg, kwargs):
        merged = dict(self.extra or {})
        merged.update(kwargs.get("extra") or {})
        kwargs["extra"] = merged
        return msg, kwargs


def get_logger(name: str) -> AppLogger:
    return AppLogger(logging.getLogger(LOGGER_NAME), {"bw_module": module_of(name)})


class CidFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.cid = get_cid() or "-"
        record.proc = _state["proc"]
        return True


def _module(record: logging.LogRecord) -> str:
    return getattr(record, "bw_module", None) or ("core" if record.name == LOGGER_NAME else record.name)


def _extras(record: logging.LogRecord) -> dict:
    return {k: v for k, v in record.__dict__.items() if k not in _STD_ATTRS and k not in _OWN_ATTRS}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S")
        data = {
            "ts": f"{ts}.{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "proc": getattr(record, "proc", "-"),
            "module": _module(record),
            "loc": getattr(record, "loc", None) or "-",
            "cid": getattr(record, "cid", "-"),
            "msg": record.getMessage(),
        }
        data.update(_extras(record))
        if record.exc_info:
            data["exc"] = redact_text(self.formatException(record.exc_info))
        try:
            return json.dumps(data, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001 — Rule B12 miễn trừ: đang ở TRONG formatter, log ở đây sẽ đệ quy
            return json.dumps({k: str(v) for k, v in data.items()}, ensure_ascii=False)


def _short(value) -> str:
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        parts = [
            f"{ts}.{int(record.msecs):03d}",
            f"{record.levelname:<7}",
            getattr(record, "proc", "-"),
            f"cid={getattr(record, 'cid', '-')}",
        ]
        loc = getattr(record, "loc", None)
        if loc:
            parts.append(f"[{loc}]")
        parts.append(record.getMessage())
        extras = _extras(record)
        if extras:
            parts.append(" ".join(f"{k}={_short(v)}" for k, v in extras.items()))
        line = " ".join(parts)
        if record.exc_info:
            line = f"{line}\n{redact_text(self.formatException(record.exc_info))}"
        return line


def install_redaction() -> None:
    """Bọc LogRecord factory: che msg + args lúc TẠO record — chạy trước mọi handler. Args không phải str (vd exception)
    thì dựng sẵn message rồi che, vì `str(arg)` có thể chứa bí mật."""
    if _state["redaction"]:
        return
    original = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = original(*args, **kwargs)
        if isinstance(record.args, tuple) and all(isinstance(a, str) for a in record.args):
            record.args = tuple(redact_text(a) for a in record.args)
        elif record.args:
            try:
                record.msg, record.args = record.getMessage(), ()
            except (TypeError, ValueError):
                pass  # format sai → để logging tự báo lúc emit như bình thường
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)
        return record

    logging.setLogRecordFactory(factory)
    _state["redaction"] = True


def configure_logging(proc: str, settings: Settings | None = None) -> None:
    """Gọi 1 lần khi process khởi động. Gọi lại thì thay handler, không nhân đôi."""
    s = settings or get_settings()
    _state["proc"] = proc
    install_redaction()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if s.LOG_JSON else TextFormatter())
    handler.addFilter(CidFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(s.LOG_LIB_LEVEL.upper())
    bd = logging.getLogger(LOGGER_NAME)
    bd.setLevel(s.LOG_LEVEL.upper())
    bd.propagate = True
    for name in NOISY_LIB_LOGGERS:
        logging.getLogger(name).setLevel(s.LOG_LIB_LEVEL.upper())
