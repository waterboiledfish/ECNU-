"""论文推荐：OpenAlex + arXiv，无需 API Key。"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import requests

from ..config import settings
from . import cache, llm

OPENALEX = "https://api.openalex.org/works"
ARXIV = "https://export.arxiv.org/api/query"
CACHE_TTL = 12 * 3600
ATOM = {"a": "http://www.w3.org/2005/Atom"}

FIELD_MAP = {
    "人工智能": "artificial intelligence",
    "机器学习": "machine learning",
    "深度学习": "deep learning",
    "自然语言处理": "natural language processing",
    "计算机视觉": "computer vision",
    "大语言模型": "large language model",
    "数据科学": "data science",
    "统计学": "statistics",
    "数学": "mathematics",
    "物理": "physics",
    "化学": "chemistry",
    "生物学": "biology",
    "生态学": "ecology",
    "地理学": "geography",
    "心理学": "psychology",
    "教育学": "education",
    "经济学": "economics",
    "金融学": "finance",
    "管理学": "management",
    "法学": "law",
    "社会学": "sociology",
    "新闻传播": "journalism and communication",
    "软件工程": "software engineering",
    "网络安全": "cybersecurity",
    "密码学": "cryptography",
    "药学": "pharmacy",
    "海洋科学": "marine science",
    "环境科学": "environmental science",
    "音乐": "music",
    "美术": "fine arts",
    "设计": "design",
    "历史学": "history",
    "哲学": "philosophy",
    "中国语言文学": "Chinese literature",
    "翻译": "translation studies",
}


class PaperError(Exception):
    pass


def expand_query(direction: str, creds: dict | None = None) -> str:
    direction = (direction or "").strip()
    if not direction:
        direction = "人工智能"
    if re.search(r"[a-zA-Z]", direction):
        return direction[:160]
    if creds:
        cache_key = "paper_query:" + direction[:60]
        cached = cache.get(cache_key, ttl_seconds=30 * 86400)
        if cached:
            return cached
        try:
            text = llm.chat(
                [
                    {
                        "role": "system",
                        "content": "把中文学习方向翻译成适合检索英文学术论文的 3-6 个英文关键词，只返回关键词，用空格分隔。",
                    },
                    {"role": "user", "content": direction[:100]},
                ],
                key=creds["key"],
                model=creds["model"],
                base_url=creds.get("base_url"),
                temperature=0.0,
                timeout=25,
                max_tokens=80,
            )
            query = re.sub(r"[^A-Za-z0-9 \-]", " ", text).strip()
            if len(query) >= 3:
                cache.set(cache_key, query)
                return query
        except llm.LLMError:
            pass
    for chinese, english in FIELD_MAP.items():
        if chinese in direction:
            return english
    return direction[:160]


def _reconstruct_abstract(inverted: dict | None) -> str:
    if not inverted:
        return ""
    positions: dict[int, str] = {}
    for word, indexes in inverted.items():
        for index in indexes or []:
            positions[int(index)] = word
    if not positions:
        return ""
    text = " ".join(positions[i] for i in sorted(positions))
    return text[:700]


def _openalex(query: str, per_page: int = 8) -> list[dict[str, Any]]:
    params = {
        "search": query,
        "per-page": per_page,
        "sort": "relevance_score:desc",
        "filter": f"from_publication_date:{datetime.now(UTC).year - 5}-01-01,type:article",
    }
    if settings.openalex_mailto:
        params["mailto"] = settings.openalex_mailto
    try:
        response = requests.get(
            OPENALEX,
            params=params,
            timeout=18,
            headers={"User-Agent": settings.user_agent},
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return []
    results = []
    for work in payload.get("results", []):
        title = (work.get("title") or work.get("display_name") or "").strip()
        if not title:
            continue
        authors = []
        for authorship in (work.get("authorships") or [])[:5]:
            name = (authorship.get("author") or {}).get("display_name")
            if name:
                authors.append(name)
        location = (work.get("primary_location") or {}).get("source") or {}
        doi = (work.get("doi") or "").replace("https://doi.org/", "")
        results.append(
            {
                "title": title[:300],
                "authors": authors,
                "year": work.get("publication_year"),
                "venue": (location.get("display_name") or "")[:120],
                "citations": work.get("cited_by_count", 0),
                "abstract": _reconstruct_abstract(work.get("abstract_inverted_index")),
                "doi": doi,
                "openalex": work.get("id"),
                "oa_url": (work.get("open_access") or {}).get("oa_url") or "",
                "source": "openalex",
            }
        )
    return results


def _arxiv(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    try:
        response = requests.get(
            ARXIV,
            params={
                "search_query": f'all:"{query}"',
                "start": 0,
                "max_results": max_results,
                "sortBy": "relevance",
                "sortOrder": "descending",
            },
            timeout=18,
            headers={"User-Agent": settings.user_agent},
        )
        response.raise_for_status()
        root = ET.fromstring(response.text)
    except (requests.RequestException, ET.ParseError):
        return []
    results = []
    for entry in root.findall("a:entry", ATOM):
        title = (entry.findtext("a:title", default="", namespaces=ATOM) or "").strip()
        if not title:
            continue
        link = entry.findtext("a:id", default="", namespaces=ATOM)
        authors = [
            (author.findtext("a:name", default="", namespaces=ATOM) or "").strip()
            for author in entry.findall("a:author", ATOM)
        ][:5]
        published = entry.findtext("a:published", default="", namespaces=ATOM) or ""
        results.append(
            {
                "title": re.sub(r"\s+", " ", title)[:300],
                "authors": authors,
                "year": published[:4],
                "venue": "arXiv",
                "citations": 0,
                "abstract": re.sub(
                    r"\s+", " ", entry.findtext("a:summary", default="", namespaces=ATOM) or ""
                )[:700],
                "doi": "",
                "openalex": "",
                "oa_url": link,
                "source": "arxiv",
            }
        )
    return results


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", title.lower())[:80]


def _rank(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current_year = datetime.now(UTC).year
    seen: set[str] = set()
    ranked = []
    for paper in papers:
        key = _normalize_title(paper["title"])
        if not key or key in seen:
            continue
        seen.add(key)
        citations = int(paper.get("citations") or 0)
        year = int(paper.get("year") or current_year)
        recency = max(0.0, 1.0 - (current_year - year) / 8)
        score = math.log1p(citations) + recency * 1.5
        paper = dict(paper)
        paper["score"] = round(score, 3)
        paper["link"] = (
            (f"https://doi.org/{paper['doi']}" if paper.get("doi") else "")
            or paper.get("oa_url")
            or paper.get("openalex")
        )
        ranked.append(paper)
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked


def recommend(direction: str, creds: dict | None = None, refresh: bool = False) -> dict[str, Any]:
    direction = (direction or "").strip() or "人工智能"
    key = "papers:" + direction[:80]
    if not refresh:
        cached = cache.get(key, ttl_seconds=CACHE_TTL)
        if cached:
            return {**cached, "cached": True}
    query = expand_query(direction, creds)
    papers = _openalex(query)
    if len(papers) < 3:
        papers.extend(_arxiv(query))
    if not papers:
        stale = cache.get_stale(key)
        if stale:
            return {**stale, "cached": True, "stale": True}
        raise PaperError("暂时无法连接论文服务（OpenAlex / arXiv），请稍后重试")
    payload = {
        "direction": direction,
        "query": query,
        "papers": _rank(papers)[:8],
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "note": "论文元数据来自 OpenAlex 与 arXiv；点击链接前往原文或 DOI 页面。",
    }
    cache.set(key, payload)
    return {**payload, "cached": False}


def recommend_many(directions: list[str], creds: dict | None = None) -> list[dict[str, Any]]:
    items = []
    for direction in directions[:3]:
        items.append(recommend(direction, creds))
    return items


def arxiv_search_link(query: str) -> str:
    return f"https://arxiv.org/search/?query={quote(query)}&searchtype=all"
