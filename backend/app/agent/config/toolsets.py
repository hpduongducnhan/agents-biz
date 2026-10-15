"""Toolset của agent theo việc: module khai bằng `register_toolset` (trong `app/<module>/agent.py`); op gắn vào bằng
`toolset=` trên `@operation(agent=True)`. Quyền `agent.<toolset>` tự vào catalog."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from app.auth.rbac import ALL_ROLES, declare_agent_toolset
from app.core.operations.registry import all_specs
from app.core.operations.spec import OperationSpec

NAME = re.compile(r"[a-z][a-z0-9_]{0,39}")


@dataclass(frozen=True)
class Toolset:
    name: str
    description: str  # dạng "<việc>: <chi tiết>" — phần trước ":" là nhãn trong ngữ cảnh "chưa được dùng trợ lý cho …"
    confirm_writes: frozenset[str]  # op ghi rủi ro: qua trợ lý phải duyệt; web không đổi


_TOOLSETS: dict[str, Toolset] = {}


def register_toolset(
    name: str, description: str, *, confirm_writes: Iterable[str] = (), roles: Iterable[str] = ALL_ROLES
) -> None:
    """Thêm toolset + quyền `agent.<name>` (role có sẵn trong `roles` nhận quyền).
    Khai lại y hệt = vô hại; khác = lỗi cấu hình."""
    if not NAME.fullmatch(name):
        raise ValueError(f"tên toolset '{name}' phải là chữ thường / số / gạch dưới")
    toolset = Toolset(name, description, frozenset(confirm_writes))
    if name in _TOOLSETS and _TOOLSETS[name] != toolset:
        raise ValueError(f"toolset '{name}' đã đăng ký với nội dung khác")
    label, _, detail = description.partition(":")
    perm_text = f"Trợ lý: {label.strip().lower()}" + (f" ({detail.strip()})" if detail.strip() else "")
    declare_agent_toolset(perm_of(name), perm_text, roles)  # lỗi (role lạ…) thì toolset không vào registry
    _TOOLSETS[name] = toolset


def toolsets() -> dict[str, str]:
    """Tên → mô tả, theo tên."""
    return {name: _TOOLSETS[name].description for name in sorted(_TOOLSETS)}


def registered() -> tuple[Toolset, ...]:
    return tuple(_TOOLSETS[name] for name in sorted(_TOOLSETS))


def confirm_writes() -> frozenset[str]:
    return frozenset().union(*(t.confirm_writes for t in _TOOLSETS.values()))


def perm_of(toolset: str) -> str:
    """Quyền hệ thống cho phép trợ lý dùng toolset."""
    return f"agent.{toolset}"


def agent_specs() -> list[OperationSpec]:
    return sorted((s for s in all_specs() if s.agent), key=lambda s: s.name)


def ops_of(toolset: str) -> list[OperationSpec]:
    return [s for s in agent_specs() if s.toolset == toolset]


def default_policy(spec: OperationSpec) -> str:
    return "confirm" if spec.effect == "destructive" or spec.name in confirm_writes() else "auto"


register_toolset("lookup", "Tra cứu chung: thông báo")
