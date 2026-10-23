"""问答 API：官网文件问答（带引用）与学业问答，支持流式输出；对话历史落库。"""
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import iterate_in_threadpool

from ..db import db
from ..deps import client_llm
from ..security import enforce_rate, get_current_user
from ..services import llm, rag
from ..services.events import sse
from ..timeutil import iso, now_utc

router = APIRouter(prefix="/api/chat", tags=["chat"])

MODES = ("official", "academic")
MAX_THREADS = 60
MAX_MESSAGES = 60


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    site_ids: list[int] = Field(default_factory=list, max_length=60)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=12)


class ThreadIn(BaseModel):
    mode: Literal["official", "academic"] = "official"


class MessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(default="", max_length=20000)
    sources: list[dict[str, Any]] = Field(default_factory=list, max_length=30)
    insufficient: bool = False
    error: str = Field(default="", max_length=500)


class ThreadSaveIn(BaseModel):
    messages: list[MessageIn] = Field(default_factory=list, max_length=MAX_MESSAGES)
    title: str = Field(default="", max_length=60)


def _limit(request: Request) -> None:
    enforce_rate(request, "chat", 60, 600)


def _clean(question: str) -> str:
    value = question.strip()
    if not value:
        raise HTTPException(status_code=400, detail="问题不能为空")
    return value


@router.post("/official")
def official_chat(payload: ChatIn, request: Request, user: dict = Depends(get_current_user)):
    _limit(request)
    creds = client_llm(request)
    assert creds is not None
    try:
        return rag.answer_official(
            _clean(payload.question),
            key=creds["key"],
            model=creds["model"],
            base_url=creds["base_url"],
            site_ids=payload.site_ids,
        )
    except llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=exc.message) from None


@router.post("/official/stream")
def official_stream(payload: ChatIn, request: Request, user: dict = Depends(get_current_user)):
    _limit(request)
    creds = client_llm(request)
    assert creds is not None
    question = _clean(payload.question)

    def events() -> Iterator[dict[str, Any]]:
        try:
            yield from rag.stream_official(
                question,
                key=creds["key"],
                model=creds["model"],
                base_url=creds["base_url"],
                site_ids=payload.site_ids,
            )
        except llm.LLMError as exc:
            yield {"type": "error", "detail": exc.message}
        except Exception:
            yield {"type": "error", "detail": "问答服务暂时不可用，请稍后重试"}

    async def stream():
        async for event in iterate_in_threadpool(events()):
            yield sse(event)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.post("/academic")
def academic_chat(payload: ChatIn, request: Request, user: dict = Depends(get_current_user)):
    _limit(request)
    creds = client_llm(request)
    assert creds is not None
    history = [
        {"role": item.get("role", ""), "content": item.get("content", "")}
        for item in payload.history
        if isinstance(item, dict)
    ]
    try:
        return rag.answer_academic(
            _clean(payload.question),
            key=creds["key"],
            model=creds["model"],
            base_url=creds["base_url"],
            history=history,
        )
    except llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=exc.message) from None


@router.post("/academic/stream")
def academic_stream(payload: ChatIn, request: Request, user: dict = Depends(get_current_user)):
    _limit(request)
    creds = client_llm(request)
    assert creds is not None
    question = _clean(payload.question)
    history = [
        {"role": item.get("role", ""), "content": item.get("content", "")}
        for item in payload.history
        if isinstance(item, dict)
    ]

    def events() -> Iterator[dict[str, Any]]:
        try:
            yield from rag.stream_academic(
                question,
                key=creds["key"],
                model=creds["model"],
                base_url=creds["base_url"],
                history=history,
            )
        except llm.LLMError as exc:
            yield {"type": "error", "detail": exc.message}
        except Exception:
            yield {"type": "error", "detail": "问答服务暂时不可用，请稍后重试"}

    async def stream():
        async for event in iterate_in_threadpool(events()):
            yield sse(event)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------- 对话历史
def _thread_summary(row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "mode": row["mode"],
        "title": row["title"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "message_count": int(row["message_count"]) if "message_count" in row.keys() else 0,
    }


def _thread_or_404(conn, thread_id: int, user_id: int):
    row = conn.execute(
        "SELECT * FROM chat_threads WHERE id = ? AND user_id = ?", (thread_id, user_id)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="对话不存在")
    return row


def _message_rows(conn, thread_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT role, content, sources, insufficient, error, created_at "
        "FROM chat_messages WHERE thread_id = ? ORDER BY id",
        (thread_id,),
    ).fetchall()
    result = []
    for row in rows:
        try:
            sources = json.loads(row["sources"] or "[]")
        except json.JSONDecodeError:
            sources = []
        result.append(
            {
                "role": row["role"],
                "content": row["content"],
                "sources": sources if isinstance(sources, list) else [],
                "insufficient": bool(row["insufficient"]),
                "error": row["error"],
                "created_at": row["created_at"],
            }
        )
    return result


@router.get("/threads")
def list_threads(mode: str = "official", user: dict = Depends(get_current_user)):
    mode = mode if mode in MODES else "official"
    with db() as conn:
        rows = conn.execute(
            "SELECT t.*, (SELECT COUNT(*) FROM chat_messages m WHERE m.thread_id = t.id) AS message_count "
            "FROM chat_threads t WHERE t.user_id = ? AND t.mode = ? "
            "ORDER BY t.updated_at DESC, t.id DESC LIMIT ?",
            (user["id"], mode, MAX_THREADS),
        ).fetchall()
    return {"threads": [_thread_summary(row) for row in rows]}


@router.post("/threads", status_code=201)
def create_thread(payload: ThreadIn, request: Request, user: dict = Depends(get_current_user)):
    enforce_rate(request, "chat-thread", 120, 600)
    now = iso(now_utc())
    with db() as conn:
        extra = conn.execute(
            "SELECT id FROM chat_threads WHERE user_id = ? AND mode = ? "
            "ORDER BY updated_at DESC, id DESC LIMIT -1 OFFSET ?",
            (user["id"], payload.mode, MAX_THREADS - 1),
        ).fetchall()
        for row in extra:
            conn.execute("DELETE FROM chat_threads WHERE id = ?", (row["id"],))
        cursor = conn.execute(
            "INSERT INTO chat_threads (user_id, mode, title, created_at, updated_at) VALUES (?, ?, '', ?, ?)",
            (user["id"], payload.mode, now, now),
        )
        thread_id = int(cursor.lastrowid)
    return {"id": thread_id, "mode": payload.mode, "title": "", "created_at": now, "updated_at": now, "messages": []}


@router.get("/threads/{thread_id}")
def get_thread(thread_id: int, user: dict = Depends(get_current_user)):
    with db() as conn:
        row = _thread_or_404(conn, thread_id, user["id"])
        messages = _message_rows(conn, thread_id)
    return {**_thread_summary(row), "messages": messages}


@router.put("/threads/{thread_id}")
def save_thread(thread_id: int, payload: ThreadSaveIn, user: dict = Depends(get_current_user)):
    now = iso(now_utc())
    with db() as conn:
        row = _thread_or_404(conn, thread_id, user["id"])
        title = payload.title.strip()
        if not title:
            first = next(
                (m.content for m in payload.messages if m.role == "user" and m.content.strip()), ""
            )
            title = first.strip().replace("\n", " ")[:40] or row["title"] or "新对话"
        conn.execute("DELETE FROM chat_messages WHERE thread_id = ?", (thread_id,))
        conn.executemany(
            "INSERT INTO chat_messages (thread_id, role, content, sources, insufficient, error, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    thread_id,
                    message.role,
                    message.content[:20000],
                    json.dumps(message.sources[:30], ensure_ascii=False)[:40000],
                    1 if message.insufficient else 0,
                    message.error[:500],
                    now,
                )
                for message in payload.messages
            ],
        )
        conn.execute(
            "UPDATE chat_threads SET title = ?, updated_at = ? WHERE id = ?", (title, now, thread_id)
        )
    return {"id": thread_id, "title": title, "updated_at": now, "messages": len(payload.messages)}


@router.delete("/threads/{thread_id}")
def delete_thread(thread_id: int, user: dict = Depends(get_current_user)):
    with db() as conn:
        _thread_or_404(conn, thread_id, user["id"])
        conn.execute("DELETE FROM chat_threads WHERE id = ?", (thread_id,))
    return {"ok": True}
