"""auth.* — đăng ký, đăng nhập, phiên, hồ sơ của chính mình; cài resolver JWT khi nạp."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.auth import qkeys
from app.auth.emailflow import send_verify
from app.auth.flags import auth_flags
from app.auth.identity import jwt_resolver
from app.auth.passwords import DUMMY_HASH, check_password_policy, hash_password, verify_password
from app.auth.ratelimit import hit_rate_limit
from app.auth.rbac import audience
from app.auth.sessions import TokenPair, find_refresh, issue_session, revoke_all, revoke_family, rotate_refresh
from app.auth.signin import check_can_sign_in
from app.auth.superadmins import apply_superadmin
from app.auth.users import (
    Email,
    Locale,
    MeOut,
    TimeZone,
    load_active_user,
    me_out,
    user_by_email,
)
from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.operations.context import OpContext
from app.core.operations.spec import operation
from app.core.security.principal import set_principal_resolver
from app.tenants.enroll import enroll

logger = get_logger(__name__)
set_principal_resolver(jwt_resolver)


class RegisterIn(BaseModel):
    email: Email
    password: str = Field(max_length=200)
    name: str = Field(default="", max_length=200)
    invite_token: str | None = Field(default=None, max_length=200)  # lời mời → vào đúng tenant + role (D12)
    tenant_name: str | None = Field(default=None, max_length=200)  # `signup_mode=new_tenant`: tên tenant mới


class LoginIn(BaseModel):
    email: Email
    password: str = Field(max_length=200)


class RefreshIn(BaseModel):
    refresh_token: str = Field(max_length=200)


class LogoutIn(BaseModel):
    refresh_token: str | None = Field(default=None, max_length=200)


class UpdateMeIn(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    timezone: TimeZone | None = None
    locale: Locale | None = None


class ChangePasswordIn(BaseModel):
    current_password: str = Field(default="", max_length=200)
    new_password: str = Field(max_length=200)


class AuthOut(BaseModel):
    user: MeOut
    verification_sent: bool = False  # đã gửi thư xác thực email (D14)
    tokens: TokenPair | None = None  # None khi email_verification=required và chưa xác thực


def _ip(ctx: OpContext) -> str:
    return ctx.request_ip or "-"


async def _tenant_admins(ctx: OpContext, user) -> list:
    """Người xem danh sách user của tenant `user` (op công khai — session chưa scope)."""
    return await audience(ctx.session, "user.view", tenant_id=user.tenant_id)


async def _user_list_changed(ctx: OpContext) -> None:
    ctx.invalidate((qkeys.USERS,), await audience(ctx.session, "user.view"))


@operation(
    name="auth.register",
    title="Đăng ký",
    description="Tạo tài khoản bằng email + mật khẩu. Tenant + role theo lời mời (invite_token) hoặc signup_mode: "
    "default_tenant (tenant mặc định, member) · new_tenant (tenant mới, admin) · invite_only (đóng, trừ "
    "SUPERADMIN_EMAILS); email_verification=required thì chưa cấp phiên tới khi xác thực",
    effect="write",
    public=True,
    invalidates=(qkeys.ME,),
)
async def register(ctx: OpContext, inp: RegisterIn) -> AuthOut:
    s = ctx.settings
    await hit_rate_limit(
        ctx.redis.rw, ("auth", "register", _ip(ctx)), s.AUTH_REGISTER_RATE_LIMIT, s.AUTH_REGISTER_RATE_WINDOW
    )
    check_password_policy(inp.password, s.AUTH_PASSWORD_MIN_LENGTH)
    flags = await auth_flags(ctx.session, s)
    user = await enroll(
        ctx.session,
        s,
        email=inp.email,
        name=inp.name,
        password_hash=hash_password(inp.password),
        invite_token=inp.invite_token,
        tenant_name=inp.tenant_name,
    )
    sent = flags.email_verification != "off" and user.email_verified_at is None
    if sent:
        await send_verify(ctx, user)
    tokens: TokenPair | None = None
    if not (flags.email_verification == "required" and user.email_verified_at is None and not user.is_superadmin):
        user.last_login_at = datetime.now(UTC)
        ctx.session.add(user)
        tokens = await issue_session(ctx.session, user, settings=s, ip=ctx.request_ip)
    ctx.invalidate((qkeys.USERS,), await _tenant_admins(ctx, user))
    logger.info("đăng ký user=%s tenant=%s", user.id, user.tenant_id, extra={"loc": "auth0001"})
    return AuthOut(user=await me_out(ctx.session, user), tokens=tokens, verification_sent=sent)


@operation(
    name="auth.login",
    title="Đăng nhập",
    description="Đăng nhập bằng email + mật khẩu",
    effect="write",
    public=True,
    invalidates=(qkeys.ME,),
)
async def login(ctx: OpContext, inp: LoginIn) -> AuthOut:
    s = ctx.settings
    await hit_rate_limit(ctx.redis.rw, ("auth", "login", _ip(ctx), inp.email), s.AUTH_LOGIN_RATE_LIMIT)
    user = await user_by_email(ctx.session, inp.email)
    hashed = user.password_hash if user is not None and user.password_hash else DUMMY_HASH
    ok = verify_password(inp.password, hashed)  # luôn băm một lần → thời gian không lộ email có tồn tại không
    if user is None or user.password_hash is None or not ok:
        raise AppException(2102, status_code=401)
    if not user.is_active:
        raise AppException(2103, status_code=403)
    apply_superadmin(user, s)
    await check_can_sign_in(ctx.session, s, user)
    user.last_login_at = datetime.now(UTC)
    ctx.session.add(user)
    tokens = await issue_session(ctx.session, user, settings=s, ip=ctx.request_ip)
    return AuthOut(user=await me_out(ctx.session, user), tokens=tokens)


@operation(
    name="auth.refresh",
    title="Làm mới phiên",
    description="Đổi refresh token lấy cặp token mới (xoay vòng); cờ superadmin đặt lại theo env",
    effect="write",
    public=True,
    invalidates=(qkeys.ME,),
)
async def refresh(ctx: OpContext, inp: RefreshIn) -> TokenPair:
    _, tokens = await rotate_refresh(ctx.session, inp.refresh_token, settings=ctx.settings, ip=ctx.request_ip)
    return tokens


@operation(
    name="auth.logout",
    title="Đăng xuất",
    description="Kết thúc phiên của refresh token này (cả họ xoay vòng của nó)",
    effect="write",
    public=True,
    invalidates=(qkeys.ME,),
)
async def logout(ctx: OpContext, inp: LogoutIn) -> None:
    if inp.refresh_token:
        row = await find_refresh(ctx.session, inp.refresh_token)
        if row is not None:
            await revoke_family(ctx.session, row.family_id)


@operation(
    name="auth.logout_all",
    title="Đăng xuất mọi nơi",
    description="Thu hồi mọi refresh token của tôi",
    effect="write",
    invalidates=(qkeys.ME,),
)
async def logout_all(ctx: OpContext, inp: None) -> None:
    user = await load_active_user(ctx.session, ctx.principal.user_id)
    await revoke_all(ctx.session, user.id)


@operation(name="auth.me", title="Hồ sơ của tôi", description="Tài khoản, role, quyền hệ thống của tôi")
async def me(ctx: OpContext, inp: None) -> MeOut:
    return await me_out(ctx.session, await load_active_user(ctx.session, ctx.principal.user_id))


@operation(
    name="auth.update_me",
    title="Sửa hồ sơ",
    description="Đổi tên hiển thị, múi giờ, ngôn ngữ",
    effect="write",
    invalidates=(qkeys.ME,),
)
async def update_me(ctx: OpContext, inp: UpdateMeIn) -> MeOut:
    user = await load_active_user(ctx.session, ctx.principal.user_id)
    if inp.name is not None:
        user.name = inp.name.strip() or user.name
    for field in ("timezone", "locale"):
        value = getattr(inp, field)
        if value is not None:
            setattr(user, field, value)
    ctx.session.add(user)
    await ctx.session.flush()
    if inp.name is not None:
        await _user_list_changed(ctx)
    return await me_out(ctx.session, user)


@operation(
    name="auth.change_password",
    title="Đổi mật khẩu",
    description="Đổi mật khẩu; mọi phiên cũ bị thu hồi, trả cặp token mới",
    effect="write",
    invalidates=(qkeys.ME,),
)
async def change_password(ctx: OpContext, inp: ChangePasswordIn) -> TokenPair:
    s = ctx.settings
    user = await load_active_user(ctx.session, ctx.principal.user_id)
    if user.password_hash and not verify_password(inp.current_password, user.password_hash):
        raise AppException(2106, status_code=400)
    check_password_policy(inp.new_password, s.AUTH_PASSWORD_MIN_LENGTH)
    user.password_hash = hash_password(inp.new_password)
    user.must_change_password = False
    ctx.session.add(user)
    await revoke_all(ctx.session, user.id)
    return await issue_session(ctx.session, user, settings=s, ip=ctx.request_ip)
