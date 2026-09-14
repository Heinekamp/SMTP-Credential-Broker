import json
import logging

from fastapi.testclient import TestClient

from app.core.logging_config import JsonFormatter, configure_logging
from app.core.request_context import get_request_id, set_request_id


def test_json_formatter_produces_valid_json_with_expected_fields() -> None:
    record = logging.LogRecord(
        name="relay.test", level=logging.INFO, pathname=__file__, lineno=1, msg="hello", args=(), exc_info=None
    )
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "relay.test"
    assert "timestamp" in payload


def test_json_formatter_includes_request_id_when_set() -> None:
    set_request_id("test-request-id-123")
    record = logging.LogRecord(
        name="relay.test", level=logging.INFO, pathname=__file__, lineno=1, msg="hello", args=(), exc_info=None
    )
    payload = json.loads(JsonFormatter().format(record))
    assert payload["request_id"] == "test-request-id-123"


def test_json_formatter_includes_extra_fields() -> None:
    logger = logging.getLogger("relay.test.extra")
    record = logger.makeRecord(
        "relay.test.extra", logging.INFO, __file__, 1, "hello", (), None, extra={"action": "widget.create"}
    )
    payload = json.loads(JsonFormatter().format(record))
    assert payload["action"] == "widget.create"


def test_configure_logging_is_idempotent() -> None:
    configure_logging()
    handler_count = len(logging.getLogger("relay").handlers)
    configure_logging()
    assert len(logging.getLogger("relay").handlers) == handler_count


def test_response_carries_a_request_id_header(client: TestClient) -> None:
    response = client.get("/api/health")
    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) > 0


def test_each_request_gets_a_distinct_request_id(client: TestClient) -> None:
    first = client.get("/api/health").headers["X-Request-ID"]
    second = client.get("/api/health").headers["X-Request-ID"]
    assert first != second


def test_get_request_id_reflects_the_current_context() -> None:
    set_request_id("abc-123")
    assert get_request_id() == "abc-123"
