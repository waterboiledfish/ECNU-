from __future__ import annotations

from conftest import login


def test_health_is_public(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_meta_is_public(client):
    response = client.get("/api/meta")
    assert response.status_code == 200
    body = response.json()
    assert body["app"]["name"] == "ECNU 小助手"
    assert body["auth"]["mode"] == "dev"
    assert any(item["key"] == "tech" for item in body["news_categories"])
    assert len(body["providers"]) >= 3


def test_me_unauthenticated(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["authenticated"] is False


def test_dev_login_sets_hardened_cookie(client):
    response = client.post("/api/auth/dev-login", json={"nickname": "林同学"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["authenticated"] is True
    assert payload["user"]["nickname"] == "林同学"
    assert payload["csrf"]
    cookie = response.headers.get("set-cookie", "").lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert client.get("/api/auth/me").json()["authenticated"] is True


def test_mutating_requests_require_csrf(client):
    login(client)
    response = client.patch("/api/profile", json={"bio": "没有 csrf"})
    assert response.status_code == 403


def test_cross_origin_request_is_rejected(client):
    data, headers = login(client)
    response = client.patch(
        "/api/profile",
        json={"bio": "跨站"},
        headers={**headers, "Origin": "https://evil.example.com"},
    )
    assert response.status_code == 403


def test_logout_revokes_session(client):
    data, headers = login(client)
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/auth/me").json()["authenticated"] is False


def test_profile_requires_auth(client):
    response = client.get("/api/profile")
    assert response.status_code == 401


def test_admin_requires_admin(auth):
    response = auth["client"].get("/api/admin/overview")
    assert response.status_code == 403
