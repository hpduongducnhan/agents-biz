"""Múi giờ: tên IANA → ZoneInfo, tên hỏng / trống → UTC (không làm hỏng request)."""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")
