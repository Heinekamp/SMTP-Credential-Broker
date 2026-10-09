"""admin totp_last_used_step

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-09 18:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0020'
down_revision: str | None = '0019'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('admin_users', sa.Column('totp_last_used_step', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('admin_users', 'totp_last_used_step')
