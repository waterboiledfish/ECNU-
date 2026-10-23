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


def test_live_queries_use_grade_and_major_when_profile_is_empty():
    from app.services import recs

    queries = recs.queries_for({"courses": [], "directions": [], "major": "软件工程", "grade": "大二"})
    assert len(queries) == 2
    assert "软件工程" in queries[0]
    assert queries[1].startswith("大二")


def test_live_queries_keep_courses_first():
    from app.services import recs

    queries = recs.queries_for(
        {"courses": ["机器学习", "数据库"], "directions": [], "major": "计算机", "grade": "大三"}
    )
    assert queries == ["机器学习 期末复习", "数据库 期末复习"]


def test_live_results_reuse_last_success_when_blocked(client, monkeypatch):
    from app.services import recs

    user = {"courses": ["机器学习"], "directions": [], "major": "", "grade": ""}
    queries = recs.queries_for(user)
    key = "study-live:" + "|".join(queries)
    cached_payload = {
        "videos": [
            {
                "kind": "video",
                "title": "上次抓到的视频",
                "url": "https://www.bilibili.com/video/BV1xx411c7mD",
                "author": "UP",
                "count": 10,
                "count_label": "10次播放",
            }
        ],
        "docs": [],
        "queries": queries,
        "searches": [],
        "blocked": False,
        "mode": "live",
        "generated_at": "2026-10-20T00:00:00+00:00",
        "note": "",
    }
    recs.cache.set(key, cached_payload)

    def blocked(*args, **kwargs):
        raise recs.BiliBlocked("412 risk control")

    monkeypatch.setattr(recs, "_search", blocked)
    recs._COOLDOWN["until"] = 0.0
    payload = recs.recommend(user, refresh=True)
    assert payload["stale"] is True
    assert payload["cached"] is True
    assert payload["videos"][0]["title"] == "上次抓到的视频"
    assert "风控" in payload["note"]
