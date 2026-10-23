"""运行入口：python -m app [--host 127.0.0.1] [--port 8765] [--reload]"""
from __future__ import annotations

import argparse

import uvicorn

from .config import settings


def main() -> None:
    parser = argparse.ArgumentParser(description="ECNU 小助手")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument("--reload", action="store_true", help="开发时自动重载")
    args = parser.parse_args()
    print(f"ECNU 小助手：http://{args.host}:{args.port}  （Ctrl+C 停止）")
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
