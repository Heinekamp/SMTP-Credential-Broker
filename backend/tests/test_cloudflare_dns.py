"""Unit tests for app/core/cloudflare_dns.py — `requests` and `dns.resolver`
are both monkeypatched so these never make a real network call."""

import dns.exception
import dns.resolver
import pytest
import requests

from app.core.cloudflare_dns import CloudflareApiError, CloudflareDnsProvider


class _FakeNsRdata:
    def __init__(self, target: str) -> None:
        self.target = target  # dnspython's real Name.__str__ includes a trailing dot


class _FakeTxtRdata:
    def __init__(self, *strings: bytes) -> None:
        self.strings = list(strings)


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_body: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._json_body = json_body if json_body is not None else {}
        self.text = text
        self.content = b"1" if json_body is not None else b""

    def json(self) -> dict:
        return self._json_body


def test_create_txt_record_uses_admin_supplied_zone_id_and_skips_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_get(url: str, **kwargs) -> _FakeResponse:
        calls.append(("GET", url))
        raise AssertionError("zone lookup must be skipped when a zone id is supplied")

    def fake_post(url: str, **kwargs) -> _FakeResponse:
        calls.append(("POST", url))
        assert url == "https://api.cloudflare.com/client/v4/zones/Z123/dns_records"
        return _FakeResponse(200, {"success": True, "result": {"id": "REC1"}})

    monkeypatch.setattr("app.core.cloudflare_dns.requests.get", fake_get)
    monkeypatch.setattr("app.core.cloudflare_dns.requests.post", fake_post)

    provider = CloudflareDnsProvider(api_token="tok", zone_id="Z123")
    record_id = provider.create_txt_record("smtp-relay.example.com", "_acme-challenge.smtp-relay.example.com", "abc")

    assert record_id == "REC1"
    assert calls == [("POST", "https://api.cloudflare.com/client/v4/zones/Z123/dns_records")]


def test_resolve_zone_id_peels_labels_until_a_zone_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    requested_names: list[str] = []

    def fake_get(url: str, *, params: dict, **kwargs) -> _FakeResponse:
        requested_names.append(params["name"])
        if params["name"] == "example.com":
            return _FakeResponse(200, {"result": [{"id": "ZONE-EXAMPLE"}]})
        return _FakeResponse(200, {"result": []})

    monkeypatch.setattr("app.core.cloudflare_dns.requests.get", fake_get)

    provider = CloudflareDnsProvider(api_token="tok")
    zone_id = provider._resolve_zone_id("smtp-relay.example.com")

    assert zone_id == "ZONE-EXAMPLE"
    assert requested_names == ["smtp-relay.example.com", "example.com"]


def test_resolve_zone_id_raises_when_no_zone_matches_any_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.cloudflare_dns.requests.get", lambda url, **kwargs: _FakeResponse(200, {"result": []})
    )

    provider = CloudflareDnsProvider(api_token="tok")
    with pytest.raises(CloudflareApiError, match="No Cloudflare zone found"):
        provider._resolve_zone_id("smtp-relay.example.com")


def test_create_txt_record_raises_on_cloudflare_reported_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.cloudflare_dns.requests.post",
        lambda url, **kwargs: _FakeResponse(200, {"success": False, "errors": [{"message": "invalid name"}]}),
    )
    provider = CloudflareDnsProvider(api_token="tok", zone_id="Z123")

    with pytest.raises(CloudflareApiError, match="invalid name"):
        provider.create_txt_record("example.com", "_acme-challenge.example.com", "abc")


def test_delete_txt_record_is_best_effort_and_swallows_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_delete(url: str, **kwargs) -> None:
        raise requests.ConnectionError("network down")

    monkeypatch.setattr("app.core.cloudflare_dns.requests.delete", fake_delete)
    provider = CloudflareDnsProvider(api_token="tok", zone_id="Z123")

    provider.delete_txt_record("example.com", "REC1")  # must not raise


def test_verify_access_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.cloudflare_dns.requests.get", lambda url, **kwargs: _FakeResponse(200, {"result": []})
    )
    provider = CloudflareDnsProvider(api_token="tok", zone_id="Z123")

    success, detail = provider.verify_access("example.com")

    assert success is True
    assert "Z123" in detail


def test_verify_access_reports_a_rejected_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.cloudflare_dns.requests.get", lambda url, **kwargs: _FakeResponse(403))
    provider = CloudflareDnsProvider(api_token="bad-token", zone_id="Z123")

    success, detail = provider.verify_access("example.com")

    assert success is False
    assert "rejected this token" in detail


def test_verify_access_reports_a_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, **kwargs):
        raise requests.ConnectionError("dns resolution failed")

    monkeypatch.setattr("app.core.cloudflare_dns.requests.get", fake_get)
    provider = CloudflareDnsProvider(api_token="tok", zone_id="Z123")

    success, detail = provider.verify_access("example.com")

    assert success is False
    assert "Could not reach Cloudflare" in detail


def test_authoritative_nameservers_peels_labels_until_ns_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression test for issue #56: wait_for_propagation must query the
    domain's real authoritative nameservers, not Cloudflare's management
    API — the two can briefly disagree about whether a record is
    actually being served."""
    requested: list[str] = []

    def fake_resolve(qname: str, rdtype: str, **kwargs):
        requested.append(qname)
        if qname == "example.com":
            return [_FakeNsRdata("ns1.example.com."), _FakeNsRdata("ns2.example.com.")]
        raise dns.resolver.NXDOMAIN()

    monkeypatch.setattr("app.core.cloudflare_dns.dns.resolver.resolve", fake_resolve)
    provider = CloudflareDnsProvider(api_token="tok")

    nameservers = provider._authoritative_nameservers("_acme-challenge.sub.example.com")

    assert nameservers == ["ns1.example.com", "ns2.example.com"]
    assert requested == ["_acme-challenge.sub.example.com", "sub.example.com", "example.com"]


def test_authoritative_nameservers_returns_empty_when_nothing_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.cloudflare_dns.dns.resolver.resolve",
        lambda qname, rdtype, **kwargs: (_ for _ in ()).throw(dns.resolver.NXDOMAIN()),
    )
    provider = CloudflareDnsProvider(api_token="tok")

    assert provider._authoritative_nameservers("sub.example.com") == []


def test_wait_for_propagation_returns_true_once_visible_at_an_authoritative_nameserver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(CloudflareDnsProvider, "_authoritative_nameservers", lambda self, name: ["ns1.example.com"])
    responses = [
        dns.exception.DNSException("not yet"),
        [_FakeTxtRdata(b"the-txt-value")],
    ]

    def fake_resolve_at(where: str, qname: str, rdtype: str, **kwargs):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr("app.core.cloudflare_dns.dns.resolver.resolve_at", fake_resolve_at)
    monkeypatch.setattr("app.core.cloudflare_dns.time.sleep", lambda seconds: None)
    provider = CloudflareDnsProvider(api_token="tok")

    assert provider.wait_for_propagation("_acme-challenge.example.com", "the-txt-value", timeout_seconds=10) is True


def test_wait_for_propagation_ignores_a_nameserver_with_the_wrong_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stale record from a past failed attempt (a real scenario given
    issue #56's delete_txt_record cleanup gap) must not be mistaken for
    the current attempt's fresh value."""
    monkeypatch.setattr(CloudflareDnsProvider, "_authoritative_nameservers", lambda self, name: ["ns1.example.com"])
    calls = {"count": 0}

    def fake_resolve_at(where: str, qname: str, rdtype: str, **kwargs):
        calls["count"] += 1
        return [_FakeTxtRdata(b"stale-value-from-a-past-attempt")]

    monkeypatch.setattr("app.core.cloudflare_dns.dns.resolver.resolve_at", fake_resolve_at)
    monkeypatch.setattr("app.core.cloudflare_dns.time.sleep", lambda seconds: None)
    provider = CloudflareDnsProvider(api_token="tok")

    assert provider.wait_for_propagation("_acme-challenge.example.com", "the-txt-value", timeout_seconds=0.05) is False
    assert calls["count"] >= 1


def test_wait_for_propagation_gives_up_after_the_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CloudflareDnsProvider, "_authoritative_nameservers", lambda self, name: ["ns1.example.com"])
    monkeypatch.setattr(
        "app.core.cloudflare_dns.dns.resolver.resolve_at",
        lambda where, qname, rdtype, **kwargs: (_ for _ in ()).throw(dns.exception.DNSException()),
    )
    provider = CloudflareDnsProvider(api_token="tok")

    assert provider.wait_for_propagation("_acme-challenge.example.com", "the-txt-value", timeout_seconds=-1) is False


def test_wait_for_propagation_returns_false_when_no_nameservers_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CloudflareDnsProvider, "_authoritative_nameservers", lambda self, name: [])
    provider = CloudflareDnsProvider(api_token="tok")

    assert provider.wait_for_propagation("_acme-challenge.example.com", "the-txt-value", timeout_seconds=10) is False
