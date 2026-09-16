"""rate_limit_abuse_detection

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-16 16:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0016'
down_revision: str | None = '0015'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'local_smtp_users', sa.Column('rate_limit_defer_streak_started_at', sa.DateTime(), nullable=True)
    )
    op.add_column(
        'relay_settings',
        sa.Column('notify_on_rate_limit_abuse', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'relay_settings',
        sa.Column(
            'rate_limit_abuse_auto_disable_enabled', sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        'relay_settings',
        sa.Column('rate_limit_abuse_threshold_minutes', sa.Integer(), nullable=False, server_default='10'),
    )
    op.add_column(
        'background_job_state',
        sa.Column('rate_limit_abuse_active', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('background_job_state', 'rate_limit_abuse_active')
    op.drop_column('relay_settings', 'rate_limit_abuse_threshold_minutes')
    op.drop_column('relay_settings', 'rate_limit_abuse_auto_disable_enabled')
    op.drop_column('relay_settings', 'notify_on_rate_limit_abuse')
    op.drop_column('local_smtp_users', 'rate_limit_defer_streak_started_at')
