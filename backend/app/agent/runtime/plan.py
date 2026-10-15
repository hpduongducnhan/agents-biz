"""Kế hoạch của một lượt: các bước chuyên gia + con trỏ — lưu `agent_runs.plan` để resume đúng bước sau duyệt."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

MAX_HANDOFFS = 2


class PlanStep(BaseModel):
    agent_id: uuid.UUID
    slug: str
    name: str
    task: str = ""
    via: str = "router"  # router | handoff | entry


class Plan(BaseModel):
    steps: list[PlanStep] = Field(default_factory=list)
    cursor: int = 0
    handoffs: int = 0
    clarify: str | None = None
    router: dict[str, Any] = Field(default_factory=dict)  # decision gốc, fallback, sticky — cho trace / debug

    @property
    def done(self) -> bool:
        return self.cursor >= len(self.steps)

    @property
    def current(self) -> PlanStep | None:
        return None if self.done else self.steps[self.cursor]

    def insert_after_current(self, step: PlanStep) -> None:
        self.steps.insert(self.cursor + 1, step)
        self.handoffs += 1

    def dump(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def load(raw: dict[str, Any] | None) -> Plan | None:
    return Plan.model_validate(raw) if raw else None
