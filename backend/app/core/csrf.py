import hmac
import secrets

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "x-csrf-token"


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_valid(cookie_value: str | None, header_value: str | None) -> bool:
    """Double-submit check: the value the server set as a (non-HttpOnly)
    cookie must come back verbatim in a custom request header. A
    same-origin XHR/fetch is the only thing that can read the cookie and
    attach the header; a cross-site form post cannot (security-model.md
    §5)."""
    if not cookie_value or not header_value:
        return False
    return hmac.compare_digest(cookie_value, header_value)
