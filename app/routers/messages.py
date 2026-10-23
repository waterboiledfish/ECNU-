"""私信与会话列表。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..db import db
from ..security import enforce_rate, get_current_user, public_user
from ..services.notify import push
from ..timeutil import iso, now_utc

router = APIRouter(prefix="/api/messages", tags=["messages"])


class MessageIn(BaseModel):
    to: int
    body: str = Field(min_length=1, max_length=1000)


@router.get("/conversations")
def conversations(user: dict = Depends(get_current_user)):
    with db() as conn:
        rows = conn.execute(
            "SELECT m.*, CASE WHEN m.sender_id = ? THEN m.recipient_id ELSE m.sender_id END AS peer_id "
            "FROM messages m WHERE m.sender_id = ? OR m.recipient_id = ? "
            "ORDER BY m.id DESC LIMIT 600",
            (user["id"], user["id"], user["id"]),
        ).fetchall()
        unread_rows = conn.execute(
            "SELECT sender_id, COUNT(*) AS n FROM messages WHERE recipient_id = ? "
            "AND read_at IS NULL GROUP BY sender_id",
            (user["id"],),
        ).fetchall()
        unread = {int(r["sender_id"]): int(r["n"]) for r in unread_rows}
        seen: set[int] = set()
        items = []
        for row in rows:
            peer_id = int(row["peer_id"])
            if peer_id in seen:
                continue
            seen.add(peer_id)
            peer = conn.execute("SELECT * FROM users WHERE id = ?", (peer_id,)).fetchone()
            if not peer:
                continue
            items.append(
                {
                    "peer": public_user(dict(peer)),
                    "last": {
                        "id": row["id"],
                        "body": row["body"][:80],
                        "created_at": row["created_at"],
                        "mine": row["sender_id"] == user["id"],
                    },
                    "unread": unread.get(peer_id, 0),
                }
            )
    total_unread = sum(unread.values())
    return {"items": items, "unread": total_unread}


@router.get("/unread")
def unread_count(user: dict = Depends(get_current_user)):
    with db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE recipient_id = ? AND read_at IS NULL",
            (user["id"],),
        ).fetchone()
    return {"unread": int(row["n"]) if row else 0}


@router.get("/{peer_id}")
def thread(peer_id: int, user: dict = Depends(get_current_user)):
    if peer_id == user["id"]:
        raise HTTPException(status_code=400, detail="不能与自己私信")
    with db() as conn:
        peer = conn.execute("SELECT * FROM users WHERE id = ?", (peer_id,)).fetchone()
        if not peer:
            raise HTTPException(status_code=404, detail="用户不存在")
        rows = conn.execute(
            "SELECT * FROM messages WHERE (sender_id = ? AND recipient_id = ?) "
            "OR (sender_id = ? AND recipient_id = ?) ORDER BY id DESC LIMIT 200",
            (user["id"], peer_id, peer_id, user["id"]),
        ).fetchall()
        conn.execute(
            "UPDATE messages SET read_at = ? WHERE recipient_id = ? AND sender_id = ? "
            "AND read_at IS NULL",
            (iso(now_utc()), user["id"], peer_id),
        )
    messages = []
    for row in reversed(rows):
        messages.append(
            {
                "id": row["id"],
                "body": row["body"],
                "created_at": row["created_at"],
                "mine": row["sender_id"] == user["id"],
                "read": bool(row["read_at"]),
            }
        )
    return {"peer": public_user(dict(peer)), "messages": messages}


@router.post("", status_code=201)
def send_message(payload: MessageIn, request: Request, user: dict = Depends(get_current_user)):
    enforce_rate(request, "message", 40, 600)
    if payload.to == user["id"]:
        raise HTTPException(status_code=400, detail="不能给自己发私信")
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=400, detail="消息不能为空")
    with db() as conn:
        peer = conn.execute("SELECT * FROM users WHERE id = ?", (payload.to,)).fetchone()
        if not peer:
            raise HTTPException(status_code=404, detail="用户不存在")
        cur = conn.execute(
            "INSERT INTO messages (sender_id, recipient_id, body, created_at) VALUES (?, ?, ?, ?)",
            (user["id"], payload.to, body, iso(now_utc())),
        )
        message_id = int(cur.lastrowid)
        push(
            conn,
            payload.to,
            "message",
            {
                "text": f"{user['nickname']} 给你发来一条私信",
                "preview": body[:60],
                "link": f"#/messages/{user['id']}",
            },
        )
    return {
        "id": message_id,
        "body": body,
        "created_at": iso(now_utc()),
        "peer": public_user(dict(peer)),
    }
