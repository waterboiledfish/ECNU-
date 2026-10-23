from __future__ import annotations

from app.config import settings
from app.services import moderation


def test_scan_clean_text():
    verdict = moderation.scan("今天在食堂吃了红烧肉，味道不错。")
    assert verdict["risk"] == 0
    assert verdict["action"] == "ok"


def test_scan_single_category_needs_review():
    verdict = moderation.scan("这里有约炮信息")
    assert verdict["risk"] >= 30
    assert verdict["action"] == "review"
    assert "色情低俗" in verdict["categories"]


def test_scan_multiple_categories_blocks():
    verdict = moderation.scan("约炮 毒品 砍死 代考 刷单")
    assert verdict["action"] == "block"
    assert verdict["risk"] == 100


def test_scan_pii():
    verdict = moderation.scan("联系我 13812345678")
    assert "隐私泄露" in verdict["categories"]
    assert verdict["action"] == "review"


def test_status_mapping():
    assert moderation.status_for({"action": "ok"}) == "visible"
    assert moderation.status_for({"action": "review"}) == "pending"
    assert moderation.status_for({"action": "block"}) == "hidden"


def test_ai_scan_disabled_without_config():
    settings.moderation_api_key = ""
    assert moderation.ai_scan("任意内容") is None


def test_decide_merges_ai(monkeypatch):
    monkeypatch.setattr(
        moderation,
        "ai_scan",
        lambda text: {
            "risk": 90,
            "action": "block",
            "categories": ["诈骗广告"],
            "reason": "疑似诈骗",
            "source": "ai",
        },
    )
    verdict = moderation.decide("正常文本", use_ai=True)
    assert verdict["action"] == "block"
    assert verdict["source"] == "rule+ai"
    assert "诈骗广告" in verdict["categories"]
