"""tenants.* — superadmin quản tenant (D10–D12): danh sách, tạo (+ mời admin đầu tiên), sửa tên / chính sách, khoá /
mở. Op `superadmin=True` chạy không lọc tenant (runner)."""

from __future__ import annotations

import time
import uuid

from sqlalchemy import or_, update
from sqlmodel import func, select

from app.auth import qkeys as auth_qkeys
from app.auth.models import RefreshToken, User
from app.auth.rbac import TENANT_ADMIN_ROLE, role_by_name
from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.messaging.realtime import emit_to_tenant, rt_revoke
from app.core.operations.context import OpContext
from app.core.operations.pagination import Page
from app.core.operations.spec import operation
from app.tenants import qkeys
from app.tenants.invites import create_invite
from app.tenants.models import DEFAULT_TENANT_ID, Tenant
from app.tenants.ops.tenant import tenant_out
from app.tenants.policies import dump_tenant_policies
from app.tenants.schemas import (
    CreatedTenantOut,
    CreateTenantIn,
    InviteIn,
    SaveTenantIn,
    TenantIdIn,
    TenantOut,
    TenantsIn,
)
from app.tenants.service import create_tenant, disabled_key, get_tenant

logger = get_logger(__name__)
REASON = "quản trị nền tảng — chỉ superadmin trên giao diện"


def _sa(name: str, title: str, description: str, effect: str = "write"):
    return operation(name, title=title, description=description, effect=effect, superadmin=True, agent_reason=REASON,
                     invalidates=(qkeys.ALL,))  # fmt: skip


@_sa("tenants.list", "Tenant", "Superadmin: mọi tenant — tìm theo tên / slug, lọc trạng thái", effect="read")
async def list_tenants(ctx: OpContext, inp: TenantsIn) -> Page[TenantOut]:
    where = []
    if inp.q:
        like = f"%{inp.q.strip()}%"
        where.append(or_(Tenant.name.ilike(like), Tenant.slug.ilike(like)))
    if inp.status:
        where.append(Tenant.status == inp.status)
    total = (await ctx.session.exec(select(func.count()).select_from(Tenant).where(*where))).one()
    stmt = select(Tenant).where(*where).order_by(Tenant.created_at).offset(inp.offset).limit(inp.limit)
    items = [await tenant_out(ctx.session, t) for t in (await ctx.session.exec(stmt)).all()]
    return Page[TenantOut](items=items, total=total, limit=inp.limit, offset=inp.offset)


@_sa("tenants.create", "Tạo tenant", "Superadmin: tạo tenant; có admin_email thì gửi lời mời làm admin")
async def create(ctx: OpContext, inp: CreateTenantIn) -> CreatedTenantOut:
    tenant = await create_tenant(ctx.session, inp.name)
    tenant.policies = dump_tenant_policies(inp.policies)
    ctx.session.add(tenant)
    await ctx.session.flush()
    invite = None
    if inp.admin_email:
        admin_role = await role_by_name(ctx.session, TENANT_ADMIN_ROLE)
        inviter = await ctx.session.get(User, ctx.principal.user_id)
        invite = await create_invite(
            ctx, tenant, InviteIn(email=inp.admin_email, role_id=admin_role.id), inviter=inviter
        )
    ctx.emit_to_superadmins("data:changed", {"keys": [qkeys.ALL]})
    logger.info("tạo tenant %s bởi %s", tenant.slug, ctx.principal.user_id, extra={"loc": "tnt0003"})
    return CreatedTenantOut(tenant=await tenant_out(ctx.session, tenant), invite=invite)


@_sa("tenants.update", "Sửa tenant", "Superadmin: đổi tên, thay cả bộ chính sách (hạn mức user, trợ lý, chat)")
async def save(ctx: OpContext, inp: SaveTenantIn) -> TenantOut:
    tenant = await get_tenant(ctx.session, inp.tenant_id)
    if inp.name is not None:
        tenant.name = inp.name.strip()
    if inp.policies is not None:
        tenant.policies = dump_tenant_policies(inp.policies)
    ctx.session.add(tenant)
    await ctx.session.flush()
    ctx.emit_to_superadmins("data:changed", {"keys": [qkeys.ALL]})
    after_tenant_changed(ctx, tenant.id)
    return await tenant_out(ctx.session, tenant)


def after_tenant_changed(ctx: OpContext, tenant_id: uuid.UUID) -> None:
    async def send() -> None:
        keys = [qkeys.CURRENT, auth_qkeys.ME, "agent.chat_limits", "agent.agents"]  # tên, hạn mức, bật / tắt trợ lý
        await emit_to_tenant(tenant_id, "data:changed", {"keys": keys})

    ctx.after_commit(send)


async def _users_of(session, tenant_id: uuid.UUID) -> list[uuid.UUID]:
    return list((await session.exec(select(User.id).where(User.tenant_id == tenant_id))).all())


@_sa("tenants.suspend", "Khoá tenant", "Superadmin: khoá tenant — mọi user bị đăng xuất, token cũ bị từ chối (2110)")
async def suspend(ctx: OpContext, inp: TenantIdIn) -> TenantOut:
    if inp.tenant_id == DEFAULT_TENANT_ID:
        raise AppException(1003, status_code=400, detail="Không khoá tenant mặc định")
    tenant = await get_tenant(ctx.session, inp.tenant_id)
    tenant.status = "suspended"
    ctx.session.add(tenant)
    users = await _users_of(ctx.session, tenant.id)
    if users:
        await ctx.session.exec(
            update(RefreshToken).where(RefreshToken.user_id.in_(users), RefreshToken.revoked_at.is_(None))
            .values(revoked_at=func.now())
        )  # fmt: skip
    ttl = ctx.settings.AUTH_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    now = int(time.time())

    async def kick() -> None:
        await ctx.redis.rw.set(disabled_key(tenant.id), "1", ex=ttl)
        await emit_to_tenant(tenant.id, "core:account_disabled", {})
        for uid in users:
            await rt_revoke(str(uid), before=now, until=now + ttl)

    ctx.after_commit(kick)
    ctx.emit_to_superadmins("data:changed", {"keys": [qkeys.ALL]})
    logger.warning("khoá tenant %s (%d user) bởi %s", tenant.slug, len(users), ctx.principal.user_id,
                   extra={"loc": "tnt0004"})  # fmt: skip
    return await tenant_out(ctx.session, tenant)


@_sa("tenants.resume", "Mở khoá tenant", "Superadmin: mở lại tenant đã khoá — user đăng nhập lại được")
async def resume(ctx: OpContext, inp: TenantIdIn) -> TenantOut:
    tenant = await get_tenant(ctx.session, inp.tenant_id)
    tenant.status = "active"
    ctx.session.add(tenant)

    async def unmark() -> None:
        await ctx.redis.rw.delete(disabled_key(tenant.id))

    ctx.after_commit(unmark)
    ctx.emit_to_superadmins("data:changed", {"keys": [qkeys.ALL]})
    logger.info("mở khoá tenant %s bởi %s", tenant.slug, ctx.principal.user_id, extra={"loc": "tnt0005"})
    return await tenant_out(ctx.session, tenant)
