"""Add declarative Content fixed columns and query indexes."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_declarative_content_columns"
down_revision: str | None = "0009_password_reset"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "contents",
        sa.Column("excerpt", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "contents",
        sa.Column("comment_count", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "contents",
        sa.Column("trashed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_contents_type_updated",
        "contents",
        ["type", "updated_at", "id"],
    )
    op.create_index(
        "ix_contents_type_comment_count",
        "contents",
        ["type", "comment_count", "id"],
    )
    op.create_index(
        "ix_contents_data",
        "contents",
        ["data"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_contents_data", table_name="contents")
    op.drop_index("ix_contents_type_comment_count", table_name="contents")
    op.drop_index("ix_contents_type_updated", table_name="contents")
    op.drop_column("contents", "trashed_at")
    op.drop_column("contents", "comment_count")
    op.drop_column("contents", "excerpt")
