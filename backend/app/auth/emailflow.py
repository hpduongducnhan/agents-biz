"""Thư của luồng auth (D14): xác thực email, đặt lại mật khẩu — tạo token một lần, dựng link, gửi sau commit."""

from __future__ import annotations

from datetime import timedelta

from app.auth import onetime
from app.auth.models import User
from app.core.operations.context import OpContext
from app.mail.links import app_link
from app.mail.service import queue_mail


async def send_verify(ctx: OpContext, user: User) -> None:
    s = ctx.settings
    await onetime.revoke_for_user(ctx.session, user.id, "verify")
    raw, _ = await onetime.issue(
        ctx.session,
        purpose="verify",
        ttl=timedelta(hours=s.AUTH_VERIFY_TOKEN_HOURS),
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
    )
    link = app_link(s, "/verify-email", token=raw)
    to, locale, name = user.email, user.locale, user.name

    async def send() -> None:
        await queue_mail(
            to, "verify_email", locale, name=name, app_name=s.PROJECT_NAME, hours=s.AUTH_VERIFY_TOKEN_HOURS, link=link
        )

    ctx.after_commit(send)


async def send_reset(ctx: OpContext, user: User) -> None:
    s = ctx.settings
    await onetime.revoke_for_user(ctx.session, user.id, "reset")
    raw, _ = await onetime.issue(
        ctx.session,
        purpose="reset",
        ttl=timedelta(minutes=s.AUTH_RESET_TOKEN_MINUTES),
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
    )
    link = app_link(s, "/reset-password", token=raw)
    to, locale, name = user.email, user.locale, user.name

    async def send() -> None:
        await queue_mail(
            to,
            "reset_password",
            locale,
            name=name,
            app_name=s.PROJECT_NAME,
            minutes=s.AUTH_RESET_TOKEN_MINUTES,
            link=link,
        )

    ctx.after_commit(send)
