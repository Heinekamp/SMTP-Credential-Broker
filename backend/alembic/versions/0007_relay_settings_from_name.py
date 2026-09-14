"""relay_settings_from_name

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-14 19:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: str | None = '0006'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('relay_settings', sa.Column('notify_from_name', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('relay_settings', 'notify_from_name')
