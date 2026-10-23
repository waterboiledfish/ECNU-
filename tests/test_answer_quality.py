"""摘要格式、检索同义扩展、正文页优先采集等「回答质量」用例。"""
from __future__ import annotations


def test_decode_ignores_default_latin1():
    """HTTP 头没有 charset 时 requests 给 ISO-8859-1，不能让正文变乱码。"""
    from app.services.extract import _decode

    utf8 = '<html><head><meta charset="utf-8"></head><body>推免生综合考核实施细则</body></html>'.encode()
    assert "推免生综合考核实施细则" in _decode(utf8, "ISO-8859-1")

    gbk = '<html><head><meta charset="gbk"></head><body>推免生综合考核实施细则</body></html>'.encode("gbk")
    assert "推免生综合考核实施细则" in _decode(gbk, "ISO-8859-1")

    # 明确声明 GBK 且字节确实是 GBK 时也要按声明解
    assert "中文" in _decode("<p>中文</p>".encode("gbk"), "gbk")


def test_mojibake_documents_are_marked_for_refetch(auth):
    from app.db import _OLD_STAMP, _repair_mojibake, db
    from app.timeutil import iso, now_utc

    now = iso(now_utc())
    with db() as conn:
        site_id = conn.execute("SELECT id FROM sites ORDER BY id LIMIT 1").fetchone()["id"]
        for title, text in [
            ("乱码页", "å¤§å­¦æ»´æ°´æ¹–å½éè½¯ä»¶å¦é¢ æ­£æåå®¹"),
            ("正常页", "华东师范大学软件工程学院 推免生综合考核实施细则"),
        ]:
            conn.execute(
                "INSERT INTO documents (site_id, url, title, published_at, fetched_at, "
                "content_type, sha256, text, char_count) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?)",
                (site_id, f"https://www.ecnu.edu.cn/{title}.html", title, now, "text/html", title, text, len(text)),
            )
        _repair_mojibake(conn)
        rows = {
            row["title"]: row["fetched_at"]
            for row in conn.execute("SELECT title, fetched_at FROM documents WHERE title IN ('乱码页','正常页')")
        }
    assert rows["乱码页"] == _OLD_STAMP
    assert rows["正常页"] == now


def test_priority_topic_matching():
    from app.services import priority

    assert priority.matches("2027 年推免生综合考核实施细则")
    assert priority.matches("保研经验分享：如何准备夏令营")
    assert priority.matches("硕士研究生复试录取实施细则")
    assert not priority.matches("食堂开放时间调整")
    assert priority.is_priority("通知公告", "正文里提到推免与预报名安排")


def test_extract_returns_anchor_text():
    from app.services import extract

    html = (
        '<html><body><div class="content">'
        '<a href="/a/page.htm">2027年推免生综合考核实施细则</a>'
        '<a href="/b/list.htm">更多通知</a>'
        "</div></body></html>"
    ).encode()
    content = extract.extract("https://www.ecnu.edu.cn/33171/list.htm", "text/html", html, "utf-8")
    texts = [item["text"] for item in content["link_items"]]
    assert any("推免" in text for text in texts)
    assert content["links"][0].startswith("https://www.ecnu.edu.cn/")


def test_priority_endpoint_lists_known_documents(auth):
    from app.db import db
    from app.timeutil import iso, now_utc

    with db() as conn:
        site_id = conn.execute("SELECT id FROM sites ORDER BY id LIMIT 1").fetchone()["id"]
        conn.execute(
            "INSERT INTO documents (site_id, url, title, published_at, fetched_at, content_type, "
            "sha256, text, char_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                site_id,
                "https://www.ecnu.edu.cn/priority-test.html",
                "软件工程学院 2027 年推免生综合考核实施细则",
                "2026-09-11",
                iso(now_utc()),
                "text/html",
                "priority-test",
                "推免招生计划等相关内容",
                20,
            ),
        )
    payload = auth["client"].get("/api/sources/priority").json()
    assert "推免" in payload["topics"]
    assert any("推免" in item["title"] for item in payload["items"])


def test_crawl_accepts_focus_flag(auth, monkeypatch):
    from app.routers import sources as sources_router

    captured: dict = {}

    def fake_start(site_ids, user_id=None, focus=False):
        captured["focus"] = focus
        captured["site_ids"] = site_ids
        return {"running": True, "message": "准备重点扫描（保研 / 推免 / 复试等）"}

    monkeypatch.setattr(sources_router.crawl_manager, "start", fake_start)
    response = auth["client"].post(
        "/api/sources/crawl", json={"site_ids": [1, 2], "focus": True}, headers=auth["headers"]
    )
    assert response.status_code == 202
    assert captured["focus"] is True
    assert captured["site_ids"] == [1, 2]


def test_meta_exposes_faculty_and_catalogs(auth):
    client = auth["client"]
    meta = client.get("/api/meta").json()
    assert meta["faculty_url"].startswith("https://faculty.ecnu.edu.cn")
    names = {item["name"] for item in meta["academics"]["departments"]}
    assert "创新创业学院" in names
    assert len(names) >= 37

    sites = client.get("/api/sources").json()["sites"]
    by_name = {site["name"]: site for site in sites}
    assert "创新创业学院" in by_name
    assert by_name["创新创业学院"]["url"] == "https://sie.ecnu.edu.cn/"
    assert len(sites) >= 44


def test_clean_digest_strips_planning_text():
    from app.services.news import clean_digest

    messy = """我们需要回答中文。需要生成“今日热点摘要”，5-7条要点，每条标注[编号]。
需要识别重复：7[11]同一事件李昌钰下葬，可合并但标注7[11]。
需要5-7条。每条标注编号，可能多个编号。

今日热点摘要
1. 台湾渔产品输入大陆仪式在厦门举行[1]
2. “活力中国”报道关注海南“海上风车”转向世界[2]
3. 多家上市公司披露业绩，汤姆猫、东岳硅材、中煤能源口径不一[3][6][12]
值得继续关注的方向
- 两岸渔产品贸易后续
- 海上风电产业国际化
"""
    cleaned = clean_digest(messy)
    assert cleaned.startswith("今日热点摘要")
    assert "需要识别重复" not in cleaned
    assert "1. 台湾渔产品" in cleaned
    assert "值得继续关注的方向" in cleaned


def test_clean_digest_keeps_numbered_items_without_header():
    from app.services.news import clean_digest

    cleaned = clean_digest("1. 第一条[1]\n2. 第二条[2]")
    assert cleaned.startswith("今日热点摘要")
    assert "第二条[2]" in cleaned


def test_digest_uses_strict_prompt(monkeypatch):
    from app.services import news

    captured: dict = {}

    def fake_chat(messages, **kwargs):
        captured["system"] = messages[0]["content"]
        captured["user"] = messages[-1]["content"]
        return "思考中…\n今日热点摘要\n1. 甲事件[1]\n值得继续关注的方向\n- 甲"

    monkeypatch.setattr(news.llm, "chat", fake_chat)
    feed = {
        "category": "general",
        "label": "综合",
        "items": [
            {
                "title": "甲事件",
                "url": "https://example.com/1",
                "source": "示例",
                "published_at": "2026-10-23T00:00:00+00:00",
            }
        ],
        "fetched_at": "2026-10-23T00:00:00+00:00",
    }
    payload = news._digest_payload(feed, {"key": "sk-1234567890", "model": "m"}, "分类：综合")
    assert "5-7 条" in captured["system"]
    assert "同一事件" in captured["system"]
    assert payload["digest"].startswith("今日热点摘要")
    assert "思考中" not in payload["digest"]


def test_expand_query_adds_formal_terms():
    from app.services.rag import expand_query

    expanded = expand_query("2026年预推免的规则")
    assert "预推免" in expanded
    assert "推免" in expanded
    assert "免试攻读" in expanded
    # 没有命中关键词时原样返回
    assert expand_query("食堂几点开门") == "食堂几点开门"


def test_article_like_prioritizes_detail_pages():
    from app.services.crawler import CrawlManager

    assert CrawlManager._article_like("https://software.ecnu.edu.cn/info/1004/1234.htm")
    assert CrawlManager._article_like("https://www.ecnu.edu.cn/2026/0923/c1847a123456/page.htm")
    assert not CrawlManager._article_like("https://www.ecnu.edu.cn/index.htm")
    assert not CrawlManager._article_like("https://www.ecnu.edu.cn/xygk/xyjj.htm")
