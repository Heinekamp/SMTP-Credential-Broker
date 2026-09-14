"""Shared low-level SMTP connection-establishment, extracted from
test_connection.py so the alert mailer (mailer.py) doesn't have to
duplicate the DNS-agnostic TCP/TLS dance. Split into two functions rather
than one, matching the two genuinely distinct failure points the caller
needs to tell apart: `connect_and_greet()` (TCP connect, or for implicit
TLS accounts, TCP+TLS+greeting together — a single smtplib call) and
`upgrade_to_starttls()` (the separate EHLO/STARTTLS/EHLO dance, STARTTLS
accounts only). Neither catches anything — the caller decides what a
failure at each phase means (test_connection.py turns it into a
per-step diagnostic; mailer.py just lets it propagate and logs+skips).
"""

import smtplib
import ssl
from collections.abc import Callable
from email.message import EmailMessage
from typing import Protocol

from app.models.enums import TlsMode


class SmtpClient(Protocol):
    """The subset of smtplib.SMTP / SMTP_SSL this module depends on — tests
    substitute a fake implementing this same shape and exercise every
    branch without a real socket or DNS lookup (testing-strategy.md §1:
    "mockable transport layer"). `send_message` is only ever called by
    mailer.py — test_connection.py's diagnostic never sends a message."""

    def connect(self, host: str, port: int) -> tuple[int, bytes]: ...
    def ehlo(self) -> tuple[int, bytes]: ...
    def starttls(self, context: ssl.SSLContext | None = None) -> tuple[int, bytes]: ...
    def login(self, user: str, password: str) -> tuple[int, bytes]: ...
    def send_message(self, msg: EmailMessage) -> dict: ...
    def quit(self) -> tuple[int, bytes]: ...


ClientFactory = Callable[[float], SmtpClient]


def default_client_factory(tls_mode: TlsMode) -> ClientFactory:
    cls = smtplib.SMTP_SSL if tls_mode is TlsMode.implicit else smtplib.SMTP
    return lambda timeout: cls(timeout=timeout)


def decode(message: bytes) -> str:
    return message.decode("utf-8", errors="replace")


def connect_and_greet(
    *,
    host: str,
    port: int,
    tls_mode: TlsMode,
    timeout: float,
    client_factory: ClientFactory | None = None,
) -> tuple[SmtpClient, str]:
    """Connects and returns (client, decoded greeting). For implicit TLS,
    this single call performs TCP + TLS + reading the greeting — a
    ssl.SSLError here means TCP succeeded and TLS failed; an OSError means
    TCP itself never established; a smtplib.SMTPConnectError means TCP
    (and, for implicit TLS, TLS) succeeded but the greeting was bad."""
    factory = client_factory or default_client_factory(tls_mode)
    client = factory(timeout)
    # smtplib only sets `_host` (which starttls() needs for TLS SNI/hostname
    # verification) when a host is passed to the constructor itself, not
    # when connect() is called afterward — set it explicitly since we
    # deliberately construct with no host to control the connect step
    # ourselves. Harmless on the fake client used in tests.
    client._host = host
    code, message = client.connect(host, port)
    return client, f"{code} {decode(message)}"


def upgrade_to_starttls(client: SmtpClient) -> str:
    """EHLO/STARTTLS/EHLO for a STARTTLS (non-implicit-TLS) account —
    returns the decoded STARTTLS response. Raises on any failure
    (smtplib.SMTPException, ssl.SSLError, OSError, or ValueError for a
    lower-level failure smtplib doesn't wrap, e.g. a bad server_hostname)."""
    client.ehlo()
    tls_code, tls_message = client.starttls(context=ssl.create_default_context())
    client.ehlo()
    return f"{tls_code} {decode(tls_message)}"


def safe_quit(client: SmtpClient) -> None:
    try:
        client.quit()
    except Exception:
        pass
