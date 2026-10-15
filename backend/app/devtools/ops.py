"""Công cụ dev cho smoke / E2E: gây lỗi có chủ đích (luồng bắt lỗi → Issues), chạy ngay task định kỳ."""

from __future__ import annotations

from typing import Any

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from app.core.errors import AppException
from app.core.messaging.tasks import scheduled_tasks
from app.core.operations.context import OpContext
from app.core.operations.spec import operation


class DevError(RuntimeError):
    """Lỗi có chủ đích — tên riêng để Issues gom một fingerprint dễ nhận ra."""


class RaiseErrorIn(BaseModel):
    note: str = Field(default="", max_length=200)


@operation(
    "devtools.raise_error",
    title="Gây lỗi thử",
    description="Ném DevError để kiểm luồng bắt lỗi HTTP → Issues và event log ok=false",
    effect="write",
    superadmin=True,
    agent=False,
    agent_reason="công cụ kiểm thử, chỉ có ở môi trường dev / smoke",
    invalidates=("observability",),
)
async def raise_error(ctx: OpContext, inp: RaiseErrorIn) -> None:
    raise DevError(f"devtools: lỗi thử có chủ đích {inp.note}".strip())


class RunTaskIn(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$", max_length=128)


class RunTaskOut(BaseModel):
    name: str
    result: Any = None


@operation(
    "devtools.run_task",
    title="Chạy ngay task định kỳ",
    description="Chạy ngay một task cron / every (không tham số) trong request — E2E không chờ scheduler",
    effect="write",
    superadmin=True,
    agent=False,
    agent_reason="công cụ kiểm thử, chỉ có ở môi trường dev / smoke",
    invalidates=("notifications",),
)
async def run_task(ctx: OpContext, inp: RunTaskIn) -> RunTaskOut:
    spec = next((t for t in scheduled_tasks() if t.name == inp.name), None)
    if spec is None:
        raise AppException(1001, status_code=404, detail=f"Không có task định kỳ '{inp.name}'")
    return RunTaskOut(name=spec.name, result=jsonable_encoder(await spec.func()))
