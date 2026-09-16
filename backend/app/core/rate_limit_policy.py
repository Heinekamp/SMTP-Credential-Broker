"""A Postfix policy-delegation service (SMTPD_POLICY_README) enforcing
`LocalSmtpUser.rate_limit_per_hour`, keyed on `sasl_username` — Postfix's
own anvil limiter only keys on client IP, which can't distinguish local
users that share one (the common case on a LAN). Wired into
`smtpd_end_of_data_restrictions` (main.cf.j2), so this runs once per
message, not per recipient.

`evaluate()` is the pure, synchronously-testable accept/defer decision;
`run_policy_service()` is the thin `asyncio.start_server` wrapper Postfix
actually connects to (`inet:app:{port}`), opening its own short-lived
`SessionLocal()` per request — the same "independent session per unit of
work" idiom as the background ticks (core/retention.py). Started in
main.py's lifespan, gated behind `scheduler_enabled` like every other
real-DB-engine startup touch, so tests never bind a real socket.

Over the limit, Postfix is told `action=DEFER` — a temporary (450) reject.
The message is never queued; the submitting client is responsible for
retrying, the same as any real-world submission-rate-limiter. A rejected
attempt does not itself count against the window (retrying a legitimate
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
from app.models.rate_limit import LocalUserRateLimitCounter

_logger = get_logger("rate_limit_policy")

_DUNNO = "action=DUNNO\n\n"


def _window_start(now: datetime.datetime) -> datetime.datetime:
    return now.replace(minute=0, second=0, microsecond=0)


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

    window_start = _window_start(utcnow())
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

    if counter.count >= user.rate_limit_per_hour:
        db.commit()
        return (
            f"action=DEFER rate limit exceeded ({user.rate_limit_per_hour}/hour) "
            "— try again after the current hour ends\n\n"
        )

    counter.count += 1
    db.commit()
    return _DUNNO


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


async def _handle_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Postfix keeps one policy connection open across many requests —
    loop until it closes rather than handling a single request per
    connection."""
    try:
        while True:
            lines: list[bytes] = []
            while True:
                line = await reader.readline()
                if not line:
                    return  # client closed the connection
                line = line.rstrip(b"\r\n")
                if not line:
                    break  # blank line: end of this request's attributes
                lines.append(line)

            attrs = _parse_attributes(lines)
            db = SessionLocal()
            try:
                response = evaluate(db, attrs)
            except Exception:
                # A bug here must never become a mail outage — fail open.
                _logger.exception("rate-limit policy evaluation failed — permitting the message")
                response = _DUNNO
            finally:
                db.close()

            writer.write(response.encode("utf-8"))
            await writer.drain()
    finally:
        writer.close()


async def run_policy_service(port: int) -> None:
    """Runs until cancelled — main.py registers this as a long-lived task
    alongside the periodic background ticks."""
    server = await asyncio.start_server(_handle_connection, host="0.0.0.0", port=port)
    async with server:
        await server.serve_forever()
