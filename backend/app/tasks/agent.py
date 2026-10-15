"""Tasks trên trợ lý: toolset `tasks`, dòng ngữ cảnh "việc của tôi", chuyên gia `tasks` — module chỉ khai ở đây."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import func
from sqlmodel import select

from app.agent.config.seed_data import SpecialistSeed, register_specialist
from app.agent.config.toolsets import register_toolset
from app.agent.runtime.context import register_context
from app.auth.models import User
from app.core.dates import zone
from app.tasks import service
from app.tasks.models import OPEN_STATUSES, Task

UPCOMING = 5

register_toolset(
    "tasks",
    "Công việc: xem, tạo, sửa, giao, đổi trạng thái, bình luận, xoá",
    confirm_writes=(),  # xoá đã là `destructive` → luôn phải duyệt
)


async def _context(session, user: User) -> list[str]:
    """Số việc theo trạng thái + vài việc đang mở gần hạn của tôi (kèm id để sửa không cần tra lại)."""
    at = service.now()
    counts = dict((await session.exec(select(Task.status, func.count()).group_by(Task.status))).all())
    mine = Task.assignee_id == user.id
    stmt = (
        select(Task)
        .where(mine, Task.status.in_(OPEN_STATUSES))
        .order_by(Task.due_at.asc().nulls_last(), Task.created_at.desc())
        .limit(UPCOMING)
    )
    rows = (await session.exec(stmt)).all()
    tz = zone(user.timezone)
    lines = [
        f"tasks: tổ chức todo {counts.get('todo', 0)} · doing {counts.get('doing', 0)} · done {counts.get('done', 0)}"
        f" · việc đang mở của tôi {len(rows) if len(rows) < UPCOMING else f'≥ {UPCOMING}'}"
    ]
    for t in rows:
        due = t.due_at.astimezone(tz).strftime("%Y-%m-%d %H:%M") if t.due_at else "không hạn"
        late = " · QUÁ HẠN" if service.is_overdue(t, at) else ""
        lines.append(f"- task {t.id} · {t.title} · {t.status} · ưu tiên {t.priority} · hạn {due}{late}")
    return lines


register_context("tasks", _context, order=50, budget=UPCOMING + 1)

register_specialist(
    SpecialistSeed(
        "tasks",
        "Công việc",
        "Tạo, tìm, giao, cập nhật, bình luận công việc của tổ chức",
        ("tasks",),
        "The organization's tasks / to-dos: create, find, list, assign to someone, change status, due dates, "
        "priorities, comments, delete; questions about what is overdue or due soon",
        (
            "tạo việc gọi khách hàng thứ Sáu giao cho Lan",
            "tuần này còn việc gì quá hạn",
            "đánh dấu việc báo cáo tháng là xong",
            "create a task to review the contract tomorrow",
            "what tasks are assigned to me",
        ),
        prompt_dir=Path(__file__).resolve().parent / "prompts",
    )
)
