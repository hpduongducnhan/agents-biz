"""Realtime phía Python: đẩy ra `bw.rt.out` (service realtime Node chuyển tới socket), khai handler cho event client
từ `bw.rt.in` (service realtime đã xác thực JWT và gắn `claims`). Backend không giữ WebSocket nào."""

from __future__ import annotations

import inspect
import re
import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.core.cid import get_cid, set_cid
from app.core.messaging.hub import get_hub
from app.core.messaging.lanes import check_lane
from app.core.messaging.names import RT_IN_EXCHANGE, rt_out_exchange
from app.core.messaging.streams import check_event, payload_model
from app.core.messaging.util import utc_iso
from app.core.security.principal import Principal

ENVELOPE_VERSION = 1
OUT_EVENT_RE = re.compile(r"^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$")
CONTROL_PREFIX = "rt:"  # lệnh cho chính service realtime (không tới client) — chỉ lõi gửi


def check_out_event(event: str) -> str:
    if not OUT_EVENT_RE.match(event) or event.startswith(CONTROL_PREFIX):
        raise ValueError(f"tên event realtime '{event}' sai: cần <miền>:<việc>, tiền tố rt: dành cho lõi")
    return event


def envelope(event: str, data: Any) -> dict:
    return {"v": ENVELOPE_VERSION, "event": event, "data": data, "cid": get_cid(), "ts": utc_iso()}


async def _publish(target: str, event: str, data: Any) -> None:
    if get_cid() is None:
        set_cid(None)  # envelope và property AMQP phải cùng một cid
    await get_hub().publish(
        envelope(event, data if data is not None else {}),
        exchange=rt_out_exchange(),
        routing_key=target,
        persist=False,
        mandatory=False,
    )


async def emit_to_user(user_id: uuid.UUID | str, event: str, data: dict | None = None) -> None:
    await _publish(f"user.{user_id}", check_out_event(event), data)


async def emit_to_users(user_ids: Iterable[uuid.UUID | str], event: str, data: dict | None = None) -> None:
    check_out_event(event)
    for uid in dict.fromkeys(str(u) for u in user_ids):
        await _publish(f"user.{uid}", event, data)


async def emit_to_tenant(tenant_id: uuid.UUID | str, event: str, data: dict | None = None) -> None:
    """Mọi socket của tenant (phòng `tenant:<tid>` — D13). Chỉ dùng cho tín hiệu không lộ dữ liệu (`data:changed`)."""
    await _publish(f"tenant.{tenant_id}", check_out_event(event), data)


async def emit_to_superadmins(event: str, data: dict | None = None) -> None:
    await _publish("sup", check_out_event(event), data)


async def emit_all(event: str, data: dict | None = None) -> None:
    await _publish("all", check_out_event(event), data)


async def rt_revoke(sub: str, *, before: int, until: int) -> None:
    """Lệnh cho MỌI instance realtime: ngắt socket của `sub`, từ chối access token `iat ≤ before` tới `until`."""
    await _publish("all", "rt:revoke", {"sub": str(sub), "before": int(before), "until": int(until)})


@dataclass
class WsContext:
    principal: Principal
    sid: str | None
    cid: str | None
    event: str

    async def reply(self, event: str, data: dict | None = None) -> None:
        """Trả lời người gửi — mọi tab của user nhận."""
        await emit_to_user(self.principal.user_id, event, data)


@dataclass(frozen=True)
class WsSpec:
    event: str
    func: Callable[[WsContext, Any], Awaitable[None]]
    model: type[BaseModel] | None
    lane: str
    permission: str | None

    @property
    def queue(self) -> str:
        return f"{RT_IN_EXCHANGE}.{self.event}"


_WS: dict[str, WsSpec] = {}


def on_ws(event: str, *, permission: str | None = None, lane: str = "default"):
    """Handler cho event client `<miền>.<việc>` — thao tác nhẹ, không ghi tiền."""
    check_event(event, "on_ws")
    check_lane(lane)

    def deco(func: Callable) -> Callable:
        if not inspect.iscoroutinefunction(func):
            raise TypeError(f"on_ws {func.__qualname__} phải là async def")
        if event in _WS:
            raise ValueError(f"on_ws '{event}' bị trùng")
        _WS[event] = WsSpec(event, func, payload_model(func, skip=1), lane, permission)
        return func

    return deco


def all_ws() -> list[WsSpec]:
    return list(_WS.values())
