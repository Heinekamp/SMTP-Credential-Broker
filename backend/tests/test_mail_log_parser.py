from app.core.mail_log_parser import parse_line
from app.models.enums import MailStatus

_AUTH_LINE = (
    "Sep 14 10:00:00 relay postfix/smtpd[123]: 4XYZ123456: client=unknown[172.20.0.1], "
    "sasl_method=PLAIN, sasl_username=printer-service"
)
_ENQUEUED_LINE = (
    "Sep 14 10:00:00 relay postfix/qmgr[125]: 4XYZ123456: from=<printer@example.com>, "
    "size=1234, nrcpt=1 (queue active)"
)
_SENT_LINE = (
    "Sep 14 10:00:01 relay postfix/smtp[126]: 4XYZ123456: to=<dest@example.net>, "
    "relay=upstream-stub[172.20.0.5]:2525, delay=0.5, delays=0.1/0/0.2/0.2, dsn=2.0.0, "
    "status=sent (250 2.0.0 Ok: queued as ABC123)"
)
_DEFERRED_LINE = (
    "Sep 14 10:00:01 relay postfix/smtp[126]: 4XYZ123456: to=<dest@example.net>, "
    "relay=upstream-stub[172.20.0.5]:2525, delay=1.2, delays=0.1/0/0.2/0.9, dsn=4.7.8, "
    "status=deferred (host upstream-stub[172.20.0.5] said: 454 4.7.8 Authentication failed)"
)
_BOUNCED_LINE = (
    "Sep 14 10:00:01 relay postfix/smtp[126]: 4XYZ123456: to=<dest@example.net>, "
    "relay=none, delay=0.1, dsn=5.1.1, status=bounced (host upstream-stub said: 550 5.1.1 unknown user)"
)
_REMOVED_LINE = "Sep 14 10:00:01 relay postfix/qmgr[125]: 4XYZ123456: removed"
_NOQUEUE_REJECT_LINE = (
    "Sep 14 10:00:00 relay postfix/smtpd[123]: NOQUEUE: reject: RCPT from unknown[172.20.0.1]: "
    "553 5.7.1 <noreply@example.com>: Sender address rejected: not owned by user diag-user; "
    "from=<noreply@example.com> to=<dest@example.net> proto=ESMTP helo=<client>"
)
_IGNORED_LINE = "Sep 14 10:00:00 relay postfix/smtpd[123]: connect from unknown[172.20.0.1]"
_NOQUEUE_REJECT_WITH_SASL_LINE = (
    "Sep 14 10:00:00 relay postfix/submission/smtpd[123]: NOQUEUE: reject: END-OF-MESSAGE from "
    "unknown[172.20.0.1]: 450 4.7.1 <printer-service>: rate limit exceeded, try again later; "
    "from=<printer@example.com> to=<dest@example.net> proto=ESMTP helo=<client> "
    "sasl_method=PLAIN sasl_username=printer-service"
)


def test_auth_line_is_parsed() -> None:
    event = parse_line(_AUTH_LINE)
    assert event is not None
    assert event.kind == "auth"
    assert event.queue_id == "4XYZ123456"
    assert event.sasl_username == "printer-service"


def test_enqueued_line_is_parsed() -> None:
    event = parse_line(_ENQUEUED_LINE)
    assert event is not None
    assert event.kind == "enqueued"
    assert event.queue_id == "4XYZ123456"
    assert event.envelope_sender == "printer@example.com"


def test_sent_delivery_line_is_parsed() -> None:
    event = parse_line(_SENT_LINE)
    assert event is not None
    assert event.kind == "delivery"
    assert event.queue_id == "4XYZ123456"
    assert event.recipient == "dest@example.net"
    assert event.status == MailStatus.sent
    assert event.relay_host == "upstream-stub"
    assert event.relay_port == 2525
    assert event.error is None


def test_deferred_delivery_line_captures_error_detail() -> None:
    event = parse_line(_DEFERRED_LINE)
    assert event is not None
    assert event.status == MailStatus.deferred
    assert "Authentication failed" in event.error
    # Never contains a password — security-model.md §8 (Postfix itself
    # never logs one, but this is what the ingester actually reads).
    assert "pass" not in event.error.lower() or "authentication failed" in event.error.lower()


def test_bounced_delivery_line_is_parsed() -> None:
    event = parse_line(_BOUNCED_LINE)
    assert event is not None
    assert event.status == MailStatus.bounced
    assert "unknown user" in event.error


def test_removed_line_is_not_a_recognized_event() -> None:
    assert parse_line(_REMOVED_LINE) is None


def test_noqueue_reject_is_parsed() -> None:
    event = parse_line(_NOQUEUE_REJECT_LINE)
    assert event is not None
    assert event.kind == "reject"
    assert event.queue_id is None
    assert event.envelope_sender == "noreply@example.com"
    assert event.recipient == "dest@example.net"
    assert "not owned by user diag-user" in event.error
    assert event.error.startswith("553")
    assert event.sasl_username is None


def test_noqueue_reject_captures_sasl_username_when_present() -> None:
    """A rate-limit policy-service defer (or any reject of an already-
    authenticated session) carries sasl_username= in the tail — without
    capturing it, a throttled local user's own rejections show up in
    mail_log with no attribution at all."""
    event = parse_line(_NOQUEUE_REJECT_WITH_SASL_LINE)
    assert event is not None
    assert event.kind == "reject"
    assert event.sasl_username == "printer-service"
    assert event.envelope_sender == "printer@example.com"
    assert event.recipient == "dest@example.net"


def test_irrelevant_lines_are_ignored() -> None:
    assert parse_line(_IGNORED_LINE) is None


def test_garbage_line_is_ignored() -> None:
    assert parse_line("this is not a postfix log line at all") is None


def test_failed_auth_warning_is_not_mistaken_for_a_queue_id() -> None:
    """A real bug, found by running against a real Postfix instance: a
    failed AUTH attempt logs a "warning: ...: sasl_username=x" line, and
    the queue-ID regex was matching the leading word "warning" itself as a
    7-character queue ID, fabricating a phantom mail_log row attributing a
    failed login to a fake "warning" queue. Fixed by requiring a digit in
    a queue ID (see _QUEUE_ID_RE) — confirmed here by checking this event
    never carries a queue_id at all, regardless of which kind it parses as."""
    line = (
        "Sep 14 09:31:03 relay-test postfix/submission/smtpd[134]: warning: "
        "unknown[172.18.0.1]: SASL CRAM-MD5 authentication failed: "
        "authentication failure, sasl_username=printer-service"
    )
    event = parse_line(line)
    assert event is not None
    assert event.queue_id is None


def test_failed_auth_warning_is_parsed_as_a_rejection() -> None:
    """Regression test for issue #105: the digit-requiring fix above used
    to stop this line matching _QUEUE_ID_RE at all, but nothing else
    picked it up either — the event fell through every branch and
    parse_line returned None, so a rejected login left no mail_log trace
    whatsoever. It must now surface as a "reject" event, attributed by
    sasl_username exactly like a NOQUEUE reject."""
    line = (
        "Sep 14 09:31:03 relay-test postfix/submission/smtpd[134]: warning: "
        "unknown[172.18.0.1]: SASL CRAM-MD5 authentication failed: "
        "authentication failure, sasl_username=printer-service"
    )
    event = parse_line(line)
    assert event is not None
    assert event.kind == "reject"
    assert event.queue_id is None
    assert event.sasl_username == "printer-service"
    assert event.envelope_sender is None
    assert "CRAM-MD5" in event.error
    assert "authentication failure" in event.error


def test_failed_auth_warning_without_sasl_username_is_still_captured() -> None:
    """Some failure modes (e.g. a mechanism that never reveals a
    username) don't append sasl_username= at all — the event must still
    be captured, just without that attribution."""
    line = (
        "Sep 14 09:31:03 relay-test postfix/submission/smtpd[134]: warning: "
        "unknown[172.18.0.1]: SASL LOGIN authentication failed: no secret in database"
    )
    event = parse_line(line)
    assert event is not None
    assert event.kind == "reject"
    assert event.sasl_username is None
    assert "no secret in database" in event.error


def test_other_plain_log_level_words_are_not_mistaken_for_queue_ids() -> None:
    for word in ("warning", "fatal", "starting", "stopping", "connect", "disconnect"):
        line = f"Sep 14 09:31:03 relay-test postfix/smtpd[1]: {word}: something sasl_username=x"
        assert parse_line(line) is None, f"{word!r} was mistaken for a queue ID"
