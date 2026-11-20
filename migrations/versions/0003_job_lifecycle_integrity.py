"""Persist job closure and preserve administrator moderation decisions.

Revision ID: 0003_job_lifecycle_integrity
Revises: 0002_role_normalization
Create Date: 2026-11-20 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0003_job_lifecycle_integrity"
down_revision = "0002_role_normalization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add durable lifecycle facts without changing existing listing states."""
    op.add_column(
        "jobs",
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column(
            "is_moderation_locked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    """Remove lifecycle facts added by this revision."""
    op.drop_column("jobs", "is_moderation_locked")
    op.drop_column("jobs", "closed_at")
