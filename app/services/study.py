"""学习资料推荐：按年级、课程与方向生成平台检索链接 + 论文推荐。"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from . import cache, llm, papers

PLATFORMS = {
    "bilibili": {"label": "Bilibili", "icon": "video", "tone": "#fb7299"},
    "xiaohongshu": {"label": "小红书", "icon": "note", "tone": "#ff2442"},
    "douyin": {"label": "抖音", "icon": "music", "tone": "#161823"},
    "zhihu": {"label": "知乎", "icon": "help", "tone": "#0066ff"},
    "mooc": {"label": "中国大学 MOOC", "icon": "cap", "tone": "#00a870"},
    "arxiv": {"label": "arXiv 论文", "icon": "paper", "tone": "#b31b1b"},
}


def platform_url(platform: str, query: str) -> str:
    q = quote(query)
    if platform == "bilibili":
        return f"https://search.bilibili.com/all?keyword={q}"
    if platform == "xiaohongshu":
        return f"https://www.xiaohongshu.com/search_result?keyword={q}"
    if platform == "douyin":
        return f"https://www.douyin.com/search/{q}"
    if platform == "zhihu":
        return f"https://www.zhihu.com/search?type=content&q={q}"
    if platform == "mooc":
        return f"https://www.icourse163.org/search.htm?search={q}"
    if platform == "arxiv":
        return f"https://arxiv.org/search/?query={q}&searchtype=all"
    return f"https://www.bing.com/search?q={q}"


def _deterministic(user: dict) -> list[dict[str, Any]]:
    courses = [c for c in (user.get("courses") or []) if c][:3]
    directions = [d for d in (user.get("directions") or []) if d][:2]
    grade = user.get("grade") or "大一"
    items: list[dict[str, Any]] = []
    for course in courses:
        items.append(
            {
                "platform": "bilibili",
                "title": f"{course} · 期末复习串讲",
                "query": f"{course} 期末复习",
                "reason": f"围绕你正在学的《{course}》补齐重点章节，适合系统过一遍。",
            }
        )
        items.append(
            {
                "platform": "zhihu",
                "title": f"{course} 怎么学：高赞经验",
                "query": f"{course} 怎么学",
                "reason": "先看别人的学习路径，再挑适合自己的方法。",
            }
        )
    if directions:
        items.append(
            {
                "platform": "arxiv",
                "title": f"{directions[0]} · 最新论文",
                "query": directions[0],
                "reason": "按你的学习方向检索近五年论文，先读综述再看具体方法。",
            }
        )
        items.append(
            {
                "platform": "bilibili",
                "title": f"{directions[0]} 入门路线",
                "query": f"{directions[0]} 入门",
                "reason": "用视频建立整体框架，再回到论文和教材。",
            }
        )
    items.append(
        {
            "platform": "xiaohongshu",
            "title": f"{grade}学习规划与时间管理",
            "query": f"{grade} 学习规划 时间管理",
            "reason": "看看同龄人怎么安排一周节奏，取长补短。",
        }
    )
    items.append(
        {
            "platform": "mooc",
            "title": "国家精品课 · 补基础",
            "query": courses[0] if courses else "大学学习方法",
            "reason": "系统课适合补概念，和学校课程形成互补。",
        }
    )
    items.append(
        {
            "platform": "douyin",
            "title": "三分钟知识卡片",
            "query": f"{courses[0] if courses else '大学学习'} 知识卡片",
            "reason": "碎片时间看短内容，但不要替代系统学习。",
        }
    )
    return items[:8]


AI_PROMPT = """你是学习资源策划。根据学生的年级、课程和学习方向，生成 6-8 条学习资料检索建议。
平台只能从 bilibili、xiaohongshu、douyin、zhihu、mooc、arxiv 中选择。
只返回 JSON 数组：[{"platform":"bilibili","title":"展示标题","query":"检索词","reason":"一句话说明为什么适合该学生"}]。
检索词要具体、可搜索；不要编造具体视频标题或链接；不要推荐盗版资源。"""


def _ai_items(creds: dict, user: dict) -> list[dict[str, Any]]:
    profile = {
        "grade": user.get("grade") or "未填写",
        "major": user.get("major") or "未填写",
        "courses": (user.get("courses") or [])[:8],
        "directions": (user.get("directions") or [])[:5],
    }
    text = llm.chat(
        [
            {"role": "system", "content": AI_PROMPT},
            {"role": "user", "content": json.dumps(profile, ensure_ascii=False)},
        ],
        key=creds["key"],
        model=creds["model"],
        base_url=creds.get("base_url"),
        temperature=0.5,
        timeout=60,
        json_mode=True,
        max_tokens=1600,
    )
    raw = llm.parse_json_array(text)
    items = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        platform = str(entry.get("platform", "")).strip()
        query = str(entry.get("query", "")).strip()
        if platform not in PLATFORMS or not query:
            continue
        items.append(
            {
                "platform": platform,
                "title": str(entry.get("title", query))[:80],
                "query": query[:60],
                "reason": str(entry.get("reason", ""))[:160],
            }
        )
        if len(items) >= 8:
            break
    return items


def recommend(user: dict, creds: dict | None = None, refresh: bool = False) -> dict[str, Any]:
    hour = datetime.now(UTC).strftime("%Y-%m-%d")
    key = f"study:{user['id']}:{hour}"
    if not refresh:
        cached = cache.get(key, ttl_seconds=20 * 3600)
        if cached:
            return {**cached, "cached": True}
    items = _deterministic(user)
    mode = "local"
    if creds:
        try:
            ai_items = _ai_items(creds, user)
            if len(ai_items) >= 3:
                items = ai_items
                mode = "ai"
            else:
                mode = "local-fallback"
        except llm.LLMError:
            mode = "local-fallback"
    enriched = []
    for item in items:
        platform = item["platform"]
        enriched.append(
            {
                **item,
                "platform_label": PLATFORMS[platform]["label"],
                "url": platform_url(platform, item["query"]),
                "tone": PLATFORMS[platform]["tone"],
            }
        )
    paper_items: list[dict[str, Any]] = []
    directions = user.get("directions") or []
    if directions:
        try:
            paper_payload = papers.recommend(directions[0], creds)
            paper_items = paper_payload.get("papers", [])[:3]
        except papers.PaperError:
            paper_items = []
    payload = {
        "items": enriched,
        "papers": paper_items,
        "mode": mode,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "note": "以上为平台站内检索链接，内容由相应平台提供；请遵守平台规则与版权要求。",
    }
    cache.set(key, payload)
    return {**payload, "cached": False}
