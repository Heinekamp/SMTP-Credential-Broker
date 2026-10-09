"""upstream tls_skip_verify

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-09 15:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0019'
down_revision: str | None = '0018'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default so existing accounts get False (verify) on upgrade.
    op.add_column(
        'upstream_accounts',
        sa.Column('tls_skip_verify', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('upstream_accounts', 'tls_skip_verify')
