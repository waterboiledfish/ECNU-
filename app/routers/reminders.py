"""待办事项与一次性/重复提醒。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..db import db
from ..security import enforce_rate, get_current_user
from ..services import notifier
from ..timeutil import human_local, iso, next_occurrence, now_utc, parse_dt

router = APIRouter(prefix="/api/reminders", tags=["reminders"])

RECURRENCES = ("once", "daily", "weekly", "monthly")
AVAILABLE_CHANNELS = set(notifier.channels_available())


class ReminderCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    notes: str = Field(default="", max_length=1000)
    due_at: str
    recurrence: Literal["once", "daily", "weekly", "monthly"] = "once"
    channels: list[str] = Field(default_factory=lambda: ["inapp"])


class ReminderUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=1000)
    due_at: str | None = None
    recurrence: Literal["once", "daily", "weekly", "monthly"] | None = None
    channels: list[str] | None = None


class SnoozeIn(BaseModel):
    minutes: int = Field(default=10, ge=1, le=1440)


def _channels_meta() -> dict[str, object]:
    return {
        "available_channels": sorted(AVAILABLE_CHANNELS),
        "platform": "windows" if "cmd" in AVAILABLE_CHANNELS else "other",
    }


def _validate_channels(channels: list[str]) -> list[str]:
    cleaned: list[str] = []
    for channel in channels:
        if channel not in {"inapp", "browser", "system", "cmd"}:
            raise HTTPException(status_code=400, detail="提醒方式无效")
        if channel not in AVAILABLE_CHANNELS:
            raise HTTPException(status_code=400, detail=f"当前设备不支持提醒方式：{channel}")
        if channel not in cleaned:
            cleaned.append(channel)
    return cleaned or ["inapp"]


def _parse_due(raw: str) -> datetime:
    due = parse_dt(raw)
    if not due:
        raise HTTPException(status_code=400, detail="时间格式无效")
    now = now_utc()
    if due.year < 2000 or due > now + timedelta(days=3650):
        raise HTTPException(status_code=400, detail="提醒时间超出合理范围")
    return due


def serialize(row, now: datetime | None = None) -> dict:
    now = now or now_utc()
    due = parse_dt(row["due_at"])
    channels = json.loads(row["channels"] or '["inapp"]')
    fired = bool(row["last_fired_at"])
    return {
        "id": row["id"],
        "title": row["title"],
        "notes": row["notes"],
        "due_at": row["due_at"],
        "due_local": human_local(row["due_at"]),
        "recurrence": row["recurrence"],
        "channels": channels,
        "done": bool(row["done"]),
        "overdue": bool(due and not row["done"] and due < now),
        "fired": fired,
        "last_fired_at": row["last_fired_at"],
        "created_at": row["created_at"],
    }


@router.get("")
def list_reminders(user: dict = Depends(get_current_user)):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE user_id = ? ORDER BY done, due_at", (user["id"],)
        ).fetchall()
    now = now_utc()
    upcoming = [serialize(r, now) for r in rows if not r["done"]]
    done = [serialize(r, now) for r in rows if r["done"]][-30:]
    return {"upcoming": upcoming, "done": done, "meta": _channels_meta()}


@router.post("", status_code=201)
def create_reminder(payload: ReminderCreate, request: Request, user: dict = Depends(get_current_user)):
    enforce_rate(request, "reminder-create", 60, 3600)
    due = _parse_due(payload.due_at)
    channels = _validate_channels(payload.channels)
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO reminders (user_id, title, notes, due_at, recurrence, channels, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                user["id"],
                payload.title.strip(),
                payload.notes.strip(),
                iso(due),
                payload.recurrence,
                json.dumps(channels),
                iso(now_utc()),
            ),
        )
        reminder_id = int(cur.lastrowid)
        row = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
    return serialize(row)


@router.patch("/{reminder_id}")
def update_reminder(
    reminder_id: int, payload: ReminderUpdate, user: dict = Depends(get_current_user)
):
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="没有需要修改的内容")
    updates: list[str] = []
    values: list[object] = []
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM reminders WHERE id = ? AND user_id = ?", (reminder_id, user["id"])
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="提醒不存在")
        if "title" in fields and fields["title"]:
            updates.append("title = ?")
            values.append(fields["title"].strip())
        if "notes" in fields:
            updates.append("notes = ?")
            values.append((fields["notes"] or "").strip())
        if "due_at" in fields and fields["due_at"]:
            due = _parse_due(fields["due_at"])
            updates.append("due_at = ?")
            values.append(iso(due))
            updates.append("last_fired_at = NULL")
        if "recurrence" in fields and fields["recurrence"]:
            updates.append("recurrence = ?")
            values.append(fields["recurrence"])
        if "channels" in fields and fields["channels"] is not None:
            updates.append("channels = ?")
            values.append(json.dumps(_validate_channels(fields["channels"])))
        if not updates:
            raise HTTPException(status_code=400, detail="没有需要修改的内容")
        values.append(reminder_id)
        conn.execute(f"UPDATE reminders SET {', '.join(updates)} WHERE id = ?", tuple(values))
        row = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
    return serialize(row)


@router.delete("/{reminder_id}")
def delete_reminder(reminder_id: int, user: dict = Depends(get_current_user)):
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM reminders WHERE id = ? AND user_id = ?", (reminder_id, user["id"])
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="提醒不存在")
    return {"ok": True}


@router.post("/{reminder_id}/complete")
def complete_reminder(reminder_id: int, user: dict = Depends(get_current_user)):
    now = now_utc()
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM reminders WHERE id = ? AND user_id = ?", (reminder_id, user["id"])
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="提醒不存在")
        if row["recurrence"] == "once":
            conn.execute(
                "UPDATE reminders SET done = 1, completed_at = ? WHERE id = ?",
                (iso(now), reminder_id),
            )
            message = "已完成"
        else:
            due = parse_dt(row["due_at"]) or now
            following = next_occurrence(due, row["recurrence"], now)
            conn.execute(
                "UPDATE reminders SET due_at = ?, last_fired_at = ?, done = 0 WHERE id = ?",
                (iso(following), iso(now), reminder_id),
            )
            message = f"本次已完成，下次提醒：{human_local(following)}"
        row = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
    return {"message": message, "reminder": serialize(row)}


@router.post("/{reminder_id}/snooze")
def snooze_reminder(
    reminder_id: int, payload: SnoozeIn, user: dict = Depends(get_current_user)
):
    due = now_utc() + timedelta(minutes=payload.minutes)
    with db() as conn:
        cur = conn.execute(
            "UPDATE reminders SET due_at = ?, done = 0, last_fired_at = NULL "
            "WHERE id = ? AND user_id = ?",
            (iso(due), reminder_id, user["id"]),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="提醒不存在")
        row = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
    return {"message": f"已推迟到 {human_local(due)}", "reminder": serialize(row)}
