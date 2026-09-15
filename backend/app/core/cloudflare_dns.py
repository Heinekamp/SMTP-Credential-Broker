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
        return body["result"]["id"]

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
        """Polls Cloudflare's own (authoritative) API for the record's
        existence rather than doing real DNS resolution — Cloudflare's API
        reflects a just-created record immediately in the overwhelming
        majority of cases, and avoiding a real DNS-resolution dependency
        (e.g. dnspython) here keeps this feature's footprint small. Let's
        Encrypt's own validation retries independently on top of this."""
        deadline = time.monotonic() + timeout_seconds
        try:
            # _resolve_zone_id already peels labels off whatever domain-like
            # string it's given until one matches a real zone, so passing
            # the full challenge name (e.g. "_acme-challenge.sub.example.com")
            # resolves to the same zone create_txt_record used, without
            # needing to know how many labels belong to the actual domain.
            zone_id = self._resolve_zone_id(name)
        except CloudflareApiError:
            return False

        while time.monotonic() < deadline:
            try:
                response = requests.get(
                    f"{_API_BASE}/zones/{zone_id}/dns_records",
                    headers=self._headers(),
                    params={"type": "TXT", "name": name},
                    timeout=self.timeout,
                )
                if response.ok:
                    records = response.json().get("result") or []
                    if any(record.get("content") == value for record in records):
                        return True
            except requests.RequestException:
                pass
            time.sleep(2)
        return False
