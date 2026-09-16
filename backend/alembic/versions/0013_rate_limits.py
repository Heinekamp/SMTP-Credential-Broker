"""rate_limits

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-16 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0013'
down_revision: str | None = '0012'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('local_smtp_users', sa.Column('rate_limit_per_hour', sa.Integer(), nullable=True))
    op.add_column('upstream_accounts', sa.Column('rate_limit_per_hour', sa.Integer(), nullable=True))

    op.create_table(
        'local_user_rate_limit_counters',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('local_smtp_user_id', sa.Integer(), nullable=False),
        sa.Column('window_start', sa.DateTime(), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ['local_smtp_user_id'],
            ['local_smtp_users.id'],
            name=op.f('fk_local_user_rate_limit_counters_local_smtp_user_id_local_smtp_users'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_local_user_rate_limit_counters')),
        sa.UniqueConstraint(
            'local_smtp_user_id',
            'window_start',
            name=op.f('uq_local_user_rate_limit_counters_local_smtp_user_id'),
        ),
    )


def downgrade() -> None:
    op.drop_table('local_user_rate_limit_counters')
    op.drop_column('upstream_accounts', 'rate_limit_per_hour')
    op.drop_column('local_smtp_users', 'rate_limit_per_hour')
