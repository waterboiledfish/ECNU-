from __future__ import annotations

from app.security import anonymous_name, limiter


def test_anonymous_name_stable_within_post():
    first = anonymous_name(1, 42)
    second = anonymous_name(1, 42)
    other_post = anonymous_name(2, 42)
    assert first == second
    assert first != other_post
    assert first.startswith("匿名同学·")


def test_rate_limiter():
    limiter._hits.clear()
    assert limiter.allow("unit-test", 2, 60) is True
    assert limiter.allow("unit-test", 2, 60) is True
    assert limiter.allow("unit-test", 2, 60) is False


def test_media_avatar_not_found(auth):
    response = auth["client"].get("/api/media/avatar/ffffffffffffffffffff.png")
    assert response.status_code == 404


def test_csrf_wrong_token_is_rejected(auth):
    response = auth["client"].patch(
        "/api/profile", json={"bio": "x"}, headers={"X-CSRF-Token": "wrong-token"}
    )
    assert response.status_code == 403


def test_api_responses_disable_cache(auth):
    response = auth["client"].get("/api/auth/me")
    assert response.headers.get("cache-control") == "no-store"


def test_security_headers(client):
    response = client.get("/")
    assert "content-security-policy" in response.headers
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
