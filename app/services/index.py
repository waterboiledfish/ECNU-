"""内存 BM25 检索索引。

索引在首次查询时从 SQLite 的 chunks 表构建，之后按 meta.index_version
判断是否失效。语料规模面向"学校官网公开文件"（数千至数万段），
构建与查询都在毫秒到秒级，无需外部向量库。
"""
from __future__ import annotations

import math
import re
import threading
import time
from collections import defaultdict
from typing import Any

from ..db import db, get_meta
from .tokenize import query_terms, tokenize

_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {
    "version": None,
    "postings": {},
    "lengths": {},
    "docs": {},
    "df": {},
    "total_len": 0,
    "n": 0,
    "built_at": 0.0,
    "doc_count": 0,
}

K1 = 1.5
B = 0.75


def build_index(force: bool = False) -> dict[str, Any]:
    version = get_meta("index_version", "0")
    with _LOCK:
        if not force and _CACHE["version"] == version and _CACHE["built_at"]:
            return _CACHE
        with db() as conn:
            rows = conn.execute(
                """
                SELECT c.id AS chunk_id, c.document_id, c.ordinal, c.text,
                       d.title, d.url, d.published_at, d.site_id, s.name AS site_name
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                JOIN sites s ON s.id = d.site_id
                """
            ).fetchall()
        postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        lengths: dict[int, int] = {}
        docs: dict[int, dict[str, Any]] = {}
        df: dict[str, int] = defaultdict(int)
        total_len = 0
        for row in rows:
            cid = int(row["chunk_id"])
            tokens = tokenize(row["text"])
            length = len(tokens)
            lengths[cid] = length
            total_len += length
            docs[cid] = {
                "chunk_id": cid,
                "document_id": int(row["document_id"]),
                "ordinal": int(row["ordinal"]),
                "title": row["title"],
                "url": row["url"],
                "published_at": row["published_at"],
                "site_id": int(row["site_id"]),
                "site_name": row["site_name"],
                "text": row["text"],
                "title_tokens": set(tokenize(row["title"])),
            }
            counts: dict[str, int] = defaultdict(int)
            for token in tokens:
                counts[token] += 1
            for token, tf in counts.items():
                postings[token].append((cid, tf))
                df[token] += 1
        _CACHE.update(
            {
                "version": version,
                "postings": dict(postings),
                "lengths": lengths,
                "docs": docs,
                "df": dict(df),
                "total_len": total_len,
                "n": len(rows),
                "built_at": time.time(),
                "doc_count": len({d["document_id"] for d in docs.values()}),
            }
        )
        return _CACHE


def invalidate() -> None:
    with _LOCK:
        _CACHE["version"] = None
        _CACHE["built_at"] = 0.0


def stats() -> dict[str, int]:
    cache = build_index()
    avg = (cache["total_len"] / cache["n"]) if cache["n"] else 0
    return {
        "chunks": int(cache["n"]),
        "documents": int(cache["doc_count"]),
        "terms": len(cache["postings"]),
        "avg_chunk_tokens": round(avg, 1),
    }


def search(
    question: str,
    *,
    site_ids: list[int] | None = None,
    limit: int = 8,
    per_document: int = 2,
) -> list[dict[str, Any]]:
    cache = build_index()
    if not cache["n"]:
        return []
    terms = query_terms(question)[:24]
    if not terms:
        return []
    postings = cache["postings"]
    docs = cache["docs"]
    lengths = cache["lengths"]
    df = cache["df"]
    total = int(cache["n"])
    avgdl = (cache["total_len"] / total) if total else 0.0
    scores: dict[int, float] = defaultdict(float)
    for term in terms:
        plist = postings.get(term)
        if not plist:
            continue
        idf = math.log(1.0 + (total - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5))
        for cid, tf in plist:
            dl = lengths.get(cid, 0)
            denom = tf + K1 * (1 - B + B * (dl / avgdl if avgdl else 1.0))
            scores[cid] += idf * (tf * (K1 + 1) / denom if denom else 0.0)
    if not scores:
        return []
    allowed_sites = set(site_ids or [])
    candidates: list[tuple[float, int]] = []
    term_set = set(terms)
    for cid, score in scores.items():
        doc = docs.get(cid)
        if not doc:
            continue
        if allowed_sites and doc["site_id"] not in allowed_sites:
            continue
        title_hits = len(term_set & doc["title_tokens"])
        if title_hits:
            score *= 1.0 + min(0.6, 0.18 * title_hits)
        candidates.append((score, cid))
    candidates.sort(reverse=True)
    results: list[dict[str, Any]] = []
    seen_docs: dict[int, int] = defaultdict(int)
    for score, cid in candidates:
        doc = docs[cid]
        if seen_docs[doc["document_id"]] >= per_document:
            continue
        seen_docs[doc["document_id"]] += 1
        results.append(
            {
                **{k: v for k, v in doc.items() if k != "title_tokens"},
                "score": round(score, 4),
                "snippet": make_snippet(doc["text"], terms),
            }
        )
        if len(results) >= limit:
            break
    return results


def make_snippet(text: str, terms: list[str], width: int = 180) -> str:
    plain = re.sub(r"\s+", " ", text or "").strip()
    if not plain:
        return ""
    lowered = plain.lower()
    pos = -1
    for term in terms:
        if len(term) < 2:
            continue
        found = lowered.find(term.lower())
        if found >= 0 and (pos < 0 or found < pos):
            pos = found
    if pos < 0:
        return plain[:width] + ("…" if len(plain) > width else "")
    start = max(0, pos - 60)
    end = min(len(plain), start + width)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(plain) else ""
    return prefix + plain[start:end].strip() + suffix


def document_chunks(document_id: int) -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            "SELECT ordinal, text FROM chunks WHERE document_id = ? ORDER BY ordinal",
            (document_id,),
        ).fetchall()
    return [dict(r) for r in rows]
