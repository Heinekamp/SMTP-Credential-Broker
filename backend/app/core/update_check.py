"""Best-effort checks for a newer release of this app (GitHub's releases
API — clean and reliable) and of Postfix (no clean canonical "latest
version" feed exists, so this regex-scrapes postfix.org's own download
page — approximate by nature, expected to fail silently if that page's
format ever changes). Both return None on any failure and never raise —
this must never be allowed to break the scheduler loop or crash a request.

Only ever called when relay_settings.update_check_enabled is True — see
update_check_tick() below, which checks that before either network call.
"""

import asyncio
import datetime
import json
import re
import urllib.request

from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.logging_config import get_logger
from app.core.settings_store import get_background_job_state, get_relay_settings
from app.db.session import SessionLocal

_logger = get_logger("update_check")

_GITHUB_RELEASES_URL = "https://api.github.com/repos/Heinekamp/smtp-credential-broker/releases/latest"
_POSTFIX_DOWNLOAD_URL = "https://www.postfix.org/download.html"
_REQUEST_TIMEOUT_SECONDS = 10
_CHECK_INTERVAL = datetime.timedelta(hours=24)


def parse_version(value: str) -> tuple[int, ...] | None:
    """Parses a numeric-dotted version string (e.g. "3.8.6" or "0.2.0")
    into a tuple usable for ordering comparison. Returns None (never
    raises) for anything that doesn't look like one."""
    if not re.fullmatch(r"\d+(\.\d+)*", value):
        return None
    return tuple(int(part) for part in value.split("."))


def check_app_update() -> str | None:
    try:
        request = urllib.request.Request(
            _GITHUB_RELEASES_URL,
            headers={"User-Agent": "smtp-credential-broker-update-check", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read())
        tag = data.get("tag_name", "")
        return tag.lstrip("v") or None
    except Exception:
        _logger.warning("app update check failed", exc_info=True)
        return None


def check_postfix_update() -> str | None:
    try:
        request = urllib.request.Request(
            _POSTFIX_DOWNLOAD_URL, headers={"User-Agent": "smtp-credential-broker-update-check"}
        )
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            html = response.read().decode("utf-8", errors="replace")
        match = re.search(r"[Ss]table release[^0-9]{0,20}(\d+\.\d+(?:\.\d+)?)", html)
        return match.group(1) if match else None
    except Exception:
        _logger.warning("postfix update check failed", exc_info=True)
        return None


def _run_checks(db: Session) -> None:
    state = get_background_job_state(db)
    now = utcnow()

    app_version = check_app_update()
    if app_version is not None:
        state.latest_app_version = app_version
        state.latest_app_version_checked_at = now

    postfix_version = check_postfix_update()
    if postfix_version is not None:
        state.latest_postfix_version = postfix_version
        state.latest_postfix_version_checked_at = now

    state.update_check_last_run_at = now
    db.commit()


def _update_check_tick_sync() -> None:
    db = SessionLocal()
    try:
        settings_row = get_relay_settings(db)
        if not settings_row.update_check_enabled:
            # Zero outbound calls at all when off — checked before either
            # network call, not after (decision: opt-in, off by default).
            return

        state = get_background_job_state(db)
        if state.update_check_last_run_at is not None:
            elapsed = utcnow() - state.update_check_last_run_at
            if elapsed < _CHECK_INTERVAL:
                return

        _run_checks(db)
    finally:
        db.close()


async def update_check_tick() -> None:
    # check_app_update/check_postfix_update are blocking urllib calls (up
    # to a 10s timeout each) — see connection_test_tick's identical
    # rationale for why this can't run directly on the event loop.
    await asyncio.to_thread(_update_check_tick_sync)
