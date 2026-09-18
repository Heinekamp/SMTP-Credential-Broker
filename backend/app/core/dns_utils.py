"""Provider-agnostic authoritative-DNS propagation check, shared by every
DnsProvider implementation (core/dns_provider.py) that needs to confirm a
TXT record is actually live before answering an ACME DNS-01 challenge.

Queries the domain's real authoritative nameservers directly rather than
trusting any provider's own management API — confirmed in production
(issue #56) that the two can briefly disagree: a provider's API can be
instantly self-consistent with itself once a record is created, but its
actual DNS-serving edge network can lag a few seconds behind, long enough
that answering the ACME challenge as soon as the API confirms the record
can still result in Let's Encrypt's own validation (which queries real
DNS) finding nothing."""

import time

import dns.exception
import dns.resolver

from app.core.logging_config import get_logger

_logger = get_logger("dns_utils")


def authoritative_nameservers(name: str, *, timeout: float = 15.0) -> list[str]:
    """Peels labels off `name` until an NS lookup succeeds, so this works
    whether given a bare domain or a full challenge name like
    "_acme-challenge.sub.example.com"."""
    labels = name.split(".")
    for i in range(len(labels) - 1):
        candidate = ".".join(labels[i:])
        try:
            answer = dns.resolver.resolve(candidate, "NS", lifetime=timeout)
        except dns.exception.DNSException:
            continue
        return [str(rdata.target).rstrip(".") for rdata in answer]
    return []


def txt_record_visible_at(nameservers: list[str], name: str, value: str) -> bool:
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


def wait_for_propagation_via_authoritative_dns(name: str, value: str, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    nameservers = authoritative_nameservers(name)
    if not nameservers:
        _logger.warning("wait_for_propagation: could not resolve authoritative nameservers for %s", name)
        return False

    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        if txt_record_visible_at(nameservers, name, value):
            _logger.info("wait_for_propagation: %s visible on attempt %d via %s", name, attempt, nameservers)
            return True
        time.sleep(2)
    _logger.warning(
        "wait_for_propagation: %s never became visible via %s within %.0fs", name, nameservers, timeout_seconds
    )
    return False
