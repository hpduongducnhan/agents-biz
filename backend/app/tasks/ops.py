"""tasks.* — công việc của tổ chức: danh sách / chi tiết / tạo / sửa / giao / đổi trạng thái / xoá / bình luận /
tổng hợp / người trong tổ chức. Web và trợ lý dùng chung handler; người cùng tổ chức nhận `data:changed` (R18)."""

from __future__ import annotations

import uuid

from sqlalchemy import case, func
from sqlmodel import select

from app.auth.models import User
from app.core.operations.context import OpContext
from app.core.operations.pagination import Page
from app.core.operations.spec import operation
from app.tasks import notify, qkeys, service
from app.tasks.models import OPEN_STATUSES, STATUSES, Task, TaskComment
from app.tasks.permissions import DELETE, EDIT, VIEW
from app.tasks.schemas import (
    AssignIn,
    CommentIn,
    CommentOut,
    CreateIn,
    PeopleIn,
    PersonRef,
    StatusIn,
    SummaryOut,
    TaskDetail,
    TaskIdIn,
    TaskOut,
    TasksIn,
    UpdateIn,
)

TOOLSET = "tasks"
COMMENTS_SHOWN = 100


def _me(ctx: OpContext) -> uuid.UUID:
    return ctx.principal.user_id


def _source(ctx: OpContext) -> str:
    return "agent" if ctx.source == "agent" else "web"


def _changed(ctx: OpContext) -> None:
    ctx.invalidate(qkeys.ALL, tenant=True)  # cả tổ chức thấy ngay


async def _actor_name(ctx: OpContext) -> str:
    me = await ctx.session.get(User, _me(ctx))
    return service.display_name(me) if me else ""


async def _notify_assigned(ctx: OpContext, task: Task) -> None:
    if task.assignee_id is None or task.assignee_id == _me(ctx):
        return
    by = await _actor_name(ctx)
    ctx.notify(
        task.assignee_id,
        notify.ASSIGNED,
        f"{by} giao cho bạn: {task.title}",
        params={"title": task.title, "by": by},
        action=notify.link(task.id),
    )


def _order(sort: str) -> list:
    if sort == "updated":
        return [Task.updated_at.desc()]
    if sort == "created":
        return [Task.created_at.desc()]
    rank = case(service.PRIORITY_RANK, value=Task.priority, else_=9)
    if sort == "priority":
        return [rank, Task.due_at.asc().nulls_last()]
    return [Task.due_at.asc().nulls_last(), rank, Task.created_at.desc()]


@operation(
    "tasks.list",
    title="Danh sách công việc",
    description="Việc của tổ chức — lọc trạng thái, người làm / của tôi, hạn (quá hạn / hôm nay / 7 ngày tới / "
    "không hạn), tìm chữ; sắp theo hạn / cập nhật / tạo / ưu tiên; phân trang",
    permission=VIEW,
    agent=True,
    toolset=TOOLSET,
    agent_hint="Dùng để tìm việc trước khi sửa / giao / đổi trạng thái (lấy task_id). 'việc của tôi' → mine=true; "
    "'quá hạn' → due=overdue; 'còn gì chưa xong' → open_only=true.",
)
async def list_tasks(ctx: OpContext, inp: TasksIn) -> Page[TaskOut]:
    where: list = []
    if inp.status:
        where.append(Task.status == inp.status)
    elif inp.open_only:
        where.append(Task.status.in_(OPEN_STATUSES))
    if inp.mine:
        where.append(Task.assignee_id == _me(ctx))
    elif inp.assignee_id:
        where.append(Task.assignee_id == inp.assignee_id)
    if inp.due:
        where += service.due_window(inp.due, await service.user_zone(ctx.session, _me(ctx)), service.now())
    if inp.q and inp.q.strip():
        where += service.search(inp.q)
    total = (await ctx.session.exec(select(func.count()).select_from(Task).where(*where))).one()
    stmt = select(Task).where(*where).order_by(*_order(inp.sort), Task.id).offset(inp.offset).limit(inp.limit)
    rows = (await ctx.session.exec(stmt)).all()
    return Page[TaskOut](items=await service.outs(ctx.session, rows), total=total, limit=inp.limit, offset=inp.offset)


@operation(
    "tasks.get",
    title="Chi tiết công việc",
    description="Một việc kèm 100 bình luận gần nhất",
    permission=VIEW,
    agent=True,
    toolset=TOOLSET,
    agent_hint="Đọc đủ mô tả + bình luận của một việc (task_id lấy từ tasks.list).",
)
async def get_task(ctx: OpContext, inp: TaskIdIn) -> TaskDetail:
    task = await service.load(ctx.session, inp.task_id)
    stmt = (
        select(TaskComment)
        .where(TaskComment.task_id == task.id)
        .order_by(TaskComment.created_at.desc(), TaskComment.id.desc())
        .limit(COMMENTS_SHOWN)
    )
    comments = list(reversed((await ctx.session.exec(stmt)).all()))
    (out,) = await service.outs(ctx.session, [task])
    return TaskDetail(**out.model_dump(), comments=await service.comment_outs(ctx.session, comments))


@operation(
    "tasks.create",
    title="Tạo công việc",
    description="Tạo việc mới (tiêu đề, mô tả, trạng thái, ưu tiên, hạn, người làm cùng tổ chức); người được giao nhận "
    "thông báo",
    effect="write",
    permission=EDIT,
    agent=True,
    toolset=TOOLSET,
    agent_hint="Hạn ghi theo múi giờ của người dùng (ISO 8601 có offset). Giao cho ai thì tìm id bằng tasks.people.",
    invalidates=qkeys.ALL,
)
async def create_task(ctx: OpContext, inp: CreateIn) -> TaskOut:
    await service.check_assignee(ctx.session, inp.assignee_id)
    task = Task(
        **inp.model_dump(),
        created_by=_me(ctx),
        source=_source(ctx),
        agent_run_id=ctx.agent_run_id,
        completed_at=service.now() if inp.status == "done" else None,
    )
    ctx.session.add(task)
    await ctx.session.flush()
    await _notify_assigned(ctx, task)
    _changed(ctx)
    (out,) = await service.outs(ctx.session, [task])
    return out


@operation(
    "tasks.update",
    title="Sửa công việc",
    description="Sửa tiêu đề / mô tả / ưu tiên / hạn / vị trí — chỉ trường gửi lên; due_at=null bỏ hạn",
    effect="write",
    permission=EDIT,
    agent=True,
    toolset=TOOLSET,
    agent_hint="Đổi người làm dùng tasks.assign, đổi trạng thái dùng tasks.set_status.",
    invalidates=qkeys.ALL,
)
async def update_task(ctx: OpContext, inp: UpdateIn) -> TaskOut:
    task = await service.load(ctx.session, inp.task_id, lock=True)
    for name in inp.model_fields_set - {"task_id"}:
        value = getattr(inp, name)
        if value is None and name != "due_at":
            continue  # chỉ hạn mới bỏ được bằng null
        setattr(task, name, value)
    ctx.session.add(task)
    await ctx.session.flush()
    _changed(ctx)
    (out,) = await service.outs(ctx.session, [task])
    return out


@operation(
    "tasks.assign",
    title="Giao việc",
    description="Giao việc cho người cùng tổ chức (null = bỏ giao); người được giao nhận thông báo",
    effect="write",
    permission=EDIT,
    agent=True,
    toolset=TOOLSET,
    agent_hint="Tìm id người được giao bằng tasks.people theo tên.",
    invalidates=qkeys.ALL,
)
async def assign_task(ctx: OpContext, inp: AssignIn) -> TaskOut:
    task = await service.load(ctx.session, inp.task_id, lock=True)
    await service.check_assignee(ctx.session, inp.assignee_id)
    changed = task.assignee_id != inp.assignee_id
    task.assignee_id = inp.assignee_id
    ctx.session.add(task)
    await ctx.session.flush()
    if changed:
        await _notify_assigned(ctx, task)
    _changed(ctx)
    (out,) = await service.outs(ctx.session, [task])
    return out


@operation(
    "tasks.set_status",
    title="Đổi trạng thái công việc",
    description="todo · doing · done · cancelled; xong thì ghi thời điểm hoàn thành",
    effect="write",
    permission=EDIT,
    agent=True,
    toolset=TOOLSET,
    agent_hint="'xong rồi' → done; 'đang làm' → doing; 'huỷ' → cancelled; 'mở lại' → todo.",
    invalidates=qkeys.ALL,
)
async def set_status(ctx: OpContext, inp: StatusIn) -> TaskOut:
    task = await service.load(ctx.session, inp.task_id, lock=True)
    if task.status != inp.status:
        task.status = inp.status
        task.completed_at = service.now() if inp.status == "done" else None
        ctx.session.add(task)
        await ctx.session.flush()
        _changed(ctx)
    (out,) = await service.outs(ctx.session, [task])
    return out


@operation(
    "tasks.delete",
    title="Xoá công việc",
    description="Xoá hẳn một việc cùng bình luận — qua trợ lý phải được duyệt",
    effect="destructive",
    permission=DELETE,
    agent=True,
    toolset=TOOLSET,
    agent_hint="Chỉ xoá khi người dùng nói rõ muốn xoá; muốn bỏ việc thì đề nghị đổi trạng thái 'cancelled'.",
    invalidates=qkeys.ALL,
)
async def delete_task(ctx: OpContext, inp: TaskIdIn) -> None:
    task = await service.load(ctx.session, inp.task_id, lock=True)
    await ctx.session.delete(task)
    await ctx.session.flush()
    _changed(ctx)


@operation(
    "tasks.add_comment",
    title="Bình luận công việc",
    description="Thêm bình luận; người làm + người tạo việc (trừ người viết) nhận thông báo",
    effect="write",
    permission=EDIT,
    agent=True,
    toolset=TOOLSET,
    invalidates=qkeys.ALL,
)
async def add_comment(ctx: OpContext, inp: CommentIn) -> CommentOut:
    task = await service.load(ctx.session, inp.task_id)
    row = TaskComment(task_id=task.id, author_id=_me(ctx), body=inp.body, source=_source(ctx))
    ctx.session.add(row)
    await ctx.session.flush()
    by = await _actor_name(ctx)
    for user_id in {task.assignee_id, task.created_by} - {None, _me(ctx)}:
        ctx.notify(
            user_id,
            notify.COMMENTED,
            f"{by} bình luận: {task.title}",
            body=inp.body[:200],
            params={"title": task.title, "by": by},
            action=notify.link(task.id),
        )
    _changed(ctx)
    (out,) = await service.comment_outs(ctx.session, [row])
    return out


@operation(
    "tasks.summary",
    title="Tổng hợp công việc",
    description="Đếm việc theo trạng thái, quá hạn, đến hạn hôm nay, việc đang mở / quá hạn của tôi",
    permission=VIEW,
    agent=True,
    toolset=TOOLSET,
    agent_hint="Trả lời nhanh 'còn bao nhiêu việc', 'có gì quá hạn không' trước khi liệt kê chi tiết.",
)
async def summary(ctx: OpContext, inp: None) -> SummaryOut:
    at = service.now()
    tz = await service.user_zone(ctx.session, _me(ctx))
    by_status = dict((await ctx.session.exec(select(Task.status, func.count()).group_by(Task.status))).all())

    async def count(*where) -> int:
        return (await ctx.session.exec(select(func.count()).select_from(Task).where(*where))).one()

    mine = Task.assignee_id == _me(ctx)
    overdue = service.due_window("overdue", tz, at)
    return SummaryOut(
        **{s: by_status.get(s, 0) for s in STATUSES},
        overdue=await count(*overdue),
        due_today=await count(Task.status.in_(OPEN_STATUSES), *service.due_window("today", tz, at)),
        mine_open=await count(mine, Task.status.in_(OPEN_STATUSES)),
        mine_overdue=await count(mine, *overdue),
    )


@operation(
    "tasks.people",
    title="Người trong tổ chức",
    description="Tên + id người đang hoạt động trong tổ chức — để giao việc",
    permission=VIEW,
    agent=True,
    toolset=TOOLSET,
    agent_hint="Tìm người theo tên trước khi giao việc; nhiều người trùng tên thì hỏi lại người dùng.",
)
async def list_people(ctx: OpContext, inp: PeopleIn) -> list[PersonRef]:
    stmt = select(User).where(User.is_active.is_(True))
    if inp.q and inp.q.strip():
        like = f"%{inp.q.strip()}%"
        stmt = stmt.where(User.name.ilike(like) | User.email.ilike(like))
    rows = (await ctx.session.exec(stmt.order_by(User.name, User.email).limit(inp.limit))).all()
    return [PersonRef(id=u.id, name=service.display_name(u)) for u in rows]
