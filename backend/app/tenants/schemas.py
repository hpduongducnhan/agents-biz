"""Kiểu vào / ra của op tenant."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.auth.users import Email, RoleRef
from app.tenants.policies import TenantPolicies


class TenantOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: str
    policies: TenantPolicies  # chỉ khoá đã đặt ở tầng tenant
    user_count: int  # user đang hoạt động
    user_limit: int  # hiệu lực (tenant → mặc định hệ thống); 0 = không giới hạn
    created_at: datetime


class UpdateTenantIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class InviteIn(BaseModel):
    email: Email | None = None  # None = link dùng chung (gửi qua chat / Zalo…)
    role_id: uuid.UUID | None = None  # None = member
    days: int = Field(default=7, ge=1, le=30)
    max_uses: int | None = Field(default=None, ge=1, le=500)  # mặc định: email 1, link 20


class InviteOut(BaseModel):
    id: uuid.UUID
    email: str | None
    role: RoleRef | None
    max_uses: int
    uses: int
    expires_at: datetime
    created_at: datetime
    link: str | None = None  # chỉ có ngay lúc tạo (token thô không lưu)


class InviteIdIn(BaseModel):
    invite_id: uuid.UUID


class InviteTokenIn(BaseModel):
    token: str = Field(min_length=1, max_length=200)


class InvitePreviewOut(BaseModel):
    tenant_name: str
    role_name: str
    email: str | None  # đã che (`a***@d***.com`)
    expires_at: datetime


class TenantIdIn(BaseModel):
    tenant_id: uuid.UUID


class CreateTenantIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    admin_email: Email | None = None  # có → mời làm admin (gửi thư)
    policies: TenantPolicies = TenantPolicies()


class SaveTenantIn(TenantIdIn):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    policies: TenantPolicies | None = None  # thay cả bộ; trường null = theo mặc định hệ thống


class CreatedTenantOut(BaseModel):
    tenant: TenantOut
    invite: InviteOut | None = None


class TenantsIn(BaseModel):
    q: str | None = Field(default=None, max_length=200)
    status: str | None = Field(default=None, pattern="^(active|suspended)$")
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
