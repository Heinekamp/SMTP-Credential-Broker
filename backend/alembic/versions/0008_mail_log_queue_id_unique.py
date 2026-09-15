"""mail_log_queue_id_unique

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-15 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: str | None = '0007'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A pre-existing install may already have duplicate queue_id rows from
    # the exact ingestion race this unique index is closing (two
    # concurrent /api/mail-log requests both processing the same maillog
    # bytes) — creating the index would otherwise fail outright on such a
    # database. Keep the earliest row per queue_id (the one that saw the
    # most updates over time, since _get_or_create always looks up the
    # existing row before creating a new one) and drop the rest.
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "DELETE FROM mail_log WHERE id NOT IN (SELECT MIN(id) FROM mail_log GROUP BY queue_id)"
        )
    )

    # Plain index -> unique index, not a UniqueConstraint: SQLite can't
    # ALTER TABLE ADD CONSTRAINT without a full table rebuild (Alembic
    # batch mode, not configured for this project), while dropping and
    # recreating an index needs neither.
    op.drop_index('ix_mail_log_queue_id', table_name='mail_log')
    op.create_index('ux_mail_log_queue_id', 'mail_log', ['queue_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ux_mail_log_queue_id', table_name='mail_log')
    op.create_index('ix_mail_log_queue_id', 'mail_log', ['queue_id'], unique=False)
