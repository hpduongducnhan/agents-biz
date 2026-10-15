"""Quyền Tasks + role có sẵn nhận quyền nào (D12)."""

from __future__ import annotations

from app.auth.rbac import declare_permissions

VIEW, EDIT, DELETE = "tasks.view", "tasks.edit", "tasks.delete"

declare_permissions(
    "tasks",
    {
        VIEW: "Xem công việc của tổ chức",
        EDIT: "Tạo, sửa, giao việc, đổi trạng thái, bình luận",
        DELETE: "Xoá công việc",
    },
    roles={"admin": [VIEW, EDIT, DELETE], "member": [VIEW, EDIT], "viewer": [VIEW]},
)
