"""Tiện ích nhỏ dùng chung của messaging."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_iso() -> str:
    """ISO-8601 UTC, mili-giây, hậu tố Z — cùng dạng `ts` của log và envelope."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
