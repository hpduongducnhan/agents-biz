"""Op của module __mod__: danh sách / chi tiết / tạo / sửa / xoá.
Web và trợ lý dùng chung handler; người cùng tổ chức nhận `data:changed` (R18)."""

from __future__ import annotations

from sqlmodel import func, select

from app.core.operations.context import OpContext
from app.core.operations.pagination import Page
from app.core.operations.spec import operation
from app.__mod__ import qkeys, service
from app.__mod__.models import __Mod__Item
from app.__mod__.permissions import DELETE, EDIT, VIEW
from app.__mod__.schemas import CreateIn, IdIn, ItemOut, ListIn, UpdateIn

TOOLSET = "__mod__"


def _changed(ctx: OpContext) -> None:
    ctx.invalidate(qkeys.ALL, tenant=True)  # cả tổ chức thấy ngay


@operation(
    "__mod__.list",
    title="Danh sách __title_vi_lower__",
    description="Lọc trạng thái, do tôi tạo, tìm chữ; mới cập nhật trước; phân trang",
    permission=VIEW,
    agent=True,
    toolset=TOOLSET,
    agent_hint="Tìm mục trước khi sửa / xoá (lấy item_id).",
)
async def list_items(ctx: OpContext, inp: ListIn) -> Page[ItemOut]:
    where: list = []
    if inp.status:
        where.append(__Mod__Item.status == inp.status)
    if inp.mine:
        where.append(__Mod__Item.created_by == ctx.principal.user_id)
    if inp.q and inp.q.strip():
        where += service.search(inp.q)
    total = (await ctx.session.exec(select(func.count()).select_from(__Mod__Item).where(*where))).one()
    stmt = (
        select(__Mod__Item)
        .where(*where)
        .order_by(__Mod__Item.updated_at.desc(), __Mod__Item.id)
        .offset(inp.offset)
        .limit(inp.limit)
    )
    rows = (await ctx.session.exec(stmt)).all()
    return Page[ItemOut](items=await service.outs(ctx.session, rows), total=total, limit=inp.limit, offset=inp.offset)


@operation(
    "__mod__.get",
    title="Chi tiết __title_vi_lower__",
    description="Một mục",
    permission=VIEW,
    agent=True,
    toolset=TOOLSET,
)
async def get_item(ctx: OpContext, inp: IdIn) -> ItemOut:
    (out,) = await service.outs(ctx.session, [await service.load(ctx.session, inp.item_id)])
    return out


@operation(
    "__mod__.create",
    title="Tạo __title_vi_lower__",
    description="Tạo mục mới (tiêu đề, mô tả)",
    effect="write",
    permission=EDIT,
    agent=True,
    toolset=TOOLSET,
    invalidates=qkeys.ALL,
)
async def create_item(ctx: OpContext, inp: CreateIn) -> ItemOut:
    item = __Mod__Item(
        **inp.model_dump(),
        created_by=ctx.principal.user_id,
        source="agent" if ctx.source == "agent" else "web",
        agent_run_id=ctx.agent_run_id,
    )
    ctx.session.add(item)
    await ctx.session.flush()
    _changed(ctx)
    (out,) = await service.outs(ctx.session, [item])
    return out


@operation(
    "__mod__.update",
    title="Sửa __title_vi_lower__",
    description="Sửa tiêu đề / mô tả / trạng thái — chỉ trường gửi lên",
    effect="write",
    permission=EDIT,
    agent=True,
    toolset=TOOLSET,
    invalidates=qkeys.ALL,
)
async def update_item(ctx: OpContext, inp: UpdateIn) -> ItemOut:
    item = await service.load(ctx.session, inp.item_id, lock=True)
    for name in inp.model_fields_set - {"item_id"}:
        if (value := getattr(inp, name)) is not None:
            setattr(item, name, value)
    ctx.session.add(item)
    await ctx.session.flush()
    _changed(ctx)
    (out,) = await service.outs(ctx.session, [item])
    return out


@operation(
    "__mod__.delete",
    title="Xoá __title_vi_lower__",
    description="Xoá hẳn một mục — qua trợ lý phải được duyệt",
    effect="destructive",
    permission=DELETE,
    agent=True,
    toolset=TOOLSET,
    agent_hint="Chỉ xoá khi người dùng nói rõ muốn xoá.",
    invalidates=qkeys.ALL,
)
async def delete_item(ctx: OpContext, inp: IdIn) -> None:
    item = await service.load(ctx.session, inp.item_id, lock=True)
    await ctx.session.delete(item)
    await ctx.session.flush()
    _changed(ctx)
