from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from tests.conftest import csrf_headers


def test_get_branding_is_public(client: TestClient) -> None:
    response = client.get("/api/branding")
    assert response.status_code == 200
    body = response.json()
    assert body["accent_color"] is None
    assert body["has_custom_logo"] is False


def test_get_favicon_is_public_and_falls_back_to_the_bundled_default(client: TestClient) -> None:
    response = client.get("/api/branding/favicon")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


def test_get_logo_is_404_when_none_is_configured(client: TestClient) -> None:
    assert client.get("/api/branding/logo").status_code == 404


def test_patch_requires_authentication(admin_client: TestClient) -> None:
    """A CSRF token alone isn't enough — the session must belong to a
    real admin. The unauthenticated `client` fixture has no CSRF cookie
    either, so that case is covered by the plain 403 CSRF check instead."""
    admin_client.cookies.delete("session")
    response = admin_client.patch(
        "/api/branding", json={"accent_color": "#3b82f6"}, headers=csrf_headers(admin_client)
    )
    assert response.status_code == 401


def test_patch_sets_and_clears_the_accent_color(admin_client: TestClient) -> None:
    response = admin_client.patch(
        "/api/branding", json={"accent_color": "#3b82f6"}, headers=csrf_headers(admin_client)
    )
    assert response.status_code == 200
    assert response.json()["accent_color"] == "#3b82f6"

    response = admin_client.patch("/api/branding", json={"accent_color": None}, headers=csrf_headers(admin_client))
    assert response.json()["accent_color"] is None


def test_patch_rejects_a_non_hex_accent_color(admin_client: TestClient) -> None:
    response = admin_client.patch(
        "/api/branding", json={"accent_color": "blue"}, headers=csrf_headers(admin_client)
    )
    assert response.status_code == 422


def test_patch_is_audited(admin_client: TestClient, db_session: Session) -> None:
    admin_client.patch("/api/branding", json={"accent_color": "#72bf44"}, headers=csrf_headers(admin_client))
    entry = db_session.query(AuditLog).filter(AuditLog.action == "branding.update").one()
    assert entry.detail == {"fields": ["accent_color"]}


def test_upload_logo_requires_authentication(admin_client: TestClient) -> None:
    admin_client.cookies.delete("session")
    response = admin_client.post(
        "/api/branding/logo",
        files={"file": ("logo.png", b"fake-bytes", "image/png")},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 401


def test_upload_logo_requires_csrf(admin_client: TestClient) -> None:
    response = admin_client.post("/api/branding/logo", files={"file": ("logo.png", b"fake-bytes", "image/png")})
    assert response.status_code == 403


def test_upload_logo_rejects_a_disallowed_content_type(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/branding/logo",
        files={"file": ("logo.gif", b"fake-bytes", "image/gif")},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 422


def test_upload_logo_rejects_an_oversized_file(admin_client: TestClient) -> None:
    oversized = b"x" * (512 * 1024 + 1)
    response = admin_client.post(
        "/api/branding/logo",
        files={"file": ("logo.png", oversized, "image/png")},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 422


_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"rest-of-a-png"
_SVG_WITH_SCRIPT = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><script>alert(2)</script></svg>'


def test_upload_get_and_delete_logo_round_trip(admin_client: TestClient) -> None:
    upload = admin_client.post(
        "/api/branding/logo",
        files={"file": ("logo.png", _PNG_BYTES, "image/png")},
        headers=csrf_headers(admin_client),
    )
    assert upload.status_code == 200
    assert upload.json()["has_custom_logo"] is True

    get = admin_client.get("/api/branding/logo")
    assert get.status_code == 200
    assert get.content == _PNG_BYTES
    assert get.headers["content-type"] == "image/png"

    favicon = admin_client.get("/api/branding/favicon")
    assert favicon.content == _PNG_BYTES

    delete = admin_client.delete("/api/branding/logo", headers=csrf_headers(admin_client))
    assert delete.status_code == 200
    assert delete.json()["has_custom_logo"] is False
    assert admin_client.get("/api/branding/logo").status_code == 404


def test_upload_logo_rejects_bytes_that_dont_match_the_declared_type(admin_client: TestClient) -> None:
    """Regression test for #155: the declared Content-Type is just a header
    the uploader picked. An SVG (or HTML) document declared as image/png
    must not be stored and served back under that label."""
    response = admin_client.post(
        "/api/branding/logo",
        files={"file": ("logo.png", _SVG_WITH_SCRIPT, "image/png")},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 422


def test_svg_logo_is_served_sandboxed_so_its_scripts_never_run(admin_client: TestClient) -> None:
    """Regression test for #155: the logo/favicon GETs are public, and opening
    one directly renders an SVG as a document on this origin. Its scripts
    must be blocked by a sandboxing CSP, and the type must not be sniffed."""
    upload = admin_client.post(
        "/api/branding/logo",
        files={"file": ("logo.svg", _SVG_WITH_SCRIPT, "image/svg+xml")},
        headers=csrf_headers(admin_client),
    )
    assert upload.status_code == 200

    for path in ("/api/branding/logo", "/api/branding/favicon"):
        response = admin_client.get(path)
        assert response.headers["content-type"].startswith("image/svg+xml")
        csp = response.headers["content-security-policy"]
        assert "sandbox" in csp
        assert "default-src 'none'" in csp
        assert "script-src" not in csp
        assert response.headers["x-content-type-options"] == "nosniff"


def test_every_response_carries_baseline_security_headers(client: TestClient) -> None:
    response = client.get("/api/branding")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "same-origin"
    csp = response.headers["content-security-policy"]
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_delete_logo_requires_authentication(admin_client: TestClient) -> None:
    admin_client.cookies.delete("session")
    response = admin_client.delete("/api/branding/logo", headers=csrf_headers(admin_client))
    assert response.status_code == 401
