import pyotp

from app.core.totp import verify_totp

SECRET = pyotp.random_base32()
NOW = 1_800_000_000.0  # a fixed instant, mid-step
STEP = int(NOW // 30)


def _code_for(step: int) -> str:
    return pyotp.TOTP(SECRET).generate_otp(step)


def test_accepts_the_current_step_and_one_either_side_for_clock_drift() -> None:
    for step in (STEP - 1, STEP, STEP + 1):
        assert verify_totp(SECRET, _code_for(step), last_used_step=None, now=NOW) == step
    assert verify_totp(SECRET, _code_for(STEP + 2), last_used_step=None, now=NOW) is None
    assert verify_totp(SECRET, _code_for(STEP - 2), last_used_step=None, now=NOW) is None


def test_a_code_cannot_be_replayed_or_followed_by_an_older_one() -> None:
    """Regression test for #169: valid_window=1 used to accept the same code
    for ~90 seconds, any number of times."""
    assert verify_totp(SECRET, _code_for(STEP), last_used_step=STEP, now=NOW) is None
    assert verify_totp(SECRET, _code_for(STEP - 1), last_used_step=STEP, now=NOW) is None
    assert verify_totp(SECRET, _code_for(STEP + 1), last_used_step=STEP, now=NOW) == STEP + 1


def test_a_wrong_code_is_rejected() -> None:
    accepted = {_code_for(step) for step in (STEP - 1, STEP, STEP + 1)}
    wrong = next(c for c in ("000000", "111111", "222222", "333333") if c not in accepted)
    assert verify_totp(SECRET, wrong, last_used_step=None, now=NOW) is None
