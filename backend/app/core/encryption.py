import base64
import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

_NONCE_SIZE = 12  # 96-bit, the standard/recommended nonce size for AES-GCM


class EncryptionKeyNotConfigured(RuntimeError):
    """RELAY_ENCRYPTION_KEY / RELAY_ENCRYPTION_KEY_FILE is missing or
    malformed. Raised instead of falling back to any default — a
    recoverable default would defeat the point of encrypting the secret at
    all (security-model.md §2)."""


class DecryptionFailed(RuntimeError):
    """Ciphertext failed GCM's authentication check — either corrupted, or
    encrypted under a different key (e.g. after a key rotation that didn't
    re-encrypt every row). Never silently returns garbage plaintext."""


def _load_key() -> bytes:
    settings = get_settings()
    key_b64: str | None = None

    if settings.encryption_key_file:
        path = Path(settings.encryption_key_file)
        if path.is_file():
            key_b64 = path.read_text(encoding="utf-8").strip()

    if not key_b64:
        key_b64 = settings.encryption_key

    if not key_b64:
        raise EncryptionKeyNotConfigured(
            "No encryption key configured. Set RELAY_ENCRYPTION_KEY (or "
            "RELAY_ENCRYPTION_KEY_FILE) to a base64-encoded 32-byte key — "
            "see `relay generate-encryption-key`."
        )

    try:
        key = base64.b64decode(key_b64, validate=True)
    except Exception as exc:
        raise EncryptionKeyNotConfigured("RELAY_ENCRYPTION_KEY is not valid base64.") from exc

    if len(key) != 32:
        raise EncryptionKeyNotConfigured(
            f"RELAY_ENCRYPTION_KEY must decode to exactly 32 bytes (AES-256); got {len(key)}."
        )
    return key


def is_encryption_key_configured() -> bool:
    """For the Settings System tab (never the key's value, just whether one
    resolves) — reuses `_load_key`'s exact loading/validation logic rather
    than re-checking `RELAY_ENCRYPTION_KEY`/`_FILE` a second way."""
    try:
        _load_key()
    except EncryptionKeyNotConfigured:
        return False
    return True


def encrypt_with_key(plaintext: str, key: bytes) -> bytes:
    """Encrypts with AES-256-GCM under an explicitly supplied key. Output
    layout: 12-byte nonce || ciphertext (GCM's authentication tag is
    appended to the ciphertext automatically by this library). A fresh
    random nonce is generated per call — nonces must never repeat under
    the same key. `encrypt_secret` (below) is the normal call path; this
    is what `relay rotate-encryption-key` uses directly with an old/new
    key pair that was never loaded from Settings."""
    nonce = os.urandom(_NONCE_SIZE)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return nonce + ciphertext


def decrypt_with_key(blob: bytes, key: bytes) -> str:
    nonce, ciphertext = blob[:_NONCE_SIZE], blob[_NONCE_SIZE:]
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    except InvalidTag as exc:
        raise DecryptionFailed(
            "Ciphertext failed authentication — wrong key or corrupted data."
        ) from exc
    return plaintext.decode("utf-8")


def encrypt_secret(plaintext: str) -> bytes:
    return encrypt_with_key(plaintext, _load_key())


def decrypt_secret(blob: bytes) -> str:
    return decrypt_with_key(blob, _load_key())


def parse_key_file(path: Path) -> bytes:
    """Reads and validates a base64-encoded 32-byte key from a file — the
    same format `_load_key` expects from `RELAY_ENCRYPTION_KEY_FILE`, used
    directly by `relay rotate-encryption-key`'s `--old-key-file`/
    `--new-key-file` (security-model.md §2), which never touches
    `RELAY_ENCRYPTION_KEY` itself."""
    key_b64 = path.read_text(encoding="utf-8").strip()
    try:
        key = base64.b64decode(key_b64, validate=True)
    except Exception as exc:
        raise EncryptionKeyNotConfigured(f"{path} is not valid base64.") from exc
    if len(key) != 32:
        raise EncryptionKeyNotConfigured(f"{path} must decode to exactly 32 bytes (AES-256); got {len(key)}.")
    return key
