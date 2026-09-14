"""The scheduler itself (core/scheduler.py) plus the lifespan wiring in
main.py — conftest.py disables the scheduler for every other test module
(RELAY_SCHEDULER_ENABLED=false), so this file is the one place the
enabled path actually runs, verifying tasks start and stop cleanly rather
than leaking or crashing app startup/shutdown."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.core.scheduler import run_periodic


def test_run_periodic_calls_tick_repeatedly_and_survives_a_failing_tick() -> None:
    calls: list[int] = []

    async def _tick() -> None:
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("boom")

    async def _run() -> None:
        task = asyncio.create_task(run_periodic("test", 0.01, _tick))
        await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(_run())

    # At least a few ticks ran despite one of them raising.
    assert len(calls) >= 3


def test_app_starts_and_stops_cleanly_with_the_scheduler_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Confirms lifespan startup (creating the background task) and
    shutdown (cancelling it) don't raise — not a business-logic check
    (that's scheduled_tests.py's job), so this deliberately makes no HTTP
    request that would need real DB schema on the global engine."""
    from app.config import get_settings

    monkeypatch.setenv("RELAY_SCHEDULER_ENABLED", "true")
    get_settings.cache_clear()
    try:
        from app.main import app

        with TestClient(app):
            pass
    finally:
        get_settings.cache_clear()
