from pathlib import Path

import pytest

from app.main import _static_files


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>spa</html>")
    (static / "favicon.svg").write_text("<svg/>")
    (static / "assets" / "index-abc.js").write_text("// js")
    (tmp_path / "secret.txt").write_text("outside the static dir")
    return static


def test_maps_every_static_file_by_its_url_path(static_dir: Path) -> None:
    """Keys are what the route's `{full_path:path}` param looks like for a
    real asset: relative, forward-slashed (even on Windows), no directories."""
    assert _static_files(static_dir) == {
        "index.html": static_dir / "index.html",
        "favicon.svg": static_dir / "favicon.svg",
        "assets/index-abc.js": static_dir / "assets" / "index-abc.js",
    }


@pytest.mark.parametrize("full_path", ["", "senders", "senders/42", "assets", "missing.js"])
def test_client_routes_and_non_files_are_not_served_directly(static_dir: Path, full_path: str) -> None:
    assert full_path not in _static_files(static_dir)


@pytest.mark.parametrize(
    "full_path",
    ["../secret.txt", "assets/../../secret.txt", "..\\secret.txt", "./favicon.svg", "assets/../favicon.svg"],
)
def test_dot_dot_and_unnormalized_paths_never_match(static_dir: Path, full_path: str) -> None:
    """The route's param arrives percent-decoded, so `/%2e%2e/secret.txt`
    or `/..%2fsecret.txt` reaches the lookup as a literal `../secret.txt`.
    Only exact keys match, so it falls back to index.html — even forms
    that would resolve to a real in-dir file are simply not keys."""
    assert full_path not in _static_files(static_dir)


def test_absolute_path_never_matches(static_dir: Path) -> None:
    """A request for `//etc/passwd` arrives as `/etc/passwd`. An exact-key
    lookup can never turn that into a read of the absolute path."""
    outside = static_dir.parent / "secret.txt"
    files = _static_files(static_dir)
    assert str(outside) not in files
    assert outside.as_posix() not in files
    assert outside not in files.values()
