import base64

import pytest

from app.config import get_settings
from app.core.encryption import (
    DecryptionFailed,
    EncryptionKeyNotConfigured,
    decrypt_secret,
    encrypt_secret,
)


def test_round_trip() -> None:
    ciphertext = encrypt_secret("hunter2")
    assert decrypt_secret(ciphertext) == "hunter2"


def test_ciphertext_is_not_plaintext() -> None:
    ciphertext = encrypt_secret("hunter2")
    assert b"hunter2" not in ciphertext


def test_two_encryptions_of_same_plaintext_differ() -> None:
    # Fresh random nonce per call — equal inputs must not produce
    # byte-identical ciphertext.
    assert encrypt_secret("hunter2") != encrypt_secret("hunter2")


def test_tampered_ciphertext_fails_to_decrypt() -> None:
    ciphertext = bytearray(encrypt_secret("hunter2"))
    ciphertext[-1] ^= 0xFF  # flip a bit in the GCM tag/ciphertext
    with pytest.raises(DecryptionFailed):
        decrypt_secret(bytes(ciphertext))


def test_missing_key_raises_configured_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RELAY_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("RELAY_ENCRYPTION_KEY_FILE", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(EncryptionKeyNotConfigured):
            encrypt_secret("hunter2")
    finally:
        get_settings.cache_clear()


def test_wrong_length_key_raises_configured_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RELAY_ENCRYPTION_KEY", base64.b64encode(b"too-short").decode())
    get_settings.cache_clear()
    try:
        with pytest.raises(EncryptionKeyNotConfigured):
            encrypt_secret("hunter2")
    finally:
        get_settings.cache_clear()


def test_decrypting_under_a_different_key_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    ciphertext = encrypt_secret("hunter2")
    monkeypatch.setenv("RELAY_ENCRYPTION_KEY", base64.b64encode(b"1" * 32).decode())
    get_settings.cache_clear()
    try:
        with pytest.raises(DecryptionFailed):
            decrypt_secret(ciphertext)
    finally:
        get_settings.cache_clear()
