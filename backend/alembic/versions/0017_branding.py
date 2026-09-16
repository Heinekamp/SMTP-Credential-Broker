"""branding

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-16 17:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0017'
down_revision: str | None = '0016'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('relay_settings', sa.Column('accent_color', sa.String(), nullable=True))
    op.add_column('relay_settings', sa.Column('logo_image', sa.LargeBinary(), nullable=True))
    op.add_column('relay_settings', sa.Column('logo_content_type', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('relay_settings', 'logo_content_type')
    op.drop_column('relay_settings', 'logo_image')
    op.drop_column('relay_settings', 'accent_color')
