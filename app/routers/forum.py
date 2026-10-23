"""校园论坛：发帖、评论、匿名、点赞、收藏、举报、申诉、关注与用户主页。"""
from __future__ import annotations

import json
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..config import settings
from ..db import db
from ..security import enforce_rate, get_current_user, public_user
from ..services import forum as forum_service
from ..services import moderation
from ..services.forum import TAG_KEYS, TAGS

router = APIRouter(prefix="/api/forum", tags=["forum"])

REPORT_REASONS = ("色情低俗", "暴力血腥", "违法违规", "诈骗广告", "人身攻击", "隐私泄露", "其他")
STATUS_MESSAGES = {
    "visible": "发布成功",
    "pending": "已提交，等待人工审核后对其他人可见",
    "hidden": "内容疑似违规，已转入人工复核；如果判断有误，可在帖子页提交申诉",
}


class PostCreate(BaseModel):
    title: str = Field(min_length=4, max_length=80)
    body: str = Field(min_length=1, max_length=8000)
    tags: list[str] = Field(min_length=1, max_length=3)
    board: str = Field(default="", max_length=20)
    anonymous: bool = False


class PostUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=4, max_length=80)
    body: str | None = Field(default=None, min_length=1, max_length=8000)
    tags: list[str] | None = Field(default=None, min_length=1, max_length=3)
    board: str | None = Field(default=None, max_length=20)
    anonymous: bool | None = None


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    anonymous: bool = False
    parent_id: int | None = None


class ReportIn(BaseModel):
    target_type: Literal["post", "comment", "user"]
    target_id: int
    reason: str = Field(min_length=1, max_length=20)
    detail: str = Field(default="", max_length=500)


class AppealIn(BaseModel):
    target_type: Literal["post", "comment"]
    target_id: int
    reason: str = Field(min_length=5, max_length=500)


def _clean_tags(tags: list[str]) -> list[str]:
    cleaned = []
    for tag in tags:
        if tag not in TAG_KEYS:
            raise HTTPException(status_code=400, detail="帖子标签无效")
        if tag not in cleaned:
            cleaned.append(tag)
    if not cleaned:
        raise HTTPException(status_code=400, detail="请至少选择一个标签")
    return cleaned


def _get_post(conn, post_id: int, viewer_id: int, is_admin: bool):
    row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="帖子不存在")
    if not forum_service.can_view_post(row, viewer_id, is_admin):
        raise HTTPException(status_code=404, detail="帖子不存在或正在审核")
    return row


def _moderation_payload(verdict: dict) -> str:
    return json.dumps(
        {
            "risk": verdict.get("risk", 0),
            "action": verdict.get("action", "ok"),
            "categories": verdict.get("categories", []),
            "source": verdict.get("source", "rule"),
        },
        ensure_ascii=False,
    )


@router.get("/tags")
def list_tags():
    return {"tags": forum_service.tag_counts(), "all": TAGS}


@router.get("/boards")
def list_boards():
    return {"boards": forum_service.board_counts()}


@router.get("/home")
def forum_home(user: dict = Depends(get_current_user)):
    """论坛首页：全站公告、轮播、推荐阅读与站点统计。"""
    return forum_service.home(user["id"], user["role"] == "admin")


@router.get("/posts")
def list_posts(
    tag: str = "",
    board: str = "",
    range: Literal["all", "day", "week", "month"] = "all",
    sort: Literal["new", "hot", "following"] = "new",
    q: str = "",
    page: int = 1,
    size: int = 10,
    author: int = 0,
    user: dict = Depends(get_current_user),
):
    page = max(1, min(page, 500))
    size = max(1, min(size, 20))
    conditions = ["(p.status = 'visible' OR p.author_id = ?)"]
    params: list[object] = [user["id"]]
    if tag:
        if tag not in TAG_KEYS:
            raise HTTPException(status_code=400, detail="标签无效")
        conditions.append("p.tags LIKE ?")
        params.append(f'%"{tag}"%')
    if board:
        if board not in forum_service.BOARD_KEYS:
            raise HTTPException(status_code=400, detail="版面无效")
        # 旧帖子 board 为空：按标签推导出的版面也算进来
        board_tags = [
            key for key, value in forum_service.TAG_TO_BOARD.items() if value == board
        ]
        clauses = ["p.board = ?"]
        params.append(board)
        if board_tags:
            clauses.append(
                "(p.board = '' AND ("
                + " OR ".join("p.tags LIKE ?" for _ in board_tags)
                + "))"
            )
            params.extend(f'%"{item}"%' for item in board_tags)
        conditions.append("(" + " OR ".join(clauses) + ")")
    if range != "all":
        from ..timeutil import iso, now_utc

        days = {"day": 1, "week": 7, "month": 30}[range]
        conditions.append("p.created_at >= ?")
        params.append(iso(now_utc() - timedelta(days=days)))
    if q.strip():
        needle = f"%{q.strip()[:50]}%"
        conditions.append("(p.title LIKE ? OR p.body LIKE ?)")
        params.extend([needle, needle])
    if author:
        conditions.append("p.author_id = ?")
        params.append(author)
    if sort == "following":
        conditions.append(
            "(p.author_id IN (SELECT followee_id FROM follows WHERE follower_id = ?) OR p.author_id = ?)"
        )
        params.extend([user["id"], user["id"]])
    where = " AND ".join(conditions)
    order = "p.created_at DESC"
    if sort == "hot":
        order = (
            "((SELECT COUNT(*) FROM post_likes pl WHERE pl.post_id = p.id) * 3 + "
            "(SELECT COUNT(*) FROM comments c WHERE c.post_id = p.id AND c.status = 'visible') * 2 + "
            "p.views * 0.02) DESC, p.created_at DESC"
        )
    with db() as conn:
        total_row = conn.execute(
            f"SELECT COUNT(*) AS n FROM posts p WHERE {where}", tuple(params)
        ).fetchone()
        total = int(total_row["n"]) if total_row else 0
        rows = conn.execute(
            f"SELECT p.* FROM posts p WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
            tuple(params) + (size, (page - 1) * size),
        ).fetchall()
        items = [
            forum_service.serialize_post(conn, row, user["id"], user["role"] == "admin")
            for row in rows
        ]
    return {
        "items": items,
        "page": page,
        "size": size,
        "total": total,
        "has_more": page * size < total,
        "tags": forum_service.tag_counts(),
    }


@router.post("/posts", status_code=201)
def create_post(
    payload: PostCreate,
    request: Request,
    background: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    enforce_rate(request, "forum-post", 8, 600)
    tags = _clean_tags(payload.tags)
    title = payload.title.strip()
    body = payload.body.strip()
    if not title or not body:
        raise HTTPException(status_code=400, detail="标题和正文不能为空")
    verdict = moderation.scan(title + "\n" + body)
    status = moderation.status_for(verdict)
    from ..timeutil import iso, now_utc

    with db() as conn:
        board = forum_service.resolve_board(payload.board, tags)
        cur = conn.execute(
            "INSERT INTO posts (author_id, title, body, tags, board, anonymous, status, moderation, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user["id"],
                title,
                body,
                json.dumps(tags, ensure_ascii=False),
                board,
                1 if payload.anonymous else 0,
                status,
                _moderation_payload(verdict),
                iso(now_utc()),
                iso(now_utc()),
            ),
        )
        post_id = int(cur.lastrowid)
        row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        post = forum_service.serialize_post(conn, row, user["id"], user["role"] == "admin")
    if settings.moderation_api_key and status != "hidden":
        background.add_task(forum_service.ai_review_post, post_id)
    forum_service.invalidate_board_counts()
    return {"post": post, "message": STATUS_MESSAGES[status]}


@router.get("/posts/{post_id}")
def get_post(post_id: int, user: dict = Depends(get_current_user)):
    is_admin = user["role"] == "admin"
    with db() as conn:
        row = _get_post(conn, post_id, user["id"], is_admin)
        if row["author_id"] != user["id"]:
            conn.execute("UPDATE posts SET views = views + 1 WHERE id = ?", (post_id,))
            row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        post = forum_service.serialize_post(conn, row, user["id"], is_admin)
        if is_admin:
            comment_rows = conn.execute(
                "SELECT * FROM comments WHERE post_id = ? ORDER BY created_at", (post_id,)
            ).fetchall()
        else:
            comment_rows = conn.execute(
                "SELECT * FROM comments WHERE post_id = ? AND (status = 'visible' OR author_id = ?) "
                "ORDER BY created_at",
                (post_id, user["id"]),
            ).fetchall()
        comments = [
            forum_service.serialize_comment(conn, c, user["id"], post_id) for c in comment_rows
        ]
    return {"post": post, "comments": comments}


@router.patch("/posts/{post_id}")
def update_post(
    post_id: int,
    payload: PostUpdate,
    request: Request,
    background: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    enforce_rate(request, "forum-edit", 20, 600)
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="没有需要修改的内容")
    with db() as conn:
        row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="帖子不存在")
        if row["author_id"] != user["id"] and user["role"] != "admin":
            raise HTTPException(status_code=403, detail="只能编辑自己的帖子")
        title = (fields.get("title") or row["title"]).strip()
        body = (fields.get("body") or row["body"]).strip()
        tags = _clean_tags(fields["tags"]) if fields.get("tags") is not None else forum_service.parse_tags(row["tags"])
        anonymous = fields.get("anonymous", bool(row["anonymous"]))
        verdict = moderation.scan(title + "\n" + body)
        status = moderation.status_for(verdict)
        from ..timeutil import iso, now_utc

        conn.execute(
            "UPDATE posts SET title = ?, body = ?, tags = ?, anonymous = ?, status = ?, "
            "moderation = ?, updated_at = ? WHERE id = ?",
            (
                title,
                body,
                json.dumps(tags, ensure_ascii=False),
                1 if anonymous else 0,
                status,
                _moderation_payload(verdict),
                iso(now_utc()),
                post_id,
            ),
        )
        row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        post = forum_service.serialize_post(conn, row, user["id"], user["role"] == "admin")
    if settings.moderation_api_key and status != "hidden":
        background.add_task(forum_service.ai_review_post, post_id)
    forum_service.invalidate_board_counts()
    return {"post": post, "message": STATUS_MESSAGES[status]}


@router.delete("/posts/{post_id}")
def delete_post(post_id: int, user: dict = Depends(get_current_user)):
    with db() as conn:
        row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="帖子不存在")
        if row["author_id"] != user["id"] and user["role"] != "admin":
            raise HTTPException(status_code=403, detail="只能删除自己的帖子")
        conn.execute("UPDATE posts SET status = 'removed' WHERE id = ?", (post_id,))
    forum_service.invalidate_board_counts()
    return {"ok": True}


@router.post("/posts/{post_id}/like")
def like_post(post_id: int, user: dict = Depends(get_current_user)):
    from ..timeutil import iso, now_utc

    with db() as conn:
        row = _get_post(conn, post_id, user["id"], user["role"] == "admin")
        exists = conn.execute(
            "SELECT 1 FROM post_likes WHERE post_id = ? AND user_id = ?", (post_id, user["id"])
        ).fetchone()
        if exists:
            conn.execute(
                "DELETE FROM post_likes WHERE post_id = ? AND user_id = ?", (post_id, user["id"])
            )
            liked = False
        else:
            conn.execute(
                "INSERT INTO post_likes (post_id, user_id, created_at) VALUES (?, ?, ?)",
                (post_id, user["id"], iso(now_utc())),
            )
            liked = True
            forum_service.notify_post_author(
                conn,
                row,
                {"id": user["id"], "nickname": user["nickname"], "avatar": user["avatar"]},
                "like",
                f"{user['nickname']} 赞了你的帖子《{row['title'][:30]}》",
                forum_service.post_link(post_id),
            )
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM post_likes WHERE post_id = ?", (post_id,)
        ).fetchone()["n"]
    return {"liked": liked, "count": int(count)}


@router.post("/posts/{post_id}/bookmark")
def bookmark_post(post_id: int, user: dict = Depends(get_current_user)):
    from ..timeutil import iso, now_utc

    with db() as conn:
        _get_post(conn, post_id, user["id"], user["role"] == "admin")
        exists = conn.execute(
            "SELECT 1 FROM bookmarks WHERE post_id = ? AND user_id = ?", (post_id, user["id"])
        ).fetchone()
        if exists:
            conn.execute(
                "DELETE FROM bookmarks WHERE post_id = ? AND user_id = ?", (post_id, user["id"])
            )
            bookmarked = False
        else:
            conn.execute(
                "INSERT INTO bookmarks (post_id, user_id, created_at) VALUES (?, ?, ?)",
                (post_id, user["id"], iso(now_utc())),
            )
            bookmarked = True
    return {"bookmarked": bookmarked}


@router.post("/posts/{post_id}/comments", status_code=201)
def create_comment(
    post_id: int,
    payload: CommentCreate,
    request: Request,
    background: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    enforce_rate(request, "forum-comment", 30, 600)
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=400, detail="评论不能为空")
    from ..timeutil import iso, now_utc

    with db() as conn:
        post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        if not post or post["status"] != "visible":
            raise HTTPException(status_code=404, detail="帖子不存在或正在审核")
        parent = None
        if payload.parent_id:
            parent = conn.execute(
                "SELECT * FROM comments WHERE id = ? AND post_id = ? AND status = 'visible'",
                (payload.parent_id, post_id),
            ).fetchone()
            if not parent:
                raise HTTPException(status_code=400, detail="回复的评论不存在")
        verdict = moderation.scan(body)
        status = moderation.status_for(verdict)
        cur = conn.execute(
            "INSERT INTO comments (post_id, author_id, parent_id, body, anonymous, status, "
            "moderation, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                post_id,
                user["id"],
                payload.parent_id,
                body,
                1 if payload.anonymous else 0,
                status,
                _moderation_payload(verdict),
                iso(now_utc()),
                iso(now_utc()),
            ),
        )
        comment_id = int(cur.lastrowid)
        row = conn.execute("SELECT * FROM comments WHERE id = ?", (comment_id,)).fetchone()
        comment = forum_service.serialize_comment(conn, row, user["id"], post_id)
        if status == "visible":
            actor = {
                "id": None if payload.anonymous else user["id"],
                "nickname": "匿名同学" if payload.anonymous else user["nickname"],
                "avatar": "preset:ghost" if payload.anonymous else user["avatar"],
            }
            forum_service.notify_post_author(
                conn,
                post,
                actor,
                "comment",
                f"{actor['nickname']} 评论了你的帖子《{post['title'][:30]}》",
                forum_service.post_link(post_id),
            )
            if parent and parent["author_id"] and parent["author_id"] != user["id"]:
                from ..services.notify import push

                push(
                    conn,
                    int(parent["author_id"]),
                    "reply",
                    {
                        "text": f"{actor['nickname']} 回复了你的评论",
                        "link": forum_service.post_link(post_id),
                    },
                )
    if settings.moderation_api_key and status != "hidden":
        background.add_task(forum_service.ai_review_comment, comment_id)
    return {"comment": comment, "message": STATUS_MESSAGES[status]}


@router.delete("/comments/{comment_id}")
def delete_comment(comment_id: int, user: dict = Depends(get_current_user)):
    with db() as conn:
        row = conn.execute("SELECT * FROM comments WHERE id = ?", (comment_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="评论不存在")
        if row["author_id"] != user["id"] and user["role"] != "admin":
            raise HTTPException(status_code=403, detail="只能删除自己的评论")
        conn.execute("UPDATE comments SET status = 'removed' WHERE id = ?", (comment_id,))
    return {"ok": True}


@router.post("/comments/{comment_id}/like")
def like_comment(comment_id: int, user: dict = Depends(get_current_user)):
    from ..services.notify import push
    from ..timeutil import iso, now_utc

    with db() as conn:
        row = conn.execute(
            "SELECT c.*, p.status AS post_status FROM comments c JOIN posts p ON p.id = c.post_id "
            "WHERE c.id = ?",
            (comment_id,),
        ).fetchone()
        if not row or row["post_status"] != "visible":
            raise HTTPException(status_code=404, detail="评论不存在")
        exists = conn.execute(
            "SELECT 1 FROM comment_likes WHERE comment_id = ? AND user_id = ?",
            (comment_id, user["id"]),
        ).fetchone()
        if exists:
            conn.execute(
                "DELETE FROM comment_likes WHERE comment_id = ? AND user_id = ?",
                (comment_id, user["id"]),
            )
            liked = False
        else:
            conn.execute(
                "INSERT INTO comment_likes (comment_id, user_id, created_at) VALUES (?, ?, ?)",
                (comment_id, user["id"], iso(now_utc())),
            )
            liked = True
            if row["author_id"] and row["author_id"] != user["id"]:
                push(
                    conn,
                    int(row["author_id"]),
                    "like",
                    {
                        "text": f"{user['nickname']} 赞了你的评论",
                        "link": forum_service.post_link(int(row["post_id"])),
                    },
                )
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM comment_likes WHERE comment_id = ?", (comment_id,)
        ).fetchone()["n"]
    return {"liked": liked, "count": int(count)}


@router.post("/reports", status_code=201)
def report_target(payload: ReportIn, request: Request, user: dict = Depends(get_current_user)):
    enforce_rate(request, "forum-report", 20, 3600)
    if payload.reason not in REPORT_REASONS:
        raise HTTPException(status_code=400, detail="举报原因无效")
    from ..services.notify import notify_admins
    from ..timeutil import iso, now_utc

    with db() as conn:
        if payload.target_type == "post":
            target = conn.execute("SELECT id FROM posts WHERE id = ?", (payload.target_id,)).fetchone()
            label = "帖子"
        elif payload.target_type == "comment":
            target = conn.execute(
                "SELECT id FROM comments WHERE id = ?", (payload.target_id,)
            ).fetchone()
            label = "评论"
        else:
            if payload.target_id == user["id"]:
                raise HTTPException(status_code=400, detail="不能举报自己")
            target = conn.execute(
                "SELECT id FROM users WHERE id = ?", (payload.target_id,)
            ).fetchone()
            label = "用户"
        if not target:
            raise HTTPException(status_code=404, detail="举报对象不存在")
        try:
            conn.execute(
                "INSERT INTO reports (reporter_id, target_type, target_id, reason, detail, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    user["id"],
                    payload.target_type,
                    payload.target_id,
                    payload.reason,
                    payload.detail.strip(),
                    iso(now_utc()),
                ),
            )
        except Exception:
            raise HTTPException(status_code=409, detail="你已经举报过该内容") from None
        notify_admins(
            conn,
            "report",
            {
                "text": f"收到一条{label}举报：{payload.reason}",
                "link": "#/admin",
                "target_type": payload.target_type,
                "target_id": payload.target_id,
            },
        )
    return {"ok": True, "message": "举报已提交，管理员会尽快处理"}


@router.post("/appeals", status_code=201)
def submit_appeal(payload: AppealIn, user: dict = Depends(get_current_user)):
    from ..services.notify import notify_admins
    from ..timeutil import iso, now_utc

    with db() as conn:
        if payload.target_type == "post":
            row = conn.execute(
                "SELECT * FROM posts WHERE id = ? AND author_id = ?",
                (payload.target_id, user["id"]),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM comments WHERE id = ? AND author_id = ?",
                (payload.target_id, user["id"]),
            ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="只能申诉自己的内容")
        if row["status"] == "visible":
            raise HTTPException(status_code=400, detail="该内容当前可见，无需申诉")
        open_appeal = conn.execute(
            "SELECT 1 FROM appeals WHERE user_id = ? AND target_type = ? AND target_id = ? "
            "AND status = 'open'",
            (user["id"], payload.target_type, payload.target_id),
        ).fetchone()
        if open_appeal:
            raise HTTPException(status_code=409, detail="已有待处理的申诉")
        conn.execute(
            "INSERT INTO appeals (user_id, target_type, target_id, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user["id"], payload.target_type, payload.target_id, payload.reason.strip(), iso(now_utc())),
        )
        notify_admins(
            conn,
            "appeal",
            {"text": "收到一条内容申诉", "link": "#/admin"},
        )
    return {"ok": True, "message": "申诉已提交"}


@router.get("/users/{user_id}")
def user_profile(user_id: int, user: dict = Depends(get_current_user)):
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="用户不存在")
        profile = public_user(dict(row))
        profile["directions"] = json.loads(row["directions"] or "[]")
        profile["is_self"] = user_id == user["id"]
        profile["is_following"] = bool(
            conn.execute(
                "SELECT 1 FROM follows WHERE follower_id = ? AND followee_id = ?",
                (user["id"], user_id),
            ).fetchone()
        )
        followers = conn.execute(
            "SELECT COUNT(*) AS n FROM follows WHERE followee_id = ?", (user_id,)
        ).fetchone()["n"]
        following = conn.execute(
            "SELECT COUNT(*) AS n FROM follows WHERE follower_id = ?", (user_id,)
        ).fetchone()["n"]
        post_count = conn.execute(
            "SELECT COUNT(*) AS n FROM posts WHERE author_id = ? AND status = 'visible'",
            (user_id,),
        ).fetchone()["n"]
        post_rows = conn.execute(
            "SELECT * FROM posts WHERE author_id = ? AND status = 'visible' "
            "ORDER BY created_at DESC LIMIT 12",
            (user_id,),
        ).fetchall()
        posts = [forum_service.serialize_post(conn, p, user["id"]) for p in post_rows]
    return {
        "user": profile,
        "stats": {
            "posts": int(post_count),
            "followers": int(followers),
            "following": int(following),
        },
        "posts": posts,
    }


@router.post("/users/{user_id}/follow")
def toggle_follow(user_id: int, user: dict = Depends(get_current_user)):
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="不能关注自己")
    from ..services.notify import push
    from ..timeutil import iso, now_utc

    with db() as conn:
        target = conn.execute("SELECT id, nickname FROM users WHERE id = ?", (user_id,)).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="用户不存在")
        exists = conn.execute(
            "SELECT 1 FROM follows WHERE follower_id = ? AND followee_id = ?",
            (user["id"], user_id),
        ).fetchone()
        if exists:
            conn.execute(
                "DELETE FROM follows WHERE follower_id = ? AND followee_id = ?",
                (user["id"], user_id),
            )
            following = False
        else:
            conn.execute(
                "INSERT INTO follows (follower_id, followee_id, created_at) VALUES (?, ?, ?)",
                (user["id"], user_id, iso(now_utc())),
            )
            following = True
            push(
                conn,
                user_id,
                "follow",
                {
                    "text": f"{user['nickname']} 关注了你",
                    "link": f"#/forum/user/{user['id']}",
                },
            )
        followers = conn.execute(
            "SELECT COUNT(*) AS n FROM follows WHERE followee_id = ?", (user_id,)
        ).fetchone()["n"]
    return {"following": following, "followers": int(followers)}


@router.get("/users/{user_id}/followers")
def followers(user_id: int, user: dict = Depends(get_current_user)):
    with db() as conn:
        rows = conn.execute(
            "SELECT u.* FROM follows f JOIN users u ON u.id = f.follower_id "
            "WHERE f.followee_id = ? ORDER BY f.created_at DESC LIMIT 100",
            (user_id,),
        ).fetchall()
    return {"items": [public_user(dict(r)) for r in rows]}


@router.get("/users/{user_id}/following")
def following(user_id: int, user: dict = Depends(get_current_user)):
    with db() as conn:
        rows = conn.execute(
            "SELECT u.* FROM follows f JOIN users u ON u.id = f.followee_id "
            "WHERE f.follower_id = ? ORDER BY f.created_at DESC LIMIT 100",
            (user_id,),
        ).fetchall()
    return {"items": [public_user(dict(r)) for r in rows]}
