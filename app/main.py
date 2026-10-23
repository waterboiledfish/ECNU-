"""FastAPI 应用装配：中间件、路由、静态前端与生命周期。"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import settings
from .db import db, init_db
from .routers import (
    admin,
    auth,
    chat,
    dashboard,
    events,
    forum,
    messages,
    meta,
    news,
    papers,
    plans,
    profile,
    reminders,
    sources,
    study,
)
from .security import CSRFMiddleware, get_current_user
from .services import index, scheduler
from .services.events import hub
from .timeutil import now_iso

logger = logging.getLogger("ecnu")
WEB_DIR = Path(__file__).resolve().parent / "web"
AVATAR_RE = re.compile(r"^[a-f0-9]{20}\.png$")


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                path = scope.get("path", "")
                if path.startswith("/api/") and not path.startswith("/api/media/"):
                    headers.append((b"cache-control", b"no-store"))
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"strict-origin-when-cross-origin"),
                        (
                            b"permissions-policy",
                            b"geolocation=(), microphone=(), camera=(), payment=()",
                        ),
                        (
                            b"content-security-policy",
                            b"default-src 'self'; img-src 'self' data:; "
                            b"style-src 'self' 'unsafe-inline'; script-src 'self'; "
                            b"connect-src 'self'; font-src 'self' data:; object-src 'none'; "
                            b"base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
                        ),
                    ]
                )
            await send(message)

        await self.app(scope, receive, send_wrapper)


class BodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        length = headers.get("content-length")
        if length and length.isdigit() and int(length) > settings.max_body_bytes:
            body = json.dumps({"detail": "请求体过大"}, ensure_ascii=False).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 413,
                    "headers": [(b"content-type", b"application/json; charset=utf-8")],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    hub.bind_loop(asyncio.get_running_loop())
    scheduler.start()
    # 上次进程可能是被强杀的，把残留的「进行中」采集任务标记掉
    with db() as conn:
        conn.execute(
            "UPDATE crawl_runs SET status = 'interrupted', finished_at = ? WHERE status = 'running'",
            (now_iso(),),
        )
    # 后台预热检索索引：语料大时不把首页请求卡住
    index.warmup_async()
    logger.info(
        "ECNU 小助手 %s 已启动 · 登录模式=%s · 数据目录=%s",
        __version__,
        settings.auth_mode,
        settings.data_dir,
    )
    if settings.auth_mode == "dev":
        logger.warning("当前为本地演示登录模式，未连接学校统一身份认证。")
    try:
        yield
    finally:
        await scheduler.stop()


app = FastAPI(
    title="ECNU 小助手 API",
    version=__version__,
    description="面向华东师范大学学生的本地优先助手：官网文件问答、待办提醒、学习计划、论坛与推荐。",
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(BodyLimitMiddleware)
app.add_middleware(CSRFMiddleware)

for module in (
    auth,
    chat,
    reminders,
    plans,
    forum,
    messages,
    events,
    papers,
    news,
    study,
    sources,
    profile,
    dashboard,
    meta,
    admin,
):
    app.include_router(module.router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("未处理异常：%s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误，请稍后重试"})


@app.get("/api/health", tags=["meta"])
def health():
    with db() as conn:
        conn.execute("SELECT 1").fetchone()
    return {
        "status": "ok",
        "version": __version__,
        "mode": settings.auth_mode,
        "time": now_iso(),
    }


@app.get("/api/media/avatar/{name}", tags=["media"])
def avatar_file(name: str, user: dict = Depends(get_current_user)):
    if not AVATAR_RE.match(name):
        raise HTTPException(status_code=404, detail="头像不存在")
    path = settings.avatar_dir / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="头像不存在")
    return FileResponse(
        path,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/")
def index_page():
    return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/favicon.ico")
def favicon():
    return FileResponse(WEB_DIR / "favicon.svg", media_type="image/svg+xml")


@app.get("/{path:path}")
def spa_fallback(path: str, request: Request):
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="接口不存在")
    candidate = (WEB_DIR / path).resolve()
    if WEB_DIR.resolve() in candidate.parents and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})
