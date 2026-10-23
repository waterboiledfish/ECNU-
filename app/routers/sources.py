"""官网目录、采集任务与文档浏览。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..config import settings
from ..db import db
from ..security import client_ip, enforce_rate, get_current_user
from ..services import index
from ..services.crawler import crawl_manager
from ..timeutil import iso, now_utc

router = APIRouter(prefix="/api/sources", tags=["sources"])


class CrawlIn(BaseModel):
    site_ids: list[int] = Field(default_factory=list, max_length=60)


def _crawl_allowed(user: dict) -> bool:
    return user["role"] == "admin" or settings.allow_user_crawl


@router.get("")
def list_sources(user: dict = Depends(get_current_user)):
    with db() as conn:
        rows = conn.execute(
            "SELECT s.*, (SELECT COUNT(*) FROM documents d WHERE d.site_id = s.id) AS doc_count "
            "FROM sites s ORDER BY s.category, s.id"
        ).fetchall()
        sites = [
            {
                "id": row["id"],
                "name": row["name"],
                "url": row["url"],
                "category": row["category"],
                "description": row["description"],
                "enabled": bool(row["enabled"]),
                "doc_count": row["doc_count"],
                "last_crawled_at": row["last_crawled_at"],
            }
            for row in rows
        ]
        categories: dict[str, list] = {}
        for site in sites:
            categories.setdefault(site["category"], []).append(site)
        doc_total = conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"]
    return {
        "sites": sites,
        "categories": [{"name": name, "sites": items} for name, items in categories.items()],
        "documents": int(doc_total),
        "index": index.stats(),
        "crawl": crawl_manager.status(),
        "can_crawl": _crawl_allowed(user),
        "portal_url": settings.portal_url,
    }


@router.get("/{site_id}/documents")
def site_documents(site_id: int, limit: int = 20, user: dict = Depends(get_current_user)):
    limit = max(1, min(limit, 100))
    with db() as conn:
        site = conn.execute("SELECT * FROM sites WHERE id = ?", (site_id,)).fetchone()
        if not site:
            raise HTTPException(status_code=404, detail="站点不存在")
        rows = conn.execute(
            "SELECT id, title, url, published_at, fetched_at, content_type, char_count "
            "FROM documents WHERE site_id = ? ORDER BY fetched_at DESC LIMIT ?",
            (site_id, limit),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM documents WHERE site_id = ?", (site_id,)
        ).fetchone()["n"]
    return {
        "site": {"id": site["id"], "name": site["name"], "url": site["url"]},
        "items": [dict(r) for r in rows],
        "total": int(total),
    }


@router.get("/documents/{doc_id}")
def document_detail(doc_id: int, user: dict = Depends(get_current_user)):
    with db() as conn:
        row = conn.execute(
            "SELECT d.*, s.name AS site_name FROM documents d JOIN sites s ON s.id = d.site_id "
            "WHERE d.id = ?",
            (doc_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {
        "id": row["id"],
        "title": row["title"],
        "url": row["url"],
        "site_name": row["site_name"],
        "published_at": row["published_at"],
        "fetched_at": row["fetched_at"],
        "content_type": row["content_type"],
        "char_count": row["char_count"],
        "excerpt": row["text"][:8000],
    }


@router.post("/crawl", status_code=202)
def start_crawl(payload: CrawlIn, request: Request, user: dict = Depends(get_current_user)):
    if not _crawl_allowed(user):
        raise HTTPException(status_code=403, detail="当前部署仅管理员可以触发采集")
    enforce_rate(request, "crawl", 10, 3600)
    try:
        status = crawl_manager.start(payload.site_ids, user["id"])
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    with db() as conn:
        conn.execute(
            "INSERT INTO audit_log (actor_id, action, target, detail, created_at) "
            "VALUES (?, 'crawl', ?, ?, ?)",
            (user["id"], ",".join(str(x) for x in payload.site_ids), json.dumps({"ip": client_ip(request)}), iso(now_utc())),
        )
    return status


@router.get("/crawl/status")
def crawl_status(user: dict = Depends(get_current_user)):
    return {"status": crawl_manager.status(), "can_crawl": _crawl_allowed(user)}


@router.post("/crawl/cancel")
def cancel_crawl(user: dict = Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可以停止采集")
    return {"status": crawl_manager.cancel()}


@router.get("/crawl/runs")
def crawl_runs(user: dict = Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可以查看采集记录")
    return {"items": crawl_manager.recent_runs(10)}
