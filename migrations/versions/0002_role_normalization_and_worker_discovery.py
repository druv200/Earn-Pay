"""Normalize legacy role values to canonical 'worker'/'employer' and index worker discovery.

Revision ID: 0002_role_normalization
Revises: 0001_initial_schema
Create Date: 2026-10-25 15:05:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_role_normalization"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Safely map legacy 'employee' role values to 'worker' and add discovery index."""
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE users SET role = 'worker' "
            "WHERE lower(trim(role)) IN ('employee', 'job_seeker', 'jobseeker')"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE users SET role = 'employer' "
            "WHERE lower(trim(role)) IN ('hiring', 'business')"
        )
    )
    op.create_index(
        "ix_worker_profiles_public_availability",
        "worker_profiles",
        ["is_profile_public", "availability"],
        unique=False,
    )


def downgrade() -> None:
    """Revert worker discovery index while preserving valid user records."""
    op.drop_index("ix_worker_profiles_public_availability", table_name="worker_profiles")
