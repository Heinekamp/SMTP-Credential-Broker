"""mail_log_ingest_state_inode

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-15 13:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: str | None = '0008'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('mail_log_ingest_state', sa.Column('maillog_inode', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('mail_log_ingest_state', 'maillog_inode')
