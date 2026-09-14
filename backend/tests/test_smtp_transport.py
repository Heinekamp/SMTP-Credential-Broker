import smtplib
import ssl

import pytest

from app.core.smtp_transport import connect_and_greet, safe_quit, upgrade_to_starttls
from app.models.enums import TlsMode


class FakeSmtpClient:
    def __init__(
        self,
        *,
        connect_exc: Exception | None = None,
        connect_result: tuple[int, bytes] = (220, b"hello.example.com ESMTP"),
        starttls_exc: Exception | None = None,
        starttls_result: tuple[int, bytes] = (220, b"2.0.0 Ready to start TLS"),
        quit_exc: Exception | None = None,
    ) -> None:
        self._connect_exc = connect_exc
        self._connect_result = connect_result
        self._starttls_exc = starttls_exc
        self._starttls_result = starttls_result
        self._quit_exc = quit_exc
        self.ehlo_calls = 0
        self.quit_called = False

    def connect(self, host: str, port: int) -> tuple[int, bytes]:
        if self._connect_exc:
            raise self._connect_exc
        return self._connect_result

    def ehlo(self) -> tuple[int, bytes]:
        self.ehlo_calls += 1
        return (250, b"hello.example.com")

    def starttls(self, context: ssl.SSLContext | None = None) -> tuple[int, bytes]:
        if self._starttls_exc:
            raise self._starttls_exc
        return self._starttls_result

    def login(self, user: str, password: str) -> tuple[int, bytes]:
        return (235, b"2.7.0 Authentication successful")

    def quit(self) -> tuple[int, bytes]:
        self.quit_called = True
        if self._quit_exc:
            raise self._quit_exc
        return (221, b"Bye")


def test_connect_and_greet_returns_client_and_decoded_greeting() -> None:
    fake = FakeSmtpClient()
    client, greeting = connect_and_greet(
        host="smtp.example.com", port=587, tls_mode=TlsMode.starttls, timeout=5.0, client_factory=lambda t: fake
    )
    assert client is fake
    assert greeting == "220 hello.example.com ESMTP"
    assert fake._host == "smtp.example.com"


def test_connect_and_greet_propagates_the_underlying_exception_unchanged() -> None:
    fake = FakeSmtpClient(connect_exc=ConnectionRefusedError("refused"))
    with pytest.raises(ConnectionRefusedError):
        connect_and_greet(
            host="smtp.example.com", port=587, tls_mode=TlsMode.starttls, timeout=5.0, client_factory=lambda t: fake
        )


def test_upgrade_to_starttls_does_ehlo_starttls_ehlo_and_returns_decoded_response() -> None:
    fake = FakeSmtpClient()
    detail = upgrade_to_starttls(fake)
    assert detail == "220 2.0.0 Ready to start TLS"
    assert fake.ehlo_calls == 2


def test_upgrade_to_starttls_propagates_starttls_failure() -> None:
    fake = FakeSmtpClient(starttls_exc=smtplib.SMTPException("STARTTLS failed"))
    with pytest.raises(smtplib.SMTPException):
        upgrade_to_starttls(fake)


def test_safe_quit_swallows_any_exception() -> None:
    fake = FakeSmtpClient(quit_exc=OSError("already closed"))
    safe_quit(fake)  # must not raise
    assert fake.quit_called is True
