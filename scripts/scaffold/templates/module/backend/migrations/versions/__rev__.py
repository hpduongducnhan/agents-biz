"""module __title_vi__: __mod__ (theo tenant)"""

import sqlalchemy as sa
from alembic import op

revision = "__rev__"
down_revision = "__down_rev__"
branch_labels = None
depends_on = None


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "__mod__",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(length=8), server_default="web", nullable=False),
        sa.Column("agent_run_id", sa.Uuid(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("status IN ('open', 'done')", name="ck___mod___status"),
        sa.CheckConstraint("source IN ('web', 'agent')", name="ck___mod___source"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix___mod___tenant_id"), "__mod__", ["tenant_id"], unique=False)
    op.create_index("ix___mod___tenant_status", "__mod__", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_table("__mod__")
