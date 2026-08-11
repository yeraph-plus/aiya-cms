"""add comments capability tables

Revision ID: 0002_comments
Revises: 0001_initial
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_comments"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "comments",
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=200), nullable=False),
        sa.Column("author_type", sa.String(length=64), nullable=False),
        sa.Column("author_id", sa.String(length=200), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("moderation_reason", sa.String(length=1000), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_comments_version"),
        sa.CheckConstraint(
            "status IN ('pending', 'published', 'rejected', 'deleted')",
            name="ck_comments_status",
        ),
        sa.ForeignKeyConstraint(["parent_id"], ["comments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_comments_parent_id", "comments", ["parent_id"], unique=False)
    op.create_index(
        "ix_comments_target_status",
        "comments",
        ["target_type", "target_id", "status"],
        unique=False,
    )
    op.create_index("ix_comments_author", "comments", ["author_type", "author_id"], unique=False)
    op.create_index("ix_comments_admin_order", "comments", ["submitted_at", "id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_comments_admin_order", table_name="comments")
    op.drop_index("ix_comments_author", table_name="comments")
    op.drop_index("ix_comments_target_status", table_name="comments")
    op.drop_index("ix_comments_parent_id", table_name="comments")
    op.drop_table("comments")
