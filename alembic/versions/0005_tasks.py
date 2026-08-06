"""Create task instance persistence for M1.10 tasks."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_tasks"
down_revision: str | None = "0004_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_instances",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", postgresql.JSONB(), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("timeout_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_task_instances_type_state",
        "task_instances",
        ["task_type", "state"],
    )
    op.create_index(
        "uq_task_instances_idem",
        "task_instances",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.and_(
            sa.column("idempotency_key").is_not(None),
            sa.column("state").not_in(["succeeded", "failed", "cancelled"]),
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_task_instances_idem", table_name="task_instances")
    op.drop_index("ix_task_instances_type_state", table_name="task_instances")
    op.drop_table("task_instances")
