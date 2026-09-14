"""A minimal, controlled stand-in for an externally hosted SMTP provider
(e.g. STRATO), used only by the integration test harness — never a real
upstream, per testing-strategy.md §3 ("upstream side is always a
controlled test SMTP server so tests are deterministic ... and don't leak
credentials or spam real mailboxes").

Supports STARTTLS + AUTH PLAIN/LOGIN against a fixed credential table so
tests can assert exactly which upstream account's credentials Postfix
presented (testing-strategy.md §2's "Upstream selection" scenarios).
"""

import asyncio
import json
import os
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword

# username -> password. Overridable via env for the "upstream auth
# failure" and "credential rotation" scenarios without rebuilding the image.
_CREDENTIALS = {
    "printer@example.com": os.environ.get("STUB_PRINTER_PASSWORD", "printer-upstream-pass"),
    "noreply@example.com": os.environ.get("STUB_NOREPLY_PASSWORD", "noreply-upstream-pass"),
    "server@example.com": os.environ.get("STUB_SERVER_PASSWORD", "server-upstream-pass"),
}

# Deliveries the test suite can assert against: (auth_username, mail_from, rcpt_tos)
DELIVERIES: list[dict] = []


class _Authenticator:
    def __call__(self, server, session, envelope, mechanism, auth_data):
        if not isinstance(auth_data, LoginPassword):
            return AuthResult(success=False, handled=False)
        username = auth_data.login.decode()
        password = auth_data.password.decode()
        if _CREDENTIALS.get(username) == password:
            session.stub_authenticated_as = username
            return AuthResult(success=True)
        return AuthResult(success=False)


class _Handler:
    async def handle_DATA(self, server, session, envelope):
        DELIVERIES.append(
            {
                "authenticated_as": getattr(session, "stub_authenticated_as", None),
                "mail_from": envelope.mail_from,
                "rcpt_tos": list(envelope.rcpt_tos),
            }
        )
        return "250 Message accepted for delivery"


def _build_ssl_context() -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain("/certs/stub.crt", "/certs/stub.key")
    return context


class _InspectionHandler(BaseHTTPRequestHandler):
    """The test suite runs on the host, outside this container — this is
    the only way it can see what the stub actually received (which
    credentials authenticated, what was delivered)."""

    def do_GET(self) -> None:
        if self.path == "/deliveries":
            body = json.dumps(DELIVERIES).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_DELETE(self) -> None:
        if self.path == "/deliveries":
            DELIVERIES.clear()
            self.send_response(204)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_PUT(self) -> None:
        if self.path == "/credentials":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            # Lets the "credential rotation" integration test simulate the
            # provider-side password actually changing, not just the
            # relay's stored copy of it — the property under test is
            # "old fails, new works, local user untouched."
            _CREDENTIALS[body["username"]] = body["password"]
            self.send_response(204)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # keep container logs focused on the SMTP side


def main() -> None:
    controller = Controller(
        _Handler(),
        hostname="0.0.0.0",
        port=2525,
        authenticator=_Authenticator(),
        auth_required=True,
        auth_require_tls=True,
        tls_context=_build_ssl_context(),
        require_starttls=True,
    )
    controller.start()

    http_server = ThreadingHTTPServer(("0.0.0.0", 2526), _InspectionHandler)
    threading.Thread(target=http_server.serve_forever, daemon=True).start()

    print("upstream-stub listening on :2525 (SMTP/STARTTLS), :2526 (inspection HTTP)", flush=True)
    asyncio.get_event_loop().run_forever()


if __name__ == "__main__":
    main()
