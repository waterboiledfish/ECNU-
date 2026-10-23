"""定期计划：每日/每周目标、打卡进度、词汇背诵与 AI 教练。"""
from __future__ import annotations

import json
import random
import re
from datetime import timedelta
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..db import db
from ..deps import client_llm
from ..security import enforce_rate, get_current_user
from ..services import llm, planner
from ..timeutil import iso, local_day, now_utc, parse_local_day

router = APIRouter(prefix="/api/plans", tags=["plans"])

CATEGORIES = ("vocab", "reading", "exercise", "skill", "custom")
_WORD_FILE = Path(__file__).resolve().parent.parent / "data" / "cet6_words.json"
_WORDS: list[dict] | None = None
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def word_bank() -> list[dict]:
    global _WORDS
    if _WORDS is None:
        try:
            data = json.loads(_WORD_FILE.read_text(encoding="utf-8"))
            _WORDS = data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            _WORDS = []
    return _WORDS


def _today() -> str:
    return local_day()


def _get_plan(conn, plan_id: int, user_id: int):
    row = conn.execute(
        "SELECT * FROM plans WHERE id = ? AND user_id = ?", (plan_id, user_id)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="计划不存在")
    return row


def _progress_row(conn, plan_id: int, day: str):
    return conn.execute(
        "SELECT * FROM plan_progress WHERE plan_id = ? AND day = ?", (plan_id, day)
    ).fetchone()


def _streak(conn, plan_id: int, today: str) -> int:
    rows = conn.execute(
        "SELECT day FROM plan_progress WHERE plan_id = ? AND completed = 1", (plan_id,)
    ).fetchall()
    days = {r["day"] for r in rows}
    cursor = parse_local_day(today)
    if cursor.isoformat() not in days:
        cursor -= timedelta(days=1)
    streak = 0
    while cursor.isoformat() in days and streak < 3650:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def _history(conn, plan_id: int, days: int = 14) -> list[dict]:
    start = parse_local_day(_today()) - timedelta(days=days - 1)
    rows = conn.execute(
        "SELECT day, done_count, completed FROM plan_progress "
        "WHERE plan_id = ? AND day >= ? ORDER BY day",
        (plan_id, start.isoformat()),
    ).fetchall()
    mapping = {r["day"]: r for r in rows}
    result = []
    for offset in range(days):
        day = (start + timedelta(days=offset)).isoformat()
        row = mapping.get(day)
        result.append(
            {
                "day": day,
                "label": day[5:],
                "done": int(row["done_count"]) if row else 0,
                "completed": bool(row["completed"]) if row else False,
            }
        )
    return result


def serialize_plan(conn, row) -> dict:
    day = _today()
    progress = _progress_row(conn, int(row["id"]), day)
    done = int(progress["done_count"]) if progress else 0
    completed = bool(progress["completed"]) if progress else False
    return {
        "id": row["id"],
        "title": row["title"],
        "category": row["category"],
        "cadence": row["cadence"],
        "weekdays": json.loads(row["weekdays"] or "[]"),
        "target_count": row["target_count"],
        "unit": row["unit"],
        "reminder_time": row["reminder_time"],
        "note": row["note"],
        "active": bool(row["active"]),
        "created_at": row["created_at"],
        "today": {"day": day, "done": done, "target": row["target_count"], "completed": completed},
        "streak": _streak(conn, int(row["id"]), day),
        "history": _history(conn, int(row["id"]), 7),
    }


def _validate_time(value: str) -> str:
    value = (value or "").strip()
    if value and not _TIME_RE.match(value):
        raise HTTPException(status_code=400, detail="提醒时间格式应为 HH:MM")
    return value


def _validate_weekdays(values: list[int]) -> list[int]:
    cleaned = sorted({int(x) for x in values if 1 <= int(x) <= 7})
    return cleaned


class PlanCreate(BaseModel):
    title: str = Field(min_length=1, max_length=60)
    category: Literal["vocab", "reading", "exercise", "skill", "custom"] = "custom"
    cadence: Literal["daily", "weekly"] = "daily"
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    target_count: int = Field(default=1, ge=1, le=999)
    unit: str = Field(default="次", max_length=8)
    reminder_time: str = Field(default="", max_length=5)
    note: str = Field(default="", max_length=500)
    active: bool = True


class PlanUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=60)
    category: Literal["vocab", "reading", "exercise", "skill", "custom"] | None = None
    cadence: Literal["daily", "weekly"] | None = None
    weekdays: list[int] | None = None
    target_count: int | None = Field(default=None, ge=1, le=999)
    unit: str | None = Field(default=None, max_length=8)
    reminder_time: str | None = None
    note: str | None = Field(default=None, max_length=500)
    active: bool | None = None


class ProgressIn(BaseModel):
    delta: int = Field(default=1, ge=-999, le=999)


class VocabStart(BaseModel):
    size: int = Field(default=20, ge=5, le=30)
    mode: Literal["mixed", "ai", "review"] = "mixed"


class VocabResult(BaseModel):
    word: str = Field(min_length=1, max_length=64)
    known: bool
    meaning: str = Field(default="", max_length=300)
    example: str = Field(default="", max_length=500)
    example_cn: str = Field(default="", max_length=500)


class VocabGrade(BaseModel):
    session_id: int
    results: list[VocabResult] = Field(min_length=1, max_length=40)


@router.get("")
def list_plans(user: dict = Depends(get_current_user)):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM plans WHERE user_id = ? ORDER BY active DESC, id DESC", (user["id"],)
        ).fetchall()
        plans = [serialize_plan(conn, row) for row in rows]
    today = _today()
    active = [p for p in plans if p["active"]]
    completed_today = sum(1 for p in active if p["today"]["completed"])
    return {
        "plans": plans,
        "summary": {
            "active": len(active),
            "completed_today": completed_today,
            "day": today,
        },
    }


@router.post("", status_code=201)
def create_plan(payload: PlanCreate, user: dict = Depends(get_current_user)):
    weekdays = _validate_weekdays(payload.weekdays)
    if payload.cadence == "weekly" and not weekdays:
        raise HTTPException(status_code=400, detail="每周计划请至少选择一个星期几")
    reminder_time = _validate_time(payload.reminder_time)
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO plans (user_id, title, category, cadence, weekdays, target_count, "
            "unit, reminder_time, note, active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user["id"],
                payload.title.strip(),
                payload.category,
                payload.cadence,
                json.dumps(weekdays),
                payload.target_count,
                payload.unit.strip() or "次",
                reminder_time,
                payload.note.strip(),
                1 if payload.active else 0,
                iso(now_utc()),
            ),
        )
        row = conn.execute("SELECT * FROM plans WHERE id = ?", (cur.lastrowid,)).fetchone()
        return serialize_plan(conn, row)


@router.patch("/{plan_id}")
def update_plan(plan_id: int, payload: PlanUpdate, user: dict = Depends(get_current_user)):
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="没有需要修改的内容")
    updates: list[str] = []
    values: list[object] = []
    if "title" in fields and fields["title"]:
        updates.append("title = ?")
        values.append(fields["title"].strip())
    if "category" in fields and fields["category"]:
        updates.append("category = ?")
        values.append(fields["category"])
    if "cadence" in fields and fields["cadence"]:
        updates.append("cadence = ?")
        values.append(fields["cadence"])
    if "weekdays" in fields and fields["weekdays"] is not None:
        updates.append("weekdays = ?")
        values.append(json.dumps(_validate_weekdays(fields["weekdays"])))
    if "target_count" in fields and fields["target_count"] is not None:
        updates.append("target_count = ?")
        values.append(fields["target_count"])
    if "unit" in fields and fields["unit"]:
        updates.append("unit = ?")
        values.append(fields["unit"].strip() or "次")
    if "reminder_time" in fields and fields["reminder_time"] is not None:
        updates.append("reminder_time = ?")
        values.append(_validate_time(fields["reminder_time"]))
    if "note" in fields and fields["note"] is not None:
        updates.append("note = ?")
        values.append(fields["note"].strip())
    if "active" in fields and fields["active"] is not None:
        updates.append("active = ?")
        values.append(1 if fields["active"] else 0)
    if not updates:
        raise HTTPException(status_code=400, detail="没有需要修改的内容")
    with db() as conn:
        _get_plan(conn, plan_id, user["id"])
        values.append(plan_id)
        conn.execute(f"UPDATE plans SET {', '.join(updates)} WHERE id = ?", tuple(values))
        row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
        return serialize_plan(conn, row)


@router.delete("/{plan_id}")
def delete_plan(plan_id: int, user: dict = Depends(get_current_user)):
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM plans WHERE id = ? AND user_id = ?", (plan_id, user["id"])
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="计划不存在")
    return {"ok": True}


def _apply_progress(conn, plan, delta: int) -> tuple[int, bool, str]:
    day = _today()
    row = _progress_row(conn, int(plan["id"]), day)
    current = int(row["done_count"]) if row else 0
    done = max(0, min(int(plan["target_count"]), current + delta))
    completed = done >= int(plan["target_count"])
    if row:
        conn.execute(
            "UPDATE plan_progress SET done_count = ?, completed = ?, updated_at = ? WHERE id = ?",
            (done, 1 if completed else 0, iso(now_utc()), row["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO plan_progress (plan_id, day, done_count, completed, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (plan["id"], day, done, 1 if completed else 0, iso(now_utc())),
        )
    return done, completed, day


@router.post("/{plan_id}/progress")
def update_progress(plan_id: int, payload: ProgressIn, user: dict = Depends(get_current_user)):
    with db() as conn:
        plan = _get_plan(conn, plan_id, user["id"])
        done, completed, day = _apply_progress(conn, plan, payload.delta)
        refreshed = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
        data = serialize_plan(conn, refreshed)
    return {"today": {"day": day, "done": done, "target": plan["target_count"], "completed": completed}, "plan": data}


@router.get("/{plan_id}/stats")
def plan_stats(plan_id: int, days: int = 30, user: dict = Depends(get_current_user)):
    days = max(7, min(90, days))
    with db() as conn:
        _get_plan(conn, plan_id, user["id"])
        history = _history(conn, plan_id, days)
        row = conn.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(done_count), 0) AS amount "
            "FROM plan_progress WHERE plan_id = ? AND completed = 1",
            (plan_id,),
        ).fetchone()
        streak = _streak(conn, plan_id, _today())
    return {
        "history": history,
        "completed_days": int(row["total"]) if row else 0,
        "total_amount": int(row["amount"]) if row else 0,
        "streak": streak,
    }


# ---------------------------------------------------------------- 词汇
def _due_reviews(conn, user_id: int, limit: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM vocab_reviews WHERE user_id = ? AND due_at <= ? "
        "ORDER BY due_at LIMIT ?",
        (user_id, iso(now_utc()), limit),
    ).fetchall()
    return [
        {
            "word": r["word"],
            "phonetic": "",
            "meaning": r["meaning"],
            "example": r["example"],
            "example_cn": "",
            "source": "review",
        }
        for r in rows
    ]


def _learned_words(conn, user_id: int) -> set[str]:
    rows = conn.execute("SELECT word FROM vocab_reviews WHERE user_id = ?", (user_id,)).fetchall()
    return {r["word"].lower() for r in rows}


def _new_words(exclude: set[str], count: int) -> list[dict]:
    bank = [w for w in word_bank() if w.get("word", "").lower() not in exclude]
    random.shuffle(bank)
    picked = bank[:count]
    return [
        {
            "word": w.get("word", ""),
            "phonetic": w.get("phonetic", ""),
            "meaning": w.get("meaning", ""),
            "example": w.get("example", ""),
            "example_cn": w.get("example_cn", ""),
            "source": "new",
        }
        for w in picked
    ]


def _ai_words(creds: dict, count: int, exclude: set[str]) -> list[dict]:
    avoid = "、".join(list(exclude)[:80]) or "无"
    messages = [
        {
            "role": "system",
            "content": "你是大学英语六级词汇教练。只返回 JSON 数组，不要解释。",
        },
        {
            "role": "user",
            "content": (
                f"生成 {count} 个大学英语六级核心词汇，排除这些词：{avoid}。\n"
                '返回格式：[{"word":"英文单词","phonetic":"音标","meaning":"词性 + 中文释义",'
                '"example":"英文例句","example_cn":"中文翻译"}]。'
                "每个单词与例句都要准确，不要编造拼写。"
            ),
        },
    ]
    text = llm.chat(
        messages,
        key=creds["key"],
        model=creds["model"],
        base_url=creds.get("base_url"),
        temperature=0.7,
        timeout=60,
        json_mode=True,
        max_tokens=2000,
    )
    raw = llm.parse_json_array(text)
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        word = str(item.get("word", "")).strip()
        meaning = str(item.get("meaning", "")).strip()
        if not word or not meaning or len(word) > 40:
            continue
        if word.lower() in exclude:
            continue
        result.append(
            {
                "word": word,
                "phonetic": str(item.get("phonetic", ""))[:60],
                "meaning": meaning[:200],
                "example": str(item.get("example", ""))[:400],
                "example_cn": str(item.get("example_cn", ""))[:400],
                "source": "ai",
            }
        )
        if len(result) >= count:
            break
    return result


@router.get("/{plan_id}/vocab/overview")
def vocab_overview(plan_id: int, user: dict = Depends(get_current_user)):
    now = iso(now_utc())
    with db() as conn:
        plan = _get_plan(conn, plan_id, user["id"])
        learned = conn.execute(
            "SELECT COUNT(*) AS n FROM vocab_reviews WHERE user_id = ?", (user["id"],)
        ).fetchone()
        due = conn.execute(
            "SELECT COUNT(*) AS n FROM vocab_reviews WHERE user_id = ? AND due_at <= ?",
            (user["id"], now),
        ).fetchone()
        sessions = conn.execute(
            "SELECT COUNT(*) AS n FROM vocab_sessions WHERE user_id = ? AND status = 'completed'",
            (user["id"],),
        ).fetchone()
        last = conn.execute(
            "SELECT * FROM vocab_sessions WHERE user_id = ? AND plan_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (user["id"], plan_id),
        ).fetchone()
    return {
        "plan_id": plan_id,
        "title": plan["title"],
        "learned": int(learned["n"]) if learned else 0,
        "due": int(due["n"]) if due else 0,
        "sessions": int(sessions["n"]) if sessions else 0,
        "bank_size": len(word_bank()),
        "last_session": dict(last) if last else None,
    }


@router.post("/{plan_id}/vocab/start")
def start_vocab(
    plan_id: int, payload: VocabStart, request: Request, user: dict = Depends(get_current_user)
):
    enforce_rate(request, "vocab-start", 30, 3600)
    creds = client_llm(request, required=False)
    warning = ""
    with db() as conn:
        plan = _get_plan(conn, plan_id, user["id"])
        if plan["category"] != "vocab":
            raise HTTPException(status_code=400, detail="该计划不是词汇计划")
        learned = _learned_words(conn, user["id"])
        due_count = max(5, payload.size // 2)
        items = _due_reviews(conn, user["id"], due_count) if payload.mode != "ai" else []
        used = {item["word"].lower() for item in items} | learned
        remaining = payload.size - len(items)
        if payload.mode == "ai":
            if not creds:
                warning = "未填写 API Key，已使用内置词库。"
            else:
                try:
                    items.extend(_ai_words(creds, min(remaining, 20), used))
                except llm.LLMError as exc:
                    warning = f"AI 生成词汇失败：{exc.message}，已使用内置词库。"
                used |= {item["word"].lower() for item in items}
                remaining = payload.size - len(items)
        if remaining > 0:
            items.extend(_new_words(used, remaining))
        if not items:
            raise HTTPException(
                status_code=400, detail="没有可学习的单词：词库已全部学过，且暂时无法调用 AI 生成"
            )
        session_day = _today()
        cur = conn.execute(
            "INSERT INTO vocab_sessions (user_id, plan_id, day, items, status, created_at) "
            "VALUES (?, ?, ?, ?, 'active', ?)",
            (
                user["id"],
                plan_id,
                session_day,
                json.dumps(items, ensure_ascii=False),
                iso(now_utc()),
            ),
        )
        session_id = int(cur.lastrowid)
    return {
        "session_id": session_id,
        "plan_id": plan_id,
        "size": len(items),
        "items": items,
        "warning": warning,
    }


@router.post("/{plan_id}/vocab/grade")
def grade_vocab(plan_id: int, payload: VocabGrade, user: dict = Depends(get_current_user)):
    now = now_utc()
    with db() as conn:
        _get_plan(conn, plan_id, user["id"])
        session = conn.execute(
            "SELECT * FROM vocab_sessions WHERE id = ? AND user_id = ? AND plan_id = ?",
            (payload.session_id, user["id"], plan_id),
        ).fetchone()
        if not session:
            raise HTTPException(status_code=404, detail="背诵会话不存在")
        if session["status"] == "completed":
            raise HTTPException(status_code=400, detail="本次背诵已经完成")
        score = 0
        for result in payload.results:
            word = result.word.strip()
            known = result.known
            existing = conn.execute(
                "SELECT * FROM vocab_reviews WHERE user_id = ? AND word = ?",
                (user["id"], word),
            ).fetchone()
            if existing:
                ease = float(existing["ease"])
                interval = int(existing["interval_days"])
                lapses = int(existing["lapses"])
            else:
                ease, interval, lapses = 2.5, 0, 0
            if known:
                score += 1
                ease = min(3.2, ease + 0.05)
                interval = min(180, max(2, round((interval or 1) * ease)))
            else:
                ease = max(1.3, ease - 0.2)
                interval = 1
                lapses += 1
            due = now + timedelta(days=interval)
            meaning = result.meaning or (existing["meaning"] if existing else "")
            example = result.example or (existing["example"] if existing else "")
            conn.execute(
                "INSERT INTO vocab_reviews (user_id, word, meaning, example, ease, interval_days, "
                "due_at, lapses, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id, word) DO UPDATE SET meaning = excluded.meaning, "
                "example = excluded.example, ease = excluded.ease, "
                "interval_days = excluded.interval_days, due_at = excluded.due_at, "
                "lapses = excluded.lapses, updated_at = excluded.updated_at",
                (
                    user["id"],
                    word,
                    meaning[:300],
                    example[:500],
                    ease,
                    interval,
                    iso(due),
                    lapses,
                    iso(now),
                ),
            )
        conn.execute(
            "UPDATE vocab_sessions SET status = 'completed', score = ?, completed_at = ? WHERE id = ?",
            (score, iso(now), payload.session_id),
        )
        plan = _get_plan(conn, plan_id, user["id"])
        done, completed, day = _apply_progress(conn, plan, len(payload.results))
        due = conn.execute(
            "SELECT COUNT(*) AS n FROM vocab_reviews WHERE user_id = ? AND due_at <= ?",
            (user["id"], iso(now + timedelta(days=1))),
        ).fetchone()
    total = len(payload.results)
    return {
        "score": score,
        "total": total,
        "accuracy": round(score / total * 100) if total else 0,
        "due_tomorrow": int(due["n"]) if due else 0,        "today": {"day": day, "done": done, "target": plan["target_count"], "completed": completed},
    }


@router.post("/{plan_id}/coach")
def coach(plan_id: int, request: Request, user: dict = Depends(get_current_user)):
    enforce_rate(request, "coach", 30, 3600)
    creds = client_llm(request, required=False)
    with db() as conn:
        plan = _get_plan(conn, plan_id, user["id"])
        history = _history(conn, plan_id, 7)
    advice = planner.local_advice(dict(plan), history)
    mode = "local"
    if creds:
        try:
            advice = planner.ai_advice(creds, dict(plan), history)
            mode = "ai"
        except llm.LLMError as exc:
            advice += f"\n\n（AI 教练暂时不可用：{exc.message}）"
    return {"advice": advice, "mode": mode}
