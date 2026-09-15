"""The seam between the ACME orchestration (core/acme_tls.py) and a real
DNS API for fulfilling DNS-01 challenges. Cloudflare (core/cloudflare_dns.py)
is the only implementation for v1 — a second provider is a new class
implementing this Protocol, never a change to the orchestration logic."""

from typing import Protocol


class DnsProvider(Protocol):
    def verify_access(self, domain: str) -> tuple[bool, str]:
        """Read-only precheck: can this provider's credentials see and
        manage records for `domain`'s zone? Must not create anything —
        callers use this to catch a bad credential before spending an
        ACME rate-limited attempt."""
        ...

    def create_txt_record(self, domain: str, name: str, value: str) -> str:
        """Creates a TXT record (e.g. `_acme-challenge.<domain>`) and
        returns a provider-specific record id for later deletion."""
        ...

    def delete_txt_record(self, domain: str, record_id: str) -> None:
        """Best-effort cleanup — a leftover challenge TXT record is
        harmless noise, so implementations should log and swallow
        failures here rather than raise."""
        ...

    def wait_for_propagation(self, name: str, value: str, timeout_seconds: float = 60.0) -> bool:
        """Blocks until the record is visible (by whatever means this
        provider considers authoritative), or `timeout_seconds` elapses.
        Returns whether it became visible in time."""
        ...
