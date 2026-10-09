"""TOTP verification with replay protection (#169).

pyotp's `TOTP.verify(code, valid_window=1)` accepts a code for the
previous, current and next 30-second step, and says nothing about *which*
step matched — so an observed code could be replayed for about 90 seconds.
This returns the matched step instead, and refuses any step at or before
the last one already accepted for that admin."""

import hmac
import time

import pyotp

# One step either side of "now", the same tolerance for clock drift
# valid_window=1 gave before.
_DRIFT_STEPS = 1


def verify_totp(secret: str, code: str, *, last_used_step: int | None, now: float | None = None) -> int | None:
    """The time step `code` is valid for, or None if it matches no step in
    the drift window that's newer than `last_used_step`. The caller stores
    the returned step as the admin's new last_used_step."""
    totp = pyotp.TOTP(secret)
    current = int((time.time() if now is None else now) // totp.interval)
    for step in range(current - _DRIFT_STEPS, current + _DRIFT_STEPS + 1):
        if last_used_step is not None and step <= last_used_step:
            continue
        if hmac.compare_digest(totp.generate_otp(step), code):
            return step
    return None
