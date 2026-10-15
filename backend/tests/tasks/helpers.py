"""Dựng dữ liệu cho test Tasks: hai tổ chức, người theo role, gọi op."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlmodel import select

from app.core.connections.registry import get_connections
from app.notifications.models import Notification
from tests.auth.api import Api, Session
from tests.auth.factories import make_tenant, make_user


@dataclass
class World:
    api: Api
    admin: Session  # admin tổ chức default
    member: Session
    viewer: Session
    other: Session  # member tổ chức Acme
    acme_id: Any


async def world(api: Api) -> World:
    admin = await api.as_user("boss@x.io", roles=("admin",), name="Sếp")
    member = await api.as_user("lan@x.io", roles=("member",), name="Lan")
    viewer = await api.as_user("xem@x.io", roles=("viewer",), name="Người xem")
    async with get_connections().postgres.rw() as s:
        acme = await make_tenant(s, "Acme")
        await make_user(s, "far@acme.io", tenant_id=acme.id, roles=("member",), name="Far")
    other = await api.login("far@acme.io")
    return World(api, admin, member, viewer, other, acme.id)


async def create(api: Api, who: Session, title: str = "Gọi khách hàng", **kw: Any) -> dict:
    return await api.post("tasks.create", who, title=title, **kw)


async def notifications_of(user_id: str) -> list[Notification]:
    async with get_connections().postgres.ro() as s:
        stmt = select(Notification).where(Notification.user_id == user_id).order_by(Notification.created_at)
        return list((await s.exec(stmt)).all())
