"""Unit tests for postfix/control_surface.py.

That script runs stdlib-only inside the `postfix` container (see its own
module docstring) and is otherwise only exercised by the real-Docker
integration suite (integration/test_relay_e2e.py). These tests import it
directly by file path and monkeypatch `_run` (its one `subprocess.run`
wrapper) so the SASL idempotency logic itself gets fast, real unit coverage
without needing saslpasswd2/sasldblistusers2 installed.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[2] / "postfix" / "control_surface.py"
_spec = importlib.util.spec_from_file_location("control_surface", _MODULE_PATH)
control_surface = importlib.util.module_from_spec(_spec)
sys.modules["control_surface"] = control_surface
_spec.loader.exec_module(control_surface)


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_delete_is_a_noop_when_sasldblistusers2_shows_the_user_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess:
        calls.append(args)
        assert args[0] == "sasldblistusers2", "delete must check existence, not call saslpasswd2 -d at all"
        return _completed(0, stdout="other@smtp-relay.internal: userPassword\n")

    monkeypatch.setattr(control_surface, "_run", fake_run)

    result = control_surface._sasl_delete_user({"username": "inventree"})

    assert result == {"ok": True}
    assert len(calls) == 1


def test_delete_calls_saslpasswd2_when_the_user_exists_and_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess:
        calls.append(args)
        if args[0] == "sasldblistusers2":
            return _completed(0, stdout="inventree@smtp-relay.internal: userPassword\n")
        assert args[:2] == ["saslpasswd2", "-d"]
        return _completed(0)

    monkeypatch.setattr(control_surface, "_run", fake_run)

    result = control_surface._sasl_delete_user({"username": "inventree"})

    assert result == {"ok": True}
    assert [c[0] for c in calls] == ["sasldblistusers2", "saslpasswd2"]


def test_delete_reports_a_real_failure_from_saslpasswd2(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess:
        if args[0] == "sasldblistusers2":
            return _completed(0, stdout="inventree@smtp-relay.internal: userPassword\n")
        return _completed(1, stderr="permission denied")

    monkeypatch.setattr(control_surface, "_run", fake_run)

    result = control_surface._sasl_delete_user({"username": "inventree"})

    assert result["ok"] is False
    assert "permission denied" in result["error"]


def test_existence_check_matches_the_realm_suffixed_username_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    """A prefix match against the bare username would wrongly treat
    "inventree-printer" as proof "inventree" exists — the ':' after the
    realm in sasldblistusers2's own output format is what prevents that."""

    def fake_run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess:
        assert args == ["sasldblistusers2"]
        return _completed(0, stdout="inventree-printer@smtp-relay.internal: userPassword\n")

    monkeypatch.setattr(control_surface, "_run", fake_run)

    assert control_surface._sasl_user_exists("inventree") is False


def test_existence_check_falls_back_to_true_when_sasldblistusers2_itself_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Can't determine either way — fall through to attempting the real
    delete and surfacing whatever saslpasswd2 itself says, rather than
    silently pretending the user is absent."""

    def fake_run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess:
        return _completed(1, stderr="sasldb2 unreadable")

    monkeypatch.setattr(control_surface, "_run", fake_run)

    assert control_surface._sasl_user_exists("inventree") is True
