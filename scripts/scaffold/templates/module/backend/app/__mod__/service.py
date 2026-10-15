"""Luật của module __mod__ dùng chung cho op và trợ lý:
đọc mục (404 khác tổ chức), dựng output kèm tên người tạo."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import or_
from sqlmodel import select

from app.auth.models import User
from app.core.errors import AppException
from app.__mod__.models import __Mod__Item
from app.__mod__.schemas import ItemOut, PersonRef


async def load(session, item_id: uuid.UUID, *, lock: bool = False) -> __Mod__Item:
    """Session đã scope theo tenant → mục của tổ chức khác coi như không có."""
    stmt = select(__Mod__Item).where(__Mod__Item.id == item_id)
    item = (await session.exec(stmt.with_for_update() if lock else stmt)).first()
    if item is None:
        raise AppException(__code1__, status_code=404)
    return item


def search(q: str) -> list:
    like = f"%{q.strip()}%"
    return [or_(__Mod__Item.title.ilike(like), __Mod__Item.description.ilike(like))]


async def outs(session, items: Sequence[__Mod__Item]) -> list[ItemOut]:
    ids = {i.created_by for i in items if i.created_by}
    users = (await session.exec(select(User).where(User.id.in_(ids)))).all() if ids else []
    names = {u.id: PersonRef(id=u.id, name=u.name or u.email.split("@", 1)[0]) for u in users}
    return [
        ItemOut(
            **i.model_dump(exclude={"created_by", "agent_run_id", "tenant_id"}),
            created_by=names.get(i.created_by) if i.created_by else None,
        )
        for i in items
    ]
