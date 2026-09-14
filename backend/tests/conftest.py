import os
import tempfile
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("RELAY_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("RELAY_COOKIE_SECURE", "false")

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
