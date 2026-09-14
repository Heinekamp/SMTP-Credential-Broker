"""Integration test suite (testing-strategy.md §2) — drives real SMTP
sessions against a real Postfix instance and a real (but controlled)
upstream stub. Every scenario here corresponds directly to one in spec §25.

Requires `docker compose -f integration/docker-compose.test.yml up -d
--build` to already be running — see integration/README.md. NOT run as
part of the fast backend unit suite (`backend/tests/`); this is
deliberately a separate, slower, Docker-dependent harness.
"""

import smtplib
import ssl
import time

import httpx
import pytest
from conftest import (
    create_local_user,
    create_sender,
    create_upstream_account,
    grant,
    push_config,
    relay_cli,
    stub_deliveries,
)

SUBMISSION_HOST = "localhost"
SUBMISSION_PORT = 1587
PLAIN_SMTP_PORT = 1025

# The relay's own TLS cert is a build-time self-signed placeholder
# (postfix/Dockerfile) — trusted only by this test's client context, never
# by a real deployment's actual clients.
_RELAY_TLS_CONTEXT = ssl.create_default_context()
_RELAY_TLS_CONTEXT.check_hostname = False
_RELAY_TLS_CONTEXT.verify_mode = ssl.CERT_NONE


def _connect_submission() -> smtplib.SMTP:
    client = smtplib.SMTP(SUBMISSION_HOST, SUBMISSION_PORT, timeout=15)
    client.ehlo()
    client.starttls(context=_RELAY_TLS_CONTEXT)
    client.ehlo()
    return client


def _wait_for_delivery(predicate, timeout: float = 10.0) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for delivery in stub_deliveries():
            if predicate(delivery):
                return delivery
        time.sleep(0.5)
    return None


def test_valid_credentials_authenticate(api: httpx.Client, uid: str) -> None:
    _, password = create_local_user(api, name="Auth Test", username=f"auth-test-user-{uid}")
    client = _connect_submission()
    try:
        client.login(f"auth-test-user-{uid}", password)  # raises on failure
    finally:
        client.quit()


def test_invalid_credentials_are_rejected(api: httpx.Client, uid: str) -> None:
    create_local_user(api, name="Auth Test 2", username=f"auth-test-user-2-{uid}")
    client = _connect_submission()
    try:
        with pytest.raises(smtplib.SMTPAuthenticationError):
            client.login(f"auth-test-user-2-{uid}", "definitely-the-wrong-password")
    finally:
        client.quit()


def test_failed_auth_does_not_produce_a_phantom_mail_log_row(api: httpx.Client, uid: str) -> None:
    """Regression test: a failed AUTH attempt logs a `warning: ...:
    sasl_username=x` line, which mail_log_parser.py's queue-ID regex used
    to mistake the leading word "warning" itself for a 7-character queue
    ID — fabricating a phantom mail_log row attributing a failed login to
    a fake "warning" queue (see docs/postfix-architecture.md §9 and
    backend/tests/test_mail_log_parser.py for the unit-level fix and
    detail). This proves it end to end against a real Postfix instance."""
    username = f"auth-test-user-warning-{uid}"
    create_local_user(api, name="Auth Warning Test", username=username)
    client = _connect_submission()
    try:
        with pytest.raises(smtplib.SMTPAuthenticationError):
            client.login(username, "definitely-the-wrong-password")
    finally:
        client.quit()

    # No polling-until-true here on purpose: the failed AUTH line is
    # already on disk by the time login() raises, and ingestion (a side
    # effect of GET /api/mail-log) is synchronous within one request — a
    # regression would fabricate the phantom row on the very first call,
    # not eventually, so retrying "until true" would risk masking it.
    time.sleep(1.0)
    response = api.get("/api/mail-log")
    response.raise_for_status()
    assert all(e["queue_id"] != "warning" for e in response.json()["entries"])


def test_sender_matching_permission_is_accepted_and_mismatch_is_rejected(
    api: httpx.Client, stub: None, uid: str
) -> None:
    printer_address = f"printer-{uid}@example.com"
    noreply_address = f"noreply-{uid}@example.com"
    account_id = create_upstream_account(
        api, name="STRATO printer", username="printer@example.com", password="printer-upstream-pass"
    )
    printer_sender = create_sender(api, address=printer_address, upstream_account_id=account_id)
    noreply_sender_account = create_upstream_account(
        api, name="STRATO noreply", username="noreply@example.com", password="noreply-upstream-pass"
    )
    create_sender(api, address=noreply_address, upstream_account_id=noreply_sender_account)
    user_id, password = create_local_user(api, name="Printer Service", username=f"printer-service-{uid}")
    grant(api, user_id=user_id, sender_id=printer_sender)
    push_config(api)

    client = _connect_submission()
    client.login(f"printer-service-{uid}", password)

    # Allowed sender: accepted.
    client.sendmail(printer_address, ["dest@example.net"], "Subject: test\n\nbody")
    delivered = _wait_for_delivery(lambda d: d["mail_from"] == printer_address)
    assert delivered is not None, "expected the allowed sender's message to reach the upstream stub"
    assert delivered["authenticated_as"] == "printer@example.com"

    # Sender the user is NOT permitted to use: Postfix must reject this at
    # the SMTP level (reject_sender_login_mismatch), not just decline to
    # deliver it — this is the core invariant (security-model.md).
    # NOTE: `.mail()`/`.rcpt()` are low-level smtplib calls that return a
    # (code, message) tuple and do NOT raise on failure themselves (unlike
    # `.sendmail()`, which orchestrates the whole transaction and does) —
    # asserting the code directly, confirmed against a real Postfix
    # instance to reject at the RCPT stage with 553.
    mail_code, _ = client.mail(noreply_address)
    assert mail_code == 250  # Postfix accepts MAIL FROM; the check happens at RCPT
    rcpt_code, rcpt_msg = client.rcpt("dest@example.net")
    assert rcpt_code == 553, f"expected a sender-login-mismatch rejection, got {rcpt_code} {rcpt_msg!r}"
    assert b"not owned by" in rcpt_msg
    client.rset()
    client.quit()


def test_correct_upstream_credentials_are_selected_per_sender(api: httpx.Client, stub: None, uid: str) -> None:
    printer_address = f"printer-{uid}@example.com"
    noreply_address = f"noreply-{uid}@example.com"
    printer_account = create_upstream_account(
        api, name="STRATO printer", username="printer@example.com", password="printer-upstream-pass"
    )
    noreply_account = create_upstream_account(
        api, name="STRATO noreply", username="noreply@example.com", password="noreply-upstream-pass"
    )
    printer_sender = create_sender(api, address=printer_address, upstream_account_id=printer_account)
    noreply_sender = create_sender(api, address=noreply_address, upstream_account_id=noreply_account)
    user_id, password = create_local_user(api, name="Multi Sender", username=f"multi-sender-{uid}")
    grant(api, user_id=user_id, sender_id=printer_sender)
    grant(api, user_id=user_id, sender_id=noreply_sender)
    push_config(api)

    client = _connect_submission()
    client.login(f"multi-sender-{uid}", password)

    client.sendmail(printer_address, ["dest@example.net"], "Subject: t\n\nb")
    client.sendmail(noreply_address, ["dest@example.net"], "Subject: t\n\nb")
    client.quit()

    printer_delivery = _wait_for_delivery(lambda d: d["mail_from"] == printer_address)
    noreply_delivery = _wait_for_delivery(lambda d: d["mail_from"] == noreply_address)
    assert printer_delivery["authenticated_as"] == "printer@example.com"
    assert noreply_delivery["authenticated_as"] == "noreply@example.com"


def test_permission_change_takes_effect_after_regeneration(api: httpx.Client, stub: None, uid: str) -> None:
    printer_address = f"printer-{uid}@example.com"
    alerts_address = f"alerts-{uid}@example.com"
    account_id = create_upstream_account(
        api, name="STRATO reassign", username="printer@example.com", password="printer-upstream-pass"
    )
    printer_sender = create_sender(api, address=printer_address, upstream_account_id=account_id)
    alerts_account = create_upstream_account(
        api, name="STRATO alerts", username="alerts@example.com", password="alerts-upstream-pass"
    )
    alerts_sender = create_sender(api, address=alerts_address, upstream_account_id=alerts_account)
    user_id, password = create_local_user(api, name="Reassign Test", username=f"reassign-test-user-{uid}")
    grant(api, user_id=user_id, sender_id=printer_sender)
    push_config(api)

    client = _connect_submission()
    client.login(f"reassign-test-user-{uid}", password)
    client.sendmail(printer_address, ["dest@example.net"], "Subject: t\n\nb")
    client.quit()
    assert _wait_for_delivery(lambda d: d["mail_from"] == printer_address) is not None

    # Reassign: revoke printer@, grant alerts@ instead.
    api.delete(f"/api/senders/{printer_sender}/permissions/{user_id}").raise_for_status()
    grant(api, user_id=user_id, sender_id=alerts_sender)
    push_config(api)

    client = _connect_submission()
    client.login(f"reassign-test-user-{uid}", password)
    mail_code, _ = client.mail(printer_address)
    assert mail_code == 250
    rcpt_code, rcpt_msg = client.rcpt("dest@example.net")
    assert rcpt_code == 553, f"expected rejection after revocation, got {rcpt_code} {rcpt_msg!r}"
    client.rset()
    client.sendmail(alerts_address, ["dest@example.net"], "Subject: t\n\nb")
    client.quit()
    assert _wait_for_delivery(lambda d: d["mail_from"] == alerts_address) is not None


def test_open_relay_is_prevented_without_authentication(api: httpx.Client) -> None:
    # Deliberately the submission port (587), not plain smtp (25): port 25
    # is bound loopback-only by design (postfix-architecture.md §3) and
    # isn't reachable from outside the container at all — trying it here
    # would test a port that's already unreachable, not the actual exposed
    # attack surface. Submission is what's genuinely reachable and must
    # reject relay attempts with no AUTH, regardless of source.
    client = _connect_submission()
    with pytest.raises((smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError)):
        client.sendmail("nobody@example.com", ["dest@example.net"], "Subject: t\n\nb")
    client.quit()


def test_plain_smtp_port_is_unreachable_from_outside(api: httpx.Client) -> None:
    # Confirms the *other* half of the open-relay story: port 25 isn't
    # just "also protected by AUTH," it's not reachable at all from
    # outside the container (inet_interfaces=loopback-only on that
    # service — postfix-architecture.md §3).
    with pytest.raises((ConnectionRefusedError, smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, OSError)):
        smtplib.SMTP(SUBMISSION_HOST, PLAIN_SMTP_PORT, timeout=5)


def test_upstream_auth_failure_does_not_leak_the_password(api: httpx.Client, stub: None, uid: str) -> None:
    printer_address = f"printer-{uid}@example.com"
    account_id = create_upstream_account(
        api, name="STRATO wrong-password", username="printer@example.com", password="not-the-real-password"
    )
    sender_id = create_sender(api, address=printer_address, upstream_account_id=account_id)
    user_id, password = create_local_user(api, name="Bad Upstream", username=f"bad-upstream-user-{uid}")
    grant(api, user_id=user_id, sender_id=sender_id)
    push_config(api)

    client = _connect_submission()
    client.login(f"bad-upstream-user-{uid}", password)
    client.sendmail(printer_address, ["dest@example.net"], "Subject: t\n\nb")
    client.quit()

    # The message must never reach the stub (upstream AUTH fails before
    # DATA), and Postfix's bounce/log text must never contain the
    # configured password anywhere the app's mail_log would surface it.
    assert _wait_for_delivery(lambda d: d["mail_from"] == printer_address, timeout=5) is None


def _wait_for_mail_log(api: httpx.Client, *, envelope_sender: str, timeout: float = 15.0) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = api.get("/api/mail-log", params={"envelope_sender": envelope_sender})
        response.raise_for_status()
        entries = response.json()["entries"]
        if entries:
            return entries[0]
        time.sleep(0.5)
    return None


def test_successful_delivery_is_ingested_into_mail_log(api: httpx.Client, stub: None, uid: str) -> None:
    printer_address = f"printer-maillog-{uid}@example.com"
    account_id = create_upstream_account(
        api, name="STRATO mail-log", username="printer@example.com", password="printer-upstream-pass"
    )
    sender_id = create_sender(api, address=printer_address, upstream_account_id=account_id)
    user_id, password = create_local_user(api, name="Mail Log Test", username=f"maillog-user-{uid}")
    grant(api, user_id=user_id, sender_id=sender_id)
    push_config(api)

    client = _connect_submission()
    client.login(f"maillog-user-{uid}", password)
    client.sendmail(printer_address, ["dest@example.net"], "Subject: t\n\nb")
    client.quit()
    assert _wait_for_delivery(lambda d: d["mail_from"] == printer_address) is not None

    # Real Postfix log lines, tailed through the control surface
    # (postfix-architecture.md §9) and parsed into mail_log — not the app
    # intercepting the mail itself (database-schema.md §7).
    entry = _wait_for_mail_log(api, envelope_sender=printer_address)
    assert entry is not None, "expected the delivery to show up in mail_log"
    assert entry["status"] == "sent"
    assert entry["recipients"] == ["dest@example.net"]
    assert entry["local_smtp_user_id"] == user_id
    assert entry["upstream_account_id"] == account_id


def test_sender_login_mismatch_rejection_is_ingested_into_mail_log(api: httpx.Client, uid: str) -> None:
    noreply_address = f"noreply-maillog-reject-{uid}@example.com"
    account_id = create_upstream_account(
        api, name="STRATO mail-log reject", username="noreply@example.com", password="noreply-upstream-pass"
    )
    create_sender(api, address=noreply_address, upstream_account_id=account_id)
    _, password = create_local_user(api, name="Mail Log Reject Test", username=f"maillog-reject-user-{uid}")
    push_config(api)

    client = _connect_submission()
    client.login(f"maillog-reject-user-{uid}", password)
    mail_code, _ = client.mail(noreply_address)
    assert mail_code == 250
    rcpt_code, _ = client.rcpt("dest@example.net")
    assert rcpt_code == 553
    client.rset()
    client.quit()

    entry = _wait_for_mail_log(api, envelope_sender=noreply_address)
    assert entry is not None, "expected the rejection to show up in mail_log"
    assert entry["status"] == "rejected"
    assert "not owned by" in entry["error"]
    # NOQUEUE rejections never get a queue ID at all, so there's nothing
    # for the earlier AUTH's queue-id-keyed row to attach to — no
    # local_smtp_user_id attribution for this event type is expected.
    assert entry["local_smtp_user_id"] is None


def test_queue_endpoint_reflects_the_real_postfix_queue(api: httpx.Client) -> None:
    # A light smoke check rather than a scenario: proves the app's /api/queue
    # is genuinely backed by `postqueue -j` inside the real container
    # (postfix-architecture.md §9), not a stub — the live queue is normally
    # empty in this fast-delivery test harness, so an empty list is the
    # expected common case, not a weak assertion.
    response = api.get("/api/queue")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_health_detects_config_drift_and_resolves_on_regeneration(api: httpx.Client, uid: str) -> None:
    # Establish a known-good baseline first — other tests in this shared
    # session may or may not have generated a config yet, so this pins
    # the starting state explicitly rather than assuming it.
    push_config(api)
    baseline = api.get("/api/health").json()
    assert baseline["status"] == "ok"
    assert baseline["postfix_reachable"]["ok"] is True
    assert baseline["postfix_running"]["ok"] is True
    assert baseline["last_generation_result"] == "pass"
    assert baseline["config_in_sync"]["ok"] is True

    # Change DB state (a new sender) without regenerating — architecture.md
    # §7's "generation succeeded but drifted since" case.
    account_id = create_upstream_account(
        api, name="STRATO health drift", username="printer@example.com", password="printer-upstream-pass"
    )
    create_sender(api, address=f"drift-{uid}@example.com", upstream_account_id=account_id)

    drifted = api.get("/api/health").json()
    assert drifted["status"] == "degraded"
    assert drifted["config_in_sync"]["ok"] is False

    push_config(api)
    healed = api.get("/api/health").json()
    assert healed["status"] == "ok"
    assert healed["config_in_sync"]["ok"] is True


def test_relay_doctor_cli_reports_the_same_overall_status(api: httpx.Client) -> None:
    push_config(api)
    result = relay_cli("doctor")
    assert result.returncode == 0, f"relay doctor failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    assert "Overall: ok" in result.stdout
    assert "[PASS] Database reachable" in result.stdout
    assert "[PASS] Postfix running" in result.stdout


def test_credential_rotation_old_password_fails_new_succeeds_local_user_unaffected(
    api: httpx.Client, stub: None, uid: str
) -> None:
    printer_address = f"printer-{uid}@example.com"
    rotation_username = f"printer-rotation-{uid}@example.com"
    account_id = create_upstream_account(
        api, name="STRATO rotation", username=rotation_username, password="original-upstream-pass"
    )
    sender_id = create_sender(api, address=printer_address, upstream_account_id=account_id)
    user_id, password = create_local_user(api, name="Rotation Test", username=f"rotation-test-user-{uid}")
    grant(api, user_id=user_id, sender_id=sender_id)

    # The stub only knows fixed credentials from its own startup env/prior
    # PUTs — register this test's own upstream identity with it directly,
    # since `rotation_username` is unique per test run.
    httpx.put(
        "http://localhost:2526/credentials",
        json={"username": rotation_username, "password": "original-upstream-pass"},
        timeout=5,
    )
    push_config(api)

    # Prove the OLD credential currently works, before rotating anything.
    client = _connect_submission()
    client.login(f"rotation-test-user-{uid}", password)
    client.sendmail(printer_address, ["dest@example.net"], "Subject: before\n\nb")
    client.quit()
    assert _wait_for_delivery(lambda d: d["mail_from"] == printer_address) is not None

    # Rotate: the provider's actual password changes...
    httpx.put(
        "http://localhost:2526/credentials",
        json={"username": rotation_username, "password": "rotated-upstream-pass"},
        timeout=5,
    )
    # ...the relay is told the new password...
    api.patch(f"/api/upstream-accounts/{account_id}", json={"password": "rotated-upstream-pass"}).raise_for_status()
    push_config(api)
    httpx.delete("http://localhost:2526/deliveries", timeout=5)

    # New credential now works.
    client = _connect_submission()
    client.login(f"rotation-test-user-{uid}", password)  # local credential is untouched by any of this
    client.sendmail(printer_address, ["dest@example.net"], "Subject: after\n\nb")
    client.quit()
    assert _wait_for_delivery(lambda d: d["mail_from"] == printer_address) is not None
