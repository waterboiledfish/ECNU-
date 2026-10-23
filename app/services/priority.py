"""重点内容识别：保研 / 推免 / 预推免 / 复试等学生最常找的通知，抓取时优先。

- 这些词既用于「链接锚文本」排序，也用于把已入库的重点通知单独列出来。
- 关键词可在 meta 表里改（`priority_topics`，逗号分隔），默认见 PRIORITY_TOPICS。
"""
from __future__ import annotations

import time

from ..db import get_meta, set_meta

KEY = "priority_topics"

# 默认重点词：招生升学类为主，这些内容的时效性最强、访问量最高
PRIORITY_TOPICS: tuple[str, ...] = (
    "推免",
    "预推免",
    "保研",
    "免试攻读",
    "复试",
    "调剂",
    "招生简章",
    "招生",
    "录取",
    "奖学金",
    "评奖评优",
)

# 采集时对每个链接都要判断，缓存 60 秒避免反复读库
_CACHE: dict[str, object] = {"value": None, "at": 0.0}
_TTL = 60.0


def topics() -> list[str]:
    now = time.time()
    cached = _CACHE.get("value")
    if cached and now - float(_CACHE.get("at", 0.0)) < _TTL:
        return list(cached)  # type: ignore[arg-type]
    try:
        raw = get_meta(KEY, "")
    except Exception:  # 数据库还没准备好时用默认值，别让采集挂掉
        raw = ""
    if raw:
        items = [item.strip() for item in raw.split(",") if item.strip()]
        result = items[:20] if items else list(PRIORITY_TOPICS)
    else:
        result = list(PRIORITY_TOPICS)
    _CACHE["value"] = result
    _CACHE["at"] = now
    return result


def set_topics(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for value in values[:20]:
        text = str(value).strip()[:20]
        if text and text not in cleaned:
            cleaned.append(text)
    set_meta(KEY, ",".join(cleaned))
    _CACHE["value"] = cleaned
    _CACHE["at"] = time.time()
    return cleaned


def matches(text: str | None) -> bool:
    """文本里是否命中任一重点词。"""
    if not text:
        return False
    return any(topic in text for topic in topics())


def is_priority(title: str | None, text: str | None = None) -> bool:
    if matches(title):
        return True
    return bool(text) and matches(text[:4000])
