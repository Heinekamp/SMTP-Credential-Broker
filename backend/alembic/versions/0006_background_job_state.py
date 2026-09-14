"""background_job_state

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-14 18:05:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: str | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'background_job_state',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('connection_test_last_run_at', sa.DateTime(), nullable=True),
        sa.Column('update_check_last_run_at', sa.DateTime(), nullable=True),
        sa.Column('latest_app_version', sa.String(), nullable=True),
        sa.Column('latest_app_version_checked_at', sa.DateTime(), nullable=True),
        sa.Column('latest_postfix_version', sa.String(), nullable=True),
        sa.Column('latest_postfix_version_checked_at', sa.DateTime(), nullable=True),
        sa.Column('app_update_last_emailed_version', sa.String(), nullable=True),
        sa.Column('app_update_acknowledged_version', sa.String(), nullable=True),
        sa.Column('postfix_update_last_emailed_version', sa.String(), nullable=True),
        sa.Column('postfix_update_acknowledged_version', sa.String(), nullable=True),
        sa.Column('health_degraded_active', sa.Boolean(), nullable=False),
        sa.Column('upstream_test_failure_active', sa.Boolean(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_background_job_state')),
    )


def downgrade() -> None:
    op.drop_table('background_job_state')
