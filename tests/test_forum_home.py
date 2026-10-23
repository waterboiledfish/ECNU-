"""论坛首页：全站公告、轮播、推荐阅读与版面计数。"""
from __future__ import annotations

from app.db import db
from app.services import forum as forum_service


def _promote_admin(auth):
    with db() as conn:
        conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (auth["user"]["id"],))
    auth["user"]["role"] = "admin"


def _create_post(client, headers, title: str, tags: list[str] | None = None, board: str = "") -> dict:
    response = client.post(
        "/api/forum/posts",
        json={
            "title": title,
            "body": "用于检查论坛首页模块的示例正文，包含一些可读内容。",
            "tags": tags or ["经验分享"],
            "board": board,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["post"]


def test_home_returns_default_announcement(auth):
    payload = auth["client"].get("/api/forum/home")
    assert payload.status_code == 200
    data = payload.json()
    assert data["announcement"]["title"] == "全站公告"
    assert data["announcement"]["text"]
    assert data["carousel"] == []
    assert data["recommended"] == []
    assert data["stats"] == {"posts": 0, "today_posts": 0, "comments": 0, "users": 1}


def test_home_carousel_puts_most_discussed_first(auth, second_user):
    _create_post(auth["client"], auth["headers"], "随便聊聊宿舍熄灯时间")
    for index in range(4):
        _create_post(auth["client"], auth["headers"], f"选课经验分享第 {index + 1} 篇")
    hot = _create_post(auth["client"], auth["headers"], "保研经验：大三这一年该怎么准备")

    for _ in range(2):
        second_user["client"].post(f"/api/forum/posts/{hot['id']}/like", headers=second_user["headers"])
    second_user["client"].post(
        f"/api/forum/posts/{hot['id']}/comments",
        json={"body": "写得很详细，谢谢分享。"},
        headers=second_user["headers"],
    )

    data = auth["client"].get("/api/forum/home").json()
    assert data["carousel"][0]["id"] == hot["id"]
    assert data["carousel"][0]["score"] > 0
    assert len(data["carousel"]) == 4
    carousel_ids = [item["id"] for item in data["carousel"]]
    assert len(set(carousel_ids)) == len(carousel_ids)
    recommended_ids = {item["id"] for item in data["recommended"]}
    assert set(carousel_ids).isdisjoint(recommended_ids)
    assert len(data["recommended"]) == 2
    assert data["stats"]["posts"] == 6
    assert data["stats"]["comments"] == 1


def test_home_recommended_is_disjoint_from_carousel(auth):
    for index in range(7):
        _create_post(auth["client"], auth["headers"], f"首页模块检查第 {index + 1} 条帖子")
    data = auth["client"].get("/api/forum/home").json()
    carousel_ids = {item["id"] for item in data["carousel"]}
    recommended_ids = {item["id"] for item in data["recommended"]}
    assert carousel_ids and recommended_ids
    assert carousel_ids.isdisjoint(recommended_ids)


def test_board_counts_invalidate_after_new_post(auth):
    forum_service.invalidate_board_counts()
    before = auth["client"].get("/api/forum/boards").json()["boards"]
    assert sum(item["count"] for item in before) == 0
    _create_post(auth["client"], auth["headers"], "版面计数检查：学习交流", tags=["学习交流"])
    after = auth["client"].get("/api/forum/boards").json()["boards"]
    counts = {item["key"]: item["count"] for item in after}
    assert counts["study"] == 1
    assert sum(counts.values()) == 1


def test_board_counts_reads_through_cache(auth):
    forum_service.invalidate_board_counts()
    assert sum(item["count"] for item in forum_service.board_counts()) == 0
    with db() as conn:
        conn.execute(
            "INSERT INTO posts (author_id, title, body, tags, board, status, created_at, updated_at) "
            "VALUES (?, '直接入库的帖子', '绕过接口写入', '[]', 'life', 'visible', "
            "'2026-10-01T00:00:00+00:00', '2026-10-01T00:00:00+00:00')",
            (auth["user"]["id"],),
        )
    # 缓存有效期内仍返回旧值，发帖/删帖会主动失效，force=True 用于对账
    assert sum(item["count"] for item in forum_service.board_counts()) == 0
    assert sum(item["count"] for item in forum_service.board_counts(force=True)) == 1


def test_admin_updates_announcement(auth):
    denied = auth["client"].post(
        "/api/admin/announcement",
        json={"text": "期中教学检查周，请按时提交作业。"},
        headers=auth["headers"],
    )
    assert denied.status_code == 403

    _promote_admin(auth)
    response = auth["client"].post(
        "/api/admin/announcement",
        json={"title": "本周公告", "text": "期中教学检查周，请按时提交作业。", "link": "https://www.ecnu.edu.cn/"},
        headers=auth["headers"],
    )
    assert response.status_code == 200, response.text
    assert response.json()["announcement"]["text"] == "期中教学检查周，请按时提交作业。"

    data = auth["client"].get("/api/forum/home").json()
    assert data["announcement"]["title"] == "本周公告"
    assert data["announcement"]["updated_at"]

    with db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log WHERE action = 'forum.announcement'"
        ).fetchone()
    assert row["n"] == 1
