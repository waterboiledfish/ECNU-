"""AI 对话历史：落库、列表、读取、覆盖保存与用户隔离。"""
from __future__ import annotations


def _create(client, headers, mode: str = "official") -> int:
    response = client.post("/api/chat/threads", json={"mode": mode}, headers=headers)
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def test_thread_save_and_list(auth):
    client, headers = auth["client"], auth["headers"]
    thread_id = _create(client, headers)

    saved = client.put(
        f"/api/chat/threads/{thread_id}",
        json={
            "messages": [
                {"role": "user", "content": "缓考怎么申请？"},
                {
                    "role": "assistant",
                    "content": "先说结论：到教务处提交申请。",
                    "sources": [
                        {"index": 1, "title": "缓考办理通知", "url": "https://www.ecnu.edu.cn/a.html"}
                    ],
                    "insufficient": False,
                },
            ]
        },
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["title"] == "缓考怎么申请？"

    listing = client.get("/api/chat/threads?mode=official").json()["threads"]
    assert len(listing) == 1
    assert listing[0]["id"] == thread_id
    assert listing[0]["message_count"] == 2

    detail = client.get(f"/api/chat/threads/{thread_id}").json()
    assert [message["role"] for message in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["sources"][0]["title"] == "缓考办理通知"


def test_thread_overwrite_and_title_fallback(auth):
    client, headers = auth["client"], auth["headers"]
    thread_id = _create(client, headers)
    client.put(
        f"/api/chat/threads/{thread_id}",
        json={"messages": [{"role": "user", "content": "第一个问题"}]},
        headers=headers,
    )
    saved = client.put(
        f"/api/chat/threads/{thread_id}",
        json={"messages": [{"role": "user", "content": "换了的问题"}, {"role": "assistant", "content": "回答"}]},
        headers=headers,
    )
    assert saved.status_code == 200
    detail = client.get(f"/api/chat/threads/{thread_id}").json()
    assert len(detail["messages"]) == 2
    assert detail["title"] == "换了的问题"

    empty = client.put(f"/api/chat/threads/{thread_id}", json={"messages": []}, headers=headers)
    assert empty.status_code == 200
    assert empty.json()["title"] == "换了的问题"


def test_thread_modes_are_separate(auth):
    client, headers = auth["client"], auth["headers"]
    official = _create(client, headers, "official")
    academic = _create(client, headers, "academic")
    official_ids = {item["id"] for item in client.get("/api/chat/threads?mode=official").json()["threads"]}
    academic_ids = {item["id"] for item in client.get("/api/chat/threads?mode=academic").json()["threads"]}
    assert official in official_ids and official not in academic_ids
    assert academic in academic_ids and academic not in official_ids


def test_thread_delete_and_isolation(auth, second_user):
    client, headers = auth["client"], auth["headers"]
    thread_id = _create(client, headers)
    assert client.delete(f"/api/chat/threads/{thread_id}", headers=headers).status_code == 200
    assert client.get(f"/api/chat/threads/{thread_id}").status_code == 404

    other = _create(client, headers)
    assert second_user["client"].get(f"/api/chat/threads/{other}").status_code == 404
    assert (
        second_user["client"].delete(
            f"/api/chat/threads/{other}", headers=second_user["headers"]
        ).status_code
        == 404
    )


def test_thread_requires_auth(client):
    assert client.get("/api/chat/threads").status_code == 401
    assert client.post("/api/chat/threads", json={"mode": "official"}).status_code == 403
