"""今日热点 API。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..deps import client_llm
from ..security import enforce_rate, get_current_user
from ..services import llm, news

router = APIRouter(prefix="/api/news", tags=["news"])


class DigestIn(BaseModel):
    category: str = "general"


@router.get("/categories")
def categories():
    return {"items": news.categories_payload()}


@router.get("")
def feed(
    request: Request,
    category: str = "general",
    refresh: bool = False,
    user: dict = Depends(get_current_user),
):
    enforce_rate(request, "news", 60, 3600)
    try:
        return news.fetch_category(category, refresh)
    except news.NewsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


@router.post("/digest")
def make_digest(payload: DigestIn, request: Request, user: dict = Depends(get_current_user)):
    enforce_rate(request, "news-digest", 30, 3600)
    creds = client_llm(request)
    assert creds is not None
    try:
        return news.digest(payload.category, creds)
    except news.NewsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=exc.message) from None
