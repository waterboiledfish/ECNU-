from __future__ import annotations

from app.db import db


def _admin(auth):
    with db() as conn:
        conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (auth["user"]["id"],))
    auth["user"]["role"] = "admin"


def _create_post(client, headers, title="期末复习经验分享", body="整理了一份复习路线，欢迎补充。", anonymous=False, tags=None):
    response = client.post(
        "/api/forum/posts",
        json={"title": title, "body": body, "tags": tags or ["学习交流"], "anonymous": anonymous},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["post"]


def test_create_and_list_post(auth, second_user):
    post = _create_post(auth["client"], auth["headers"])
    assert post["status"] == "visible"
    listing = second_user["client"].get("/api/forum/posts?tag=学习交流")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    item = listing.json()["items"][0]
    assert item["author"]["nickname"] == "测试同学"
    assert item["author"]["id"] is not None


def test_anonymous_post_hides_identity(auth, second_user):
    post = _create_post(auth["client"], auth["headers"], title="匿名问问选课", anonymous=True)
    detail = second_user["client"].get(f"/api/forum/posts/{post['id']}").json()["post"]
    assert detail["anonymous"] is True
    assert detail["author"]["id"] is None
    assert detail["author"]["nickname"].startswith("匿名同学·")
    assert detail["mine"] is False


def test_comment_like_bookmark(auth, second_user):
    post = _create_post(auth["client"], auth["headers"])
    comment = second_user["client"].post(
        f"/api/forum/posts/{post['id']}/comments",
        json={"body": "谢谢分享，很有用。", "anonymous": False},
        headers=second_user["headers"],
    )
    assert comment.status_code == 201
    assert comment.json()["comment"]["status"] == "visible"

    like = second_user["client"].post(f"/api/forum/posts/{post['id']}/like", headers=second_user["headers"])
    assert like.status_code == 200
    assert like.json() == {"liked": True, "count": 1}
    again = second_user["client"].post(f"/api/forum/posts/{post['id']}/like", headers=second_user["headers"])
    assert again.json()["liked"] is False

    bookmark = second_user["client"].post(f"/api/forum/posts/{post['id']}/bookmark", headers=second_user["headers"])
    assert bookmark.json()["bookmarked"] is True
    detail = second_user["client"].get(f"/api/forum/posts/{post['id']}").json()
    assert detail["post"]["bookmarked"] is True
    assert detail["comments"][0]["body"] == "谢谢分享，很有用。"


def test_moderation_pending_and_admin_approval(auth, second_user):
    post = _create_post(
        auth["client"],
        auth["headers"],
        title="测试审核流程",
        body="约炮 毒品 砍死 这些词不应该直接展示",
    )
    assert post["status"] == "hidden"
    assert auth["client"].get(f"/api/forum/posts/{post['id']}").status_code == 200
    assert second_user["client"].get(f"/api/forum/posts/{post['id']}").status_code == 404

    _admin(auth)
    queue = auth["client"].get("/api/admin/moderation?kind=posts&status=hidden").json()
    assert queue["total"] >= 1
    approved = auth["client"].post(
        f"/api/admin/moderation/post/{post['id']}", json={"action": "approve", "note": "人工确认"}, headers=auth["headers"]
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "visible"
    assert second_user["client"].get(f"/api/forum/posts/{post['id']}").status_code == 200


def test_report_and_admin_resolve(auth, second_user):
    post = _create_post(second_user["client"], second_user["headers"], title="待举报的帖子", body="正常内容")
    report = auth["client"].post(
        "/api/forum/reports",
        json={"target_type": "post", "target_id": post["id"], "reason": "其他", "detail": "测试"},
        headers=auth["headers"],
    )
    assert report.status_code == 201
    duplicate = auth["client"].post(
        "/api/forum/reports",
        json={"target_type": "post", "target_id": post["id"], "reason": "其他"},
        headers=auth["headers"],
    )
    assert duplicate.status_code == 409

    _admin(auth)
    reports = auth["client"].get("/api/admin/reports").json()["items"]
    assert any(item["target_id"] == post["id"] for item in reports)
    resolved = auth["client"].post(
        f"/api/admin/reports/{reports[0]['id']}",
        json={"action": "hide", "reply": "已处理"},
        headers=auth["headers"],
    )
    assert resolved.status_code == 200
    detail = second_user["client"].get(f"/api/forum/posts/{post['id']}").json()["post"]
    assert detail["status"] == "hidden"


def test_follow_and_message(auth, second_user):
    follow = auth["client"].post(
        f"/api/forum/users/{second_user['user_id']}/follow", headers=auth["headers"]
    )
    assert follow.status_code == 200
    assert follow.json()["following"] is True
    profile = auth["client"].get(f"/api/forum/users/{second_user['user_id']}").json()
    assert profile["stats"]["followers"] == 1
    assert profile["user"]["is_following"] is True

    sent = auth["client"].post(
        "/api/messages",
        json={"to": second_user["user_id"], "body": "你好，想请教一个问题"},
        headers=auth["headers"],
    )
    assert sent.status_code == 201
    conversations = second_user["client"].get("/api/messages/conversations").json()
    assert conversations["unread"] == 1
    thread = second_user["client"].get(f"/api/messages/{auth['user']['id']}").json()
    assert thread["messages"][0]["body"] == "你好，想请教一个问题"
    assert thread["messages"][0]["mine"] is False
    reply = second_user["client"].post(
        "/api/messages",
        json={"to": auth["user"]["id"], "body": "可以呀，请说"},
        headers=second_user["headers"],
    )
    assert reply.status_code == 201

    notifications = second_user["client"].get("/api/notifications").json()
    assert any(item["kind"] in {"follow", "message"} for item in notifications["items"])


def test_forum_search(auth):
    _create_post(auth["client"], auth["headers"], title="独一无二的标题词", body="正文")
    result = auth["client"].get("/api/forum/posts?q=独一无二").json()
    assert result["total"] == 1


def test_cannot_report_self(auth):
    _create_post(auth["client"], auth["headers"])
    response = auth["client"].post(
        "/api/forum/reports",
        json={"target_type": "user", "target_id": auth["user"]["id"], "reason": "其他"},
        headers=auth["headers"],
    )
    assert response.status_code == 400
