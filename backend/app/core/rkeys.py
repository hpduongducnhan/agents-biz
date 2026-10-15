"""Mọi key Redis của BizWithAgents có tiền tố `bw:` — Redis dùng chung instance với dự án khác."""

from __future__ import annotations

PREFIX = "bw:"


def rkey(*parts: str) -> str:
    """`rkey("hb", "work")` → `bw:hb:work`."""
    return PREFIX + ":".join(parts)
