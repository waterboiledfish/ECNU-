from __future__ import annotations

from app.db import bump_index_version, db
from app.services import llm


def _seed_documents() -> tuple[int, int]:
    with db() as conn:
        site_rows = conn.execute("SELECT id FROM sites ORDER BY id LIMIT 2").fetchall()
        site_one, site_two = int(site_rows[0]["id"]), int(site_rows[1]["id"])
        docs = [
            (
                site_one,
                "https://www.ecnu.edu.cn/notice-exam.html",
                "关于期末考试与缓考安排的通知",
                "期末考试在第十八周进行。学生因病不能参加考试，需要提前向教务处提交缓考申请，"
                "并附医院证明。缓考申请截止时间为考试前三个工作日。" * 2,
            ),
            (
                site_two,
                "https://lib.ecnu.edu.cn/opening.html",
                "图书馆开放时间与借阅规则",
                "图书馆周一至周日开放，本科生每次可借十册图书，借期三十天，可续借一次。" * 2,
            ),
        ]
        ids = []
        for site_id, url, title, text in docs:
            cursor = conn.execute(
                "INSERT INTO documents (site_id, url, title, published_at, fetched_at, content_type, sha256, text, char_count) "
                "VALUES (?, ?, ?, '2026-09-01', '2026-09-02T00:00:00+00:00', 'html', 'hash', ?, ?)",
                (site_id, url, title, text, len(text)),
            )
            doc_id = int(cursor.lastrowid)
            conn.execute(
                "INSERT INTO chunks (document_id, ordinal, text) VALUES (?, 0, ?)", (doc_id, text)
            )
            ids.append(doc_id)
    bump_index_version()
    return ids[0], ids[1]


def _key_headers(headers: dict) -> dict:
    return {**headers, "X-LLM-Key": "sk-test-123456789", "X-LLM-Model": "test-model"}


def test_official_chat_with_citations(auth, monkeypatch):
    _seed_documents()
    captured = {}

    def fake_chat(messages, **kwargs):
        captured["messages"] = messages
        return "缓考需要提前向教务处提交申请，并附医院证明 [1]。"

    monkeypatch.setattr(llm, "chat", fake_chat)
    response = auth["client"].post(
        "/api/chat/official",
        json={"question": "因病不能参加期末考试，缓考怎么申请？"},
        headers=_key_headers(auth["headers"]),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["insufficient"] is False
    assert body["sources"][0]["url"].endswith("notice-exam.html")
    assert body["sources"][0]["used"] is True
    assert "缓考" in body["answer"]
    assert '<document index="1"' in captured["messages"][1]["content"]
    assert "不可信" in captured["messages"][0]["content"]


def test_official_chat_insufficient_without_hits(auth, monkeypatch):
    _seed_documents()

    def fail_chat(*args, **kwargs):
        raise AssertionError("没有检索结果时不应调用模型")

    monkeypatch.setattr(llm, "chat", fail_chat)
    response = auth["client"].post(
        "/api/chat/official",
        json={"question": "请问火星基地的招生简章在哪里？"},
        headers=_key_headers(auth["headers"]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["insufficient"] is True
    assert body["sources"] == []
    assert "没有找到" in body["answer"]


def test_official_chat_site_filter(auth, monkeypatch):
    _seed_documents()
    monkeypatch.setattr(llm, "chat", lambda messages, **kwargs: "只看图书馆的资料 [1]。")
    with db() as conn:
        site_two = int(conn.execute("SELECT id FROM sites ORDER BY id LIMIT 1 OFFSET 1").fetchone()["id"])
    response = auth["client"].post(
        "/api/chat/official",
        json={"question": "图书馆开放时间", "site_ids": [site_two]},
        headers=_key_headers(auth["headers"]),
    )
    assert response.status_code == 200
    sources = response.json()["sources"]
    assert sources and all(item["site_name"] for item in sources)
    assert "图书馆" in sources[0]["title"]


def test_chat_requires_key_and_model(auth):
    response = auth["client"].post("/api/chat/official", json={"question": "你好"}, headers=auth["headers"])
    assert response.status_code == 400
    response = auth["client"].post(
        "/api/chat/official",
        json={"question": "你好"},
        headers={**auth["headers"], "X-LLM-Key": "sk-test-123456789"},
    )
    # 没有已索引文件时直接返回“依据不足”，不会请求模型
    assert response.status_code == 200
    assert response.json()["insufficient"] is True


def test_official_stream_events(auth, monkeypatch):
    _seed_documents()

    def fake_stream(messages, **kwargs):
        yield "缓考申请需要"
        yield "提前三个工作日提交 [1]。"

    monkeypatch.setattr(llm, "stream_chat", fake_stream)
    with auth["client"].stream(
        "POST",
        "/api/chat/official/stream",
        json={"question": "缓考申请时间"},
        headers=_key_headers(auth["headers"]),
    ) as response:
        assert response.status_code == 200
        text = "".join(response.iter_text())
    assert '"type": "sources"' in text
    assert '"type": "delta"' in text
    assert '"type": "done"' in text
    assert "缓考" in text


def test_academic_chat(auth, monkeypatch):
    monkeypatch.setattr(llm, "chat", lambda messages, **kwargs: "贝叶斯定理是……")
    response = auth["client"].post(
        "/api/chat/academic",
        json={"question": "解释贝叶斯定理", "history": [{"role": "user", "content": "先讲讲概率"}]},
        headers=_key_headers(auth["headers"]),
    )
    assert response.status_code == 200
    assert response.json()["sources"] == []
    assert "贝叶斯" in response.json()["answer"]
