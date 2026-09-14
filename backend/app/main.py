from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import auth, config, health, local_users, senders, upstream_accounts

app = FastAPI(title="Managed SMTP Relay")

app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(upstream_accounts.router, prefix="/api")
app.include_router(senders.router, prefix="/api")
app.include_router(local_users.router, prefix="/api")
app.include_router(config.router, prefix="/api")

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
