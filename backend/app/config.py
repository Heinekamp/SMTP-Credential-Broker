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

    # AES-256-GCM key for upstream account passwords (security-model.md §2),
    # base64-encoded, decoding to exactly 32 bytes. Never stored in the
    # database. `encryption_key_file` (a Docker secret path) takes
    # precedence over the plain env var when both are set — a mounted
    # secret file doesn't show up in `docker inspect` the way an env var
    # does.
    encryption_key: str | None = None
    encryption_key_file: str | None = None

    # Unix domain socket for the Postfix container's control surface
    # (security-model.md §6) — the only channel `app` uses to mutate
    # sasldb2 or install generated Postfix config. Never a network socket.
    postfix_control_socket: str = "/shared-config/control.sock"
    postfix_control_timeout: float = 15.0
    # apply_config's own worst case is stop-then-start, each up to
    # control_surface.py's own 30s subprocess timeout — up to ~60s total
    # for a slow-but-successful reload. postfix_control_timeout alone used
    # to also gate this call and would time out first, misreporting a
    # successful-but-slow reload as "control surface unreachable" (no
    # ConfigGeneration row recorded, checksum bookkeeping left out of sync
    # with Postfix's real state). Comfortably above that 60s worst case.
    postfix_control_apply_timeout: float = 75.0

    # What local SMTP users are told to configure their services with
    # (the "Connection Details" view, claude-design-prompt.md's Local SMTP
    # Users screen) — this relay's own submission endpoint, not anything
    # upstream-provider-related.
    submission_host: str = "smtp-relay.internal"
    submission_port: int = 587

    # Runs the background scheduler (core/scheduler.py — scheduled
    # connection tests, update checks, alert email) as part of the app's
    # lifespan. Tests set this false so a TestClient's lifespan doesn't
    # spin up real periodic tasks against a schema-less in-memory DB.
    scheduler_enabled: bool = True

    # Deliberately a deploy-time env var, not a RelaySettings DB field an
    # admin could toggle from the UI — a UI toggle risks a production
    # relay being silently left pinned to Let's Encrypt's staging
    # directory (untrusted certs). Override only for manual verification
    # against staging (core/acme_tls.py).
    acme_directory_url: str = "https://acme-v02.api.letsencrypt.org/directory"


@lru_cache
def get_settings() -> Settings:
    return Settings()
