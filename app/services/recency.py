"""官网文件收录时间窗口：只把「最近 N 天内发布」的文件收进检索库。

- 0 表示不限制，任何年份的文件都收录。
- 发布日期未知（页面上没写）的文件照常收录，避免把大量通知类页面挡在门外。
- 窗口存在 meta 表里，管理员可在「官网文件」页面调整，修改后索引会自动重建。
"""
from __future__ import annotations

import re
from datetime import timedelta

from ..config import settings
from ..db import get_meta, set_meta
from ..timeutil import local_day, parse_local_day

KEY = "source_max_age_days"
CHOICES = (0, 365, 730, 1095, 1825)
MAX_DAYS = 36500
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def max_age_days() -> int:
    """当前生效的收录窗口（天），0 = 不限。"""
    raw = get_meta(KEY, "")
    if raw:
        try:
            return max(0, min(MAX_DAYS, int(raw)))
        except ValueError:
            pass
    return max(0, min(MAX_DAYS, int(settings.source_max_age_days)))


def set_max_age_days(days: int) -> int:
    value = max(0, min(MAX_DAYS, int(days)))
    set_meta(KEY, str(value))
    return value


def cutoff_day(days: int | None = None) -> str | None:
    """窗口起点（YYYY-MM-DD）；不限时返回 None。"""
    value = max_age_days() if days is None else max(0, int(days))
    if value <= 0:
        return None
    return (parse_local_day(local_day()) - timedelta(days=value)).isoformat()


def published_day(value: str | None) -> str | None:
    """把 published_at 归一化成 YYYY-MM-DD；无法识别时返回 None。"""
    if not value:
        return None
    match = _DATE_RE.match(str(value).strip())
    return match.group(0) if match else None


def is_too_old(published_at: str | None, days: int | None = None, cutoff: str | None = None) -> bool:
    """判断一份文件是否超出收录窗口。

    大量调用（例如建索引）请传 cutoff：否则每次都会读一次 meta 表，
    几千条就是几千次数据库连接。
    """
    day = published_day(published_at)
    if not day:
        return False
    cut = cutoff if cutoff is not None else cutoff_day(days)
    if not cut:
        return False
    return day < cut
