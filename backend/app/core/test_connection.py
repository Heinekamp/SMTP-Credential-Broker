import dataclasses
import smtplib
import socket
import ssl
from collections.abc import Callable

from app.core import smtp_transport
from app.core.smtp_transport import ClientFactory, safe_quit
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


Resolver = Callable[[str, int], object]


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

    try:
        client, greeting_detail = smtp_transport.connect_and_greet(
            host=host, port=port, tls_mode=tls_mode, timeout=timeout, client_factory=client_factory
        )
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

    if tls_mode is TlsMode.implicit:
        results["TLS handshake"] = StepResult(
            "TLS handshake", True, "Implicit TLS established during connection"
        )
        results["Server greeting"] = StepResult("Server greeting", True, greeting_detail)
    else:
        results["Server greeting"] = StepResult("Server greeting", True, greeting_detail)
        try:
            tls_detail = smtp_transport.upgrade_to_starttls(client)
        except (smtplib.SMTPException, ssl.SSLError, OSError, ValueError) as exc:
            # ssl.SSLError covers real handshake/certificate failures;
            # ValueError/OSError cover lower-level failures smtplib doesn't
            # wrap in an SMTPException (e.g. a bad server_hostname).
            results["TLS handshake"] = StepResult("TLS handshake", False, str(exc))
            safe_quit(client)
            return _finalize(results)
        results["TLS handshake"] = StepResult("TLS handshake", True, tls_detail)

    try:
        auth_code, auth_message = client.login(username, password)
        results["AUTH"] = StepResult("AUTH", True, f"{auth_code} {smtp_transport.decode(auth_message)}")
    except (smtplib.SMTPException, OSError) as exc:
        results["AUTH"] = StepResult("AUTH", False, str(exc))
    finally:
        safe_quit(client)

    return _finalize(results)
