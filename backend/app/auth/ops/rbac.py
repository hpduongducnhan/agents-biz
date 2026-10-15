"""rbac.* — catalog quyền, role hệ thống có sẵn (bất biến) + tự tạo."""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import delete, func
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.auth import qkeys
from app.auth.models import Permission, Role, RolePermission, User, UserRole
from app.auth.policies import AccountPolicies, read_policies
from app.auth.rbac import RESERVED_ROLE_NAMES, audience, role_holders
from app.core.errors import AppException
from app.core.operations.context import OpContext
from app.core.operations.pagination import Page, PageIn
from app.core.operations.spec import operation

RoleName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class PermissionOut(BaseModel):
    codename: str
    domain: str
    description: str


class RoleOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    is_builtin: bool
    permissions: list[str]
    user_count: int
    policies: AccountPolicies  # chỉ superadmin đặt


class RoleIdIn(BaseModel):
    role_id: uuid.UUID


class CreateRoleIn(BaseModel):
    name: RoleName
    description: str = Field(default="", max_length=500)
    permissions: list[str] = Field(default_factory=list, max_length=100)


class UpdateRoleIn(RoleIdIn):
    name: RoleName | None = None
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] | None = Field(default=None, max_length=100)


async def roles_out(session, roles: list[Role]) -> list[RoleOut]:
    ids = [r.id for r in roles]
    perms: dict[uuid.UUID, list[str]] = defaultdict(list)
    counts: dict[uuid.UUID, int] = {}
    if ids:
        perm_rows = await session.exec(
            select(RolePermission.role_id, RolePermission.permission)
            .join(Permission, Permission.codename == RolePermission.permission)
            .where(RolePermission.role_id.in_(ids), Permission.deprecated_at.is_(None))
            .order_by(RolePermission.permission)
        )
        for role_id, code in perm_rows.all():
            perms[role_id].append(code)
        count_rows = await session.exec(  # join users → session đã scope chỉ đếm user cùng tenant (D11)
            select(UserRole.role_id, func.count())
            .join(User, User.id == UserRole.user_id)
            .where(UserRole.role_id.in_(ids))
            .group_by(UserRole.role_id)
        )
        counts = {role_id: n for role_id, n in count_rows.all()}
    return [
        RoleOut(
            id=r.id,
            name=r.name,
            description=r.description,
            is_builtin=r.is_builtin,
            permissions=perms[r.id],
            user_count=counts.get(r.id, 0),
            policies=read_policies(r.policies, owner=f"role {r.name}"),
        )
        for r in roles
    ]


async def _check_perms(session, codes: list[str]) -> list[str]:
    wanted = sorted(set(codes))
    if not wanted:
        return []
    stmt = select(Permission.codename).where(Permission.codename.in_(wanted), Permission.deprecated_at.is_(None))
    found = set((await session.exec(stmt)).all())
    unknown = [c for c in wanted if c not in found]
    if unknown:
        raise AppException(2203, status_code=422, data={"unknown": unknown})
    return wanted


async def _check_name(session, name: str, *, exclude: uuid.UUID | None = None) -> None:
    if name.lower() in RESERVED_ROLE_NAMES:
        raise AppException(2201, status_code=409)
    stmt = select(Role.id).where(func.lower(Role.name) == name.lower())
    if exclude is not None:
        stmt = stmt.where(Role.id != exclude)
    if (await session.exec(stmt)).first() is not None:
        raise AppException(2201, status_code=409)


async def _custom_role(ctx: OpContext, role_id: uuid.UUID, *, lock: bool = False) -> Role:
    stmt = select(Role).where(Role.id == role_id)
    if lock:
        stmt = stmt.with_for_update()
    role = (await ctx.session.exec(stmt)).first()
    if role is None:
        raise AppException(1001, status_code=404, detail="Role not found")
    if role.is_builtin:
        raise AppException(2202, status_code=409)
    return role


async def _roles_changed(ctx: OpContext) -> None:
    ctx.invalidate((qkeys.ROLES, qkeys.USERS), await audience(ctx.session, "user.view"))


@operation(
    name="rbac.list_permissions",
    title="Catalog quyền",
    description="Quyền hệ thống đang dùng — chọn khi tạo / sửa role",
)
async def list_permissions(ctx: OpContext, inp: None) -> list[PermissionOut]:
    stmt = select(Permission).where(Permission.deprecated_at.is_(None)).order_by(Permission.domain, Permission.codename)
    rows = (await ctx.session.exec(stmt)).all()
    return [PermissionOut(codename=p.codename, domain=p.domain, description=p.description) for p in rows]


@operation(
    name="rbac.list_roles",
    title="Role hệ thống",
    description="Role có sẵn + tự tạo, kèm quyền và số người đang giữ (cần user.view)",
)
async def list_roles(ctx: OpContext, inp: PageIn) -> Page[RoleOut]:
    if not ctx.principal.can("user.view"):
        raise AppException(1005, status_code=403)
    total = (await ctx.session.exec(select(func.count()).select_from(Role))).one()
    stmt = select(Role).order_by(Role.is_builtin.desc(), Role.name).offset(inp.offset).limit(inp.limit)
    items = await roles_out(ctx.session, list((await ctx.session.exec(stmt)).all()))
    return Page[RoleOut](items=items, total=total, limit=inp.limit, offset=inp.offset)


@operation(
    name="rbac.create_role",
    title="Tạo role",
    description="Đặt tên và chọn quyền từ catalog (không tạo được quyền mới)",
    effect="write",
    superadmin=True,
    invalidates=(qkeys.ROLES,),
)
async def create_role(ctx: OpContext, inp: CreateRoleIn) -> RoleOut:
    await _check_name(ctx.session, inp.name)
    perms = await _check_perms(ctx.session, inp.permissions)
    role = Role(name=inp.name, description=inp.description.strip(), is_builtin=False)
    try:
        async with ctx.session.begin_nested():
            ctx.session.add(role)
            await ctx.session.flush()
    except IntegrityError as exc:
        raise AppException(2201, status_code=409) from exc
    ctx.session.add_all(RolePermission(role_id=role.id, permission=p) for p in perms)
    await ctx.session.flush()
    await _roles_changed(ctx)
    return (await roles_out(ctx.session, [role]))[0]


@operation(
    name="rbac.update_role",
    title="Sửa role",
    description="Đổi tên / mô tả / thay toàn bộ quyền của role tự tạo",
    effect="write",
    superadmin=True,
    invalidates=(qkeys.ROLES, qkeys.USERS),
)
async def update_role(ctx: OpContext, inp: UpdateRoleIn) -> RoleOut:
    role = await _custom_role(ctx, inp.role_id, lock=True)
    if inp.name is not None:
        await _check_name(ctx.session, inp.name, exclude=role.id)
        role.name = inp.name
    if inp.description is not None:
        role.description = inp.description.strip()
    perms_changed = False
    if inp.permissions is not None:
        wanted = set(await _check_perms(ctx.session, inp.permissions))
        stmt = select(RolePermission.permission).where(RolePermission.role_id == role.id)
        current = set((await ctx.session.exec(stmt)).all())
        if wanted != current:
            await ctx.session.exec(
                delete(RolePermission).where(
                    RolePermission.role_id == role.id, RolePermission.permission.not_in(sorted(wanted))
                )
            )
            ctx.session.add_all(RolePermission(role_id=role.id, permission=p) for p in sorted(wanted - current))
            perms_changed = True
    ctx.session.add(role)
    try:
        async with ctx.session.begin_nested():
            await ctx.session.flush()
    except IntegrityError as exc:
        raise AppException(2201, status_code=409) from exc
    if perms_changed:
        holders = await role_holders(ctx.session, role.id)
        ctx.emit_to_users(holders, "core:rbac_updated", {})
        ctx.invalidate((qkeys.ME,), holders)
    await _roles_changed(ctx)
    return (await roles_out(ctx.session, [role]))[0]


@operation(
    name="rbac.delete_role",
    title="Xoá role",
    description="Xoá role tự tạo chưa gán cho ai",
    effect="destructive",
    superadmin=True,
    invalidates=(qkeys.ROLES,),
)
async def delete_role(ctx: OpContext, inp: RoleIdIn) -> None:
    role = await _custom_role(ctx, inp.role_id, lock=True)
    holders = await role_holders(ctx.session, role.id)
    if holders:
        raise AppException(2205, status_code=409, data={"user_count": len(holders)})
    try:
        async with ctx.session.begin_nested():
            await ctx.session.delete(role)
            await ctx.session.flush()
    except IntegrityError as exc:  # vừa có người được gán role này (FK user_roles RESTRICT)
        raise AppException(2205, status_code=409) from exc
    await _roles_changed(ctx)
