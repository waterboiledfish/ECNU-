from __future__ import annotations

import pytest

from app.services import news

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>测试新闻</title>
    <item>
      <title><![CDATA[今日科技要闻：某实验室发布新成果]]></title>
      <link>https://example.com/news/1</link>
      <description><![CDATA[<p>这是一段摘要 &amp; 内容</p>]]></description>
      <pubDate>Fri, 23 Oct 2026 10:00:00 +0800</pubDate>
    </item>
    <item>
      <title>教育新闻第二条 - 新华网</title>
      <link>https://example.com/news/2</link>
      <pubDate>2026-10-23 09:00:00</pubDate>
    </item>
  </channel>
</rss>""".encode()


def test_parse_rss():
    items = news._parse_rss(SAMPLE_RSS, "测试源")
    assert len(items) == 2
    assert items[0]["title"].startswith("今日科技要闻")
    assert items[0]["source"] == "测试源"
    assert items[0]["summary"] == "这是一段摘要 & 内容"
    assert items[0]["published_at"].startswith("2026-10-23T02:00:00")
    # 无时区的时间按中国标准时间解释
    assert items[1]["published_at"].startswith("2026-10-23T01:00:00")


def test_fetch_category_uses_feeds_and_cache(client, monkeypatch):
    fake = [
        {
            "title": "测试新闻 A",
            "url": "https://example.com/a",
            "summary": "",
            "source": "测试源",
            "published_at": "2026-10-23T02:00:00+00:00",
        }
    ]

    def fake_feed(name, url):
        return list(fake) if "ithome" in url else []

    monkeypatch.setattr(news, "_fetch_feed", fake_feed)
    monkeypatch.setattr(news, "_fetch_tavily", lambda query: [])
    payload = news.fetch_category("tech", refresh=True)
    assert payload["category"] == "tech"
    assert payload["label"] == "科技"
    assert len(payload["items"]) == 1
    cached = news.fetch_category("tech", refresh=False)
    assert cached["cached"] is True

    with pytest.raises(news.NewsError):
        news.fetch_category("not-a-category")


def test_digest(client, monkeypatch):
    monkeypatch.setattr(
        news,
        "_fetch_feed",
        lambda name, url: [
            {
                "title": f"新闻 {i}",
                "url": f"https://example.com/{i}",
                "summary": "",
                "source": "测试源",
                "published_at": f"2026-10-23T{i:02d}:00:00+00:00",
            }
            for i in range(12)
        ],
    )
    monkeypatch.setattr(news, "_fetch_tavily", lambda query: [])

    from app.services import llm

    monkeypatch.setattr(llm, "chat", lambda messages, **kwargs: "今日要点 [1]。")
    payload = news.digest("general", {"key": "sk-test-123456789", "model": "m", "base_url": None})
    assert "今日要点" in payload["digest"]
    assert len(payload["sources"]) == 12
    assert payload["sources"][0]["url"].startswith("https://example.com/")


def test_categories_payload():
    categories = news.categories_payload()
    keys = {item["key"] for item in categories}
    assert {"tech", "finance", "entertainment", "sports", "education", "world"} <= keys
