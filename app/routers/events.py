"""站内通知与 SSE 实时事件。"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..db import db
from ..security import get_current_user
from ..services.events import hub, sse
from ..timeutil import iso, now_utc

router = APIRouter(tags=["events"])


class ReadIn(BaseModel):
    ids: list[int] = []
    all: bool = False


@router.get("/api/notifications")
def list_notifications(limit: int = 30, user: dict = Depends(get_current_user)):
    limit = max(1, min(limit, 100))
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user["id"], limit),
        ).fetchall()
        unread = conn.execute(
            "SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND read_at IS NULL",
            (user["id"],),
        ).fetchone()
    items = []
    for row in rows:
        try:
            payload = json.loads(row["payload"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        items.append(
            {
                "id": row["id"],
                "kind": row["kind"],
                "payload": payload,
                "read": bool(row["read_at"]),
                "created_at": row["created_at"],
            }
        )
    return {"items": items, "unread": int(unread["n"]) if unread else 0}


@router.post("/api/notifications/read")
def mark_read(payload: ReadIn, user: dict = Depends(get_current_user)):
    with db() as conn:
        if payload.all:
            conn.execute(
                "UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL",
                (iso(now_utc()), user["id"]),
            )
        elif payload.ids:
            marks = ",".join("?" for _ in payload.ids[:100])
            conn.execute(
                f"UPDATE notifications SET read_at = ? WHERE user_id = ? AND id IN ({marks})",
                (iso(now_utc()), user["id"], *payload.ids[:100]),
            )
    return {"ok": True}


@router.get("/api/events")
async def events(request: Request, user: dict = Depends(get_current_user)):
    queue = hub.subscribe(user["id"])

    async def stream():
        try:
            yield "retry: 4000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20)
                    yield sse(event)
                except TimeoutError:
                    yield ": ping\n\n"
        finally:
            hub.unsubscribe(user["id"], queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
