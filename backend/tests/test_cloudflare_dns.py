"""Unit tests for app/core/cloudflare_dns.py — `requests` is monkeypatched
so these never make a real network call. The authoritative-nameserver
propagation check itself now lives in app/core/dns_utils.py and is
covered by tests/test_dns_utils.py; this file only checks that
wait_for_propagation delegates to it correctly."""

import pytest
import requests

from app.core.cloudflare_dns import CloudflareApiError, CloudflareDnsProvider


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


def test_wait_for_propagation_delegates_to_dns_utils(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(
        "app.core.cloudflare_dns.dns_utils.wait_for_propagation_via_authoritative_dns",
        lambda name, value, timeout_seconds: calls.append((name, value, timeout_seconds)) or True,
    )
    provider = CloudflareDnsProvider(api_token="tok")

    result = provider.wait_for_propagation("_acme-challenge.example.com", "the-txt-value", timeout_seconds=10)

    assert result is True
    assert calls == [("_acme-challenge.example.com", "the-txt-value", 10)]


def test_wait_for_propagation_returns_false_when_dns_utils_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.cloudflare_dns.dns_utils.wait_for_propagation_via_authoritative_dns",
        lambda name, value, timeout_seconds: False,
    )
    provider = CloudflareDnsProvider(api_token="tok")

    assert provider.wait_for_propagation("_acme-challenge.example.com", "the-txt-value", timeout_seconds=10) is False
