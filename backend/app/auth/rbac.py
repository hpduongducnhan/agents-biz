"""RBAC: catalog quyền khai trong code, role có sẵn admin / member / viewer dùng chung mọi tenant (D12), quyền của
user. Role tự tạo chỉ superadmin quản."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import delete, or_
from sqlmodel import select

from app.auth.models import Permission, Role, RolePermission, User, UserRole
from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.migrate import post_migrate_step
from app.core.settings import Settings

logger = get_logger(__name__)

_DECLARED: dict[str, tuple[str, str]] = {}  # codename → (miền, mô tả)
# Role có sẵn (D12) — dùng chung mọi tenant; quyền mỗi role = hợp các `roles=` khai kèm `declare_permissions`.
BUILTIN_ROLE_INFO: dict[str, str] = {
    "admin": "Quản trị tenant: user, lời mời, cài đặt tenant + mọi quyền module",
    "member": "Thành viên: làm việc với dữ liệu của tenant",
    "viewer": "Chỉ xem",
}
_ROLE_GRANTS: dict[str, set[str]] = {name: set() for name in BUILTIN_ROLE_INFO}
DEFAULT_ROLE = "member"  # user mới không có lời mời / không tự tạo tenant
TENANT_ADMIN_ROLE = "admin"  # người tự tạo tenant (`signup_mode=new_tenant`)
RESERVED_ROLE_NAMES = frozenset({"superadmin", *BUILTIN_ROLE_INFO})


def declare_permissions(domain: str, perms: dict[str, str], *, roles: dict[str, list[str]] | None = None) -> None:
    """Khai quyền hệ thống của một miền + role có sẵn nhận quyền nào (`roles={"admin": […], "member": […]}`).
    Khai lại cùng miền = cập nhật; trùng codename ở miền khác, role lạ, quyền không thuộc lần khai = lỗi cấu hình."""
    for code, description in perms.items():
        owner = _DECLARED.get(code)
        if owner is not None and owner[0] != domain:
            raise ValueError(f"quyền {code} đã khai ở miền {owner[0]}")
        _DECLARED[code] = (domain, description)
    for role, codes in (roles or {}).items():
        if role not in _ROLE_GRANTS:
            raise ValueError(f"role có sẵn '{role}' không tồn tại ({', '.join(_ROLE_GRANTS)})")
        unknown = sorted(set(codes) - set(perms))
        if unknown:
            raise ValueError(f"role {role} nhận quyền chưa khai trong lần này: {unknown}")
        _ROLE_GRANTS[role] |= set(codes)


def declared_permissions() -> dict[str, tuple[str, str]]:
    return dict(_DECLARED)


def builtin_roles() -> dict[str, tuple[str, frozenset[str]]]:
    """Role có sẵn → (mô tả, quyền) theo catalog đang khai — `bw migrate` đặt DB đúng như vậy."""
    return {name: (desc, frozenset(_ROLE_GRANTS[name])) for name, desc in BUILTIN_ROLE_INFO.items()}


ALL_ROLES = ["admin", "member", "viewer"]

# Catalog quyền nền; module khai thêm quyền của mình bằng `declare_permissions` (không khai lại các mã này).
declare_permissions(
    "auth",
    {
        "user.view": "Xem danh sách user của tenant (tên, email, trạng thái, role)",
        "user.manage": "Khoá / mở tài khoản, gán role, đặt lại mật khẩu (trong tenant)",
    },
    roles={"admin": ["user.view", "user.manage"]},
)
declare_permissions(
    "agent", {"agent.chat": "Chat với các agent được mở cho mình"}, roles=dict.fromkeys(ALL_ROLES, ["agent.chat"])
)
# Trợ lý được dùng nhóm tool nào — `register_toolset` (app/agent/config/toolsets.py) khai qua đây.
AGENT_TOOLSET_PERMS: dict[str, str] = {}


def declare_agent_toolset(code: str, description: str, roles: Iterable[str]) -> None:
    declare_permissions("agent", {code: description}, roles={role: [code] for role in roles})
    AGENT_TOOLSET_PERMS[code] = description


async def sync_permissions(session) -> dict[str, list[str]]:
    """Quyền mới → thêm; quyền không còn khai → `deprecated_at` (không xoá)."""
    declared = declared_permissions()
    existing = {p.codename: p for p in (await session.exec(select(Permission))).all()}
    added: list[str] = []
    for code, (domain, description) in sorted(declared.items()):
        perm = existing.get(code)
        if perm is None:
            session.add(Permission(codename=code, domain=domain, description=description))
            added.append(code)
        elif (perm.domain, perm.description, perm.deprecated_at) != (domain, description, None):
            perm.domain, perm.description, perm.deprecated_at = domain, description, None
            session.add(perm)
    deprecated = sorted(c for c, p in existing.items() if c not in declared and p.deprecated_at is None)
    now = datetime.now(UTC)
    for code in deprecated:
        existing[code].deprecated_at = now
        session.add(existing[code])
    await session.flush()
    return {"added": added, "deprecated": deprecated}


async def sync_builtin_roles(session) -> list[str]:
    """Tạo role có sẵn nếu thiếu và đặt quyền ĐÚNG như code. Trả tên các role vừa đổi."""
    changed: list[str] = []
    for name, (description, perms) in builtin_roles().items():
        role = (await session.exec(select(Role).where(Role.name == name))).first()
        dirty = role is None or not role.is_builtin or role.description != description
        if role is None:
            role = Role(name=name, description=description, is_builtin=True)
        role.is_builtin, role.description = True, description
        session.add(role)
        await session.flush()
        stmt = select(RolePermission.permission).where(RolePermission.role_id == role.id)
        current = set((await session.exec(stmt)).all())
        if current != perms:
            await session.exec(
                delete(RolePermission).where(
                    RolePermission.role_id == role.id, RolePermission.permission.not_in(sorted(perms))
                )
            )
            session.add_all(RolePermission(role_id=role.id, permission=p) for p in sorted(perms - current))
            await session.flush()
            dirty = True
        if dirty:
            changed.append(name)
    return changed


async def grant_new_agent_perms(session, added: list[str]) -> list[str]:
    """Quyền `agent.<toolset>` vừa vào catalog lần đầu → role tự tạo đang có `agent.chat` nhận đủ (giữ hành vi cũ).
    Chỉ chạy ở lần thêm đó — role bị bỏ bớt quyền sau này không được cấp lại."""
    new = sorted(set(added) & set(AGENT_TOOLSET_PERMS))
    if not new:
        return []
    stmt = (
        select(Role)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .where(Role.is_builtin.is_(False), RolePermission.permission == "agent.chat")
    )
    roles = list((await session.exec(stmt)).all())
    session.add_all(RolePermission(role_id=r.id, permission=p) for r in roles for p in new)
    await session.flush()
    return sorted(r.name for r in roles)


@post_migrate_step("auth.catalog", order=10)
async def sync_catalog(session, settings: Settings) -> dict[str, list[str]]:
    synced = await sync_permissions(session)
    result = (
        synced
        | {"roles_changed": await sync_builtin_roles(session)}
        | {"agent_perms_granted": await grant_new_agent_perms(session, synced["added"])}
    )
    if any(result.values()):
        logger.info("đồng bộ catalog quyền: %s", result, extra={"loc": "auth0003"})
    return result


async def user_permissions(session, user_id: uuid.UUID) -> frozenset[str]:
    stmt = (
        select(RolePermission.permission)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .join(Permission, Permission.codename == RolePermission.permission)
        .where(UserRole.user_id == user_id, Permission.deprecated_at.is_(None))
        .distinct()
    )
    return frozenset((await session.exec(stmt)).all())


async def active_permission_codes(session) -> list[str]:
    stmt = select(Permission.codename).where(Permission.deprecated_at.is_(None)).order_by(Permission.codename)
    return list((await session.exec(stmt)).all())


async def role_by_name(session, name: str) -> Role:
    role = (await session.exec(select(Role).where(Role.name == name))).first()
    if role is None:
        raise AppException(1000, status_code=500, detail=f"Role '{name}' missing — run bw migrate")
    return role


async def grant_role(session, user_id: uuid.UUID, role: Role | str = DEFAULT_ROLE) -> None:
    """Gán một role (đối tượng hoặc tên) cho user mới."""
    target = role if isinstance(role, Role) else await role_by_name(session, role)
    session.add(UserRole(user_id=user_id, role_id=target.id))
    await session.flush()


async def role_names(session, user_id: uuid.UUID) -> list[str]:
    stmt = select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
    return sorted((await session.exec(stmt)).all())


async def role_holders(session, role_id: uuid.UUID) -> list[uuid.UUID]:
    stmt = select(UserRole.user_id).where(UserRole.role_id == role_id).order_by(UserRole.user_id)
    return list((await session.exec(stmt)).all())


async def audience(session, *perms: str, tenant_id: uuid.UUID | None = None) -> list[uuid.UUID]:
    """User đang hoạt động là superadmin hoặc có ít nhất một quyền trong `perms` (người cần thấy thay đổi). Session đã
    scope thì tự gói trong tenant; session chưa scope (op công khai) truyền `tenant_id` để chỉ lấy người của tenant đó
    (+ superadmin)."""
    holders = (
        select(UserRole.user_id)
        .join(RolePermission, RolePermission.role_id == UserRole.role_id)
        .join(Permission, Permission.codename == RolePermission.permission)
        .where(RolePermission.permission.in_(perms), Permission.deprecated_at.is_(None))
    )
    stmt = select(User.id).where(User.is_active.is_(True), or_(User.is_superadmin.is_(True), User.id.in_(holders)))
    if tenant_id is not None:
        stmt = stmt.where(or_(User.tenant_id == tenant_id, User.is_superadmin.is_(True)))
    return list((await session.exec(stmt)).all())
