# README screenshot tooling

Regenerates every screenshot in the top-level README (`docs/images/*.png`)
against a throwaway, realistically-seeded demo instance — see issue #39.

## Usage

```bash
scripts/screenshots/run.sh
```

This builds/boots a temporary backend + frontend dev pair against a fresh
SQLite database in a scratch directory, seeds it with realistic demo data
(several upstream accounts, senders, local SMTP users, and a Mail Log with
a believable mix of sent/deferred/bounced/rejected entries), captures every
screenshot in `shots.py`, writes them into `docs/images/`, and tears
everything down again. Nothing it touches is left behind — the demo
database and dev servers are scoped to the run.

To only regenerate a subset (faster, while iterating on one page):

```bash
scripts/screenshots/run.sh --only dashboard mail-log
```

Requires `backend/.venv` to already exist (the normal backend dev setup) —
this installs the `screenshots` extra (Playwright, Pillow) into it and the
Chromium browser Playwright needs, both idempotently.

## Adding a screenshot for a new feature

Add one entry to `shots.py`'s `SHOTS` list — a name (becomes
`docs/images/{name}.png`), the frontend route, and an optional `prepare`
callback if the shot needs some clicking first (opening a settings tab, a
modal, etc. — see `_open_settings_tab` for an example). `capture.py` needs
no changes. Then add the new image to the README's Screenshots section.

## Files

- `seed_demo_data.py` — writes demo rows directly via the backend's own
  SQLAlchemy models (bypassing the HTTP API and Postfix's control socket,
  neither of which anything here needs to actually work end-to-end).
- `shots.py` — the registry described above; the intended extension point.
- `capture.py` — the Playwright driver: logs in once, then walks the
  registry. Also handles `ThemeSplitShot`s (see `theme-light-dark-split`),
  which capture the same route in both themes and composite them
  side-by-side with Pillow.
- `run.sh` — orchestrates the whole pipeline end to end.
