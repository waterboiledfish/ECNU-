"""首页聚合数据。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..db import db
from ..security import get_current_user
from ..services import forum as forum_service
from ..timeutil import human_local, local_now, now_iso, now_utc, parse_dt

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _greeting() -> str:
    hour = local_now().hour
    if hour < 6:
        return "夜深了"
    if hour < 12:
        return "早上好"
    if hour < 18:
        return "下午好"
    return "晚上好"


@router.get("")
def dashboard(user: dict = Depends(get_current_user)):
    now = now_utc()
    with db() as conn:
        reminder_rows = conn.execute(
            "SELECT * FROM reminders WHERE user_id = ? AND done = 0 ORDER BY due_at LIMIT 5",
            (user["id"],),
        ).fetchall()
        reminder_total = conn.execute(
            "SELECT COUNT(*) AS n FROM reminders WHERE user_id = ? AND done = 0", (user["id"],)
        ).fetchone()["n"]
        due_today = 0
        for row in reminder_rows:
            due = parse_dt(row["due_at"])
            if due and due.date() == local_now().date():
                due_today += 1
        plan_rows = conn.execute(
            "SELECT p.*, pr.done_count AS today_done, pr.completed AS today_completed "
            "FROM plans p LEFT JOIN plan_progress pr ON pr.plan_id = p.id AND pr.day = ? "
            "WHERE p.user_id = ? AND p.active = 1 ORDER BY p.id DESC LIMIT 4",
            (local_now().date().isoformat(), user["id"]),
        ).fetchall()
        plans = [
            {
                "id": row["id"],
                "title": row["title"],
                "category": row["category"],
                "target": row["target_count"],
                "unit": row["unit"],
                "done": int(row["today_done"] or 0),
                "completed": bool(row["today_completed"]),
            }
            for row in plan_rows
        ]
        recent_posts = conn.execute(
            "SELECT * FROM posts WHERE status = 'visible' ORDER BY created_at DESC LIMIT 3"
        ).fetchall()
        posts = [forum_service.serialize_post(conn, row, user["id"]) for row in recent_posts]
        unread_notifications = conn.execute(
            "SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND read_at IS NULL",
            (user["id"],),
        ).fetchone()["n"]
        unread_messages = conn.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE recipient_id = ? AND read_at IS NULL",
            (user["id"],),
        ).fetchone()["n"]
        doc_total = conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"]
        site_total = conn.execute("SELECT COUNT(*) AS n FROM sites WHERE enabled = 1").fetchone()["n"]
        crawled_sites = conn.execute(
            "SELECT COUNT(DISTINCT site_id) AS n FROM documents"
        ).fetchone()["n"]
        top_sites = conn.execute(
            "SELECT s.id, s.name, COUNT(d.id) AS doc_count FROM sites s "
            "JOIN documents d ON d.site_id = s.id GROUP BY s.id "
            "ORDER BY doc_count DESC LIMIT 4"
        ).fetchall()
    reminders = []
    for row in reminder_rows:
        due = parse_dt(row["due_at"])
        reminders.append(
            {
                "id": row["id"],
                "title": row["title"],
                "due_at": row["due_at"],
                "due_local": human_local(row["due_at"]),
                "overdue": bool(due and due < now),
                "recurrence": row["recurrence"],
            }
        )
    settings = user.get("settings") if isinstance(user.get("settings"), dict) else {}
    return {
        "greeting": _greeting(),
        "server_time": now_iso(),
        "user": {"nickname": user["nickname"], "avatar": user["avatar"]},
        "reminders": {
            "items": reminders,
            "total": int(reminder_total),
            "today": due_today,
            "overdue": sum(1 for item in reminders if item["overdue"]),
        },
        "plans": plans,
        "plans_completed_today": sum(1 for p in plans if p["completed"]),
        "forum": posts,
        "unread": {
            "notifications": int(unread_notifications),
            "messages": int(unread_messages),
        },
        "library": {
            "documents": int(doc_total),
            "sites": int(site_total),
            "crawled_sites": int(crawled_sites),
            "top_sites": [dict(row) for row in top_sites],
        },
        "preferences": {
            "news_categories": settings.get("news_categories", ["general", "tech", "finance"]),
            "directions": user.get("directions", []),
        },
    }
