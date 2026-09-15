"""tls_certificate_state

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-15 18:35:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0012'
down_revision: str | None = '0011'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'tls_certificate_state',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('domain', sa.String(), nullable=True),
        sa.Column('cert_pem', sa.Text(), nullable=True),
        sa.Column('encrypted_key_pem', sa.LargeBinary(), nullable=True),
        sa.Column('not_before', sa.DateTime(), nullable=True),
        sa.Column('not_after', sa.DateTime(), nullable=True),
        sa.Column('issued_at', sa.DateTime(), nullable=True),
        sa.Column('acme_account_key_encrypted', sa.LargeBinary(), nullable=True),
        sa.Column('acme_account_uri', sa.String(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_tls_certificate_state')),
    )


def downgrade() -> None:
    op.drop_table('tls_certificate_state')
