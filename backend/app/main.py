import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.routes import (
    admins,
    auth,
    config,
    health,
    local_users,
    mail_log,
    queue,
    senders,
    system,
    upstream_accounts,
)
from app.core.logging_config import configure_logging
from app.core.request_context import set_request_id

configure_logging()

app = FastAPI(title="Managed SMTP Relay")


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
app.include_router(queue.router, prefix="/api")
app.include_router(admins.router, prefix="/api")
app.include_router(system.router, prefix="/api")

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
