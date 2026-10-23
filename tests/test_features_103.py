"""v1.0.3 新增能力：学习资料直链、自定义话题、四级词库、论坛版面与时间筛选。"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from app.timeutil import iso, now_utc

CET4_PATH = Path(__file__).resolve().parent.parent / "app" / "data" / "cet4_words.json"


def test_study_includes_direct_links(auth, monkeypatch):
    from app.services import recs

    monkeypatch.setattr(
        recs,
        "recommend",
        lambda user, refresh=False: {
            "videos": [
                {
                    "kind": "video",
                    "title": "线性代数 期末复习",
                    "url": "https://www.bilibili.com/video/BV1xx411c7mD",
                    "author": "某老师",
                    "count": 1234567,
                    "count_label": "123.5 万次播放",
                }
            ],
            "docs": [
                {
                    "kind": "doc",
                    "title": "线性代数笔记",
                    "url": "https://www.bilibili.com/read/cv123456",
                    "author": "某同学",
                    "count": 4567,
                    "count_label": "4567次浏览",
                }
            ],
            "queries": ["线性代数 期末复习"],
            "mode": "live",
            "note": "测试数据",
        },
    )
    response = auth["client"].get("/api/study")
    assert response.status_code == 200
    live = response.json()["live"]
    assert live["videos"][0]["url"].startswith("https://www.bilibili.com/video/")
    assert live["docs"][0]["count_label"].endswith("次浏览")


def test_news_topic_custom_keywords(auth, monkeypatch):
    from app.services import news

    def fake_bing(topic: str):
        assert topic == "人工智能"
        return [
            {
                "title": "人工智能新进展",
                "url": "https://example.com/ai",
                "summary": "摘要",
                "source": "示例",
                "published_at": iso(now_utc()),
            }
        ]

    monkeypatch.setattr(news, "_fetch_bing_news", fake_bing)
    response = auth["client"].get("/api/news/topic?topic=人工智能")
    assert response.status_code == 200
    payload = response.json()
    assert payload["topic"] == "人工智能"
    assert payload["items"][0]["title"] == "人工智能新进展"

    empty = auth["client"].get("/api/news/topic?topic=")
    assert empty.status_code == 502


def test_plan_word_level_cet4(auth):
    client, headers = auth["client"], auth["headers"]
    plan = client.post(
        "/api/plans",
        json={"title": "四级词汇", "category": "vocab", "word_level": "cet4", "target_count": 5, "unit": "个"},
        headers=headers,
    )
    assert plan.status_code == 201, plan.text
    data = plan.json()
    assert data["word_level"] == "cet4"

    overview = client.get(f"/api/plans/{data['id']}/vocab/overview").json()
    cet4 = json.loads(CET4_PATH.read_text(encoding="utf-8"))
    assert overview["word_level"] == "cet4"
    assert overview["bank_size"] == len(cet4)

    started = client.post(
        f"/api/plans/{data['id']}/vocab/start", json={"size": 5, "mode": "mixed"}, headers=headers
    )
    assert started.status_code == 200, started.text
    bank = {item["word"].lower() for item in cet4}
    assert all(item["word"].lower() in bank for item in started.json()["items"])


def test_forum_boards_and_filters(auth):
    client, headers = auth["client"], auth["headers"]
    boards = client.get("/api/forum/boards").json()["boards"]
    assert len(boards) >= 5
    keys = {board["key"] for board in boards}
    assert {"study", "life", "lost"} <= keys

    created = client.post(
        "/api/forum/posts",
        json={
            "title": "版面测试帖子",
            "body": "这是一条用于测试版面的帖子内容。",
            "tags": ["学习交流"],
            "board": "study",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    post = created.json()["post"]
    assert post["board"] == "study"
    assert post["board_name"] == "学习科研"

    listed = client.get("/api/forum/posts?board=study").json()
    assert any(item["id"] == post["id"] for item in listed["items"])

    other = client.get("/api/forum/posts?board=trade").json()
    assert all(item["id"] != post["id"] for item in other["items"])

    recent = client.get("/api/forum/posts?range=day").json()
    assert any(item["id"] == post["id"] for item in recent["items"])

    invalid = client.get("/api/forum/posts?board=nope")
    assert invalid.status_code == 400


def test_forum_old_posts_fall_back_to_tag_board(auth):
    from app.db import db

    client = auth["client"]
    with db() as conn:
        user_id = conn.execute("SELECT id FROM users LIMIT 1").fetchone()["id"]
        cursor = conn.execute(
            "INSERT INTO posts (author_id, title, body, tags, board, anonymous, status, moderation, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, '', 0, 'visible', '{}', ?, ?)",
            (
                user_id,
                "旧帖子没有版面字段",
                "这是升级前发布的帖子。",
                json.dumps(["学习交流"], ensure_ascii=False),
                iso(now_utc() - timedelta(days=2)),
                iso(now_utc() - timedelta(days=2)),
            ),
        )
        legacy_id = int(cursor.lastrowid)

    listed = client.get("/api/forum/posts?board=study").json()
    item = next(item for item in listed["items"] if item["id"] == legacy_id)
    assert item["board"] == "study"
    assert item["board_name"] == "学习科研"
