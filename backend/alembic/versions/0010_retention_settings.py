"""retention_settings

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-15 14:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0010'
down_revision: str | None = '0009'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('relay_settings', sa.Column('mail_log_retention_days', sa.Integer(), nullable=True))
    op.add_column('relay_settings', sa.Column('audit_log_retention_days', sa.Integer(), nullable=True))
    op.add_column(
        'background_job_state', sa.Column('retention_cleanup_last_run_at', sa.DateTime(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('background_job_state', 'retention_cleanup_last_run_at')
    op.drop_column('relay_settings', 'audit_log_retention_days')
    op.drop_column('relay_settings', 'mail_log_retention_days')
