"""Quyền __title_vi__ + role có sẵn nhận quyền nào (D12)."""

from __future__ import annotations

from app.auth.rbac import declare_permissions

VIEW, EDIT, DELETE = "__mod__.view", "__mod__.edit", "__mod__.delete"

declare_permissions(
    "__mod__",
    {
        VIEW: "Xem __title_vi_lower__ của tổ chức",
        EDIT: "Tạo, sửa __title_vi_lower__",
        DELETE: "Xoá __title_vi_lower__",
    },
    roles={"admin": [VIEW, EDIT, DELETE], "member": [VIEW, EDIT], "viewer": [VIEW]},
)
