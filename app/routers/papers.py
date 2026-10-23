"""论文推荐 API。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ..deps import client_llm
from ..security import enforce_rate, get_current_user
from ..services import papers

router = APIRouter(prefix="/api/papers", tags=["papers"])


@router.get("")
def recommend(
    request: Request,
    direction: str = "",
    refresh: bool = False,
    user: dict = Depends(get_current_user),
):
    enforce_rate(request, "papers", 40, 3600)
    creds = client_llm(request, required=False)
    target = (direction or "").strip()
    if not target and user.get("directions"):
        target = user["directions"][0]
    target = target or "人工智能"
    try:
        return papers.recommend(target, creds, refresh)
    except papers.PaperError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
