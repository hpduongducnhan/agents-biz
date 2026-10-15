"""Cài đặt stream của một lượt: đọc đầu mỗi đoạn chạy (lượt mới / resume), đi theo `RunContext`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agent.trace.events import TOKEN_WINDOW
from app.core.logging import get_logger
from app.system.settings_store import cached_system_settings

logger = get_logger(__name__)
DEFAULT_FLUSH_MS = round(TOKEN_WINDOW * 1000)
FALLBACK_KEYS = ("chat_stream", "chat_stream_flush_ms")


@dataclass(frozen=True)
class StreamCfg:
    on: bool = True
    flush_ms: int = DEFAULT_FLUSH_MS
    defaults_applied: tuple[str, ...] = ()

    @property
    def window(self) -> float:
        return self.flush_ms / 1000

    def trace(self) -> dict[str, Any]:
        return {"on": self.on, "flush_ms": self.flush_ms, "defaults_applied": list(self.defaults_applied)}


async def load_stream_cfg() -> StreamCfg:
    try:
        cfg = await cached_system_settings()
    except Exception as exc:  # noqa: BLE001 — đọc cài đặt hỏng: vẫn chạy lượt với mặc định (R11)
        logger.warning(
            "đọc cài đặt stream lỗi: %s; DEFAULTS_APPLIED=[chat_stream=true, chat_stream_flush_ms=%d]",
            exc,
            DEFAULT_FLUSH_MS,
            extra={"loc": "agt0509"},
        )
        return StreamCfg(defaults_applied=FALLBACK_KEYS)
    return StreamCfg(on=cfg.chat_stream, flush_ms=cfg.chat_stream_flush_ms)
