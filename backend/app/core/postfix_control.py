import dataclasses
import json
import socket

from app.config import get_settings


class PostfixControlError(RuntimeError):
    """The control surface (security-model.md §6) is unreachable, or
    reported a server-side failure (unknown op, crash) — distinct from an
    expected business-level failure like "the generated config didn't
    validate," which apply_config() reports in its return value instead of
    raising. Callers should surface this as a 503, not a generic 500: it
    means the Postfix side of the relay can't be reached, not that the
    application itself is broken."""


def _call(op: str, payload: dict) -> dict:
    if not hasattr(socket, "AF_UNIX"):
        # The documented deployment target (Linux, inside the postfix
        # container) always has this; surfacing it as PostfixControlError
        # rather than an unhandled AttributeError keeps the API's failure
        # mode consistent ("control surface unreachable") on any platform
        # that genuinely lacks Unix domain sockets.
        raise PostfixControlError("This platform does not support Unix domain sockets (AF_UNIX).")

    settings = get_settings()
    request = json.dumps({"op": op, **payload}) + "\n"

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(settings.postfix_control_timeout)
            sock.connect(settings.postfix_control_socket)
            sock.sendall(request.encode("utf-8"))
            sock.shutdown(socket.SHUT_WR)
            chunks: list[bytes] = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
    except OSError as exc:
        raise PostfixControlError(f"Could not reach the Postfix control surface: {exc}") from exc

    raw = b"".join(chunks).decode("utf-8", errors="replace").strip()
    if not raw:
        raise PostfixControlError("Postfix control surface closed the connection with no response")
    try:
        response = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PostfixControlError(f"Postfix control surface returned invalid JSON: {raw!r}") from exc

    if not response.get("ok", False):
        raise PostfixControlError(response.get("error", "unknown control-surface error"))
    return response


def sasl_set_user(username: str, password: str) -> None:
    """Creates or updates a local SMTP user's Cyrus SASL credential
    (postfix-architecture.md §5 — `saslpasswd2`, run inside the postfix
    container since that's where `/etc/sasldb2` lives)."""
    _call("sasl_set_user", {"username": username, "password": password})


def sasl_delete_user(username: str) -> None:
    _call("sasl_delete_user", {"username": username})


@dataclasses.dataclass
class ApplyConfigResult:
    success: bool
    validation_detail: str
    reloaded: bool


def apply_config(
    *,
    main_cf: str,
    master_cf: str,
    maps: dict[str, str],
    reload_if_main_changed: bool,
) -> ApplyConfigResult:
    """Runs architecture.md §5's full pipeline (write to temp -> validate
    -> atomic install -> reload-or-not) inside the postfix container, which
    is the only place `postconf`/`postmap`/the live config directory
    actually exist. `success: False` is an expected outcome (the generated
    config didn't validate) reported here, not raised as
    PostfixControlError — the RPC itself succeeded."""
    response = _call(
        "apply_config",
        {
            "main_cf": main_cf,
            "master_cf": master_cf,
            "maps": maps,
            "reload_if_main_changed": reload_if_main_changed,
        },
    )
    return ApplyConfigResult(
        success=response.get("success", False),
        validation_detail=response.get("validation_detail", ""),
        reloaded=response.get("reloaded", False),
    )


@dataclasses.dataclass
class PostfixStatus:
    running: bool
    detail: str


def status() -> PostfixStatus:
    """Is Postfix's master process actually running inside the postfix
    container (architecture.md §7's health check) — a successful RPC
    round-trip to this function already proves the control surface itself
    is reachable; `running=False` is the separate, and entirely expected
    on a never-yet-configured relay, question of whether `postfix start`
    has ever succeeded (see control_surface.py's `_apply_config`)."""
    response = _call("status", {})
    return PostfixStatus(running=response.get("running", False), detail=response.get("detail", ""))


@dataclasses.dataclass
class MaillogTail:
    lines: list[str]
    new_offset: int
    truncated: bool


def tail_maillog(since_offset: int) -> MaillogTail:
    """Pulls any Postfix maillog lines written since `since_offset` — the
    read side of Stage 5's mail_log ingestion (docs/postfix-architecture.md
    §9). The control surface, not this process, holds the actual file; this
    process is the one that persists the returned offset across calls
    (app/core/mail_log_ingest.py), since the postfix container's control
    surface is deliberately stateless about anything other app-side state
    already tracks (config_generations works the same way)."""
    response = _call("tail_maillog", {"since_offset": since_offset})
    return MaillogTail(
        lines=response.get("lines", []),
        new_offset=response.get("new_offset", 0),
        truncated=response.get("truncated", False),
    )


def version() -> str:
    """The installed Postfix version (`postconf -h mail_version`), shown in
    Settings alongside this app's own version — purely informational, no
    liveness implication (see `status()` for that)."""
    response = _call("version", {})
    return response.get("version", "")


def queue_list() -> list[dict]:
    """Wraps `postqueue -j` (postfix-architecture.md §9) — the live Postfix
    queue, independent of and complementary to mail_log's historical
    record: a message can be sitting in the deferred queue with no
    mail_log row yet reflecting its next retry outcome."""
    response = _call("queue_list", {})
    return response.get("entries", [])


def queue_requeue(queue_id: str) -> None:
    """Forces an immediate delivery attempt for one queued message
    (`postsuper -r`), rather than waiting for Postfix's own backoff
    schedule."""
    _call("queue_requeue", {"queue_id": queue_id})


def queue_delete(queue_id: str) -> None:
    """Permanently removes one queued message (`postsuper -d`) — e.g. a
    message stuck retrying against a since-fixed but originally
    misconfigured sender/upstream pairing that the admin has decided isn't
    worth redelivering."""
    _call("queue_delete", {"queue_id": queue_id})
