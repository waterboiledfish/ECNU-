"""时间与日期工具：存储用 UTC，展示/计划用站点时区。"""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import settings


def tz() -> ZoneInfo:
    try:
        return ZoneInfo(settings.timezone)
    except Exception:  # pragma: no cover - 极端环境缺少 tzdata 时退回固定时区
        if settings.timezone == "Asia/Shanghai":
            return timezone(timedelta(hours=8), "Asia/Shanghai")  # type: ignore[return-value]
        return UTC  # type: ignore[return-value]


def now_utc() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="seconds")


def now_iso() -> str:
    return iso(now_utc())


def parse_dt(value: str | datetime | None) -> datetime | None:
    """解析 ISO 时间；无时区视为 UTC。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def local_now() -> datetime:
    return now_utc().astimezone(tz())


def local_day(moment: datetime | None = None) -> str:
    dt = (moment or now_utc()).astimezone(tz())
    return dt.date().isoformat()


def parse_local_day(day: str) -> date:
    return date.fromisoformat(day)


def local_hm(moment: datetime | None = None) -> str:
    return (moment or now_utc()).astimezone(tz()).strftime("%H:%M")


def to_local(moment: datetime) -> datetime:
    return moment.astimezone(tz())


def at_local_time(day: date, hm: str) -> datetime:
    hour, minute = (int(x) for x in hm.split(":"))
    return datetime.combine(day, time(hour=hour, minute=minute), tzinfo=tz())


def next_occurrence(due_at: datetime, recurrence: str, after: datetime | None = None) -> datetime:
    """计算下一次触发时间，保持用户本地墙钟时间。"""
    after = after or now_utc()
    current = due_at.astimezone(tz())
    steps = 0
    if recurrence == "daily":
        while current <= after and steps < 1000:
            current += timedelta(days=1)
            steps += 1
    elif recurrence == "weekly":
        while current <= after and steps < 500:
            current += timedelta(days=7)
            steps += 1
    elif recurrence == "monthly":
        while current <= after and steps < 120:
            current = _add_month(current)
            steps += 1
    return current.astimezone(UTC)


def _add_month(dt: datetime) -> datetime:
    year = dt.year + (1 if dt.month == 12 else 0)
    month = 1 if dt.month == 12 else dt.month + 1
    day = min(dt.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                       31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return dt.replace(year=year, month=month, day=day)


def human_local(value: str | datetime | None) -> str:
    dt = parse_dt(value)
    if not dt:
        return ""
    return dt.astimezone(tz()).strftime("%Y-%m-%d %H:%M")


def human_day(day: str) -> str:
    try:
        d = parse_local_day(day)
    except ValueError:
        return day
    return f"{d.month}月{d.day}日"


def relative_time(value: str | datetime | None) -> str:
    dt = parse_dt(value)
    if not dt:
        return ""
    seconds = int((now_utc() - dt).total_seconds())
    future = seconds < 0
    seconds = abs(seconds)
    if seconds < 60:
        text = "刚刚"
    elif seconds < 3600:
        text = f"{seconds // 60} 分钟"
    elif seconds < 86400:
        text = f"{seconds // 3600} 小时"
    elif seconds < 86400 * 30:
        text = f"{seconds // 86400} 天"
    else:
        return human_local(dt)
    return f"{text}后" if future else f"{text}前"


def day_range_local(day: str) -> tuple[datetime, datetime]:
    d = parse_local_day(day)
    start = datetime.combine(d, time(0, 0), tzinfo=tz())
    end = datetime.combine(d + timedelta(days=1), time(0, 0), tzinfo=tz())
    return start.astimezone(UTC), end.astimezone(UTC)
