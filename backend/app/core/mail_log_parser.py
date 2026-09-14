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
# than plain hex, not just 0-9A-F.
_QUEUE_ID_RE = re.compile(r"^([0-9A-Za-z]{6,16}):\s*(.*)$")
_SASL_USERNAME_RE = re.compile(r"sasl_username=(?P<value>\S+)")
_FROM_RE = re.compile(r"from=<(?P<value>[^>]*)>")
_TO_RE = re.compile(r"\bto=<(?P<value>[^>]*)>")
_STATUS_RE = re.compile(r"status=(?P<status>\w+)(?:\s+\((?P<detail>.*)\))?\s*$")
_RELAY_RE = re.compile(r"relay=(?P<host>[^\[\s,]+)\[[^\]]*\]:(?P<port>\d+)")
_NOQUEUE_REJECT_RE = re.compile(r"^NOQUEUE: reject: .*?: (?P<code_and_text>\d{3}[^;]*);\s*(?P<rest>.*)$")

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
        return LogEvent(
            kind="reject",
            timestamp=timestamp,
            envelope_sender=from_match.group("value") if from_match else None,
            recipient=to_match.group("value") if to_match else None,
            error=noqueue.group("code_and_text").strip(),
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
