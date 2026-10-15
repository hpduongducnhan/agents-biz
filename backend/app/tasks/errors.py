"""Mã lỗi Tasks — dải module 10001–10099."""

from __future__ import annotations

from app.core.errors import register_errors

TASK_ERRORS: dict[int, str] = {
    10001: "Task not found",
    10002: "Assignee is not a member of your organization",
}
register_errors(TASK_ERRORS, owner="tasks")
