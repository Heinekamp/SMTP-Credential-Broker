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


def _sasl_delete_user(payload: dict) -> dict:
    username = payload["username"]
    result = _run(["saslpasswd2", "-d", "-u", SASL_REALM, username])
    # Exit code 1 with "no user" style stderr means it was already absent —
    # deleting an absent user is not a failure (idempotent, matches the
    # app-side revoke/disable semantics).
    if result.returncode != 0 and "no such" not in result.stderr.lower() and "not found" not in result.stderr.lower():
        return {"ok": False, "error": f"saslpasswd2 -d failed: {result.stderr.strip()}"}
    return {"ok": True}


def _validate_staged_config(main_cf: str, master_cf: str) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as staging_dir:
        with open(os.path.join(staging_dir, "main.cf"), "w", encoding="utf-8") as f:
            f.write(main_cf)
        with open(os.path.join(staging_dir, "master.cf"), "w", encoding="utf-8") as f:
            f.write(master_cf)
        result = _run(["postconf", "-c", staging_dir, "-n"])
        detail = (result.stdout + result.stderr).strip()
        # postconf exits non-zero on a hard parse error; "warning:" lines
        # about unknown parameters are noise we still want to see but not
        # treat as fatal, so the check is on returncode, not stderr content.
        return result.returncode == 0, detail or "postconf: OK"


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


def _install_config(main_cf: str, master_cf: str) -> None:
    for filename, content in (("main.cf", main_cf), ("master.cf", master_cf)):
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
        _install_maps(maps)
        _install_config(main_cf, master_cf)
    except (OSError, RuntimeError) as exc:
        return {"ok": True, "success": False, "validation_detail": f"install failed: {exc}", "reloaded": False}

    reloaded = False
    if reload_if_main_changed:
        result = _run(["postfix", "reload"])
        if result.returncode != 0:
            return {
                "ok": True,
                "success": False,
                "validation_detail": f"{detail}\npostfix reload failed: {result.stderr.strip()}",
                "reloaded": False,
            }
        reloaded = True

    return {"ok": True, "success": True, "validation_detail": detail, "reloaded": reloaded}


_HANDLERS = {
    "sasl_set_user": _sasl_set_user,
    "sasl_delete_user": _sasl_delete_user,
    "apply_config": _apply_config,
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
