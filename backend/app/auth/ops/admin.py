"""admin.* — quản trị tài khoản trong tenant: xem (user.view); khoá / mở, gán role, đặt lại mật khẩu (user.manage).
Superadmin thấy mọi tenant (`sup_all_tenants`)."""

from __future__ import annotations

import time
import uuid

from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.auth import qkeys
from app.auth.identity import mark_disabled
from app.auth.models import Role, User, UserRole
from app.auth.passwords import check_password_policy, hash_password
from app.auth.rbac import audience
from app.auth.sessions import revoke_all
from app.auth.users import UserOut, users_out
from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.messaging.realtime import rt_revoke
from app.core.operations.context import OpContext
from app.core.operations.pagination import Page, PageIn
from app.core.operations.spec import operation

logger = get_logger(__name__)


class ListUsersIn(PageIn):
    q: str | None = Field(default=None, max_length=200)
    tenant_id: uuid.UUID | None = None  # chỉ superadmin lọc được theo tenant (admin tenant luôn chỉ thấy tenant mình)
    is_active: bool | None = None
    role_id: uuid.UUID | None = None


class UserIdIn(BaseModel):
    user_id: uuid.UUID


class UpdateUserIn(UserIdIn):
    is_active: bool | None = None
    role_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)
    is_superadmin: bool | None = None  # có mặt → 2204: cờ chỉ do SUPERADMIN_EMAILS đặt


class ResetPasswordIn(UserIdIn):
    new_password: str = Field(max_length=200)


def _like(q: str) -> str:
    """Chuỗi tìm của người dùng → mẫu ILIKE; `%`, `_`, `\\` hiểu theo nghĩa đen."""
    escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def _load(ctx: OpContext, user_id: uuid.UUID, *, lock: bool = False) -> User:
    kw = {"with_for_update": True} if lock else {}
    user = await ctx.session.get(User, user_id, **kw)
    if user is None:
        raise AppException(1001, status_code=404, detail="User not found")
    return user


async def _set_roles(session, user_id: uuid.UUID, role_ids: list[uuid.UUID]) -> bool:
    """Thay TOÀN BỘ role của user. Trả True nếu tập role đổi."""
    wanted = list(dict.fromkeys(role_ids))
    found = set((await session.exec(select(Role.id).where(Role.id.in_(wanted)))).all()) if wanted else set()
    missing = [str(r) for r in wanted if r not in found]
    if missing:
        raise AppException(1002, status_code=422, detail=f"Unknown roles: {missing}")
    current = set((await session.exec(select(UserRole.role_id).where(UserRole.user_id == user_id))).all())
    if current == set(wanted):
        return False
    await session.exec(delete(UserRole).where(UserRole.user_id == user_id, UserRole.role_id.not_in(wanted)))
    session.add_all(UserRole(user_id=user_id, role_id=r) for r in wanted if r not in current)
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as exc:  # role vừa bị xoá song song
        raise AppException(1002, status_code=422, detail="Unknown roles") from exc
    return True


async def _apply_lock(ctx: OpContext, user_id: uuid.UUID, *, disabled: bool) -> None:
    """Khoá: thu hồi refresh token, dấu Redis sống bằng đời access token, báo user, ngắt mọi socket. Mở: xoá dấu."""
    ttl = ctx.settings.AUTH_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    redis = ctx.redis.rw
    if not disabled:
        ctx.after_commit(lambda: mark_disabled(redis, user_id, False, ttl))
        return
    await revoke_all(ctx.session, user_id)
    now = int(time.time())
    ctx.after_commit(lambda: mark_disabled(redis, user_id, True, ttl))
    ctx.after_commit(lambda: rt_revoke(str(user_id), before=now, until=now + ttl))
    ctx.emit_to_user(user_id, "core:account_disabled", {})
    logger.info("khoá tài khoản user=%s bởi %s", user_id, ctx.principal.user_id, extra={"loc": "auth0006"})


async def _user_list_changed(ctx: OpContext) -> None:
    ctx.invalidate((qkeys.USERS,), await audience(ctx.session, "user.view"))


@operation(
    name="admin.list_users",
    title="Danh sách user",
    description="Tìm theo email / tên; lọc theo trạng thái, role; phân trang",
    permission="user.view",
    sup_all_tenants=True,
)
async def list_users(ctx: OpContext, inp: ListUsersIn) -> Page[UserOut]:
    where = []
    if inp.q and inp.q.strip():
        like = _like(inp.q)
        where.append(or_(User.email.ilike(like, escape="\\"), User.name.ilike(like, escape="\\")))
    if inp.is_active is not None:
        where.append(User.is_active.is_(inp.is_active))
    if inp.tenant_id is not None:
        where.append(User.tenant_id == inp.tenant_id)
    if inp.role_id is not None:
        where.append(User.id.in_(select(UserRole.user_id).where(UserRole.role_id == inp.role_id)))
    total = (await ctx.session.exec(select(func.count()).select_from(User).where(*where))).one()
    stmt = select(User).where(*where).order_by(User.created_at, User.id).offset(inp.offset).limit(inp.limit)
    rows = list((await ctx.session.exec(stmt)).all())
    return Page[UserOut](items=await users_out(ctx.session, rows), total=total, limit=inp.limit, offset=inp.offset)


@operation(
    name="admin.get_user",
    title="Chi tiết user",
    description="Hồ sơ + role của một user",
    permission="user.view",
    sup_all_tenants=True,
)
async def get_user(ctx: OpContext, inp: UserIdIn) -> UserOut:
    return (await users_out(ctx.session, [await _load(ctx, inp.user_id)]))[0]


@operation(
    name="admin.update_user",
    title="Sửa tài khoản",
    description="Khoá / mở tài khoản, thay toàn bộ role hệ thống của user",
    effect="destructive",
    permission="user.manage",
    sup_all_tenants=True,
    invalidates=(qkeys.USERS,),
)
async def update_user(ctx: OpContext, inp: UpdateUserIn) -> UserOut:
    if inp.is_superadmin is not None:
        raise AppException(2204, status_code=409)
    user = await _load(ctx, inp.user_id, lock=True)
    if inp.is_active is False and user.id == ctx.principal.user_id:
        raise AppException(2206, status_code=409)
    if user.is_superadmin:
        raise AppException(2204, status_code=409)
    roles_changed = inp.role_ids is not None and await _set_roles(ctx.session, user.id, inp.role_ids)
    disabled = inp.is_active is False and user.is_active
    enabled = inp.is_active is True and not user.is_active
    if inp.is_active is not None:
        user.is_active = inp.is_active
        ctx.session.add(user)
        await ctx.session.flush()
    if disabled or enabled:
        await _apply_lock(ctx, user.id, disabled=disabled)
    if roles_changed:
        ctx.emit_to_user(user.id, "core:rbac_updated", {})
        ctx.invalidate((qkeys.ME,), [user.id])
    await _user_list_changed(ctx)
    return (await users_out(ctx.session, [user]))[0]


@operation(
    name="admin.reset_password",
    title="Đặt lại mật khẩu",
    description="Đặt mật khẩu tạm; user phải đổi ở lần đăng nhập sau; mọi phiên cũ bị thu hồi",
    effect="write",
    permission="user.manage",
    sup_all_tenants=True,
    invalidates=(qkeys.USERS,),
)
async def reset_password(ctx: OpContext, inp: ResetPasswordIn) -> UserOut:
    user = await _load(ctx, inp.user_id, lock=True)
    if user.is_superadmin:
        raise AppException(2204, status_code=409)
    check_password_policy(inp.new_password, ctx.settings.AUTH_PASSWORD_MIN_LENGTH)
    user.password_hash = hash_password(inp.new_password)
    user.must_change_password = True
    ctx.session.add(user)
    await revoke_all(ctx.session, user.id)
    ctx.invalidate((qkeys.ME,), [user.id])
    await _user_list_changed(ctx)
    return (await users_out(ctx.session, [user]))[0]
