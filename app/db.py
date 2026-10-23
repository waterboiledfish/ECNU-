"""SQLite 连接、建表与站点种子数据。"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT, settings
from .timeutil import now_iso

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SOURCES_PATH = Path(__file__).with_name("data") / "sources.json"


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    """每次操作使用独立连接，提交/回滚后关闭。"""
    conn = sqlite3.connect(settings.db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        _seed_sites(conn)
        _set_meta(conn, "schema_version", "1")
        if _get_meta(conn, "index_version") is None:
            _set_meta(conn, "index_version", "1")


def _seed_sites(conn: sqlite3.Connection) -> None:
    if not SOURCES_PATH.is_file():
        return
    try:
        payload = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    for item in payload.get("sites", []):
        key = item.get("key") or item["url"]
        conn.execute(
            """
            INSERT INTO sites (key, name, url, category, description, enabled)
            VALUES (?, ?, ?, ?, ?, 1)
            ON CONFLICT(key) DO UPDATE SET
                name = excluded.name,
                url = excluded.url,
                category = excluded.category,
                description = excluded.description
            """,
            (
                key,
                item["name"],
                item["url"],
                item.get("category", "院系"),
                item.get("description", ""),
            ),
        )
    # 站点文档数按实际数据校准（重复执行安全）
    conn.execute(
        """
        UPDATE sites SET doc_count = (
            SELECT COUNT(*) FROM documents WHERE documents.site_id = sites.id
        )
        """
    )


def _get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def get_meta(key: str, default: str = "") -> str:
    with db() as conn:
        value = _get_meta(conn, key)
    return value if value is not None else default


def set_meta(key: str, value: str) -> None:
    with db() as conn:
        _set_meta(conn, key, value)


def bump_index_version() -> None:
    with db() as conn:
        current = int(_get_meta(conn, "index_version") or "0")
        _set_meta(conn, "index_version", str(current + 1))


def rowdict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def rowsdict(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def jloads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def jdumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def insert_and_get_id(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> int:
    cur = conn.execute(sql, params)
    return int(cur.lastrowid)


def cleanup_expired(conn: sqlite3.Connection) -> None:
    now = now_iso()
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
    conn.execute("DELETE FROM auth_states WHERE expires_at < ?", (now,))


def count(conn: sqlite3.Connection, table: str, where: str = "", params: tuple[Any, ...] = ()) -> int:
    sql = f"SELECT COUNT(*) AS n FROM {table}"
    if where:
        sql += f" WHERE {where}"
    row = conn.execute(sql, params).fetchone()
    return int(row["n"]) if row else 0


def data_dir() -> Path:
    return settings.data_dir


def project_root() -> Path:
    return PROJECT_ROOT
