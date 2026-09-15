import datetime

from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base


class TlsCertificateState(Base):
    """Singleton row (id fixed at 1) — the durable, DB-backed record of
    whatever TLS certificate/key is (or should be) installed at
    /etc/postfix/tls inside the postfix container. The postfix_tls named
    volume (docker-compose.yml) is explicitly not guaranteed durable
    across a container/volume loss; this table is the source of truth an
    app-startup hook and the renewal tick (core/cert_renewal.py)
    reconcile the live files against (core/acme_tls.py's
    sync_certificate_to_postfix)."""

    __tablename__ = "tls_certificate_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    # "self_signed" (never issued via ACME yet — the Dockerfile-baked
    # placeholder is assumed live) | "lets_encrypt"
    source: Mapped[str] = mapped_column(nullable=False, default="self_signed")
    domain: Mapped[str | None] = mapped_column(nullable=True, default=None)
    # Full certificate chain PEM — public data, not a secret, so it's
    # stored in cleartext (unlike the private key material below).
    cert_pem: Mapped[str | None] = mapped_column(nullable=True, default=None)
    encrypted_key_pem: Mapped[bytes | None] = mapped_column(nullable=True, default=None)
    not_before: Mapped[datetime.datetime | None] = mapped_column(nullable=True, default=None)
    not_after: Mapped[datetime.datetime | None] = mapped_column(nullable=True, default=None)
    issued_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True, default=None)
    # ACME account reuse across renewals (RFC 8555 §7.3) — re-registering
    # a new account every renewal is both unnecessary and impolite to the CA.
    acme_account_key_encrypted: Mapped[bytes | None] = mapped_column(nullable=True, default=None)
    acme_account_uri: Mapped[str | None] = mapped_column(nullable=True, default=None)
    updated_at: Mapped[datetime.datetime] = mapped_column(default=utcnow, onupdate=utcnow, nullable=False)
