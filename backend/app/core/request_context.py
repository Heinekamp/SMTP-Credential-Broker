"""Per-request correlation ID, threaded through structured log lines
(core/logging_config.py) and audit_log entries (core/audit.py) — the
correlation security-model.md §8 describes ("an admin action ... to the
resulting config_generations row"). A contextvar, not request.state,
because the logging Filter that reads it runs inside the logging module's
own call stack, which doesn't have access to the current Request object.
"""

import contextvars

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)


def set_request_id(request_id: str) -> None:
    _request_id.set(request_id)


def get_request_id() -> str | None:
    return _request_id.get()
