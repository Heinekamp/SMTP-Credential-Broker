import json
import socket
import threading
from collections.abc import Callable, Generator

import pytest

from app.config import get_settings
from app.core.postfix_control import PostfixControlError, apply_config, sasl_delete_user, sasl_set_user

# AF_UNIX is what the real deployment target (Linux, inside the postfix
# container) always has — some Windows Python builds don't expose it even
# though the OS itself may support it. Skip rather than fail on those dev
# machines; CI runs on Linux and exercises this module for real.
pytestmark = pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"),
    reason="AF_UNIX not available on this Python/OS build",
)


def _serve_one(sock_path: str, responder: Callable[[dict], dict], stop_event: threading.Event) -> None:
    """A minimal stand-in for postfix/control_surface.py's real server —
    exercises the actual wire protocol (one JSON line in, one JSON line
    out, over AF_UNIX) without needing the real script or a Postfix
    install anywhere near this test."""
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    server.listen(1)
    server.settimeout(0.2)
    while not stop_event.is_set():
        try:
            conn, _ = server.accept()
        except TimeoutError:
            continue
        with conn:
            chunks = []
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
            request = json.loads(b"".join(chunks).decode("utf-8"))
            response = responder(request)
            conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
    server.close()


@pytest.fixture()
def control_socket(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Generator[Callable, None, None]:
    sock_path = str(tmp_path / "control.sock")
    monkeypatch.setenv("RELAY_POSTFIX_CONTROL_SOCKET", sock_path)
    get_settings.cache_clear()

    threads: list[tuple[threading.Thread, threading.Event]] = []

    def _start(responder: Callable[[dict], dict]) -> None:
        stop_event = threading.Event()
        thread = threading.Thread(target=_serve_one, args=(sock_path, responder, stop_event), daemon=True)
        thread.start()
        threads.append((thread, stop_event))

    yield _start

    for thread, stop_event in threads:
        stop_event.set()
        thread.join(timeout=2)
    get_settings.cache_clear()


def test_sasl_set_user_success(control_socket) -> None:
    received = []
    control_socket(lambda req: (received.append(req), {"ok": True})[1])
    sasl_set_user("printer-service", "hunter2")
    assert received == [{"op": "sasl_set_user", "username": "printer-service", "password": "hunter2"}]


def test_sasl_delete_user_success(control_socket) -> None:
    received = []
    control_socket(lambda req: (received.append(req), {"ok": True})[1])
    sasl_delete_user("printer-service")
    assert received == [{"op": "sasl_delete_user", "username": "printer-service"}]


def test_server_reported_failure_raises_postfix_control_error(control_socket) -> None:
    control_socket(lambda req: {"ok": False, "error": "unknown op"})
    with pytest.raises(PostfixControlError, match="unknown op"):
        sasl_set_user("x", "y")


def test_unreachable_socket_raises(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("RELAY_POSTFIX_CONTROL_SOCKET", str(tmp_path / "does-not-exist.sock"))
    get_settings.cache_clear()
    try:
        with pytest.raises(PostfixControlError):
            sasl_set_user("x", "y")
    finally:
        get_settings.cache_clear()


def test_apply_config_success(control_socket) -> None:
    control_socket(
        lambda req: {"ok": True, "success": True, "validation_detail": "postconf: OK", "reloaded": True}
    )
    result = apply_config(main_cf="main", master_cf="master", maps={"sender_login": "a b"}, reload_if_main_changed=True)
    assert result.success is True
    assert result.reloaded is True
    assert "OK" in result.validation_detail


def test_apply_config_reports_validation_failure_without_raising(control_socket) -> None:
    """A bad generated config is an expected, reportable outcome — not a
    PostfixControlError. architecture.md §5: the previous good config must
    stay active, and the caller needs the detail to show the admin."""
    control_socket(
        lambda req: {
            "ok": True,
            "success": False,
            "validation_detail": "postconf: warning: unknown parameter: bogus_directive",
            "reloaded": False,
        }
    )
    result = apply_config(main_cf="main", master_cf="master", maps={}, reload_if_main_changed=True)
    assert result.success is False
    assert result.reloaded is False
    assert "bogus_directive" in result.validation_detail
