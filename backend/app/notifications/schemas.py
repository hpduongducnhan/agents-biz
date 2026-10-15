"""Kiểu dữ liệu của thông báo (R13): `action` là union phân biệt theo `kind`; `params` theo model mà miền đăng ký cho
từng loại thông báo (`register_kind`). Thêm loại mới = đăng ký thêm model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

OPERATION_NAME = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$"


class LinkAction(BaseModel):
    """Bấm thông báo → mở trang trong app."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["link"] = "link"
    to: str = Field(pattern=r"^/", max_length=500)


class OperationAction(BaseModel):
    """Nút chạy một operation qua REST của nó (vd "Xong" của việc sắp tới hạn)."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["operation"] = "operation"
    operation: str = Field(pattern=OPERATION_NAME, max_length=128)
    input: dict[str, Any] = Field(default_factory=dict)
    label: str = Field(min_length=1, max_length=40)


class UrlAction(BaseModel):
    """Bấm thông báo → mở link ngoài (https) ở tab mới — vd tài liệu bên ngoài."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["url"] = "url"
    url: str = Field(pattern=r"^https://", max_length=1000)
    label: str = Field(default="", max_length=40)


NotificationAction = Annotated[LinkAction | OperationAction | UrlAction, Field(discriminator="kind")]
_ACTION: TypeAdapter = TypeAdapter(NotificationAction)


class IssueNewParams(BaseModel):
    """`issue_new` (superadmin): issue mới hoặc vừa mở lại."""

    model_config = ConfigDict(extra="forbid")
    fingerprint: str = Field(pattern=r"^[0-9a-f]{40}$")
    loc: str | None = None
    source: str
    reopened: bool = False


_PARAMS: dict[str, type[BaseModel]] = {}


def register_kind(kind: str, params: type[BaseModel]) -> None:
    current = _PARAMS.get(kind)
    if current is not None and current is not params:
        raise ValueError(f"loại thông báo '{kind}' đã đăng ký với {current.__name__}")
    _PARAMS[kind] = params


def registered_kinds() -> dict[str, type[BaseModel]]:
    return dict(_PARAMS)


def validate_payload(
    kind: str, params: BaseModel | dict[str, Any] | None, action: BaseModel | dict[str, Any] | None
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """(params, action) dạng JSON đã kiểm; loại chưa đăng ký / dữ liệu sai → ValueError (gồm ValidationError)."""
    model = _PARAMS.get(kind)
    if model is None:
        raise ValueError(f"loại thông báo '{kind}' chưa đăng ký (register_kind)")
    raw = params.model_dump() if isinstance(params, BaseModel) else (params or {})
    clean = model.model_validate(raw).model_dump(mode="json")
    if action is None:
        return clean, None
    raw_action = action.model_dump() if isinstance(action, BaseModel) else action
    return clean, _ACTION.validate_python(raw_action).model_dump(mode="json")


class NotificationOut(BaseModel):
    """Dạng gửi frontend — `notifications.list` và event `core:notification`."""

    id: uuid.UUID
    kind: str
    title: str
    body: str
    params: dict[str, Any]
    action: NotificationAction | None = None
    read_at: datetime | None = None
    created_at: datetime


class TestParams(BaseModel):
    """`test` — thông báo thử superadmin gửi (`notifications.send_test`), không có tham số."""

    model_config = ConfigDict(extra="forbid")


register_kind("issue_new", IssueNewParams)
register_kind("test", TestParams)
