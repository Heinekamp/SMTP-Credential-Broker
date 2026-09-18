from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_db, require_csrf
from app.core.acme_tls import begin_manual_dns_challenge, finalize_manual_dns_challenge, issue_or_renew
from app.core.audit import client_ip, record_audit
from app.core.clock import utcnow
from app.core.cloudflare_dns import CloudflareDnsProvider
from app.core.encryption import DecryptionFailed, EncryptionKeyNotConfigured, decrypt_secret, encrypt_secret
from app.core.settings_store import (
    get_background_job_state,
    get_relay_settings,
    get_tls_certificate_state,
    get_tls_pending_manual_challenge,
)
from app.models.admin import AdminUser
from app.models.settings import BackgroundJobState, RelaySettings
from app.models.tls import TlsCertificateState, TlsPendingManualChallenge
from app.schemas.tls_settings import (
    IssueCertificateResponse,
    ManualDnsChallengeResponse,
    TlsSettingsRead,
    TlsSettingsUpdate,
    VerifyDnsAccessResponse,
)

router = APIRouter(prefix="/tls-settings", tags=["tls-settings"], dependencies=[Depends(get_current_admin)])

# TlsSettingsUpdate field name -> RelaySettings attribute name. The schema
# drops the "tls_" prefix for a cleaner API surface; cloudflare_api_token
# is handled separately since it needs encryption, not a plain setattr.
_FIELD_MAP = {
    "acme_enabled": "tls_acme_enabled",
    "domain": "tls_domain",
    "contact_email": "tls_contact_email",
    "dns_provider": "tls_dns_provider",
    "cloudflare_zone_id": "tls_cloudflare_zone_id",
}


def _encrypt_or_503(token: str) -> bytes:
    try:
        return encrypt_secret(token)
    except EncryptionKeyNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


def _decrypt_or_503(blob: bytes) -> str:
    try:
        return decrypt_secret(blob)
    except (EncryptionKeyNotConfigured, DecryptionFailed) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


def _to_read(
    settings_row: RelaySettings,
    cert_state: TlsCertificateState,
    job_state: BackgroundJobState,
    pending_challenge: TlsPendingManualChallenge | None,
) -> TlsSettingsRead:
    # An expired-but-not-yet-cleaned-up row reads as absent — GET stays
    # read-only, actual cleanup happens lazily in finalize_manual_dns_challenge.
    pending = pending_challenge if pending_challenge is not None and pending_challenge.expires_at > utcnow() else None
    return TlsSettingsRead(
        acme_enabled=settings_row.tls_acme_enabled,
        domain=settings_row.tls_domain,
        contact_email=settings_row.tls_contact_email,
        dns_provider=settings_row.tls_dns_provider,
        cloudflare_zone_id=settings_row.tls_cloudflare_zone_id,
        cloudflare_api_token_configured=settings_row.tls_cloudflare_api_token_encrypted is not None,
        cert_source=cert_state.source,
        cert_domain=cert_state.domain,
        cert_not_after=cert_state.not_after,
        cert_issued_at=cert_state.issued_at,
        last_checked_at=job_state.cert_renewal_last_checked_at,
        last_renewal_attempt_at=job_state.cert_last_renewal_attempt_at,
        last_renewal_error=job_state.cert_last_renewal_error,
        manual_dns_pending=pending is not None,
        manual_dns_record_name=pending.record_name if pending else None,
        manual_dns_record_value=pending.record_value if pending else None,
        manual_dns_expires_at=pending.expires_at if pending else None,
    )


@router.get("", response_model=TlsSettingsRead)
def get_tls_settings(db: Session = Depends(get_db)) -> TlsSettingsRead:
    return _to_read(
        get_relay_settings(db),
        get_tls_certificate_state(db),
        get_background_job_state(db),
        get_tls_pending_manual_challenge(db),
    )


@router.patch("", response_model=TlsSettingsRead, dependencies=[Depends(require_csrf)])
def update_tls_settings(
    payload: TlsSettingsUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> TlsSettingsRead:
    settings_row = get_relay_settings(db)
    # exclude_unset (not exclude_none) — a field explicitly sent as null
    # (e.g. clearing the domain) must still be applied; only fields the
    # client didn't send at all should be left untouched.
    updates = payload.model_dump(exclude_unset=True)
    token = updates.pop("cloudflare_api_token", None)
    for field, value in updates.items():
        setattr(settings_row, _FIELD_MAP[field], value)
    if token:
        settings_row.tls_cloudflare_api_token_encrypted = _encrypt_or_503(token)

    audited_fields = sorted([*updates.keys(), *(["cloudflare_api_token"] if token else [])])
    record_audit(
        db,
        admin_user_id=admin.id,
        action="tls_settings.update",
        target_type="relay_settings",
        target_id=settings_row.id,
        detail={"fields": audited_fields},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(settings_row)
    return _to_read(
        settings_row, get_tls_certificate_state(db), get_background_job_state(db), get_tls_pending_manual_challenge(db)
    )


@router.post("/verify-dns-access", response_model=VerifyDnsAccessResponse, dependencies=[Depends(require_csrf)])
def verify_dns_access(
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> VerifyDnsAccessResponse:
    """A read-only precheck — confirms the configured Cloudflare token can
    see and manage the domain's zone, without creating any DNS record or
    spending a Let's Encrypt rate-limited attempt."""
    settings_row = get_relay_settings(db)
    if not settings_row.tls_domain:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Configure a domain first.")
    if settings_row.tls_dns_provider != "cloudflare":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Verify is only applicable to the Cloudflare provider.")
    if settings_row.tls_cloudflare_api_token_encrypted is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Configure a Cloudflare API token first.")

    token = _decrypt_or_503(settings_row.tls_cloudflare_api_token_encrypted)
    provider = CloudflareDnsProvider(api_token=token, zone_id=settings_row.tls_cloudflare_zone_id)
    success, detail = provider.verify_access(settings_row.tls_domain)

    record_audit(
        db,
        admin_user_id=admin.id,
        action="tls_settings.verify_dns_access",
        detail={"success": success},
        ip_address=client_ip(request),
    )
    db.commit()
    return VerifyDnsAccessResponse(success=success, detail=detail)


@router.post("/issue", response_model=IssueCertificateResponse, dependencies=[Depends(require_csrf)])
def issue_now(
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> IssueCertificateResponse:
    """Runs one real ACME issuance attempt right now — same "diagnostic
    report, not an exception" contract as Test Connection/Send Test
    Alert: a precondition that makes issuance flatly impossible is a
    400, an actual issuance failure is success: false with the real
    detail."""
    settings_row = get_relay_settings(db)
    if not settings_row.tls_acme_enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enable Let's Encrypt first.")
    if not settings_row.tls_domain:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Configure a domain first.")
    if settings_row.tls_dns_provider == "cloudflare" and settings_row.tls_cloudflare_api_token_encrypted is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Configure a Cloudflare API token first.")

    result = issue_or_renew(db)

    record_audit(
        db,
        admin_user_id=admin.id,
        action="tls_certificate.manual_issue",
        detail={"success": result.success, "domain": settings_row.tls_domain},
        ip_address=client_ip(request),
    )
    db.commit()
    return IssueCertificateResponse(success=result.success, detail=result.detail)


@router.post("/manual-dns/start", response_model=ManualDnsChallengeResponse, dependencies=[Depends(require_csrf)])
def start_manual_dns_challenge(
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> ManualDnsChallengeResponse:
    """Starts (or resumes) a manual DNS-01 challenge — returns the TXT
    record the admin needs to add at their own DNS provider before
    calling /manual-dns/confirm."""
    settings_row = get_relay_settings(db)
    if not settings_row.tls_acme_enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enable Let's Encrypt first.")
    if not settings_row.tls_domain:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Configure a domain first.")
    if settings_row.tls_dns_provider != "manual":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Set DNS provider to Manual first.")

    result = begin_manual_dns_challenge(db)

    record_audit(
        db,
        admin_user_id=admin.id,
        action="tls_certificate.manual_dns_start",
        detail={"success": result.success, "domain": settings_row.tls_domain},
        ip_address=client_ip(request),
    )
    db.commit()
    return ManualDnsChallengeResponse(
        success=result.success,
        detail=result.detail,
        record_name=result.record_name,
        record_value=result.record_value,
        expires_at=result.expires_at,
    )


@router.post("/manual-dns/confirm", response_model=IssueCertificateResponse, dependencies=[Depends(require_csrf)])
def confirm_manual_dns_challenge(
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> IssueCertificateResponse:
    """Confirms the manual TXT record is live and finishes issuance. Safe
    to call repeatedly while DNS is still propagating — a not-yet-visible
    record is reported as a failure without discarding the in-progress
    challenge, so the admin can just try again."""
    domain = get_relay_settings(db).tls_domain
    result = finalize_manual_dns_challenge(db)

    record_audit(
        db,
        admin_user_id=admin.id,
        action="tls_certificate.manual_confirm",
        detail={"success": result.success, "domain": domain},
        ip_address=client_ip(request),
    )
    db.commit()
    return IssueCertificateResponse(success=result.success, detail=result.detail)
