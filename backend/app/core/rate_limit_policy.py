"""A Postfix policy-delegation service (SMTPD_POLICY_README) enforcing
`LocalSmtpUser.rate_limit_per_hour`/`rate_limit_burst`, keyed on
`sasl_username` — Postfix's own anvil limiter only keys on client IP,
which can't distinguish local users that share one (the common case on a
LAN). Wired into `smtpd_end_of_data_restrictions` (main.cf.j2), so this
runs once per message, not per recipient.

`evaluate()` is the pure, synchronously-testable accept/defer decision;
`run_policy_service()` is the thin `asyncio.start_server` wrapper Postfix
actually connects to (`inet:app:{port}`), opening its own short-lived
`SessionLocal()` per request — the same "independent session per unit of
work" idiom as the background ticks (core/retention.py). Started in
main.py's lifespan, gated behind `scheduler_enabled` like every other
real-DB-engine startup touch, so tests never bind a real socket.

Two independent checks, both of which must pass to permit a message:

- **Hourly ceiling** (`LocalUserRateLimitCounter`): a fixed clock-hour
  window — simple, and a coarse period total is exactly what an admin
  configuring "N per hour" expects.
- **Burst protection** (`LocalUserBurstBucket`, optional): a token bucket
  whose capacity is `rate_limit_burst` and whose refill rate is always
  derived from `rate_limit_per_hour` (never a second independent rate to
  configure). A fixed *second* window ("N per minute") was considered and
  rejected: two fixed windows that don't know about each other let a
  burst at the end of one plus a burst at the start of the next add up to
  ~2x the per-window limit in a couple of seconds. A token bucket has no
  such boundary — it smooths bursts by construction, which is the actual
  goal ("don't let it blast out the whole hourly budget in 10 seconds"),
  whereas the hourly counter alone only bites once the budget is already
  gone.

Over either limit, Postfix is told `action=DEFER` — a temporary (450)
reject. The message is never queued; the submitting client is responsible
for retrying, the same as any real-world submission-rate-limiter. A
rejected attempt consumes from **neither** budget (retrying a legitimate
send must not make things worse), and Postfix's own `NOQUEUE: reject:`
line for it already carries `sasl_username=`, so mail_log_ingest.py
attributes it to the right local user.
"""

import asyncio
import datetime

from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.logging_config import get_logger
from app.db.session import SessionLocal
from app.models.local_user import LocalSmtpUser
from app.models.rate_limit import LocalUserBurstBucket, LocalUserRateLimitCounter

_logger = get_logger("rate_limit_policy")

# A defer streak only continues while deferred messages keep arriving at
# most this far apart; a longer gap starts a new streak (#183). Ten minutes
# outlasts a sending MTA's first retry backoff, so a client genuinely
# hammering through its queue stays in one streak.
DEFER_STREAK_GAP = datetime.timedelta(minutes=10)

_DUNNO = "action=DUNNO\n\n"
_HOURLY_DEFER = "action=DEFER rate limit exceeded ({limit}/hour) — try again after the current hour ends\n\n"
_BURST_DEFER = "action=DEFER sending too fast — try again in a moment\n\n"


def _window_start(now: datetime.datetime) -> datetime.datetime:
    return now.replace(minute=0, second=0, microsecond=0)


def _refill_burst_tokens(
    bucket: LocalUserBurstBucket, capacity: int, rate_limit_per_hour: int, now: datetime.datetime
) -> float:
    """Pure refill computation, shared by evaluate() and the read-only
    current_burst_tokens() below — never mutates `bucket` itself."""
    refill_rate_per_second = rate_limit_per_hour / 3600.0
    elapsed_seconds = (now - bucket.last_refill_at).total_seconds()
    return min(float(capacity), bucket.tokens + elapsed_seconds * refill_rate_per_second)


def evaluate(db: Session, attrs: dict[str, str]) -> str:
    """Returns one full Postfix policy response (including the trailing
    blank line) for one end-of-data check. Only `sasl_username` is
    consulted — every other attribute Postfix sends is irrelevant to this
    decision."""
    username = attrs.get("sasl_username")
    if not username:
        return _DUNNO  # not an authenticated session — nothing to key on

    user = db.query(LocalSmtpUser).filter(LocalSmtpUser.username == username).one_or_none()
    if user is None or user.rate_limit_per_hour is None:
        return _DUNNO

    now = utcnow()

    window_start = _window_start(now)
    counter = (
        db.query(LocalUserRateLimitCounter)
        .filter(
            LocalUserRateLimitCounter.local_smtp_user_id == user.id,
            LocalUserRateLimitCounter.window_start == window_start,
        )
        .one_or_none()
    )
    if counter is None:
        # A window rolling over is simply a fresh row starting at
        # count=0 — no explicit reset job needed for correctness (only
        # for tidiness, handled separately by rate_limit_cleanup.py).
        counter = LocalUserRateLimitCounter(local_smtp_user_id=user.id, window_start=window_start, count=0)
        db.add(counter)
    hourly_ok = counter.count < user.rate_limit_per_hour

    bucket: LocalUserBurstBucket | None = None
    tokens_after: float | None = None
    burst_ok = True
    if user.rate_limit_burst is not None:
        bucket = db.get(LocalUserBurstBucket, user.id)
        if bucket is None:
            # Starts full — a fresh/idle user isn't throttled on their
            # first messages, only once they've actually burned capacity.
            bucket = LocalUserBurstBucket(
                local_smtp_user_id=user.id, tokens=float(user.rate_limit_burst), last_refill_at=now
            )
            db.add(bucket)
        tokens_after = _refill_burst_tokens(bucket, user.rate_limit_burst, user.rate_limit_per_hour, now)
        burst_ok = tokens_after >= 1.0

    if not hourly_ok or not burst_ok:
        # Refill progress (and its clock reference) is persisted even on
        # defer — a rejected message must not lose the bucket's progress
        # any more than it should get to spend a token it never used.
        if bucket is not None:
            bucket.tokens = tokens_after
            bucket.last_refill_at = now
        # Marks the start of an unbroken streak of rejections — only set
        # once, left alone by every later defer in the same streak.
        # core/alerts.py surfaces a streak past
        # rate_limit_abuse_threshold_minutes on the notification bell
        # unconditionally, and core/rate_limit_abuse.py's opt-in tick can
        # act on it — this module only ever records the fact, never
        # alerts or disables anything itself.
        last_defer = user.rate_limit_defer_streak_last_at
        if user.rate_limit_defer_streak_started_at is None or last_defer is None or now - last_defer > DEFER_STREAK_GAP:
            user.rate_limit_defer_streak_started_at = now
        user.rate_limit_defer_streak_last_at = now
        db.commit()
        if not hourly_ok:
            return _HOURLY_DEFER.format(limit=user.rate_limit_per_hour)
        return _BURST_DEFER

    counter.count += 1
    if bucket is not None:
        bucket.tokens = tokens_after - 1.0
        bucket.last_refill_at = now
    user.rate_limit_defer_streak_started_at = None
    user.rate_limit_defer_streak_last_at = None
    db.commit()
    return _DUNNO


def current_usage(db: Session, local_smtp_user_id: int) -> int:
    """How many messages this local user has sent in the current hourly
    window — the exact bucket evaluate() itself checks against. Read-only,
    for the API/UI usage readout; never itself part of the accept/defer
    decision path."""
    window_start = _window_start(utcnow())
    counter = (
        db.query(LocalUserRateLimitCounter)
        .filter(
            LocalUserRateLimitCounter.local_smtp_user_id == local_smtp_user_id,
            LocalUserRateLimitCounter.window_start == window_start,
        )
        .one_or_none()
    )
    return counter.count if counter is not None else 0


def current_burst_tokens(
    db: Session, local_smtp_user_id: int, rate_limit_burst: int, rate_limit_per_hour: int
) -> float:
    """How many burst tokens are available right now, computed the same
    way evaluate() itself would refill them. Read-only, for the API/UI
    usage readout; never itself part of the accept/defer decision path."""
    bucket = db.get(LocalUserBurstBucket, local_smtp_user_id)
    if bucket is None:
        return float(rate_limit_burst)
    return _refill_burst_tokens(bucket, rate_limit_burst, rate_limit_per_hour, utcnow())


def _parse_attributes(lines: list[bytes]) -> dict[str, str]:
    """One policy request's attribute lines (already split, blank line
    excluded) into a name->value dict, per SMTPD_POLICY_README's
    `name=value` wire format."""
    attrs: dict[str, str] = {}
    for line in lines:
        if b"=" not in line:
            continue
        key, _, value = line.partition(b"=")
        attrs[key.decode("utf-8", "replace")] = value.decode("utf-8", "replace")
    return attrs


# A real smtpd policy request is a couple of dozen short attribute lines
# (SMTPD_POLICY_README); anything far beyond that isn't Postfix (#167).
_MAX_ATTRIBUTE_LINES = 100
_MAX_LINE_BYTES = 2048

# evaluate() reads and writes counters with no locking of its own; running
# it in a worker thread (so a SQLite lock can't stall the event loop) must
# not let two evaluations interleave.
_evaluate_lock = asyncio.Lock()


def _evaluate_in_new_session(attrs: dict[str, str]) -> str:
    db = SessionLocal()
    try:
        return evaluate(db, attrs)
    finally:
        db.close()


async def _peer_is_allowed(peer_host: str, allowed_host: str | None) -> bool:
    """Only Postfix itself may ask (#167): this listener believes whatever
    sasl_username it's told, so any other client on a shared network could
    otherwise burn through a user's budget and get them auto-disabled. The
    allowed name is resolved per connection (Postfix keeps its connection
    open, so this is rare) — container IPs change on recreation. A failed
    lookup refuses the connection; Postfix then falls back to
    smtpd_policy_service_default_action (DUNNO), so mail keeps flowing."""
    if peer_host in ("127.0.0.1", "::1"):
        return True
    if allowed_host is None:
        return True
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(allowed_host, None)
    except OSError:
        return False
    return peer_host in {info[4][0] for info in infos}


async def _read_request(reader: asyncio.StreamReader) -> list[bytes] | None:
    """One request's attribute lines, or None if the client closed the
    connection or sent something no Postfix request looks like."""
    lines: list[bytes] = []
    while True:
        try:
            line = await reader.readuntil(b"\n")
        except asyncio.IncompleteReadError:
            return None  # client closed the connection
        except asyncio.LimitOverrunError:
            return None  # one line longer than the stream limit
        line = line.rstrip(b"\r\n")
        if not line:
            return lines  # blank line: end of this request's attributes
        if len(line) > _MAX_LINE_BYTES or len(lines) >= _MAX_ATTRIBUTE_LINES:
            return None
        lines.append(line)


async def _handle_connection(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, *, allowed_host: str | None
) -> None:
    """Postfix keeps one policy connection open across many requests —
    loop until it closes rather than handling a single request per
    connection."""
    try:
        peer = writer.get_extra_info("peername")
        peer_host = peer[0] if peer else ""
        if not await _peer_is_allowed(peer_host, allowed_host):
            _logger.warning("refused rate-limit policy connection from %s — not the postfix service", peer_host)
            return
        while True:
            lines = await _read_request(reader)
            if lines is None:
                return

            attrs = _parse_attributes(lines)
            try:
                async with _evaluate_lock:
                    response = await asyncio.to_thread(_evaluate_in_new_session, attrs)
            except Exception:
                # A bug here must never become a mail outage — fail open.
                _logger.exception("rate-limit policy evaluation failed — permitting the message")
                response = _DUNNO

            writer.write(response.encode("utf-8"))
            await writer.drain()
    finally:
        writer.close()


async def run_policy_service(port: int, *, allowed_host: str | None = "postfix", host: str = "0.0.0.0") -> None:
    """Runs until cancelled — main.py registers this as a long-lived task
    alongside the periodic background ticks. Still binds every interface
    (Postfix reaches it across the Compose network as inet:app:{port}),
    but only answers the `allowed_host` service; see _peer_is_allowed."""

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await _handle_connection(reader, writer, allowed_host=allowed_host)

    server = await asyncio.start_server(handler, host=host, port=port, limit=_MAX_LINE_BYTES * 2)
    async with server:
        await server.serve_forever()
