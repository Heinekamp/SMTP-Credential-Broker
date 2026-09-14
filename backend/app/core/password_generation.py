import secrets
import string

_ALPHABET = string.ascii_letters + string.digits
_DEFAULT_LENGTH = 24  # ~142 bits of entropy from a 62-char alphabet


def generate_password(length: int = _DEFAULT_LENGTH) -> str:
    """Local SMTP user credentials — generated, never chosen. `secrets`
    (not `random`) is a CSPRNG, appropriate for anything used as an
    authentication credential."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))
