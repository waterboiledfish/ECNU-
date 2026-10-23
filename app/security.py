"""会话、CSRF、限流与匿名展示。"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import deque
from datetime import UTC
from typing import Any

from fastapi import HTTPException, Request, Response

from .config import settings
from .db import db, jloads
from .timeutil import iso, now_utc

SESSION_COOKIE = "ecnu_session"
DEVICE_COOKIE = "ecnu_device"
STATE_COOKIE = "ecnu_sso_state"

PUBLIC_USER_FIELDS = (
    "id",
    "nickname",
    "avatar",
    "bio",
    "major",
    "department",
    "grade",
    "role",
    "created_at",
)


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def create_session(
    conn, user_id: int, ip: str = "", ua: str = ""
) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    now = now_utc()
    expires = now.timestamp() + settings.session_ttl_days * 86400
    from datetime import datetime

    expires_iso = datetime.fromtimestamp(expires, UTC).isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO sessions (user_id, token_hash, csrf, created_at, expires_at, ip, ua) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, sha256(token), csrf, iso(now), expires_iso, ip[:80], ua[:300]),
    )
    return token, csrf


def revoke_session(conn, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (sha256(token),))


def session_row(conn, token: str | None):
    if not token:
        return None
    return conn.execute(
        "SELECT s.*, u.id AS u_id FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = ? AND s.expires_at > ?",
        (sha256(token), iso(now_utc())),
    ).fetchone()


def load_user(conn, user_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        return None
    return user_dict(row)


def user_dict(row) -> dict[str, Any]:
    data = dict(row)
    if "id" in data and "u_id" in data:
        data.pop("u_id", None)
    for key in ("directions", "courses", "settings"):
        if key in data and isinstance(data[key], str):
            data[key] = jloads(data[key], [] if key != "settings" else {})
    return data


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    data = {key: user.get(key) for key in PUBLIC_USER_FIELDS}
    data["avatar_url"] = avatar_url(user.get("avatar", ""))
    return data


def avatar_url(avatar: str) -> str:
    if avatar.startswith("file:"):
        name = avatar[5:]
        if name and "/" not in name and "\\" not in name:
            return f"/api/media/avatar/{name}"
    return ""


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def get_current_user(request: Request) -> dict[str, Any]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="请先登录")
    with db() as conn:
        row = session_row(conn, token)
        if not row:
            raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
        user = load_user(conn, int(row["u_id"]))
        if not user:
            raise HTTPException(status_code=401, detail="账号不存在")
        user["csrf"] = row["csrf"]
        return user


def optional_user(request: Request) -> dict[str, Any] | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    with db() as conn:
        row = session_row(conn, token)
        if not row:
            return None
        user = load_user(conn, int(row["u_id"]))
        if user:
            user["csrf"] = row["csrf"]
        return user


def require_admin(user: dict[str, Any]) -> dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def is_admin_subject(subject: str) -> bool:
    if not settings.admin_subjects:
        return False
    principal = subject.split(":", 1)[-1]
    return subject in settings.admin_subjects or principal in settings.admin_subjects


def anonymous_name(post_id: int, user_id: int | None) -> str:
    """同一帖子内同一匿名作者显示名稳定，帖子之间不可关联。"""
    if not user_id:
        return "匿名同学"
    digest = hmac.new(
        settings.secret_key.encode("utf-8"),
        f"anon:{post_id}:{user_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"匿名同学·{digest[:4]}"


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window: int) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and bucket[0] < now - window:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            if len(self._hits) > 5000:
                for stale in [k for k, v in self._hits.items() if not v][:1000]:
                    self._hits.pop(stale, None)
            return True


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:60]
    return (request.client.host if request.client else "unknown")[:60]


def enforce_rate(request: Request, bucket: str, limit: int, window: int) -> None:
    if not limiter.allow(f"{bucket}:{client_ip(request)}", limit, window):
        raise HTTPException(
            status_code=429,
            detail=f"操作太频繁，请 {max(1, window // 60)} 分钟后再试",
        )


EXEMPT_CSRF = {
    "/api/auth/dev-login",
    "/api/auth/logout",
    "/api/auth/cas/login",
    "/api/auth/cas/callback",
    "/api/auth/oidc/login",
    "/api/auth/oidc/callback",
}


class CSRFMiddleware:
    """纯 ASGI 中间件：校验同源与会话 CSRF，不依赖第三方包。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        method = scope.get("method", "GET").upper()
        path = scope.get("path", "")
        if method in {"POST", "PUT", "PATCH", "DELETE"} and path.startswith("/api/"):
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
            # 同源校验（浏览器带 Origin 时）
            origin = headers.get("origin", "")
            host = headers.get("host", "")
            if origin and host:
                import urllib.parse

                origin_host = urllib.parse.urlsplit(origin).netloc
                if origin_host and origin_host != host:
                    return await _json_response(send, 403, "跨站请求被拒绝")
            if path not in EXEMPT_CSRF:
                cookie = _cookie_value(headers.get("cookie", ""), SESSION_COOKIE)
                token = headers.get("x-csrf-token", "")
                ok = False
                if cookie and token:
                    with db() as conn:
                        row = conn.execute(
                            "SELECT csrf FROM sessions WHERE token_hash = ? AND expires_at > ?",
                            (sha256(cookie), iso(now_utc())),
                        ).fetchone()
                        ok = bool(row and hmac.compare_digest(row["csrf"], token))
                if not ok:
                    return await _json_response(
                        send, 403, "安全校验失败，请刷新页面后重试"
                    )
        return await self.app(scope, receive, send)


def _cookie_value(cookie_header: str, name: str) -> str:
    for part in cookie_header.split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value
    return ""


async def _json_response(send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}, ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
