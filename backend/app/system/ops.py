"""system.* — cài đặt hệ thống (superadmin), thông tin công khai cho trang đăng nhập, trạng thái hệ thống."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.auth.flags import auth_flags, google_missing
from app.auth.rbac import audience
from app.core.operations.context import OpContext
from app.core.operations.spec import operation
from app.system.settings_store import SettingsSnapshot, SystemSettings, settings_snapshot, update_system_settings
from app.system.status import StatusOut, collect_status

INVALIDATES = ("system",)
CHAT_LIMITS_KEY = "agent.chat_limits"


class UpdateSettingsIn(BaseModel):
    signup_mode: Literal["default_tenant", "new_tenant", "invite_only"] | None = None
    email_verification: Literal["off", "soft", "required"] | None = None
    user_limit_default: int | None = Field(default=None, ge=0, le=1_000_000)
    google_enabled: bool | None = None
    event_log_ttl_days: int | None = Field(default=None, ge=1, le=3650)
    span_ttl_days: int | None = Field(default=None, ge=1, le=3650)
    raw_http_ttl_days: int | None = Field(default=None, ge=1, le=365)
    chat_session_idle_min: int | None = Field(default=None, ge=1, le=1440)
    chat_history_limit: int | None = Field(default=None, ge=1, le=100)
    chat_history_tools: bool | None = None
    chat_stream: bool | None = None
    chat_stream_flush_ms: int | None = Field(default=None, ge=20, le=1000)
    chat_per_minute: int | None = Field(default=None, ge=0, le=100_000)
    chat_per_hour: int | None = Field(default=None, ge=0, le=100_000)
    chat_per_day: int | None = Field(default=None, ge=0, le=100_000)
    chat_autoblock: bool | None = None
    chat_autoblock_strikes: int | None = Field(default=None, ge=1, le=100)
    chat_autoblock_window_min: int | None = Field(default=None, ge=1, le=1440)
    chat_autoblock_minutes: int | None = Field(default=None, ge=1, le=10_080)


class SettingsOut(SystemSettings):
    google_configured: bool
    defaults_applied: list[str]


class PublicInfoOut(BaseModel):
    name: str
    signup_open: bool
    signup_mode: str
    email_verification: str
    google_enabled: bool
    version: str


def _settings_out(ctx: OpContext, snap: SettingsSnapshot) -> SettingsOut:
    return SettingsOut(
        **snap.values.model_dump(),
        google_configured=not google_missing(ctx.settings),
        defaults_applied=snap.defaults_applied,
    )


@operation(
    name="system.public_info",
    title="Thông tin công khai",
    description="Tên app, công tắc đăng ký / đăng nhập Google, phiên bản — cho trang đăng nhập",
    public=True,
)
async def public_info(ctx: OpContext, inp: None) -> PublicInfoOut:
    flags = await auth_flags(ctx.session, ctx.settings)  # một chỗ với miền auth: Google hiệu lực = đủ env + công tắc
    return PublicInfoOut(
        name=ctx.settings.PROJECT_NAME,
        signup_open=flags.signup_open,
        signup_mode=flags.signup_mode,
        email_verification=flags.email_verification,
        google_enabled=flags.google,
        version=ctx.settings.BUILD_VERSION,
    )


@operation(
    name="system.get_settings",
    title="Cài đặt hệ thống",
    description="Superadmin: chế độ đăng ký, xác thực email, hạn mức user / tenant, Google, hạn log / trace, chat; "
    "khoá đang mặc định",
    superadmin=True,
)
async def get_settings_op(ctx: OpContext, inp: None) -> SettingsOut:
    return _settings_out(ctx, await settings_snapshot(ctx.session))


@operation(
    name="system.update_settings",
    title="Sửa cài đặt hệ thống",
    description="Superadmin: đổi một hoặc nhiều cài đặt; trường không gửi giữ nguyên",
    effect="write",
    superadmin=True,
    invalidates=INVALIDATES,
)
async def update_settings_op(ctx: OpContext, inp: UpdateSettingsIn) -> SettingsOut:
    patch = inp.model_dump(exclude_unset=True, exclude_none=True)
    before = (await settings_snapshot(ctx.session, fresh=True)).values
    await update_system_settings(ctx.session, patch, by=ctx.principal.user_id)
    ctx.emit_to_superadmins("data:changed", {"keys": list(INVALIDATES)})  # superadmin khác đang mở trang Cài đặt
    if any(k.startswith("chat_per_") and v != getattr(before, k) for k, v in patch.items()):
        ctx.invalidate((CHAT_LIMITS_KEY,), await audience(ctx.session, "agent.chat"))  # màn chat: "còn N tin"
    return _settings_out(ctx, await settings_snapshot(ctx.session, fresh=True))


@operation(
    name="system.status",
    title="Trạng thái hệ thống",
    description="Superadmin: kết nối, nhịp tim, phiên bản, sink quan sát, issue đang mở, cài đặt đang mặc định",
    superadmin=True,
)
async def status(ctx: OpContext, inp: None) -> StatusOut:
    return await collect_status(ctx)
