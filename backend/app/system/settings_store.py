"""Cài đặt hệ thống: một dòng `system_settings` (id=1); `data` jsonb chỉ chứa khoá đã cấu hình, khoá thiếu / hỏng
dùng mặc định và được báo trong `DEFAULTS_APPLIED` (R11). Đọc qua cache Redis `bw:sys:settings` 60 giây."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.connections.postgres import after_commit
from app.core.connections.registry import get_connections
from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.messaging.broadcast import broadcast, on_broadcast
from app.core.rkeys import rkey
from app.system.models import SystemSettingsRow

logger = get_logger(__name__)
CACHE_KEY = rkey("sys", "settings")
CACHE_TTL = 60  # giây
BROADCAST_TOPIC = "system.settings_changed"


class SystemSettings(BaseModel):
    """Giá trị hiệu lực; khoá lạ bị bỏ qua."""

    model_config = ConfigDict(extra="ignore")

    # đăng ký vào tenant nào (D12): default_tenant · new_tenant · invite_only (lời mời chạy ở mọi chế độ)
    signup_mode: Literal["default_tenant", "new_tenant", "invite_only"] = "default_tenant"
    email_verification: Literal["off", "soft", "required"] = "soft"  # D14
    user_limit_default: int = Field(default=0, ge=0, le=1_000_000)  # số user tối đa mỗi tenant; 0 = không giới hạn
    google_enabled: bool = False
    event_log_ttl_days: int = Field(default=180, ge=1, le=3650)
    span_ttl_days: int = Field(default=90, ge=1, le=3650)
    raw_http_ttl_days: int = Field(default=7, ge=1, le=365)
    chat_session_idle_min: int = Field(default=30, ge=1, le=1440)
    chat_history_limit: int = Field(default=20, ge=1, le=100)
    chat_history_tools: bool = True
    # trả lời dạng stream (D23): tắt = gọi mô hình một lần; cửa sổ gom chữ mỗi sự kiện `agent:token`
    chat_stream: bool = True
    chat_stream_flush_ms: int = Field(default=50, ge=20, le=1000)
    # chống spam trợ lý: tin / phút · giờ · ngày theo user (0 = không giới hạn) + luật tự chặn
    chat_per_minute: int = Field(default=10, ge=0, le=100_000)
    chat_per_hour: int = Field(default=100, ge=0, le=100_000)
    chat_per_day: int = Field(default=400, ge=0, le=100_000)
    chat_autoblock: bool = True
    chat_autoblock_strikes: int = Field(default=5, ge=1, le=100)
    chat_autoblock_window_min: int = Field(default=10, ge=1, le=1440)
    chat_autoblock_minutes: int = Field(default=30, ge=1, le=10_080)


class SettingsSnapshot(BaseModel):
    values: SystemSettings
    defaults_applied: list[str]


_last_logged: str | None = None


def _clean(raw: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    """Giữ khoá đã cấu hình và hợp lệ; trả thêm danh sách khoá đang dùng mặc định."""
    kept: dict[str, Any] = {}
    for name in SystemSettings.model_fields:
        if not raw or name not in raw:
            continue
        try:
            SystemSettings.model_validate({name: raw[name]})
        except ValidationError as exc:
            logger.warning("cài đặt %s đã lưu không hợp lệ, dùng mặc định: %s", name, exc, extra={"loc": "sys0702"})
            continue
        kept[name] = raw[name]
    return kept, [name for name in SystemSettings.model_fields if name not in kept]


def _snapshot(raw: dict[str, Any] | None) -> SettingsSnapshot:
    global _last_logged
    kept, defaults = _clean(raw)
    snap = SettingsSnapshot(values=SystemSettings.model_validate(kept), defaults_applied=defaults)
    line = f"{snap.values.model_dump()} DEFAULTS_APPLIED=[{', '.join(defaults)}]"
    if line != _last_logged:  # chỉ log khi giá trị hiệu lực đổi — không lặp mỗi lần cache hết hạn
        _last_logged = line
        logger.info("cài đặt hệ thống hiệu lực: %s", line, extra={"loc": "sys0701"})
    return snap


def _redis():
    conns = get_connections()
    return conns.redis.rw if conns.redis is not None else None


async def _cache_get() -> SettingsSnapshot | None:
    redis = _redis()
    if redis is None:
        return None
    try:
        raw = await redis.get(CACHE_KEY)
    except Exception as exc:  # noqa: BLE001 — Redis lỗi thì đọc thẳng DB, không làm hỏng request
        logger.warning("đọc cache cài đặt lỗi: %s", exc, extra={"loc": "sys0703"})
        return None
    if not raw:
        return None
    try:
        return SettingsSnapshot.model_validate_json(raw)
    except ValidationError as exc:
        logger.warning("cache cài đặt hỏng, xoá: %s", exc, extra={"loc": "sys0705"})
        await redis.delete(CACHE_KEY)
        return None


async def _cache_fill(snap: SettingsSnapshot) -> None:
    """Ghi cache khi đang trống (NX) — không đè giá trị mới mà process vừa lưu đặt sau commit."""
    redis = _redis()
    if redis is None:
        return
    try:
        await redis.set(CACHE_KEY, snap.model_dump_json(), ex=CACHE_TTL, nx=True)
    except Exception as exc:  # noqa: BLE001 — cache chỉ để nhanh; lỗi không làm hỏng request
        logger.warning("ghi cache cài đặt lỗi: %s", exc, extra={"loc": "sys0704"})


async def _cached(load: Callable[[], Awaitable[SettingsSnapshot]]) -> SettingsSnapshot:
    hit = await _cache_get()
    if hit is not None:
        return hit
    snap = await load()
    await _cache_fill(snap)
    return snap


async def _row_snapshot(session: AsyncSession) -> SettingsSnapshot:
    row = await session.get(SystemSettingsRow, 1)
    return _snapshot(row.data if row else None)


async def settings_snapshot(session: AsyncSession, *, fresh: bool = False) -> SettingsSnapshot:
    """Giá trị hiệu lực + khoá đang dùng mặc định. `fresh=True` bỏ qua cache (đọc trong transaction đang ghi)."""
    if fresh:
        return await _row_snapshot(session)
    return await _cached(lambda: _row_snapshot(session))


async def get_system_settings(session: AsyncSession) -> SystemSettings:
    return (await settings_snapshot(session)).values


async def cached_system_settings() -> SystemSettings:
    """Như `get_system_settings` nhưng tự mở session RO khi cache trống — cho code nền không có session."""

    async def load() -> SettingsSnapshot:
        async with get_connections().postgres.ro() as session:
            return await _row_snapshot(session)

    return (await _cached(load)).values


async def update_system_settings(
    session: AsyncSession, patch: dict[str, Any], *, by: uuid.UUID | None = None
) -> SystemSettings:
    """Gộp `patch` vào khoá đã cấu hình (khoá dòng), validate cả bộ — lỗi → 1002. Cache + broadcast chạy SAU commit."""
    stmt = select(SystemSettingsRow).where(SystemSettingsRow.id == 1).with_for_update()
    row = (await session.exec(stmt)).first() or SystemSettingsRow(id=1, data={})
    kept, _ = _clean(row.data)
    merged = {**kept, **{k: v for k, v in patch.items() if k in SystemSettings.model_fields}}
    try:
        value = SystemSettings.model_validate(merged)
    except ValidationError as exc:
        raise AppException(1002, status_code=422, data=exc.errors(include_url=False)) from exc
    row.data = {name: getattr(value, name) for name in merged}
    row.updated_by, row.updated_at = by, datetime.now(UTC)
    session.add(row)
    await session.flush()
    snap = _snapshot(row.data)

    async def refresh_cache() -> None:
        redis = _redis()
        if redis is not None:
            await redis.set(CACHE_KEY, snap.model_dump_json(), ex=CACHE_TTL)

    async def announce() -> None:
        await broadcast(BROADCAST_TOPIC, {})

    after_commit(session, refresh_cache)
    after_commit(session, announce)
    return value


@on_broadcast(BROADCAST_TOPIC)
async def on_settings_changed(data: dict) -> None:
    """Mọi process: xoá cache — lần đọc sau lấy từ DB (đã commit)."""
    redis = _redis()
    if redis is not None:
        await redis.delete(CACHE_KEY)
