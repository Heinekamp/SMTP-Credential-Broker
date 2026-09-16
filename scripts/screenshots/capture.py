"""Playwright driver that walks shots.py's registry and writes each
screenshot into docs/images/ (issue #39). Assumes a backend + frontend
dev server are already running and reachable at --base-url, seeded via
seed_demo_data.py — run.sh wires all of that up; this script only
drives the browser.

    backend/.venv/Scripts/python.exe scripts/screenshots/capture.py \\
        --base-url http://localhost:5177
"""

import argparse
import io
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from shots import DEFAULT_VIEWPORT, SHOTS, SPLIT_SHOTS, Shot, ThemeSplitShot  # noqa: E402

DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs" / "images"
DEFAULT_EMAIL = "admin@example.com"
DEFAULT_PASSWORD = "Sup3rSecret!Pass"


def login(page: Page, base_url: str, email: str, password: str) -> None:
    page.goto(f"{base_url}/login")
    page.fill('input[aria-label="Email"]', email)
    page.fill('input[aria-label="Password"]', password)
    page.click('button[type="submit"]')
    page.wait_for_url(f"{base_url}/", timeout=10_000)
    page.wait_for_timeout(300)


def set_theme(page: Page, theme: str, *, account_button: str) -> None:
    """Drives the real account-menu switcher (Titlebar.tsx) rather than
    poking localStorage directly, so a capture run also doubles as a
    smoke test that the switcher itself still works."""
    label = "Dark" if theme == "dark" else "Light"
    page.click(account_button)
    page.wait_for_timeout(150)
    page.click(f'button:has-text("{label}")')
    page.wait_for_timeout(250)
    # Close the dropdown so it never accidentally appears in a shot —
    # it doesn't auto-close on a theme pick (Titlebar.tsx, by design).
    page.click(account_button)
    page.wait_for_timeout(150)


def goto_shot(page: Page, base_url: str, shot) -> None:
    page.set_viewport_size(shot.viewport)
    page.goto(f"{base_url}{shot.path}")
    page.wait_for_timeout(shot.wait_ms)
    if shot.prepare:
        shot.prepare(page)
        page.wait_for_timeout(shot.wait_ms)


def capture_shot(page: Page, base_url: str, shot: Shot, output_dir: Path, *, account_button: str) -> None:
    goto_shot(page, base_url, shot)
    set_theme(page, shot.theme, account_button=account_button)
    # Re-apply prepare() after the theme switch — set_theme navigated the
    # dropdown open/closed on the same page, which is harmless for most
    # shots, but a shot on a route with its own transient UI state (an
    # opened tab/modal) should still end in the state prepare() left it in.
    if shot.prepare:
        shot.prepare(page)
        page.wait_for_timeout(shot.wait_ms)
    out_path = output_dir / f"{shot.name}.png"
    page.screenshot(path=str(out_path))
    print(f"  wrote {out_path.relative_to(REPO_ROOT)}")


def capture_split_shot(
    page: Page, base_url: str, shot: ThemeSplitShot, output_dir: Path, *, account_button: str
) -> None:
    from PIL import Image

    goto_shot(page, base_url, shot)

    set_theme(page, "light", account_button=account_button)
    if shot.prepare:
        shot.prepare(page)
        page.wait_for_timeout(shot.wait_ms)
    light_bytes = page.screenshot()

    set_theme(page, "dark", account_button=account_button)
    if shot.prepare:
        shot.prepare(page)
        page.wait_for_timeout(shot.wait_ms)
    dark_bytes = page.screenshot()

    light_img = Image.open(io.BytesIO(light_bytes))
    dark_img = Image.open(io.BytesIO(dark_bytes))
    width, height = light_img.size
    assert dark_img.size == (width, height), "light/dark captures must be the same size to split cleanly"

    composite = Image.new("RGB", (width, height))
    half = width // 2
    composite.paste(light_img.crop((0, 0, half, height)), (0, 0))
    composite.paste(dark_img.crop((half, 0, width, height)), (half, 0))

    out_path = output_dir / f"{shot.name}.png"
    composite.save(out_path)
    print(f"  wrote {out_path.relative_to(REPO_ROOT)} (light|dark split)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:5177")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument(
        "--only",
        nargs="*",
        help="Only capture shots with these names (from shots.py) instead of the full registry.",
    )
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    shots = [s for s in SHOTS if not args.only or s.name in args.only]
    split_shots = [s for s in SPLIT_SHOTS if not args.only or s.name in args.only]
    if not shots and not split_shots:
        print("Nothing matched --only.", file=sys.stderr)
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=DEFAULT_VIEWPORT)
        login(page, args.base_url, args.email, args.password)
        account_button = f'button:has-text("{args.email}")'

        for shot in shots:
            print(f"Capturing {shot.name} ({shot.theme})...")
            capture_shot(page, args.base_url, shot, args.output_dir, account_button=account_button)

        for split_shot in split_shots:
            print(f"Capturing {split_shot.name} (light|dark split)...")
            capture_split_shot(page, args.base_url, split_shot, args.output_dir, account_button=account_button)

        browser.close()

    print("Done.")


if __name__ == "__main__":
    main()
