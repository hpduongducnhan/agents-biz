"""Loại thông báo của miền agent (params kiểm bằng `register_kind`)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.notifications.schemas import register_kind

KEY_DISABLED = "agent_key_disabled"


class KeyDisabledParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    reason: str


register_kind(KEY_DISABLED, KeyDisabledParams)


HOOK_NOTICE = "agent_hook"


class HookNoticeParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    agent: str = ""


register_kind(HOOK_NOTICE, HookNoticeParams)


CHAT_BLOCKED = "agent_chat_blocked"
CHAT_UNBLOCKED = "agent_chat_unblocked"


class ChatBlockedParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    until: str | None = None  # ISO; None = tới khi quản trị mở
    reason: str = ""
    source: str = "manual"


class ChatUnblockedParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


register_kind(CHAT_BLOCKED, ChatBlockedParams)
register_kind(CHAT_UNBLOCKED, ChatUnblockedParams)
