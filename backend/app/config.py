from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, sourced from the environment.

    Nothing sensitive here is given a default that would be safe to ship
    unnoticed to production (COOKIE_SECURE defaults True; SECRET-bearing
    settings have no default at all and must be supplied).
    """

    model_config = SettingsConfigDict(env_prefix="RELAY_", extra="ignore")

    database_url: str = "sqlite:///./data/app.db"

    session_ttl_seconds: int = 12 * 60 * 60
    cookie_secure: bool = True

    # Rate limiting thresholds: (failure_count, lockout_seconds) pairs,
    # evaluated in order — the highest threshold met wins.
    rate_limit_thresholds: tuple[tuple[int, int], ...] = (
        (5, 60),
        (10, 5 * 60),
        (15, 15 * 60),
    )
    rate_limit_window_seconds: int = 60 * 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
