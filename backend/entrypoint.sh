#!/bin/sh
set -e

alembic upgrade head

# Best-effort: on a fresh `docker compose up`, the postfix container's
# control surface may not be listening yet even though `depends_on` says
# the container has started (that only waits for the container, not the
# socket inside it). Retry briefly, then start the API regardless —
# `relay generate-config` (or the Settings UI) can always be run again
# later, and this must never block the application from coming up.
attempt=1
while [ "$attempt" -le 5 ]; do
    if relay generate-config; then
        break
    fi
    echo "relay generate-config attempt $attempt failed, retrying..." >&2
    attempt=$((attempt + 1))
    sleep 3
done

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
