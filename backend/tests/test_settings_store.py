from sqlalchemy.orm import Session

from app.core.settings_store import get_background_job_state, get_relay_settings, get_tls_certificate_state
from app.models.settings import BackgroundJobState, RelaySettings
from app.models.tls import TlsCertificateState


def test_get_relay_settings_creates_row_1_with_defaults(db_session: Session) -> None:
    settings_row = get_relay_settings(db_session)
    assert settings_row.id == 1
    assert settings_row.connection_test_interval_minutes is None
    assert settings_row.update_check_enabled is False
    assert settings_row.notify_recipients == []
    assert settings_row.notify_sender_id is None
    assert settings_row.notify_on_health_degraded is True
    assert settings_row.notify_on_upstream_test_failure is True
    assert settings_row.notify_on_app_update_available is True
    assert settings_row.notify_on_postfix_update_available is True
    assert settings_row.tls_acme_enabled is False
    assert settings_row.tls_domain is None
    assert settings_row.tls_dns_provider == "cloudflare"
    assert settings_row.tls_cloudflare_api_token_encrypted is None
    assert db_session.query(RelaySettings).count() == 1


def test_get_relay_settings_is_idempotent(db_session: Session) -> None:
    first = get_relay_settings(db_session)
    first.update_check_enabled = True
    db_session.commit()

    second = get_relay_settings(db_session)
    assert second.id == first.id
    assert second.update_check_enabled is True
    assert db_session.query(RelaySettings).count() == 1


def test_get_background_job_state_creates_row_1_with_defaults(db_session: Session) -> None:
    state = get_background_job_state(db_session)
    assert state.id == 1
    assert state.connection_test_last_run_at is None
    assert state.latest_app_version is None
    assert state.health_degraded_active is False
    assert state.upstream_test_failure_active is False
    assert state.cert_renewal_last_checked_at is None
    assert state.cert_last_renewal_error is None
    assert db_session.query(BackgroundJobState).count() == 1


def test_get_background_job_state_is_idempotent(db_session: Session) -> None:
    first = get_background_job_state(db_session)
    first.health_degraded_active = True
    db_session.commit()

    second = get_background_job_state(db_session)
    assert second.id == first.id
    assert second.health_degraded_active is True
    assert db_session.query(BackgroundJobState).count() == 1


def test_get_tls_certificate_state_creates_row_1_with_defaults(db_session: Session) -> None:
    state = get_tls_certificate_state(db_session)
    assert state.id == 1
    assert state.source == "self_signed"
    assert state.domain is None
    assert state.cert_pem is None
    assert state.encrypted_key_pem is None
    assert db_session.query(TlsCertificateState).count() == 1


def test_get_tls_certificate_state_is_idempotent(db_session: Session) -> None:
    first = get_tls_certificate_state(db_session)
    first.source = "lets_encrypt"
    db_session.commit()

    second = get_tls_certificate_state(db_session)
    assert second.id == first.id
    assert second.source == "lets_encrypt"
    assert db_session.query(TlsCertificateState).count() == 1
