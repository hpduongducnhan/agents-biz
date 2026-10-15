"""Chính sách tầng tenant (jsonb `tenants.policies`, chỉ chứa khoá đã đặt; superadmin sửa ở `/sa/tenants`)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.logging import get_logger
from app.tenants.models import Tenant

logger = get_logger(__name__)


class TenantPolicies(BaseModel):
    """`None` = không đặt → theo mặc định hệ thống. Khoá lạ bị bỏ qua."""

    model_config = ConfigDict(extra="ignore")

    user_limit: int | None = Field(default=None, ge=0, le=1_000_000)  # 0 = không giới hạn
    agent_enabled: bool | None = None  # false = tenant không dùng trợ lý (agent.send → 6023)
    chat_per_minute: int | None = Field(default=None, ge=0, le=100_000)
    chat_per_hour: int | None = Field(default=None, ge=0, le=100_000)
    chat_per_day: int | None = Field(default=None, ge=0, le=100_000)


def read_tenant_policies(raw: dict[str, Any] | None, *, owner: str) -> TenantPolicies:
    kept: dict[str, Any] = {}
    for name in TenantPolicies.model_fields:
        if not raw or raw.get(name) is None:
            continue
        try:
            TenantPolicies.model_validate({name: raw[name]})
        except ValidationError as exc:
            logger.warning("chính sách %s của %s không hợp lệ, bỏ qua: %s", name, owner, exc, extra={"loc": "tnt0101"})
            continue
        kept[name] = raw[name]
    return TenantPolicies.model_validate(kept)


def agent_enabled(tenant: Tenant | None) -> bool:
    """Tenant dùng được trợ lý không — `agent_enabled` chưa đặt = có."""
    if tenant is None:
        return True
    return read_tenant_policies(tenant.policies, owner=f"tenant {tenant.id}").agent_enabled is not False


def dump_tenant_policies(policies: TenantPolicies) -> dict[str, Any]:
    return policies.model_dump(mode="json", exclude_none=True)
