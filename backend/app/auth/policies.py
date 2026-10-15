"""Chính sách tài khoản: giá trị gắn theo role + ghi đè theo user, jsonb chỉ chứa khoá đã đặt.
Hạn mức hiệu lực: superadmin miễn → user ghi đè → lớn nhất trong các role → tenant (`tenants.policies`) → mặc định
hệ thống."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlmodel import select

from app.auth.models import Role, User, UserRole
from app.core.logging import get_logger
from app.tenants.models import Tenant
from app.tenants.policies import read_tenant_policies

logger = get_logger(__name__)

LimitSource = Literal["superadmin", "user", "role", "tenant", "default"]
LimitKey = Literal["chat_per_minute", "chat_per_hour", "chat_per_day"]
CHAT_KEYS: tuple[LimitKey, ...] = ("chat_per_minute", "chat_per_hour", "chat_per_day")


class AccountPolicies(BaseModel):
    """`None` = không đặt → theo tầng dưới. Khoá lạ bị bỏ qua."""

    model_config = ConfigDict(extra="ignore")

    # tin nhắn với trợ lý / phút · giờ · ngày; 0 = không giới hạn
    chat_per_minute: int | None = Field(default=None, ge=0, le=100_000)
    chat_per_hour: int | None = Field(default=None, ge=0, le=100_000)
    chat_per_day: int | None = Field(default=None, ge=0, le=100_000)


def read_policies(raw: dict[str, Any] | None, *, owner: str) -> AccountPolicies:
    """jsonb đã lưu → giá trị; khoá hỏng bỏ qua + WARNING, không làm hỏng request."""
    kept: dict[str, Any] = {}
    for name in AccountPolicies.model_fields:
        if not raw or raw.get(name) is None:
            continue
        try:
            AccountPolicies.model_validate({name: raw[name]})
        except ValidationError as exc:
            logger.warning("chính sách %s của %s không hợp lệ, bỏ qua: %s", name, owner, exc, extra={"loc": "auth0601"})
            continue
        kept[name] = raw[name]
    return AccountPolicies.model_validate(kept)


def dump_policies(policies: AccountPolicies) -> dict[str, Any]:
    return policies.model_dump(mode="json", exclude_none=True)


@dataclass(frozen=True)
class EffectiveLimit:
    value: int | None  # None = không giới hạn
    source: LimitSource
    role: str | None = None  # role cho giá trị khi source = "role"


def _rank(value: int, zero_unlimited: bool) -> float:
    return float("inf") if zero_unlimited and value == 0 else float(value)


async def effective_limits(
    session, user: User, defaults: dict[LimitKey, int], *, zero_unlimited: bool = False
) -> dict[LimitKey, EffectiveLimit]:
    """Nhiều khoá một lượt (một truy vấn role). `zero_unlimited`: `0` = không giới hạn → thắng mọi số khi gộp role."""
    if user.is_superadmin:
        return {k: EffectiveLimit(None, "superadmin") for k in defaults}
    own = read_policies(user.policies, owner=f"user {user.id}")
    stmt = (
        select(Role.name, Role.policies)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id)
        .order_by(Role.name)
    )
    roles = [(name, read_policies(raw, owner=f"role {name}")) for name, raw in (await session.exec(stmt)).all()]
    tenant = await session.get(Tenant, user.tenant_id) if user.tenant_id else None
    tenant_policies = read_tenant_policies(tenant.policies if tenant else None, owner=f"tenant {user.tenant_id}")
    out: dict[LimitKey, EffectiveLimit] = {}
    for key, default in defaults.items():
        if (mine := getattr(own, key)) is not None:
            out[key] = EffectiveLimit(mine, "user")
            continue
        best: EffectiveLimit | None = None
        for name, pol in roles:
            value = getattr(pol, key)
            if value is not None and (
                best is None or _rank(value, zero_unlimited) > _rank(best.value or 0, zero_unlimited)
            ):
                best = EffectiveLimit(value, "role", name)
        if best is None and (value := getattr(tenant_policies, key, None)) is not None:
            best = EffectiveLimit(value, "tenant")
        out[key] = best or EffectiveLimit(default, "default")
    return out


async def effective_limit(session, user: User, key: LimitKey, default: int) -> EffectiveLimit:
    return (await effective_limits(session, user, {key: default}))[key]
