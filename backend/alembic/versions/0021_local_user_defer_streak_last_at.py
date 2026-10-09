"""local user defer streak last_at

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-09 20:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0021'
down_revision: str | None = '0020'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing streaks get no last_at, so they count as inactive: an old
    # single-rejection "streak" stops looking like ongoing abuse (#183).
    op.add_column('local_smtp_users', sa.Column('rate_limit_defer_streak_last_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('local_smtp_users', 'rate_limit_defer_streak_last_at')
