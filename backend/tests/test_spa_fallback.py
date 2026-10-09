from pathlib import Path

import pytest

from app.main import _spa_file


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    static = (tmp_path / "static").resolve()
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>spa</html>")
    (static / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("outside the static dir")
    return static


def test_serves_existing_static_file(static_dir: Path) -> None:
    assert _spa_file(static_dir, "favicon.svg") == static_dir / "favicon.svg"


@pytest.mark.parametrize("full_path", ["", "senders", "senders/42", "assets", "missing.js"])
def test_client_routes_and_non_files_fall_back_to_index(static_dir: Path, full_path: str) -> None:
    assert _spa_file(static_dir, full_path) == static_dir / "index.html"


@pytest.mark.parametrize("full_path", ["../secret.txt", "assets/../../secret.txt", "..\\secret.txt"])
def test_dot_dot_traversal_never_escapes_static_dir(static_dir: Path, full_path: str) -> None:
    """The route's `{full_path:path}` param arrives percent-decoded, so a
    request like `/%2e%2e/secret.txt` or `/..%2fsecret.txt` reaches here
    as a literal `../secret.txt` — it must not be served."""
    assert _spa_file(static_dir, full_path) == static_dir / "index.html"


def test_absolute_path_never_escapes_static_dir(static_dir: Path) -> None:
    """`Path("/static") / "/etc/passwd"` is `/etc/passwd` — a request for
    `//etc/passwd` must not turn into a read of that absolute path."""
    outside = static_dir.parent / "secret.txt"
    assert outside.is_file()
    assert _spa_file(static_dir, str(outside)) == static_dir / "index.html"
