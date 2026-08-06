"""Create content, taxonomy and comment module tables for M2."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_m2_modules"
down_revision: str | None = "0006_mail_audit_settings"
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
    op.create_table(
        "contents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("slug", sa.String(256), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("rating", sa.Numeric(3, 1), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("type", "slug", name="uq_contents_type_slug"),
    )
    op.create_index("ix_contents_type_status", "contents", ["type", "status", "published_at"])
    op.create_index("ix_contents_owner_id", "contents", ["owner_id"])

    op.create_table(
        "terms",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("group", sa.String(32), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        *_timestamps(),
        sa.UniqueConstraint("content_type", "group", "slug", name="uq_terms_type_group_slug"),
    )
    op.create_index("ix_terms_content_type", "terms", ["content_type"])
    op.create_table(
        "term_relationships",
        sa.Column("content_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "term_id", sa.Uuid(), sa.ForeignKey("terms.id", ondelete="CASCADE"), primary_key=True
        ),
    )
    op.create_index("ix_term_rel_term", "term_relationships", ["term_id", "content_id"])

    op.create_table(
        "comments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), sa.ForeignKey("comments.id"), nullable=True),
        sa.Column("root_id", sa.Uuid(), nullable=True),
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        *_timestamps(),
    )
    op.create_index(
        "ix_comments_target", "comments", ["target_type", "target_id", "status", "created_at"]
    )
    op.create_index("ix_comments_root", "comments", ["root_id"])
    op.create_index("ix_comments_owner", "comments", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_comments_owner", table_name="comments")
    op.drop_index("ix_comments_root", table_name="comments")
    op.drop_index("ix_comments_target", table_name="comments")
    op.drop_table("comments")
    op.drop_index("ix_term_rel_term", table_name="term_relationships")
    op.drop_table("term_relationships")
    op.drop_index("ix_terms_content_type", table_name="terms")
    op.drop_table("terms")
    op.drop_index("ix_contents_owner_id", table_name="contents")
    op.drop_index("ix_contents_type_status", table_name="contents")
    op.drop_table("contents")
