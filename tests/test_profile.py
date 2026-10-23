from __future__ import annotations

import base64
import io


def _png_data_url() -> str:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (12, 12), (20, 120, 140)).save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def test_update_profile(auth):
    response = auth["client"].patch(
        "/api/profile",
        json={
            "nickname": "樱桃河",
            "major": "数据科学与大数据技术",
            "grade": "大三",
            "bio": "喜欢跑步和写代码",
            "directions": ["人工智能", "数据可视化"],
            "courses": ["机器学习", "数据库"],
            "settings": {"theme": "dark", "news_categories": ["tech", "finance"]},
        },
        headers=auth["headers"],
    )
    assert response.status_code == 200
    user = response.json()["user"]
    assert user["nickname"] == "樱桃河"
    assert user["directions"] == ["人工智能", "数据可视化"]
    me = auth["client"].get("/api/auth/me").json()["user"]
    assert me["settings"]["theme"] == "dark"
    assert me["settings"]["news_categories"] == ["tech", "finance"]


def test_invalid_nickname_and_duplicate(auth, second_user):
    response = auth["client"].patch("/api/profile", json={"nickname": "x"}, headers=auth["headers"])
    assert response.status_code == 400
    response = auth["client"].patch(
        "/api/profile", json={"nickname": "第二位同学"}, headers=auth["headers"]
    )
    assert response.status_code == 409


def test_reserved_nickname(auth):
    response = auth["client"].patch(
        "/api/profile", json={"nickname": "管理员"}, headers=auth["headers"]
    )
    assert response.status_code == 400


def test_avatar_preset_and_upload(auth):
    client, headers = auth["client"], auth["headers"]
    response = client.patch("/api/profile", json={"avatar": "preset:forest"}, headers=headers)
    assert response.status_code == 200
    response = client.patch("/api/profile", json={"avatar": "preset:unknown"}, headers=headers)
    assert response.status_code == 400

    response = client.post("/api/profile/avatar", json={"image": _png_data_url()}, headers=headers)
    assert response.status_code == 200
    url = response.json()["avatar_url"]
    assert url.startswith("/api/media/avatar/")
    image_response = client.get(url)
    assert image_response.status_code == 200
    assert image_response.headers["content-type"] == "image/png"


def test_avatar_rejects_bad_data(auth):
    response = auth["client"].post(
        "/api/profile/avatar",
        json={"image": "data:image/png;base64,bm90LWEtcG5n"},
        headers=auth["headers"],
    )
    assert response.status_code == 400


def test_avatar_media_requires_auth_and_rejects_traversal(client):
    assert client.get("/api/media/avatar/not-a-file.png").status_code == 401


def test_delete_account_anonymizes_posts(auth, second_user):
    client, headers = auth["client"], auth["headers"]
    post = client.post(
        "/api/forum/posts",
        json={"title": "准备删除的帖子", "body": "这条帖子会在账号删除后保留为匿名。", "tags": ["生活分享"], "anonymous": False},
        headers=headers,
    )
    assert post.status_code == 201
    post_id = post.json()["post"]["id"]
    response = client.delete("/api/profile?confirm=DELETE", headers=headers)
    assert response.status_code == 200
    assert client.get("/api/auth/me").json()["authenticated"] is False
    feed = second_user["client"].get("/api/forum/posts")
    assert feed.status_code == 200
    item = next(item for item in feed.json()["items"] if item["id"] == post_id)
    assert item["author"]["id"] is None
    assert item["author"]["nickname"] == "已注销用户"
