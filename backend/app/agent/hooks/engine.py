"""Chạy hook ở một điểm móc: lọc `point` + bật, theo `position`, điều kiện AND khớp → hành động;
`block` đầu tiên thắng (dừng các hook sau). `notify` / `webhook` có tác dụng ngoài — chạy thử (`dry`) chỉ trả việc sẽ
làm. Hook hỏng ghi span lỗi + log, không làm hỏng lượt chạy."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import TypeAdapter

from app.agent.hooks.conditions import matches, render
from app.agent.hooks.schemas import ALLOWED, HookAction
from app.agent.hooks.webhook import request_of, send_webhook
from app.agent.notify import HOOK_NOTICE, HookNoticeParams
from app.core.logging import get_logger
from app.notifications.service import notify_superadmins, notify_users

logger = get_logger(__name__)
ACTION = TypeAdapter(HookAction)


@dataclass
class HookOutcome:
    blocked: bool = False
    message: str | None = None
    approval: bool = False
    context: list[str] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)


async def _notify(action, text: str, data: dict[str, Any], agent: str) -> dict[str, Any]:
    params = HookNoticeParams(text=text, agent=agent).model_dump()
    if action.to == "user":
        user_id = (data.get("user") or {}).get("id")
        if user_id:
            await notify_users([uuid.UUID(str(user_id))], HOOK_NOTICE, text[:200], "", params=params)
        return {"to": "user", "user_id": user_id, "text": text}
    await notify_superadmins(HOOK_NOTICE, text[:200], "", params=params)
    return {"to": "superadmins", "text": text}


async def _act(hook, action, point: str, data: dict[str, Any], out: HookOutcome, *, dry: bool, run_id) -> dict:
    agent = str((data.get("agent") or {}).get("slug") or "")
    kind = action.action
    if kind == "block":
        out.blocked, out.message = True, render(action.message, data)
        return {"action": kind, "message": out.message}
    if kind == "require_approval":
        out.approval = True
        return {"action": kind}
    if kind == "add_context":
        text = render(action.text, data)
        out.context.append(text)
        return {"action": kind, "text": text}
    if kind == "notify":
        text = render(action.text, data)
        if dry:
            return {"action": kind, "to": action.to, "text": text, "sent": False}
        return {"action": kind, **await _notify(action, text, data, agent), "sent": True}
    payload = {"hook_id": str(hook.id), "point": point, "agent": agent, "data": data}
    credential = str(action.credential_id) if action.credential_id else None
    if dry:
        return {"action": kind, "request": await request_of(str(action.url), payload, credential), "sent": False}
    run = str(run_id) if run_id else None
    await send_webhook.kiq(str(hook.id), str(action.url), payload, credential, run)
    return {"action": kind, "url": str(action.url), "queued": True}


async def run(
    point: str, hooks, data: dict[str, Any], *, tracer=None, parent: str | None = None, dry: bool = False, run_id=None
) -> HookOutcome:
    out = HookOutcome()
    for hook in sorted((h for h in hooks if h.point == point and h.enabled), key=lambda h: h.position):
        try:
            if not matches(hook.conditions or [], data):
                continue
            action = ACTION.validate_python(hook.action_config)
            if action.action not in ALLOWED[point]:
                continue
            result = await _act(hook, action, point, data, out, dry=dry, run_id=run_id)
            error = None
        except Exception as exc:  # noqa: BLE001 — hook hỏng không được làm hỏng lượt chạy
            logger.warning("hook %s (%s) lỗi: %s", hook.id, point, exc, extra={"loc": "agt0704"})
            result, error = {"error": f"{type(exc).__name__}: {exc}"[:500]}, str(exc)[:500]
        out.results.append({"hook_id": str(hook.id), "name": hook.name, **result})
        if tracer is not None:
            tracer.hook(hook, point, result, parent=parent, error=error)
        if out.blocked:
            break
    return out
