"""摘要格式、检索同义扩展、正文页优先采集等「回答质量」用例。"""
from __future__ import annotations


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
