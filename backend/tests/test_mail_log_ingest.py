import datetime
import threading
import time

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.core.mail_log_ingest import ingest_new_log_lines
from app.core.postfix_control import MaillogTail
from app.models.enums import MailStatus, TlsMode
from app.models.local_user import LocalSmtpUser
from app.models.mail_log import MailLog, MailLogIngestState
from app.models.upstream import UpstreamAccount

_LINES = [
    (
        "Sep 14 10:00:00 relay postfix/smtpd[1]: 4XYZ000001: client=unknown[172.20.0.1], "
        "sasl_method=PLAIN, sasl_username=printer-service"
    ),
    (
        "Sep 14 10:00:00 relay postfix/qmgr[2]: 4XYZ000001: from=<printer@example.com>, "
        "size=1234, nrcpt=1 (queue active)"
    ),
    (
        "Sep 14 10:00:01 relay postfix/smtp[3]: 4XYZ000001: to=<dest@example.net>, "
        "relay=upstream-stub[172.20.0.5]:2525, delay=0.5, dsn=2.0.0, status=sent (250 2.0.0 Ok: queued as ABC)"
    ),
    "Sep 14 10:00:01 relay postfix/qmgr[2]: 4XYZ000001: removed",
    (
        "Sep 14 10:00:02 relay postfix/smtpd[1]: NOQUEUE: reject: RCPT from unknown[172.20.0.1]: "
        "553 5.7.1 <noreply@example.com>: Sender address rejected: not owned by user diag-user; "
        "from=<noreply@example.com> to=<dest@example.net> proto=ESMTP helo=<client>"
    ),
]


@pytest.fixture()
def _seed(db_session: Session) -> None:
    db_session.add(
        LocalSmtpUser(name="Printer Service", username="printer-service", password_hash="x", enabled=True)
    )
    db_session.add(
        UpstreamAccount(
            name="STRATO printer",
            host="upstream-stub",
            port=2525,
            tls_mode=TlsMode.starttls,
            username="printer@example.com",
            encrypted_password=b"ciphertext",
            enabled=True,
        )
    )
    db_session.commit()


def _patch_tail(monkeypatch: pytest.MonkeyPatch, lines: list[str], truncated: bool = False) -> None:
    def _fake_tail(since_offset: int) -> MaillogTail:
        consumed = sum(len(line) + 1 for line in lines)
        return MaillogTail(lines=lines, new_offset=since_offset + consumed, truncated=truncated)

    monkeypatch.setattr("app.core.mail_log_ingest.tail_maillog", _fake_tail)


def test_ingest_correlates_a_full_delivery_by_queue_id(
    db_session: Session, _seed: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_tail(monkeypatch, _LINES)

    processed = ingest_new_log_lines(db_session)
    assert processed == len(_LINES)

    row = db_session.query(MailLog).filter(MailLog.queue_id == "4XYZ000001").one()
    assert row.envelope_sender == "printer@example.com"
    assert row.recipients == ["dest@example.net"]
    assert row.status == MailStatus.sent
    local_user = db_session.query(LocalSmtpUser).filter(LocalSmtpUser.username == "printer-service").one()
    assert row.local_smtp_user_id == local_user.id
    upstream = db_session.query(UpstreamAccount).filter(UpstreamAccount.host == "upstream-stub").one()
    assert row.upstream_account_id == upstream.id


def test_ingest_records_a_noqueue_rejection(db_session: Session, _seed: None, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_tail(monkeypatch, _LINES)
    ingest_new_log_lines(db_session)

    rejected = db_session.query(MailLog).filter(MailLog.status == MailStatus.rejected).one()
    assert rejected.envelope_sender == "noreply@example.com"
    assert rejected.recipients == ["dest@example.net"]
    assert "not owned by user diag-user" in rejected.error
    assert rejected.queue_id.startswith("REJECT-")


def test_ingest_persists_offset_and_is_idempotent(
    db_session: Session, _seed: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_tail(monkeypatch, _LINES)
    ingest_new_log_lines(db_session)
    state = db_session.get(MailLogIngestState, 1)
    assert state.byte_offset > 0

    # A second call with no new lines (the real tail_maillog would return
    # an empty list once its offset catches up) must not duplicate rows.
    _patch_tail(monkeypatch, [])
    ingest_new_log_lines(db_session)
    assert db_session.query(MailLog).count() == 2  # one delivery + one rejection


def test_ingest_handles_maillog_truncation(db_session: Session, _seed: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """A rotated/recreated maillog file (control_surface.py's `truncated`
    flag) must not crash ingestion — it just re-reads from the start."""
    _patch_tail(monkeypatch, _LINES, truncated=True)
    processed = ingest_new_log_lines(db_session)
    assert processed == len(_LINES)


def test_ingest_with_unknown_sasl_user_and_upstream_leaves_fields_null(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No local user or upstream account exists yet — attribution should
    come back None rather than raising (database-schema.md §7: mail_log
    rows must remain storable even without a resolvable reference)."""
    _patch_tail(monkeypatch, _LINES)
    ingest_new_log_lines(db_session)
    row = db_session.query(MailLog).filter(MailLog.queue_id == "4XYZ000001").one()
    assert row.local_smtp_user_id is None
    assert row.upstream_account_id is None


def test_concurrent_ingestion_runs_are_serialized(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression test for issue #14: ingest_new_log_lines runs on every
    GET /api/mail-log request with no coordination between calls (sync
    FastAPI routes run in a thread pool, so this is real thread
    concurrency even with a single uvicorn worker). Two overlapping calls
    used to both read the same stale byte_offset and both process the
    same new maillog bytes — creating two rows for one logical event, or
    (now that queue_id has a unique index) crashing outright on the
    second commit. The module-level lock must fully serialize them:
    however the two threads get scheduled, their time inside
    tail_maillog must never overlap."""
    engine = db_session.get_bind()
    session_factory = sessionmaker(bind=engine)

    intervals: list[tuple[float, float]] = []
    intervals_lock = threading.Lock()

    def fake_tail(since_offset: int) -> MaillogTail:
        start = time.monotonic()
        time.sleep(0.05)
        end = time.monotonic()
        with intervals_lock:
            intervals.append((start, end))
        return MaillogTail(lines=[], new_offset=since_offset, truncated=False)

    monkeypatch.setattr("app.core.mail_log_ingest.tail_maillog", fake_tail)

    errors: list[BaseException] = []

    def worker() -> None:
        session = session_factory()
        try:
            ingest_new_log_lines(session)
        except BaseException as exc:  # noqa: BLE001 - captured for the assertion below
            errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert not any(t.is_alive() for t in threads), "a worker thread hung — the lock deadlocked"
    assert errors == []
    assert len(intervals) == 2
    (a_start, a_end), (b_start, b_end) = intervals
    assert a_end <= b_start or b_end <= a_start, f"overlapping ingestion runs: {intervals}"


def test_parsed_timestamp_is_used(db_session: Session, _seed: None, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_tail(monkeypatch, _LINES)
    ingest_new_log_lines(db_session)
    row = db_session.query(MailLog).filter(MailLog.queue_id == "4XYZ000001").one()
    assert row.timestamp.month == 9
    assert row.timestamp.day == 14
    assert row.timestamp.hour == 10
    assert isinstance(row.timestamp, datetime.datetime)
