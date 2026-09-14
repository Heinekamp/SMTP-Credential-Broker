import subprocess
import time
from collections.abc import Generator

import httpx
import pytest

COMPOSE_FILE = "integration/docker-compose.test.yml"
APP_URL = "http://localhost:8000"
STUB_INSPECT_URL = "http://localhost:2526"
ADMIN_EMAIL = "admin@integration.test"
ADMIN_PASSWORD = "Integration-Test-Passw0rd!"


def _compose_exec(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", "-f", COMPOSE_FILE, "exec", "-T", *args],
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="session", autouse=True)
def _wait_for_app() -> None:
    """Assumes `docker compose -f integration/docker-compose.test.yml up
    -d --build` has already been run — see integration/README.md. This
    harness does not start Compose itself, so a failure here almost always
    means that step was skipped."""
    deadline = time.time() + 120
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            if httpx.get(f"{APP_URL}/api/health", timeout=2).status_code == 200:
                return
        except httpx.TransportError as exc:
            last_error = exc
        time.sleep(2)
    pytest.fail(f"app never became healthy within 120s (last error: {last_error})")


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_admin(_wait_for_app: None) -> None:
    # No "Initial Setup" UI/API exists yet (Stage 1's documented gap) — the
    # CLI is the only bootstrap path. Idempotent: a second run's "already
    # exists" failure is expected and ignored.
    _compose_exec("app", "relay", "create-admin", "--email", ADMIN_EMAIL, "--password", ADMIN_PASSWORD)


@pytest.fixture()
def api() -> Generator[httpx.Client, None, None]:
    client = httpx.Client(base_url=APP_URL, timeout=10.0)
    response = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    response.raise_for_status()
    client.headers["x-csrf-token"] = client.cookies["csrf_token"]
    yield client
    client.close()


@pytest.fixture()
def stub() -> Generator[None, None, None]:
    """Clears the upstream stub's recorded deliveries before the test and
    leaves the client able to read them afterward via stub_deliveries()."""
    httpx.delete(f"{STUB_INSPECT_URL}/deliveries", timeout=5)
    yield


def stub_deliveries() -> list[dict]:
    return httpx.get(f"{STUB_INSPECT_URL}/deliveries", timeout=5).json()


def create_upstream_account(api: httpx.Client, *, name: str, username: str, password: str) -> int:
    response = api.post(
        "/api/upstream-accounts",
        json={
            "name": name,
            "host": "upstream-stub",  # Docker Compose service name, resolved from inside the postfix container
            "port": 2525,
            "tls_mode": "starttls",
            "username": username,
            "password": password,
        },
    )
    response.raise_for_status()
    return response.json()["id"]


def create_sender(api: httpx.Client, *, address: str, upstream_account_id: int) -> int:
    response = api.post("/api/senders", json={"address": address, "upstream_account_id": upstream_account_id})
    response.raise_for_status()
    return response.json()["id"]


def create_local_user(api: httpx.Client, *, name: str, username: str) -> tuple[int, str]:
    response = api.post("/api/local-users", json={"name": name, "username": username})
    response.raise_for_status()
    body = response.json()
    return body["user"]["id"], body["password"]


def grant(api: httpx.Client, *, user_id: int, sender_id: int) -> None:
    response = api.put(f"/api/local-users/{user_id}/permissions/{sender_id}")
    response.raise_for_status()


def push_config(api: httpx.Client) -> dict:
    response = api.post("/api/config/generate")
    response.raise_for_status()
    body = response.json()
    assert body["success"], f"config generation failed: {body}"
    return body
