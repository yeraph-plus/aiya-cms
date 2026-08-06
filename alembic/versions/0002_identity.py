"""Create the identity tables: users, identities, organizations (M1.5).

Contract source: context/kernel/identity.md §5, ADR-0017. Mirrors the models
registered in inc/kernel/identity/models.py.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_identity"
down_revision: str | None = "0001_m0_empty"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("username", sa.String(32), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(64), nullable=False),
        sa.Column("avatar_url", sa.String(512), nullable=True),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="active",
        ),
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
        sa.UniqueConstraint("username", name="users_username_key"),
        sa.UniqueConstraint("email", name="users_email_key"),
    )
    op.create_table(
        "identities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_uid", sa.String(320), nullable=False),
        sa.Column("secret_hash", sa.String(256), nullable=True),
        sa.Column(
            "verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
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
        sa.UniqueConstraint("provider", "provider_uid", name="identities_provider_uid_key"),
    )
    op.create_index("ix_identities_user_id", "identities", ["user_id"])
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
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
        sa.UniqueConstraint("slug", name="organizations_slug_key"),
    )


def downgrade() -> None:
    op.drop_table("organizations")
    op.drop_table("identities")
    op.drop_table("users")
