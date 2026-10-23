"""后台调度：到期提醒、定期计划、清理过期数据。

一次触发后：
- 一次性提醒保留记录（done=0，但 last_fired_at 已覆盖本次 due，不会重复触发）；
- 重复提醒推进到下一次触发时间；
- 通知写入 notifications 表，并通过 SSE 推送；按用户勾选调用本机弹窗。
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any

from ..db import db, jdumps
from ..security import anonymous_name  # noqa: F401  (保持模块内可用)
from ..timeutil import (
    iso,
    local_day,
    local_now,
    next_occurrence,
    now_utc,
    parse_dt,
)
from . import notifier
from .events import hub

_stop: asyncio.Event | None = None
_task: asyncio.Task | None = None
_tick_count = 0


def _insert_notification(conn, user_id: int, kind: str, payload: dict[str, Any]) -> int:
    cur = conn.execute(
        "INSERT INTO notifications (user_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
        (user_id, kind, jdumps(payload), iso(now_utc())),
    )
    return int(cur.lastrowid)


def _notify(user_id: int, kind: str, payload: dict[str, Any]) -> None:
    hub.publish(
        user_id,
        {"type": "notification", "kind": kind, "payload": payload, "created_at": iso(now_utc())},
    )


def fire_reminders(now: datetime | None = None) -> int:
    now = now or now_utc()
    fired = 0
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE done = 0 AND due_at <= ? "
            "AND (last_fired_at IS NULL OR last_fired_at < due_at) "
            "ORDER BY due_at LIMIT 50",
            (iso(now),),
        ).fetchall()
        for row in rows:
            reminder = dict(row)
            due = parse_dt(reminder["due_at"])
            if due is None:
                continue
            channels = json.loads(reminder.get("channels") or '["inapp"]')
            overdue = now - due
            advance = reminder["recurrence"] != "once"
            payload = {
                "reminder_id": reminder["id"],
                "title": reminder["title"],
                "notes": reminder.get("notes", ""),
                "due_at": reminder["due_at"],
                "channels": channels,
                "overdue_hours": max(0, int(overdue.total_seconds() // 3600)),
            }
            if advance:
                following = next_occurrence(due, reminder["recurrence"], now)
                conn.execute(
                    "UPDATE reminders SET due_at = ?, last_fired_at = ? WHERE id = ?",
                    (iso(following), iso(now), reminder["id"]),
                )
            else:
                conn.execute(
                    "UPDATE reminders SET last_fired_at = ? WHERE id = ?",
                    (iso(now), reminder["id"]),
                )
            # 超过 7 天才回到应用的旧提醒只推进时间，避免一次刷出大量通知
            if overdue > timedelta(days=7):
                continue
            _insert_notification(conn, int(reminder["user_id"]), "reminder", payload)
            for channel in channels:
                conn.execute(
                    "INSERT INTO reminder_log (reminder_id, fired_at, channel, status) "
                    "VALUES (?, ?, ?, 'pending')",
                    (reminder["id"], iso(now), channel),
                )
            fired += 1
            hub.publish(int(reminder["user_id"]), {"type": "reminder", "payload": payload})
            if {"system", "cmd"} & set(channels):
                result = notifier.dispatch(
                    int(reminder["id"]), reminder["title"], reminder.get("notes", ""), channels
                )
                for channel, ok in result.items():
                    conn.execute(
                        "UPDATE reminder_log SET status = ? WHERE reminder_id = ? AND channel = ? "
                        "AND status = 'pending'",
                        ("sent" if ok else "failed", reminder["id"], channel),
                    )
    return fired


def fire_plan_notices(now: datetime | None = None) -> int:
    moment = (now or now_utc()).astimezone(local_now().tzinfo)
    day = local_day(moment)
    minute = moment.hour * 60 + moment.minute
    planned = 0
    with db() as conn:
        rows = conn.execute(
            "SELECT p.*, pr.completed AS today_completed FROM plans p "
            "LEFT JOIN plan_progress pr ON pr.plan_id = p.id AND pr.day = ? "
            "WHERE p.active = 1 AND p.reminder_time != ''",
            (day,),
        ).fetchall()
        for row in rows:
            plan = dict(row)
            if plan.get("today_completed"):
                continue
            if plan["cadence"] == "weekly":
                weekdays = json.loads(plan.get("weekdays") or "[]")
                if weekdays and moment.isoweekday() not in weekdays:
                    continue
            try:
                hour, minute_part = (int(x) for x in plan["reminder_time"].split(":"))
            except (ValueError, AttributeError):
                continue
            target = hour * 60 + minute_part
            if not (0 <= minute - target <= 2):
                continue
            exists = conn.execute(
                "SELECT 1 FROM plan_notices WHERE plan_id = ? AND day = ?", (plan["id"], day)
            ).fetchone()
            if exists:
                continue
            conn.execute("INSERT INTO plan_notices (plan_id, day) VALUES (?, ?)", (plan["id"], day))
            payload = {
                "plan_id": plan["id"],
                "title": plan["title"],
                "target": plan["target_count"],
                "unit": plan["unit"],
                "time": plan["reminder_time"],
            }
            _insert_notification(conn, int(plan["user_id"]), "plan", payload)
            _notify(int(plan["user_id"]), "plan", payload)
            planned += 1
    return planned


def cleanup() -> None:
    with db() as conn:
        now = iso(now_utc())
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        conn.execute("DELETE FROM auth_states WHERE expires_at < ?", (now,))
        conn.execute(
            "DELETE FROM api_cache WHERE created_at < ?",
            (iso(now_utc() - timedelta(days=14)),),
        )


def tick(now: datetime | None = None) -> dict[str, int]:
    global _tick_count
    _tick_count += 1
    reminders = fire_reminders(now)
    plans = fire_plan_notices(now)
    if _tick_count % 60 == 0:
        cleanup()
    return {"reminders": reminders, "plans": plans}


async def loop() -> None:
    stop_event = _stop
    if stop_event is None:
        return
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(tick)
        except Exception:
            # 调度器不能因单次异常退出
            pass
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=20)
        except TimeoutError:
            continue


def start() -> None:
    global _task, _stop
    _stop = asyncio.Event()
    if _task is None or _task.done():
        _task = asyncio.create_task(loop(), name="ecnu-scheduler")


async def stop() -> None:
    if _stop is not None:
        _stop.set()
    if _task is not None:
        try:
            await asyncio.wait_for(_task, timeout=5)
        except (TimeoutError, asyncio.CancelledError):
            _task.cancel()
