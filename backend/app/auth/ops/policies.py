"""Chính sách tài khoản: chỉ superadmin đặt, cho role (kể cả role có sẵn) và từng user."""

from __future__ import annotations

import uuid

from pydantic import BaseModel
from sqlmodel import select

from app.auth import qkeys
from app.auth.models import Role, User
from app.auth.ops.rbac import RoleOut, roles_out
from app.auth.policies import AccountPolicies, dump_policies, read_policies
from app.auth.rbac import audience, role_holders
from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.operations.context import OpContext
from app.core.operations.spec import operation

logger = get_logger(__name__)
CHAT_LIMITS_KEY = "agent.chat_limits"  # hạn mức chat của user đổi theo chính sách role / user


class SetRolePoliciesIn(BaseModel):
    role_id: uuid.UUID
    policies: AccountPolicies  # thay cả bộ; trường null = không đặt


class UserIdIn(BaseModel):
    user_id: uuid.UUID


class SetUserPoliciesIn(UserIdIn):
    policies: AccountPolicies


class UserPoliciesOut(BaseModel):
    policies: AccountPolicies  # ghi đè đang đặt cho user


async def _user(ctx: OpContext, user_id: uuid.UUID, *, lock: bool = False) -> User:
    kw = {"with_for_update": True} if lock else {}
    user = await ctx.session.get(User, user_id, **kw)
    if user is None:
        raise AppException(1001, status_code=404, detail="User not found")
    return user


async def _user_policies_out(ctx: OpContext, user: User) -> UserPoliciesOut:
    return UserPoliciesOut(policies=read_policies(user.policies, owner=f"user {user.id}"))


@operation(
    name="rbac.set_role_policies",
    title="Đặt hạn mức cho role",
    description="Superadmin: thay toàn bộ chính sách của một role (kể cả role có sẵn) — vd hạn mức chat với trợ lý",
    effect="write",
    superadmin=True,
    invalidates=(qkeys.ROLES,),
)
async def set_role_policies(ctx: OpContext, inp: SetRolePoliciesIn) -> RoleOut:
    role = (await ctx.session.exec(select(Role).where(Role.id == inp.role_id).with_for_update())).first()
    if role is None:
        raise AppException(1001, status_code=404, detail="Role not found")
    role.policies = dump_policies(inp.policies)
    ctx.session.add(role)
    await ctx.session.flush()
    logger.info(
        "chính sách role %s → %s bởi %s", role.name, role.policies, ctx.principal.user_id, extra={"loc": "auth0602"}
    )
    ctx.invalidate((qkeys.ROLES,), await audience(ctx.session, "user.view"))
    ctx.invalidate((CHAT_LIMITS_KEY,), await role_holders(ctx.session, role.id))
    return (await roles_out(ctx.session, [role]))[0]


@operation(
    name="admin.user_policies",
    title="Hạn mức của user",
    description="Superadmin: chính sách ghi đè của user",
    superadmin=True,
)
async def user_policies(ctx: OpContext, inp: UserIdIn) -> UserPoliciesOut:
    return await _user_policies_out(ctx, await _user(ctx, inp.user_id))


@operation(
    name="admin.set_user_policies",
    title="Đặt hạn mức cho user",
    description="Superadmin: thay toàn bộ chính sách ghi đè của một user (thắng giá trị của role); null = theo role",
    effect="write",
    superadmin=True,
    invalidates=(qkeys.USERS,),
)
async def set_user_policies(ctx: OpContext, inp: SetUserPoliciesIn) -> UserPoliciesOut:
    user = await _user(ctx, inp.user_id, lock=True)
    if user.is_superadmin:
        raise AppException(2204, status_code=409)
    user.policies = dump_policies(inp.policies)
    ctx.session.add(user)
    await ctx.session.flush()
    logger.info(
        "chính sách user %s → %s bởi %s", user.id, user.policies, ctx.principal.user_id, extra={"loc": "auth0603"}
    )
    ctx.emit_to_superadmins("data:changed", {"keys": [qkeys.USERS]})
    ctx.invalidate((CHAT_LIMITS_KEY,), (user.id,))
    return await _user_policies_out(ctx, user)
