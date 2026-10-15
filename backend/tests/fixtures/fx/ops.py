"""Operation của miền giả `fx` — chỉ test import; không thuộc `app.*` nên app `api` không gắn route của nó."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field
from sqlalchemy import text

from app.core.errors import AppException
from app.core.operations.context import OpContext
from app.core.operations.pagination import Page, PageIn
from app.core.operations.spec import operation

FX_TABLE = "CREATE TABLE IF NOT EXISTS fx_notes (id serial PRIMARY KEY, title text NOT NULL)"
HOOKS: list[str] = []


class NoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=50)
    password: str | None = None  # trường bí mật → event log phải che


class NoteOut(BaseModel):
    id: int
    title: str


class ListIn(PageIn):
    q: str = ""


class IdIn(BaseModel):
    id: int


class ShareIn(BaseModel):
    id: int
    user_ids: list[uuid.UUID]


async def _record_hook() -> None:
    HOOKS.append("ran")


async def _never() -> None:
    HOOKS.append("never")


@operation("fx.list_notes", title="Liệt kê ghi chú", agent=True, toolset="lookup")
async def list_notes(ctx: OpContext, inp: ListIn) -> Page[NoteOut]:
    where = {"q": f"%{inp.q}%"}
    count = text("SELECT count(*) FROM fx_notes WHERE title ILIKE :q")
    total = (await ctx.session.exec(count, params=where)).one()[0]
    sql = text("SELECT id, title FROM fx_notes WHERE title ILIKE :q ORDER BY id LIMIT :n OFFSET :o")
    rows = (await ctx.session.exec(sql, params=where | {"n": inp.limit, "o": inp.offset})).all()
    items = [NoteOut(id=r.id, title=r.title) for r in rows]
    return Page[NoteOut](items=items, total=total, limit=inp.limit, offset=inp.offset)


@operation(
    "fx.create_note",
    title="Tạo ghi chú",
    effect="write",
    permission="fx.write",
    invalidates=("fx.notes",),
    agent=True,
    toolset="personal",
    status_code=201,
)
async def create_note(ctx: OpContext, inp: NoteIn) -> NoteOut:
    sql = text("INSERT INTO fx_notes (title) VALUES (:t) RETURNING id, title")
    row = (await ctx.session.exec(sql, params={"t": inp.title})).one()
    ctx.emit_to_superadmins("fx:created", {"id": row.id})
    ctx.notify(ctx.principal.user_id, "fx_created", "Đã tạo ghi chú", params={"id": row.id})
    return NoteOut(id=row.id, title=row.title)


@operation(
    "fx.share_note",
    title="Chia sẻ ghi chú",
    effect="write",
    permission="fx.write",
    invalidates=("fx.notes",),
    agent_reason="test: thao tác chỉ có trên UI",
)
async def share_note(ctx: OpContext, inp: ShareIn) -> dict:
    ctx.emit_to_users(inp.user_ids, "fx:shared", {"id": inp.id})
    ctx.invalidate(("fx.notes", "fx.shared"), users=inp.user_ids)
    return {"shared": len(inp.user_ids)}


@operation(
    "fx.delete_note", title="Xoá ghi chú", effect="destructive", permission="fx.write", invalidates=("fx.notes",)
)
async def delete_note(ctx: OpContext, inp: IdIn) -> dict:
    result = await ctx.session.exec(text("DELETE FROM fx_notes WHERE id = :id"), params={"id": inp.id})
    if result.rowcount == 0:
        raise AppException(1001, status_code=404, detail="Không có ghi chú")
    return {"deleted": inp.id}


@operation("fx.create_then_fail", title="Tạo rồi lỗi", effect="write", permission="fx.write", invalidates=("fx.notes",))
async def create_then_fail(ctx: OpContext, inp: NoteIn) -> dict:
    await ctx.session.exec(text("INSERT INTO fx_notes (title) VALUES (:t)"), params={"t": inp.title})
    ctx.emit_to_superadmins("fx:created", {})
    ctx.notify(ctx.principal.user_id, "fx_created", "Không được gửi")
    ctx.after_commit(_never)
    raise AppException(1006, status_code=409, detail="lỗi thử sau khi ghi")


@operation("fx.purge", title="Xoá sạch", effect="destructive", superadmin=True, invalidates=("fx.notes",))
async def purge(ctx: OpContext) -> dict:
    result = await ctx.session.exec(text("DELETE FROM fx_notes"))
    return {"purged": result.rowcount}


@operation("fx.ping", title="Ping công khai", public=True)
async def ping(ctx: OpContext) -> dict:
    return {"pong": True, "user": str(ctx.principal.user_id) if ctx.principal else None}


@operation("fx.write_in_read", title="Ghi lén trong thao tác đọc")
async def write_in_read(ctx: OpContext, inp: None) -> dict:
    await ctx.session.exec(text("INSERT INTO fx_notes (title) VALUES ('lén')"))
    return {}


@operation("fx.with_hook", title="Có hook sau commit", effect="write", invalidates=("fx.notes",))
async def with_hook(ctx: OpContext) -> dict:
    ctx.after_commit(_record_hook)
    return {"ok": True}
