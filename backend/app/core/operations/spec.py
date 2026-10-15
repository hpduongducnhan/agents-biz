"""`@operation` — một khai báo cho REST, tool của agent, kiểm quyền và event log."""

from __future__ import annotations

import inspect
import re
import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from app.core.operations.registry import register

Effect = Literal["read", "write", "destructive"]
Source = Literal["web", "agent", "system", "ws"]
EFFECTS = ("read", "write", "destructive")
READ_FROM = ("ro", "rw")
HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
OP_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
_EMPTY_SCHEMA = {"type": "object", "properties": {}}


@dataclass(frozen=True)
class OperationSpec:
    name: str
    func: Callable
    input_model: type[BaseModel] | None
    output_model: Any
    takes_input: bool
    title: str
    description: str
    http: tuple[str, str] | None
    effect: Effect
    permission: str | None
    superadmin: bool
    sup_all_tenants: bool
    public: bool
    agent: bool
    toolset: str | None
    agent_reason: str | None
    agent_hint: str | None
    invalidates: tuple[str, ...]
    read_from: Literal["ro", "rw"]
    status_code: int
    source: str

    @property
    def namespace(self) -> str:
        """Phần trước dấu chấm — đoạn đầu đường dẫn REST (`auth.login` → `auth`)."""
        return self.name.split(".", 1)[0]

    @property
    def package(self) -> str:
        """Miền khai operation (`admin.list_users` khai trong `app.auth.ops` → `auth`)."""
        parts = self.source.split(".")
        return parts[1] if len(parts) >= 3 and parts[0] == "app" else self.namespace

    @property
    def route(self) -> tuple[str, str]:
        """(method, path tương đối api_prefix) — mặc định GET cho đọc, POST cho ghi, path = tên đổi `.` → `/`."""
        if self.http is not None:
            return self.http
        return ("GET" if self.effect == "read" else "POST", "/" + self.name.replace(".", "/"))

    def input_schema(self) -> dict:
        return self.input_model.model_json_schema() if self.input_model is not None else dict(_EMPTY_SCHEMA)


def _check_http(name: str, http: tuple[str, str] | None, effect: str) -> tuple[str, str] | None:
    if http is None:
        return None
    method, path = http[0].upper(), http[1]
    if method not in HTTP_METHODS:
        raise ValueError(f"operation '{name}': method '{method}' không hợp lệ {HTTP_METHODS}")
    if not path.startswith("/"):
        raise ValueError(f"operation '{name}': đường dẫn http phải bắt đầu bằng /")
    if method == "GET" and effect != "read":
        raise ValueError(f"operation '{name}': GET chỉ cho effect='read' (prefetch / crawler không được ghi)")
    return method, path


def operation(
    name: str,
    *,
    title: str,
    description: str = "",
    http: tuple[str, str] | None = None,
    effect: Effect = "read",
    permission: str | None = None,
    superadmin: bool = False,
    sup_all_tenants: bool = False,
    public: bool = False,
    agent: bool = False,
    toolset: str | None = None,
    agent_reason: str | None = None,
    agent_hint: str | None = None,
    invalidates: tuple[str, ...] = (),
    read_from: Literal["ro", "rw"] = "ro",
    status_code: int = 200,
) -> Callable[[Callable], Callable]:
    if not OP_NAME_RE.match(name):
        raise ValueError(f"tên operation '{name}' phải dạng <miền>.<việc> chữ thường")
    if effect not in EFFECTS:
        raise ValueError(f"operation '{name}': effect '{effect}' không hợp lệ {EFFECTS}")
    if read_from not in READ_FROM:
        raise ValueError(f"operation '{name}': read_from '{read_from}' không hợp lệ {READ_FROM}")
    if not title.strip():
        raise ValueError(f"operation '{name}': thiếu title")
    if public and (permission or superadmin):
        raise ValueError(f"operation '{name}': public không đi cùng permission / superadmin")
    if agent and not toolset:
        raise ValueError(f"operation '{name}': agent=True phải khai toolset")
    route = _check_http(name, http, effect)

    def deco(func: Callable) -> Callable:
        if not inspect.iscoroutinefunction(func):
            raise TypeError(f"operation '{name}' phải là async def")
        params = list(inspect.signature(func).parameters.values())
        if len(params) not in (1, 2):
            raise TypeError(f"operation '{name}': handler nhận (ctx) hoặc (ctx, inp)")
        hints = typing.get_type_hints(func)
        model = hints.get(params[1].name) if len(params) == 2 else None
        spec = OperationSpec(
            name=name,
            func=func,
            input_model=model if inspect.isclass(model) and issubclass(model, BaseModel) else None,
            output_model=hints.get("return"),
            takes_input=len(params) == 2,
            title=title,
            description=description,
            http=route,
            effect=effect,
            permission=permission,
            superadmin=superadmin,
            sup_all_tenants=sup_all_tenants,
            public=public,
            agent=agent,
            toolset=toolset,
            agent_reason=agent_reason,
            agent_hint=agent_hint,
            invalidates=tuple(invalidates),
            read_from=read_from,
            status_code=status_code,
            source=func.__module__,
        )
        register(spec)
        func.__bw_operation__ = spec
        return func

    return deco


def ui_only(reason: str):
    """Đánh dấu route / hàm viết tay KHÔNG đi qua @operation (healthcheck, redirect OAuth…) — kèm lý do."""
    if not reason.strip():
        raise ValueError("ui_only cần lý do")

    def deco(func: Callable) -> Callable:
        func.__bw_ui_only__ = reason
        return func

    return deco
