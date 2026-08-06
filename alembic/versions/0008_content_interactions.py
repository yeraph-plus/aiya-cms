"""Replace editorial content rating with user interaction aggregates."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_content_interactions"
down_revision: str | None = "0007_m2_modules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
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


def upgrade() -> None:
    op.alter_column("contents", "view_count", type_=sa.BigInteger(), existing_type=sa.Integer())
    op.drop_column("contents", "rating")
    op.add_column(
        "contents", sa.Column("like_count", sa.BigInteger(), nullable=False, server_default="0")
    )
    op.add_column(
        "contents", sa.Column("rating_sum", sa.BigInteger(), nullable=False, server_default="0")
    )
    op.add_column(
        "contents", sa.Column("rating_count", sa.BigInteger(), nullable=False, server_default="0")
    )

    op.create_table(
        "interactions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("numeric_value", sa.SmallInteger(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "user_id", "target_type", "target_id", "kind", name="uq_interactions_user_target_kind"
        ),
    )
    op.create_index(
        "ix_interactions_user_kind_created",
        "interactions",
        ["user_id", "kind", "created_at"],
    )
    op.create_index(
        "ix_interactions_target_kind",
        "interactions",
        ["target_type", "target_id", "kind"],
    )


def downgrade() -> None:
    op.drop_index("ix_interactions_target_kind", table_name="interactions")
    op.drop_index("ix_interactions_user_kind_created", table_name="interactions")
    op.drop_table("interactions")
    op.drop_column("contents", "rating_count")
    op.drop_column("contents", "rating_sum")
    op.drop_column("contents", "like_count")
    op.add_column("contents", sa.Column("rating", sa.Numeric(3, 1), nullable=True))
    op.alter_column("contents", "view_count", type_=sa.Integer(), existing_type=sa.BigInteger())
