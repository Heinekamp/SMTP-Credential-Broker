"""baseline

Revision ID: 0001
Revises:
Create Date: 2026-09-14

Empty on purpose — establishes the revision chain (Stage 0) before any real
schema exists. Stage 1's schema lands in 0002.
"""
from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
