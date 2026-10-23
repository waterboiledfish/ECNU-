"""论坛内容审核：本地规则预筛 + 可选 AI 复核。

规则命中不等于违规：达到阈值的内容只会进入人工审核队列，
管理员可以放行、隐藏或删除；用户可申诉。AI 审核同样只作为辅助。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..config import settings
from . import llm

_RULES_PATH = Path(__file__).resolve().parent.parent / "data" / "moderation_rules.json"
_RULES: dict[str, Any] | None = None


def rules() -> dict[str, Any]:
    global _RULES
    if _RULES is None:
        try:
            _RULES = json.loads(_RULES_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _RULES = {"categories": [], "pii_patterns": [], "spam": {}}
    return _RULES


def _risk_for(score: int) -> str:
    if score >= 85:
        return "block"
    if score >= 30:
        return "review"
    if score > 0:
        return "low"
    return "ok"


def scan(text: str) -> dict[str, Any]:
    ruleset = rules()
    text = (text or "")[:8000]
    score = 0
    hits: list[dict[str, str]] = []
    categories: list[str] = []
    review_only = False
    lowered = text.lower()
    for category in ruleset.get("categories", []):
        matched = False
        for keyword in category.get("keywords", []):
            if keyword.lower() in lowered:
                if not matched:
                    score += int(category.get("weight", 20))
                    categories.append(category["name"])
                    matched = True
                hits.append({"category": category["name"], "keyword": keyword})
                if category.get("review_only"):
                    review_only = True
        if len(hits) > 12:
            break
    for pattern in ruleset.get("pii_patterns", []):
        try:
            if re.search(pattern["pattern"], text):
                score += int(pattern.get("weight", 20))
                categories.append("隐私泄露")
                hits.append({"category": "隐私泄露", "keyword": pattern["name"]})
        except re.error:
            continue
    spam = ruleset.get("spam", {})
    link_count = len(re.findall(spam.get("link_pattern", r"https?://"), text))
    if link_count >= int(spam.get("link_threshold", 3)):
        score += 25
        categories.append("广告垃圾")
        hits.append({"category": "广告垃圾", "keyword": f"包含 {link_count} 个链接"})
    repeat_threshold = max(1, int(spam.get("repeat_threshold", 8)) - 1)
    if re.search(r"(.)\1{" + str(repeat_threshold) + ",}", text):
        score += 10
        hits.append({"category": "垃圾内容", "keyword": "重复字符"})
    score = min(100, score)
    action = _risk_for(score)
    if review_only and action == "ok":
        action = "review"
    return {
        "risk": score,
        "action": action,
        "categories": sorted(set(categories)),
        "hits": hits[:12],
        "source": "rule",
        "review_only": review_only,
    }


def status_for(verdict: dict[str, Any]) -> str:
    action = verdict.get("action")
    if action == "block":
        return "hidden"
    if action == "review":
        return "pending"
    return "visible"


AI_SYSTEM = """你是校园论坛的内容安全审核助手。请判断帖子是否包含色情低俗、暴力血腥、违法违规、诈骗广告、严重人身攻击或泄露他人隐私的内容。
正常的学习交流、生活分享、寻物启事、对学校的合理批评不属于违规。
只返回 JSON：{"risk": 0-100 的整数, "categories": ["..."], "reason": "一句话说明"}。
risk >= 85 表示应直接隐藏，30-84 表示需要人工复核，低于 30 表示可以放行。"""


def ai_scan(text: str) -> dict[str, Any] | None:
    if not settings.moderation_api_key or not settings.moderation_model:
        return None
    base = settings.moderation_base_url or settings.llm_base_url
    try:
        response = llm.chat(
            [
                {"role": "system", "content": AI_SYSTEM},
                {"role": "user", "content": (text or "")[:4000]},
            ],
            key=settings.moderation_api_key,
            model=settings.moderation_model,
            base_url=base,
            temperature=0.0,
            timeout=20,
            json_mode=True,
            max_tokens=300,
        )
        data = llm.parse_json_object(response)
        risk = max(0, min(100, int(data.get("risk", 0))))
        categories = [str(x)[:20] for x in data.get("categories", []) if isinstance(x, str)][:6]
        return {
            "risk": risk,
            "action": _risk_for(risk),
            "categories": categories,
            "reason": str(data.get("reason", ""))[:200],
            "source": "ai",
        }
    except (llm.LLMError, ValueError, TypeError):
        return None


def decide(text: str, use_ai: bool = True) -> dict[str, Any]:
    rule = scan(text)
    result = dict(rule)
    ai = ai_scan(text) if use_ai else None
    if ai:
        if ai["risk"] >= rule["risk"]:
            result.update(
                {
                    "risk": ai["risk"],
                    "action": ai["action"],
                    "categories": sorted(set(rule["categories"]) | set(ai["categories"])),
                    "ai_reason": ai.get("reason", ""),
                    "source": "rule+ai",
                }
            )
        else:
            result["ai_checked"] = True
    return result
