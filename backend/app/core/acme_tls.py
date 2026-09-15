"""Let's Encrypt certificate issuance/renewal via DNS-01 (RFC 8555),
using the `acme` package (EFF/Certbot's client) for the protocol itself
— JWS signing, account/order/challenge/finalize handling is a security
protocol this codebase should not hand-roll.

`issue_or_renew` is the single entry point both the manual "Issue/Renew
Now" route and the background renewal tick (core/cert_renewal.py) call.
It reads its configuration from RelaySettings/TlsCertificateState, talks
to Let's Encrypt through an injectable `AcmeIssuer` (the real
implementation is `LetsEncryptAcmeIssuer`; tests substitute a fake), and
only mutates TlsCertificateState once postfix_control.install_tls_certificate
has actually confirmed the new cert is live — an ACME success that
Postfix then rejects must never be recorded as if it succeeded.
"""

import dataclasses
import datetime
from typing import Protocol

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import postfix_control
from app.core.clock import utcnow
from app.core.cloudflare_dns import CloudflareDnsProvider
from app.core.dns_provider import DnsProvider
from app.core.encryption import DecryptionFailed, EncryptionKeyNotConfigured, decrypt_secret, encrypt_secret
from app.core.logging_config import get_logger
from app.core.postfix_control import PostfixControlError
from app.core.settings_store import get_background_job_state, get_relay_settings, get_tls_certificate_state

_logger = get_logger("acme_tls")

_RSA_KEY_SIZE = 2048  # matches the Dockerfile-baked placeholder cert's key size


@dataclasses.dataclass
class IssuedCertificate:
    cert_pem: str  # full chain
    key_pem: str  # RSA private key, PEM
    not_before: datetime.datetime
    not_after: datetime.datetime


class AcmeIssuer(Protocol):
    """Seam between the orchestration logic below and a real ACME server
    — tests substitute a fake implementation so the default suite never
    makes a real network call."""

    def issue(
        self,
        *,
        domain: str,
        contact_email: str | None,
        account_key_pem: str | None,
        account_uri: str | None,
        dns_provider: DnsProvider,
    ) -> tuple[IssuedCertificate, str, str]:  # (certificate, account_key_pem, account_uri)
        ...


def _generate_rsa_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=_RSA_KEY_SIZE)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


class LetsEncryptAcmeIssuer:
    """Real implementation, backed by the `acme` package."""

    def __init__(self, directory_url: str) -> None:
        self.directory_url = directory_url

    def issue(
        self,
        *,
        domain: str,
        contact_email: str | None,
        account_key_pem: str | None,
        account_uri: str | None,
        dns_provider: DnsProvider,
    ) -> tuple[IssuedCertificate, str, str]:
        import josepy as jose
        from acme import challenges, client, crypto_util, errors, messages

        if account_key_pem is None:
            account_key_pem = _generate_rsa_key_pem()
        account_key = jose.JWKRSA.load(account_key_pem.encode("utf-8"))

        net = client.ClientNetwork(account_key, user_agent="smtp-manager-relay/1.0")
        directory = messages.Directory.from_json(net.get(self.directory_url).json())
        acme_client = client.ClientV2(directory, net=net)

        regr = None
        if account_uri:
            try:
                regr = acme_client.query_registration(
                    messages.RegistrationResource(uri=account_uri, body=messages.Registration())
                )
            except errors.Error:
                regr = None  # stored account no longer valid — register fresh below

        if regr is None:
            new_reg = messages.NewRegistration.from_data(email=contact_email, terms_of_service_agreed=True)
            try:
                regr = acme_client.new_account(new_reg)
            except errors.ConflictError as exc:
                regr = acme_client.query_registration(
                    messages.RegistrationResource(uri=exc.args[0], body=messages.Registration())
                )

        cert_key_pem = _generate_rsa_key_pem()
        csr_pem = crypto_util.make_csr(cert_key_pem.encode("utf-8"), domains=[domain])
        orderr = acme_client.new_order(csr_pem)

        challenge_name = f"_acme-challenge.{domain}"
        record_id: str | None = None
        try:
            for authz in orderr.authorizations:
                dns_challenge = next(
                    (c for c in authz.body.challenges if isinstance(c.chall, challenges.DNS01)), None
                )
                if dns_challenge is None:
                    raise RuntimeError(f"No dns-01 challenge offered for {domain!r}.")

                validation = dns_challenge.chall.validation(acme_client.net.key)
                record_id = dns_provider.create_txt_record(domain, challenge_name, validation)
                if not dns_provider.wait_for_propagation(challenge_name, validation):
                    raise RuntimeError(f"DNS-01 TXT record for {challenge_name!r} did not propagate in time.")
                acme_client.answer_challenge(dns_challenge, dns_challenge.chall.response(acme_client.net.key))

            deadline = datetime.datetime.now() + datetime.timedelta(seconds=90)
            finalized = acme_client.poll_and_finalize(orderr, deadline=deadline)
        finally:
            if record_id is not None:
                dns_provider.delete_txt_record(domain, record_id)

        # fullchain_pem is the leaf certificate followed by its
        # intermediate(s) — the first one is what Postfix's smtpd
        # presents and whose validity window governs renewal.
        leaf = x509.load_pem_x509_certificates(finalized.fullchain_pem.encode("utf-8"))[0]
        issued = IssuedCertificate(
            cert_pem=finalized.fullchain_pem,
            key_pem=cert_key_pem,
            not_before=leaf.not_valid_before_utc,
            not_after=leaf.not_valid_after_utc,
        )
        return issued, account_key_pem, regr.uri


@dataclasses.dataclass
class CertificateIssuanceResult:
    success: bool
    detail: str
    not_after: datetime.datetime | None = None


def _build_dns_provider(provider_name: str, api_token: str, zone_id: str | None) -> DnsProvider | None:
    if provider_name == "cloudflare":
        return CloudflareDnsProvider(api_token=api_token, zone_id=zone_id)
    return None


def issue_or_renew(db: Session, *, issuer: AcmeIssuer | None = None) -> CertificateIssuanceResult:
    """Reads config from RelaySettings/TlsCertificateState, performs one
    full ACME issuance, and — only on a verified success — mutates
    tls_certificate_state in place. Does not commit; the caller (the
    manual route, or cert_renewal.py's tick) controls the transaction,
    same division of responsibility as run_retention_cleanup."""
    settings_row = get_relay_settings(db)
    state = get_tls_certificate_state(db)

    if not settings_row.tls_acme_enabled:
        return CertificateIssuanceResult(success=False, detail="Let's Encrypt issuance is not enabled.")
    if not settings_row.tls_domain:
        return CertificateIssuanceResult(success=False, detail="No domain configured.")
    if settings_row.tls_cloudflare_api_token_encrypted is None:
        return CertificateIssuanceResult(success=False, detail="No Cloudflare API token configured.")

    try:
        token = decrypt_secret(settings_row.tls_cloudflare_api_token_encrypted)
    except (EncryptionKeyNotConfigured, DecryptionFailed) as exc:
        return CertificateIssuanceResult(success=False, detail=str(exc))

    dns_provider = _build_dns_provider(settings_row.tls_dns_provider, token, settings_row.tls_cloudflare_zone_id)
    if dns_provider is None:
        detail = f"Unsupported DNS provider: {settings_row.tls_dns_provider!r}"
        return CertificateIssuanceResult(success=False, detail=detail)

    account_key_pem = None
    if state.acme_account_key_encrypted is not None:
        try:
            account_key_pem = decrypt_secret(state.acme_account_key_encrypted)
        except (EncryptionKeyNotConfigured, DecryptionFailed):
            account_key_pem = None  # fall through to registering a fresh account

    active_issuer = issuer or LetsEncryptAcmeIssuer(get_settings().acme_directory_url)

    try:
        issued, account_key_pem, account_uri = active_issuer.issue(
            domain=settings_row.tls_domain,
            contact_email=settings_row.tls_contact_email,
            account_key_pem=account_key_pem,
            account_uri=state.acme_account_uri,
            dns_provider=dns_provider,
        )
    except Exception as exc:  # ACME/DNS failures are business-level, not crashes
        return CertificateIssuanceResult(success=False, detail=str(exc))

    install_result = postfix_control.install_tls_certificate(cert_pem=issued.cert_pem, key_pem=issued.key_pem)
    if not install_result.success:
        # ACME succeeded but Postfix rejected it (shouldn't happen given
        # the control surface's own validation, but never persist a
        # "success" the live relay doesn't actually have) — leave
        # tls_certificate_state untouched so a stale-but-good cert stays
        # recorded as the source of truth.
        detail = f"Issued but Postfix rejected it: {install_result.detail}"
        return CertificateIssuanceResult(success=False, detail=detail)

    state.source = "lets_encrypt"
    state.domain = settings_row.tls_domain
    state.cert_pem = issued.cert_pem
    state.encrypted_key_pem = encrypt_secret(issued.key_pem)
    state.not_before = issued.not_before
    state.not_after = issued.not_after
    state.issued_at = utcnow()
    state.acme_account_key_encrypted = encrypt_secret(account_key_pem)
    state.acme_account_uri = account_uri

    # Clears a previously-recorded failure regardless of whether this
    # success came from the background tick or a manual "Issue/Renew
    # Now" click — a resolved problem must not keep showing as if it's
    # still broken just because the manual path doesn't otherwise touch
    # BackgroundJobState (issue #56's follow-up: the fix landed, but the
    # stale error from before it stayed on screen next to a freshly
    # issued, working certificate).
    get_background_job_state(db).cert_last_renewal_error = None

    return CertificateIssuanceResult(success=True, detail="Issued.", not_after=issued.not_after)


def sync_certificate_to_postfix(db: Session) -> None:
    """Pushes whatever's in tls_certificate_state to the live Postfix
    files if a real cert has ever been issued (the self-signed
    placeholder is left alone otherwise) — called once at app startup
    and, cheaply, at the top of every renewal tick, so a lost
    postfix_tls volume (or a fresh postfix container) self-heals from
    the database. install_tls_certificate itself is a no-op (no
    restart) when the live files already match."""
    state = get_tls_certificate_state(db)
    if state.cert_pem is None or state.encrypted_key_pem is None:
        return
    try:
        key_pem = decrypt_secret(state.encrypted_key_pem)
    except (EncryptionKeyNotConfigured, DecryptionFailed):
        _logger.warning("cannot sync TLS certificate to postfix: encryption key unavailable")
        return
    try:
        postfix_control.install_tls_certificate(cert_pem=state.cert_pem, key_pem=key_pem)
    except PostfixControlError:
        _logger.warning("could not reach the postfix control surface to sync TLS certificate", exc_info=True)
