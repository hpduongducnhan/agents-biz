"""Quyền của tenant — admin tenant có sẵn; role tự tạo chọn được từ catalog."""

from __future__ import annotations

from app.auth.rbac import declare_permissions

declare_permissions(
    "tenants",
    {
        "tenant.settings": "Sửa tên và cài đặt của tenant",
        "tenant.invite": "Mời người vào tenant (email / link), xem và thu hồi lời mời",
    },
    roles={"admin": ["tenant.settings", "tenant.invite"]},
)
