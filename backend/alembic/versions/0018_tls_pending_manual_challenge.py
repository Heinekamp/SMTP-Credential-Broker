"""tls_pending_manual_challenge

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-18 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0018'
down_revision: str | None = '0017'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'tls_pending_manual_challenge',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('domain', sa.String(), nullable=False),
        sa.Column('contact_email', sa.String(), nullable=True),
        sa.Column('record_name', sa.String(), nullable=False),
        sa.Column('record_value', sa.String(), nullable=False),
        sa.Column('order_json', sa.Text(), nullable=False),
        sa.Column('encrypted_cert_key_pem', sa.LargeBinary(), nullable=False),
        sa.Column('encrypted_account_key_pem', sa.LargeBinary(), nullable=False),
        sa.Column('account_uri', sa.String(), nullable=False),
        sa.Column('directory_url', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_tls_pending_manual_challenge')),
    )


def downgrade() -> None:
    op.drop_table('tls_pending_manual_challenge')
