"""rate_limit_burst

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-16 15:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0015'
down_revision: str | None = '0014'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('local_smtp_users', sa.Column('rate_limit_burst', sa.Integer(), nullable=True))

    op.create_table(
        'local_user_burst_buckets',
        sa.Column('local_smtp_user_id', sa.Integer(), nullable=False),
        sa.Column('tokens', sa.Float(), nullable=False),
        sa.Column('last_refill_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['local_smtp_user_id'],
            ['local_smtp_users.id'],
            name=op.f('fk_local_user_burst_buckets_local_smtp_user_id_local_smtp_users'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('local_smtp_user_id', name=op.f('pk_local_user_burst_buckets')),
    )


def downgrade() -> None:
    op.drop_table('local_user_burst_buckets')
    op.drop_column('local_smtp_users', 'rate_limit_burst')
