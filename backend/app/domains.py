"""Danh sách miền nghiệp vụ — một chỗ duy nhất. Import miền = đăng ký @operation / @task / @subscriber / @on_ws."""

from __future__ import annotations

import importlib
import importlib.util

from app.core.operations.registry import specs_for
from app.core.settings import active_settings
from app.devtools.guard import devtools_enabled

DOMAINS = (
    "system",
    "auth",
    "tenants",
    "mail",
    "observability",
    "notifications",
    "credentials",
    "agent",
    "tasks",  # module mẫu — module mới thêm một dòng ở đây
)
PARTS = ("ops", "tasks", "consumers", "agent")  # `agent.py`: register_toolset / register_context / register_specialist


def load_domains() -> None:
    """Import `app.<miền>` (thiếu package = lỗi cấu hình) rồi `ops` / `tasks` / `consumers` nếu có. Gọi lại vô hại."""
    for domain in DOMAINS:
        importlib.import_module(f"app.{domain}")
        for part in PARTS:
            name = f"app.{domain}.{part}"
            if importlib.util.find_spec(name) is not None:
                importlib.import_module(name)
    if devtools_enabled(active_settings()):
        importlib.import_module("app.devtools.ops")


def domain_for_path(path: str, api_prefix: str) -> str:
    """`{api_prefix}/<đoạn>/…` → miền cho trường `module` của log HTTP: namespace operation → package khai nó."""
    if not path.startswith(api_prefix + "/"):
        return "core"
    first = path[len(api_prefix) + 1 :].split("/", 1)[0]
    specs = specs_for(first)
    if specs:
        return specs[0].package
    return first if first in DOMAINS else "core"
