"""Múi giờ: tên IANA hợp lệ → ZoneInfo, tên hỏng / trống → UTC."""

from zoneinfo import ZoneInfo

import pytest

from app.core.dates import zone


def test_zone_returns_named_zone():
    assert zone("Asia/Ho_Chi_Minh") == ZoneInfo("Asia/Ho_Chi_Minh")


@pytest.mark.parametrize("name", [None, "", "Mars/Base", "../etc"])
def test_zone_falls_back_to_utc(name):
    assert zone(name) == ZoneInfo("UTC")
