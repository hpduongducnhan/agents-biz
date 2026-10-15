"""Quan sát: event log + issues (Mongo theo cờ MONGO_ENABLED). Mọi role gọi lúc boot / tắt."""

from __future__ import annotations

from app.core.connections.mongo import Mongo
from app.core.logging import get_logger
from app.core.settings import Settings
from app.observability.sinks import Sinks, noop_sinks, set_sinks

logger = get_logger(__name__)
_state = {"warned": False}


async def init_observability(settings: Settings, mongo: Mongo | None) -> Sinks:
    """Bật Mongo + role có kết nối Mongo → sink Mongo + LogStore; còn lại Noop, báo một lần mỗi process (R11, R12).
    Gọi lại trong cùng process (reload / test) thì dừng task ghi cũ trước."""
    from app.observability import runtime  # defer: tránh vòng import với app.core.operations.runner (Lựa chọn Q6)

    await runtime.stop()
    if settings.MONGO_ENABLED and mongo is not None:
        sinks = await runtime.start(settings, mongo)
        logger.info("sink Mongo sẵn sàng (event_log, issues) — store đọc đã gắn", extra={"loc": "obs0003"})
    else:
        sinks = noop_sinks()
        if not _state["warned"]:
            _state["warned"] = True
            if not settings.MONGO_ENABLED:
                msg = "MONGO_ENABLED=false — trace / event log / issues tắt; DEFAULTS_APPLIED=[sinks=noop]"
                logger.warning(msg, extra={"loc": "obs0001"})
            else:
                msg = "role này không kết nối Mongo — event log / issues không ghi ở đây; DEFAULTS_APPLIED=[sinks=noop]"
                logger.info(msg, extra={"loc": "obs0002"})
    set_sinks(sinks)
    return sinks


async def close_observability(timeout: float = 2.0) -> None:
    """Gọi lúc tắt process, sau khi dừng messaging: ghi nốt hàng đợi tối đa `timeout` giây rồi về Noop."""
    from app.observability import runtime  # defer: tránh vòng import với app.core.operations.runner (Lựa chọn Q6)

    await runtime.stop(timeout)
    set_sinks(noop_sinks())
