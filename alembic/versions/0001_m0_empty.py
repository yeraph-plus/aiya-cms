"""Create the empty M0 migration boundary."""

from collections.abc import Sequence

revision: str = "0001_m0_empty"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Leave the database schema empty until M1 models are specified."""
    pass


def downgrade() -> None:
    """Revert the empty M0 migration."""
    pass
