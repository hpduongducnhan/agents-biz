"""Webhook của hook: chạy nền qua taskiq — POST JSON, ký HMAC-SHA256 bằng secret của credential (nếu có) ở header
`X-BizWithAgents-Signature: sha256=<hex>`, timeout 10 s. Kết quả ghi event log (`agent.hook_webhook`, ok / lỗi); lỗi
không bao giờ làm hỏng lượt chạy."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx2

from app.core.cid import get_cid
from app.core.connections.registry import get_connections
from app.core.logging import get_logger
from app.core.messaging.tasks import task
from app.core.settings import active_settings
from app.credentials.service import reveal
from app.observability.sinks import EventLogEntry, get_sinks

logger = get_logger(__name__)
TIMEOUT_SEC = 10.0
SIGNATURE = "X-BizWithAgents-Signature"


def body_of(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode()


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def request_of(url: str, payload: dict[str, Any], credential_id: str | None) -> dict[str, Any]:
    """Request sẽ gửi (chạy thử trả cái này thay vì gửi thật)."""
    body = body_of(payload)
    headers = {"Content-Type": "application/json"}
    if credential_id:
        async with get_connections().postgres.ro() as session:
            secret = await reveal(session, uuid.UUID(credential_id), active_settings(), purpose="hook-webhook")
        headers[SIGNATURE] = sign(secret, body)
    return {"url": url, "headers": headers, "body": body.decode()}


async def _log(hook_id: str, run_id: str | None, url: str, ok: bool, status: int | None, started: float) -> None:
    entry = EventLogEntry(
        ts=datetime.now(UTC),
        cid=get_cid(),
        actor_id=None,
        actor_sup=False,
        source="system",
        agent_run_id=uuid.UUID(run_id) if run_id else None,
        operation="agent.hook_webhook",
        effect="write",
        input={"hook_id": hook_id, "url": url.split("?", 1)[0], "status": status},
        ok=ok,
        error_code=None if ok else 6018,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    try:
        await get_sinks().event_log.write(entry)
    except Exception as exc:  # noqa: BLE001 — webhook đã chạy; ghi event log hỏng chỉ được báo
        logger.warning("ghi event log webhook lỗi: %s", exc, extra={"loc": "agt0703"})


@task("agent.hook_webhook", retry=0, timeout=30)
async def send_webhook(
    hook_id: str, url: str, payload: dict, credential_id: str | None = None, run_id: str | None = None
):
    started = time.perf_counter()
    status: int | None = None
    try:
        req = await request_of(url, payload, credential_id)
        async with httpx2.AsyncClient(timeout=TIMEOUT_SEC) as client:
            res = await client.post(url, content=req["body"].encode(), headers=req["headers"])
        status = res.status_code
        ok = 200 <= status < 300
        if not ok:
            logger.warning("webhook hook=%s trả HTTP %s", hook_id, status, extra={"loc": "agt0701"})
    except Exception as exc:  # noqa: BLE001 — webhook hỏng ghi event log ok=false, không làm chết lane
        ok = False
        logger.warning("webhook hook=%s lỗi: %s", hook_id, exc, extra={"loc": "agt0702"})
    await _log(hook_id, run_id, url, ok, status, started)
    return {"ok": ok, "status": status}
