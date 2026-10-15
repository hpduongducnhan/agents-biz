"""chống spam trợ lý: agent_chat_blocks"""

import sqlalchemy as sa
from alembic import op

revision = "0008_chat_blocks"
down_revision = "0007_agent_routes"
branch_labels = None
depends_on = None


def _ts(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=None if nullable else sa.text("now()"), nullable=nullable
    )


def upgrade() -> None:
    op.create_table(
        "agent_chat_blocks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        _ts("until", nullable=True),
        sa.Column("reason", sa.Text(), server_default="", nullable=False),
        sa.Column("source", sa.String(length=8), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        _ts("created_at"),
        _ts("lifted_at", nullable=True),
        sa.Column("lifted_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("source IN ('auto', 'manual')", name="ck_agent_chat_blocks_source"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lifted_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_chat_blocks_open",
        "agent_chat_blocks",
        ["user_id"],
        postgresql_where=sa.text("lifted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_agent_chat_blocks_open", table_name="agent_chat_blocks")
    op.drop_table("agent_chat_blocks")
