#!/usr/bin/env python3
"""The Postfix container's control surface (security-model.md §6).

Runs as root inside the `postfix` container, listening on a Unix domain
socket that only the `app` container can reach (a private Docker volume,
never a network port). It is the *only* channel `app` uses to mutate
sasldb2 or install generated Postfix configuration — `app` never has a
shell in this container or direct filesystem access to `/etc/postfix` or
`/etc/sasldb2`.

Protocol: one JSON object per connection, newline-terminated, in; one JSON
object, newline-terminated, out. See backend/app/core/postfix_control.py
for the client side and the exact request/response shapes.

This script is intentionally dependency-free (stdlib only) so the postfix
image only needs a bare `python3` package, not a virtualenv.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile

CONTROL_SOCKET_PATH = os.environ.get("CONTROL_SOCKET_PATH", "/etc/postfix/relay/control.sock")
SASL_REALM = os.environ.get("RELAY_SUBMISSION_HOST", "smtp-relay.internal")
POSTFIX_CONFIG_DIR = "/etc/postfix"
RELAY_MAP_DIR = "/etc/postfix/relay"
MAP_TYPE = "lmdb"
MAILLOG_PATH = "/var/log/postfix/maillog"


def _run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _sasl_set_user(payload: dict) -> dict:
    username = payload["username"]
    password = payload["password"]
    # Password piped via stdin, never an argv (visible to other processes
    # via /proc) and never logged — postfix-architecture.md §5.
    result = _run(
        ["saslpasswd2", "-c", "-p", "-u", SASL_REALM, username],
        input_text=password,
    )
    if result.returncode != 0:
        return {"ok": False, "error": f"saslpasswd2 failed: {result.stderr.strip()}"}
    return {"ok": True}


def _sasl_user_exists(username: str) -> bool:
    # sasldblistusers2 prints one "user@realm: userPassword" line per entry
    # — a positive existence check, unlike pattern-matching saslpasswd2's
    # own (version/locale-dependent) stderr wording. Same sasl2-bin package
    # as saslpasswd2, so it's always present alongside it.
    result = _run(["sasldblistusers2"])
    if result.returncode != 0:
        # Can't determine — fall through to attempting the delete and
        # reporting whatever saslpasswd2 itself says, rather than guessing.
        return True
    prefix = f"{username}@{SASL_REALM}:"
    return any(line.startswith(prefix) for line in result.stdout.splitlines())


def _sasl_delete_user(payload: dict) -> dict:
    username = payload["username"]
    # Idempotent delete (matches the app-side revoke/disable semantics):
    # check existence first with a real command rather than guessing from
    # saslpasswd2's own stderr wording, which is version/locale-dependent.
    if not _sasl_user_exists(username):
        return {"ok": True}
    result = _run(["saslpasswd2", "-d", "-u", SASL_REALM, username])
    if result.returncode != 0:
        return {"ok": False, "error": f"saslpasswd2 -d failed: {result.stderr.strip()}"}
    return {"ok": True}


def _validate_staged_config(main_cf: str, master_cf: str) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as staging_dir:
        with open(os.path.join(staging_dir, "main.cf"), "w", encoding="utf-8") as f:
            f.write(main_cf)
        with open(os.path.join(staging_dir, "master.cf"), "w", encoding="utf-8") as f:
            f.write(master_cf)
        main_result = _run(["postconf", "-c", staging_dir, "-n"])
        # `postconf -n` only validates/dumps *main.cf* parameters — it
        # never parses master.cf at all, so a broken master.cf (found via
        # code review: nothing here previously validated its syntax)
        # would sail through this check and only fail later, after
        # install, when `postfix start` itself chokes on it. `-M` forces
        # postconf to also parse and print master.cf's service table,
        # catching the same class of syntax error here instead, while
        # nothing on disk has been touched yet.
        master_result = _run(["postconf", "-c", staging_dir, "-M"])
        detail = (
            main_result.stdout + main_result.stderr + master_result.stdout + master_result.stderr
        ).strip()
        # postconf exits non-zero on a hard parse error; "warning:" lines
        # about unknown parameters are noise we still want to see but not
        # treat as fatal, so the check is on returncode, not stderr content.
        valid = main_result.returncode == 0 and master_result.returncode == 0
        return valid, detail or "postconf: OK"


def _install_maps(maps: dict[str, str]) -> None:
    os.makedirs(RELAY_MAP_DIR, exist_ok=True)
    for name, content in maps.items():
        source_path = os.path.join(RELAY_MAP_DIR, name)
        tmp_path = source_path + ".new"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, source_path)  # atomic on the same filesystem
        result = _run(["postmap", f"{MAP_TYPE}:{source_path}"])
        if result.returncode != 0:
            raise RuntimeError(f"postmap failed for {name}: {result.stderr.strip()}")


def _install_config(main_cf: str, master_cf: str) -> dict[str, str | None]:
    """Installs main.cf/master.cf atomically, returning each file's
    previous content (None if it didn't exist yet — this container's very
    first boot) so a failed `postfix start` afterward has something to
    roll back to."""
    previous: dict[str, str | None] = {}
    for filename, content in (("main.cf", main_cf), ("master.cf", master_cf)):
        live_path = os.path.join(POSTFIX_CONFIG_DIR, filename)
        try:
            with open(live_path, encoding="utf-8") as f:
                previous[filename] = f.read()
        except OSError:
            previous[filename] = None
        tmp_path = live_path + ".new"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, live_path)
    return previous


def _restore_config(previous: dict[str, str | None]) -> None:
    for filename, content in previous.items():
        if content is None:  # didn't exist before install — nothing to restore
            continue
        live_path = os.path.join(POSTFIX_CONFIG_DIR, filename)
        tmp_path = live_path + ".new"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, live_path)


def _apply_config(payload: dict) -> dict:
    main_cf = payload["main_cf"]
    master_cf = payload["master_cf"]
    maps = payload["maps"]
    reload_if_main_changed = payload["reload_if_main_changed"]

    valid, detail = _validate_staged_config(main_cf, master_cf)
    if not valid:
        # architecture.md §5: the previous good config stays active —
        # nothing on disk is touched when validation fails.
        return {"ok": True, "success": False, "validation_detail": detail, "reloaded": False}

    try:
        # main.cf must exist on disk before `postmap` runs — it does its
        # own config lookups and fails outright ("open /etc/postfix/main.cf:
        # No such file or directory") if main.cf isn't there yet, which is
        # exactly the state on this container's very first boot before any
        # config has ever been installed.
        previous_config = _install_config(main_cf, master_cf)
        _install_maps(maps)
    except (OSError, RuntimeError) as exc:
        return {"ok": True, "success": False, "validation_detail": f"install failed: {exc}", "reloaded": False}

    reloaded = False
    if reload_if_main_changed:
        # SIGHUP-triggered `postfix reload` reproducibly crashed the
        # master process in real testing against a real Postfix instance
        # — every second-and-later config change, regardless of whether
        # master ran as this container's PID 1 (`start-fg`) or as a
        # normal detached daemon (`postfix start`). A cold stop+start of
        # the exact same config never had that problem in the same
        # testing. This is also how Postfix gets started at all on this
        # container's first boot — nothing else starts it (see
        # postfix/entrypoint.sh).
        _run(["postfix", "stop"])  # best-effort; "not running" here is fine
        start_result = _run(["postfix", "start"])
        if start_result.returncode != 0:
            combined = f"{start_result.stdout}\n{start_result.stderr}".strip()
            # postconf -n/-M passed but a defect only `postfix start`
            # itself catches (e.g. a master.cf service pointing at a
            # chroot/queue path that doesn't exist) still slipped through
            # validation. The new, broken config is already installed at
            # this point — restore what was there before and try to get
            # the relay back up with it, rather than leaving it stopped
            # with the broken config still on disk (architecture.md §5's
            # "previous config stays active" invariant otherwise only
            # held up to the point of install, not through this failure
            # mode).
            rollback_detail = ""
            if any(value is not None for value in previous_config.values()):
                _restore_config(previous_config)
                rollback_start = _run(["postfix", "start"])
                rollback_detail = (
                    "; rolled back to the previous config and restarted successfully"
                    if rollback_start.returncode == 0
                    else f"; rollback to the previous config ALSO failed to start: {rollback_start.stderr.strip()}"
                )
            return {
                "ok": True,
                "success": False,
                "validation_detail": f"{detail}\npostfix start failed: {combined}{rollback_detail}",
                "reloaded": False,
            }
        reloaded = True

    return {"ok": True, "success": True, "validation_detail": detail, "reloaded": reloaded}


def _tail_maillog(payload: dict) -> dict:
    """Returns any maillog bytes written since `since_offset` (Stage 5's
    mail_log ingestion — see backend/app/core/mail_log_ingest.py), plus the
    new offset (and inode) to pass next time. Stateless on this side by
    design: the caller (the app container, which can be restarted
    independently of this one) is the one that persists the offset/inode,
    not this process."""
    since_offset = payload.get("since_offset", 0)
    since_inode = payload.get("since_inode")
    try:
        stat_result = os.stat(MAILLOG_PATH)
    except OSError:
        return {"ok": True, "lines": [], "new_offset": 0, "truncated": False, "inode": None}
    size = stat_result.st_size
    inode = stat_result.st_ino

    # Prefer inode comparison when a previous inode is known — a log
    # rotation that renames the old file and creates a new one at the
    # same path (rather than truncating it in place) changes the inode
    # immediately, even though the new file could grow past the old
    # since_offset before the next poll and make a size-only comparison
    # wrongly conclude nothing was rotated (silently skipping straight
    # into the middle of the new file instead of starting from its
    # beginning). Fall back to the size heuristic only when since_inode
    # is unknown — the very first call, or an upgrade from before this
    # existed.
    if since_inode is not None:
        truncated = inode != since_inode
    else:
        truncated = since_offset > size
    start = 0 if truncated else since_offset

    with open(MAILLOG_PATH, encoding="utf-8", errors="replace") as f:
        f.seek(start)
        data = f.read()

    return {"ok": True, "lines": data.splitlines(), "new_offset": size, "truncated": truncated, "inode": inode}


def _status(payload: dict) -> dict:
    """Backs the health-check "is Postfix's master process actually
    running" check (architecture.md §7) — distinct from "is this control
    surface reachable at all," which a successful RPC round-trip already
    proves on its own. Not running is an entirely expected state before
    the very first successful `apply_config` (see that function's
    comment: nothing else starts Postfix), not necessarily a fault."""
    result = _run(["postfix", "status"])
    detail = (result.stdout + result.stderr).strip()
    return {"ok": True, "running": result.returncode == 0, "detail": detail}


def _version(payload: dict) -> dict:
    # `-h` omits the "mail_version = " prefix `postconf` would otherwise
    # print, giving a bare version string like "3.8.6".
    result = _run(["postconf", "-h", "mail_version"])
    if result.returncode != 0:
        return {"ok": False, "error": f"postconf failed: {result.stderr.strip()}"}
    return {"ok": True, "version": result.stdout.strip()}


def _queue_list(payload: dict) -> dict:
    # `-j`: one JSON object per queued message (Postfix 3.1+) — far more
    # reliable to parse than postqueue -p's human-oriented text table.
    result = _run(["postqueue", "-j"])
    if result.returncode != 0:
        return {"ok": False, "error": f"postqueue -j failed: {result.stderr.strip()}"}
    entries = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    return {"ok": True, "entries": entries}


def _queue_requeue(payload: dict) -> dict:
    result = _run(["postsuper", "-r", payload["queue_id"]])
    if result.returncode != 0:
        return {"ok": False, "error": f"postsuper -r failed: {result.stderr.strip()}"}
    return {"ok": True}


def _queue_delete(payload: dict) -> dict:
    result = _run(["postsuper", "-d", payload["queue_id"]])
    if result.returncode != 0:
        return {"ok": False, "error": f"postsuper -d failed: {result.stderr.strip()}"}
    return {"ok": True}


_HANDLERS = {
    "sasl_set_user": _sasl_set_user,
    "sasl_delete_user": _sasl_delete_user,
    "apply_config": _apply_config,
    "status": _status,
    "version": _version,
    "tail_maillog": _tail_maillog,
    "queue_list": _queue_list,
    "queue_requeue": _queue_requeue,
    "queue_delete": _queue_delete,
}


def _handle_connection(conn: socket.socket) -> None:
    with conn:
        chunks = []
        while True:
            chunk = conn.recv(1_048_576)
            if not chunk:
                break
            chunks.append(chunk)
        try:
            request = json.loads(b"".join(chunks).decode("utf-8"))
            handler = _HANDLERS.get(request.get("op"))
            if handler is None:
                response = {"ok": False, "error": f"unknown op: {request.get('op')!r}"}
            else:
                response = handler(request)
        except Exception as exc:  # noqa: BLE001 - a survivable per-request failure, not a crash
            response = {"ok": False, "error": f"control surface error: {exc}"}
        conn.sendall((json.dumps(response) + "\n").encode("utf-8"))


def main() -> None:
    if os.path.exists(CONTROL_SOCKET_PATH):
        os.remove(CONTROL_SOCKET_PATH)
    os.makedirs(os.path.dirname(CONTROL_SOCKET_PATH), exist_ok=True)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(CONTROL_SOCKET_PATH)
    os.chmod(CONTROL_SOCKET_PATH, 0o660)
    server.listen(8)
    print(f"control surface listening on {CONTROL_SOCKET_PATH}", file=sys.stderr, flush=True)

    while True:
        conn, _ = server.accept()
        _handle_connection(conn)


if __name__ == "__main__":
    main()
