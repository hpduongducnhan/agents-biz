"""Bảng `tenants` (D10): một khách hàng = một tenant; user thuộc đúng một tenant (`users.tenant_id`)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Column, String
from sqlalchemy.dialects.postgresql import CITEXT
from sqlmodel import Field, SQLModel

from app.auth.models import _now, _policies, _ts

# Tenant `default` có id cố định: migration gán cho user sẵn có, `signup_mode=default_tenant` đưa user mới vào đây.
DEFAULT_TENANT_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
DEFAULT_TENANT_SLUG = "default"
STATUSES = ("active", "suspended")


class Tenant(SQLModel, table=True):
    __tablename__ = "tenants"
    __table_args__ = (CheckConstraint("status IN ('active', 'suspended')", name="ck_tenants_status"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=200)
    slug: str = Field(sa_column=Column(CITEXT, unique=True, nullable=False))
    status: str = Field(default="active", sa_column=Column(String(16), nullable=False, server_default="active"))
    policies: dict = Field(default_factory=dict, sa_column=_policies())  # tầng tenant của AccountPolicies
    created_at: datetime = Field(default_factory=_now, sa_column=_ts())
    updated_at: datetime = Field(default_factory=_now, sa_column=_ts(onupdate=True))
