"""Bảng tài khoản + RBAC hệ thống: role dùng chung mọi tenant, gán qua `user_roles`; token email / lời mời."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlmodel import Field, SQLModel

from app.core.settings import active_settings
from app.core.tenancy import TenantScoped


def _now() -> datetime:
    return datetime.now(UTC)


def _ts(*, nullable: bool = False, onupdate: bool = False) -> Column:
    # onupdate phía Python → giá trị có ngay trên object, không bị expire sau flush (session async)
    return Column(
        DateTime(timezone=True),
        nullable=nullable,
        server_default=None if nullable else text("now()"),
        onupdate=_now if onupdate else None,
    )


def _policies() -> Column:
    # chỉ chứa khoá đã đặt; đọc qua `app.auth.policies.read_policies`
    return Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))


class User(TenantScoped, table=True):
    """Mỗi user thuộc đúng một tenant (D10) — `tenant_id` từ `TenantScoped`, admin tenant chỉ thấy user cùng tenant."""

    __tablename__ = "users"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(sa_column=Column(CITEXT, unique=True, nullable=False))  # luôn lưu dạng strip().lower()
    password_hash: str | None = Field(default=None, sa_column=Column(Text, nullable=True))  # None = chỉ có Google
    name: str = Field(default="", max_length=200)
    timezone: str = Field(default_factory=lambda: active_settings().APP_TIMEZONE, max_length=64)
    locale: str = Field(default="vi", max_length=8)
    is_active: bool = True
    is_superadmin: bool = False  # chỉ SUPERADMIN_EMAILS đặt
    must_change_password: bool = False
    email_verified_at: datetime | None = Field(default=None, sa_column=_ts(nullable=True))
    policies: dict = Field(default_factory=dict, sa_column=_policies())  # ghi đè theo user
    last_login_at: datetime | None = Field(default=None, sa_column=_ts(nullable=True))
    created_at: datetime = Field(default_factory=_now, sa_column=_ts())
    updated_at: datetime = Field(default_factory=_now, sa_column=_ts(onupdate=True))


class OAuthAccount(SQLModel, table=True):
    __tablename__ = "oauth_accounts"
    __table_args__ = (UniqueConstraint("provider", "provider_uid"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(sa_column=Column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True))
    provider: str = Field(max_length=32)
    provider_uid: str = Field(max_length=255)
    email: str = Field(max_length=320)
    created_at: datetime = Field(default_factory=_now, sa_column=_ts())


class RefreshToken(SQLModel, table=True):
    __tablename__ = "refresh_tokens"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(sa_column=Column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True))
    token_hash: str = Field(sa_column=Column(String(64), unique=True, nullable=False))  # SHA-256, không lưu token
    family_id: uuid.UUID = Field(index=True)
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    revoked_at: datetime | None = Field(default=None, sa_column=_ts(nullable=True))
    ip: str | None = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=_now, sa_column=_ts())


class Permission(SQLModel, table=True):
    __tablename__ = "permissions"

    codename: str = Field(primary_key=True, max_length=64)
    domain: str = Field(max_length=32)
    description: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))
    deprecated_at: datetime | None = Field(default=None, sa_column=_ts(nullable=True))


class Role(SQLModel, table=True):
    __tablename__ = "roles"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(sa_column=Column(CITEXT, unique=True, nullable=False))
    description: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))
    is_builtin: bool = False
    policies: dict = Field(default_factory=dict, sa_column=_policies())
    created_at: datetime = Field(default_factory=_now, sa_column=_ts())
    updated_at: datetime = Field(default_factory=_now, sa_column=_ts(onupdate=True))


class RolePermission(SQLModel, table=True):
    __tablename__ = "role_permissions"

    role_id: uuid.UUID = Field(sa_column=Column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True))
    permission: str = Field(sa_column=Column(ForeignKey("permissions.codename", ondelete="CASCADE"), primary_key=True))


class UserRole(SQLModel, table=True):
    """Role hệ thống của user. Xoá role đang gán bị DB chặn (RESTRICT)."""

    __tablename__ = "user_roles"

    user_id: uuid.UUID = Field(sa_column=Column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True))
    role_id: uuid.UUID = Field(
        sa_column=Column(ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True, index=True)
    )


TOKEN_PURPOSES = ("verify", "reset", "invite")


class AuthToken(SQLModel, table=True):
    """Token một lần / có hạn gửi qua email hoặc link: xác thực email, đặt lại mật khẩu, lời mời vào tenant.
    DB chỉ giữ SHA-256 — token thô chỉ nằm trong link."""

    __tablename__ = "auth_tokens"
    __table_args__ = (CheckConstraint("purpose IN ('verify', 'reset', 'invite')", name="ck_auth_tokens_purpose"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    purpose: str = Field(sa_column=Column(String(16), nullable=False))
    token_hash: str = Field(sa_column=Column(String(64), unique=True, nullable=False))
    user_id: uuid.UUID | None = Field(
        default=None, sa_column=Column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    )
    tenant_id: uuid.UUID | None = Field(
        default=None, sa_column=Column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    )
    email: str | None = Field(default=None, sa_column=Column(CITEXT, nullable=True))  # lời mời gắn email
    role_id: uuid.UUID | None = Field(
        default=None, sa_column=Column(ForeignKey("roles.id", ondelete="SET NULL"), nullable=True)
    )
    max_uses: int = Field(default=1, sa_column=Column(Integer, nullable=False, server_default="1"))
    uses: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default="0"))
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    used_at: datetime | None = Field(default=None, sa_column=_ts(nullable=True))
    revoked_at: datetime | None = Field(default=None, sa_column=_ts(nullable=True))
    created_by: uuid.UUID | None = Field(
        default=None, sa_column=Column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    )
    created_at: datetime = Field(default_factory=_now, sa_column=_ts())
