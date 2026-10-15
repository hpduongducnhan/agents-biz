"""Bảng `orchestrator_routes` (migration `0007_agent_routes`): orchestrator → chuyên gia, kèm ý định + ví dụ."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

MAX_ROUTES = 20


class OrchestratorRoute(SQLModel, table=True):
    __tablename__ = "orchestrator_routes"

    orchestrator_id: uuid.UUID = Field(sa_column=Column(ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True))
    agent_id: uuid.UUID = Field(sa_column=Column(ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True))
    intent: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))
    examples: list = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    )
    position: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default="0"))
    enabled: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, server_default=text("true")))
