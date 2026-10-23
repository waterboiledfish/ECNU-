"""前端可用的固定选项。"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

GRADES = ["大一", "大二", "大三", "大四", "研一", "研二", "研三", "博士", "教师", "其他"]

AVATAR_PRESETS = [
    {"key": "ocean", "label": "海风", "bg": "linear-gradient(135deg,#0b3a66,#16a3a0)", "emoji": "🌊"},
    {"key": "forest", "label": "梧桐", "bg": "linear-gradient(135deg,#14532d,#84cc16)", "emoji": "🌿"},
    {"key": "sunset", "label": "晚霞", "bg": "linear-gradient(135deg,#f97316,#ec4899)", "emoji": "🌅"},
    {"key": "grape", "label": "紫藤", "bg": "linear-gradient(135deg,#5b21b6,#a78bfa)", "emoji": "🪻"},
    {"key": "ink", "label": "墨色", "bg": "linear-gradient(135deg,#1f2937,#64748b)", "emoji": "🖋️"},
    {"key": "mint", "label": "薄荷", "bg": "linear-gradient(135deg,#0f766e,#99f6e4)", "emoji": "🍃"},
    {"key": "candy", "label": "糖果", "bg": "linear-gradient(135deg,#db2777,#fbbf24)", "emoji": "🍬"},
    {"key": "night", "label": "星夜", "bg": "linear-gradient(135deg,#0f172a,#3b82f6)", "emoji": "🌌"},
]

REPORT_REASONS = ["色情低俗", "暴力血腥", "违法违规", "诈骗广告", "人身攻击", "隐私泄露", "其他"]

RESERVED_NICKNAMES = {"管理员", "官方", "客服", "系统", "ECNU小助手", "小助手", "admin", "administrator"}

_ACADEMICS_PATH = Path(__file__).with_name("data") / "academics.json"


@lru_cache(maxsize=1)
def academics() -> dict:
    """院系 / 专业选项；读取失败时返回空目录，前端仍可手动填写。"""
    try:
        return json.loads(_ACADEMICS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"departments": [], "note": ""}


DEFAULT_SETTINGS = {
    "theme": "system",
    "news_categories": ["general", "tech", "finance"],
    "notify_channels": ["inapp", "browser"],
    "show_grade": True,
    "compact": False,
}
