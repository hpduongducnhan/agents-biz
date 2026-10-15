"""Loại thông báo của Tasks (params kiểm bằng `register_kind`; tiêu đề theo ngôn ngữ ở frontend `notif.kind.<loại>`)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.notifications.schemas import register_kind

ASSIGNED = "task_assigned"
COMMENTED = "task_commented"
DUE_SOON = "task_due_soon"
OVERDUE = "task_overdue"


class ByParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    by: str


class DueParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    due_at: str  # ISO 8601 — frontend hiện theo múi giờ người xem


register_kind(ASSIGNED, ByParams)
register_kind(COMMENTED, ByParams)
register_kind(DUE_SOON, DueParams)
register_kind(OVERDUE, DueParams)


def link(task_id) -> dict:
    return {"kind": "link", "to": f"/tasks?task={task_id}"}
