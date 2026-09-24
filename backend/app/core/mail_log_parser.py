"""Parses Postfix's own maillog lines into structured events, keyed by
queue ID, for ingestion into the `mail_log` table (database-schema.md §7 —
"populated by tailing/parsing Postfix's own logs ... not by the
application intercepting mail"). Pure, dependency-free string parsing so
it's unit-testable without a real Postfix instance; app/core/mail_log_ingest.py
does the DB-side correlation.

A single delivery attempt is scattered across several independent log
lines from different Postfix services, all sharing one queue ID:

    postfix/smtpd[1]: 4XYZ0001: client=..., sasl_username=printer-service
    postfix/cleanup[2]: 4XYZ0001: message-id=<...>
    postfix/qmgr[3]: 4XYZ0001: from=<printer@example.com>, size=123, nrcpt=1
    postfix/smtp[4]: 4XYZ0001: to=<dest@example.net>, relay=host[1.2.3.4]:587,
        delay=0.5, status=sent (250 2.0.0 Ok: queued as ABCDEF)
    postfix/qmgr[3]: 4XYZ0001: removed

A rejection that never gets a queue ID at all looks like:

    postfix/smtpd[1]: NOQUEUE: reject: RCPT from unknown[1.2.3.4]: 553 5.7.1
        <...>: Sender address rejected: not owned by user x; from=<a@b> to=<c@d>

A failed SMTP AUTH attempt (wrong password, unknown user, ...) never gets a
queue ID either — it's rejected before `MAIL FROM` is even reached — and
looks like:

    postfix/submission/smtpd[1]: warning: unknown[1.2.3.4]: SASL PLAIN
        authentication failed: authentication failure, sasl_username=someuser

A client that can't complete TLS negotiation, or that connects and drops
before finishing whatever it was doing, also never gets a queue ID:

    postfix/submission/smtpd[1]: warning: unknown[1.2.3.4]: SSL_accept
        error from unknown[1.2.3.4]: -1
    postfix/submission/smtpd[1]: lost connection after STARTTLS from
        unknown[1.2.3.4]
"""

import dataclasses
import datetime
import re

from app.models.enums import MailStatus

_LINE_RE = re.compile(
    # The process tag isn't always a single word — a master.cf service
    # whose name differs from its daemon (e.g. this project's "submission"
    # service running the "smtpd" daemon) logs as
    # "postfix/submission/smtpd[pid]", not "postfix/smtpd[pid]". Found by
    # running against a real Postfix instance: without the "/" in this
    # character class, every submission-service line (which is every AUTH
    # and every NOQUEUE reject this relay ever produces, since submission
    # is the only port real clients use) silently failed to match at all.
    r"^\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+\S+\s+postfix/(?P<service>[\w./-]+)\[(?P<pid>\d+)\]:\s*(?P<rest>.*)$"
)
# Modern Postfix ("long queue IDs") uses a wider alphanumeric alphabet
# than plain hex, not just 0-9A-F — but a bare alphanumeric-token-then-colon
# match at the start of the message also matches ordinary log-level prefixes
# like "warning:" or "fatal:", which are not queue IDs (found by running
# against a real Postfix instance: a failed AUTH attempt logs
# "warning: ...: SASL ... authentication failed: ..., sasl_username=x" and
# "warning" was being treated as a 7-character queue ID, fabricating a
# phantom mail_log row attributing a failed login to a fake queue). A real
# queue ID always contains at least one digit; no plain-English log-level
# word does — requiring one is a minimal, robust way to reject them without
# hardcoding to hex and risking a real long-queue-ID false negative.
_QUEUE_ID_RE = re.compile(r"^(?=[0-9A-Za-z]*\d)([0-9A-Za-z]{6,16}):\s*(.*)$")
_SASL_USERNAME_RE = re.compile(r"sasl_username=(?P<value>\S+)")
_FROM_RE = re.compile(r"from=<(?P<value>[^>]*)>")
_TO_RE = re.compile(r"\bto=<(?P<value>[^>]*)>")
_STATUS_RE = re.compile(r"status=(?P<status>\w+)(?:\s+\((?P<detail>.*)\))?\s*$")
_RELAY_RE = re.compile(r"relay=(?P<host>[^\[\s,]+)\[[^\]]*\]:(?P<port>\d+)")
_NOQUEUE_REJECT_RE = re.compile(r"^NOQUEUE: reject: .*?: (?P<code_and_text>\d{3}[^;]*);\s*(?P<rest>.*)$")
# A failed AUTH attempt never gets a queue ID (rejected before MAIL FROM),
# and — unlike a NOQUEUE reject — carries no "553 5.7.1 ..." style code,
# just this free-text shape. Matched explicitly rather than left to fall
# through to _QUEUE_ID_RE, whose digit requirement (see that regex's own
# comment) only stops "warning" being mistaken for a queue ID; it doesn't
# give this line anywhere to go, so before this branch existed the event
# was silently dropped and a rejected login left no mail_log trace at all.
_AUTH_FAILED_RE = re.compile(
    r"^warning: (?P<client>\S+): SASL (?P<mechanism>\S+) authentication failed: (?P<detail>.*)$"
)
# A client whose TLS stack can't negotiate with this relay's config (old
# embedded gear stuck on a retired protocol/cipher, or attempting implicit
# TLS on the STARTTLS-only submission port) never gets far enough to
# attempt AUTH at all — issue #108. The companion "warning: TLS library
# problem: ..." line Postfix usually logs alongside this carries no client
# identifier at all, so it's deliberately not matched here: a row with no
# attribution wouldn't be actionable, just noise.
_TLS_HANDSHAKE_FAILED_RE = re.compile(r"^warning: (?P<client>\S+): SSL_accept error from \S+: (?P<detail>.+)$")
# A client that connects and then drops mid-session — firewall/NAT
# weirdness, a device that can't complete STARTTLS, a health-check probe
# hitting the submission port — also never gets a queue ID. Unlike the
# other reject shapes above, Postfix logs this one *without* a leading
# "warning:" (issue #108).
_LOST_CONNECTION_RE = re.compile(r"^lost connection after (?P<phase>\S+) from (?P<client>\S+)$")

_POSTFIX_STATUS_TO_MAIL_STATUS = {
    "sent": MailStatus.sent,
    "deferred": MailStatus.deferred,
    "bounced": MailStatus.bounced,
    # Postfix's own terminal failure state after all retries are exhausted
    # — the closest equivalent this schema has is "bounced" (permanently
    # failed), not "deferred" (still retrying).
    "expired": MailStatus.bounced,
}


@dataclasses.dataclass
class LogEvent:
    kind: str  # "auth" | "enqueued" | "delivery" | "reject"
    timestamp: datetime.datetime
    queue_id: str | None = None
    sasl_username: str | None = None
    envelope_sender: str | None = None
    recipient: str | None = None
    status: MailStatus | None = None
    relay_host: str | None = None
    relay_port: int | None = None
    error: str | None = None


def _parse_timestamp(line: str) -> datetime.datetime:
    # Postfix's own log lines (whether via syslog or maillog_file) carry no
    # year — "Jun 10 12:34:56" — so one is assumed from the current date.
    # This means a line from Dec 31 parsed just after a new year rolls
    # over would be misdated by a year; an accepted, cosmetic limitation of
    # this timestamp format shared by every traditional syslog-line parser,
    # not something this project's data model depends on for correctness.
    now = datetime.datetime.now(tz=datetime.UTC)
    prefix = line[:15]
    try:
        parsed = datetime.datetime.strptime(prefix, "%b %d %H:%M:%S")
    except ValueError:
        return now
    return parsed.replace(year=now.year, tzinfo=datetime.UTC)


def parse_line(line: str) -> LogEvent | None:
    """Returns a structured event for one maillog line, or None if the line
    isn't one this project cares about (connect/disconnect/TLS-negotiation
    noise, warnings, etc.)."""
    match = _LINE_RE.match(line)
    if match is None:
        return None
    rest = match.group("rest")
    timestamp = _parse_timestamp(line)

    noqueue = _NOQUEUE_REJECT_RE.match(rest)
    if noqueue is not None:
        tail = noqueue.group("rest")
        from_match = _FROM_RE.search(tail)
        to_match = _TO_RE.search(tail)
        # Postfix appends sasl_method=/sasl_username= to a reject line
        # whenever the rejected session had already authenticated (e.g. a
        # rate-limit policy-service defer at end-of-data) — without
        # capturing it, a throttled local user's own rejections show up in
        # mail_log with no attribution at all.
        sasl_match = _SASL_USERNAME_RE.search(tail)
        return LogEvent(
            kind="reject",
            timestamp=timestamp,
            sasl_username=sasl_match.group("value") if sasl_match else None,
            envelope_sender=from_match.group("value") if from_match else None,
            recipient=to_match.group("value") if to_match else None,
            error=noqueue.group("code_and_text").strip(),
        )

    auth_failed = _AUTH_FAILED_RE.match(rest)
    if auth_failed is not None:
        detail = auth_failed.group("detail")
        sasl_match = _SASL_USERNAME_RE.search(detail)
        reason = _SASL_USERNAME_RE.sub("", detail).rstrip(", ").strip()
        return LogEvent(
            kind="reject",
            timestamp=timestamp,
            sasl_username=sasl_match.group("value") if sasl_match else None,
            error=f"SASL {auth_failed.group('mechanism')} authentication failed: {reason}",
        )

    tls_failed = _TLS_HANDSHAKE_FAILED_RE.match(rest)
    if tls_failed is not None:
        return LogEvent(
            kind="reject",
            timestamp=timestamp,
            error=f"TLS handshake failed ({tls_failed.group('client')}): {tls_failed.group('detail')}",
        )

    lost_connection = _LOST_CONNECTION_RE.match(rest)
    if lost_connection is not None:
        return LogEvent(
            kind="reject",
            timestamp=timestamp,
            error=f"Lost connection after {lost_connection.group('phase')} ({lost_connection.group('client')})",
        )

    queue_match = _QUEUE_ID_RE.match(rest)
    if queue_match is None:
        return None
    queue_id, body = queue_match.group(1), queue_match.group(2)

    sasl_match = _SASL_USERNAME_RE.search(body)
    if sasl_match is not None:
        return LogEvent(kind="auth", timestamp=timestamp, queue_id=queue_id, sasl_username=sasl_match.group("value"))

    if body.startswith("from="):
        from_match = _FROM_RE.search(body)
        return LogEvent(
            kind="enqueued",
            timestamp=timestamp,
            queue_id=queue_id,
            envelope_sender=from_match.group("value") if from_match else None,
        )

    if body.startswith("to="):
        to_match = _TO_RE.search(body)
        status_match = _STATUS_RE.search(body)
        relay_match = _RELAY_RE.search(body)
        status = _POSTFIX_STATUS_TO_MAIL_STATUS.get(status_match.group("status")) if status_match else None
        return LogEvent(
            kind="delivery",
            timestamp=timestamp,
            queue_id=queue_id,
            recipient=to_match.group("value") if to_match else None,
            status=status,
            relay_host=relay_match.group("host") if relay_match else None,
            relay_port=int(relay_match.group("port")) if relay_match else None,
            error=(status_match.group("detail") if status_match and status != MailStatus.sent else None),
        )

    return None
