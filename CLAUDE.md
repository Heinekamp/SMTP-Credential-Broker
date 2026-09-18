# CLAUDE.md

Project-wide guidance for working on SMTP Manager. This is the durable,
should-still-be-true-in-six-months layer — architecture, conventions, and
hard-won gotchas. It deliberately does **not** try to enumerate every
feature (that rots; the README's Features section and `docs/` are the
source of truth for "what exists today").

For machine-local details (this dev box's Docker install, SSH access to
the production host, deploy procedure) see `CLAUDE.local.md` — gitignored,
not part of this repo's history, recreate it per machine.

## What this project is

A self-hosted management plane around Postfix. A small number of
externally-hosted SMTP mailboxes (STRATO, Gmail, etc.) get shared by many
internal services, each issued its own scoped local credential — no
internal service ever sees a real upstream password. Three moving parts:

- **`backend/`** — FastAPI + SQLAlchemy + Alembic, Python 3.12. The admin
  API, the local-user rate-limit policy service (a Postfix
  policy-delegation listener), background schedulers (connection testing,
  update checks, alert email, rate-limit abuse detection, cert renewal),
  and the `relay` CLI (`backend/app/cli.py`).
- **`frontend/`** — React 18 + TypeScript + Vite + react-router-dom. Talks
  to the backend over `/api/*`, same-origin (the dev server proxies it —
  see `frontend/vite.config.ts`'s `VITE_BACKEND_PORT`).
- **`postfix/`** — a custom Postfix image with a Unix-socket control
  surface (`control_surface.py`) that's the *only* channel the backend
  uses to mutate `sasldb2` or install generated config
  (`security-model.md` §6).

Two Docker Compose services (`app` + `postfix`), SQLite by default. Deep
architecture docs live in `docs/` — `architecture.md`,
`postfix-architecture.md`, `security-model.md`, `database-schema.md`;
read those before touching config generation, the control surface, or the
encryption/auth model.

## Workflow conventions

- **Open a labeled GitHub issue before implementing anything non-trivial**
  (`enhancement`/`bug`/etc.). Multi-part work gets a master issue + linked
  child issues (e.g. #51 "Visual customization" → #52-#55). Never
  reference internal planning-file artifacts in issue/PR text.
- **This is a solo-maintainer repo worked via direct pushes to `main`**,
  not a PR-per-change workflow — commit and push directly once
  tests/lint/build are green. Branch protection on `main` requires the 4
  CI jobs as status checks, but `enforce_admins: false`, so that doesn't
  block direct pushes; it only gates PR merges (which is how Dependabot
  lands its own changes).
- **New automated-behavior settings default off/null** — "opt-in, never
  silently change behavior on upgrade." E.g. `rate_limit_abuse_auto_disable_enabled`
  and `notify_on_rate_limit_abuse` default `False`; `accent_color`/`logo_image`
  default `None` (fixed green accent / default logo). The 4 older
  `notify_on_*` fields (health degraded, upstream test failure, app/postfix
  update) are the one exception — they predate this convention and default
  `True` as "baseline monitoring."
- **Releases**: bump `backend/pyproject.toml` + `frontend/package.json` +
  `frontend/package-lock.json` together in one "Bump version to X.Y.Z"
  commit, confirm CI green, then `git tag vX.Y.Z && git push origin vX.Y.Z`
  and `gh release create` with Highlights / New features / Bug fixes /
  Upgrading sections (see any past release for the tone/format).
- **Real browser verification is expected for UI-facing changes** — don't
  just trust lint/build. Spin up a throwaway backend (`uvicorn` against a
  scratch SQLite DB) + frontend (`vite` dev server with `VITE_BACKEND_PORT`
  pointed at that backend's port), log in, and use Playwright to click
  through and screenshot the actual change. `scripts/screenshots/` is the
  reusable version of this pattern for README screenshots specifically.

## Testing

- Backend: `pytest -q` from `backend/`, fixtures in `backend/tests/conftest.py`
  — `client` (unauthenticated), `admin_client` (logged in),
  `csrf_headers(client)` (CSRF header for mutating requests),
  `fake_postfix_control` (captures control-surface calls instead of
  hitting a real socket — needed on this Windows dev box, see below).
  Lint: `ruff check .` (line-length 120, target py312).
- Frontend: `npm run lint` (eslint flat config) and `npm run build`
  (`tsc -b && vite build`) from `frontend/`.
- CI (`.github/workflows/ci.yml`) has 4 jobs: `backend`, `frontend`,
  `compose-smoke`, `integration`. The `integration` job runs real SMTP
  sessions against the real Postfix image (`integration/`) — this is the
  mandatory suite per `testing-strategy.md`; don't treat `compose-smoke`'s
  shallow health check as a substitute for it.

## Windows dev-machine limitation (matters for local testing)

Postfix's control surface needs a real Unix domain socket, which isn't
available on Windows — so local-user creation via the real UI/API can't
complete end-to-end on this dev machine (the `_set_sasl_or_503` call in
`api/routes/local_users.py` will fail). Workarounds already established:

- Backend tests use the `fake_postfix_control` fixture instead of a real
  socket.
- For manual UI verification needing seeded data, write rows directly via
  SQLAlchemy models, bypassing the control surface entirely — see
  `scripts/screenshots/seed_demo_data.py` for the reference pattern
  (admin, upstream accounts, senders, local users, mail log, all via
  direct `db.add()`, no API calls).
- SQLite URLs passed to a **native Windows** `python.exe` (the backend
  venv's interpreter) can't resolve Git Bash's `/tmp/...` paths — convert
  with `cygpath -m` to get a `C:/...`-style path first (see `run.sh`).

## Dependency-update review lessons (Dependabot)

`.github/dependabot.yml` + `.github/workflows/dependabot-auto-merge.yml`
cover pip (backend, integration), npm (frontend), docker (3 Dockerfiles),
and github-actions. Patch/minor updates auto-merge once CI passes; majors
always need manual review. Lessons learned the hard way:

- **Docker base-image tags are excluded from auto-merge entirely**,
  regardless of what `dependabot/fetch-metadata` reports. A tag bump like
  `python:3.12-slim → 3.14-slim` reads as "minor" (same leading version
  component) but carries none of the stability guarantees a real
  semver-minor library release does — this exact bump broke the
  integration test image once (Python 3.14 removed the implicit
  `asyncio.get_event_loop()` fallback the test stub relied on) and
  auto-merged to `main` before anyone looked at it. **Always manually
  review a Docker base-image bump.**
- **Don't judge a major-version PR by its changelog — test it.** Fetch
  the branch into a `git worktree`, `npm ci`/`pip install`, then
  lint/build/test. Several "broken" Dependabot majors turned out to have
  a perfectly fine intermediate version one step down: `vite` 5→8 was
  blocked (plugin-react's peer cap), but 5→7 installed and built clean;
  `typescript` 5.6→7.0 was blocked (`@typescript-eslint`'s peer cap), but
  5.6→6.0.3 was fine. Check the tightest-constraining installed package's
  actual peer-dependency ceiling before writing an upgrade off.
- When merging several Dependabot PRs against branch protection with
  strict (must-be-up-to-date) checks, **go one at a time** — `gh pr
  update-branch <n>`, wait for that PR's own checks, confirm it merged,
  *then* move to the next. Batch-updating all of them at once just causes
  repeated "BEHIND" churn as each merge advances `main` out from under
  the others.
- When two open PRs touch the same lines (e.g. two action-version bumps in
  the same workflow file), `gh pr update-branch` reports "Cannot update
  PR branch due to conflicts" — apply the second change by hand instead of
  fighting the rebase.
- `react` 19 as Dependabot proposed it bundles `react` alone without
  `react-dom`/`@types/react-dom` — an unresolvable peer conflict. Any
  future react-major bump needs those moved together.
- `eslint-plugin-react-hooks` 7 (needed for `eslint`/`@eslint/js` 10) adds
  stricter rules (`react-hooks/set-state-in-effect`, `react-hooks/purity`)
  that flag 10 existing "hydrate form state from a fetched object in a
  `useEffect`" call sites across the frontend — tracked in issue #90, a
  deliberate refactor, not a routine bump.

## Where things live

- `docs/` — installation, configuration, backup-restore, troubleshooting,
  upgrading, architecture, postfix-architecture, security-model,
  database-schema. Keep these in sync when adding DB columns, settings, or
  Postfix-facing behavior.
- `scripts/screenshots/` — the README-screenshot pipeline. `shots.py` is
  the extension point for a new screenshot (add a `Shot` or `GridShot`,
  no other file needs touching); `run.sh` orchestrates the whole seed →
  boot → capture → teardown cycle. See its own README for usage.
- `integration/` — the real-Postfix end-to-end test suite (separate
  `requirements.txt`, separate compose file).
