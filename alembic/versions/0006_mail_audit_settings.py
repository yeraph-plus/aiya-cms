"""Create mail outbox, append-only audit logs and runtime settings."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_mail_audit_settings"
down_revision: str | None = "0005_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mail_outbox",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("to_addr", sa.String(320), nullable=False),
        sa.Column("template", sa.String(64), nullable=False),
        sa.Column("context", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(1024), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index("ix_mail_outbox_status_attempts", "mail_outbox", ["status", "attempts"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=True),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("context", postgresql.JSONB(), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_audit_logs_action_time", "audit_logs", ["action", "created_at"])
    op.create_index("ix_audit_logs_actor_time", "audit_logs", ["actor_id", "created_at"])

    op.create_table(
        "settings",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("settings")
    op.drop_index("ix_audit_logs_actor_time", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action_time", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_mail_outbox_status_attempts", table_name="mail_outbox")
    op.drop_table("mail_outbox")
