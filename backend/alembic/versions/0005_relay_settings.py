"""relay_settings

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-14 18:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'relay_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('connection_test_interval_minutes', sa.Integer(), nullable=True),
        sa.Column('update_check_enabled', sa.Boolean(), nullable=False),
        sa.Column('notify_recipients', sa.JSON(), nullable=False),
        sa.Column('notify_sender_id', sa.Integer(), nullable=True),
        sa.Column('notify_on_health_degraded', sa.Boolean(), nullable=False),
        sa.Column('notify_on_upstream_test_failure', sa.Boolean(), nullable=False),
        sa.Column('notify_on_app_update_available', sa.Boolean(), nullable=False),
        sa.Column('notify_on_postfix_update_available', sa.Boolean(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['notify_sender_id'], ['senders.id'],
            name=op.f('fk_relay_settings_notify_sender_id_senders'), ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_relay_settings')),
    )


def downgrade() -> None:
    op.drop_table('relay_settings')
