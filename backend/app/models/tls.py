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


class TlsPendingManualChallenge(Base):
    """Singleton row (id fixed at 1) — the in-progress manual DNS-01
    challenge, if any. Unlike TlsCertificateState, *absence* of a row is
    the normal state (no manual challenge currently in progress); it's
    created by acme_tls.begin_manual_dns_challenge and cleared by
    acme_tls.finalize_manual_dns_challenge once resolved (issued or
    unrecoverably failed). order_json is the serialized ACME order +
    authorizations (acme.messages.OrderResource.json_dumps()) needed to
    resume the order on a later, separate HTTP request — the admin may
    take anywhere from seconds to hours to add the TXT record."""

    __tablename__ = "tls_pending_manual_challenge"

    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(nullable=False)
    contact_email: Mapped[str | None] = mapped_column(nullable=True, default=None)
    record_name: Mapped[str] = mapped_column(nullable=False)
    record_value: Mapped[str] = mapped_column(nullable=False)
    order_json: Mapped[str] = mapped_column(nullable=False)
    encrypted_cert_key_pem: Mapped[bytes] = mapped_column(nullable=False)
    encrypted_account_key_pem: Mapped[bytes] = mapped_column(nullable=False)
    account_uri: Mapped[str] = mapped_column(nullable=False)
    directory_url: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(default=utcnow, nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(nullable=False)
