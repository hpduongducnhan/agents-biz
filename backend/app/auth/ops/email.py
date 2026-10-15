"""auth.* qua email (D14): gửi lại thư xác thực, xác thực email, quên mật khẩu, đặt lại mật khẩu — đều công khai.
Hai op gửi thư luôn trả 200 (không lộ email có tài khoản hay không) và giới hạn theo IP + email."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.auth import onetime, qkeys
from app.auth.emailflow import send_reset, send_verify
from app.auth.flags import auth_flags
from app.auth.models import User
from app.auth.passwords import check_password_policy, hash_password
from app.auth.ratelimit import hit_rate_limit
from app.auth.sessions import revoke_all
from app.auth.users import Email, user_by_email
from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.operations.context import OpContext
from app.core.operations.spec import operation

logger = get_logger(__name__)
HOUR = 3600


class EmailIn(BaseModel):
    email: Email


class TokenIn(BaseModel):
    token: str = Field(min_length=1, max_length=200)


class ResetPasswordIn(TokenIn):
    new_password: str = Field(max_length=200)


class SentOut(BaseModel):
    ok: bool = True  # luôn True — không lộ email có tài khoản hay không


async def _limit(ctx: OpContext, what: str, email: str) -> None:
    ip = ctx.request_ip or "-"
    await hit_rate_limit(ctx.redis.rw, ("auth", what, ip, email), ctx.settings.AUTH_EMAIL_RATE_LIMIT, HOUR)


@operation(
    name="auth.request_verify",
    title="Gửi lại thư xác thực",
    description="Gửi lại link xác thực email (luôn trả ok; giới hạn theo IP + email)",
    effect="write",
    public=True,
)
async def request_verify(ctx: OpContext, inp: EmailIn) -> SentOut:
    await _limit(ctx, "verify", inp.email)
    user = await user_by_email(ctx.session, inp.email)
    flags = await auth_flags(ctx.session, ctx.settings)
    if user is not None and user.is_active and user.email_verified_at is None and flags.email_verification != "off":
        await send_verify(ctx, user)
    return SentOut()


@operation(
    name="auth.verify_email",
    title="Xác thực email",
    description="Đánh dấu email đã xác thực bằng token trong link (dùng một lần)",
    effect="write",
    public=True,
)
async def verify_email(ctx: OpContext, inp: TokenIn) -> SentOut:
    row = await onetime.find_valid(ctx.session, inp.token, "verify", lock=True)
    user = await ctx.session.get(User, row.user_id) if row is not None and row.user_id else None
    if row is None or user is None or (row.email and row.email.lower() != user.email):
        raise AppException(2114, status_code=400)
    onetime.consume(ctx.session, row)
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)
        ctx.session.add(user)
    ctx.invalidate((qkeys.ME,), [user.id])
    logger.info("xác thực email user=%s", user.id, extra={"loc": "auth0701"})
    return SentOut()


@operation(
    name="auth.forgot_password",
    title="Quên mật khẩu",
    description="Gửi link đặt lại mật khẩu (luôn trả ok; giới hạn theo IP + email)",
    effect="write",
    public=True,
)
async def forgot_password(ctx: OpContext, inp: EmailIn) -> SentOut:
    await _limit(ctx, "reset", inp.email)
    user = await user_by_email(ctx.session, inp.email)
    if user is not None and user.is_active:
        await send_reset(ctx, user)
    return SentOut()


@operation(
    name="auth.reset_password",
    title="Đặt lại mật khẩu",
    description="Đặt mật khẩu mới bằng token trong link (dùng một lần); thu hồi mọi phiên đang mở",
    effect="write",
    public=True,
)
async def reset_password(ctx: OpContext, inp: ResetPasswordIn) -> SentOut:
    row = await onetime.find_valid(ctx.session, inp.token, "reset", lock=True)
    user = await ctx.session.get(User, row.user_id) if row is not None and row.user_id else None
    if row is None or user is None or not user.is_active:
        raise AppException(2114, status_code=400)
    check_password_policy(inp.new_password, ctx.settings.AUTH_PASSWORD_MIN_LENGTH)
    onetime.consume(ctx.session, row)
    user.password_hash = hash_password(inp.new_password)
    user.must_change_password = False
    user.email_verified_at = user.email_verified_at or datetime.now(UTC)  # mở được thư = sở hữu email
    ctx.session.add(user)
    await revoke_all(ctx.session, user.id)
    ctx.invalidate((qkeys.ME,), [user.id])
    logger.info("đặt lại mật khẩu user=%s", user.id, extra={"loc": "auth0702"})
    return SentOut()
