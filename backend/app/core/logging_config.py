"""Structured (JSON) application logging (security-model.md §8). Stdlib
`logging` only — no new dependency for something this small. One JSON
object per line: timestamp, level, logger name, message, the current
request ID (core/request_context.py), and anything passed via `extra=`.

This is deliberately separate from uvicorn's own access log, which stays
as-is (it logs method/path/status, never headers/bodies, so it's already
outside security-model.md §8's "never logged" list).
"""

import datetime
import json
import logging

from app.core.request_context import get_request_id

# Attributes every stdlib LogRecord already carries — anything else passed
# via `extra=` is application-specific and gets included in the JSON output.
_STANDARD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys()) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.datetime.fromtimestamp(record.created, tz=datetime.UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": get_request_id(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Idempotent — safe to call more than once (e.g. once from app
    startup, once from a test fixture) without stacking duplicate handlers."""
    root = logging.getLogger("relay")
    if root.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"relay.{name}")
