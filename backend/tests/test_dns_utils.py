"""Unit tests for app/core/dns_utils.py — the authoritative-nameserver
propagation check shared by every DnsProvider implementation. `dns.resolver`
is monkeypatched so these never make a real network call."""

import dns.exception
import dns.resolver
import pytest

from app.core import dns_utils


class _FakeNsRdata:
    def __init__(self, target: str) -> None:
        self.target = target  # dnspython's real Name.__str__ includes a trailing dot


class _FakeTxtRdata:
    def __init__(self, *strings: bytes) -> None:
        self.strings = list(strings)


def test_authoritative_nameservers_peels_labels_until_ns_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression test for issue #56: wait_for_propagation must query the
    domain's real authoritative nameservers, not a provider's management
    API — the two can briefly disagree about whether a record is
    actually being served."""
    requested: list[str] = []

    def fake_resolve(qname: str, rdtype: str, **kwargs):
        requested.append(qname)
        if qname == "example.com":
            return [_FakeNsRdata("ns1.example.com."), _FakeNsRdata("ns2.example.com.")]
        raise dns.resolver.NXDOMAIN()

    monkeypatch.setattr("app.core.dns_utils.dns.resolver.resolve", fake_resolve)

    nameservers = dns_utils.authoritative_nameservers("_acme-challenge.sub.example.com")

    assert nameservers == ["ns1.example.com", "ns2.example.com"]
    assert requested == ["_acme-challenge.sub.example.com", "sub.example.com", "example.com"]


def test_authoritative_nameservers_returns_empty_when_nothing_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.dns_utils.dns.resolver.resolve",
        lambda qname, rdtype, **kwargs: (_ for _ in ()).throw(dns.resolver.NXDOMAIN()),
    )

    assert dns_utils.authoritative_nameservers("sub.example.com") == []


def test_wait_for_propagation_returns_true_once_visible_at_an_authoritative_nameserver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dns_utils, "authoritative_nameservers", lambda name: ["ns1.example.com"])
    responses = [
        dns.exception.DNSException("not yet"),
        [_FakeTxtRdata(b"the-txt-value")],
    ]

    def fake_resolve_at(where: str, qname: str, rdtype: str, **kwargs):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr("app.core.dns_utils.dns.resolver.resolve_at", fake_resolve_at)
    monkeypatch.setattr("app.core.dns_utils.time.sleep", lambda seconds: None)

    result = dns_utils.wait_for_propagation_via_authoritative_dns(
        "_acme-challenge.example.com", "the-txt-value", timeout_seconds=10
    )
    assert result is True


def test_wait_for_propagation_ignores_a_nameserver_with_the_wrong_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stale record from a past failed attempt (a real scenario given
    issue #56's delete_txt_record cleanup gap) must not be mistaken for
    the current attempt's fresh value."""
    monkeypatch.setattr(dns_utils, "authoritative_nameservers", lambda name: ["ns1.example.com"])
    calls = {"count": 0}

    def fake_resolve_at(where: str, qname: str, rdtype: str, **kwargs):
        calls["count"] += 1
        return [_FakeTxtRdata(b"stale-value-from-a-past-attempt")]

    monkeypatch.setattr("app.core.dns_utils.dns.resolver.resolve_at", fake_resolve_at)
    monkeypatch.setattr("app.core.dns_utils.time.sleep", lambda seconds: None)

    result = dns_utils.wait_for_propagation_via_authoritative_dns(
        "_acme-challenge.example.com", "the-txt-value", timeout_seconds=0.05
    )
    assert result is False
    assert calls["count"] >= 1


def test_wait_for_propagation_gives_up_after_the_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dns_utils, "authoritative_nameservers", lambda name: ["ns1.example.com"])
    monkeypatch.setattr(
        "app.core.dns_utils.dns.resolver.resolve_at",
        lambda where, qname, rdtype, **kwargs: (_ for _ in ()).throw(dns.exception.DNSException()),
    )

    result = dns_utils.wait_for_propagation_via_authoritative_dns(
        "_acme-challenge.example.com", "the-txt-value", timeout_seconds=-1
    )
    assert result is False


def test_wait_for_propagation_returns_false_when_no_nameservers_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dns_utils, "authoritative_nameservers", lambda name: [])

    result = dns_utils.wait_for_propagation_via_authoritative_dns(
        "_acme-challenge.example.com", "the-txt-value", timeout_seconds=10
    )
    assert result is False
