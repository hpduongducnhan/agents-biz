"""credentials.* — superadmin quản lý credential; API không bao giờ trả giá trị (chỉ `masked_hint`)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.core.errors import AppException
from app.core.operations.context import OpContext
from app.core.operations.pagination import Page, PageIn
from app.core.operations.spec import operation
from app.credentials.models import Credential
from app.credentials.service import seal

REASON = "cấu hình agent — chỉ trên giao diện"
KEYS = ("credentials.list", "studio.agents", "studio.agent")
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Secret = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]


class CredentialOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    provider_id: uuid.UUID | None
    masked_hint: str
    weight: int
    status: str
    disabled_reason: str | None
    key_id: str
    created_at: datetime
    updated_at: datetime


class ListIn(PageIn):
    provider_id: uuid.UUID | None = None
    kind: Literal["api_key", "google_service_account"] = "api_key"


class CreateIn(BaseModel):
    name: Name
    provider_id: uuid.UUID | None = None
    secret: Secret
    weight: int = Field(default=1, ge=1, le=100)


class UpdateIn(BaseModel):
    credential_id: uuid.UUID
    name: Name | None = None
    secret: Secret | None = None
    weight: int | None = Field(default=None, ge=1, le=100)
    status: Literal["active", "disabled"] | None = None


class IdIn(BaseModel):
    credential_id: uuid.UUID


def out(c: Credential) -> CredentialOut:
    return CredentialOut.model_validate(c, from_attributes=True)


async def _flush(ctx: OpContext) -> None:
    try:
        async with ctx.session.begin_nested():
            await ctx.session.flush()
    except IntegrityError as exc:
        raise AppException(1006, status_code=409, detail="Credential name already exists") from exc


@operation("credentials.list", title="Credential", description="Danh sách credential (chỉ gợi ý che)", superadmin=True)
async def list_credentials(ctx: OpContext, inp: ListIn) -> Page[CredentialOut]:
    stmt = select(Credential).where(Credential.kind == inp.kind)
    if inp.provider_id:
        stmt = stmt.where(Credential.provider_id == inp.provider_id)
    total = (await ctx.session.exec(select(func.count()).select_from(stmt.subquery()))).one()
    rows = (await ctx.session.exec(stmt.order_by(Credential.name).offset(inp.offset).limit(inp.limit))).all()
    return Page[CredentialOut](items=[out(c) for c in rows], total=total, limit=inp.limit, offset=inp.offset)


@operation(
    "credentials.create",
    title="Thêm credential",
    description="Lưu key đã mã hoá; giá trị không bao giờ đọc lại được qua API",
    effect="write",
    superadmin=True,
    agent_reason=REASON,
    invalidates=KEYS,
)
async def create(ctx: OpContext, inp: CreateIn) -> CredentialOut:
    c = Credential(name=inp.name, provider_id=inp.provider_id, weight=inp.weight, created_by=ctx.principal.user_id)
    seal(c, inp.secret, ctx.settings)
    ctx.session.add(c)
    await _flush(ctx)
    return out(c)


@operation(
    "credentials.update",
    title="Sửa credential",
    description="Đổi tên / thay giá trị / trọng số / bật tắt",
    effect="write",
    superadmin=True,
    agent_reason=REASON,
    invalidates=KEYS,
)
async def update(ctx: OpContext, inp: UpdateIn) -> CredentialOut:
    c = await ctx.session.get(Credential, inp.credential_id)
    if c is None:
        raise AppException(1001, status_code=404, detail="Credential not found")
    if inp.name is not None:
        c.name = inp.name
    if inp.secret is not None:
        seal(c, inp.secret, ctx.settings)
    if inp.weight is not None:
        c.weight = inp.weight
    if inp.status is not None:
        c.status = inp.status
        c.disabled_reason = None if inp.status == "active" else (c.disabled_reason or "tắt tay")
    ctx.session.add(c)
    await _flush(ctx)
    return out(c)


@operation(
    "credentials.delete",
    title="Xoá credential",
    description="Xoá credential không còn gắn agent nào",
    effect="destructive",
    superadmin=True,
    agent_reason=REASON,
    invalidates=KEYS,
)
async def delete(ctx: OpContext, inp: IdIn) -> None:
    c = await ctx.session.get(Credential, inp.credential_id)
    if c is None:
        raise AppException(1001, status_code=404, detail="Credential not found")
    try:
        async with ctx.session.begin_nested():
            await ctx.session.delete(c)
            await ctx.session.flush()
    except IntegrityError as exc:  # agent_keys.credential_id RESTRICT
        raise AppException(6016, status_code=409, detail="Credential is attached to agents") from exc
