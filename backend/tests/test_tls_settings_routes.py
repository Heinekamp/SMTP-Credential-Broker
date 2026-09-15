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
