"""Sends a real alert email — the app's only code path that composes and
sends an actual message (everywhere else, this app only configures
Postfix to relay OTHER services' mail; see test_connection.py's docstring
for the same distinction on the diagnostic side). Deliberately bypasses
the local Postfix relay entirely and connects straight upstream, exactly
the way test_connection.py's diagnostic already does — reusing
smtp_transport.py's shared connection-establishment rather than routing
through this relay's own submission port with a local SMTP user."""

from email.message import EmailMessage
from email.utils import formataddr

from app.core import smtp_transport
from app.core.encryption import decrypt_secret
from app.core.test_connection import DEFAULT_TIMEOUT
from app.models.enums import TlsMode
from app.models.sender import Sender
from app.models.upstream import UpstreamAccount


def send_alert_email(
    *,
    sender: Sender,
    upstream_account: UpstreamAccount,
    to_addrs: list[str],
    subject: str,
    body: str,
    from_name: str | None = None,
) -> None:
    """Raises on any failure (decryption, connection, auth, send) — callers
    (alert_email.py) log and skip rather than crash the scheduler loop,
    retrying on the next tick."""
    password = decrypt_secret(upstream_account.encrypted_password)
    client, _greeting = smtp_transport.connect_and_greet(
        host=upstream_account.host,
        port=upstream_account.port,
        tls_mode=upstream_account.tls_mode,
        timeout=DEFAULT_TIMEOUT,
    )
    try:
        if upstream_account.tls_mode is not TlsMode.implicit:
            smtp_transport.upgrade_to_starttls(client)
        client.login(upstream_account.username, password)

        message = EmailMessage()
        message["From"] = formataddr((from_name, sender.address)) if from_name else sender.address
        message["To"] = ", ".join(to_addrs)
        message["Subject"] = subject
        message.set_content(body)
        client.send_message(message)
    finally:
        smtp_transport.safe_quit(client)
