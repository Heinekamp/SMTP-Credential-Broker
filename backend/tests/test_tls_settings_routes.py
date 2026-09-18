import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.encryption import decrypt_secret, encrypt_secret
from app.core.settings_store import get_tls_certificate_state
from app.models.audit import AuditLog
from tests.conftest import csrf_headers


def test_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/tls-settings").status_code == 401


def test_get_returns_defaults_on_a_fresh_install(admin_client: TestClient) -> None:
    response = admin_client.get("/api/tls-settings")
    assert response.status_code == 200
    body = response.json()
    assert body["acme_enabled"] is False
    assert body["domain"] is None
    assert body["dns_provider"] == "cloudflare"
    assert body["cloudflare_api_token_configured"] is False
    assert body["cert_source"] == "self_signed"
    assert body["cert_not_after"] is None
    assert body["last_renewal_error"] is None


def test_patch_updates_domain_and_provider_fields(admin_client: TestClient) -> None:
    response = admin_client.patch(
        "/api/tls-settings",
        json={"acme_enabled": True, "domain": "smtp-relay.example.com", "contact_email": "ops@example.com"},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["acme_enabled"] is True
    assert body["domain"] == "smtp-relay.example.com"
    assert body["contact_email"] == "ops@example.com"
    assert body["cloudflare_api_token_configured"] is False  # not sent this call


def test_patch_only_changes_supplied_fields(admin_client: TestClient) -> None:
    admin_client.patch(
        "/api/tls-settings", json={"domain": "smtp-relay.example.com"}, headers=csrf_headers(admin_client)
    )
    response = admin_client.patch(
        "/api/tls-settings", json={"acme_enabled": True}, headers=csrf_headers(admin_client)
    )
    body = response.json()
    assert body["acme_enabled"] is True
    assert body["domain"] == "smtp-relay.example.com"  # untouched by the second PATCH


def test_patch_can_clear_the_domain(admin_client: TestClient) -> None:
    admin_client.patch(
        "/api/tls-settings", json={"domain": "smtp-relay.example.com"}, headers=csrf_headers(admin_client)
    )
    response = admin_client.patch("/api/tls-settings", json={"domain": None}, headers=csrf_headers(admin_client))
    assert response.json()["domain"] is None


def test_patch_stores_the_cloudflare_token_encrypted(admin_client: TestClient, db_session: Session) -> None:
    response = admin_client.patch(
        "/api/tls-settings", json={"cloudflare_api_token": "cf-secret-token"}, headers=csrf_headers(admin_client)
    )
    assert response.json()["cloudflare_api_token_configured"] is True

    from app.core.settings_store import get_relay_settings

    settings_row = get_relay_settings(db_session)
    assert settings_row.tls_cloudflare_api_token_encrypted != b"cf-secret-token"
    assert decrypt_secret(settings_row.tls_cloudflare_api_token_encrypted) == "cf-secret-token"


def test_patch_blank_token_keeps_the_current_one(admin_client: TestClient, db_session: Session) -> None:
    admin_client.patch(
        "/api/tls-settings", json={"cloudflare_api_token": "cf-secret-token"}, headers=csrf_headers(admin_client)
    )
    response = admin_client.patch(
        "/api/tls-settings", json={"domain": "smtp-relay.example.com"}, headers=csrf_headers(admin_client)
    )
    assert response.json()["cloudflare_api_token_configured"] is True

    from app.core.settings_store import get_relay_settings

    assert decrypt_secret(get_relay_settings(db_session).tls_cloudflare_api_token_encrypted) == "cf-secret-token"


def test_patch_is_audited(admin_client: TestClient, db_session: Session) -> None:
    admin_client.patch(
        "/api/tls-settings",
        json={"acme_enabled": True, "cloudflare_api_token": "cf-secret-token"},
        headers=csrf_headers(admin_client),
    )
    entry = db_session.query(AuditLog).filter(AuditLog.action == "tls_settings.update").one()
    assert entry.detail == {"fields": ["acme_enabled", "cloudflare_api_token"]}


def test_patch_requires_csrf(admin_client: TestClient) -> None:
    response = admin_client.patch("/api/tls-settings", json={"acme_enabled": True})
    assert response.status_code == 403


def test_verify_dns_access_requires_domain_and_token(admin_client: TestClient) -> None:
    response = admin_client.post("/api/tls-settings/verify-dns-access", headers=csrf_headers(admin_client))
    assert response.status_code == 400


def test_verify_dns_access_success(
    admin_client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin_client.patch(
        "/api/tls-settings",
        json={"domain": "smtp-relay.example.com", "cloudflare_api_token": "cf-secret-token"},
        headers=csrf_headers(admin_client),
    )
    monkeypatch.setattr(
        "app.core.cloudflare_dns.CloudflareDnsProvider.verify_access", lambda self, domain: (True, "Access confirmed.")
    )

    response = admin_client.post("/api/tls-settings/verify-dns-access", headers=csrf_headers(admin_client))
    assert response.status_code == 200
    assert response.json() == {"success": True, "detail": "Access confirmed."}


def test_verify_dns_access_reports_failure_without_raising(
    admin_client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin_client.patch(
        "/api/tls-settings",
        json={"domain": "smtp-relay.example.com", "cloudflare_api_token": "bad-token"},
        headers=csrf_headers(admin_client),
    )
    monkeypatch.setattr(
        "app.core.cloudflare_dns.CloudflareDnsProvider.verify_access",
        lambda self, domain: (False, "Cloudflare rejected this token."),
    )

    response = admin_client.post("/api/tls-settings/verify-dns-access", headers=csrf_headers(admin_client))
    assert response.status_code == 200
    assert response.json() == {"success": False, "detail": "Cloudflare rejected this token."}


def test_verify_dns_access_is_audited(
    admin_client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin_client.patch(
        "/api/tls-settings",
        json={"domain": "smtp-relay.example.com", "cloudflare_api_token": "cf-secret-token"},
        headers=csrf_headers(admin_client),
    )
    monkeypatch.setattr(
        "app.core.cloudflare_dns.CloudflareDnsProvider.verify_access", lambda self, domain: (True, "ok")
    )
    admin_client.post("/api/tls-settings/verify-dns-access", headers=csrf_headers(admin_client))

    entry = db_session.query(AuditLog).filter(AuditLog.action == "tls_settings.verify_dns_access").one()
    assert entry.detail == {"success": True}


def test_issue_now_requires_enabled_domain_and_token(admin_client: TestClient) -> None:
    response = admin_client.post("/api/tls-settings/issue", headers=csrf_headers(admin_client))
    assert response.status_code == 400


def test_issue_now_success(admin_client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    admin_client.patch(
        "/api/tls-settings",
        json={"acme_enabled": True, "domain": "smtp-relay.example.com", "cloudflare_api_token": "cf-secret-token"},
        headers=csrf_headers(admin_client),
    )

    class _Result:
        success = True
        detail = "Issued."

    monkeypatch.setattr("app.api.routes.tls_settings.issue_or_renew", lambda db: _Result())

    response = admin_client.post("/api/tls-settings/issue", headers=csrf_headers(admin_client))
    assert response.status_code == 200
    assert response.json() == {"success": True, "detail": "Issued."}


def test_issue_now_reports_a_real_failure_without_raising(
    admin_client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin_client.patch(
        "/api/tls-settings",
        json={"acme_enabled": True, "domain": "smtp-relay.example.com", "cloudflare_api_token": "cf-secret-token"},
        headers=csrf_headers(admin_client),
    )

    class _Result:
        success = False
        detail = "DNS-01 challenge failed."

    monkeypatch.setattr("app.api.routes.tls_settings.issue_or_renew", lambda db: _Result())

    response = admin_client.post("/api/tls-settings/issue", headers=csrf_headers(admin_client))
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert "DNS-01 challenge failed" in body["detail"]


def test_issue_now_is_audited(admin_client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    admin_client.patch(
        "/api/tls-settings",
        json={"acme_enabled": True, "domain": "smtp-relay.example.com", "cloudflare_api_token": "cf-secret-token"},
        headers=csrf_headers(admin_client),
    )

    class _Result:
        success = True
        detail = "Issued."

    monkeypatch.setattr("app.api.routes.tls_settings.issue_or_renew", lambda db: _Result())
    admin_client.post("/api/tls-settings/issue", headers=csrf_headers(admin_client))

    entry = db_session.query(AuditLog).filter(AuditLog.action == "tls_certificate.manual_issue").one()
    assert entry.detail == {"success": True, "domain": "smtp-relay.example.com"}


def test_issue_now_requires_csrf(admin_client: TestClient) -> None:
    response = admin_client.post("/api/tls-settings/issue")
    assert response.status_code == 403


def test_get_reflects_the_issued_certificate_state(admin_client: TestClient, db_session: Session) -> None:
    state = get_tls_certificate_state(db_session)
    state.source = "lets_encrypt"
    state.domain = "smtp-relay.example.com"
    state.cert_pem = "CERT-PEM"
    state.encrypted_key_pem = encrypt_secret("KEY-PEM")
    db_session.commit()

    response = admin_client.get("/api/tls-settings")
    body = response.json()
    assert body["cert_source"] == "lets_encrypt"
    assert body["cert_domain"] == "smtp-relay.example.com"


def _configure_manual(admin_client: TestClient) -> None:
    admin_client.patch(
        "/api/tls-settings",
        json={"acme_enabled": True, "domain": "smtp-relay.example.com", "dns_provider": "manual"},
        headers=csrf_headers(admin_client),
    )


def test_verify_dns_access_rejects_manual_provider(admin_client: TestClient) -> None:
    _configure_manual(admin_client)
    response = admin_client.post("/api/tls-settings/verify-dns-access", headers=csrf_headers(admin_client))
    assert response.status_code == 400


def test_issue_now_does_not_require_a_cloudflare_token_for_manual_provider(
    admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_manual(admin_client)

    class _Result:
        success = False
        detail = 'This domain uses manual DNS-01 — use "Start DNS-01 Challenge" instead.'

    monkeypatch.setattr("app.api.routes.tls_settings.issue_or_renew", lambda db: _Result())

    response = admin_client.post("/api/tls-settings/issue", headers=csrf_headers(admin_client))
    assert response.status_code == 200  # not the 400 a missing Cloudflare token would cause
    assert response.json()["success"] is False


def test_manual_dns_start_requires_enabled_domain_and_manual_provider(admin_client: TestClient) -> None:
    response = admin_client.post("/api/tls-settings/manual-dns/start", headers=csrf_headers(admin_client))
    assert response.status_code == 400  # not enabled, no domain

    admin_client.patch(
        "/api/tls-settings",
        json={"acme_enabled": True, "domain": "smtp-relay.example.com"},  # still "cloudflare"
        headers=csrf_headers(admin_client),
    )
    response = admin_client.post("/api/tls-settings/manual-dns/start", headers=csrf_headers(admin_client))
    assert response.status_code == 400


def test_manual_dns_start_requires_csrf(admin_client: TestClient) -> None:
    response = admin_client.post("/api/tls-settings/manual-dns/start")
    assert response.status_code == 403


def test_manual_dns_start_success_and_audit(
    admin_client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_manual(admin_client)

    class _Result:
        success = True
        detail = "Add this TXT record, then click Verify & Continue."
        record_name = "_acme-challenge.smtp-relay.example.com"
        record_value = "the-validation-value"
        expires_at = None

    monkeypatch.setattr("app.api.routes.tls_settings.begin_manual_dns_challenge", lambda db: _Result())

    response = admin_client.post("/api/tls-settings/manual-dns/start", headers=csrf_headers(admin_client))
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["record_name"] == "_acme-challenge.smtp-relay.example.com"
    assert body["record_value"] == "the-validation-value"

    entry = db_session.query(AuditLog).filter(AuditLog.action == "tls_certificate.manual_dns_start").one()
    assert entry.detail == {"success": True, "domain": "smtp-relay.example.com"}


def test_manual_dns_confirm_requires_csrf(admin_client: TestClient) -> None:
    response = admin_client.post("/api/tls-settings/manual-dns/confirm")
    assert response.status_code == 403


def test_manual_dns_confirm_reports_when_nothing_is_pending(
    admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Result:
        success = False
        detail = "No manual DNS-01 challenge in progress."

    monkeypatch.setattr("app.api.routes.tls_settings.finalize_manual_dns_challenge", lambda db: _Result())

    response = admin_client.post("/api/tls-settings/manual-dns/confirm", headers=csrf_headers(admin_client))
    assert response.status_code == 200
    assert response.json() == {"success": False, "detail": "No manual DNS-01 challenge in progress."}


def test_manual_dns_confirm_success_and_audit(
    admin_client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_manual(admin_client)

    class _Result:
        success = True
        detail = "Issued."

    monkeypatch.setattr("app.api.routes.tls_settings.finalize_manual_dns_challenge", lambda db: _Result())

    response = admin_client.post("/api/tls-settings/manual-dns/confirm", headers=csrf_headers(admin_client))
    assert response.status_code == 200
    assert response.json() == {"success": True, "detail": "Issued."}

    entry = db_session.query(AuditLog).filter(AuditLog.action == "tls_certificate.manual_confirm").one()
    assert entry.detail == {"success": True, "domain": "smtp-relay.example.com"}


def test_get_reflects_a_pending_manual_challenge(admin_client: TestClient, db_session: Session) -> None:
    import datetime

    from app.core.encryption import encrypt_secret as _encrypt
    from app.core.settings_store import upsert_tls_pending_manual_challenge

    _configure_manual(admin_client)
    upsert_tls_pending_manual_challenge(
        db_session,
        domain="smtp-relay.example.com",
        contact_email=None,
        record_name="_acme-challenge.smtp-relay.example.com",
        record_value="the-validation-value",
        order_json="{}",
        encrypted_cert_key_pem=_encrypt("CERT-KEY"),
        encrypted_account_key_pem=_encrypt("ACCOUNT-KEY"),
        account_uri="https://acme.example/acct/1",
        directory_url="https://acme.example/directory",
        created_at=datetime.datetime.now(datetime.UTC),
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=24),
    )
    db_session.commit()

    response = admin_client.get("/api/tls-settings")
    body = response.json()
    assert body["manual_dns_pending"] is True
    assert body["manual_dns_record_name"] == "_acme-challenge.smtp-relay.example.com"
    assert body["manual_dns_record_value"] == "the-validation-value"
    assert body["manual_dns_expires_at"] is not None


def test_get_does_not_report_an_expired_pending_challenge(admin_client: TestClient, db_session: Session) -> None:
    import datetime

    from app.core.encryption import encrypt_secret as _encrypt
    from app.core.settings_store import upsert_tls_pending_manual_challenge

    _configure_manual(admin_client)
    upsert_tls_pending_manual_challenge(
        db_session,
        domain="smtp-relay.example.com",
        contact_email=None,
        record_name="_acme-challenge.smtp-relay.example.com",
        record_value="the-validation-value",
        order_json="{}",
        encrypted_cert_key_pem=_encrypt("CERT-KEY"),
        encrypted_account_key_pem=_encrypt("ACCOUNT-KEY"),
        account_uri="https://acme.example/acct/1",
        directory_url="https://acme.example/directory",
        created_at=datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC),
        expires_at=datetime.datetime(2020, 1, 2, tzinfo=datetime.UTC),
    )
    db_session.commit()

    response = admin_client.get("/api/tls-settings")
    assert response.json()["manual_dns_pending"] is False
