"""The policy service's network listener itself (#167) — who may connect,
how much a request may contain — over a real loopback socket.
evaluate()'s decision logic is covered in test_rate_limit_policy.py."""

import asyncio
import socket

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.core import rate_limit_policy
from app.core.rate_limit_policy import _peer_is_allowed, run_policy_service


@pytest.mark.parametrize(
    ("peer", "allowed", "expected"),
    [
        ("127.0.0.1", "postfix.invalid", True),  # loopback is always allowed
        ("::1", "postfix.invalid", True),
        ("10.0.0.5", "10.0.0.5", True),  # the allowed service's own address
        ("10.0.0.6", "10.0.0.5", False),  # any other container on the network
        ("10.0.0.5", "postfix.invalid", False),  # unresolvable: refuse, Postfix then fails open
        ("10.0.0.6", None, True),  # check explicitly disabled
    ],
)
def test_only_the_postfix_service_may_connect(peer: str, allowed: str | None, expected: bool) -> None:
    assert asyncio.run(_peer_is_allowed(peer, allowed)) is expected


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _exchange(db_session: Session, monkeypatch: pytest.MonkeyPatch, payload: bytes) -> bytes:
    """Starts the real listener on a loopback port, sends `payload`, and
    returns whatever comes back before the server closes the connection."""
    monkeypatch.setattr(rate_limit_policy, "SessionLocal", sessionmaker(bind=db_session.get_bind()))
    port = _free_port()

    async def scenario() -> bytes:
        server = asyncio.create_task(run_policy_service(port, allowed_host=None, host="127.0.0.1"))
        try:
            for _ in range(50):
                try:
                    reader, writer = await asyncio.open_connection("127.0.0.1", port)
                    break
                except OSError:
                    await asyncio.sleep(0.05)
            writer.write(payload)
            await writer.drain()
            writer.write_eof()
            data = await asyncio.wait_for(reader.read(), timeout=5)
            writer.close()
            return data
        finally:
            server.cancel()
            await asyncio.gather(server, return_exceptions=True)

    return asyncio.run(scenario())


def test_a_normal_request_gets_an_answer(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    request = b"request=smtpd_access_policy\nprotocol_state=END-OF-MESSAGE\nsasl_username=nobody\n\n"
    assert _exchange(db_session, monkeypatch, request) == b"action=DUNNO\n\n"


def test_an_oversized_request_is_dropped_without_an_answer(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test for #167: attribute lines used to accumulate without
    bound, so one connection could exhaust the app's memory."""
    request = b"".join(b"padding%d=x\n" % i for i in range(1000)) + b"\n"
    assert _exchange(db_session, monkeypatch, request) == b""


def test_an_overlong_line_is_dropped_without_an_answer(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    request = b"sasl_username=" + b"x" * 100_000 + b"\n\n"
    assert _exchange(db_session, monkeypatch, request) == b""
