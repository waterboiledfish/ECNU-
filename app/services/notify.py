"""站内通知：写库 + SSE 推送。"""
from __future__ import annotations

from typing import Any

from ..db import jdumps
from ..timeutil import iso, now_utc
from .events import hub


def push(conn, user_id: int, kind: str, payload: dict[str, Any]) -> int:
    cur = conn.execute(
        "INSERT INTO notifications (user_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
        (user_id, kind, jdumps(payload), iso(now_utc())),
    )
    hub.publish(
        user_id,
        {
            "type": "notification",
            "kind": kind,
            "payload": payload,
            "created_at": iso(now_utc()),
        },
    )
    return int(cur.lastrowid)


def notify_admins(conn, kind: str, payload: dict[str, Any]) -> None:
    rows = conn.execute("SELECT id FROM users WHERE role = 'admin'").fetchall()
    for row in rows:
        push(conn, int(row["id"]), kind, payload)
