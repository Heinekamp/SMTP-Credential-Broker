from app.core.csrf import csrf_valid, generate_csrf_token


def test_matching_cookie_and_header_is_valid() -> None:
    token = generate_csrf_token()
    assert csrf_valid(token, token) is True


def test_mismatched_values_are_invalid() -> None:
    assert csrf_valid(generate_csrf_token(), generate_csrf_token()) is False


def test_missing_cookie_is_invalid() -> None:
    token = generate_csrf_token()
    assert csrf_valid(None, token) is False


def test_missing_header_is_invalid() -> None:
    token = generate_csrf_token()
    assert csrf_valid(token, None) is False


def test_both_missing_is_invalid() -> None:
    assert csrf_valid(None, None) is False


def test_generated_tokens_are_not_predictable_repeats() -> None:
    assert generate_csrf_token() != generate_csrf_token()
