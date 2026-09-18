"""acme_tls.issue_or_renew/sync_certificate_to_postfix exercised against
a fake AcmeIssuer (never a real ACME server) and a monkeypatched
postfix_control.install_tls_certificate (never a real Unix socket)."""

import datetime

import pytest
from sqlalchemy.orm import Session

from app.core import acme_tls
from app.core.cloudflare_dns import CloudflareDnsProvider
from app.core.encryption import EncryptionKeyNotConfigured, decrypt_secret, encrypt_secret
from app.core.postfix_control import InstallTlsCertificateResult, PostfixControlError
from app.core.settings_store import (
    get_background_job_state,
    get_relay_settings,
    get_tls_certificate_state,
    get_tls_pending_manual_challenge,
)


class _FakeIssuer:
    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.fail_with = fail_with
        self.calls: list[dict] = []

    def issue(self, *, domain, contact_email, account_key_pem, account_uri, dns_provider):
        self.calls.append(
            {
                "domain": domain,
                "contact_email": contact_email,
                "account_key_pem": account_key_pem,
                "account_uri": account_uri,
                "dns_provider": dns_provider,
            }
        )
        if self.fail_with is not None:
            raise self.fail_with
        issued = acme_tls.IssuedCertificate(
            cert_pem="CERT-PEM",
            key_pem="KEY-PEM",
            not_before=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            not_after=datetime.datetime(2026, 4, 1, tzinfo=datetime.UTC),
        )
        return issued, account_key_pem or "NEW-ACCOUNT-KEY-PEM", account_uri or "https://acme.example/acct/1"


class _FakePendingIssuer:
    """Fakes the begin_order/finalize_order split used by the manual
    DNS-01 flow — never touches the real `acme` package or network."""

    def __init__(
        self, *, fail_begin_with: Exception | None = None, fail_finalize_with: Exception | None = None
    ) -> None:
        self.fail_begin_with = fail_begin_with
        self.fail_finalize_with = fail_finalize_with
        self.begin_calls: list[dict] = []
        self.finalize_calls: list[acme_tls.PendingAcmeOrder] = []

    def issue(self, **kwargs):  # pragma: no cover - not exercised by the manual-flow tests
        raise NotImplementedError

    def begin_order(self, *, domain, contact_email, account_key_pem, account_uri) -> acme_tls.PendingAcmeOrder:
        self.begin_calls.append(
            {
                "domain": domain,
                "contact_email": contact_email,
                "account_key_pem": account_key_pem,
                "account_uri": account_uri,
            }
        )
        if self.fail_begin_with is not None:
            raise self.fail_begin_with
        return acme_tls.PendingAcmeOrder(
            domain=domain,
            record_name=f"_acme-challenge.{domain}",
            record_value="expected-validation-value",
            order_json='{"fake": "order"}',
            cert_key_pem="CERT-KEY-PEM",
            account_key_pem=account_key_pem or "NEW-ACCOUNT-KEY-PEM",
            account_uri=account_uri or "https://acme.example/acct/1",
            directory_url="https://acme.example/directory",
        )

    def finalize_order(self, *, pending: acme_tls.PendingAcmeOrder):
        self.finalize_calls.append(pending)
        if self.fail_finalize_with is not None:
            raise self.fail_finalize_with
        issued = acme_tls.IssuedCertificate(
            cert_pem="CERT-PEM",
            key_pem=pending.cert_key_pem,
            not_before=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            not_after=datetime.datetime(2026, 4, 1, tzinfo=datetime.UTC),
        )
        return issued, pending.account_key_pem, pending.account_uri


def _configure_manual(db: Session, *, enabled: bool = True, domain: str = "smtp-relay.example.com") -> None:
    settings_row = get_relay_settings(db)
    settings_row.tls_acme_enabled = enabled
    settings_row.tls_domain = domain
    settings_row.tls_dns_provider = "manual"
    db.commit()


def _stub_propagation(result: bool):
    return lambda self, name, value, timeout_seconds: result


def _configure(db: Session, *, enabled: bool = True, domain: str = "smtp-relay.example.com") -> None:
    settings_row = get_relay_settings(db)
    settings_row.tls_acme_enabled = enabled
    settings_row.tls_domain = domain
    settings_row.tls_cloudflare_api_token_encrypted = encrypt_secret("cf-token")
    settings_row.tls_cloudflare_zone_id = "Z123"
    db.commit()


def test_issue_or_renew_reports_when_disabled(db_session: Session) -> None:
    _configure(db_session, enabled=False)
    issuer = _FakeIssuer()

    result = acme_tls.issue_or_renew(db_session, issuer=issuer)

    assert result.success is False
    assert "not enabled" in result.detail
    assert issuer.calls == []


def test_issue_or_renew_reports_missing_domain(db_session: Session) -> None:
    _configure(db_session, domain="")
    get_relay_settings(db_session).tls_domain = None
    db_session.commit()
    issuer = _FakeIssuer()

    result = acme_tls.issue_or_renew(db_session, issuer=issuer)

    assert result.success is False
    assert "No domain" in result.detail
    assert issuer.calls == []


def test_issue_or_renew_reports_missing_token(db_session: Session) -> None:
    settings_row = get_relay_settings(db_session)
    settings_row.tls_acme_enabled = True
    settings_row.tls_domain = "smtp-relay.example.com"
    db_session.commit()
    issuer = _FakeIssuer()

    result = acme_tls.issue_or_renew(db_session, issuer=issuer)

    assert result.success is False
    assert "No Cloudflare API token" in result.detail
    assert issuer.calls == []


def test_issue_or_renew_success_persists_state(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> None:
    _configure(db_session)
    monkeypatch.setattr(
        acme_tls.postfix_control,
        "install_tls_certificate",
        lambda **kwargs: InstallTlsCertificateResult(success=True, detail="Installed.", restarted=True),
    )
    issuer = _FakeIssuer()

    result = acme_tls.issue_or_renew(db_session, issuer=issuer)

    assert result.success is True
    assert result.not_after == datetime.datetime(2026, 4, 1, tzinfo=datetime.UTC)

    state = get_tls_certificate_state(db_session)
    assert state.source == "lets_encrypt"
    assert state.domain == "smtp-relay.example.com"
    assert state.cert_pem == "CERT-PEM"
    assert decrypt_secret(state.encrypted_key_pem) == "KEY-PEM"
    assert decrypt_secret(state.acme_account_key_encrypted) == "NEW-ACCOUNT-KEY-PEM"
    assert state.acme_account_uri == "https://acme.example/acct/1"
    assert state.issued_at is not None

    # The DnsProvider passed through to the issuer was built from the
    # decrypted token/zone id, not the ciphertext.
    passed_provider = issuer.calls[0]["dns_provider"]
    assert isinstance(passed_provider, CloudflareDnsProvider)
    assert passed_provider.api_token == "cf-token"
    assert passed_provider.zone_id == "Z123"


def test_issue_or_renew_success_clears_a_previously_recorded_renewal_error(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    """Regression test: a manual "Issue/Renew Now" success must clear a
    stale error left over from an earlier failed attempt (e.g. the
    background tick's own last failure, before a bug fix landed) — a
    resolved problem must not keep showing as if it's still broken next
    to a freshly issued, working certificate."""
    _configure(db_session)
    get_background_job_state(db_session).cert_last_renewal_error = "stale error from before the fix"
    db_session.commit()
    monkeypatch.setattr(
        acme_tls.postfix_control,
        "install_tls_certificate",
        lambda **kwargs: InstallTlsCertificateResult(success=True, detail="Installed.", restarted=True),
    )

    result = acme_tls.issue_or_renew(db_session, issuer=_FakeIssuer())

    assert result.success is True
    assert get_background_job_state(db_session).cert_last_renewal_error is None


def test_issue_or_renew_reuses_the_existing_acme_account(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> None:
    _configure(db_session)
    state = get_tls_certificate_state(db_session)
    state.acme_account_key_encrypted = encrypt_secret("EXISTING-ACCOUNT-KEY-PEM")
    state.acme_account_uri = "https://acme.example/acct/existing"
    db_session.commit()
    monkeypatch.setattr(
        acme_tls.postfix_control,
        "install_tls_certificate",
        lambda **kwargs: InstallTlsCertificateResult(success=True, detail="Installed.", restarted=True),
    )
    issuer = _FakeIssuer()

    acme_tls.issue_or_renew(db_session, issuer=issuer)

    assert issuer.calls[0]["account_key_pem"] == "EXISTING-ACCOUNT-KEY-PEM"
    assert issuer.calls[0]["account_uri"] == "https://acme.example/acct/existing"


def test_issue_or_renew_leaves_state_untouched_on_acme_failure(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    _configure(db_session)
    before = get_tls_certificate_state(db_session).source
    issuer = _FakeIssuer(fail_with=RuntimeError("DNS-01 challenge failed"))

    result = acme_tls.issue_or_renew(db_session, issuer=issuer)

    assert result.success is False
    assert "DNS-01 challenge failed" in result.detail
    assert get_tls_certificate_state(db_session).source == before
    assert get_tls_certificate_state(db_session).cert_pem is None


def test_issue_or_renew_leaves_state_untouched_when_postfix_rejects_the_cert(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    _configure(db_session)
    monkeypatch.setattr(
        acme_tls.postfix_control,
        "install_tls_certificate",
        lambda **kwargs: InstallTlsCertificateResult(success=False, detail="Private key does not match certificate."),
    )
    issuer = _FakeIssuer()

    result = acme_tls.issue_or_renew(db_session, issuer=issuer)

    assert result.success is False
    assert "Issued but Postfix rejected it" in result.detail
    assert get_tls_certificate_state(db_session).cert_pem is None


def test_issue_or_renew_reports_a_broken_encryption_key_without_raising(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    _configure(db_session)
    monkeypatch.setattr(
        acme_tls,
        "decrypt_secret",
        lambda blob: (_ for _ in ()).throw(EncryptionKeyNotConfigured("no key configured")),
    )
    issuer = _FakeIssuer()

    result = acme_tls.issue_or_renew(db_session, issuer=issuer)

    assert result.success is False
    assert "no key configured" in result.detail
    assert issuer.calls == []


def test_sync_certificate_to_postfix_is_a_noop_when_nothing_issued(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    calls = []
    monkeypatch.setattr(acme_tls.postfix_control, "install_tls_certificate", lambda **kwargs: calls.append(kwargs))

    acme_tls.sync_certificate_to_postfix(db_session)

    assert calls == []


def test_sync_certificate_to_postfix_pushes_the_stored_certificate(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    state = get_tls_certificate_state(db_session)
    state.source = "lets_encrypt"
    state.cert_pem = "CERT-PEM"
    state.encrypted_key_pem = encrypt_secret("KEY-PEM")
    db_session.commit()
    calls = []
    monkeypatch.setattr(
        acme_tls.postfix_control,
        "install_tls_certificate",
        lambda **kwargs: (calls.append(kwargs), InstallTlsCertificateResult(success=True, detail="ok"))[1],
    )

    acme_tls.sync_certificate_to_postfix(db_session)

    assert calls == [{"cert_pem": "CERT-PEM", "key_pem": "KEY-PEM"}]


def test_sync_certificate_to_postfix_swallows_an_unreachable_control_surface(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    state = get_tls_certificate_state(db_session)
    state.cert_pem = "CERT-PEM"
    state.encrypted_key_pem = encrypt_secret("KEY-PEM")
    db_session.commit()

    def raise_unreachable(**kwargs):
        raise PostfixControlError("could not reach the control surface")

    monkeypatch.setattr(acme_tls.postfix_control, "install_tls_certificate", raise_unreachable)

    acme_tls.sync_certificate_to_postfix(db_session)  # must not raise


def test_issue_or_renew_reports_when_dns_provider_is_manual(db_session: Session) -> None:
    _configure_manual(db_session)
    issuer = _FakeIssuer()

    result = acme_tls.issue_or_renew(db_session, issuer=issuer)

    assert result.success is False
    assert "Start DNS-01 Challenge" in result.detail
    assert issuer.calls == []


def test_begin_manual_dns_challenge_reports_when_disabled(db_session: Session) -> None:
    _configure_manual(db_session, enabled=False)

    result = acme_tls.begin_manual_dns_challenge(db_session, issuer=_FakePendingIssuer())

    assert result.success is False
    assert "not enabled" in result.detail


def test_begin_manual_dns_challenge_reports_missing_domain(db_session: Session) -> None:
    _configure_manual(db_session)
    get_relay_settings(db_session).tls_domain = None
    db_session.commit()

    result = acme_tls.begin_manual_dns_challenge(db_session, issuer=_FakePendingIssuer())

    assert result.success is False
    assert "No domain" in result.detail


def test_begin_manual_dns_challenge_reports_when_provider_is_not_manual(db_session: Session) -> None:
    _configure(db_session)  # dns_provider defaults to "cloudflare"

    result = acme_tls.begin_manual_dns_challenge(db_session, issuer=_FakePendingIssuer())

    assert result.success is False
    assert "not set to Manual" in result.detail


def test_begin_manual_dns_challenge_persists_and_returns_the_record(db_session: Session) -> None:
    _configure_manual(db_session)
    issuer = _FakePendingIssuer()

    result = acme_tls.begin_manual_dns_challenge(db_session, issuer=issuer)

    assert result.success is True
    assert result.record_name == "_acme-challenge.smtp-relay.example.com"
    assert result.record_value == "expected-validation-value"
    assert result.expires_at is not None

    row = get_tls_pending_manual_challenge(db_session)
    assert row is not None
    assert row.domain == "smtp-relay.example.com"
    assert row.record_name == result.record_name
    assert decrypt_secret(row.encrypted_cert_key_pem) == "CERT-KEY-PEM"
    assert decrypt_secret(row.encrypted_account_key_pem) == "NEW-ACCOUNT-KEY-PEM"


def test_begin_manual_dns_challenge_reuses_a_non_expired_pending_challenge(db_session: Session) -> None:
    """Idempotent restart-safety: reloading the page or clicking Start
    twice must not burn a second ACME order and invalidate a TXT value
    the admin may have already added."""
    _configure_manual(db_session)
    issuer = _FakePendingIssuer()

    first = acme_tls.begin_manual_dns_challenge(db_session, issuer=issuer)
    second = acme_tls.begin_manual_dns_challenge(db_session, issuer=issuer)

    assert len(issuer.begin_calls) == 1
    assert second.record_name == first.record_name
    assert second.record_value == first.record_value


def test_finalize_manual_dns_challenge_reports_when_nothing_is_pending(db_session: Session) -> None:
    result = acme_tls.finalize_manual_dns_challenge(db_session, issuer=_FakePendingIssuer())

    assert result.success is False
    assert "No manual DNS-01 challenge" in result.detail


def test_finalize_manual_dns_challenge_clears_an_expired_challenge(db_session: Session) -> None:
    _configure_manual(db_session)
    acme_tls.begin_manual_dns_challenge(db_session, issuer=_FakePendingIssuer())
    row = get_tls_pending_manual_challenge(db_session)
    row.expires_at = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
    db_session.commit()

    result = acme_tls.finalize_manual_dns_challenge(db_session, issuer=_FakePendingIssuer())

    assert result.success is False
    assert "expired" in result.detail
    assert get_tls_pending_manual_challenge(db_session) is None


def test_finalize_manual_dns_challenge_keeps_the_pending_row_when_not_yet_propagated(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    _configure_manual(db_session)
    acme_tls.begin_manual_dns_challenge(db_session, issuer=_FakePendingIssuer())
    monkeypatch.setattr(acme_tls.ManualDnsProvider, "wait_for_propagation", _stub_propagation(False))

    result = acme_tls.finalize_manual_dns_challenge(db_session, issuer=_FakePendingIssuer())

    assert result.success is False
    assert "isn't visible yet" in result.detail
    assert get_tls_pending_manual_challenge(db_session) is not None


def test_finalize_manual_dns_challenge_success_persists_state_and_clears_the_pending_row(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    _configure_manual(db_session)
    get_background_job_state(db_session).cert_last_renewal_error = "stale error from before the fix"
    db_session.commit()
    acme_tls.begin_manual_dns_challenge(db_session, issuer=_FakePendingIssuer())
    monkeypatch.setattr(acme_tls.ManualDnsProvider, "wait_for_propagation", _stub_propagation(True))
    monkeypatch.setattr(
        acme_tls.postfix_control,
        "install_tls_certificate",
        lambda **kwargs: InstallTlsCertificateResult(success=True, detail="Installed.", restarted=True),
    )
    finalize_issuer = _FakePendingIssuer()

    result = acme_tls.finalize_manual_dns_challenge(db_session, issuer=finalize_issuer)

    assert result.success is True
    assert len(finalize_issuer.finalize_calls) == 1
    assert finalize_issuer.finalize_calls[0].cert_key_pem == "CERT-KEY-PEM"

    state = get_tls_certificate_state(db_session)
    assert state.source == "lets_encrypt"
    assert state.domain == "smtp-relay.example.com"
    assert state.cert_pem == "CERT-PEM"
    assert decrypt_secret(state.encrypted_key_pem) == "CERT-KEY-PEM"
    assert get_background_job_state(db_session).cert_last_renewal_error is None
    assert get_tls_pending_manual_challenge(db_session) is None


def test_finalize_manual_dns_challenge_clears_the_pending_row_on_an_acme_failure(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    """A failed/invalid ACME order can't be retried — the pending row
    must be cleared so the admin can start a fresh challenge instead of
    being stuck retrying something that can never succeed."""
    _configure_manual(db_session)
    acme_tls.begin_manual_dns_challenge(db_session, issuer=_FakePendingIssuer())
    monkeypatch.setattr(acme_tls.ManualDnsProvider, "wait_for_propagation", _stub_propagation(True))

    finalize_issuer = _FakePendingIssuer(fail_finalize_with=RuntimeError("order is invalid"))
    result = acme_tls.finalize_manual_dns_challenge(db_session, issuer=finalize_issuer)

    assert result.success is False
    assert "order is invalid" in result.detail
    assert get_tls_pending_manual_challenge(db_session) is None
