"""官网目录、采集任务与文档浏览。"""
from __future__ import annotations

import json
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..config import settings
from ..db import bump_index_version, db
from ..security import client_ip, enforce_rate, get_current_user
from ..services import extract, index, recency
from ..services.crawler import CrawlManager, crawl_manager
from ..timeutil import iso, now_utc

router = APIRouter(prefix="/api/sources", tags=["sources"])


class CrawlIn(BaseModel):
    site_ids: list[int] = Field(default_factory=list, max_length=60)


class ImportIn(BaseModel):
    url: str = Field(min_length=8, max_length=500)


class SettingsIn(BaseModel):
    max_age_days: int = Field(ge=0, le=recency.MAX_DAYS)


def _crawl_allowed(user: dict) -> bool:
    return user["role"] == "admin" or settings.allow_user_crawl


@router.get("")
def list_sources(user: dict = Depends(get_current_user)):
    with db() as conn:
        rows = conn.execute(
            "SELECT s.*, (SELECT COUNT(*) FROM documents d WHERE d.site_id = s.id) AS doc_count "
            "FROM sites s WHERE s.enabled = 1 ORDER BY s.category, s.id"
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
        last = conn.execute("SELECT * FROM crawl_runs ORDER BY id DESC LIMIT 1").fetchone()
        last_run = None
        if last:
            try:
                detail = json.loads(last["detail"] or "{}")
            except json.JSONDecodeError:
                detail = {}
            last_run = {
                "status": last["status"],
                "started_at": last["started_at"],
                "finished_at": last["finished_at"],
                "pages_ok": last["pages_ok"],
                "pages_failed": last["pages_failed"],
                "skipped_old": int(detail.get("skipped_old", 0) or 0),
                "skipped_fresh": int(detail.get("skipped_fresh", 0) or 0),
                "errors": detail.get("errors", [])[-8:],
            }
    return {
        "sites": sites,
        "categories": [{"name": name, "sites": items} for name, items in categories.items()],
        "documents": int(doc_total),
        "index": index.stats(fast=True),
        "crawl": crawl_manager.status(),
        "last_run": last_run,
        "can_crawl": _crawl_allowed(user),
        "max_age_days": recency.max_age_days(),
        "age_choices": list(recency.CHOICES),
        "portal_url": settings.portal_url,
    }


@router.patch("/settings")
def update_settings(payload: SettingsIn, request: Request, user: dict = Depends(get_current_user)):
    """调整「只收录最近 N 天文件」的窗口，0 表示不限。"""
    if not _crawl_allowed(user):
        raise HTTPException(status_code=403, detail="当前部署仅管理员可以调整收录范围")
    enforce_rate(request, "source-settings", 20, 600)
    value = recency.set_max_age_days(payload.max_age_days)
    bump_index_version()
    return {"ok": True, "max_age_days": value, "index": index.stats()}


def _site_for_host(conn, host: str):
    rows = conn.execute("SELECT * FROM sites WHERE enabled = 1 ORDER BY id").fetchall()
    for row in rows:
        base = (urlparse(row["url"]).hostname or "").lower()
        if base and (host == base or host.endswith("." + base)):
            return row
    return None


@router.post("/import", status_code=201)
def import_document(payload: ImportIn, request: Request, user: dict = Depends(get_current_user)):
    """手动导入一个官网公开文件链接，适合爬虫难以覆盖的通知/规章/PDF。"""
    if not _crawl_allowed(user):
        raise HTTPException(status_code=403, detail="当前部署仅管理员可以导入官网文件")
    enforce_rate(request, "import-doc", 30, 3600)
    url = payload.url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="请输入完整的 http(s) 链接")
    if not extract.host_allowed(url, settings.crawl_allowed_suffixes):
        raise HTTPException(status_code=400, detail="链接不在学校官网白名单（ecnu.edu.cn）内")
    try:
        result = extract.fetch(url)
        if not extract.host_allowed(result["url"], settings.crawl_allowed_suffixes):
            raise HTTPException(status_code=400, detail="链接跳转到了非学校官网，已拒绝")
        content = extract.extract(
            result["url"], result["content_type"], result["data"], result.get("charset", "utf-8")
        )
    except extract.FetchError as exc:
        raise HTTPException(status_code=400, detail=f"读取失败：{exc}") from None
    if len(content["text"]) < 60:
        raise HTTPException(
            status_code=400,
            detail="没有提取到足够的正文（扫描版 PDF 需先 OCR，或该页面依赖脚本渲染）",
        )
    if recency.is_too_old(content.get("published_at")):
        raise HTTPException(
            status_code=400,
            detail=f"该文件的发布日期超出收录窗口（最近 {recency.max_age_days()} 天），如需收录请先在页面上放宽收录范围",
        )
    host = (urlparse(result["url"]).hostname or "").lower()
    with db() as conn:
        site = _site_for_host(conn, host)
        if site is None:
            cursor = conn.execute(
                "INSERT INTO sites (key, name, url, category, description, enabled) "
                "VALUES (?, ?, ?, '手动导入', '通过链接手动导入的学校官网文件', 1)",
                (host, host, f"https://{host}/"),
            )
            site_id = int(cursor.lastrowid)
        else:
            site_id = int(site["id"])
        changed = CrawlManager._save_document(conn, site_id, result["url"], content)
        conn.execute(
            "UPDATE sites SET last_crawled_at = ?, doc_count = "
            "(SELECT COUNT(*) FROM documents WHERE site_id = ?) WHERE id = ?",
            (iso(now_utc()), site_id, site_id),
        )
        conn.execute(
            "INSERT INTO audit_log (actor_id, action, target, detail, created_at) "
            "VALUES (?, 'import-document', ?, ?, ?)",
            (user["id"], result["url"][:300], json.dumps({"ip": client_ip(request)}), iso(now_utc())),
        )
        doc = conn.execute(
            "SELECT id, title, url, published_at, char_count, content_type "
            "FROM documents WHERE url = ?",
            (result["url"],),
        ).fetchone()
    bump_index_version()
    return {
        "ok": True,
        "changed": changed,
        "document": dict(doc) if doc else None,
        "message": "已导入并加入检索索引" if changed else "文件已存在且内容未变化",
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
