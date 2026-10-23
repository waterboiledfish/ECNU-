"""问答 API：官网文件问答（带引用）与学业问答，支持流式输出。"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import iterate_in_threadpool

from ..deps import client_llm
from ..security import enforce_rate, get_current_user
from ..services import llm, rag
from ..services.events import sse

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    site_ids: list[int] = Field(default_factory=list, max_length=60)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=12)


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
