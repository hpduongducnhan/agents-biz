"""Sự kiện của một lượt chạy: `seq` tăng dần trong lượt, gửi phòng
`user:<id>` qua realtime (best-effort) và đệm Redis `bw:run:<id>:events` (TTL 1 giờ, ≤ 5000) để client bù khi hở `seq`
/ nối lại / tải lại trang."""

from __future__ import annotations

import json
import time
from typing import Any

from app.core.logging import get_logger
from app.core.messaging.realtime import emit_to_user
from app.core.redact import build_keys, is_sensitive_key
from app.core.rkeys import rkey

logger = get_logger(__name__)
BUFFER_CAP = 5_000  # quá trần: bỏ agent:token khỏi bộ đệm, vẫn giữ step / end / error
BUFFER_TTL = 3_600
TOKEN_WINDOW = 0.05  # gom chữ ~50 ms mỗi sự kiện
_KEYS = build_keys(frozenset())
BY_EVENTS = frozenset({"agent:token", "agent:step", "agent:approval", "agent:llm"})


def buffer_key(run_id: str) -> str:
    return rkey("run", str(run_id), "events")


def cancel_key(run_id: str) -> str:
    return rkey("run", str(run_id), "cancel")


def redact(value: Any) -> Any:
    """Tham số hiển thị cho người chat / trace — che trường bí mật theo cùng danh sách của log."""
    if isinstance(value, dict):
        return {k: "***" if is_sensitive_key(k, _KEYS) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


async def buffered(redis, run_id: str, after_seq: int = 0) -> list[dict[str, Any]] | None:
    """Sự kiện đã đệm có `seq > after_seq` (theo thứ tự); None khi bộ đệm không còn (hết hạn / Redis mất)."""
    raw = await redis.rw.lrange(buffer_key(run_id), 0, -1)
    if not raw:
        return None
    events = [json.loads(x) for x in raw]
    return [e for e in events if e["data"]["seq"] > after_seq]


class RunEmitter:
    def __init__(
        self, redis, run_id: str, session_id: str, user_id: str, *, window: float = TOKEN_WINDOW, start_seq: int = 0
    ) -> None:
        self.redis = redis
        self.run_id, self.session_id, self.user_id = str(run_id), str(session_id), str(user_id)
        self.seq = start_seq
        self._window = window
        self._pending = ""
        self._last = 0.0
        self._buffered = 0
        self.text = ""  # mọi chữ đã stream trong lượt (phần dở khi bị huỷ)
        self.by: dict[str, str] | None = None  # chuyên gia đang chạy — gắn vào token / step / approval

    async def _emit(self, event: str, data: dict[str, Any]) -> None:
        self.seq += 1
        payload = {"run_id": self.run_id, "session_id": self.session_id, "seq": self.seq, **data}
        if self.by is not None and event in BY_EVENTS:
            payload["by"] = self.by
        try:
            if event != "agent:token" or self._buffered < BUFFER_CAP:
                key = buffer_key(self.run_id)
                await self.redis.rw.rpush(
                    key, json.dumps({"event": event, "data": payload}, ensure_ascii=False, default=str)
                )
                await self.redis.rw.expire(key, BUFFER_TTL)
                self._buffered += 1
            await emit_to_user(self.user_id, event, payload)
        except Exception as exc:  # noqa: BLE001 — realtime best-effort; client bù qua run_events khi nối lại
            logger.warning("phát %s run=%s lỗi: %s", event, self.run_id, exc, extra={"loc": "agt0201"})

    async def start(self, **event: Any) -> None:
        await self._emit("agent:start", event)

    async def token(self, delta: str) -> None:
        if not delta:
            return
        self._pending += delta
        self.text += delta
        if time.monotonic() - self._last >= self._window:
            await self.flush()

    async def flush(self) -> None:
        if self._pending:
            text, self._pending = self._pending, ""
            self._last = time.monotonic()
            await self._emit("agent:token", {"delta": text})

    async def step(self, **event: Any) -> None:
        await self.flush()
        await self._emit("agent:step", event)

    async def llm(self, **event: Any) -> None:
        """Một lần gọi mô hình vừa xong (hàng chấm tiến trình)."""
        await self.flush()
        await self._emit("agent:llm", event)

    async def approval(self, **event: Any) -> None:
        await self.flush()
        await self._emit("agent:approval", event)

    async def decided(self, **event: Any) -> None:
        await self._emit("agent:approval_decided", event)

    async def route(self, *, steps: list[dict[str, Any]], clarify: str | None) -> None:
        await self._emit("agent:route", {"steps": steps, "clarify": clarify})

    async def end(self, *, message_id: str | None, usage: dict[str, int], status: str = "done") -> None:
        await self.flush()
        await self._emit("agent:end", {"message_id": message_id, "usage": usage, "status": status})

    async def error(self, code: int, message: str) -> None:
        await self.flush()
        await self._emit("agent:error", {"code": code, "message": message})
