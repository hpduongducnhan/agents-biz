"""Cấu hình hook vòng đời: điều kiện `{path, op, value}` nối AND (≤ 10) + hành động theo
discriminated union (R13). Điểm móc giới hạn hành động được phép."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

Op = Literal["eq", "ne", "in", "contains", "exists", "gt", "gte", "lt", "lte"]
Point = Literal["before_run", "before_tool", "after_tool", "after_run"]


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=200, pattern=r"^[a-z_]+(\.[A-Za-z0-9_\[\]]+)*$")
    op: Op
    value: Any = None


class BlockAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["block"] = "block"
    message: str = Field(min_length=1, max_length=1000)


class ApprovalAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["require_approval"] = "require_approval"


class ContextAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["add_context"] = "add_context"
    text: str = Field(min_length=1, max_length=2000)


class NotifyAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["notify"] = "notify"
    to: Literal["user", "superadmins"] = "superadmins"
    text: str = Field(min_length=1, max_length=1000)


class WebhookAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["webhook"] = "webhook"
    url: HttpUrl
    credential_id: uuid.UUID | None = None


HookAction = Annotated[
    BlockAction | ApprovalAction | ContextAction | NotifyAction | WebhookAction, Field(discriminator="action")
]
ALLOWED: dict[str, frozenset[str]] = {
    "before_run": frozenset({"block", "add_context", "notify", "webhook"}),
    "before_tool": frozenset({"block", "require_approval", "notify", "webhook"}),
    "after_tool": frozenset({"notify", "webhook"}),
    "after_run": frozenset({"notify", "webhook"}),
}
MAX_CONDITIONS = 10
