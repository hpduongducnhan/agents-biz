"""Module __mod__ trên trợ lý: toolset, dòng ngữ cảnh, chuyên gia (D15)."""

from __future__ import annotations

from pathlib import Path

from sqlmodel import func, select

from app.agent.config.seed_data import SpecialistSeed, register_specialist
from app.agent.config.toolsets import register_toolset
from app.agent.runtime.context import register_context
from app.auth.models import User
from app.__mod__.models import __Mod__Item

register_toolset("__mod__", "__title_vi__: xem, tạo, sửa, xoá")


async def _context(session, user: User) -> list[str]:
    counts = dict((await session.exec(select(__Mod__Item.status, func.count()).group_by(__Mod__Item.status))).all())
    return [f"__mod__: đang mở {counts.get('open', 0)} · xong {counts.get('done', 0)}"]


register_context("__mod__", _context, order=60, budget=1)

register_specialist(
    SpecialistSeed(
        "__mod__",
        "__title_vi__",
        "Xem, tạo, sửa, xoá __title_vi_lower__ của tổ chức",
        ("__mod__",),
        "__title_en__ of the organization: create, find, list, update, mark done, delete",
        ("tạo __title_vi_lower__ mới", "liệt kê __title_vi_lower__", "create a new __title_en_lower__ item"),
        prompt_dir=Path(__file__).resolve().parent / "prompts",
    )
)
