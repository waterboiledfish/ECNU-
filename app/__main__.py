"""运行入口：python -m app [--host 127.0.0.1] [--port 8765] [--lan] [--reload]"""
from __future__ import annotations

import argparse

import uvicorn

from .config import settings


def main() -> None:
    parser = argparse.ArgumentParser(description="ECNU 小助手")
    parser.add_argument("--host", default=settings.host, help="监听地址；局域网共享用 0.0.0.0")
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument("--lan", action="store_true", help="等同 --host 0.0.0.0：同一局域网的同学也能访问")
    parser.add_argument("--reload", action="store_true", help="开发时自动重载")
    args = parser.parse_args()
    if args.lan:
        args.host = "0.0.0.0"
    settings.host = args.host
    settings.port = args.port

    print(f"{settings.app_name} {settings.version}")
    for url in settings.access_urls:
        print(f"  · {url}")
    if settings.lan_enabled:
        print("  已开启局域网访问：同学连同一个 Wi-Fi，用上面的局域网地址即可打开。")
        if settings.auth_mode == "dev":
            print(
                "  注意：当前是本地演示登录，能访问该地址的人都能注册；"
                "对外分享前请设置 ECNU_ADMIN_SUBJECTS，并只在可信网络里开放。"
            )
    print("  （Ctrl+C 停止）")
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
