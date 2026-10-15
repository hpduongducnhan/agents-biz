"""agent: credentials, provider, model, agent, pool key, hạn mức, toolset, override, hook, persona"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_agent_config"
down_revision = "0003_notifications_system"
branch_labels = None
depends_on = None


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)


def _jsonb(name: str, default: str = "{}") -> sa.Column:
    return sa.Column(name, postgresql.JSONB(), server_default=sa.text(f"'{default}'::jsonb"), nullable=False)


def _price(name: str) -> sa.Column:
    return sa.Column(name, sa.Numeric(12, 6), server_default="0", nullable=False)


def _limits() -> list[sa.Column]:
    return [sa.Column(n, sa.Integer(), nullable=True) for n in ("per_minute", "per_hour", "per_day", "tokens_per_day")]


def upgrade() -> None:
    op.create_table(
        "agent_providers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        _jsonb("extra_headers"),
        _jsonb("default_params"),
        sa.Column("status", sa.String(length=16), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(
            "kind IN ('openai', 'anthropic', 'google_genai', 'openai_compatible')", name="ck_agent_providers_kind"
        ),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_agent_providers_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=True),
        sa.Column("secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("key_id", sa.String(length=8), nullable=False),
        sa.Column("masked_hint", sa.String(length=32), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("disabled_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=32), server_default="api_key", nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_credentials_status"),
        sa.CheckConstraint("kind IN ('api_key', 'google_service_account')", name="ck_credentials_kind"),
        sa.CheckConstraint("weight BETWEEN 1 AND 100", name="ck_credentials_weight"),
        sa.ForeignKeyConstraint(["provider_id"], ["agent_providers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "agent_models",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        _price("input_price_per_1m"),
        _price("output_price_per_1m"),
        _price("cache_read_price_per_1m"),
        _price("cache_write_price_per_1m"),
        sa.Column("context_window", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        _ts("created_at"),
        sa.ForeignKeyConstraint(["provider_id"], ["agent_providers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_id", "model_id", name="uq_agent_models_provider_model"),
    )
    op.create_table(
        "agents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("instructions", sa.Text(), server_default="", nullable=False),
        sa.Column("persona_shared", sa.Boolean(), nullable=False),
        _jsonb("starters", "[]"),
        sa.Column("model_id", sa.Uuid(), nullable=True),
        _jsonb("params_override"),
        sa.Column("history_limit", sa.Integer(), server_default="20", nullable=False),
        sa.Column("recursion_limit", sa.Integer(), server_default="25", nullable=False),
        sa.Column("timeout_sec", sa.Integer(), server_default="90", nullable=False),
        sa.Column("key_strategy", sa.String(length=16), nullable=False),
        sa.Column("key_cooldown_sec", sa.Integer(), server_default="300", nullable=False),
        sa.Column("visible_to", sa.String(length=8), nullable=False),
        _jsonb("visible_roles", "[]"),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("kind IN ('specialist', 'orchestrator')", name="ck_agents_kind"),
        sa.CheckConstraint("key_strategy IN ('round_robin', 'auto')", name="ck_agents_key_strategy"),
        sa.CheckConstraint("visible_to IN ('all', 'roles')", name="ck_agents_visible_to"),
        sa.ForeignKeyConstraint(["model_id"], ["agent_models.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "agent_keys",
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("credential_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["credential_id"], ["credentials.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("agent_id", "credential_id"),
    )
    op.create_table(
        "agent_limits",
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        *_limits(),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("agent_id"),
    )
    op.create_table(
        "agent_user_limits",
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        *_limits(),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("agent_id", "user_id"),
    )
    op.create_table(
        "agent_toolsets",
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("toolset", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("agent_id", "toolset"),
    )
    op.create_table(
        "agent_tool_overrides",
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=128), nullable=False),
        sa.Column("policy", sa.String(length=8), nullable=True),
        _jsonb("locked_params"),
        _jsonb("default_params"),
        sa.CheckConstraint("policy IN ('auto', 'confirm', 'deny')", name="ck_agent_tool_overrides_policy"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("agent_id", "operation"),
    )
    op.create_table(
        "agent_hooks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("point", sa.String(length=16), nullable=False),
        _jsonb("conditions", "[]"),
        sa.Column("action", sa.String(length=32), nullable=False),
        _jsonb("action_config"),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        _ts("created_at"),
        sa.CheckConstraint(
            "point IN ('before_run', 'before_tool', 'after_tool', 'after_run')", name="ck_agent_hooks_point"
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_agent_hooks_agent_id"), "agent_hooks", ["agent_id"])
    op.create_table(
        "agent_system_prompts",
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), server_default="", nullable=False),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("agent_system_prompts")
    op.drop_index(op.f("ix_agent_hooks_agent_id"), table_name="agent_hooks")
    for name in ("agent_hooks", "agent_tool_overrides", "agent_toolsets", "agent_user_limits", "agent_limits"):
        op.drop_table(name)
    op.drop_table("agent_keys")
    op.drop_table("agents")
    op.drop_table("agent_models")
    op.drop_table("credentials")
    op.drop_table("agent_providers")
