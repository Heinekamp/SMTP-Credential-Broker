"""rate_limit_cleanup_state

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-16 13:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0014'
down_revision: str | None = '0013'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'background_job_state', sa.Column('rate_limit_cleanup_last_run_at', sa.DateTime(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('background_job_state', 'rate_limit_cleanup_last_run_at')
