#!/usr/bin/env bash
# Regenerates every README screenshot (issue #39) end to end: fresh
# throwaway DB -> migrate -> seed realistic demo data -> boot a
# dev backend + frontend -> drive them with Playwright -> write
# docs/images/*.png -> tear everything down again.
#
# Usage:
#   scripts/screenshots/run.sh                 # regenerate everything in shots.py
#   scripts/screenshots/run.sh --only dashboard mail-log
#
# Requires the backend venv to exist already (backend/.venv) — this
# installs the screenshots extras (Playwright, Pillow) into it and the
# Chromium browser Playwright needs, both idempotent.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
FRONTEND_DIR="$REPO_ROOT/frontend"

BACKEND_PORT="${SCREENSHOT_BACKEND_PORT:-8010}"
FRONTEND_PORT="${SCREENSHOT_FRONTEND_PORT:-5179}"
BASE_URL="http://localhost:$FRONTEND_PORT"

if [ -x "$BACKEND_DIR/.venv/Scripts/python.exe" ]; then
    PYTHON="$BACKEND_DIR/.venv/Scripts/python.exe"
elif [ -x "$BACKEND_DIR/.venv/bin/python" ]; then
    PYTHON="$BACKEND_DIR/.venv/bin/python"
else
    echo "backend/.venv not found — set it up first (see backend's README/AGENTS notes)." >&2
    exit 1
fi

SCRATCH_DIR="$(mktemp -d)"
DB_PATH="$SCRATCH_DIR/screenshots.db"
# SQLite is opened by native Windows python.exe, which can't resolve Git
# Bash's /tmp/... path — cygpath -m gives the forward-slash-with-drive-
# letter form (C:/...) both sqlite3 and this script's own bash can use.
if command -v cygpath >/dev/null 2>&1; then
    DB_PATH_FOR_URL="$(cygpath -m "$DB_PATH")"
else
    DB_PATH_FOR_URL="$DB_PATH"
fi
BACKEND_PID=""
FRONTEND_PID=""

port_in_use() {
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && { exec 3<&-; exec 3>&-; return 0; } || return 1
}

# A silently-failed-to-bind server here is worse than a loud error: the
# readiness check below only confirms *something* answers on the port,
# so a leftover process from a previous interrupted run would otherwise
# serve stale seeded data all over again without anyone noticing (this
# bit a real regeneration during development — see the run.sh history).
for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
    if port_in_use "$port"; then
        echo "Port $port is already in use — a previous run may not have shut down cleanly." >&2
        echo "Find and stop whatever's listening on it, then re-run." >&2
        exit 1
    fi
done

cleanup() {
    [ -n "$BACKEND_PID" ] && kill -9 "$BACKEND_PID" 2>/dev/null || true
    [ -n "$FRONTEND_PID" ] && kill -9 "$FRONTEND_PID" 2>/dev/null || true
    # Give both a moment to actually release the DB file/ports before
    # removing the scratch dir out from under them.
    sleep 1
    rm -rf "$SCRATCH_DIR" 2>/dev/null || true
}
trap cleanup EXIT

echo "==> Installing screenshot tooling deps into backend/.venv (idempotent)..."
(cd "$BACKEND_DIR" && "$PYTHON" -m pip install -q -e ".[screenshots]")
"$PYTHON" -m playwright install --with-deps chromium >/dev/null 2>&1 || "$PYTHON" -m playwright install chromium

export RELAY_DATABASE_URL="sqlite:///$DB_PATH_FOR_URL"
export RELAY_COOKIE_SECURE=false
export RELAY_SCHEDULER_ENABLED=false
export RELAY_ENCRYPTION_KEY="${RELAY_ENCRYPTION_KEY:-$("$PYTHON" -c 'import base64, os; print(base64.b64encode(os.urandom(32)).decode())')}"

echo "==> Running migrations against a fresh throwaway DB..."
(cd "$BACKEND_DIR" && "$PYTHON" -m alembic upgrade head)

echo "==> Seeding realistic demo data..."
"$PYTHON" "$SCRIPT_DIR/seed_demo_data.py"

echo "==> Starting backend on :$BACKEND_PORT..."
# --app-dir (not a `cd` in a subshell) so $! below is the real uvicorn
# process, not an intermediate subshell — a subshell's child can survive
# `kill "$!"` and keep the scratch DB file locked during cleanup.
"$PYTHON" -m uvicorn app.main:app --app-dir "$BACKEND_DIR" --host 127.0.0.1 --port "$BACKEND_PORT" \
    >"$SCRATCH_DIR/backend.log" 2>&1 &
BACKEND_PID=$!

echo "==> Starting frontend on :$FRONTEND_PORT..."
VITE_BACKEND_PORT="$BACKEND_PORT" "$FRONTEND_DIR/node_modules/.bin/vite" "$FRONTEND_DIR" \
    --config "$FRONTEND_DIR/vite.config.ts" --port "$FRONTEND_PORT" --strictPort \
    >"$SCRATCH_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!

echo "==> Waiting for both servers to come up..."
for i in $(seq 1 60); do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo "Backend exited immediately — see $SCRATCH_DIR/backend.log" >&2
        cat "$SCRATCH_DIR/backend.log" >&2
        exit 1
    fi
    if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
        echo "Frontend exited immediately — see $SCRATCH_DIR/frontend.log" >&2
        cat "$SCRATCH_DIR/frontend.log" >&2
        exit 1
    fi
    if curl -s -o /dev/null "http://127.0.0.1:$BACKEND_PORT/api/auth/session" && curl -s -o /dev/null "$BASE_URL"; then
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo "Servers never came up — see $SCRATCH_DIR/backend.log and $SCRATCH_DIR/frontend.log" >&2
        exit 1
    fi
    sleep 1
done

echo "==> Capturing screenshots..."
"$PYTHON" "$SCRIPT_DIR/capture.py" --base-url "$BASE_URL" "$@"

echo "==> Done. See docs/images/."
