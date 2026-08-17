"""Add optimistic-concurrency versions to administrator catalogs.

Revision ID: 0002_admin_catalog
Revises: 0001_initial
"""

import sqlalchemy as sa

from alembic import op

revision = "0002_admin_catalog"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "points_programs", sa.Column("version", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column(
        "membership_levels", sa.Column("version", sa.Integer(), nullable=False, server_default="1")
    )
    op.alter_column("points_programs", "version", server_default=None)
    op.alter_column("membership_levels", "version", server_default=None)


def downgrade() -> None:
    op.drop_column("membership_levels", "version")
    op.drop_column("points_programs", "version")
