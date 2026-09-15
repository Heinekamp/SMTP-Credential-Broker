import base64
import os
import tempfile
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

if "RELAY_DATABASE_URL" not in os.environ:
    # A real (temp-file) SQLite DB, not `:memory:` — the shared, global
    # app.db.session engine (used directly by CLI commands and background
    # scheduler tick functions under test, not the per-test db_session
    # fixture below) must be reachable from a different OS thread than the
    # one that created its schema, since scheduler ticks now run their
    # blocking work via asyncio.to_thread (core/scheduler.py). SQLAlchemy's
    # default pool for a `:memory:` URL is SingletonThreadPool, which hands
    # each thread its own separate, empty in-memory database — a tick
    # running in a worker thread would see "no such table" for schema
    # created on the main thread. A real file has no such per-thread
    # isolation, matching how a real (non-`:memory:`) deployment behaves.
    _shared_db_fd, _shared_db_path = tempfile.mkstemp(suffix=".db")
    os.close(_shared_db_fd)
    os.environ["RELAY_DATABASE_URL"] = f"sqlite:///{_shared_db_path}"
os.environ.setdefault("RELAY_COOKIE_SECURE", "false")
# A fixed, obviously-fake key so upstream-account encryption tests don't
# need a real secret configured. Individual tests that need to exercise
# EncryptionKeyNotConfigured clear this env var themselves.
os.environ.setdefault("RELAY_ENCRYPTION_KEY", base64.b64encode(b"0" * 32).decode())
# The scheduler (core/scheduler.py) opens its own SessionLocal() against
# the real app.db.session engine, not the per-test tempfile db_session
# fixture below — without this, every TestClient's lifespan would spin up
# real background tasks against a schema-less :memory: database.
os.environ.setdefault("RELAY_SCHEDULER_ENABLED", "false")

import app.models  # noqa: F401,E402
from app.api.deps import get_db  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        os.remove(path)


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "correct horse battery staple"


@pytest.fixture()
def admin_client(client: TestClient, db_session: Session) -> TestClient:
    """A TestClient already logged in as a real admin — for tests of
    endpoints that require auth (everything past Stage 1) rather than
    re-deriving the login dance in every test module."""
    from app.core.security import hash_password
    from app.models.admin import AdminUser

    db_session.add(AdminUser(email=ADMIN_EMAIL, password_hash=hash_password(ADMIN_PASSWORD)))
    db_session.commit()

    response = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert response.status_code == 200
    return client


def csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get("csrf_token")
    assert token, "no csrf_token cookie set — was the client logged in first?"
    return {"x-csrf-token": token}


@pytest.fixture()
def fake_postfix_control(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """Local SMTP user routes call app.core.postfix_control's sasl_*
    functions, which normally talk to a real Unix socket inside the
    postfix container (security-model.md §6). Route-level tests don't
    stand up a real control surface — they patch these two functions and
    record calls, the same way test_upstream_accounts_routes.py patches
    test_upstream_connection. The wire protocol itself is exercised
    separately in test_postfix_control.py."""
    calls: list[tuple] = []
    monkeypatch.setattr(
        "app.core.postfix_control.sasl_set_user",
        lambda username, password: calls.append(("set", username, password)),
    )
    monkeypatch.setattr(
        "app.core.postfix_control.sasl_delete_user",
        lambda username: calls.append(("delete", username)),
    )
    return calls
