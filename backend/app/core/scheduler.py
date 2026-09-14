"""The background scheduler: stdlib `asyncio` only, no new dependency.
Backs scheduled connection testing, background update-checking, and alert
email — see backend/app/main.py's lifespan for how these are started/
stopped, and app/config.py's `scheduler_enabled` for why tests never run
this loop at all."""

import asyncio
from collections.abc import Awaitable, Callable

from app.core.logging_config import get_logger

_logger = get_logger("scheduler")


async def run_periodic(name: str, poll_seconds: float, tick: Callable[[], Awaitable[None]]) -> None:
    """Sleeps, runs `tick()`, catches+logs any exception so one bad tick
    never kills the loop. `tick()` itself decides whether enough wall-clock
    time has actually elapsed to do real work (via background_job_state) —
    this lets an admin-edited interval take effect within one poll_seconds
    window, no restart needed."""
    while True:
        await asyncio.sleep(poll_seconds)
        try:
            await tick()
        except Exception:
            _logger.exception("periodic task %s failed", name)
