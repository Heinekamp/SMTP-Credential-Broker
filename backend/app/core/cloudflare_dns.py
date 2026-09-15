"""Cloudflare implementation of the DnsProvider protocol (core/dns_provider.py)
— used by the Let's Encrypt DNS-01 flow (core/acme_tls.py) to prove control
of the relay's domain without any inbound port 80/443.

Uses `requests` directly rather than the rest of this codebase's stdlib
`urllib.request` convention (see update_check.py) — `acme` (added in a
later slice of this feature) already forces `requests` into the
dependency tree via its own network layer, so splitting HTTP libraries
within this one feature would only double the idioms to maintain for no
real benefit."""

import time

import dns.exception
import dns.resolver
import requests

from app.core.logging_config import get_logger

_logger = get_logger("cloudflare_dns")

_API_BASE = "https://api.cloudflare.com/client/v4"


class CloudflareApiError(RuntimeError):
    """Cloudflare rejected a request or no zone could be resolved for the
    configured domain — a business-level failure the caller reports to
    the admin, not a crash."""


class CloudflareDnsProvider:
    def __init__(self, api_token: str, zone_id: str | None = None, timeout: float = 15.0) -> None:
        self.api_token = api_token
        self.zone_id = zone_id
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_token}", "Content-Type": "application/json"}

    def _resolve_zone_id(self, domain: str) -> str:
        """Uses the admin-supplied zone id verbatim if set (the robust,
        recommended path). Otherwise peels labels off `domain` and asks
        Cloudflare's `GET /zones?name=` for an exact match, since
        Cloudflare's API has no "find the zone owning this subdomain"
        endpoint and adding a public-suffix-list dependency just for this
        isn't worth it."""
        if self.zone_id:
            return self.zone_id

        labels = domain.split(".")
        for i in range(len(labels) - 1):
            candidate = ".".join(labels[i:])
            try:
                response = requests.get(
                    f"{_API_BASE}/zones", headers=self._headers(), params={"name": candidate}, timeout=self.timeout
                )
            except requests.RequestException as exc:
                raise CloudflareApiError(f"Could not reach Cloudflare: {exc}") from exc
            if not response.ok:
                raise CloudflareApiError(f"Cloudflare API error looking up zone {candidate!r}: {response.status_code}")
            result = response.json().get("result") or []
            if result:
                return result[0]["id"]

        raise CloudflareApiError(
            f"No Cloudflare zone found for {domain!r} or any parent domain. Set the Zone ID explicitly in Settings."
        )

    def verify_access(self, domain: str) -> tuple[bool, str]:
        try:
            zone_id = self._resolve_zone_id(domain)
        except CloudflareApiError as exc:
            return False, str(exc)

        try:
            response = requests.get(
                f"{_API_BASE}/zones/{zone_id}/dns_records",
                headers=self._headers(),
                params={"per_page": 1},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            return False, f"Could not reach Cloudflare: {exc}"

        if response.status_code in (401, 403):
            return False, "Cloudflare rejected this token (401/403) — check it has Zone:DNS:Edit permission."
        if not response.ok:
            return False, f"Cloudflare API error: {response.status_code} {response.text[:200]}"
        return True, f"Access confirmed for zone {zone_id}."

    def create_txt_record(self, domain: str, name: str, value: str) -> str:
        zone_id = self._resolve_zone_id(domain)
        _logger.info("creating TXT record: zone=%s requested_name=%s value=%s", zone_id, name, value)
        try:
            response = requests.post(
                f"{_API_BASE}/zones/{zone_id}/dns_records",
                headers=self._headers(),
                json={"type": "TXT", "name": name, "content": value, "ttl": 120},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise CloudflareApiError(f"Could not reach Cloudflare: {exc}") from exc

        body = response.json() if response.content else {}
        if not response.ok or not body.get("success"):
            raise CloudflareApiError(f"Failed to create TXT record: {body.get('errors', response.text[:200])}")
        result = body["result"]
        # Log exactly what Cloudflare says it stored — a diagnostic for a
        # real-world case (#56) where Cloudflare's API confirmed a record
        # existed but the zone's own authoritative nameservers never
        # served it; comparing the requested vs. stored name/zone here is
        # the fastest way to catch any silent transformation Cloudflare's
        # API applies (e.g. an unexpected zone suffix).
        _logger.info(
            "created TXT record: id=%s stored_name=%s stored_zone_id=%s stored_content=%s",
            result.get("id"),
            result.get("name"),
            result.get("zone_id"),
            result.get("content"),
        )
        return result["id"]

    def delete_txt_record(self, domain: str, record_id: str) -> None:
        try:
            zone_id = self._resolve_zone_id(domain)
            requests.delete(
                f"{_API_BASE}/zones/{zone_id}/dns_records/{record_id}", headers=self._headers(), timeout=self.timeout
            )
        except (CloudflareApiError, requests.RequestException):
            # A leftover challenge TXT record is harmless noise — not
            # worth failing an otherwise-successful issuance over.
            _logger.warning("failed to clean up ACME challenge TXT record %s", record_id, exc_info=True)

    def wait_for_propagation(self, name: str, value: str, timeout_seconds: float = 60.0) -> bool:
        """Queries the domain's real authoritative nameservers directly —
        not Cloudflare's management API. Confirmed in production (issue
        #56) that the two can briefly disagree: Cloudflare's API is
        instantly self-consistent with itself once a record is created,
        but its actual DNS-serving edge network can lag a few seconds
        behind — long enough that answering the ACME challenge as soon
        as the API confirms the record can still result in Let's
        Encrypt's own validation (which queries real DNS) finding
        nothing. Only once at least one authoritative nameserver
        genuinely serves the expected value is the challenge answered."""
        deadline = time.monotonic() + timeout_seconds
        nameservers = self._authoritative_nameservers(name)
        if not nameservers:
            _logger.warning("wait_for_propagation: could not resolve authoritative nameservers for %s", name)
            return False

        attempt = 0
        while time.monotonic() < deadline:
            attempt += 1
            if self._txt_record_visible_at(nameservers, name, value):
                _logger.info("wait_for_propagation: %s visible on attempt %d via %s", name, attempt, nameservers)
                return True
            time.sleep(2)
        _logger.warning(
            "wait_for_propagation: %s never became visible via %s within %.0fs", name, nameservers, timeout_seconds
        )
        return False

    def _authoritative_nameservers(self, name: str) -> list[str]:
        """Peels labels off `name` (the same technique _resolve_zone_id
        uses) until an NS lookup succeeds, so this works whether given a
        bare domain or a full challenge name like
        "_acme-challenge.sub.example.com"."""
        labels = name.split(".")
        for i in range(len(labels) - 1):
            candidate = ".".join(labels[i:])
            try:
                answer = dns.resolver.resolve(candidate, "NS", lifetime=self.timeout)
            except dns.exception.DNSException:
                continue
            return [str(rdata.target).rstrip(".") for rdata in answer]
        return []

    @staticmethod
    def _txt_record_visible_at(nameservers: list[str], name: str, value: str) -> bool:
        for nameserver in nameservers:
            try:
                answer = dns.resolver.resolve_at(nameserver, name, "TXT", lifetime=5.0)
            except dns.exception.DNSException:
                continue
            for rdata in answer:
                content = b"".join(rdata.strings).decode("utf-8", errors="replace")
                if content == value:
                    return True
        return False
