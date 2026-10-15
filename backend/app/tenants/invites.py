"""Lời mời vào tenant: tạo (email → thư, link → trả token một lần), đọc, che email, gửi thư."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel import select

from app.auth import onetime
from app.auth.models import AuthToken, Role, User
from app.auth.users import RoleRef, user_by_email
from app.core.errors import AppException
from app.core.operations.context import OpContext
from app.mail.links import app_link
from app.mail.service import queue_mail
from app.tenants.models import Tenant
from app.tenants.schemas import InviteIn, InviteOut

LINK_MAX_USES = 20


def mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return email
    local, _, domain = email.partition("@")
    name, _, tld = domain.rpartition(".")
    return f"{local[:1]}***@{(name or domain)[:1]}***{('.' + tld) if name else ''}"


def invite_out(row: AuthToken, role: Role | None, link: str | None = None) -> InviteOut:
    return InviteOut(
        id=row.id,
        email=row.email,
        role=RoleRef(id=role.id, name=role.name) if role else None,
        max_uses=row.max_uses,
        uses=row.uses,
        expires_at=row.expires_at,
        created_at=row.created_at,
        link=link,
    )


async def pending_invites(session, tenant_id: uuid.UUID) -> list[AuthToken]:
    stmt = (
        select(AuthToken)
        .where(
            AuthToken.purpose == "invite",
            AuthToken.tenant_id == tenant_id,
            AuthToken.revoked_at.is_(None),
            AuthToken.expires_at > datetime.now(UTC),
            AuthToken.uses < AuthToken.max_uses,
        )
        .order_by(AuthToken.created_at.desc())
    )
    return list((await session.exec(stmt)).all())


async def create_invite(ctx: OpContext, tenant: Tenant, inp: InviteIn, *, inviter: User | None) -> InviteOut:
    role = await ctx.session.get(Role, inp.role_id) if inp.role_id else None
    if inp.role_id and role is None:
        raise AppException(1001, status_code=404, detail="Role not found")
    if inp.email:
        if await user_by_email(ctx.session, inp.email) is not None:
            raise AppException(2109, status_code=409)
        for old in await pending_invites(ctx.session, tenant.id):  # mời lại cùng email → link cũ hết hiệu lực
            if old.email and old.email.lower() == inp.email:
                old.revoked_at = datetime.now(UTC)
                ctx.session.add(old)
    raw, row = await onetime.issue(
        ctx.session,
        purpose="invite",
        ttl=timedelta(days=inp.days),
        tenant_id=tenant.id,
        email=inp.email,
        role_id=role.id if role else None,
        max_uses=inp.max_uses or (1 if inp.email else LINK_MAX_USES),
        created_by=inviter.id if inviter else None,
    )
    link = app_link(ctx.settings, f"/invite/{raw}")
    if inp.email:
        to, locale = inp.email, inviter.locale if inviter else "vi"
        ctx_mail = {
            "inviter": (inviter.name or inviter.email) if inviter else ctx.settings.PROJECT_NAME,
            "tenant": tenant.name,
            "role": role.name if role else "member",
            "days": inp.days,
            "link": link,
            "app_name": ctx.settings.PROJECT_NAME,
        }

        async def send() -> None:
            await queue_mail(to, "invite", locale, **ctx_mail)

        ctx.after_commit(send)
    return invite_out(row, role, link)
