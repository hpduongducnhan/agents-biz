"""agent routes: orchestrator_routes (router → chuyên gia) + agent_runs.plan (bước của lượt, resume theo cursor)"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_agent_routes"
down_revision = "0005_agent_chat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orchestrator_routes",
        sa.Column("orchestrator_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("intent", sa.Text(), server_default="", nullable=False),
        sa.Column("examples", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.ForeignKeyConstraint(["orchestrator_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("orchestrator_id", "agent_id"),
    )
    op.add_column("agent_runs", sa.Column("plan", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_runs", "plan")
    op.drop_table("orchestrator_routes")
