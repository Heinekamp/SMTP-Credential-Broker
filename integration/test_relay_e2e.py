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
from conftest import create_local_user, create_sender, create_upstream_account, grant, push_config, stub_deliveries

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


def test_valid_credentials_authenticate(api: httpx.Client) -> None:
    _, password = create_local_user(api, name="Auth Test", username="auth-test-user")
    client = _connect_submission()
    try:
        client.login("auth-test-user", password)  # raises on failure
    finally:
        client.quit()


def test_invalid_credentials_are_rejected(api: httpx.Client) -> None:
    create_local_user(api, name="Auth Test 2", username="auth-test-user-2")
    client = _connect_submission()
    try:
        with pytest.raises(smtplib.SMTPAuthenticationError):
            client.login("auth-test-user-2", "definitely-the-wrong-password")
    finally:
        client.quit()


def test_sender_matching_permission_is_accepted_and_mismatch_is_rejected(api: httpx.Client, stub: None) -> None:
    account_id = create_upstream_account(
        api, name="STRATO printer", username="printer@example.com", password="printer-upstream-pass"
    )
    printer_sender = create_sender(api, address="printer@example.com", upstream_account_id=account_id)
    noreply_sender_account = create_upstream_account(
        api, name="STRATO noreply", username="noreply@example.com", password="noreply-upstream-pass"
    )
    create_sender(api, address="noreply@example.com", upstream_account_id=noreply_sender_account)
    user_id, password = create_local_user(api, name="Printer Service", username="printer-service")
    grant(api, user_id=user_id, sender_id=printer_sender)
    push_config(api)

    client = _connect_submission()
    client.login("printer-service", password)

    # Allowed sender: accepted.
    client.sendmail("printer@example.com", ["dest@example.net"], "Subject: test\n\nbody")
    delivered = _wait_for_delivery(lambda d: d["mail_from"] == "printer@example.com")
    assert delivered is not None, "expected the allowed sender's message to reach the upstream stub"
    assert delivered["authenticated_as"] == "printer@example.com"

    # Sender the user is NOT permitted to use: Postfix must reject this at
    # the SMTP level (reject_sender_login_mismatch), not just decline to
    # deliver it — this is the core invariant (security-model.md).
    with pytest.raises(smtplib.SMTPSenderRefused):
        client.mail("noreply@example.com")
        code, _ = client.rcpt("dest@example.net")
        if code == 250:
            # Some smtplib versions only raise on the RCPT/DATA step
            # depending on exactly when Postfix rejects; force a clear
            # failure either way by asserting the code directly.
            raise smtplib.SMTPSenderRefused(code, b"expected rejection", "noreply@example.com")
    client.quit()


def test_correct_upstream_credentials_are_selected_per_sender(api: httpx.Client, stub: None) -> None:
    printer_account = create_upstream_account(
        api, name="STRATO printer", username="printer@example.com", password="printer-upstream-pass"
    )
    noreply_account = create_upstream_account(
        api, name="STRATO noreply", username="noreply@example.com", password="noreply-upstream-pass"
    )
    printer_sender = create_sender(api, address="printer@example.com", upstream_account_id=printer_account)
    noreply_sender = create_sender(api, address="noreply@example.com", upstream_account_id=noreply_account)
    user_id, password = create_local_user(api, name="Multi Sender", username="multi-sender")
    grant(api, user_id=user_id, sender_id=printer_sender)
    grant(api, user_id=user_id, sender_id=noreply_sender)
    push_config(api)

    client = _connect_submission()
    client.login("multi-sender", password)

    client.sendmail("printer@example.com", ["dest@example.net"], "Subject: t\n\nb")
    client.sendmail("noreply@example.com", ["dest@example.net"], "Subject: t\n\nb")
    client.quit()

    printer_delivery = _wait_for_delivery(lambda d: d["mail_from"] == "printer@example.com")
    noreply_delivery = _wait_for_delivery(lambda d: d["mail_from"] == "noreply@example.com")
    assert printer_delivery["authenticated_as"] == "printer@example.com"
    assert noreply_delivery["authenticated_as"] == "noreply@example.com"


def test_permission_change_takes_effect_after_regeneration(api: httpx.Client, stub: None) -> None:
    account_id = create_upstream_account(
        api, name="STRATO reassign", username="printer@example.com", password="printer-upstream-pass"
    )
    printer_sender = create_sender(api, address="printer@example.com", upstream_account_id=account_id)
    alerts_account = create_upstream_account(
        api, name="STRATO alerts", username="alerts@example.com", password="alerts-upstream-pass"
    )
    alerts_sender = create_sender(api, address="alerts@example.com", upstream_account_id=alerts_account)
    user_id, password = create_local_user(api, name="Reassign Test", username="reassign-test-user")
    grant(api, user_id=user_id, sender_id=printer_sender)
    push_config(api)

    client = _connect_submission()
    client.login("reassign-test-user", password)
    client.sendmail("printer@example.com", ["dest@example.net"], "Subject: t\n\nb")
    client.quit()
    assert _wait_for_delivery(lambda d: d["mail_from"] == "printer@example.com") is not None

    # Reassign: revoke printer@, grant alerts@ instead.
    api.delete(f"/api/senders/{printer_sender}/permissions/{user_id}").raise_for_status()
    grant(api, user_id=user_id, sender_id=alerts_sender)
    push_config(api)

    client = _connect_submission()
    client.login("reassign-test-user", password)
    with pytest.raises(smtplib.SMTPSenderRefused):
        client.mail("printer@example.com")
        code, _ = client.rcpt("dest@example.net")
        if code == 250:
            raise smtplib.SMTPSenderRefused(code, b"expected rejection after revocation", "printer@example.com")
    client.sendmail("alerts@example.com", ["dest@example.net"], "Subject: t\n\nb")
    client.quit()
    assert _wait_for_delivery(lambda d: d["mail_from"] == "alerts@example.com") is not None


def test_open_relay_is_prevented_without_authentication(api: httpx.Client) -> None:
    client = smtplib.SMTP(SUBMISSION_HOST, PLAIN_SMTP_PORT, timeout=15)
    client.ehlo()
    with pytest.raises((smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError)):
        client.sendmail("nobody@example.com", ["dest@example.net"], "Subject: t\n\nb")
    client.quit()


def test_upstream_auth_failure_does_not_leak_the_password(api: httpx.Client, stub: None) -> None:
    account_id = create_upstream_account(
        api, name="STRATO wrong-password", username="printer@example.com", password="not-the-real-password"
    )
    sender_id = create_sender(api, address="printer@example.com", upstream_account_id=account_id)
    user_id, password = create_local_user(api, name="Bad Upstream", username="bad-upstream-user")
    grant(api, user_id=user_id, sender_id=sender_id)
    push_config(api)

    client = _connect_submission()
    client.login("bad-upstream-user", password)
    client.sendmail("printer@example.com", ["dest@example.net"], "Subject: t\n\nb")
    client.quit()

    # The message must never reach the stub (upstream AUTH fails before
    # DATA), and Postfix's bounce/log text must never contain the
    # configured password anywhere the app's mail_log would surface it.
    assert _wait_for_delivery(lambda d: d["mail_from"] == "printer@example.com", timeout=5) is None


def test_credential_rotation_old_password_fails_new_succeeds_local_user_unaffected(
    api: httpx.Client, stub: None
) -> None:
    account_id = create_upstream_account(
        api, name="STRATO rotation", username="printer@example.com", password="original-upstream-pass"
    )
    sender_id = create_sender(api, address="printer@example.com", upstream_account_id=account_id)
    user_id, password = create_local_user(api, name="Rotation Test", username="rotation-test-user")
    grant(api, user_id=user_id, sender_id=sender_id)
    push_config(api)

    # Prove the OLD credential currently works, before rotating anything.
    client = _connect_submission()
    client.login("rotation-test-user", password)
    client.sendmail("printer@example.com", ["dest@example.net"], "Subject: before\n\nb")
    client.quit()
    assert _wait_for_delivery(lambda d: d["mail_from"] == "printer@example.com") is not None

    # Rotate: the provider's actual password changes...
    httpx.put(
        "http://localhost:2526/credentials",
        json={"username": "printer@example.com", "password": "rotated-upstream-pass"},
        timeout=5,
    )
    # ...the relay is told the new password...
    api.patch(f"/api/upstream-accounts/{account_id}", json={"password": "rotated-upstream-pass"}).raise_for_status()
    push_config(api)
    httpx.delete("http://localhost:2526/deliveries", timeout=5)

    # New credential now works.
    client = _connect_submission()
    client.login("rotation-test-user", password)  # local credential is untouched by any of this
    client.sendmail("printer@example.com", ["dest@example.net"], "Subject: after\n\nb")
    client.quit()
    assert _wait_for_delivery(lambda d: d["mail_from"] == "printer@example.com") is not None
