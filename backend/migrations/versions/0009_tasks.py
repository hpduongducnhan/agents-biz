"""module mẫu Tasks: tasks + task_comments (theo tenant)"""

import sqlalchemy as sa
from alembic import op

revision = "0009_tasks"
down_revision = "0008_chat_blocks"
branch_labels = None
depends_on = None


def _ts(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=None if nullable else sa.text("now()"), nullable=nullable
    )


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="todo", nullable=False),
        sa.Column("priority", sa.String(length=16), server_default="normal", nullable=False),
        _ts("due_at", nullable=True),
        sa.Column("assignee_id", sa.Uuid(), nullable=True),
        sa.Column("position", sa.Float(), server_default="0", nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(length=8), server_default="web", nullable=False),
        sa.Column("agent_run_id", sa.Uuid(), nullable=True),
        _ts("completed_at", nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("status IN ('todo', 'doing', 'done', 'cancelled')", name="ck_tasks_status"),
        sa.CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')", name="ck_tasks_priority"),
        sa.CheckConstraint("source IN ('web', 'agent')", name="ck_tasks_source"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["assignee_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tasks_tenant_id"), "tasks", ["tenant_id"], unique=False)
    op.create_index("ix_tasks_tenant_status_due", "tasks", ["tenant_id", "status", "due_at"])
    op.create_index("ix_tasks_tenant_assignee", "tasks", ["tenant_id", "assignee_id"])
    op.create_table(
        "task_comments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=8), server_default="web", nullable=False),
        _ts("created_at"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_task_comments_tenant_id"), "task_comments", ["tenant_id"], unique=False)
    op.create_index("ix_task_comments_task_created", "task_comments", ["task_id", "created_at"])


def downgrade() -> None:
    op.drop_table("task_comments")
    op.drop_table("tasks")
