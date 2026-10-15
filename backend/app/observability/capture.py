"""Chụp lỗi hệ thống thành issue: fingerprint ổn định + traceback đã che + mẫu có kiểu."""

from __future__ import annotations

import hashlib
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.encoders import jsonable_encoder

import app
from app.core.redact import redact_mapping, redact_text
from app.observability.schemas import IssueSample

APP_DIR = Path(app.__file__).resolve().parent
TRACEBACK_LIMIT = 20_000  # byte
TITLE_LIMIT = 200
_CUT = "…(đã cắt phần đầu)…\n"


def exc_type_name(exc: BaseException) -> str:
    kind = type(exc)
    return kind.__qualname__ if kind.__module__ == "builtins" else f"{kind.__module__}.{kind.__qualname__}"


def first_app_frame(exc: BaseException) -> str:
    """Frame thuộc `app/` gần chỗ ném nhất, dạng `<đường dẫn trong app>:<hàm>` (không số dòng); không có → ""."""
    found = ""
    for frame in traceback.extract_tb(exc.__traceback__):
        path = Path(frame.filename).resolve()
        if path.is_relative_to(APP_DIR):
            found = f"{path.relative_to(APP_DIR).as_posix()}:{frame.name}"
    return found


def fingerprint(exc: BaseException, loc: str | None) -> str:
    raw = f"{exc_type_name(exc)}|{first_app_frame(exc)}|{loc or ''}"
    return hashlib.sha1(raw.encode()).hexdigest()


def redacted_traceback(exc: BaseException) -> str:
    """Traceback đã che bí mật; quá 20 KB thì giữ phần cuối (gần chỗ ném nhất)."""
    text = redact_text("".join(traceback.format_exception(exc)))
    data = text.encode()
    if len(data) <= TRACEBACK_LIMIT:
        return text
    keep = TRACEBACK_LIMIT - len(_CUT.encode())
    return _CUT + data[-keep:].decode(errors="ignore")


def title_of(exc: BaseException) -> str:
    lines = redact_text(str(exc)).strip().splitlines()
    title = f"{type(exc).__name__}: {lines[0]}" if lines else type(exc).__name__
    return title[:TITLE_LIMIT]


@dataclass(frozen=True)
class IssueEvent:
    fingerprint: str
    title: str
    exc_type: str
    loc: str | None
    source: str
    ts: datetime
    cid: str | None
    sample: IssueSample


def issue_event(
    exc: BaseException, *, source: str, loc: str | None, cid: str | None, context: dict[str, Any], keys: frozenset[str]
) -> IssueEvent:
    """Chụp NGAY lúc bắt (traceback còn nguyên); phần ghi Mongo để task nền làm."""
    ctx = redact_mapping(jsonable_encoder(context or {}), keys)
    sample = IssueSample(
        cid=cid,
        source=source,
        operation=ctx.pop("operation", None),
        path=ctx.pop("path", None),
        user_id=ctx.pop("user_id", None),
        context=ctx,
        traceback=redacted_traceback(exc),
    )
    return IssueEvent(
        fingerprint(exc, loc), title_of(exc), exc_type_name(exc), loc, source, datetime.now(UTC), cid, sample
    )
