"""tenant.* — tenant của người gọi (D10–D12): xem, đổi tên, mời (email / link), lời mời đang chờ, thu hồi;
invites.preview — trang nhận lời mời (công khai)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.auth import onetime
from app.auth.models import AuthToken, Role, User
from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.operations.context import OpContext
from app.core.operations.spec import operation
from app.system import settings_store
from app.tenants import qkeys
from app.tenants.invites import create_invite, invite_out, mask_email, pending_invites
from app.tenants.models import Tenant
from app.tenants.policies import read_tenant_policies
from app.tenants.schemas import (
    InviteIdIn,
    InviteIn,
    InviteOut,
    InvitePreviewOut,
    InviteTokenIn,
    TenantOut,
    UpdateTenantIn,
)
from app.tenants.service import active_user_count, get_tenant, user_limit

logger = get_logger(__name__)
AGENT_REASON = "quản trị tenant làm trên giao diện (trang Tổ chức)"


async def tenant_out(session, tenant: Tenant) -> TenantOut:
    default_limit = (await settings_store.get_system_settings(session)).user_limit_default
    return TenantOut(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        status=tenant.status,
        policies=read_tenant_policies(tenant.policies, owner=f"tenant {tenant.id}"),
        user_count=await active_user_count(session, tenant.id),
        user_limit=user_limit(tenant, default_limit),
        created_at=tenant.created_at,
    )


async def _mine(ctx: OpContext, *, lock: bool = False) -> Tenant:
    if ctx.tenant_id is None:
        raise AppException(2115, status_code=404)
    if lock:
        tenant = await ctx.session.get(Tenant, ctx.tenant_id, with_for_update=True)
        if tenant is None:
            raise AppException(2115, status_code=404)
        return tenant
    return await get_tenant(ctx.session, ctx.tenant_id)


@operation("tenant.get", title="Tổ chức của tôi", description="Tên, trạng thái, số user / hạn mức của tenant")
async def get_mine(ctx: OpContext, inp: None) -> TenantOut:
    return await tenant_out(ctx.session, await _mine(ctx))


@operation(
    "tenant.update",
    title="Đổi tên tổ chức",
    description="Đổi tên tenant của tôi",
    effect="write",
    permission="tenant.settings",
    agent_reason=AGENT_REASON,
    invalidates=(qkeys.CURRENT,),
)
async def update_mine(ctx: OpContext, inp: UpdateTenantIn) -> TenantOut:
    tenant = await _mine(ctx, lock=True)
    tenant.name = inp.name.strip()
    ctx.session.add(tenant)
    await ctx.session.flush()
    ctx.invalidate((qkeys.CURRENT,), tenant=True)
    return await tenant_out(ctx.session, tenant)


@operation(
    "tenant.invite",
    title="Mời vào tổ chức",
    description="Mời theo email (gửi thư, dùng 1 lần) hoặc tạo link dùng chung; chọn role, hạn, số lần dùng",
    effect="write",
    permission="tenant.invite",
    agent_reason=AGENT_REASON,
    invalidates=(qkeys.INVITES,),
)
async def invite(ctx: OpContext, inp: InviteIn) -> InviteOut:
    tenant = await _mine(ctx)
    inviter = await ctx.session.get(User, ctx.principal.user_id)
    system = await settings_store.get_system_settings(ctx.session)
    if (
        system.email_verification != "off"
        and inviter is not None
        and inviter.email_verified_at is None
        and not ctx.principal.sup
    ):
        raise AppException(2112, status_code=403)
    out = await create_invite(ctx, tenant, inp, inviter=inviter)
    ctx.invalidate((qkeys.INVITES,), tenant=True)
    logger.info("mời vào tenant %s (%s) bởi %s", tenant.slug, "email" if inp.email else "link", ctx.principal.user_id,
                extra={"loc": "tnt0002"})  # fmt: skip
    return out


@operation(
    "tenant.list_invites",
    title="Lời mời đang chờ",
    description="Lời mời còn hạn, còn lượt của tenant",
    permission="tenant.invite",
)
async def list_invites(ctx: OpContext, inp: None) -> list[InviteOut]:
    rows = await pending_invites(ctx.session, (await _mine(ctx)).id)
    roles = {r.id: r for r in [await ctx.session.get(Role, x.role_id) for x in rows if x.role_id] if r}
    return [invite_out(r, roles.get(r.role_id)) for r in rows]


@operation(
    "tenant.revoke_invite",
    title="Thu hồi lời mời",
    description="Link / thư mời hết hiệu lực ngay",
    effect="write",
    permission="tenant.invite",
    agent_reason=AGENT_REASON,
    invalidates=(qkeys.INVITES,),
)
async def revoke_invite(ctx: OpContext, inp: InviteIdIn) -> None:
    row = await ctx.session.get(AuthToken, inp.invite_id, with_for_update=True)
    if row is None or row.purpose != "invite" or row.tenant_id != ctx.tenant_id:
        raise AppException(1001, status_code=404, detail="Invite not found")
    row.revoked_at = row.revoked_at or datetime.now(UTC)
    ctx.session.add(row)
    ctx.invalidate((qkeys.INVITES,), tenant=True)


@operation(
    "invites.preview",
    title="Xem lời mời",
    description="Công khai: tổ chức, role, hạn của một link mời (email gắn đã che)",
    public=True,
)
async def preview(ctx: OpContext, inp: InviteTokenIn) -> InvitePreviewOut:
    row = await onetime.find_valid(ctx.session, inp.token, "invite")
    tenant = await ctx.session.get(Tenant, row.tenant_id) if row is not None and row.tenant_id else None
    if row is None or tenant is None or tenant.status != "active":
        raise AppException(2114, status_code=400)
    role = await ctx.session.get(Role, row.role_id) if row.role_id else None
    return InvitePreviewOut(
        tenant_name=tenant.name,
        role_name=role.name if role else "member",
        email=mask_email(row.email),
        expires_at=row.expires_at,
    )
