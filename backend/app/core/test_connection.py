import dataclasses
import smtplib
import socket
import ssl
from collections.abc import Callable
from typing import Protocol

from app.models.enums import TlsMode

DEFAULT_TIMEOUT = 10.0

# Fixed, UI-facing order (matches the design handoff's Test Connection
# screen exactly) — independent of the real protocol's chronological order,
# which differs between STARTTLS and implicit TLS. See _finalize().
CANONICAL_STEPS = ("DNS resolution", "TCP connection", "TLS handshake", "Server greeting", "AUTH")


@dataclasses.dataclass
class StepResult:
    name: str
    passed: bool
    detail: str


@dataclasses.dataclass
class TestConnectionResult:
    steps: list[StepResult]

    @property
    def success(self) -> bool:
        return all(step.passed for step in self.steps)


class SmtpClient(Protocol):
    """The subset of smtplib.SMTP / SMTP_SSL this module depends on — tests
    substitute a fake implementing this same shape and exercise every
    branch without a real socket or DNS lookup (testing-strategy.md §1:
    "mockable transport layer")."""

    def connect(self, host: str, port: int) -> tuple[int, bytes]: ...
    def ehlo(self) -> tuple[int, bytes]: ...
    def starttls(self, context: ssl.SSLContext | None = None) -> tuple[int, bytes]: ...
    def login(self, user: str, password: str) -> tuple[int, bytes]: ...
    def quit(self) -> tuple[int, bytes]: ...


ClientFactory = Callable[[float], SmtpClient]
Resolver = Callable[[str, int], object]


def _default_client_factory(tls_mode: TlsMode) -> ClientFactory:
    cls = smtplib.SMTP_SSL if tls_mode is TlsMode.implicit else smtplib.SMTP
    return lambda timeout: cls(timeout=timeout)


def _decode(message: bytes) -> str:
    return message.decode("utf-8", errors="replace")


def _finalize(results: dict[str, StepResult]) -> TestConnectionResult:
    steps: list[StepResult] = []
    previous_failed = False
    for name in CANONICAL_STEPS:
        if name in results:
            step = results[name]
        elif previous_failed:
            step = StepResult(name, False, "Not attempted — a previous step failed")
        else:
            step = StepResult(name, False, "Not attempted")
        if not step.passed:
            previous_failed = True
        steps.append(step)
    return TestConnectionResult(steps)


def _safe_quit(client: SmtpClient) -> None:
    try:
        client.quit()
    except Exception:
        pass


def test_upstream_connection(
    *,
    host: str,
    port: int,
    tls_mode: TlsMode,
    username: str,
    password: str,
    timeout: float = DEFAULT_TIMEOUT,
    resolver: Resolver = socket.getaddrinfo,
    client_factory: ClientFactory | None = None,
) -> TestConnectionResult:
    """Diagnoses an upstream SMTP account exactly as far as spec §15 asks
    for: DNS -> TCP -> TLS -> greeting -> AUTH, and never further — no
    MAIL FROM/DATA is ever sent (architecture.md: "Test connection" is
    diagnostic, not part of the mail path)."""
    results: dict[str, StepResult] = {}

    try:
        resolver(host, port)
    except OSError as exc:
        results["DNS resolution"] = StepResult("DNS resolution", False, str(exc))
        return _finalize(results)
    results["DNS resolution"] = StepResult("DNS resolution", True, f"Resolved {host}")

    factory = client_factory or _default_client_factory(tls_mode)
    client = factory(timeout)
    # smtplib only sets `_host` (which starttls() needs for TLS SNI/hostname
    # verification) when a host is passed to the constructor itself, not
    # when connect() is called afterward — set it explicitly since we
    # deliberately construct with no host to control the connect step
    # ourselves. Harmless on the fake client used in tests.
    client._host = host

    try:
        code, message = client.connect(host, port)
    except ssl.SSLError as exc:
        # Implicit-TLS connect() does TCP + TLS together — a socket-level
        # OSError below means TCP itself never established, whereas an
        # SSLError here means TCP succeeded and TLS negotiation is what failed.
        results["TCP connection"] = StepResult("TCP connection", True, f"Connected to {host}:{port}")
        results["TLS handshake"] = StepResult("TLS handshake", False, str(exc))
        return _finalize(results)
    except smtplib.SMTPConnectError as exc:
        results["TCP connection"] = StepResult("TCP connection", True, f"Connected to {host}:{port}")
        if tls_mode is TlsMode.implicit:
            results["TLS handshake"] = StepResult(
                "TLS handshake", True, "Implicit TLS established during connection"
            )
        results["Server greeting"] = StepResult("Server greeting", False, str(exc))
        return _finalize(results)
    except OSError as exc:
        results["TCP connection"] = StepResult("TCP connection", False, str(exc))
        return _finalize(results)

    results["TCP connection"] = StepResult("TCP connection", True, f"Connected to {host}:{port}")
    greeting_detail = f"{code} {_decode(message)}"

    if tls_mode is TlsMode.implicit:
        results["TLS handshake"] = StepResult(
            "TLS handshake", True, "Implicit TLS established during connection"
        )
        results["Server greeting"] = StepResult("Server greeting", True, greeting_detail)
    else:
        results["Server greeting"] = StepResult("Server greeting", True, greeting_detail)
        try:
            client.ehlo()
            tls_code, tls_message = client.starttls(context=ssl.create_default_context())
            client.ehlo()
        except (smtplib.SMTPException, ssl.SSLError, OSError, ValueError) as exc:
            # ssl.SSLError covers real handshake/certificate failures;
            # ValueError/OSError cover lower-level failures smtplib doesn't
            # wrap in an SMTPException (e.g. a bad server_hostname).
            results["TLS handshake"] = StepResult("TLS handshake", False, str(exc))
            _safe_quit(client)
            return _finalize(results)
        results["TLS handshake"] = StepResult(
            "TLS handshake", True, f"{tls_code} {_decode(tls_message)}"
        )

    try:
        auth_code, auth_message = client.login(username, password)
        results["AUTH"] = StepResult("AUTH", True, f"{auth_code} {_decode(auth_message)}")
    except (smtplib.SMTPException, OSError) as exc:
        results["AUTH"] = StepResult("AUTH", False, str(exc))
    finally:
        _safe_quit(client)

    return _finalize(results)
