"""check_app_update/check_postfix_update never make a real network call in
tests — urllib.request.urlopen is monkeypatched per test. update_check_tick
opens its own real app.db.session.SessionLocal internally (same reasoning
as test_scheduled_tests.py), so its tests use that shared in-memory engine
with the same autouse cleanup fixture pattern.
"""

import io
import json

import pytest

from app.core.settings_store import get_background_job_state, get_relay_settings
from app.core.update_check import check_app_update, check_postfix_update, parse_version, update_check_tick
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.settings import BackgroundJobState, RelaySettings


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._buf = io.BytesIO(body)

    def read(self) -> bytes:
        return self._buf.read()

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def test_parse_version_accepts_numeric_dotted_strings() -> None:
    assert parse_version("3.8.6") == (3, 8, 6)
    assert parse_version("0.1.0") == (0, 1, 0)
    assert parse_version("1") == (1,)


@pytest.mark.parametrize("value", ["", "v1.2.3", "1.2.3-beta", "not a version", "1..2"])
def test_parse_version_rejects_anything_non_numeric(value: str) -> None:
    assert parse_version(value) is None


def test_check_app_update_returns_stripped_tag_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps({"tag_name": "v0.2.0"}).encode()
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResponse(body))
    assert check_app_update() == "0.2.0"


def test_check_app_update_returns_none_on_malformed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResponse(b"not json"))
    assert check_app_update() is None


def test_check_app_update_returns_none_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: object, **kwargs: object) -> None:
        raise OSError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    assert check_app_update() is None


def test_check_postfix_update_extracts_stable_release_version(monkeypatch: pytest.MonkeyPatch) -> None:
    html = b"<html>...Stable release: 3.9.1...</html>"
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResponse(html))
    assert check_postfix_update() == "3.9.1"


def test_check_postfix_update_returns_none_when_pattern_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResponse(b"<html>nothing here</html>"))
    assert check_postfix_update() is None


def test_check_postfix_update_returns_none_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: object, **kwargs: object) -> None:
        raise TimeoutError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    assert check_postfix_update() is None


@pytest.fixture(autouse=True)
def _clean_shared_db() -> None:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        db.query(RelaySettings).delete()
        db.query(BackgroundJobState).delete()
        db.commit()
    finally:
        db.close()


def test_tick_makes_no_outbound_call_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[None] = []
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: calls.append(None))

    import asyncio

    asyncio.run(update_check_tick())

    assert calls == []


def test_tick_runs_checks_when_enabled_and_due(monkeypatch: pytest.MonkeyPatch) -> None:
    db = SessionLocal()
    get_relay_settings(db).update_check_enabled = True
    db.commit()
    db.close()

    monkeypatch.setattr("app.core.update_check.check_app_update", lambda: "0.2.0")
    monkeypatch.setattr("app.core.update_check.check_postfix_update", lambda: "3.9.1")

    import asyncio

    asyncio.run(update_check_tick())

    db = SessionLocal()
    state = get_background_job_state(db)
    assert state.latest_app_version == "0.2.0"
    assert state.latest_postfix_version == "3.9.1"
    assert state.update_check_last_run_at is not None
    db.close()


def test_tick_skips_when_not_yet_due(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.clock import utcnow

    db = SessionLocal()
    get_relay_settings(db).update_check_enabled = True
    get_background_job_state(db).update_check_last_run_at = utcnow()
    db.commit()
    db.close()

    calls: list[None] = []
    monkeypatch.setattr("app.core.update_check.check_app_update", lambda: calls.append(None) or "0.2.0")

    import asyncio

    asyncio.run(update_check_tick())

    assert calls == []
