"""官网公开内容采集器：遵守 robots.txt，按域名限速，串行采集。"""
from __future__ import annotations

import hashlib
import re
import threading
import time
import urllib.robotparser
from collections import deque
from datetime import timedelta
from typing import Any
from urllib.parse import urljoin, urlparse

from ..config import settings
from ..db import bump_index_version, db, jdumps, jloads
from ..timeutil import now_iso, now_utc
from . import extract, recency
from .extract import FetchError


class CrawlManager:
    def __init__(self) -> None:
        # 可重入锁：start() 内部会再调用 status()，普通 Lock 会直接死锁
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._state: dict[str, Any] = {
            "running": False,
            "run_id": None,
            "started_at": None,
            "site": "",
            "pages_ok": 0,
            "pages_failed": 0,
            "pages_skipped_old": 0,
            "queued": 0,
            "message": "空闲",
            "errors": [],
        }

    # ------------------------------------------------------------ public
    def start(self, site_ids: list[int], user_id: int | None = None) -> dict:
        with self._lock:
            worker = self._thread
            # 线程已经死了就别再报「正在采集」，否则用户会一直卡在「进行中」
            if self._state.get("running") and worker is not None and worker.is_alive():
                raise RuntimeError("已有采集任务正在进行，请等待完成")
            with db() as conn:
                if site_ids:
                    marks = ",".join("?" for _ in site_ids)
                    rows = conn.execute(
                        f"SELECT * FROM sites WHERE enabled = 1 AND id IN ({marks}) ORDER BY id",
                        tuple(site_ids),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM sites WHERE enabled = 1 ORDER BY id LIMIT 3"
                    ).fetchall()
            sites = [dict(r) for r in rows]
            if not sites:
                raise RuntimeError("没有可采集的站点")
            run_id = None
            with db() as conn:
                cur = conn.execute(
                    "INSERT INTO crawl_runs (site_ids, status, started_at, detail) "
                    "VALUES (?, 'running', ?, ?)",
                    (jdumps([s["id"] for s in sites]), now_iso(), jdumps({"user_id": user_id})),
                )
                run_id = int(cur.lastrowid)
            self._stop.clear()
            self._state = {
                "running": True,
                "run_id": run_id,
                "started_at": now_iso(),
                "site": sites[0]["name"],
                "pages_ok": 0,
                "pages_failed": 0,
                "queued": 0,
                "site_total": len(sites),
                "message": "准备采集",
                "errors": [],
            }
            self._thread = threading.Thread(
                target=self._run, args=(run_id, sites), name="ecnu-crawler", daemon=True
            )
            thread = self._thread
        # 出锁再启动线程：工作线程第一步就会抢这把锁，持锁启动会互相卡住
        thread.start()
        return self.status()

    def status(self) -> dict:
        """读取状态。拿不到锁也要返回，绝不能把接口卡死。"""
        acquired = self._lock.acquire(timeout=2)
        if not acquired:
            return {
                "running": True,
                "message": "采集状态读取中…",
                "pages_ok": 0,
                "pages_failed": 0,
                "queued": 0,
                "errors": [],
                "stalled": True,
            }
        try:
            return {**self._state, "errors": list(self._state.get("errors", []))[-10:]}
        finally:
            self._lock.release()

    def cancel(self) -> dict:
        self._stop.set()
        with self._lock:
            self._state["message"] = "正在停止…"
        return self.status()

    # ------------------------------------------------------------ worker
    def _run(self, run_id: int, sites: list[dict]) -> None:
        total_ok = 0
        total_failed = 0
        total_skipped = 0
        total_fresh = 0
        errors: list[str] = []
        try:
            for index, site in enumerate(sites, start=1):
                if self._stop.is_set():
                    break
                with self._lock:
                    self._state["site"] = f"{site['name']}（{index}/{len(sites)}）"
                    self._state["message"] = "读取 robots.txt"
                ok, failed, skipped_old, skipped_fresh, site_errors = self._crawl_site(site)
                total_ok += ok
                total_failed += failed
                total_skipped += skipped_old
                total_fresh += skipped_fresh
                errors.extend(site_errors)
                with self._lock:
                    self._state["pages_ok"] = total_ok
                    self._state["pages_failed"] = total_failed
                    self._state["pages_skipped_old"] = total_skipped
                    self._state["pages_skipped_fresh"] = total_fresh
                    self._state["errors"] = errors[-30:]
                with db() as conn:
                    conn.execute(
                        "UPDATE sites SET last_crawled_at = ?, doc_count = "
                        "(SELECT COUNT(*) FROM documents WHERE site_id = ?) WHERE id = ?",
                        (now_iso(), site["id"], site["id"]),
                    )
                time.sleep(1.0)
            bump_index_version()
            status = "cancelled" if self._stop.is_set() else "finished"
        except Exception as exc:  # 采集线程兜底：记录错误而不是让进程崩溃
            errors.append(f"采集器异常：{exc.__class__.__name__}")
            status = "failed"
        finally:
            with db() as conn:
                conn.execute(
                    "UPDATE crawl_runs SET status = ?, finished_at = ?, pages_ok = ?, "
                    "pages_failed = ?, detail = ? WHERE id = ?",
                    (
                        status,
                        now_iso(),
                        total_ok,
                        total_failed,
                        jdumps(
                            {
                                "errors": errors[-30:],
                                "skipped_old": total_skipped,
                                "skipped_fresh": total_fresh,
                            }
                        ),
                        run_id,
                    ),
                )
                conn.execute(
                    "UPDATE sites SET doc_count = (SELECT COUNT(*) FROM documents WHERE site_id = sites.id)"
                )
            with self._lock:
                self._state["running"] = False
                extra = []
                if total_skipped:
                    extra.append(f"跳过 {total_skipped} 篇超出收录窗口")
                if total_fresh:
                    extra.append(f"跳过 {total_fresh} 篇已抓过")
                self._state["message"] = {
                    "finished": f"采集完成：成功 {total_ok} 页，失败 {total_failed} 页"
                    + (f"，{'，'.join(extra)}" if extra else "")
                    + ("；再点一次采集会继续往里抓新页面" if total_fresh else ""),
                    "cancelled": "已停止采集",
                    "failed": "采集失败，请查看错误记录",
                }[status]
                self._state["pages_ok"] = total_ok
                self._state["pages_failed"] = total_failed
                self._state["pages_skipped_old"] = total_skipped
                self._state["errors"] = errors[-30:]

    def _crawl_site(self, site: dict) -> tuple[int, int, int, int, list[str]]:
        base = site["url"]
        robots = self._load_robots(base)
        queue: deque[tuple[str, int]] = deque([(base, 0)])
        visited: set[str] = set()
        ok = 0
        failed = 0
        skipped_old = 0
        skipped_fresh = 0
        errors: list[str] = []
        max_pages = max(1, settings.crawl_max_pages_per_site)
        # 最近抓过的正文页不再重复抓：多次点「采集」会逐层往里走，而不是反复抓同一批页面
        cutoff = (now_utc() - timedelta(days=max(0, settings.crawl_refresh_days))).isoformat()
        with db() as conn:
            fresh_articles = {
                row["url"]
                for row in conn.execute(
                    "SELECT url FROM documents WHERE site_id = ? AND fetched_at >= ?",
                    (site["id"], cutoff),
                ).fetchall()
            }
        # 每个栏目最多抓 per_section 篇正文，避免英文站/师资页把页数预算吃光
        per_section = max(6, max_pages // 4)
        section_counts: dict[str, int] = {}
        while queue and ok + failed < max_pages and not self._stop.is_set():
            url, depth = queue.popleft()
            if url in visited:
                continue
            visited.add(url)
            if robots is not None and not robots.can_fetch(settings.user_agent, url):
                continue
            if url in fresh_articles and self._article_like(url):
                skipped_fresh += 1
                continue
            if self._article_like(url):
                section = self._section_of(url)
                if section_counts.get(section, 0) >= per_section:
                    continue
                section_counts[section] = section_counts.get(section, 0) + 1
            with self._lock:
                self._state["queued"] = len(queue)
                self._state["message"] = f"正在采集：{urlparse(url).netloc}{urlparse(url).path[:40]}"
            time.sleep(max(0.2, settings.crawl_delay_seconds))
            try:
                result = extract.fetch(url)
            except FetchError as exc:
                failed += 1
                if len(errors) < 20:
                    errors.append(f"{url} · {exc}")
                continue
            try:
                content = extract.extract(
                    result["url"], result["content_type"], result["data"], result.get("charset", "utf-8")
                )
            except FetchError as exc:
                failed += 1
                if len(errors) < 20:
                    errors.append(f"{result['url']} · {exc}")
                continue
            if len(content["text"]) < 60:
                failed += 1
                continue
            if recency.is_too_old(content.get("published_at")):
                skipped_old += 1  # 超出收录窗口：直接跳过，但保留链接继续爬
                continue
            with db() as conn:
                changed = self._save_document(conn, int(site["id"]), result["url"], content)
            if changed:
                ok += 1
            else:
                failed += 1  # 未变化：计入跳过
            if depth < settings.crawl_max_depth:
                for link in content.get("links", []):
                    link = self._normalize(link, base)
                    if (
                        link not in visited
                        and len(queue) < 600
                        and extract.host_allowed(link, settings.crawl_allowed_suffixes)
                        and self._same_site(link, base)
                        and not self._skip_url(link)
                    ):
                        item = (link, depth + 1)
                        # 正文页优先：列表页的链接很多，先抓文章正文再抓导航页
                        if self._article_like(link):
                            queue.appendleft(item)
                        else:
                            queue.append(item)
        return ok, failed, skipped_old, skipped_fresh, errors

    ARTICLE_HINTS = ("/info/", "/content/", "/article/", "/news/", "/tzgg/", "/detail", "/xwzx/")
    # 博达 CMS 常见的正文页：/83/97/c33171a361367/page.htm、/2026/0923/c1847a123456/page.htm
    _CMS_ARTICLE = re.compile(r"/c\d+a\d+(?:[./]|$)")
    _PAGE_ARTICLE = re.compile(r"/\d{3,}/page\.(?:htm|html|shtml)$")
    _LIST_PAGE = re.compile(r"/list\d*\.(?:htm|html|shtml)$|/index(?:_\d+)?\.(?:htm|html|shtml)$")

    @classmethod
    def _article_like(cls, url: str) -> bool:
        """粗略判断是不是「文章正文页」：路径带 CMS 文章 id 或常见栏目，列表页除外。"""
        path = urlparse(url).path.lower()
        if cls._LIST_PAGE.search(path):
            return False
        if any(hint in path for hint in cls.ARTICLE_HINTS):
            return True
        if cls._CMS_ARTICLE.search(path):
            return True
        return bool(cls._PAGE_ARTICLE.search(path))

    @staticmethod
    def _normalize(url: str, base: str) -> str:
        """https 站点上的 http:// 链接统一升级成 https：不少学校站对 http 直接回 502。"""
        if base.startswith("https://") and url.startswith("http://"):
            return "https://" + url[len("http://") :]
        return url

    _COLUMN_ID = re.compile(r"/c(\d+)a\d+")

    @classmethod
    def _section_of(cls, url: str) -> str:
        """栏目标识：博达 CMS 用栏目 id（c33171），其它站退回第一段路径。"""
        path = urlparse(url).path.lower()
        match = cls._COLUMN_ID.search(path)
        if match:
            return f"c{match.group(1)}"
        parts = [part for part in path.split("/") if part]
        return parts[0] if parts else "/"

    @staticmethod
    def _same_site(url: str, base: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        base_host = (urlparse(base).hostname or "").lower()
        return host == base_host or host.endswith("." + base_host)

    @staticmethod
    def _skip_url(url: str) -> bool:
        path = urlparse(url).path.lower()
        query = urlparse(url).query.lower()
        blocked = ("logout", "login", "signin", "search", "print", "rss", "feed")
        return any(token in path for token in blocked) or "searchword" in query

    @staticmethod
    def _load_robots(base: str) -> urllib.robotparser.RobotFileParser | None:
        robots_url = urljoin(base, "/robots.txt")
        parser = urllib.robotparser.RobotFileParser()
        try:
            result = extract.fetch(robots_url, timeout=8, max_bytes=200_000)
            text = result["data"].decode("utf-8", "ignore")
            parser.parse(text.splitlines())
            return parser
        except FetchError:
            parser.parse([])
            return parser
        except Exception:
            return None

    @staticmethod
    def _save_document(conn, site_id: int, url: str, content: dict) -> bool:
        text = content["text"]
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        existing = conn.execute("SELECT id, sha256 FROM documents WHERE url = ?", (url,)).fetchone()
        if existing and existing["sha256"] == sha:
            return False
        title = (content.get("title") or url).strip()[:200]
        published = content.get("published_at")
        now = now_iso()
        if existing:
            doc_id = int(existing["id"])
            conn.execute(
                "UPDATE documents SET title = ?, published_at = ?, fetched_at = ?, content_type = ?, "
                "sha256 = ?, text = ?, char_count = ? WHERE id = ?",
                (
                    title,
                    published,
                    now,
                    content.get("kind", "html"),
                    sha,
                    text,
                    len(text),
                    doc_id,
                ),
            )
            conn.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
        else:
            cur = conn.execute(
                "INSERT INTO documents (site_id, url, title, published_at, fetched_at, content_type, "
                "sha256, text, char_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    site_id,
                    url,
                    title,
                    published,
                    now,
                    content.get("kind", "html"),
                    sha,
                    text,
                    len(text),
                ),
            )
            doc_id = int(cur.lastrowid)
        chunks = extract.chunk_text(text)
        conn.executemany(
            "INSERT INTO chunks (document_id, ordinal, text) VALUES (?, ?, ?)",
            [(doc_id, i, chunk) for i, chunk in enumerate(chunks)],
        )
        return True

    def recent_runs(self, limit: int = 5) -> list[dict]:
        with db() as conn:
            rows = conn.execute(
                "SELECT * FROM crawl_runs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["detail"] = jloads(item.get("detail"), {})
            result.append(item)
        return result


crawl_manager = CrawlManager()
