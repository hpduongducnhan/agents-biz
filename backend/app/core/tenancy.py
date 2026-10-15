"""Tách dữ liệu theo tenant (D11) — chỗ duy nhất của lõi biết tenant.

- Model nghiệp vụ kế thừa `TenantScoped` (cột `tenant_id`).
- Session mang `session.info["tenant_id"]` (do `scope_session` đặt): mọi `select` / `update` / `delete` ORM trên model
  `TenantScoped` tự có điều kiện `tenant_id = …` (`do_orm_execute` + `with_loader_criteria`), đối tượng mới tự được gán
  `tenant_id`, ghi đối tượng của tenant khác → 1005 (`before_flush`).
- Session không mang `tenant_id` (đăng nhập, migrate, việc nền chưa scope) thì không lọc — việc nền phải mở
  `tenant_session(tid)`; superadmin xem chéo bằng `ctx.cross_tenant()`.
- SQL thô (`text()`, bảng Core) không đi qua bộ lọc — test luật B14 cấm trên bảng `TenantScoped` trong module.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria
from sqlmodel import Field, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.connections.registry import get_connections
from app.core.errors import AppException

TENANT_KEY = "tenant_id"
ALL_TENANTS = "all_tenants"  # execution option: bỏ lọc cho một câu lệnh (chỉ dùng trong lõi / cross_tenant)


class TenantScoped(SQLModel):
    """Mixin cho bảng nghiệp vụ: `tenant_id` NOT NULL + index; gán tự động khi session đã scope."""

    tenant_id: uuid.UUID | None = Field(default=None, foreign_key="tenants.id", index=True, nullable=False)


def scope_session(session: AsyncSession | Session, tenant_id: uuid.UUID | None) -> None:
    """Gắn tenant cho session (None = bỏ lọc). Gọi trước câu lệnh đầu tiên của session."""
    target = session.sync_session if isinstance(session, AsyncSession) else session
    if tenant_id is None:
        target.info.pop(TENANT_KEY, None)
    else:
        target.info[TENANT_KEY] = tenant_id


def session_tenant(session: AsyncSession | Session) -> uuid.UUID | None:
    target = session.sync_session if isinstance(session, AsyncSession) else session
    return target.info.get(TENANT_KEY)


_scoped: dict[str, tuple[type, ...]] = {"classes": ()}


def scoped_models() -> tuple[type, ...]:
    """Mọi model bảng kế thừa `TenantScoped` (mixin SQLModel không có cột ở mức class nên phải gắn điều kiện cho từng
    bảng con). Tính lại khi có model mới được nạp."""
    found: list[type] = []
    stack = list(TenantScoped.__subclasses__())
    while stack:
        cls = stack.pop()
        stack.extend(cls.__subclasses__())
        if getattr(cls, "__table__", None) is not None:
            found.append(cls)
    if len(found) != len(_scoped["classes"]):
        _scoped["classes"] = tuple(sorted(found, key=lambda c: c.__name__))
    return _scoped["classes"]


@event.listens_for(Session, "do_orm_execute")
def _filter_by_tenant(state: ORMExecuteState) -> None:
    tid = state.session.info.get(TENANT_KEY)
    if tid is None or state.execution_options.get(ALL_TENANTS, False):
        return
    if state.is_select or state.is_update or state.is_delete:
        state.statement = state.statement.options(
            *(
                with_loader_criteria(model, lambda cls: cls.tenant_id == tid, include_aliases=True)
                for model in scoped_models()
            )
        )


@event.listens_for(Session, "before_flush")
def _stamp_tenant(session: Session, _flush_context, _instances) -> None:
    tid = session.info.get(TENANT_KEY)
    if tid is None:
        return
    for obj in session.new:
        if isinstance(obj, TenantScoped):
            if obj.tenant_id is None:
                obj.tenant_id = tid
            elif obj.tenant_id != tid:
                raise AppException(1005, status_code=403, detail="Đối tượng thuộc tenant khác")
    for obj in session.dirty:
        if isinstance(obj, TenantScoped) and obj.tenant_id != tid:
            raise AppException(1005, status_code=403, detail="Đối tượng thuộc tenant khác")


@asynccontextmanager
async def tenant_session(tenant_id: uuid.UUID, *, read_only: bool = False) -> AsyncIterator[AsyncSession]:
    """Session đã scope cho việc nền (task / consumer / cron). RW commit khi ra khỏi khối như `Postgres.rw`."""
    pg = get_connections().postgres
    cm = pg.ro() if read_only else pg.rw()
    async with cm as session:
        scope_session(session, tenant_id)
        yield session
