import pytest

from app.core.encryption import encrypt_secret
from app.core.mailer import send_alert_email
from app.models.enums import TlsMode
from app.models.sender import Sender
from app.models.upstream import UpstreamAccount


class FakeSmtpClient:
    def __init__(self, *, login_exc: Exception | None = None) -> None:
        self._login_exc = login_exc
        self.sent_messages: list[object] = []
        self.quit_called = False
        self.ehlo_calls = 0

    def connect(self, host: str, port: int) -> tuple[int, bytes]:
        return (220, b"hello ESMTP")

    def ehlo(self) -> tuple[int, bytes]:
        self.ehlo_calls += 1
        return (250, b"hello")

    def starttls(self, context=None) -> tuple[int, bytes]:
        return (220, b"2.0.0 Ready to start TLS")

    def login(self, user: str, password: str) -> tuple[int, bytes]:
        if self._login_exc:
            raise self._login_exc
        return (235, b"2.7.0 Authentication successful")

    def send_message(self, msg) -> dict:
        self.sent_messages.append(msg)
        return {}

    def quit(self) -> tuple[int, bytes]:
        self.quit_called = True
        return (221, b"Bye")


def _account(*, tls_mode: TlsMode = TlsMode.starttls) -> UpstreamAccount:
    return UpstreamAccount(
        id=1,
        name="alert-sender",
        host="smtp.example.com",
        port=587,
        tls_mode=tls_mode,
        username="alerts@example.com",
        encrypted_password=encrypt_secret("hunter2"),
    )


def _sender(account: UpstreamAccount) -> Sender:
    return Sender(id=1, address="alerts@example.com", upstream_account_id=account.id, upstream_account=account)


def test_sends_a_real_message_with_the_expected_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _account()
    sender = _sender(account)
    fake = FakeSmtpClient()
    monkeypatch.setattr(
        "app.core.mailer.smtp_transport.connect_and_greet", lambda **kwargs: (fake, "220 hello")
    )

    send_alert_email(
        sender=sender,
        upstream_account=account,
        to_addrs=["admin@example.com"],
        subject="Relay degraded",
        body="The relay is currently degraded.",
    )

    assert len(fake.sent_messages) == 1
    msg = fake.sent_messages[0]
    assert msg["From"] == "alerts@example.com"
    assert msg["To"] == "admin@example.com"
    assert msg["Subject"] == "Relay degraded"
    assert fake.quit_called is True
    # STARTTLS accounts must upgrade before logging in.
    assert fake.ehlo_calls == 2


def test_implicit_tls_accounts_skip_the_starttls_upgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _account(tls_mode=TlsMode.implicit)
    sender = _sender(account)
    fake = FakeSmtpClient()
    monkeypatch.setattr(
        "app.core.mailer.smtp_transport.connect_and_greet", lambda **kwargs: (fake, "220 hello")
    )

    send_alert_email(
        sender=sender, upstream_account=account, to_addrs=["admin@example.com"], subject="s", body="b"
    )

    assert fake.ehlo_calls == 0
    assert len(fake.sent_messages) == 1


def test_login_failure_propagates_and_still_quits(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _account()
    sender = _sender(account)
    fake = FakeSmtpClient(login_exc=RuntimeError("bad credentials"))
    monkeypatch.setattr(
        "app.core.mailer.smtp_transport.connect_and_greet", lambda **kwargs: (fake, "220 hello")
    )

    with pytest.raises(RuntimeError):
        send_alert_email(sender=sender, upstream_account=account, to_addrs=["admin@example.com"], subject="s", body="b")

    assert fake.quit_called is True
    assert fake.sent_messages == []
