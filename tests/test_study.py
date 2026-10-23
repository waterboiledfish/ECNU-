from __future__ import annotations

from app.services import study


def _user():
    return {
        "id": 1,
        "grade": "大三",
        "major": "计算机科学与技术",
        "courses": ["机器学习", "数据库"],
        "directions": [],
    }


def test_platform_urls():
    assert study.platform_url("bilibili", "机器学习 期末复习").startswith("https://search.bilibili.com/")
    assert "douyin.com/search/" in study.platform_url("douyin", "机器学习")
    assert "zhihu.com/search" in study.platform_url("zhihu", "机器学习")
    assert "theses" not in study.platform_url("bilibili", "x")


def test_recommend_local(client):
    payload = study.recommend(_user(), refresh=True)
    assert payload["mode"] in {"local", "local-fallback"}
    assert len(payload["items"]) >= 5
    platforms = {item["platform"] for item in payload["items"]}
    assert "bilibili" in platforms
    assert all(item["url"].startswith("https://") for item in payload["items"])
    cached = study.recommend(_user())
    assert cached["cached"] is True


def test_recommend_ai(client, monkeypatch):
    from app.services import llm

    def fake_chat(messages, **kwargs):
        return (
            '[{"platform":"bilibili","title":"机器学习速成","query":"机器学习 速成","reason":"快速建立框架"},'
            '{"platform":"zhihu","title":"数据库怎么复习","query":"数据库 复习","reason":"经验帖"},'
            '{"platform":"arxiv","title":"方向论文","query":"machine learning","reason":"前沿"}]'
        )

    monkeypatch.setattr(llm, "chat", fake_chat)
    payload = study.recommend(_user(), {"key": "sk-test-123456789", "model": "m", "base_url": None}, refresh=True)
    assert payload["mode"] == "ai"
    assert len(payload["items"]) == 3
    assert payload["items"][0]["platform_label"] == "Bilibili"


def test_invalid_ai_platform_falls_back(client, monkeypatch):
    from app.services import llm

    monkeypatch.setattr(
        llm,
        "chat",
        lambda messages, **kwargs: '[{"platform":"weibo","title":"x","query":"y","reason":"z"}]',
    )
    payload = study.recommend(_user(), {"key": "sk-test-123456789", "model": "m", "base_url": None}, refresh=True)
    assert payload["mode"] == "local-fallback"
    assert all(item["platform"] != "weibo" for item in payload["items"])
