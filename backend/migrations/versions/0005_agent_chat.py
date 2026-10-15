"""agent chat theo tenant: agent_sessions, agent_runs, agent_messages, agent_approvals + schema agent_lg"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_agent_chat"
down_revision = "0004_agent_config"
branch_labels = None
depends_on = None


def _ts(name: str, *, nullable: bool = False) -> sa.Column:
    if nullable:
        return sa.Column(name, sa.DateTime(timezone=True), nullable=True)
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)


def _big(name: str) -> sa.Column:
    return sa.Column(name, sa.BigInteger(), server_default="0", nullable=False)


TENANT_TABLES = ("agent_sessions", "agent_runs", "agent_messages", "agent_approvals")


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS agent_lg")
    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("entry_agent_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("last_agent_id", sa.Uuid(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entry_agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["last_agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_sessions_user_updated", "agent_sessions", ["user_id", "updated_at"])
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("entry_agent_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        _big("tokens_in"),
        _big("tokens_out"),
        _big("tokens_cache_read"),
        _big("tokens_cache_write"),
        sa.Column("cost", sa.Numeric(14, 6), server_default="0", nullable=False),
        sa.Column("credential_ids", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        _ts("heartbeat_at", nullable=True),
        _ts("started_at", nullable=True),
        _ts("ended_at", nullable=True),
        _ts("created_at"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'waiting_approval', 'done', 'failed', 'cancelled')",
            name="ck_agent_runs_status",
        ),
        sa.ForeignKeyConstraint(["session_id"], ["agent_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entry_agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_agent_runs_one_open",
        "agent_runs",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running', 'waiting_approval')"),
    )
    op.create_index("ix_agent_runs_status_heartbeat", "agent_runs", ["status", "heartbeat_at"])
    op.create_table(
        "agent_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("client_msg_id", sa.String(length=64), nullable=True),
        _ts("created_at"),
        sa.CheckConstraint("role IN ('user', 'assistant', 'tool')", name="ck_agent_messages_role"),
        sa.ForeignKeyConstraint(["session_id"], ["agent_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "seq", name="uq_agent_messages_session_seq"),
        sa.UniqueConstraint("session_id", "client_msg_id", name="uq_agent_messages_client_msg"),
    )
    op.create_table(
        "agent_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("tool_call_id", sa.String(length=128), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("operation", sa.String(length=128), nullable=False),
        sa.Column("args", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        _ts("decided_at", nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _ts("created_at"),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired')", name="ck_agent_approvals_status"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "tool_call_id", name="uq_agent_approvals_call"),
    )
    op.create_index("ix_agent_approvals_status_expires", "agent_approvals", ["status", "expires_at"])
    for table in TENANT_TABLES:  # dữ liệu hội thoại theo tenant (D22)
        op.add_column(table, sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False))
        op.create_index(op.f(f"ix_{table}_tenant_id"), table, ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_agent_approvals_status_expires", table_name="agent_approvals")
    op.drop_table("agent_approvals")
    op.drop_table("agent_messages")
    op.drop_index("ix_agent_runs_status_heartbeat", table_name="agent_runs")
    op.drop_index("uq_agent_runs_one_open", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_agent_sessions_user_updated", table_name="agent_sessions")
    op.drop_table("agent_sessions")
    op.execute("DROP SCHEMA IF EXISTS agent_lg CASCADE")
