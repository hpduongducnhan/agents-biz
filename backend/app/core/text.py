"""Chuẩn hoá chữ dùng chung giữa các miền."""

from __future__ import annotations

import re
import unicodedata


def fold(value: str) -> str:
    """So tên: bỏ dấu tiếng Việt, chữ thường, gộp khoảng trắng — `"Ăn  Uống"` ≈ `"an uong"`."""
    raw = unicodedata.normalize("NFD", value.replace("đ", "d").replace("Đ", "D"))
    plain = "".join(ch for ch in raw if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", plain).strip().lower()
