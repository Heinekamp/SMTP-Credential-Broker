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
import json
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from shots import DEFAULT_VIEWPORT, GRID_SHOTS, SHOTS, GridShot, Shot  # noqa: E402

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


def set_accent_color(page: Page, base_url: str, color: str | None) -> None:
    """PATCHes /api/branding directly rather than driving the Appearance
    tab's form — this needs to run many times per grid shot, and the
    page's own session cookie (incl. the CSRF cookie) is already
    attached to page.request automatically since it shares the
    browsing context's cookie jar."""
    csrf = next((c["value"] for c in page.context.cookies() if c["name"] == "csrf_token"), None)
    headers = {"content-type": "application/json"}
    if csrf:
        headers["x-csrf-token"] = csrf
    response = page.request.patch(f"{base_url}/api/branding", data=json.dumps({"accent_color": color}), headers=headers)
    if not response.ok:
        raise RuntimeError(f"PATCH /api/branding failed: {response.status} {response.text()}")


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


def capture_grid_shot(page: Page, base_url: str, shot: GridShot, output_dir: Path, *, account_button: str) -> None:
    from PIL import Image

    page.set_viewport_size(shot.viewport)
    cell_images = []
    for theme, color in shot.cells:
        set_accent_color(page, base_url, color)
        # A fresh navigation (not just set_theme's clicking) so the
        # branding query re-fetches and picks up the new accent color —
        # BrandingEffects only re-applies --accent when that query's
        # data actually changes.
        page.goto(f"{base_url}{shot.path}")
        page.wait_for_timeout(shot.wait_ms)
        set_theme(page, theme, account_button=account_button)
        if shot.prepare:
            shot.prepare(page)
            page.wait_for_timeout(shot.wait_ms)
        img = Image.open(io.BytesIO(page.screenshot())).convert("RGB").resize(shot.cell_size)
        cell_images.append(img)

    cols = shot.grid_cols
    rows = -(-len(cell_images) // cols)  # ceil division
    cell_w, cell_h = shot.cell_size
    grid = Image.new("RGB", (cell_w * cols, cell_h * rows))
    for i, img in enumerate(cell_images):
        row, col = divmod(i, cols)
        grid.paste(img, (col * cell_w, row * cell_h))

    # Reset to the default accent — this is a throwaway seeded instance
    # torn down right after the run, but leaving it on some arbitrary
    # grid color instead of null would be a confusing thing to stumble
    # on if a future run is inspected mid-way or reused.
    set_accent_color(page, base_url, None)

    out_path = output_dir / f"{shot.name}.png"
    grid.save(out_path)
    print(f"  wrote {out_path.relative_to(REPO_ROOT)} ({cols}x{rows} grid)")


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
    grid_shots = [s for s in GRID_SHOTS if not args.only or s.name in args.only]
    if not shots and not grid_shots:
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

        for grid_shot in grid_shots:
            print(f"Capturing {grid_shot.name} ({len(grid_shot.cells)}-cell grid)...")
            capture_grid_shot(page, args.base_url, grid_shot, args.output_dir, account_button=account_button)

        browser.close()

    print("Done.")


if __name__ == "__main__":
    main()
