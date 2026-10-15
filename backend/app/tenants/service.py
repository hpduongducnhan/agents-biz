"""Dịch vụ tenant: tạo (slug duy nhất), đếm user, hạn mức user, dấu khoá tenant."""

from __future__ import annotations

import re
import uuid

from sqlalchemy.exc import IntegrityError
from sqlmodel import func, select

from app.auth.models import User
from app.core.errors import AppException
from app.core.rkeys import rkey
from app.core.text import fold
from app.tenants.models import Tenant
from app.tenants.policies import read_tenant_policies

SLUG_MAX = 48


def slug_base(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", fold(name)).strip("-")[:SLUG_MAX].strip("-")
    return base or "tenant"


async def get_tenant(session, tenant_id: uuid.UUID) -> Tenant:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise AppException(2115, status_code=404)
    return tenant


async def create_tenant(session, name: str) -> Tenant:
    """Tenant mới; slug lấy từ tên (bỏ dấu), trùng thì thêm `-2`, `-3`…"""
    base = slug_base(name)
    taken = set(
        (await session.exec(select(Tenant.slug).where(Tenant.slug.like(f"{base}%")))).all()  # type: ignore[union-attr]
    )
    slug, n = base, 1
    while slug in taken:
        n += 1
        slug = f"{base}-{n}"
    tenant = Tenant(name=name.strip()[:200] or base, slug=slug)
    try:
        async with session.begin_nested():
            session.add(tenant)
            await session.flush()
    except IntegrityError:  # hai request cùng slug — thử thêm hậu tố ngẫu nhiên
        tenant = Tenant(name=tenant.name, slug=f"{base}-{uuid.uuid4().hex[:6]}")
        session.add(tenant)
        await session.flush()
    return tenant


async def active_user_count(session, tenant_id: uuid.UUID) -> int:
    stmt = select(func.count()).select_from(User).where(User.tenant_id == tenant_id, User.is_active.is_(True))
    return int((await session.exec(stmt)).one())


def user_limit(tenant: Tenant, default: int) -> int:
    """Hạn mức user hiệu lực: chính sách tenant → mặc định hệ thống; 0 = không giới hạn."""
    own = read_tenant_policies(tenant.policies, owner=f"tenant {tenant.id}").user_limit
    return default if own is None else own


async def ensure_can_join(session, tenant: Tenant, default_limit: int) -> None:
    """Tenant phải đang hoạt động và còn chỗ (`user_limit`) trước khi thêm user."""
    if tenant.status != "active":
        raise AppException(2110, status_code=403)
    limit = user_limit(tenant, default_limit)
    if limit and await active_user_count(session, tenant.id) >= limit:
        raise AppException(2111, status_code=409, data={"limit": limit})


def disabled_key(tenant_id: uuid.UUID | str) -> str:
    """Dấu tenant bị khoá (TTL = đời access token) — resolver JWT đọc để chặn token cũ."""
    return rkey("tenant", "disabled", str(tenant_id))


async def is_tenant_disabled(redis, tenant_id: uuid.UUID | str | None) -> bool:
    return tenant_id is not None and bool(await redis.exists(disabled_key(tenant_id)))
