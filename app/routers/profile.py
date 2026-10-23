"""个人资料、头像与账号数据删除。"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..config import settings
from ..db import db, jdumps, jloads
from ..options import AVATAR_PRESETS, DEFAULT_SETTINGS, GRADES, RESERVED_NICKNAMES
from ..security import avatar_url, clear_session_cookie, enforce_rate, get_current_user, load_user
from ..services import notifier

router = APIRouter(prefix="/api/profile", tags=["profile"])

PRESET_KEYS = {item["key"] for item in AVATAR_PRESETS}
NICK_RE = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9_·\-]{2,16}$")
ALLOWED_SETTINGS = {
    "theme",
    "news_categories",
    "news_topics",
    "notify_channels",
    "show_grade",
    "compact",
    "default_model",
    "default_provider",
}


class ProfileUpdate(BaseModel):
    nickname: str | None = Field(default=None, max_length=16)
    bio: str | None = Field(default=None, max_length=200)
    major: str | None = Field(default=None, max_length=40)
    department: str | None = Field(default=None, max_length=40)
    grade: str | None = None
    directions: list[str] | None = Field(default=None, max_length=12)
    courses: list[str] | None = Field(default=None, max_length=24)
    settings: dict[str, Any] | None = None
    avatar: str | None = None


class AvatarIn(BaseModel):
    image: str = Field(min_length=30, max_length=900_000)


def _clean_list(values: list[str], limit: int, item_len: int) -> list[str]:
    result: list[str] = []
    for value in values[:limit]:
        text = str(value).strip()[:item_len]
        if text and text not in result:
            result.append(text)
    return result


def _sanitize_settings(current: dict, incoming: dict) -> dict:
    merged = {**DEFAULT_SETTINGS, **current}
    for key, value in incoming.items():
        if key not in ALLOWED_SETTINGS:
            continue
        if key == "theme" and value in {"light", "dark", "system"}:
            merged[key] = value
        elif key == "news_categories" and isinstance(value, list):
            merged[key] = [str(v)[:20] for v in value[:8] if isinstance(v, (str, int))]
        elif key == "news_topics" and isinstance(value, list):
            topics = []
            for item in value[:8]:
                text = str(item).strip()[:20]
                if text and text not in topics:
                    topics.append(text)
            merged[key] = topics
        elif key == "notify_channels" and isinstance(value, list):
            allowed = set(notifier.channels_available())
            merged[key] = [str(v) for v in value[:4] if str(v) in allowed]
        elif key in {"show_grade", "compact"} and isinstance(value, bool):
            merged[key] = value
        elif key in {"default_model", "default_provider"} and isinstance(value, str):
            merged[key] = value[:120]
    if len(json.dumps(merged)) > 4000:
        raise HTTPException(status_code=400, detail="设置内容过大")
    return merged


def _public_self(user: dict) -> dict:
    data = {
        "id": user["id"],
        "nickname": user["nickname"],
        "avatar": user["avatar"],
        "avatar_url": avatar_url(user["avatar"]),
        "bio": user["bio"],
        "major": user["major"],
        "department": user.get("department", ""),
        "grade": user["grade"],
        "directions": user.get("directions", []),
        "courses": user.get("courses", []),
        "settings": user.get("settings", {}),
        "role": user["role"],
        "created_at": user["created_at"],
        "is_admin": user["role"] == "admin",
    }
    return data


@router.get("")
def get_profile(user: dict = Depends(get_current_user)):
    return {"user": _public_self(user)}


@router.patch("")
def update_profile(payload: ProfileUpdate, user: dict = Depends(get_current_user)):
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="没有需要修改的内容")
    updates: list[str] = []
    values: list[object] = []
    with db() as conn:
        if "nickname" in fields and fields["nickname"] is not None:
            nickname = fields["nickname"].strip()
            if not NICK_RE.match(nickname):
                raise HTTPException(status_code=400, detail="昵称需为 2-16 个中文、字母、数字或 _ - ·")
            if nickname.lower() in {x.lower() for x in RESERVED_NICKNAMES}:
                raise HTTPException(status_code=400, detail="该昵称已被保留")
            taken = conn.execute(
                "SELECT id FROM users WHERE nickname = ? AND id != ?", (nickname, user["id"])
            ).fetchone()
            if taken:
                raise HTTPException(status_code=409, detail="该昵称已被使用")
            updates.append("nickname = ?")
            values.append(nickname)
        if "bio" in fields and fields["bio"] is not None:
            updates.append("bio = ?")
            values.append(fields["bio"].strip())
        if "major" in fields and fields["major"] is not None:
            updates.append("major = ?")
            values.append(fields["major"].strip())
        if "department" in fields and fields["department"] is not None:
            updates.append("department = ?")
            values.append(fields["department"].strip())
        if "grade" in fields and fields["grade"] is not None:
            if fields["grade"] not in GRADES and fields["grade"] != "":
                raise HTTPException(status_code=400, detail="年级选项无效")
            updates.append("grade = ?")
            values.append(fields["grade"])
        if "directions" in fields and fields["directions"] is not None:
            updates.append("directions = ?")
            values.append(jdumps(_clean_list(fields["directions"], 12, 40)))
        if "courses" in fields and fields["courses"] is not None:
            updates.append("courses = ?")
            values.append(jdumps(_clean_list(fields["courses"], 24, 40)))
        if "settings" in fields and fields["settings"] is not None:
            raw_settings = user.get("settings")
            current = raw_settings if isinstance(raw_settings, dict) else jloads(raw_settings, {})
            merged = _sanitize_settings(current, fields["settings"])
            updates.append("settings = ?")
            values.append(jdumps(merged))
        if "avatar" in fields and fields["avatar"] is not None:
            avatar = fields["avatar"]
            if not avatar.startswith("preset:") or avatar[7:] not in PRESET_KEYS:
                raise HTTPException(status_code=400, detail="头像选项无效")
            updates.append("avatar = ?")
            values.append(avatar)
        if not updates:
            raise HTTPException(status_code=400, detail="没有需要修改的内容")
        values.append(user["id"])
        conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", tuple(values))
        fresh = load_user(conn, user["id"])
    return {"user": _public_self(fresh)}


@router.post("/avatar")
def upload_avatar(payload: AvatarIn, request: Request, user: dict = Depends(get_current_user)):
    enforce_rate(request, "avatar", 10, 3600)
    header, _, encoded = payload.image.partition(",")
    if not header.startswith("data:image/"):
        raise HTTPException(status_code=400, detail="头像格式无效")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="头像数据无法解码") from None
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(status_code=400, detail="头像不能超过 600KB")
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover
        raise HTTPException(status_code=501, detail="服务器未安装 Pillow，暂不支持上传头像") from None
    try:
        probe = Image.open(io.BytesIO(raw))
        probe.verify()
        image = Image.open(io.BytesIO(raw)).convert("RGB")
        image.thumbnail((256, 256))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
    except Exception:
        raise HTTPException(status_code=400, detail="图片无法识别或已损坏") from None
    name = hashlib.sha256(buffer.getvalue()).hexdigest()[:20] + ".png"
    settings.avatar_dir.mkdir(parents=True, exist_ok=True)
    (settings.avatar_dir / name).write_bytes(buffer.getvalue())
    with db() as conn:
        old = conn.execute("SELECT avatar FROM users WHERE id = ?", (user["id"],)).fetchone()
        conn.execute("UPDATE users SET avatar = ? WHERE id = ?", (f"file:{name}", user["id"]))
    if old and old["avatar"].startswith("file:"):
        old_name = old["avatar"][5:]
        if old_name != name and old_name.endswith(".png"):
            try:
                (settings.avatar_dir / old_name).unlink(missing_ok=True)
            except OSError:
                pass
    return {"avatar": f"file:{name}", "avatar_url": avatar_url(f"file:{name}")}


@router.get("/stats")
def profile_stats(user: dict = Depends(get_current_user)):
    with db() as conn:
        def scalar(sql: str, *params) -> int:
            row = conn.execute(sql, params).fetchone()
            return int(row[0]) if row else 0

        return {
            "posts": scalar("SELECT COUNT(*) FROM posts WHERE author_id = ? AND status = 'visible'", user["id"]),
            "comments": scalar(
                "SELECT COUNT(*) FROM comments WHERE author_id = ? AND status = 'visible'", user["id"]
            ),
            "followers": scalar("SELECT COUNT(*) FROM follows WHERE followee_id = ?", user["id"]),
            "following": scalar("SELECT COUNT(*) FROM follows WHERE follower_id = ?", user["id"]),
            "bookmarks": scalar("SELECT COUNT(*) FROM bookmarks WHERE user_id = ?", user["id"]),
            "plans": scalar("SELECT COUNT(*) FROM plans WHERE user_id = ? AND active = 1", user["id"]),
            "reminders": scalar("SELECT COUNT(*) FROM reminders WHERE user_id = ? AND done = 0", user["id"]),
            "member_since": user["created_at"][:10],
        }


@router.delete("")
def delete_account(
    response: Response,
    confirm: str = "",
    user: dict = Depends(get_current_user),
):
    if confirm != "DELETE":
        raise HTTPException(status_code=400, detail="请输入 DELETE 以确认删除账号")
    with db() as conn:
        avatar = conn.execute("SELECT avatar FROM users WHERE id = ?", (user["id"],)).fetchone()
        conn.execute("DELETE FROM users WHERE id = ?", (user["id"],))
    if avatar and avatar["avatar"].startswith("file:"):
        name = avatar["avatar"][5:]
        if "/" not in name and "\\" not in name:
            try:
                (settings.avatar_dir / name).unlink(missing_ok=True)
            except OSError:
                pass
    clear_session_cookie(response)
    return {"ok": True, "message": "账号与个人数据已删除；公开发帖已转为匿名（作者显示为已注销用户）。"}
