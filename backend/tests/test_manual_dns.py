"""Unit tests for app/core/manual_dns.py — the admin manages the TXT
record themselves, so create/delete are no-ops and only wait_for_propagation
does any real work (delegated to dns_utils, covered by tests/test_dns_utils.py)."""

import pytest

from app.core.manual_dns import ManualDnsProvider


def test_verify_access_always_succeeds() -> None:
    success, detail = ManualDnsProvider().verify_access("example.com")
    assert success is True
    assert detail


def test_create_txt_record_is_a_noop() -> None:
    provider = ManualDnsProvider()
    provider.create_txt_record("example.com", "_acme-challenge.example.com", "value")  # must not raise


def test_delete_txt_record_is_a_noop() -> None:
    provider = ManualDnsProvider()
    provider.delete_txt_record("example.com", "")  # must not raise


def test_wait_for_propagation_delegates_to_dns_utils(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(
        "app.core.manual_dns.dns_utils.wait_for_propagation_via_authoritative_dns",
        lambda name, value, timeout_seconds: calls.append((name, value, timeout_seconds)) or True,
    )
    provider = ManualDnsProvider()

    result = provider.wait_for_propagation("_acme-challenge.example.com", "the-txt-value", timeout_seconds=20)

    assert result is True
    assert calls == [("_acme-challenge.example.com", "the-txt-value", 20)]
