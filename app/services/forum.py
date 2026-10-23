"""论坛数据序列化、匿名展示与权限辅助。"""
from __future__ import annotations

import json
from typing import Any

from ..db import db
from ..security import anonymous_name, avatar_url
from .notify import push

TAGS = [
    {"key": "经验分享", "desc": "选课、竞赛、保研与实习经验"},
    {"key": "生活分享", "desc": "食堂、宿舍、社团与日常"},
    {"key": "寻物启事", "desc": "失物招领与寻物"},
    {"key": "学习交流", "desc": "课程、作业与学术讨论"},
]

TAG_KEYS = {item["key"] for item in TAGS}


def parse_tags(raw: str | None) -> list[str]:
    try:
        tags = json.loads(raw or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(t) for t in tags if str(t) in TAG_KEYS][:4]


def _author(conn, author_id: int | None, anonymous: bool, post_id: int) -> dict[str, Any]:
    if author_id is None:
        return {
            "id": None,
            "nickname": "已注销用户",
            "avatar": "preset:ghost",
            "avatar_url": "",
            "is_anonymous": False,
            "deleted": True,
        }
    if anonymous:
        return {
            "id": None,
            "nickname": anonymous_name(post_id, author_id),
            "avatar": "preset:ghost",
            "avatar_url": "",
            "is_anonymous": True,
            "deleted": False,
        }
    row = conn.execute("SELECT id, nickname, avatar FROM users WHERE id = ?", (author_id,)).fetchone()
    if not row:
        return {
            "id": None,
            "nickname": "已注销用户",
            "avatar": "preset:ghost",
            "avatar_url": "",
            "is_anonymous": False,
            "deleted": True,
        }
    return {
        "id": row["id"],
        "nickname": row["nickname"],
        "avatar": row["avatar"],
        "avatar_url": avatar_url(row["avatar"]),
        "is_anonymous": False,
        "deleted": False,
    }


def serialize_post(conn, row, viewer_id: int, is_admin: bool = False) -> dict[str, Any]:
    post_id = int(row["id"])
    liked = conn.execute(
        "SELECT 1 FROM post_likes WHERE post_id = ? AND user_id = ?", (post_id, viewer_id)
    ).fetchone()
    bookmarked = conn.execute(
        "SELECT 1 FROM bookmarks WHERE post_id = ? AND user_id = ?", (post_id, viewer_id)
    ).fetchone()
    like_count = conn.execute(
        "SELECT COUNT(*) AS n FROM post_likes WHERE post_id = ?", (post_id,)
    ).fetchone()["n"]
    comment_count = conn.execute(
        "SELECT COUNT(*) AS n FROM comments WHERE post_id = ? AND status = 'visible'", (post_id,)
    ).fetchone()["n"]
    author = _author(conn, row["author_id"], bool(row["anonymous"]), post_id)
    try:
        moderation = json.loads(row["moderation"] or "{}")
    except json.JSONDecodeError:
        moderation = {}
    data = {
        "id": post_id,
        "title": row["title"],
        "body": row["body"],
        "tags": parse_tags(row["tags"]),
        "anonymous": bool(row["anonymous"]),
        "status": row["status"],
        "moderation": {
            "risk": moderation.get("risk", 0),
            "action": moderation.get("action", "ok"),
            "categories": moderation.get("categories", []),
        },
        "views": row["views"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "author": author,
        "likes": int(like_count),
        "comments": int(comment_count),
        "liked": bool(liked),
        "bookmarked": bool(bookmarked),
        "mine": row["author_id"] == viewer_id,
    }
    if is_admin:
        data["author_real_id"] = row["author_id"]
    return data


def serialize_comment(conn, row, viewer_id: int, post_id: int) -> dict[str, Any]:
    comment_id = int(row["id"])
    liked = conn.execute(
        "SELECT 1 FROM comment_likes WHERE comment_id = ? AND user_id = ?",
        (comment_id, viewer_id),
    ).fetchone()
    like_count = conn.execute(
        "SELECT COUNT(*) AS n FROM comment_likes WHERE comment_id = ?", (comment_id,)
    ).fetchone()["n"]
    author = _author(conn, row["author_id"], bool(row["anonymous"]), post_id)
    return {
        "id": comment_id,
        "post_id": int(row["post_id"]),
        "parent_id": row["parent_id"],
        "body": row["body"],
        "anonymous": bool(row["anonymous"]),
        "status": row["status"],
        "created_at": row["created_at"],
        "author": author,
        "likes": int(like_count),
        "liked": bool(liked),
        "mine": row["author_id"] == viewer_id,
    }


def can_view_post(row, viewer_id: int, is_admin: bool) -> bool:
    if row["status"] == "visible":
        return True
    return is_admin or row["author_id"] == viewer_id


def notify_post_author(conn, post, actor: dict, kind: str, text: str, link: str) -> None:
    if not post["author_id"] or post["author_id"] == actor.get("id"):
        return
    payload = {
        "text": text,
        "link": link,
        "actor": {
            "id": actor.get("id"),
            "nickname": actor.get("nickname", ""),
            "avatar": actor.get("avatar", ""),
        },
    }
    push(conn, int(post["author_id"]), kind, payload)


def post_link(post_id: int) -> str:
    return f"#/forum/{post_id}"


def tag_counts() -> list[dict[str, Any]]:
    result = []
    with db() as conn:
        for item in TAGS:
            pattern = f'%"{item["key"]}"%'
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM posts WHERE status = 'visible' AND tags LIKE ?",
                (pattern,),
            ).fetchone()
            result.append({**item, "count": int(row["n"]) if row else 0})
    return result


def ai_review_post(post_id: int) -> None:
    """后台 AI 复筛：只收紧状态，不自动放行规则命中的内容。"""
    from . import moderation

    with db() as conn:
        row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    if not row or row["status"] not in {"visible", "pending"}:
        return
    verdict = moderation.ai_scan(row["title"] + "\n" + row["body"])
    if not verdict:
        return
    new_status = row["status"]
    if verdict["action"] == "block":
        new_status = "hidden"
    elif verdict["action"] == "review" and row["status"] == "visible":
        new_status = "pending"
    if new_status == row["status"]:
        return
    try:
        previous = json.loads(row["moderation"] or "{}")
    except json.JSONDecodeError:
        previous = {}
    previous.update(
        {
            "risk": max(int(previous.get("risk", 0)), verdict["risk"]),
            "action": verdict["action"],
            "categories": sorted(set(previous.get("categories", [])) | set(verdict["categories"])),
            "ai_reason": verdict.get("reason", ""),
            "source": "rule+ai",
        }
    )
    with db() as conn:
        conn.execute(
            "UPDATE posts SET status = ?, moderation = ? WHERE id = ?",
            (new_status, json.dumps(previous, ensure_ascii=False), post_id),
        )
        push(
            conn,
            int(row["author_id"]),
            "moderation",
            {
                "text": "你的帖子经 AI 复核后进入人工审核，可提交申诉说明情况。",
                "link": post_link(post_id),
            },
        )


def ai_review_comment(comment_id: int) -> None:
    from . import moderation

    with db() as conn:
        row = conn.execute("SELECT * FROM comments WHERE id = ?", (comment_id,)).fetchone()
    if not row or row["status"] not in {"visible", "pending"}:
        return
    verdict = moderation.ai_scan(row["body"])
    if not verdict:
        return
    new_status = row["status"]
    if verdict["action"] == "block":
        new_status = "hidden"
    elif verdict["action"] == "review" and row["status"] == "visible":
        new_status = "pending"
    if new_status == row["status"]:
        return
    try:
        previous = json.loads(row["moderation"] or "{}")
    except json.JSONDecodeError:
        previous = {}
    previous.update(
        {
            "risk": max(int(previous.get("risk", 0)), verdict["risk"]),
            "action": verdict["action"],
            "categories": sorted(set(previous.get("categories", [])) | set(verdict["categories"])),
            "ai_reason": verdict.get("reason", ""),
        }
    )
    with db() as conn:
        conn.execute(
            "UPDATE comments SET status = ?, moderation = ? WHERE id = ?",
            (new_status, json.dumps(previous, ensure_ascii=False), comment_id),
        )
