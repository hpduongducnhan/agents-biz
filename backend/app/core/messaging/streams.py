"""FastStream work: miền khai `@subscriber("<miền>.<việc>")`, gửi bằng `publish("<miền>.<việc>", msg)`.

Queue `bw.<miền>.<việc>` (quorum, message bị reject đi `<queue>.dlq`). Một broker duy nhất (B3): lane chỉ quyết
process `bw consume --lanes …` nào gắn handler.
"""

from __future__ import annotations

import inspect
import re
import typing
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.core.messaging.hub import get_hub
from app.core.messaging.lanes import check_lane
from app.core.messaging.names import dlq_queue, work_queue

EVENT_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


def check_event(event: str, what: str) -> str:
    if not EVENT_RE.match(event):
        raise ValueError(f"{what} '{event}' phải dạng <miền>.<việc>, chữ thường snake_case")
    return event


def queue_name(event: str) -> str:
    return f"bw.{event}"


@dataclass(frozen=True)
class SubscriberSpec:
    event: str
    func: Callable[[Any], Awaitable[None]]
    model: type[BaseModel] | None
    lane: str
    source: str

    @property
    def queue(self) -> str:
        return queue_name(self.event)


_SUBS: dict[str, SubscriberSpec] = {}


def payload_model(func: Callable, *, skip: int = 0) -> type[BaseModel] | None:
    """Kiểu pydantic của tham số dữ liệu (sau `skip` tham số đầu) — không có thì nhận dict."""
    params = list(inspect.signature(func).parameters.values())
    if len(params) != skip + 1:
        raise TypeError(f"{func.__qualname__}: cần đúng {skip + 1} tham số")
    ann = typing.get_type_hints(func).get(params[skip].name)
    return ann if inspect.isclass(ann) and issubclass(ann, BaseModel) else None


def subscriber(event: str, lane: str = "default"):
    check_event(event, "subscriber")
    check_lane(lane)

    def deco(func: Callable) -> Callable:
        if not inspect.iscoroutinefunction(func):
            raise TypeError(f"subscriber '{event}' phải là async def")
        if event in _SUBS:
            raise ValueError(f"subscriber '{event}' bị trùng")
        spec = SubscriberSpec(event, func, payload_model(func), lane, func.__module__)
        _SUBS[event] = spec
        func.__bw_subscriber__ = spec
        return func

    return deco


def all_subscribers() -> list[SubscriberSpec]:
    return list(_SUBS.values())


def _body(msg: BaseModel | dict) -> Any:
    return msg.model_dump(mode="json") if isinstance(msg, BaseModel) else msg


async def publish(event: str, msg: BaseModel | dict, *, message_id: str | None = None) -> str:
    """Gửi việc cho subscriber `event` (bền, ít nhất một lần). Trả cid. Khai queue + DLQ trước khi gửi → gửi lúc
    consumer chưa chạy lần nào cũng không mất."""
    check_event(event, "publish")
    hub = get_hub()
    queue = work_queue(queue_name(event), dlq=True)
    await hub.declare_queue(queue)
    await hub.declare_queue(dlq_queue(queue.name))
    return await hub.publish(_body(msg), queue=queue.name, persist=True, message_id=message_id)
