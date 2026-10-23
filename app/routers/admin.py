"""管理员：内容审核、举报/申诉处理、概览与审计。"""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..db import db
from ..security import avatar_url, get_current_user
from ..services.forum import invalidate_board_counts, post_link, set_announcement
from ..services.notify import push
from ..timeutil import iso, now_utc

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


class ModerationAction(BaseModel):
    action: Literal["approve", "hide", "remove"]
    note: str = Field(default="", max_length=300)


class ReportResolve(BaseModel):
    action: Literal["ignore", "hide", "remove", "warn"] = "ignore"
    reply: str = Field(default="", max_length=500)


class AppealResolve(BaseModel):
    action: Literal["accept", "reject"]
    reply: str = Field(default="", max_length=500)


class AnnouncementIn(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    link: str = Field(default="", max_length=300)
    title: str = Field(default="全站公告", max_length=20)


def _audit(conn, actor_id: int, action: str, target: str, detail: dict) -> None:
    conn.execute(
        "INSERT INTO audit_log (actor_id, action, target, detail, created_at) VALUES (?, ?, ?, ?, ?)",
        (actor_id, action, target, json.dumps(detail, ensure_ascii=False), iso(now_utc())),
    )


@router.get("/overview")
def overview(admin: dict = Depends(_admin)):
    with db() as conn:
        def scalar(sql: str, *params) -> int:
            row = conn.execute(sql, params).fetchone()
            return int(row[0]) if row else 0

        last_crawl = conn.execute(
            "SELECT * FROM crawl_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return {
            "users": scalar("SELECT COUNT(*) FROM users"),
            "posts": scalar("SELECT COUNT(*) FROM posts WHERE status = 'visible'"),
            "comments": scalar("SELECT COUNT(*) FROM comments WHERE status = 'visible'"),
            "pending_posts": scalar("SELECT COUNT(*) FROM posts WHERE status IN ('pending','hidden')"),
            "pending_comments": scalar(
                "SELECT COUNT(*) FROM comments WHERE status IN ('pending','hidden')"
            ),
            "open_reports": scalar("SELECT COUNT(*) FROM reports WHERE status = 'open'"),
            "open_appeals": scalar("SELECT COUNT(*) FROM appeals WHERE status = 'open'"),
            "documents": scalar("SELECT COUNT(*) FROM documents"),
            "chunks": scalar("SELECT COUNT(*) FROM chunks"),
            "sites": scalar("SELECT COUNT(*) FROM sites WHERE enabled = 1"),
            "last_crawl": (
                {
                    "id": last_crawl["id"],
                    "status": last_crawl["status"],
                    "started_at": last_crawl["started_at"],
                    "finished_at": last_crawl["finished_at"],
                    "pages_ok": last_crawl["pages_ok"],
                    "pages_failed": last_crawl["pages_failed"],
                }
                if last_crawl
                else None
            ),
        }


@router.post("/announcement")
def update_announcement(payload: AnnouncementIn, admin: dict = Depends(_admin)):
    """更新论坛首页的「全站公告」。"""
    announcement = set_announcement(payload.text, payload.link, payload.title)
    with db() as conn:
        _audit(conn, admin["id"], "forum.announcement", "forum", payload.model_dump())
    return {"announcement": announcement, "message": "公告已更新"}


@router.get("/moderation")
def moderation_queue(
    kind: Literal["posts", "comments"] = "posts",
    status: Literal["pending", "hidden", "removed", "all"] = "pending",
    page: int = 1,
    admin: dict = Depends(_admin),
):
    page = max(1, min(page, 200))
    offset = (page - 1) * 50
    with db() as conn:
        if kind == "posts":
            where = "p.status = ?" if status != "all" else "p.status != 'visible'"
            params: list[object] = [status] if status != "all" else []
            total = conn.execute(
                f"SELECT COUNT(*) AS n FROM posts p WHERE {where}", tuple(params)
            ).fetchone()["n"]
            rows = conn.execute(
                f"SELECT p.*, u.nickname AS author_nickname, u.avatar AS author_avatar "
                f"FROM posts p LEFT JOIN users u ON u.id = p.author_id WHERE {where} "
                f"ORDER BY p.created_at DESC LIMIT 50 OFFSET ?",
                tuple(params) + (offset,),
            ).fetchall()
            items = []
            for row in rows:
                try:
                    moderation = json.loads(row["moderation"] or "{}")
                except json.JSONDecodeError:
                    moderation = {}
                items.append(
                    {
                        "kind": "post",
                        "id": row["id"],
                        "title": row["title"],
                        "body": row["body"],
                        "tags": json.loads(row["tags"] or "[]"),
                        "status": row["status"],
                        "anonymous": bool(row["anonymous"]),
                        "author": {
                            "id": row["author_id"],
                            "nickname": row["author_nickname"] or "已注销用户",
                            "avatar": row["author_avatar"] or "preset:ghost",
                            "avatar_url": avatar_url(row["author_avatar"] or ""),
                        },
                        "moderation": moderation,
                        "created_at": row["created_at"],
                        "link": post_link(row["id"]),
                    }
                )
        else:
            where = "c.status = ?" if status != "all" else "c.status != 'visible'"
            params = [status] if status != "all" else []
            total = conn.execute(
                f"SELECT COUNT(*) AS n FROM comments c WHERE {where}", tuple(params)
            ).fetchone()["n"]
            rows = conn.execute(
                f"SELECT c.*, u.nickname AS author_nickname, p.title AS post_title "
                f"FROM comments c LEFT JOIN users u ON u.id = c.author_id "
                f"LEFT JOIN posts p ON p.id = c.post_id WHERE {where} "
                f"ORDER BY c.created_at DESC LIMIT 50 OFFSET ?",
                tuple(params) + (offset,),
            ).fetchall()
            items = []
            for row in rows:
                try:
                    moderation = json.loads(row["moderation"] or "{}")
                except json.JSONDecodeError:
                    moderation = {}
                items.append(
                    {
                        "kind": "comment",
                        "id": row["id"],
                        "post_id": row["post_id"],
                        "post_title": row["post_title"],
                        "body": row["body"],
                        "status": row["status"],
                        "anonymous": bool(row["anonymous"]),
                        "author": {
                            "id": row["author_id"],
                            "nickname": row["author_nickname"] or "已注销用户",
                            "avatar": "preset:ghost" if row["anonymous"] else "preset:ocean",
                        },
                        "moderation": moderation,
                        "created_at": row["created_at"],
                        "link": post_link(int(row["post_id"])),
                    }
                )
    return {"items": items, "total": int(total), "page": page}


@router.post("/moderation/{kind}/{target_id}")
def moderate(
    kind: Literal["post", "posts", "comment", "comments"],
    target_id: int,
    payload: ModerationAction,
    admin: dict = Depends(_admin),
):
    table = "posts" if kind in {"post", "posts"} else "comments"
    is_post = table == "posts"
    status_map = {"approve": "visible", "hide": "hidden", "remove": "removed"}
    new_status = status_map[payload.action]
    with db() as conn:
        row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (target_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="内容不存在")
        try:
            moderation = json.loads(row["moderation"] or "{}")
        except json.JSONDecodeError:
            moderation = {}
        moderation["admin_action"] = payload.action
        if payload.note:
            moderation["admin_note"] = payload.note[:300]
        moderation["reviewed_by"] = admin["id"]
        conn.execute(
            f"UPDATE {table} SET status = ?, moderation = ? WHERE id = ?",
            (new_status, json.dumps(moderation, ensure_ascii=False), target_id),
        )
        link = post_link(target_id if is_post else int(row["post_id"]))
        author_id = row["author_id"]
        if author_id:
            label = "帖子" if is_post else "评论"
            text_map = {
                "approve": f"你的{label}已通过审核，现在对其他人可见。",
                "hide": f"你的{label}未通过审核，已被暂时隐藏。若有异议可提交申诉。",
                "remove": f"你的{label}已被管理员删除。",
            }
            push(conn, int(author_id), "moderation", {"text": text_map[payload.action], "link": link})
        _audit(conn, admin["id"], f"moderation.{payload.action}", f"{kind}:{target_id}", payload.model_dump())
    if is_post:
        invalidate_board_counts()
    return {"ok": True, "status": new_status}


@router.get("/reports")
def reports(
    status: Literal["open", "resolved", "all"] = "open",
    admin: dict = Depends(_admin),
):
    with db() as conn:
        where = "r.status = ?" if status != "all" else "1=1"
        params: tuple = (status,) if status != "all" else ()
        rows = conn.execute(
            f"SELECT r.*, u.nickname AS reporter_nickname FROM reports r "
            f"LEFT JOIN users u ON u.id = r.reporter_id WHERE {where} "
            f"ORDER BY r.created_at DESC LIMIT 100",
            params,
        ).fetchall()
        items = []
        for row in rows:
            preview = ""
            link = ""
            if row["target_type"] == "post":
                target = conn.execute("SELECT title, status FROM posts WHERE id = ?", (row["target_id"],)).fetchone()
                if target:
                    preview = f"[{target['status']}] {target['title']}"
                link = post_link(int(row["target_id"]))
            elif row["target_type"] == "comment":
                target = conn.execute(
                    "SELECT c.body, c.status, c.post_id FROM comments c WHERE c.id = ?",
                    (row["target_id"],),
                ).fetchone()
                if target:
                    preview = f"[{target['status']}] {target['body'][:80]}"
                    link = post_link(int(target["post_id"]))
            else:
                target = conn.execute("SELECT nickname FROM users WHERE id = ?", (row["target_id"],)).fetchone()
                if target:
                    preview = f"用户：{target['nickname']}"
                link = f"#/forum/user/{row['target_id']}"
            items.append(
                {
                    "id": row["id"],
                    "target_type": row["target_type"],
                    "target_id": row["target_id"],
                    "reason": row["reason"],
                    "detail": row["detail"],
                    "status": row["status"],
                    "action": row["action"],
                    "created_at": row["created_at"],
                    "reporter": row["reporter_nickname"] or "已注销用户",
                    "preview": preview,
                    "link": link,
                }
            )
    return {"items": items}


@router.post("/reports/{report_id}")
def resolve_report(report_id: int, payload: ReportResolve, admin: dict = Depends(_admin)):
    with db() as conn:
        report = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        if not report:
            raise HTTPException(status_code=404, detail="举报不存在")
        if report["status"] != "open":
            raise HTTPException(status_code=400, detail="该举报已处理")
        target_author = None
        link = ""
        if payload.action in {"hide", "remove"}:
            status = "hidden" if payload.action == "hide" else "removed"
            if report["target_type"] == "post":
                target = conn.execute("SELECT author_id FROM posts WHERE id = ?", (report["target_id"],)).fetchone()
                if target:
                    conn.execute("UPDATE posts SET status = ? WHERE id = ?", (status, report["target_id"]))
                    target_author = target["author_id"]
                link = post_link(int(report["target_id"]))
            elif report["target_type"] == "comment":
                target = conn.execute("SELECT author_id, post_id FROM comments WHERE id = ?", (report["target_id"],)).fetchone()
                if target:
                    conn.execute("UPDATE comments SET status = ? WHERE id = ?", (status, report["target_id"]))
                    target_author = target["author_id"]
                    link = post_link(int(target["post_id"]))
        elif payload.action == "warn":
            if report["target_type"] == "user":
                target_author = report["target_id"]
            elif report["target_type"] == "post":
                target = conn.execute("SELECT author_id FROM posts WHERE id = ?", (report["target_id"],)).fetchone()
                target_author = target["author_id"] if target else None
            elif report["target_type"] == "comment":
                target = conn.execute("SELECT author_id FROM comments WHERE id = ?", (report["target_id"],)).fetchone()
                target_author = target["author_id"] if target else None
        conn.execute(
            "UPDATE reports SET status = 'resolved', action = ?, handled_by = ?, handled_at = ? WHERE id = ?",
            (payload.action, admin["id"], iso(now_utc()), report_id),
        )
        if report["reporter_id"]:
            text = "你的举报已处理。" + (payload.reply[:200] if payload.reply else "")
            push(conn, int(report["reporter_id"]), "report", {"text": text, "link": link or "#/forum"})
        if target_author and target_author != report["reporter_id"]:
            action_text = {
                "hide": "你的内容因被举报已被隐藏。",
                "remove": "你的内容因被举报已被删除。",
                "warn": "你收到一条管理员警告，请遵守社区规范。",
            }.get(payload.action)
            if action_text:
                push(conn, int(target_author), "moderation", {"text": action_text, "link": link or "#/forum"})
        _audit(conn, admin["id"], "report.resolve", f"report:{report_id}", payload.model_dump())
    invalidate_board_counts()
    return {"ok": True}


@router.get("/appeals")
def appeals(status: Literal["open", "resolved", "all"] = "open", admin: dict = Depends(_admin)):
    with db() as conn:
        where = "a.status = ?" if status != "all" else "1=1"
        params: tuple = (status,) if status != "all" else ()
        rows = conn.execute(
            f"SELECT a.*, u.nickname FROM appeals a LEFT JOIN users u ON u.id = a.user_id "
            f"WHERE {where} ORDER BY a.created_at DESC LIMIT 100",
            params,
        ).fetchall()
        items = []
        for row in rows:
            if row["target_type"] == "post":
                target = conn.execute("SELECT title, status FROM posts WHERE id = ?", (row["target_id"],)).fetchone()
                preview = f"[{target['status']}] {target['title']}" if target else "内容已不存在"
                link = post_link(int(row["target_id"]))
            else:
                target = conn.execute(
                    "SELECT body, status, post_id FROM comments WHERE id = ?", (row["target_id"],)
                ).fetchone()
                preview = f"[{target['status']}] {target['body'][:80]}" if target else "内容已不存在"
                link = post_link(int(target["post_id"])) if target else "#/forum"
            items.append(
                {
                    "id": row["id"],
                    "user_id": row["user_id"],
                    "nickname": row["nickname"] or "已注销用户",
                    "target_type": row["target_type"],
                    "target_id": row["target_id"],
                    "reason": row["reason"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "preview": preview,
                    "link": link,
                }
            )
    return {"items": items}


@router.post("/appeals/{appeal_id}")
def resolve_appeal(appeal_id: int, payload: AppealResolve, admin: dict = Depends(_admin)):
    with db() as conn:
        appeal = conn.execute("SELECT * FROM appeals WHERE id = ?", (appeal_id,)).fetchone()
        if not appeal:
            raise HTTPException(status_code=404, detail="申诉不存在")
        if appeal["status"] != "open":
            raise HTTPException(status_code=400, detail="该申诉已处理")
        if payload.action == "accept":
            if appeal["target_type"] == "post":
                conn.execute("UPDATE posts SET status = 'visible' WHERE id = ?", (appeal["target_id"],))
            else:
                conn.execute("UPDATE comments SET status = 'visible' WHERE id = ?", (appeal["target_id"],))
        conn.execute(
            "UPDATE appeals SET status = ?, reply = ?, handled_by = ?, handled_at = ? WHERE id = ?",
            (
                "accepted" if payload.action == "accept" else "rejected",
                payload.reply,
                admin["id"],
                iso(now_utc()),
                appeal_id,
            ),
        )
        text = (
            "你的申诉已通过，内容已恢复。"
            if payload.action == "accept"
            else "你的申诉未通过。" + (payload.reply[:200] if payload.reply else "")
        )
        push(conn, int(appeal["user_id"]), "appeal", {"text": text, "link": "#/forum"})
        _audit(conn, admin["id"], f"appeal.{payload.action}", f"appeal:{appeal_id}", payload.model_dump())
    invalidate_board_counts()
    return {"ok": True}


@router.get("/users")
def users(q: str = "", page: int = 1, admin: dict = Depends(_admin)):
    page = max(1, min(page, 200))
    needle = f"%{q.strip()[:40]}%"
    with db() as conn:
        rows = conn.execute(
            "SELECT u.id, u.nickname, u.avatar, u.major, u.grade, u.role, u.created_at, "
            "(SELECT COUNT(*) FROM posts p WHERE p.author_id = u.id AND p.status = 'visible') AS posts "
            "FROM users u WHERE (? = '%%' OR u.nickname LIKE ?) ORDER BY u.id DESC LIMIT 50 OFFSET ?",
            (needle, needle, (page - 1) * 50),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM users u WHERE (? = '%%' OR u.nickname LIKE ?)",
            (needle, needle),
        ).fetchone()["n"]
    return {
        "items": [
            {
                "id": row["id"],
                "nickname": row["nickname"],
                "avatar_url": avatar_url(row["avatar"]),
                "major": row["major"],
                "grade": row["grade"],
                "role": row["role"],
                "posts": int(row["posts"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ],
        "total": int(total),
        "page": page,
    }


@router.get("/audit")
def audit(admin: dict = Depends(_admin)):
    with db() as conn:
        rows = conn.execute(
            "SELECT a.*, u.nickname FROM audit_log a LEFT JOIN users u ON u.id = a.actor_id "
            "ORDER BY a.id DESC LIMIT 50"
        ).fetchall()
    items = []
    for row in rows:
        try:
            detail = json.loads(row["detail"] or "{}")
        except json.JSONDecodeError:
            detail = {}
        items.append(
            {
                "id": row["id"],
                "actor": row["nickname"] or "系统",
                "action": row["action"],
                "target": row["target"],
                "detail": detail,
                "created_at": row["created_at"],
            }
        )
    return {"items": items}
