"""前端初始化所需的元数据。"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

from ..config import settings
from ..options import AVATAR_PRESETS, GRADES, REPORT_REASONS
from ..services import news, notifier, study
from ..services.forum import TAGS
from .auth import auth_meta

router = APIRouter(prefix="/api/meta", tags=["meta"])

_PROVIDERS = Path(__file__).resolve().parent.parent / "data" / "providers.json"


def _providers() -> list[dict]:
    try:
        return json.loads(_PROVIDERS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


@router.get("")
def meta():
    return {
        "app": {"name": settings.app_name, "version": settings.version},
        "auth": auth_meta(),
        "portal_url": settings.portal_url,
        "providers": _providers(),
        "defaults": {"base_url": settings.llm_base_url, "model": settings.llm_model},
        "grades": GRADES,
        "avatars": AVATAR_PRESETS,
        "report_reasons": REPORT_REASONS,
        "forum_tags": TAGS,
        "news_categories": news.categories_payload(),
        "study_platforms": study.PLATFORMS,
        "channels": notifier.channels_available(),
        "features": {
            "ai_moderation": bool(settings.moderation_api_key and settings.moderation_model),
            "allow_user_crawl": settings.allow_user_crawl,
            "dev_login": settings.auth_mode == "dev" and settings.dev_login_enabled,
        },
        "limits": {
            "max_upload_bytes": settings.max_upload_bytes,
            "max_question_chars": 2000,
        },
    }
