"""tls_certificate_settings

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-15 18:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0011'
down_revision: str | None = '0010'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'relay_settings',
        sa.Column('tls_acme_enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column('relay_settings', sa.Column('tls_domain', sa.String(), nullable=True))
    op.add_column('relay_settings', sa.Column('tls_contact_email', sa.String(), nullable=True))
    op.add_column(
        'relay_settings',
        sa.Column('tls_dns_provider', sa.String(), nullable=False, server_default='cloudflare'),
    )
    op.add_column('relay_settings', sa.Column('tls_cloudflare_api_token_encrypted', sa.LargeBinary(), nullable=True))
    op.add_column('relay_settings', sa.Column('tls_cloudflare_zone_id', sa.String(), nullable=True))

    op.add_column(
        'background_job_state', sa.Column('cert_renewal_last_checked_at', sa.DateTime(), nullable=True)
    )
    op.add_column(
        'background_job_state', sa.Column('cert_last_renewal_attempt_at', sa.DateTime(), nullable=True)
    )
    op.add_column('background_job_state', sa.Column('cert_last_renewal_error', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('background_job_state', 'cert_last_renewal_error')
    op.drop_column('background_job_state', 'cert_last_renewal_attempt_at')
    op.drop_column('background_job_state', 'cert_renewal_last_checked_at')

    op.drop_column('relay_settings', 'tls_cloudflare_zone_id')
    op.drop_column('relay_settings', 'tls_cloudflare_api_token_encrypted')
    op.drop_column('relay_settings', 'tls_dns_provider')
    op.drop_column('relay_settings', 'tls_contact_email')
    op.drop_column('relay_settings', 'tls_domain')
    op.drop_column('relay_settings', 'tls_acme_enabled')
