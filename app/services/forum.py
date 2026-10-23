"""论坛数据序列化、匿名展示与权限辅助。"""
from __future__ import annotations

import json
import time
from datetime import timedelta
from typing import Any

from ..db import db
from ..security import anonymous_name, avatar_url
from ..timeutil import iso, now_utc
from .notify import push

TAGS = [
    {"key": "经验分享", "desc": "选课、竞赛、保研与实习经验"},
    {"key": "生活分享", "desc": "食堂、宿舍、社团与日常"},
    {"key": "寻物启事", "desc": "失物招领与寻物"},
    {"key": "学习交流", "desc": "课程、作业与学术讨论"},
]

TAG_KEYS = {item["key"] for item in TAGS}

# 版面：帖子归属的大类（参考常见校园 BBS 的分区方式）
BOARDS = [
    {"key": "study", "name": "学习科研", "group": "学习", "desc": "课程、作业、科研与学术讨论"},
    {"key": "exam", "name": "考研升学", "group": "学习", "desc": "考研、保研、出国与实习经验"},
    {"key": "campus", "name": "校园信息", "group": "校园", "desc": "通知、后勤、食堂与社团活动"},
    {"key": "lost", "name": "寻物启事", "group": "校园", "desc": "失物招领与寻物"},
    {"key": "life", "name": "生活分享", "group": "生活", "desc": "日常、美食、旅行与吐槽"},
    {"key": "tech", "name": "数码技术", "group": "兴趣", "desc": "编程、数码与效率工具"},
    {"key": "trade", "name": "二手交易", "group": "交易", "desc": "闲置转让与求购"},
]

BOARD_KEYS = {item["key"] for item in BOARDS}
BOARD_NAMES = {item["key"]: item["name"] for item in BOARDS}
TAG_TO_BOARD = {"学习交流": "study", "经验分享": "exam", "生活分享": "life", "寻物启事": "lost"}


def resolve_board(board: str | None, tags: list[str]) -> str:
    """显式指定优先，否则按标签推导，最后落到「生活分享」。"""
    if board in BOARD_KEYS:
        return board
    for tag in tags:
        if tag in TAG_TO_BOARD:
            return TAG_TO_BOARD[tag]
    return "life"


BOARD_COUNTS_TTL = 20.0
_BOARD_COUNTS: dict[str, Any] = {"at": 0.0, "rows": None}

# 旧帖子的 board 为空：按标签推导，和列表筛选的口径保持一致
_BOARD_OF_POST_SQL = """
CASE
    WHEN board != '' THEN board
    WHEN tags LIKE '%"经验分享"%' THEN 'exam'
    WHEN tags LIKE '%"学习交流"%' THEN 'study'
    WHEN tags LIKE '%"寻物启事"%' THEN 'lost'
    WHEN tags LIKE '%"生活分享"%' THEN 'life'
    ELSE 'life'
END
"""


def board_counts(force: bool = False) -> list[dict[str, Any]]:
    """版面帖子数：20 秒缓存，发帖/删帖时主动失效。"""
    now = time.monotonic()
    cached = _BOARD_COUNTS["rows"]
    if cached is not None and not force and now - _BOARD_COUNTS["at"] < BOARD_COUNTS_TTL:
        return [dict(item) for item in cached]
    counts: dict[str, int] = {}
    with db() as conn:
        rows = conn.execute(
            f"SELECT {_BOARD_OF_POST_SQL} AS board_key, COUNT(*) AS n FROM posts "
            "WHERE status = 'visible' GROUP BY board_key"
        ).fetchall()
        for row in rows:
            counts[row["board_key"] or ""] = int(row["n"])
    result = [{**item, "count": counts.get(item["key"], 0)} for item in BOARDS]
    _BOARD_COUNTS["rows"] = result
    _BOARD_COUNTS["at"] = now
    return [dict(item) for item in result]


def invalidate_board_counts() -> None:
    _BOARD_COUNTS["at"] = 0.0


# ------------------------------------------------------------ 全站公告
ANNOUNCEMENT_KEY = "forum_announcement"
DEFAULT_ANNOUNCEMENT = {
    "title": "全站公告",
    "text": "欢迎来到 ECNU 小助手校园论坛：请遵守社区规范，友善讨论；广告、人身攻击与隐私泄露会被折叠或删除。",
    "link": "",
    "updated_at": "",
}


def get_announcement() -> dict[str, Any]:
    with db() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (ANNOUNCEMENT_KEY,)).fetchone()
    if not row:
        return dict(DEFAULT_ANNOUNCEMENT)
    try:
        data = json.loads(row["value"])
    except (TypeError, json.JSONDecodeError):
        return dict(DEFAULT_ANNOUNCEMENT)
    if not isinstance(data, dict):
        return dict(DEFAULT_ANNOUNCEMENT)
    return {
        "title": str(data.get("title") or DEFAULT_ANNOUNCEMENT["title"])[:20],
        "text": str(data.get("text") or DEFAULT_ANNOUNCEMENT["text"])[:300],
        "link": str(data.get("link") or "")[:300],
        "updated_at": str(data.get("updated_at") or ""),
    }


def set_announcement(text: str, link: str = "", title: str = "全站公告") -> dict[str, Any]:
    payload = {
        "title": (title or "全站公告").strip()[:20] or "全站公告",
        "text": text.strip()[:300],
        "link": link.strip()[:300],
        "updated_at": iso(now_utc()),
    }
    with db() as conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (ANNOUNCEMENT_KEY, json.dumps(payload, ensure_ascii=False)),
        )
    return payload


# ------------------------------------------------------------ 论坛首页
HOME_WINDOW_DAYS = 30
HOME_HOT_SCORE_SQL = (
    "(SELECT COUNT(*) FROM post_likes pl WHERE pl.post_id = p.id) * 3 + "
    "(SELECT COUNT(*) FROM comments c WHERE c.post_id = p.id AND c.status = 'visible') * 2 + "
    "p.views * 0.02"
)


def _mark(conn, rows, viewer_id: int, is_admin: bool) -> list[dict[str, Any]]:
    items = []
    for row in rows:
        item = serialize_post(conn, row, viewer_id, is_admin)
        item["score"] = round(float(row["score"] or 0), 1)
        items.append(item)
    return items


def home(viewer_id: int, is_admin: bool = False) -> dict[str, Any]:
    """论坛首页聚合：全站公告 + 轮播（热度前 4）+ 推荐阅读（其后 5 条）+ 站点统计。"""
    since = iso(now_utc() - timedelta(days=HOME_WINDOW_DAYS))
    day_ago = iso(now_utc() - timedelta(days=1))
    with db() as conn:
        hot_rows = conn.execute(
            f"SELECT p.*, {HOME_HOT_SCORE_SQL} AS score FROM posts p "
            "WHERE p.status = 'visible' AND p.created_at >= ? "
            "ORDER BY score DESC, p.created_at DESC LIMIT 4",
            (since,),
        ).fetchall()
        # 冷启动（几乎没有互动）时用最新帖子补位，轮播不会空着
        if len(hot_rows) < 3:
            taken = [int(row["id"]) for row in hot_rows]
            spots = 3 - len(hot_rows)
            extra = conn.execute(
                "SELECT p.*, 0 AS score FROM posts p WHERE p.status = 'visible' "
                + (f"AND p.id NOT IN ({','.join('?' * len(taken))}) " if taken else "")
                + "ORDER BY p.created_at DESC LIMIT ?",
                (*taken, spots),
            ).fetchall()
            hot_rows = list(hot_rows) + list(extra)
        hot_ids = [int(row["id"]) for row in hot_rows]
        reco_rows = conn.execute(
            f"SELECT p.*, {HOME_HOT_SCORE_SQL} AS score FROM posts p "
            "WHERE p.status = 'visible' AND p.created_at >= ? "
            + (f"AND p.id NOT IN ({','.join('?' * len(hot_ids))}) " if hot_ids else "")
            + "ORDER BY score DESC, p.created_at DESC LIMIT 5",
            (since, *hot_ids),
        ).fetchall()
        stats = {
            "posts": int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM posts WHERE status = 'visible'"
                ).fetchone()["n"]
            ),
            "today_posts": int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM posts WHERE status = 'visible' AND created_at >= ?",
                    (day_ago,),
                ).fetchone()["n"]
            ),
            "comments": int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM comments WHERE status = 'visible'"
                ).fetchone()["n"]
            ),
            "users": int(conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]),
        }
        carousel = _mark(conn, hot_rows, viewer_id, is_admin)
        recommended = _mark(conn, reco_rows, viewer_id, is_admin)
    return {
        "announcement": get_announcement(),
        "carousel": carousel,
        "recommended": recommended,
        "stats": stats,
        "window_days": HOME_WINDOW_DAYS,
    }


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
        "board": row["board"] or resolve_board("", parse_tags(row["tags"])),
        "board_name": BOARD_NAMES.get(
            row["board"] or resolve_board("", parse_tags(row["tags"])), "生活分享"
        ),
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
