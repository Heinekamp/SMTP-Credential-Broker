import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.routes import (
    admins,
    alerts,
    audit_log,
    auth,
    config,
    health,
    local_users,
    mail_log,
    notification_settings,
    queue,
    senders,
    system,
    upstream_accounts,
)
from app.config import get_settings
from app.core.alert_email import alert_email_tick
from app.core.logging_config import configure_logging
from app.core.request_context import set_request_id
from app.core.retention import retention_cleanup_tick
from app.core.scheduled_tests import connection_test_tick
from app.core.scheduler import run_periodic
from app.core.update_check import update_check_tick

configure_logging()

# Real background work polls every 60s; each tick() decides for itself
# whether enough time has actually elapsed to do anything (settings_store-
# backed), so this interval is just how quickly an admin-edited setting
# takes effect, not how often real work happens.
_POLL_SECONDS = 60


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    tasks: list[asyncio.Task] = []
    if get_settings().scheduler_enabled:
        tasks = [
            asyncio.create_task(run_periodic("connection_test", _POLL_SECONDS, connection_test_tick)),
            asyncio.create_task(run_periodic("update_check", _POLL_SECONDS, update_check_tick)),
            asyncio.create_task(run_periodic("alert_email", _POLL_SECONDS, alert_email_tick)),
            asyncio.create_task(run_periodic("retention_cleanup", _POLL_SECONDS, retention_cleanup_tick)),
        ]
    yield
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="Managed SMTP Relay", lifespan=lifespan)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next) -> Response:
    """Generates one correlation ID per request, threaded through
    structured log lines and audit_log entries (security-model.md §8) via
    core/request_context.py, and echoed back as a response header so a
    client-reported issue can be traced to its exact log lines."""
    request_id = str(uuid.uuid4())
    set_request_id(request_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(upstream_accounts.router, prefix="/api")
app.include_router(senders.router, prefix="/api")
app.include_router(local_users.router, prefix="/api")
app.include_router(config.router, prefix="/api")
app.include_router(mail_log.router, prefix="/api")
app.include_router(audit_log.router, prefix="/api")
app.include_router(queue.router, prefix="/api")
app.include_router(admins.router, prefix="/api")
app.include_router(system.router, prefix="/api")
app.include_router(alerts.router, prefix="/api")
app.include_router(notification_settings.router, prefix="/api")

_STATIC_DIR = Path(__file__).resolve().parent / "static"

if _STATIC_DIR.is_dir():
    # Serve the built frontend. A plain StaticFiles(html=True) mount alone
    # 404s on a hard refresh of a client-side route like /senders, so any
    # path that isn't a static asset falls back to index.html and lets
    # react-router take over (architecture.md §6's Docker topology assumes
    # this — the "app" container serves both the API and the SPA).
    app.mount("/assets", StaticFiles(directory=_STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str) -> FileResponse:
        candidate = _STATIC_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_STATIC_DIR / "index.html")
