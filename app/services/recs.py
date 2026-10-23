"""学习资料推荐：从 B 站公开搜索接口取播放量高的视频与专栏文章，给出可直达链接。

- 视频用 search_type=video（按播放量排序），专栏用 search_type=article（按浏览量排序）。
- 接口需要 buvid cookie 才会返回 JSON，这里只在进程内取一次指纹 cookie 复用。
- 网络不通或接口改版时退回「平台检索链接」，不影响学习资料页面。
"""
from __future__ import annotations

import html
import re
import threading
import time
from datetime import UTC, datetime
from typing import Any

import requests

from . import cache

SEARCH_URL = "https://api.bilibili.com/x/web-interface/search/type"
FINGERPRINT_URL = "https://api.bilibili.com/x/frontend/finger/spi"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
VIDEO_URL = "https://www.bilibili.com/video/{}"
ARTICLE_URL = "https://www.bilibili.com/read/cv{}"

_SESSION: requests.Session | None = None
_LOCK = threading.Lock()
_TAG_RE = re.compile(r"<[^>]+>")
# 触发风控后暂停一段时间，避免继续加重；期间直接回退到检索链接
_COOLDOWN = {"until": 0.0, "last_call": 0.0}
MIN_INTERVAL = 0.8


class BiliBlocked(Exception):
    pass


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub("", text or ""))).strip()


def _session() -> requests.Session:
    global _SESSION
    with _LOCK:
        if _SESSION is None:
            session = requests.Session()
            session.headers.update({"User-Agent": UA})
            try:
                spi = session.get(FINGERPRINT_URL, timeout=8).json()
                data = spi.get("data") or {}
                if data.get("b_3"):
                    session.cookies.set("buvid3", data["b_3"], domain=".bilibili.com")
                if data.get("b_4"):
                    session.cookies.set("buvid4", data["b_4"], domain=".bilibili.com")
            except (requests.RequestException, ValueError):
                pass
            _SESSION = session
        return _SESSION


def _count_label(value: int) -> str:
    if value >= 100_000_000:
        return f"{value / 100_000_000:.1f} 亿"
    if value >= 10_000:
        return f"{value / 10_000:.1f} 万"
    return str(value)


def _search(kind: str, keyword: str, limit: int) -> list[dict[str, Any]]:
    now = time.time()
    if now < _COOLDOWN["until"]:
        raise BiliBlocked("cooling down")
    with _LOCK:
        wait = MIN_INTERVAL - (time.time() - _COOLDOWN["last_call"])
        if wait > 0:
            time.sleep(wait)
        _COOLDOWN["last_call"] = time.time()
    params = {"search_type": kind, "keyword": keyword, "page": 1, "order": "click"}
    try:
        response = _session().get(
            SEARCH_URL,
            params=params,
            headers={"Referer": "https://search.bilibili.com/"},
            timeout=10,
        )
    except requests.RequestException as exc:
        raise BiliBlocked(str(exc)) from None
    if response.status_code == 412:
        # B 站风控：停 10 分钟，期间直接给检索链接
        _COOLDOWN["until"] = time.time() + 600
        raise BiliBlocked("412 risk control")
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") not in (0, None):
        if "412" in str(payload.get("message", "")):
            _COOLDOWN["until"] = time.time() + 600
        raise BiliBlocked(str(payload.get("message")))
    rows = ((payload.get("data") or {}).get("result")) or []
    items: list[dict[str, Any]] = []
    for row in rows:
        title = _clean(row.get("title", ""))
        if not title:
            continue
        if kind == "video":
            bvid = str(row.get("bvid") or "").strip()
            if not bvid:
                continue
            count = int(row.get("play") or 0)
            items.append(
                {
                    "kind": "video",
                    "title": title[:110],
                    "url": VIDEO_URL.format(bvid),
                    "author": _clean(row.get("author", ""))[:40],
                    "count": count,
                    "count_label": f"{_count_label(count)}次播放",
                }
            )
        else:
            cvid = row.get("id")
            if not cvid:
                continue
            count = int(row.get("view") or 0)
            items.append(
                {
                    "kind": "doc",
                    "title": title[:110],
                    "url": ARTICLE_URL.format(cvid),
                    "author": _clean(row.get("author", ""))[:40],
                    "count": count,
                    "count_label": f"{_count_label(count)}次浏览",
                }
            )
        if len(items) >= limit:
            break
    return items


def queries_for(user: dict) -> list[str]:
    """按「课程 → 方向 → 专业/年级 → 通用」的顺序拼检索词，最多两条。

    资料里什么都没填时，之前只能拿到「大学学习方法」这种通用结果；
    现在会退而用专业与年级检索，命中率明显更高。
    """
    courses = [c for c in (user.get("courses") or []) if c][:2]
    directions = [d for d in (user.get("directions") or []) if d][:1]
    major = re.sub(r"\s+", " ", str(user.get("major") or "")).strip()[:24]
    grade = str(user.get("grade") or "").strip()[:8]
    queries = [f"{course} 期末复习" for course in courses]
    queries += [f"{direction} 入门" for direction in directions]
    if major:
        queries.append(f"{grade} {major} 专业课".strip() if grade else f"{major} 专业课")
    if len(queries) < 2 and grade:
        queries.append(f"{grade} 学习规划")
    if not queries:
        queries = ["大学学习方法"]
    return list(dict.fromkeys(queries))[:2]


def _fallback(queries: list[str]) -> dict[str, Any]:
    links = []
    for query in queries:
        links.append(
            {
                "kind": "link",
                "title": f"在 B 站搜索「{query}」",
                "url": f"https://search.bilibili.com/all?keyword={requests.utils.quote(query)}",
                "author": "",
                "count": 0,
                "count_label": "站内检索",
            }
        )
    return {"videos": links, "docs": [], "mode": "fallback"}


def recommend(user: dict, refresh: bool = False) -> dict[str, Any]:
    queries = queries_for(user)
    key = "study-live:" + "|".join(queries)
    if not refresh:
        cached = cache.get(key, ttl_seconds=20 * 3600)
        if cached:
            return {**cached, "cached": True}

    videos: list[dict[str, Any]] = []
    docs: list[dict[str, Any]] = []
    blocked = False
    for query in queries:
        try:
            videos.extend(_search("video", query, 4))
        except BiliBlocked:
            blocked = True
        except (requests.RequestException, ValueError):
            pass
        try:
            docs.extend(_search("article", query, 3))
        except BiliBlocked:
            blocked = True
        except (requests.RequestException, ValueError):
            pass

    # 风控期间一条都拿不到时，先复用上次成功抓到的结果，别让页面突然只剩检索链接
    if blocked and not videos and not docs:
        stale = cache.get_stale(key)
        if stale and (stale.get("videos") or stale.get("docs")):
            return {
                **stale,
                "queries": queries,
                "cached": True,
                "stale": True,
                "blocked": True,
                "note": (
                    "B 站暂时触发了访问风控，先显示上次成功抓到的结果；"
                    "过几分钟点「换一批」会重新抓取。"
                ),
            }

    def dedupe(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        seen: set[str] = set()
        ordered = sorted(rows, key=lambda item: item.get("count", 0), reverse=True)
        result = []
        for row in ordered:
            if row["url"] in seen:
                continue
            seen.add(row["url"])
            result.append(row)
            if len(result) >= limit:
                break
        return result

    payload: dict[str, Any] = {
        "videos": dedupe(videos, 6),
        "docs": dedupe(docs, 4),
        "queries": queries,
        "searches": [
            {
                "query": query,
                "url": f"https://search.bilibili.com/all?keyword={requests.utils.quote(query)}",
            }
            for query in queries
        ],
        "blocked": blocked,
        "mode": "live",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "note": "视频与专栏按公开播放/浏览量排序，链接直达 B 站；内容由平台提供，请遵守平台规则。",
    }
    if not payload["videos"] and not payload["docs"]:
        payload.update(_fallback(queries))
        if blocked:
            payload["note"] = (
                "B 站暂时触发了访问风控，先给出站内检索链接；过几分钟再点「换一批」就能看到具体视频。"
            )
    # 只有拿到真实条目才写缓存，风控/失败时下次可以重试
    if payload["videos"] and payload["mode"] == "live":
        cache.set(key, payload)
    return {**payload, "cached": False}
