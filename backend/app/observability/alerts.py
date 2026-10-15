"""Báo superadmin khi có issue mới / mở lại."""

from __future__ import annotations

from typing import Any

from app.core.messaging.realtime import emit_to_superadmins
from app.core.rkeys import rkey
from app.notifications.schemas import IssueNewParams, LinkAction
from app.notifications.service import notify_superadmins

ALERT_TTL = 3600  # giây: `issue_new` tối đa 1 lần / fingerprint / giờ


def alert_key(fp: str) -> str:
    return rkey("obs", "issue_notified", fp)


async def notify_new_issue(redis: Any, issue: dict[str, Any]) -> None:
    """`issue_new` tối đa 1 lần / fingerprint / giờ (khoá NX dùng chung mọi process); gửi hỏng thì trả khoá để lần
    gặp sau thử lại. Trang Issues của superadmin luôn được làm mới."""
    key = alert_key(issue["fingerprint"])
    if await redis.set(key, "1", nx=True, ex=ALERT_TTL):
        head = "Issue mở lại" if issue["reopened"] else "Issue mới"
        try:
            await notify_superadmins(
                "issue_new",
                f"{head}: {issue['title']}",
                body=issue["loc"] or issue["source"],
                params=IssueNewParams(
                    fingerprint=issue["fingerprint"],
                    loc=issue["loc"],
                    source=issue["source"],
                    reopened=issue["reopened"],
                ),
                action=LinkAction(to=f"/sa/issues?fingerprint={issue['fingerprint']}"),
            )
        except Exception:  # noqa: BLE001 — trả khoá rồi ném tiếp (sink log obs0505): lần gặp sau thử báo lại
            await redis.delete(key)
            raise
    await emit_to_superadmins("data:changed", {"keys": ["observability"]})
