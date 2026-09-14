from app.core.password_generation import generate_password


def test_default_length() -> None:
    assert len(generate_password()) == 24


def test_custom_length() -> None:
    assert len(generate_password(12)) == 12


def test_two_calls_differ() -> None:
    assert generate_password() != generate_password()


def test_alphabet_is_alnum_only() -> None:
    password = generate_password(200)
    assert password.isalnum()
