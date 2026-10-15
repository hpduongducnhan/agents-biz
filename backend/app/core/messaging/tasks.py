"""taskiq trên RabbitMQ: miền khai `@task("<miền>.<việc>", lane=…)`, gọi `await t.kiq(...)`; queue theo lane.
Task có `cron` / `every` do scheduler (bản giữ khoá leader) kick qua `TaskScheduleSource`."""

from __future__ import annotations

import functools
import inspect
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from taskiq import (
    NoResultError,
    ScheduledTask,
    ScheduleSource,
    SimpleRetryMiddleware,
    TaskiqMessage,
    TaskiqMiddleware,
    TaskiqResult,
)
from taskiq.kicker import AsyncKicker
from taskiq_aio_pika import AioPikaBroker, Exchange, Queue

from app.core.cid import get_cid, new_cid, set_cid
from app.core.logging import get_logger
from app.core.messaging.hub import get_hub
from app.core.messaging.lanes import check_lane, task_queue
from app.core.messaging.names import TQ_DEAD_LETTER, TQ_EXCHANGE
from app.core.settings import Settings
from app.observability.sinks import capture_issue

logger = get_logger(__name__)
TASK_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
Every = int | Callable[[Settings], float]


@dataclass(frozen=True)
class TaskSpec:
    name: str
    func: Callable[..., Awaitable[Any]]
    lane: str
    retry: int
    timeout: float | None
    cron: str | None
    every: Every | None
    source: str

    def raw_every(self, settings: Settings) -> float | None:
        if self.every is None:
            return None
        return float(self.every(settings) if callable(self.every) else self.every)

    def interval(self, settings: Settings) -> int | None:
        """Chu kỳ `every` (giây) cho scheduler — taskiq chỉ nhận số nguyên ≥ 1."""
        raw = self.raw_every(settings)
        return None if raw is None else max(1, round(raw))


_TASKS: dict[str, TaskSpec] = {}


def task_labels(spec: TaskSpec) -> dict[str, Any]:
    labels: dict[str, Any] = {"queue_name": task_queue(spec.lane)}
    if spec.retry > 0:
        labels |= {"retry_on_error": True, "max_retries": spec.retry + 1}  # max_retries = tổng số lần chạy
    if spec.timeout:
        labels["timeout"] = spec.timeout
    return labels


class AppTask:
    """Thứ `@task` trả về: `await t.kiq(...)` gửi vào queue của lane; `await t(...)` chạy thẳng."""

    def __init__(self, spec: TaskSpec) -> None:
        self.spec = spec
        functools.update_wrapper(self, spec.func)

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return await self.spec.func(*args, **kwargs)

    async def kiq(self, *args: Any, **kwargs: Any) -> str:
        broker = await get_hub().task_broker()
        sent = await AsyncKicker(self.spec.name, broker, task_labels(self.spec)).kiq(*args, **kwargs)
        return sent.task_id


def task(
    name: str,
    *,
    lane: str = "default",
    retry: int = 1,
    timeout: float | None = None,
    cron: str | None = None,
    every: Every | None = None,
):
    if not TASK_NAME_RE.match(name):
        raise ValueError(f"tên task '{name}' phải dạng <miền>.<việc> chữ thường")
    if cron and every is not None:
        raise ValueError("cron và every loại trừ nhau")
    if retry < 0:
        raise ValueError("retry phải ≥ 0")
    check_lane(lane)

    def deco(func: Callable) -> AppTask:
        if not inspect.iscoroutinefunction(func):
            raise TypeError(f"task {name} phải là async def")
        if name in _TASKS:
            raise ValueError(f"task '{name}' bị trùng")
        spec = TaskSpec(name, func, lane, retry, timeout, cron, every, func.__module__)
        _TASKS[name] = spec
        return AppTask(spec)

    return deco


def all_tasks() -> list[TaskSpec]:
    return list(_TASKS.values())


def scheduled_tasks() -> list[TaskSpec]:
    return [s for s in _TASKS.values() if s.cron or s.every is not None]


def _flag(value: Any) -> bool:
    return str(value).lower() == "true"


class CidMiddleware(TaskiqMiddleware):
    """cid đi theo label `cid`: gửi lấy từ context (cron / không có → sinh mới); chạy đặt lại vào context."""

    def pre_send(self, message: TaskiqMessage) -> TaskiqMessage:
        message.labels.setdefault("cid", get_cid() or new_cid())
        return message

    def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        set_cid(str(message.labels.get("cid") or ""))
        return message


class ErrorMiddleware(TaskiqMiddleware):
    """Log mỗi lần lỗi (tq0500); lần cuối (hết retry) → ghi issue."""

    async def on_error(self, message: TaskiqMessage, result: TaskiqResult[Any], exception: BaseException) -> None:
        if isinstance(exception, NoResultError):
            return
        attempt = int(message.labels.get("_retries", 0)) + 1
        final = not _flag(message.labels.get("retry_on_error")) or attempt >= int(message.labels.get("max_retries", 1))
        logger.warning(
            "task %s lỗi (lần %d%s): %s",
            message.task_name,
            attempt,
            ", hết lượt" if final else "",
            exception,
            extra={"loc": "tq0500"},
        )
        if final:  # capture_issue không bao giờ ném — ném từ on_error làm task bị giao lại → chạy trùng
            await capture_issue(
                exception,
                source="task",
                loc="tq0500",
                context={"task": message.task_name, "task_id": message.task_id, "attempts": attempt},
            )


def build_task_broker(url: str, queues: list[str], *, worker: bool) -> AioPikaBroker:
    broker = AioPikaBroker(
        url,
        exchange=Exchange(name=TQ_EXCHANGE),
        task_queues=[Queue(name=q) for q in queues],
        dead_letter_queue=Queue(name=TQ_DEAD_LETTER),
    ).with_middlewares(CidMiddleware(), SimpleRetryMiddleware(default_retry_count=1), ErrorMiddleware())
    broker.is_worker_process = worker  # phải đặt TRƯỚC startup: worker mở thêm kênh đọc
    return broker


def register_tasks(broker: AioPikaBroker, specs: list[TaskSpec]) -> None:
    for spec in specs:
        broker.register_task(spec.func, task_name=spec.name)


class TaskScheduleSource(ScheduleSource):
    """Lịch của mọi task khai `cron` / `every` — scheduler (bản giữ khoá leader) đọc."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._warned: set[str] = set()

    def _interval(self, spec: TaskSpec) -> int | None:
        interval = spec.interval(self.settings)
        raw = spec.raw_every(self.settings)
        if raw is not None and raw != interval and spec.name not in self._warned:
            self._warned.add(spec.name)
            logger.warning(
                "task %s: every=%s giây không dùng được với taskiq → dùng %s; DEFAULTS_APPLIED=[every=%s]",
                spec.name,
                raw,
                interval,
                interval,
                extra={"loc": "tq0101"},
            )
        return interval

    async def get_schedules(self) -> list[ScheduledTask]:
        return [
            ScheduledTask(
                task_name=spec.name,
                labels=task_labels(spec),
                args=[],
                kwargs={},
                schedule_id=spec.name,
                cron=spec.cron,
                interval=self._interval(spec),
            )
            for spec in scheduled_tasks()
        ]

    def pre_send(self, task: ScheduledTask) -> None:
        task.labels["cid"] = new_cid()  # mỗi lần cron là điểm khởi đầu chuỗi → cid mới (không kế thừa context)
