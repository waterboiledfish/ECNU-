"""轻量 API 缓存（SQLite），用于论文、新闻、学习资料。"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..db import db
from ..timeutil import iso, now_utc, parse_dt


def get(key: str, ttl_seconds: int | None = None) -> Any | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM api_cache WHERE key = ?", (key,)).fetchone()
    if not row:
        return None
    created = parse_dt(row["created_at"])
    if ttl_seconds is not None and created:
        if (now_utc() - created).total_seconds() > ttl_seconds:
            return None
    try:
        return json.loads(row["body"])
    except json.JSONDecodeError:
        return None


def get_stale(key: str) -> Any | None:
    """读取可能过期的旧缓存；数据库未就绪时按「没有缓存」处理，不打断主流程。"""
    try:
        return get(key, ttl_seconds=None)
    except sqlite3.Error:
        return None


def set(key: str, value: Any) -> None:  # noqa: A001 - 与 Python 内置同名但在本模块语义清晰
    body = json.dumps(value, ensure_ascii=False)
    with db() as conn:
        conn.execute(
            "INSERT INTO api_cache (key, body, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET body = excluded.body, created_at = excluded.created_at",
            (key, body, iso(now_utc())),
        )


def age_seconds(key: str) -> int | None:
    with db() as conn:
        row = conn.execute("SELECT created_at FROM api_cache WHERE key = ?", (key,)).fetchone()
    if not row:
        return None
    created = parse_dt(row["created_at"])
    if not created:
        return None
    return int((now_utc() - created).total_seconds())
