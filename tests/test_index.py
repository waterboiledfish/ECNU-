from __future__ import annotations

from app.db import bump_index_version, db
from app.services import index
from app.services.extract import chunk_text
from app.services.tokenize import query_terms, tokenize


def test_tokenizer_chinese_bigrams():
    tokens = tokenize("缓考申请流程")
    assert "缓考" in tokens
    assert "申请" in tokens
    assert "流程" in tokens
    assert all(len(token) <= 40 for token in tokens)
    assert "the" not in tokenize("the scholarship")


def test_query_terms_are_unique():
    terms = query_terms("奖学金 奖学金 申请")
    assert len(terms) == len(set(terms))


def test_chunk_text():
    text = "\n\n".join(["第一段内容。" * 20, "第二段内容。" * 20, "第三段内容。" * 20])
    chunks = chunk_text(text, size=120)
    assert len(chunks) >= 3
    assert all(len(chunk) <= 300 for chunk in chunks)


def test_search_and_snippet(client):
    with db() as conn:
        site_id = int(conn.execute("SELECT id FROM sites LIMIT 1").fetchone()["id"])
        cursor = conn.execute(
            "INSERT INTO documents (site_id, url, title, fetched_at, content_type, sha256, text, char_count) "
            "VALUES (?, 'https://www.ecnu.edu.cn/a.html', '奖学金评定办法', '2026-01-01T00:00:00+00:00', 'html', 'h', ?, 100)",
            (site_id, "奖学金评定按照综合测评成绩排序，申请材料包括成绩单和获奖证明。" * 3),
        )
        doc_id = int(cursor.lastrowid)
        conn.execute(
            "INSERT INTO chunks (document_id, ordinal, text) VALUES (?, 0, ?)",
            (doc_id, "奖学金评定按照综合测评成绩排序，申请材料包括成绩单和获奖证明。" * 3),
        )
    bump_index_version()
    index.invalidate()
    hits = index.search("奖学金申请需要什么材料")
    assert hits
    assert hits[0]["title"] == "奖学金评定办法"
    assert "奖学金" in hits[0]["snippet"]
    assert index.stats()["documents"] == 1
