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
from app.core.settings_store import get_background_job_state, get_relay_settings, get_tls_certificate_state


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
