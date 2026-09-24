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
from collections.abc import Callable
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


def _patch_sasldb_paths(monkeypatch: pytest.MonkeyPatch, tmp_path, *, seed: str = "") -> tuple[Path, Path]:
    """Points SASLDB_PATH/SASLDB_DIR (issue #118's sync mechanism) at real
    tmp_path locations so _sync_sasldb_to_volume's shutil.copyfile has
    somewhere real to read from and write to — the module's own default
    paths (/etc/sasldb2, /var/lib/postfix-sasldb) only exist inside the
    real postfix container."""
    sasldb_path = tmp_path / "sasldb2"
    sasldb_path.write_text(seed, encoding="utf-8")
    sasldb_dir = tmp_path / "sasldb-volume"
    sasldb_dir.mkdir()
    monkeypatch.setattr(control_surface, "SASLDB_PATH", str(sasldb_path))
    monkeypatch.setattr(control_surface, "SASLDB_DIR", str(sasldb_dir))
    return sasldb_path, sasldb_dir


def test_delete_calls_saslpasswd2_when_the_user_exists_and_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _sasldb_path, sasldb_dir = _patch_sasldb_paths(monkeypatch, tmp_path, seed="db content after delete")
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
    # Issue #118: a successful delete must sync the live file out to the
    # persisted volume, or the deleted user's absence wouldn't survive a
    # future container recreation any more than a created user's presence
    # would without this.
    assert (sasldb_dir / "sasldb2").read_text(encoding="utf-8") == "db content after delete"


def test_set_user_calls_saslpasswd2_and_syncs_to_the_persisted_volume(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Regression test for issue #118: a created local user's credential
    used to exist only in the postfix container's own writable layer.
    saslpasswd2 succeeding is necessary but not sufficient — the live
    sasldb2 file must also be synced out to the volume-backed directory
    entrypoint.sh restores from on the container's next boot."""
    _sasldb_path, sasldb_dir = _patch_sasldb_paths(monkeypatch, tmp_path, seed="db content after create")
    calls: list[list[str]] = []

    def fake_run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess:
        calls.append(args)
        assert args[:2] == ["saslpasswd2", "-c"]
        assert input_text == "hunter2"  # never an argv — postfix-architecture.md §5
        return _completed(0)

    monkeypatch.setattr(control_surface, "_run", fake_run)

    result = control_surface._sasl_set_user({"username": "inventree", "password": "hunter2"})

    assert result == {"ok": True}
    assert len(calls) == 1
    assert (sasldb_dir / "sasldb2").read_text(encoding="utf-8") == "db content after create"


def test_set_user_fails_when_saslpasswd2_itself_fails(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _patch_sasldb_paths(monkeypatch, tmp_path)

    def fake_run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess:
        return _completed(1, stderr="permission denied")

    monkeypatch.setattr(control_surface, "_run", fake_run)

    result = control_surface._sasl_set_user({"username": "inventree", "password": "hunter2"})

    assert result["ok"] is False
    assert "permission denied" in result["error"]


def test_set_user_fails_when_saslpasswd2_succeeds_but_the_volume_sync_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A local user's credential existing only where saslpasswd2 itself
    wrote it — with no durable copy — is exactly issue #118. If the sync
    step can't complete (e.g. the persisted volume is unreachable), that
    has to fail loudly rather than report success with a credential that
    silently won't survive the next container recreation."""
    monkeypatch.setattr(control_surface, "SASLDB_PATH", str(tmp_path / "sasldb2"))
    # A directory, not a file, at SASLDB_PATH: saslpasswd2 (faked below)
    # "succeeds" without ever writing anything real, so the later
    # shutil.copyfile has nothing valid to read — deliberately provoking
    # the sync failure this test exists to cover.
    (tmp_path / "sasldb2").mkdir()
    monkeypatch.setattr(control_surface, "SASLDB_DIR", str(tmp_path / "nonexistent-volume"))

    def fake_run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess:
        return _completed(0)

    monkeypatch.setattr(control_surface, "_run", fake_run)

    result = control_surface._sasl_set_user({"username": "inventree", "password": "hunter2"})

    assert result["ok"] is False
    assert "syncing to the persisted volume failed" in result["error"]


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


def test_tail_maillog_first_call_reports_the_current_inode(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    maillog = tmp_path / "maillog"
    maillog.write_text("line one\nline two\n", encoding="utf-8")
    monkeypatch.setattr(control_surface, "MAILLOG_PATH", str(maillog))

    result = control_surface._tail_maillog({"since_offset": 0, "since_inode": None})

    assert result["truncated"] is False
    assert result["lines"] == ["line one", "line two"]
    assert result["inode"] is not None


def test_tail_maillog_falls_back_to_size_heuristic_when_inode_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """First-ever call (or an upgrade from before maillog_inode existed)
    has no previous inode to compare against — must still fall back to
    detecting a genuinely-shrunk file by size."""
    maillog = tmp_path / "maillog"
    maillog.write_text("short\n", encoding="utf-8")
    monkeypatch.setattr(control_surface, "MAILLOG_PATH", str(maillog))

    result = control_surface._tail_maillog({"since_offset": 9999, "since_inode": None})

    assert result["truncated"] is True
    assert result["lines"] == ["short"]


def test_tail_maillog_detects_rotation_via_inode_even_when_the_new_file_is_already_larger(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Regression test for issue #31: a rename-based log rotation (the old
    file renamed aside, a new empty one created at the same path) changes
    the inode immediately, but the new file can grow past the old
    since_offset before the next poll — a size-only comparison would
    wrongly conclude nothing rotated and silently seek into the middle of
    the new file instead of starting from its beginning."""
    maillog = tmp_path / "maillog"
    maillog.write_text("old file content, this is the previous log\n", encoding="utf-8")
    monkeypatch.setattr(control_surface, "MAILLOG_PATH", str(maillog))
    old_inode = control_surface._tail_maillog({"since_offset": 0, "since_inode": None})["inode"]
    old_offset = len("old file content, this is the previous log\n")

    # Simulate logrotate's actual rename+create (not unlink+create): the
    # old file is renamed aside — still alive under its new name, so its
    # inode can't be handed back out — and a brand new file is created at
    # the original path, which is what guarantees a fresh inode. Deleting
    # the file first (unlink) instead of renaming it would free its inode
    # immediately, and a filesystem is free to reuse that exact number for
    # the very next file created there — which is exactly what happened
    # under the original version of this test (flaky/wrong on Linux CI:
    # https://github.com/Heinekamp/smtp-credential-broker/issues/31 was correctly
    # fixed, but this test's own simulation of rotation was not
    # equivalent to what it claimed to simulate).
    maillog.rename(tmp_path / "maillog.1")
    maillog.write_text("x" * (old_offset + 500) + "\nnew log line\n", encoding="utf-8")

    result = control_surface._tail_maillog({"since_offset": old_offset, "since_inode": old_inode})

    assert result["truncated"] is True
    assert "new log line" in result["lines"][-1] or any("new log line" in line for line in result["lines"])
    assert result["inode"] != old_inode


def test_tail_maillog_no_rotation_uses_the_offset_normally(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    maillog = tmp_path / "maillog"
    maillog.write_text("first\n", encoding="utf-8")
    monkeypatch.setattr(control_surface, "MAILLOG_PATH", str(maillog))
    first = control_surface._tail_maillog({"since_offset": 0, "since_inode": None})

    with open(maillog, "a", encoding="utf-8") as f:
        f.write("second\n")

    result = control_surface._tail_maillog({"since_offset": first["new_offset"], "since_inode": first["inode"]})

    assert result["truncated"] is False
    assert result["lines"] == ["second"]


def test_validate_staged_config_catches_a_master_cf_syntax_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression test: validation used to only run `postconf -n`, which
    never parses master.cf at all — a broken master.cf would sail through
    and only fail later, after install, when `postfix start` itself
    choked on it. `postconf -M` is the one that actually parses master.cf."""

    def fake_run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess:
        if args[-1] == "-n":
            return _completed(0, stdout="mail_version = 3.8.6\n")
        assert args[-1] == "-M"
        return _completed(1, stderr="postconf: fatal: bad master.cf syntax on line 4")

    monkeypatch.setattr(control_surface, "_run", fake_run)

    valid, detail = control_surface._validate_staged_config("main", "master")

    assert valid is False
    assert "bad master.cf syntax" in detail


def _fixed_apply_payload() -> dict:
    return {"main_cf": "new main", "master_cf": "new master", "maps": {}, "reload_if_main_changed": True}


def test_apply_config_rolls_back_when_postfix_start_fails_after_a_valid_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Regression test: postconf -n/-M can pass while `postfix start`
    itself still fails (e.g. a master.cf service pointing at a
    chroot/queue path that doesn't exist) — a defect validation can't
    catch. The newly-installed, broken config used to just stay on disk
    with the relay left stopped. It must instead restore the config that
    was live before this apply and get the relay back up with it."""
    config_dir = tmp_path / "postfix"
    config_dir.mkdir()
    (config_dir / "main.cf").write_text("old main", encoding="utf-8")
    (config_dir / "master.cf").write_text("old master", encoding="utf-8")
    monkeypatch.setattr(control_surface, "POSTFIX_CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(control_surface, "RELAY_MAP_DIR", str(tmp_path / "relay"))

    start_attempts = {"count": 0}

    def fake_run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess:
        if args[0] == "postconf":
            return _completed(0)
        if args == ["postfix", "stop"]:
            return _completed(0)
        if args == ["postfix", "start"]:
            start_attempts["count"] += 1
            if start_attempts["count"] == 1:
                return _completed(1, stderr="fatal: bad service in master.cf")
            return _completed(0)
        raise AssertionError(f"unexpected call: {args}")

    monkeypatch.setattr(control_surface, "_run", fake_run)

    result = control_surface._apply_config(_fixed_apply_payload())

    assert result["success"] is False
    assert "rolled back to the previous config and restarted successfully" in result["validation_detail"]
    assert (config_dir / "main.cf").read_text(encoding="utf-8") == "old main"
    assert (config_dir / "master.cf").read_text(encoding="utf-8") == "old master"
    assert start_attempts["count"] == 2


def test_apply_config_reports_when_the_rollback_start_also_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    config_dir = tmp_path / "postfix"
    config_dir.mkdir()
    (config_dir / "main.cf").write_text("old main", encoding="utf-8")
    (config_dir / "master.cf").write_text("old master", encoding="utf-8")
    monkeypatch.setattr(control_surface, "POSTFIX_CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(control_surface, "RELAY_MAP_DIR", str(tmp_path / "relay"))

    def fake_run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess:
        if args[0] == "postconf":
            return _completed(0)
        if args == ["postfix", "stop"]:
            return _completed(0)
        if args == ["postfix", "start"]:
            return _completed(1, stderr="still broken")
        raise AssertionError(f"unexpected call: {args}")

    monkeypatch.setattr(control_surface, "_run", fake_run)

    result = control_surface._apply_config(_fixed_apply_payload())

    assert result["success"] is False
    assert "rollback to the previous config ALSO failed to start" in result["validation_detail"]


def _fixed_tls_payload(cert: str = "new cert", key: str = "new key") -> dict:
    return {"cert_pem": cert, "key_pem": key}


def _openssl_ok_fake_run(
    *, matching: bool = True, stop_ok: bool = True, start_returncodes: list[int] | None = None
) -> tuple[Callable, dict]:
    """Builds a fake `_run` that passes openssl validation (cert not
    expired, key matches cert unless `matching=False`) and records every
    call, so tests can assert on ordering/count without duplicating this
    boilerplate for every scenario."""
    calls: list[list[str]] = []
    starts = {"count": 0}
    start_returncodes = start_returncodes if start_returncodes is not None else [0]

    def fake_run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess:
        calls.append(args)
        if args[:2] == ["openssl", "x509"] and "-checkend" in args:
            return _completed(0)
        if args[:2] == ["openssl", "x509"] and "-pubkey" in args:
            return _completed(0, stdout="PUBKEY-A\n")
        if args[:2] == ["openssl", "pkey"]:
            return _completed(0, stdout="PUBKEY-A\n" if matching else "PUBKEY-B\n")
        if args == ["postfix", "stop"]:
            return _completed(0 if stop_ok else 1)
        if args == ["postfix", "start"]:
            idx = min(starts["count"], len(start_returncodes) - 1)
            rc = start_returncodes[idx]
            starts["count"] += 1
            return _completed(rc, stderr="" if rc == 0 else "fatal: bad tls config")
        raise AssertionError(f"unexpected call: {args}")

    return fake_run, calls


def test_install_tls_certificate_success_installs_and_restarts(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    tls_dir = tmp_path / "tls"
    tls_dir.mkdir()
    monkeypatch.setattr(control_surface, "TLS_DIR", str(tls_dir))
    fake_run, calls = _openssl_ok_fake_run()
    monkeypatch.setattr(control_surface, "_run", fake_run)

    result = control_surface._install_tls_certificate(_fixed_tls_payload())

    assert result == {"ok": True, "success": True, "detail": "Installed.", "restarted": True}
    assert (tls_dir / "relay.crt").read_text(encoding="utf-8") == "new cert"
    assert (tls_dir / "relay.key").read_text(encoding="utf-8") == "new key"
    assert calls[-2:] == [["postfix", "stop"], ["postfix", "start"]]


def test_install_tls_certificate_rejects_expired_certificate(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    tls_dir = tmp_path / "tls"
    tls_dir.mkdir()
    monkeypatch.setattr(control_surface, "TLS_DIR", str(tls_dir))

    def fake_run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess:
        if "-checkend" in args:
            return _completed(1)  # already expired
        raise AssertionError(f"unexpected call: {args}")

    monkeypatch.setattr(control_surface, "_run", fake_run)

    result = control_surface._install_tls_certificate(_fixed_tls_payload())

    assert result == {"ok": True, "success": False, "detail": "Certificate is already expired."}
    assert not (tls_dir / "relay.crt").exists()


def test_install_tls_certificate_rejects_mismatched_key(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    tls_dir = tmp_path / "tls"
    tls_dir.mkdir()
    monkeypatch.setattr(control_surface, "TLS_DIR", str(tls_dir))
    fake_run, _ = _openssl_ok_fake_run(matching=False)
    monkeypatch.setattr(control_surface, "_run", fake_run)

    result = control_surface._install_tls_certificate(_fixed_tls_payload())

    assert result == {"ok": True, "success": False, "detail": "Private key does not match certificate."}
    assert not (tls_dir / "relay.crt").exists()


def test_install_tls_certificate_is_a_noop_when_already_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    tls_dir = tmp_path / "tls"
    tls_dir.mkdir()
    (tls_dir / "relay.crt").write_text("new cert", encoding="utf-8")
    (tls_dir / "relay.key").write_text("new key", encoding="utf-8")
    monkeypatch.setattr(control_surface, "TLS_DIR", str(tls_dir))
    fake_run, calls = _openssl_ok_fake_run()
    monkeypatch.setattr(control_surface, "_run", fake_run)

    result = control_surface._install_tls_certificate(_fixed_tls_payload())

    assert result == {"ok": True, "success": True, "detail": "Already installed — no change.", "restarted": False}
    assert not any(c[0] == "postfix" for c in calls), "must not bounce postfix when nothing actually changed"


def test_install_tls_certificate_rolls_back_when_postfix_start_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    tls_dir = tmp_path / "tls"
    tls_dir.mkdir()
    (tls_dir / "relay.crt").write_text("old cert", encoding="utf-8")
    (tls_dir / "relay.key").write_text("old key", encoding="utf-8")
    monkeypatch.setattr(control_surface, "TLS_DIR", str(tls_dir))
    fake_run, calls = _openssl_ok_fake_run(start_returncodes=[1, 0])
    monkeypatch.setattr(control_surface, "_run", fake_run)

    result = control_surface._install_tls_certificate(_fixed_tls_payload())

    assert result["success"] is False
    assert "rolled back to the previous certificate and restarted successfully" in result["detail"]
    assert (tls_dir / "relay.crt").read_text(encoding="utf-8") == "old cert"
    assert (tls_dir / "relay.key").read_text(encoding="utf-8") == "old key"
    assert len([c for c in calls if c == ["postfix", "start"]]) == 2


def test_install_tls_certificate_reports_when_rollback_start_also_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    tls_dir = tmp_path / "tls"
    tls_dir.mkdir()
    (tls_dir / "relay.crt").write_text("old cert", encoding="utf-8")
    (tls_dir / "relay.key").write_text("old key", encoding="utf-8")
    monkeypatch.setattr(control_surface, "TLS_DIR", str(tls_dir))
    fake_run, _ = _openssl_ok_fake_run(start_returncodes=[1, 1])
    monkeypatch.setattr(control_surface, "_run", fake_run)

    result = control_surface._install_tls_certificate(_fixed_tls_payload())

    assert result["success"] is False
    assert "rollback ALSO failed to start" in result["detail"]


def test_install_tls_certificate_on_first_boot_has_nothing_to_roll_back_to(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    tls_dir = tmp_path / "tls"
    tls_dir.mkdir()  # empty — no placeholder cert ever installed
    monkeypatch.setattr(control_surface, "TLS_DIR", str(tls_dir))
    fake_run, _ = _openssl_ok_fake_run(start_returncodes=[1])
    monkeypatch.setattr(control_surface, "_run", fake_run)

    result = control_surface._install_tls_certificate(_fixed_tls_payload())

    assert result["success"] is False
    assert "rolled back" not in result["detail"]


def test_apply_config_on_first_boot_has_nothing_to_roll_back_to(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """First boot: no main.cf/master.cf exists yet, so a failed
    `postfix start` has no previous config to restore — must not attempt
    a pointless rollback restart."""
    config_dir = tmp_path / "postfix"
    config_dir.mkdir()
    monkeypatch.setattr(control_surface, "POSTFIX_CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(control_surface, "RELAY_MAP_DIR", str(tmp_path / "relay"))

    start_attempts = {"count": 0}

    def fake_run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess:
        if args[0] == "postconf":
            return _completed(0)
        if args == ["postfix", "stop"]:
            return _completed(0)
        if args == ["postfix", "start"]:
            start_attempts["count"] += 1
            return _completed(1, stderr="fatal: bad service in master.cf")
        raise AssertionError(f"unexpected call: {args}")

    monkeypatch.setattr(control_surface, "_run", fake_run)

    result = control_surface._apply_config(_fixed_apply_payload())

    assert result["success"] is False
    assert "rolled back" not in result["validation_detail"]
    assert start_attempts["count"] == 1
