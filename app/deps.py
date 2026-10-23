"""请求级依赖：读取用户本次请求携带的模型凭据（不落库）。"""
from __future__ import annotations

from fastapi import HTTPException, Request

from .config import settings
from .services import llm


def client_llm(request: Request, required: bool = True) -> dict | None:
    key = request.headers.get("x-llm-key", "").strip()
    model = (request.headers.get("x-llm-model") or settings.llm_model).strip()
    base_url = (request.headers.get("x-llm-base-url") or settings.llm_base_url).strip()
    if not key:
        if required:
            raise HTTPException(status_code=400, detail="请先在设置中填写自己的 API Key")
        return None
    try:
        llm.validate_config(key, model)
        llm.normalize_base_url(base_url)
    except llm.LLMError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from None
    return {"key": key, "model": model, "base_url": base_url}
