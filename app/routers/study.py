"""学习资料推荐 API。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ..deps import client_llm
from ..security import enforce_rate, get_current_user
from ..services import study

router = APIRouter(prefix="/api/study", tags=["study"])


@router.get("")
def recommend(
    request: Request,
    refresh: bool = False,
    user: dict = Depends(get_current_user),
):
    enforce_rate(request, "study", 40, 3600)
    creds = client_llm(request, required=False)
    try:
        return study.recommend(user, creds, refresh)
    except Exception:
        raise HTTPException(status_code=502, detail="学习资料推荐暂时不可用，请稍后刷新") from None
