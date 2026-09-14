import base64
import os
import tempfile
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("RELAY_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("RELAY_COOKIE_SECURE", "false")
# A fixed, obviously-fake key so upstream-account encryption tests don't
# need a real secret configured. Individual tests that need to exercise
# EncryptionKeyNotConfigured clear this env var themselves.
os.environ.setdefault("RELAY_ENCRYPTION_KEY", base64.b64encode(b"0" * 32).decode())

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
