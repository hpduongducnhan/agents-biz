"""Liveness + readiness + nhịp tim pipeline. Không log từng lần gọi (healthcheck gọi liên tục)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.errors import error_message
from app.core.messaging.hub import get_hub, has_hub
from app.core.operations.spec import ui_only
from app.core.response import ApiResponse
from app.system import heartbeat

router = APIRouter(tags=["health"])
_PASS = {"ok", "disabled"}


def _unready(data: dict) -> JSONResponse:
    return JSONResponse(status_code=503, content=jsonable_encoder(ApiResponse.fail(1008, error_message(1008), data)))


async def readiness(settings, conns) -> dict[str, str]:
    """Kênh DB + RabbitMQ (mongo "disabled" khi tắt) — dùng chung cho /health/ready và system.status."""
    checks = await conns.health()
    if not settings.MONGO_ENABLED:
        checks["mongo"] = "disabled"
    checks["rabbitmq"] = await get_hub().ping() if has_hub() else "error: chưa kết nối"
    return checks


def is_ready(checks: dict[str, str]) -> bool:
    return all(v in _PASS for v in checks.values())


@router.get("/health/live")
@ui_only("healthcheck cho Docker / Coolify / smoke — không phải thao tác nghiệp vụ")
async def live(request: Request) -> ApiResponse[dict]:
    s = request.app.state.settings
    return ApiResponse.ok({"status": "ok", "service": s.SERVICE_NAME, "version": s.BUILD_VERSION})


@router.get("/health/ready")
@ui_only("healthcheck cho Docker / Coolify / smoke — không phải thao tác nghiệp vụ")
async def ready(request: Request):
    s = request.app.state.settings
    conns = getattr(request.app.state, "conns", None)
    if conns is None:
        return _unready({"reason": "chưa có kết nối"})
    checks = await readiness(s, conns)
    return ApiResponse.ok(checks) if is_ready(checks) else _unready(checks)


@router.get("/health/pipeline")
@ui_only("healthcheck cho Docker / Coolify / smoke — không phải thao tác nghiệp vụ")
async def pipeline(request: Request):
    s = request.app.state.settings
    conns = getattr(request.app.state, "conns", None)
    if conns is None:
        return _unready({"reason": "chưa có kết nối"})
    beats = await heartbeat.read_all(conns.redis.ro, s.HEARTBEAT_INTERVAL)
    return ApiResponse.ok(beats) if all(v["ok"] for v in beats.values()) else _unready(beats)
