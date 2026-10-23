"""官网文件手动导入与官网目录：只覆盖不触网的校验、权限与目录用例。"""
from __future__ import annotations


def test_import_requires_auth(client):
    # 写接口先过 CSRF/同源校验，未登录同样是 403（拿不到令牌）。
    response = client.post("/api/sources/import", json={"url": "https://www.ecnu.edu.cn/notice.pdf"})
    assert response.status_code == 403
    assert client.get("/api/sources").status_code == 401


def test_import_rejects_bad_scheme(auth):
    response = auth["client"].post(
        "/api/sources/import",
        json={"url": "ftp://www.ecnu.edu.cn/notice.pdf"},
        headers=auth["headers"],
    )
    assert response.status_code == 400
    assert "http" in response.json()["detail"]


def test_import_rejects_non_ecnu_host(auth):
    response = auth["client"].post(
        "/api/sources/import",
        json={"url": "https://example.com/notice.pdf"},
        headers=auth["headers"],
    )
    assert response.status_code == 400
    assert "白名单" in response.json()["detail"]


def test_import_requires_permission(auth, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "allow_user_crawl", False)
    response = auth["client"].post(
        "/api/sources/import",
        json={"url": "https://www.ecnu.edu.cn/notice.pdf"},
        headers=auth["headers"],
    )
    assert response.status_code == 403


def test_import_rejects_too_short_url(auth):
    response = auth["client"].post(
        "/api/sources/import", json={"url": "x"}, headers=auth["headers"]
    )
    assert response.status_code == 422


def test_official_site_catalog(auth):
    payload = auth["client"].get("/api/sources").json()
    sites = payload["sites"]
    assert len(sites) >= 40, "官网入口应包含整理后的 40+ 个站点"
    hosts = {site["url"] for site in sites}
    assert any("ecnu.edu.cn" in url for url in hosts)
    categories = {site["category"] for site in sites}
    assert "学校门户" in categories
    assert any("教务" in name or "培养" in name for name in categories)
