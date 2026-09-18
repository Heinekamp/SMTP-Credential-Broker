"""Manual implementation of the DnsProvider protocol (core/dns_provider.py)
— for admins whose DNS isn't hosted on a provider this app can talk to
directly. Unlike CloudflareDnsProvider, this provider never touches any
DNS API: the admin adds/removes the TXT record themselves, wherever
their DNS is actually hosted, and this class only ever confirms the
record is visible via the same authoritative-nameserver check Cloudflare
uses (core/dns_utils.py)."""

from app.core import dns_utils


class ManualDnsProvider:
    def verify_access(self, domain: str) -> tuple[bool, str]:
        return True, "No credentials needed — you add the TXT record yourself."

    def create_txt_record(self, domain: str, name: str, value: str) -> str:
        # Nothing to create — the admin manages the record's lifecycle.
        return ""

    def delete_txt_record(self, domain: str, record_id: str) -> None:
        # Nothing to delete — the admin owns cleanup, same as creation.
        return None

    def wait_for_propagation(self, name: str, value: str, timeout_seconds: float = 60.0) -> bool:
        return dns_utils.wait_for_propagation_via_authoritative_dns(name, value, timeout_seconds)
