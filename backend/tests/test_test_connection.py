import smtplib
import socket
import ssl

from app.core.test_connection import CANONICAL_STEPS
from app.core.test_connection import test_upstream_connection as run_test_connection
from app.models.enums import TlsMode


class FakeSmtpClient:
    """Stands in for smtplib.SMTP/SMTP_SSL — see
    app/core/test_connection.py's SmtpClient protocol. No real socket or
    DNS lookup happens anywhere in this test module."""

    def __init__(
        self,
        *,
        connect_exc: Exception | None = None,
        connect_result: tuple[int, bytes] = (220, b"hello.example.com ESMTP"),
        ehlo_exc: Exception | None = None,
        starttls_exc: Exception | None = None,
        starttls_result: tuple[int, bytes] = (220, b"2.0.0 Ready to start TLS"),
        login_exc: Exception | None = None,
        login_result: tuple[int, bytes] = (235, b"2.7.0 Authentication successful"),
    ) -> None:
        self._connect_exc = connect_exc
        self._connect_result = connect_result
        self._ehlo_exc = ehlo_exc
        self._starttls_exc = starttls_exc
        self._starttls_result = starttls_result
        self._login_exc = login_exc
        self._login_result = login_result
        self.quit_called = False

    def connect(self, host: str, port: int) -> tuple[int, bytes]:
        if self._connect_exc:
            raise self._connect_exc
        return self._connect_result

    def ehlo(self) -> tuple[int, bytes]:
        if self._ehlo_exc:
            raise self._ehlo_exc
        return (250, b"hello.example.com")

    def starttls(self, context: ssl.SSLContext | None = None) -> tuple[int, bytes]:
        if self._starttls_exc:
            raise self._starttls_exc
        return self._starttls_result

    def login(self, user: str, password: str) -> tuple[int, bytes]:
        if self._login_exc:
            raise self._login_exc
        return self._login_result

    def quit(self) -> tuple[int, bytes]:
        self.quit_called = True
        return (221, b"Bye")


def _ok_resolver(host: str, port: int) -> object:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, port))]


def _step_names(result) -> list[str]:
    return [s.name for s in result.steps]


def _passed(result) -> dict[str, bool]:
    return {s.name: s.passed for s in result.steps}


def test_full_success_starttls() -> None:
    client = FakeSmtpClient()
    result = run_test_connection(
        host="smtp.example.com",
        port=587,
        tls_mode=TlsMode.starttls,
        username="user@example.com",
        password="secret",
        resolver=_ok_resolver,
        client_factory=lambda timeout: client,
    )
    assert result.success is True
    assert _step_names(result) == list(CANONICAL_STEPS)
    assert all(_passed(result).values())
    assert client.quit_called is True


def test_full_success_implicit_tls() -> None:
    client = FakeSmtpClient()
    result = run_test_connection(
        host="smtp.example.com",
        port=465,
        tls_mode=TlsMode.implicit,
        username="user@example.com",
        password="secret",
        resolver=_ok_resolver,
        client_factory=lambda timeout: client,
    )
    assert result.success is True
    assert _passed(result) == {name: True for name in CANONICAL_STEPS}


def test_dns_failure_stops_at_first_step() -> None:
    def failing_resolver(host: str, port: int) -> object:
        raise socket.gaierror("Name or service not known")

    result = run_test_connection(
        host="does-not-exist.invalid",
        port=587,
        tls_mode=TlsMode.starttls,
        username="user@example.com",
        password="secret",
        resolver=failing_resolver,
        client_factory=lambda timeout: FakeSmtpClient(),
    )
    assert result.success is False
    steps = _passed(result)
    assert steps["DNS resolution"] is False
    assert steps["TCP connection"] is False
    assert steps["AUTH"] is False
    # Steps after the failure point are explicitly "not attempted", not
    # silently omitted — the operator should see the whole picture.
    auth_step = next(s for s in result.steps if s.name == "AUTH")
    assert "previous step failed" in auth_step.detail


def test_tcp_connection_failure() -> None:
    client = FakeSmtpClient(connect_exc=ConnectionRefusedError("Connection refused"))
    result = run_test_connection(
        host="smtp.example.com",
        port=587,
        tls_mode=TlsMode.starttls,
        username="user@example.com",
        password="secret",
        resolver=_ok_resolver,
        client_factory=lambda timeout: client,
    )
    assert result.success is False
    steps = _passed(result)
    assert steps["DNS resolution"] is True
    assert steps["TCP connection"] is False


def test_bad_greeting_after_successful_tcp_connect() -> None:
    client = FakeSmtpClient(connect_exc=smtplib.SMTPConnectError(421, "Service not available"))
    result = run_test_connection(
        host="smtp.example.com",
        port=587,
        tls_mode=TlsMode.starttls,
        username="user@example.com",
        password="secret",
        resolver=_ok_resolver,
        client_factory=lambda timeout: client,
    )
    assert result.success is False
    steps = _passed(result)
    assert steps["TCP connection"] is True
    assert steps["Server greeting"] is False


def test_tls_handshake_failure_on_starttls() -> None:
    client = FakeSmtpClient(starttls_exc=smtplib.SMTPException("STARTTLS failed"))
    result = run_test_connection(
        host="smtp.example.com",
        port=587,
        tls_mode=TlsMode.starttls,
        username="user@example.com",
        password="secret",
        resolver=_ok_resolver,
        client_factory=lambda timeout: client,
    )
    assert result.success is False
    steps = _passed(result)
    assert steps["Server greeting"] is True
    assert steps["TLS handshake"] is False
    assert steps["AUTH"] is False


def test_implicit_tls_handshake_failure() -> None:
    client = FakeSmtpClient(connect_exc=ssl.SSLError("certificate verify failed"))
    result = run_test_connection(
        host="smtp.example.com",
        port=465,
        tls_mode=TlsMode.implicit,
        username="user@example.com",
        password="secret",
        resolver=_ok_resolver,
        client_factory=lambda timeout: client,
    )
    assert result.success is False
    steps = _passed(result)
    assert steps["TCP connection"] is True
    assert steps["TLS handshake"] is False


def test_auth_failure_does_not_affect_earlier_steps() -> None:
    client = FakeSmtpClient(
        login_exc=smtplib.SMTPAuthenticationError(535, b"5.7.8 Authentication failed")
    )
    result = run_test_connection(
        host="smtp.example.com",
        port=587,
        tls_mode=TlsMode.starttls,
        username="user@example.com",
        password="wrong",
        resolver=_ok_resolver,
        client_factory=lambda timeout: client,
    )
    assert result.success is False
    steps = _passed(result)
    assert steps["DNS resolution"] is True
    assert steps["TCP connection"] is True
    assert steps["TLS handshake"] is True
    assert steps["Server greeting"] is True
    assert steps["AUTH"] is False
    assert client.quit_called is True
