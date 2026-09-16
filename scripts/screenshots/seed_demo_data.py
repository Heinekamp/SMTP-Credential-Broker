"""Populates a fresh database with realistic-looking demo data, purely
for screenshot purposes (issue #39). Writes directly via SQLAlchemy
models rather than the HTTP API or Postfix's control surface — the
latter needs a real Unix domain socket that isn't available when running
this against a throwaway dev instance, and none of the screenshots need
the credentials to actually work against Postfix, only to look right in
the UI.

Run via the backend's own virtualenv, e.g.:

    backend/.venv/Scripts/python.exe scripts/screenshots/seed_demo_data.py

`run.sh` does this for you as part of the full pipeline; run this
directly only if you want to reseed without recapturing.
"""

import base64
import datetime
import os
import random
import secrets
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

# Must be set before app.config's lru_cached Settings is ever
# constructed (any import below can trigger that) — same ordering
# constraint tests/conftest.py documents.
os.environ.setdefault("RELAY_ENCRYPTION_KEY", base64.b64encode(os.urandom(32)).decode())
os.environ.setdefault("RELAY_COOKIE_SECURE", "false")
os.environ.setdefault("RELAY_SCHEDULER_ENABLED", "false")

from app.core.clock import utcnow  # noqa: E402
from app.core.encryption import encrypt_secret  # noqa: E402
from app.core.password_generation import generate_password  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.admin import AdminUser  # noqa: E402
from app.models.enums import MailStatus, TestResult, TlsMode  # noqa: E402
from app.models.local_user import LocalSmtpUser, UserSenderPermission  # noqa: E402
from app.models.mail_log import MailLog  # noqa: E402
from app.models.sender import Sender  # noqa: E402
from app.models.upstream import UpstreamAccount  # noqa: E402

DEMO_ADMIN_EMAIL = "admin@example.com"
DEMO_ADMIN_PASSWORD = "Sup3rSecret!Pass"

random.seed(20260101)  # deterministic mail-log timestamps/status mix across runs


def seed(db) -> None:
    admin = AdminUser(email=DEMO_ADMIN_EMAIL, password_hash=hash_password(DEMO_ADMIN_PASSWORD))
    db.add(admin)
    db.flush()

    strato = UpstreamAccount(
        name="STRATO — Primary",
        host="smtp.strato.de",
        port=465,
        tls_mode=TlsMode.implicit,
        username="noreply@example.com",
        encrypted_password=encrypt_secret("hunter2-strato"),
        last_test_at=utcnow() - datetime.timedelta(minutes=12),
        last_test_result=TestResult.success,
    )
    gmail = UpstreamAccount(
        name="Gmail — Marketing",
        host="smtp.gmail.com",
        port=587,
        tls_mode=TlsMode.starttls,
        username="marketing@example.com",
        encrypted_password=encrypt_secret("hunter2-gmail"),
        last_test_at=utcnow() - datetime.timedelta(hours=1),
        last_test_result=TestResult.success,
    )
    office365 = UpstreamAccount(
        name="Office 365 — Support",
        host="smtp.office365.com",
        port=587,
        tls_mode=TlsMode.starttls,
        username="support@example.com",
        encrypted_password=encrypt_secret("hunter2-o365"),
        rate_limit_per_hour=500,
        last_test_at=utcnow() - datetime.timedelta(minutes=40),
        last_test_result=TestResult.success,
    )
    legacy = UpstreamAccount(
        name="Legacy Mailgun (decommissioning)",
        host="smtp.mailgun.org",
        port=587,
        tls_mode=TlsMode.starttls,
        username="legacy@example.com",
        encrypted_password=encrypt_secret("hunter2-mailgun"),
        enabled=False,
        last_test_at=utcnow() - datetime.timedelta(days=3),
        last_test_result=TestResult.failure,
        last_test_error="535 5.7.8 Authentication credentials invalid",
    )
    db.add_all([strato, gmail, office365, legacy])
    db.flush()

    noreply = Sender(
        address="noreply@example.com", upstream_account_id=strato.id, description="Transactional/system mail"
    )
    alerts = Sender(address="alerts@example.com", upstream_account_id=strato.id, description="Monitoring & alerting")
    marketing = Sender(
        address="marketing@example.com", upstream_account_id=gmail.id, description="Marketing campaigns"
    )
    newsletter = Sender(
        address="newsletter@example.com", upstream_account_id=gmail.id, description="Monthly newsletter"
    )
    support = Sender(address="support@example.com", upstream_account_id=office365.id, description="Helpdesk replies")
    billing = Sender(
        address="billing@example.com",
        upstream_account_id=office365.id,
        enabled=False,
        description="Retired billing flow",
    )
    db.add_all([noreply, alerts, marketing, newsletter, support, billing])
    db.flush()

    printer = LocalSmtpUser(
        name="Printer — 3rd Floor",
        username="svc-printer-3f",
        password_hash=hash_password(generate_password()),
        password_last_rotated_at=utcnow() - datetime.timedelta(days=45),
        rate_limit_per_hour=100,
    )
    grafana = LocalSmtpUser(
        name="Monitoring Stack (Grafana)",
        username="svc-grafana",
        password_hash=hash_password(generate_password()),
        password_last_rotated_at=utcnow() - datetime.timedelta(days=10),
        rate_limit_per_hour=50,
        rate_limit_burst=10,
    )
    inventree = LocalSmtpUser(
        name="InvenTree",
        username="svc-inventree",
        password_hash=hash_password(generate_password()),
        password_last_rotated_at=utcnow() - datetime.timedelta(days=200),
    )
    marketing_automation = LocalSmtpUser(
        name="Marketing Automation",
        username="svc-marketing-automation",
        password_hash=hash_password(generate_password()),
        password_last_rotated_at=utcnow() - datetime.timedelta(days=3),
        rate_limit_per_hour=1000,
        rate_limit_burst=100,
    )
    zendesk = LocalSmtpUser(
        name="Support Ticketing (Zendesk sync)",
        username="svc-zendesk",
        password_hash=hash_password(generate_password()),
        password_last_rotated_at=utcnow() - datetime.timedelta(days=60),
        rate_limit_per_hour=200,
    )
    old_crm = LocalSmtpUser(
        name="Old CRM (decommissioned)",
        username="svc-old-crm",
        password_hash=hash_password(generate_password()),
        enabled=False,
    )
    db.add_all([printer, grafana, inventree, marketing_automation, zendesk, old_crm])
    db.flush()

    grants = [
        (printer, noreply),
        (printer, alerts),
        (grafana, alerts),
        (inventree, noreply),
        (marketing_automation, marketing),
        (marketing_automation, newsletter),
        (zendesk, support),
        (old_crm, billing),
    ]
    for user, sender in grants:
        db.add(UserSenderPermission(local_smtp_user_id=user.id, sender_id=sender.id))
    db.flush()

    # sender -> local users allowed to use it, so seeded mail log rows can
    # plausibly attribute each send to a real local user instead of
    # leaving that column blank everywhere.
    senders_to_users: dict[int, list[LocalSmtpUser]] = {}
    for user, sender in grants:
        senders_to_users.setdefault(sender.id, []).append(user)

    _seed_mail_log(
        db,
        senders=[noreply, alerts, marketing, newsletter, support],
        upstream_accounts=[strato, gmail, office365],
        senders_to_users=senders_to_users,
    )

    db.commit()


def _seed_mail_log(
    db,
    *,
    senders: list[Sender],
    upstream_accounts: list[UpstreamAccount],
    senders_to_users: dict[int, list[LocalSmtpUser]],
) -> None:
    # Weighted so the Mail Log reads like a believable production mix, not
    # an even split across every status.
    status_weights = [
        (MailStatus.sent, 70),
        (MailStatus.deferred, 12),
        (MailStatus.bounced, 10),
        (MailStatus.rejected, 6),
        (MailStatus.queued, 2),
    ]
    statuses = [s for s, weight in status_weights for _ in range(weight)]

    errors = {
        MailStatus.deferred: [
            "451 4.7.1 Greylisted, try again later",
            "421 4.4.2 Connection timed out",
        ],
        MailStatus.bounced: [
            "550 5.1.1 User unknown in virtual mailbox table",
            "552 5.2.2 Mailbox full",
        ],
        MailStatus.rejected: [
            "554 5.7.1 Message rejected by policy (rate limit exceeded)",
            "550 5.7.1 Sender address not authorized for this account",
        ],
    }

    recipient_domains = ["customer.example", "partner.example", "gmail.com", "outlook.com"]
    now = utcnow()

    for i in range(80):
        status = random.choice(statuses)
        sender = random.choice(senders)
        account = next((a for a in upstream_accounts if a.id == sender.upstream_account_id), None)
        timestamp = now - datetime.timedelta(
            hours=random.uniform(0, 96), minutes=random.uniform(0, 59)
        )
        recipient = f"user{random.randint(1, 999)}@{random.choice(recipient_domains)}"
        allowed_users = senders_to_users.get(sender.id, [])
        local_user = random.choice(allowed_users) if allowed_users else None
        entry = MailLog(
            queue_id=f"{secrets.token_hex(5).upper()}",
            timestamp=timestamp,
            local_smtp_user_id=local_user.id if local_user else None,
            envelope_sender=sender.address,
            recipients=[recipient],
            upstream_account_id=account.id if account else None,
            status=status,
            error=random.choice(errors[status]) if status in errors else None,
        )
        db.add(entry)


def main() -> None:
    db = SessionLocal()
    try:
        if db.query(AdminUser).count() > 0:
            print("Database already has data — refusing to reseed on top of it.", file=sys.stderr)
            print("Point RELAY_DATABASE_URL at a fresh file, or delete the existing one first.", file=sys.stderr)
            sys.exit(1)
        seed(db)
        print(f"Seeded demo data. Admin login: {DEMO_ADMIN_EMAIL} / {DEMO_ADMIN_PASSWORD}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
