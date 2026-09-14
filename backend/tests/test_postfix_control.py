import json
import socket
import threading
from collections.abc import Callable, Generator

import pytest

from app.config import get_settings
from app.core.postfix_control import (
    PostfixControlError,
    apply_config,
    queue_delete,
    queue_list,
    queue_requeue,
    sasl_delete_user,
    sasl_set_user,
    status,
    tail_maillog,
    version,
)

# AF_UNIX is what the real deployment target (Linux, inside the postfix
# container) always has — some Windows Python builds don't expose it even
# though the OS itself may support it. Skip rather than fail on those dev
# machines; CI runs on Linux and exercises this module for real.
pytestmark = pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"),
    reason="AF_UNIX not available on this Python/OS build",
)


def _serve_one(
    sock_path: str, responder: Callable[[dict], dict], stop_event: threading.Event, ready_event: threading.Event
) -> None:
    """A minimal stand-in for postfix/control_surface.py's real server —
    exercises the actual wire protocol (one JSON line in, one JSON line
    out, over AF_UNIX) without needing the real script or a Postfix
    install anywhere near this test."""
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    server.listen(1)
    server.settimeout(0.2)
    ready_event.set()
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
        ready_event = threading.Event()
        thread = threading.Thread(
            target=_serve_one, args=(sock_path, responder, stop_event, ready_event), daemon=True
        )
        thread.start()
        # Without this, the client connect below races the server thread's
        # bind()/listen() — usually wins on a fast/idle machine, but flakes
        # (FileNotFoundError/ConnectionRefused) on a busier one, such as a
        # shared CI runner.
        if not ready_event.wait(timeout=2):
            raise RuntimeError("test control server did not become ready in time")
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


def test_status_running(control_socket) -> None:
    control_socket(lambda req: {"ok": True, "running": True, "detail": "postfix/postfix-script: is running"})
    result = status()
    assert result.running is True
    assert "is running" in result.detail


def test_status_not_running(control_socket) -> None:
    control_socket(lambda req: {"ok": True, "running": False, "detail": "the Postfix mail system is not running"})
    result = status()
    assert result.running is False


def test_version_success(control_socket) -> None:
    control_socket(lambda req: {"ok": True, "version": "3.8.6"})
    assert version() == "3.8.6"


def test_tail_maillog_success(control_socket) -> None:
    received = []
    response = {"ok": True, "lines": ["line one", "line two"], "new_offset": 42, "truncated": False}
    control_socket(lambda req: (received.append(req), response)[1])
    result = tail_maillog(17)
    assert received == [{"op": "tail_maillog", "since_offset": 17}]
    assert result.lines == ["line one", "line two"]
    assert result.new_offset == 42
    assert result.truncated is False


def test_queue_list_success(control_socket) -> None:
    entries = [{"queue_id": "Q1", "sender": "a@example.com", "recipients": []}]
    control_socket(lambda req: {"ok": True, "entries": entries})
    assert queue_list() == entries


def test_queue_requeue_success(control_socket) -> None:
    received = []
    control_socket(lambda req: (received.append(req), {"ok": True})[1])
    queue_requeue("Q1")
    assert received == [{"op": "queue_requeue", "queue_id": "Q1"}]


def test_queue_delete_success(control_socket) -> None:
    received = []
    control_socket(lambda req: (received.append(req), {"ok": True})[1])
    queue_delete("Q1")
    assert received == [{"op": "queue_delete", "queue_id": "Q1"}]
