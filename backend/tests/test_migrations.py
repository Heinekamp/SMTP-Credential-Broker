import os
import tempfile
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _alembic_config(db_path: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    os.environ["RELAY_DATABASE_URL"] = f"sqlite:///{db_path}"
    # get_settings() is lru_cache'd and very likely already called (and
    # cached) by an earlier test importing app.main — without clearing it,
    # alembic/env.py would silently keep using whatever URL was cached
    # first instead of this test's temp file.
    get_settings.cache_clear()
    return cfg


def test_upgrade_downgrade_upgrade_round_trip() -> None:
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(db_path)  # alembic/sqlite creates it fresh
    try:
        cfg = _alembic_config(db_path)
        command.upgrade(cfg, "head")
        assert Path(db_path).exists()

        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
    finally:
        os.environ["RELAY_DATABASE_URL"] = "sqlite:///:memory:"
        get_settings.cache_clear()
        if os.path.exists(db_path):
            os.remove(db_path)
