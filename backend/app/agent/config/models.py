"""Bảng cấu hình agent (migration `0004_agent_config`). Chỉ superadmin ghi (Agent Studio)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

PROVIDER_KINDS: tuple[str, ...] = ("openai", "anthropic", "google_genai", "openai_compatible")
HOOK_POINTS: tuple[str, ...] = ("before_run", "before_tool", "after_tool", "after_run")
POLICIES: tuple[str, ...] = ("auto", "confirm", "deny")


def _now() -> datetime:
    return datetime.now(UTC)


def _ts(*, onupdate: bool = False) -> Column:
    return Column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), onupdate=_now if onupdate else None
    )


def _jsonb(default: str = "{}") -> Column:
    return Column(JSONB, nullable=False, server_default=text(f"'{default}'::jsonb"))


def _price() -> Column:
    return Column(Numeric(12, 6), nullable=False, server_default="0")


class AgentProvider(SQLModel, table=True):
    __tablename__ = "agent_providers"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('openai', 'anthropic', 'google_genai', 'openai_compatible')", name="ck_agent_providers_kind"
        ),
        CheckConstraint("status IN ('active', 'disabled')", name="ck_agent_providers_status"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=100, unique=True)
    kind: str = Field(max_length=32)
    base_url: str | None = Field(default=None, max_length=500)
    extra_headers: dict = Field(default_factory=dict, sa_column=_jsonb())
    default_params: dict = Field(default_factory=dict, sa_column=_jsonb())
    status: str = Field(default="active", max_length=16)
    created_at: datetime = Field(default_factory=_now, sa_column=_ts())
    updated_at: datetime = Field(default_factory=_now, sa_column=_ts(onupdate=True))


class AgentModel(SQLModel, table=True):
    __tablename__ = "agent_models"
    __table_args__ = (UniqueConstraint("provider_id", "model_id", name="uq_agent_models_provider_model"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    provider_id: uuid.UUID = Field(
        sa_column=Column(ForeignKey("agent_providers.id", ondelete="CASCADE"), nullable=False)
    )
    model_id: str = Field(max_length=200)
    name: str = Field(max_length=100)
    input_price_per_1m: Decimal = Field(default=Decimal(0), sa_column=_price())
    output_price_per_1m: Decimal = Field(default=Decimal(0), sa_column=_price())
    cache_read_price_per_1m: Decimal = Field(default=Decimal(0), sa_column=_price())
    cache_write_price_per_1m: Decimal = Field(default=Decimal(0), sa_column=_price())
    context_window: int | None = Field(default=None)
    status: str = Field(default="active", max_length=16)
    created_at: datetime = Field(default_factory=_now, sa_column=_ts())


class Agent(SQLModel, table=True):
    __tablename__ = "agents"
    __table_args__ = (
        CheckConstraint("kind IN ('specialist', 'orchestrator')", name="ck_agents_kind"),
        CheckConstraint("key_strategy IN ('round_robin', 'auto')", name="ck_agents_key_strategy"),
        CheckConstraint("visible_to IN ('all', 'roles')", name="ck_agents_visible_to"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    slug: str = Field(max_length=64, unique=True)
    name: str = Field(max_length=100)
    kind: str = Field(default="specialist", max_length=16)
    description: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))
    instructions: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))
    persona_shared: bool = True
    starters: list = Field(default_factory=list, sa_column=_jsonb("[]"))
    model_id: uuid.UUID | None = Field(
        default=None, sa_column=Column(ForeignKey("agent_models.id", ondelete="SET NULL"), nullable=True)
    )
    params_override: dict = Field(default_factory=dict, sa_column=_jsonb())
    # cột cũ, không đọc — lịch sử theo cài đặt hệ thống `chat_history_limit`
    history_limit: int = Field(default=20, sa_column=Column(Integer, nullable=False, server_default="20"))
    recursion_limit: int = Field(default=25, sa_column=Column(Integer, nullable=False, server_default="25"))
    timeout_sec: int = Field(default=90, sa_column=Column(Integer, nullable=False, server_default="90"))
    key_strategy: str = Field(default="round_robin", max_length=16)
    key_cooldown_sec: int = Field(default=300, sa_column=Column(Integer, nullable=False, server_default="300"))
    visible_to: str = Field(default="all", max_length=8)
    visible_roles: list = Field(default_factory=list, sa_column=_jsonb("[]"))
    is_active: bool = True
    created_at: datetime = Field(default_factory=_now, sa_column=_ts())
    updated_at: datetime = Field(default_factory=_now, sa_column=_ts(onupdate=True))


class AgentKey(SQLModel, table=True):
    __tablename__ = "agent_keys"

    agent_id: uuid.UUID = Field(sa_column=Column(ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True))
    credential_id: uuid.UUID = Field(
        sa_column=Column(ForeignKey("credentials.id", ondelete="RESTRICT"), primary_key=True)
    )
    enabled: bool = True


class AgentLimit(SQLModel, table=True):
    __tablename__ = "agent_limits"

    agent_id: uuid.UUID = Field(sa_column=Column(ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True))
    per_minute: int | None = None
    per_hour: int | None = None
    per_day: int | None = None
    tokens_per_day: int | None = None


class AgentUserLimit(SQLModel, table=True):
    __tablename__ = "agent_user_limits"

    agent_id: uuid.UUID = Field(sa_column=Column(ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True))
    user_id: uuid.UUID = Field(sa_column=Column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True))
    per_minute: int | None = None
    per_hour: int | None = None
    per_day: int | None = None
    tokens_per_day: int | None = None


class AgentToolset(SQLModel, table=True):
    __tablename__ = "agent_toolsets"

    agent_id: uuid.UUID = Field(sa_column=Column(ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True))
    toolset: str = Field(sa_column=Column(String(32), primary_key=True))


class AgentToolOverride(SQLModel, table=True):
    __tablename__ = "agent_tool_overrides"
    __table_args__ = (CheckConstraint("policy IN ('auto', 'confirm', 'deny')", name="ck_agent_tool_overrides_policy"),)

    agent_id: uuid.UUID = Field(sa_column=Column(ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True))
    operation: str = Field(sa_column=Column(String(128), primary_key=True))
    policy: str | None = Field(default=None, max_length=8)
    locked_params: dict = Field(default_factory=dict, sa_column=_jsonb())
    default_params: dict = Field(default_factory=dict, sa_column=_jsonb())


class AgentHook(SQLModel, table=True):
    __tablename__ = "agent_hooks"
    __table_args__ = (
        CheckConstraint(
            "point IN ('before_run', 'before_tool', 'after_tool', 'after_run')", name="ck_agent_hooks_point"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    agent_id: uuid.UUID = Field(
        sa_column=Column(ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    )
    name: str = Field(default="", max_length=100)
    point: str = Field(max_length=16)
    conditions: list = Field(default_factory=list, sa_column=_jsonb("[]"))
    action: str = Field(max_length=32)
    action_config: dict = Field(default_factory=dict, sa_column=_jsonb())
    position: int = Field(default=0)
    enabled: bool = True
    created_at: datetime = Field(default_factory=_now, sa_column=_ts())


class AgentSystemPrompt(SQLModel, table=True):
    __tablename__ = "agent_system_prompts"

    key: str = Field(sa_column=Column(String(32), primary_key=True))
    content: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))
    updated_at: datetime = Field(default_factory=_now, sa_column=_ts(onupdate=True))
