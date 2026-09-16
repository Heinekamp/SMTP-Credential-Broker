"""Declarative registry of README screenshots (issue #39).

This is the single place to touch when a future feature needs a new
screenshot: add a `Shot` (or `ThemeSplitShot`) to the lists below —
`capture.py` doesn't need any changes. `path` is a frontend route;
`prepare`, if given, receives the already-logged-in Playwright `Page`
positioned at that route and can click around (open a tab, a modal, a
dropdown) before the screenshot is taken.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

Prepare = Callable[[object], None] | None

DEFAULT_VIEWPORT = {"width": 1400, "height": 900}


@dataclass
class Shot:
    name: str  # output file stem -> docs/images/{name}.png
    path: str  # frontend route, e.g. "/mail-log"
    theme: str = "dark"  # "dark" or "light"
    prepare: Prepare = None
    viewport: dict = field(default_factory=lambda: dict(DEFAULT_VIEWPORT))
    wait_ms: int = 400  # settle time after navigation/prepare, before the shot


@dataclass
class ThemeSplitShot:
    """Captures the same route in both themes and composites them into
    one image, light on the left half / dark on the right half."""

    name: str
    path: str
    prepare: Prepare = None
    viewport: dict = field(default_factory=lambda: dict(DEFAULT_VIEWPORT))
    wait_ms: int = 400


def _open_settings_tab(tab_label: str) -> Callable[[object], None]:
    def _prepare(page) -> None:
        page.click("text=Settings")
        page.wait_for_timeout(200)
        page.click(f"text={tab_label}")
        page.wait_for_timeout(200)

    return _prepare


# Existing README screenshots (re-captured against seeded demo data).
SHOTS: list[Shot] = [
    Shot(name="dashboard", path="/"),
    Shot(name="upstream-accounts", path="/upstream-accounts"),
    Shot(name="local-smtp-users", path="/local-users"),
    Shot(name="settings-system", path="/settings", prepare=_open_settings_tab("System")),
    # New per issue #39 — Mail Log had no screenshot at all.
    Shot(name="mail-log", path="/mail-log"),
]

# TOTP enrollment (docs/images/totp-enroll.png) is deliberately NOT
# regenerated here — its QR code is instance-specific and uninteresting
# to vary (issue #39's own "keep as-is" direction).

# Shows off visual customization (#51-#55): same screen, both themes,
# split down the middle.
SPLIT_SHOTS: list[ThemeSplitShot] = [
    ThemeSplitShot(name="theme-light-dark-split", path="/"),
]
