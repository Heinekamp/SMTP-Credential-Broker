import datetime

from sqlalchemy import JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base


class RelaySettings(Base):
    """Singleton row (id fixed at 1) holding every admin-editable,
    DB-backed setting introduced for scheduled connection testing and
    alerting — unlike this project's other tunables (app/config.py), these
    need to be editable from the UI without a container restart, and (for
    the notification sender) reference a live `senders` row, which an env
    var can't express."""

    __tablename__ = "relay_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    # None = disabled/manual-only (today's behavior). Defaults to None on a
    # fresh install so upgrading an existing instance never silently starts
    # making periodic AUTH attempts against a real upstream provider
    # without the admin opting in.
    connection_test_interval_minutes: Mapped[int | None] = mapped_column(nullable=True, default=None)
    # Off by default — checking for updates means outbound calls to GitHub
    # and postfix.org, which a self-hosted relay shouldn't make without
    # explicit opt-in.
    update_check_enabled: Mapped[bool] = mapped_column(nullable=False, default=False)
    notify_recipients: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    notify_sender_id: Mapped[int | None] = mapped_column(
        ForeignKey("senders.id", ondelete="SET NULL"), nullable=True
    )
    # Display name for the alert email's From header (e.g. "SMTP Relay
    # Alerts") — None means the header is just the bare sender address.
    notify_from_name: Mapped[str | None] = mapped_column(nullable=True, default=None)
    notify_on_health_degraded: Mapped[bool] = mapped_column(nullable=False, default=True)
    notify_on_upstream_test_failure: Mapped[bool] = mapped_column(nullable=False, default=True)
    notify_on_app_update_available: Mapped[bool] = mapped_column(nullable=False, default=True)
    notify_on_postfix_update_available: Mapped[bool] = mapped_column(nullable=False, default=True)
    # None = keep forever (today's behavior) — same "opt-in, never
    # silently start doing something new" convention as
    # connection_test_interval_minutes above; an upgrade must not start
    # deleting existing rows until an admin explicitly sets a retention
    # window (core/retention.py).
    mail_log_retention_days: Mapped[int | None] = mapped_column(nullable=True, default=None)
    audit_log_retention_days: Mapped[int | None] = mapped_column(nullable=True, default=None)
    # Let's Encrypt / DNS-01 configuration (core/acme_tls.py). Off by
    # default — the self-signed placeholder cert stays in place until an
    # admin explicitly opts in, same "opt-in, never silently start doing
    # something new on upgrade" convention as everything else here.
    tls_acme_enabled: Mapped[bool] = mapped_column(nullable=False, default=False)
    tls_domain: Mapped[str | None] = mapped_column(nullable=True, default=None)
    tls_contact_email: Mapped[str | None] = mapped_column(nullable=True, default=None)
    tls_dns_provider: Mapped[str] = mapped_column(nullable=False, default="cloudflare")
    tls_cloudflare_api_token_encrypted: Mapped[bytes | None] = mapped_column(nullable=True, default=None)
    tls_cloudflare_zone_id: Mapped[str | None] = mapped_column(nullable=True, default=None)
    # Rate-limit abuse detection (core/alerts.py, core/rate_limit_abuse.py).
    # The alert itself (the notification bell) is always live regardless
    # of these — same convention as notify_on_health_degraded/
    # notify_on_upstream_test_failure, which only gate email, never bell
    # visibility. Both default off (unlike those two, which predate this
    # project's stricter "opt-in, never silently start doing something new
    # on upgrade" convention) since this is a brand-new automated-behavior
    # category — auto-disabling especially so, since it revokes a
    # credential without a human in the loop.
    notify_on_rate_limit_abuse: Mapped[bool] = mapped_column(nullable=False, default=False)
    rate_limit_abuse_auto_disable_enabled: Mapped[bool] = mapped_column(nullable=False, default=False)
    rate_limit_abuse_threshold_minutes: Mapped[int] = mapped_column(nullable=False, default=10)
    # Visual customization (#51). None everywhere below means "use the
    # bundled default" — same nullable-means-default convention as the
    # rest of this table, so an upgrade never changes how an existing
    # deployment looks. accent_color is a "#rrggbb" hex string.
    accent_color: Mapped[str | None] = mapped_column(nullable=True, default=None)
    logo_image: Mapped[bytes | None] = mapped_column(nullable=True, default=None)
    logo_content_type: Mapped[str | None] = mapped_column(nullable=True, default=None)
    updated_at: Mapped[datetime.datetime] = mapped_column(default=utcnow, onupdate=utcnow, nullable=False)


class BackgroundJobState(Base):
    """Singleton row (id fixed at 1), system-only — never admin-edited,
    purely operational state for the background scheduler
    (core/scheduler.py), matching MailLogIngestState's existing pattern.
    Tracks when each periodic job last ran, the last-seen results of the
    update checks, and enough "already notified" state to edge-trigger
    alert emails (fire once on a resolved->active transition or a new
    version, never once per poll while a condition persists)."""

    __tablename__ = "background_job_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_test_last_run_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True, default=None)
    update_check_last_run_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True, default=None)
    retention_cleanup_last_run_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True, default=None)
    latest_app_version: Mapped[str | None] = mapped_column(nullable=True, default=None)
    latest_app_version_checked_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True, default=None)
    latest_postfix_version: Mapped[str | None] = mapped_column(nullable=True, default=None)
    latest_postfix_version_checked_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True, default=None)
    app_update_last_emailed_version: Mapped[str | None] = mapped_column(nullable=True, default=None)
    app_update_acknowledged_version: Mapped[str | None] = mapped_column(nullable=True, default=None)
    postfix_update_last_emailed_version: Mapped[str | None] = mapped_column(nullable=True, default=None)
    postfix_update_acknowledged_version: Mapped[str | None] = mapped_column(nullable=True, default=None)
    health_degraded_active: Mapped[bool] = mapped_column(nullable=False, default=False)
    upstream_test_failure_active: Mapped[bool] = mapped_column(nullable=False, default=False)
    cert_renewal_last_checked_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True, default=None)
    cert_last_renewal_attempt_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True, default=None)
    cert_last_renewal_error: Mapped[str | None] = mapped_column(nullable=True, default=None)
    rate_limit_cleanup_last_run_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True, default=None)
    # Edge-trigger for the rate_limit_abuse alert email — identical shape
    # to health_degraded_active/upstream_test_failure_active above.
    rate_limit_abuse_active: Mapped[bool] = mapped_column(nullable=False, default=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(default=utcnow, onupdate=utcnow, nullable=False)
