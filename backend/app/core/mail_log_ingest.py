"""Turns raw maillog lines (app/core/mail_log_parser.py) into `mail_log`
rows (database-schema.md §7). Runs lazily whenever the mail log is viewed
(api/routes/mail_log.py) rather than as a standing background worker — see
that route module's comment for why.

Correlation strategy: every event that carries a queue ID is applied to
one `mail_log` row addressed *by that queue ID*, created on first sight
and updated in place by every later event for the same ID. This makes
correlation robust across ingestion-poll boundaries and app restarts
without needing any separate in-memory or on-disk staging area — the
`mail_log` table itself is the staging area, which is also exactly the
table an admin wants to see update live as a message moves through the
queue (queued -> sent/deferred/bounced).
"""

import threading
import uuid

from sqlalchemy.orm import Session

from app.core import mail_log_parser as parser
from app.core.logging_config import get_logger
from app.core.postfix_control import tail_maillog
from app.models.enums import MailStatus
from app.models.local_user import LocalSmtpUser
from app.models.mail_log import MailLog, MailLogIngestState
from app.models.upstream import UpstreamAccount

_logger = get_logger("mail_log_ingest")

# ingest_new_log_lines runs on every GET /api/mail-log request (this
# module's own docstring), with no coordination between them — two
# concurrent requests (two admin tabs, or a poll overlapping a manual
# refresh; sync FastAPI `def` routes run in a thread pool, so this is real
# thread concurrency even with a single uvicorn worker, which is this
# app's deployment model) could both read the same stale byte_offset, both
# tail the same maillog bytes, and both independently create a row for the
# same queue_id or reject event — MailLog.queue_id's unique index turns
# that into a crash instead of a silent duplicate, but the actual fix is
# making sure it can't happen: only one ingestion run executes at a time.
_ingest_lock = threading.Lock()


def _get_state(db: Session) -> MailLogIngestState:
    state = db.get(MailLogIngestState, 1)
    if state is None:
        state = MailLogIngestState(id=1, byte_offset=0)
        db.add(state)
        db.flush()
    return state


def _get_or_create(db: Session, queue_id: str, event: parser.LogEvent) -> MailLog:
    row = db.query(MailLog).filter(MailLog.queue_id == queue_id).one_or_none()
    if row is None:
        row = MailLog(
            queue_id=queue_id,
            timestamp=event.timestamp,
            # Not yet known if this event turns out to be the "auth" event,
            # which arrives first but carries no sender — filled in by the
            # "enqueued" event moments later in the overwhelmingly common
            # case; left as "" only in the unlikely event the ingestion
            # poll lands in the tiny window between the two.
            envelope_sender=event.envelope_sender or "",
            recipients=[],
            status=MailStatus.queued,
        )
        db.add(row)
        # Autoflush is off in this project's session setup (tests rely on
        # it); without an explicit flush, a later event for the same
        # queue ID within this same ingestion batch wouldn't see this row
        # via the query above and would create a duplicate.
        db.flush()
    return row


def ingest_new_log_lines(db: Session) -> int:
    """Pulls and applies any maillog lines written since the last call.
    Idempotent and safe to call as often as wanted. Serialized by
    _ingest_lock (see its comment) so two overlapping calls can't both
    process the same maillog bytes."""
    with _ingest_lock:
        return _ingest_new_log_lines_locked(db)


def _ingest_new_log_lines_locked(db: Session) -> int:
    """Returns the number of raw lines processed (not all of which
    necessarily produced an event)."""
    state = _get_state(db)
    tail = tail_maillog(state.byte_offset, state.maillog_inode)
    if tail.truncated:
        # Operator-visible signal for a log rotation/truncation — there
        # used to be none at all, so this event (and any gap it might
        # cause if the rotated-out bytes genuinely aren't recoverable)
        # was invisible short of noticing missing mail_log rows.
        _logger.warning(
            "maillog rotated or truncated — resuming from the start of the current file "
            "(previous offset %d, previous inode %s, new inode %s)",
            state.byte_offset,
            state.maillog_inode,
            tail.inode,
        )

    local_user_by_username: dict[str, int] = dict(db.query(LocalSmtpUser.username, LocalSmtpUser.id).all())
    upstream_by_host_port: dict[tuple[str, int], int] = {}
    upstream_by_host: dict[str, int] = {}
    for host, port, account_id in db.query(UpstreamAccount.host, UpstreamAccount.port, UpstreamAccount.id).all():
        upstream_by_host_port[(host, port)] = account_id
        upstream_by_host.setdefault(host, account_id)

    for line in tail.lines:
        event = parser.parse_line(line)
        if event is None:
            continue

        if event.kind == "reject":
            local_smtp_user_id = (
                local_user_by_username.get(event.sasl_username) if event.sasl_username else None
            )
            db.add(
                MailLog(
                    # NOQUEUE rejections never get a real Postfix queue ID
                    # (the message was refused before being queued at
                    # all) — synthesize one so the column's not-null,
                    # unique contract still holds.
                    queue_id=f"REJECT-{uuid.uuid4().hex[:12]}",
                    timestamp=event.timestamp,
                    local_smtp_user_id=local_smtp_user_id,
                    envelope_sender=event.envelope_sender or "",
                    recipients=[event.recipient] if event.recipient else [],
                    status=MailStatus.rejected,
                    error=event.error,
                )
            )
            continue

        if event.queue_id is None:
            continue
        row = _get_or_create(db, event.queue_id, event)

        if event.kind == "auth" and event.sasl_username:
            row.local_smtp_user_id = local_user_by_username.get(event.sasl_username)
        elif event.kind == "enqueued":
            if event.envelope_sender is not None:
                row.envelope_sender = event.envelope_sender
        elif event.kind == "delivery":
            if event.recipient and event.recipient not in row.recipients:
                row.recipients = [*row.recipients, event.recipient]  # reassign: JSON column change tracking
            if event.status is not None:
                row.status = event.status
            if event.error is not None:
                row.error = event.error
            if event.relay_host is not None:
                account_id = upstream_by_host_port.get((event.relay_host, event.relay_port))
                if account_id is None:
                    account_id = upstream_by_host.get(event.relay_host)
                if account_id is not None:
                    row.upstream_account_id = account_id

    state.byte_offset = tail.new_offset
    state.maillog_inode = tail.inode
    db.commit()
    return len(tail.lines)
