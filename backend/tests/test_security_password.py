from app.core.security import hash_password, verify_password


def test_hash_is_not_plaintext() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert hashed.startswith("$argon2id$")


def test_verify_correct_password() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password(hashed, "correct horse battery staple") is True


def test_verify_wrong_password() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password(hashed, "wrong password") is False


def test_verify_against_garbage_hash_does_not_raise() -> None:
    assert verify_password("not-a-real-hash", "anything") is False


def test_two_hashes_of_same_password_differ() -> None:
    # Argon2 salts each hash independently — equal inputs must not produce
    # byte-identical hashes (would leak "these two accounts share a
    # password" from the database alone).
    assert hash_password("same-password") != hash_password("same-password")
