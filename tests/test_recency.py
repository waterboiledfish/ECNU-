"""官网文件收录时间窗口：设置接口、日期判断与索引过滤。"""
from __future__ import annotations

from app.timeutil import iso, local_day, now_utc


def test_recency_helpers(auth):
    from app.db import set_meta
    from app.services import recency

    set_meta(recency.KEY, "365")
    assert recency.max_age_days() == 365
    assert recency.cutoff_day() is not None
    assert recency.is_too_old("2001-01-01") is True
    assert recency.is_too_old(local_day()) is False
    assert recency.is_too_old("") is False
    assert recency.is_too_old(None) is False
    assert recency.published_day("2024-03-05T10:00:00") == "2024-03-05"

    set_meta(recency.KEY, "0")
    assert recency.max_age_days() == 0
    assert recency.cutoff_day() is None
    assert recency.is_too_old("2001-01-01") is False


def test_settings_endpoint(auth):
    client, headers = auth["client"], auth["headers"]
    payload = client.get("/api/sources").json()
    assert "max_age_days" in payload
    assert payload["age_choices"] == [0, 365, 730, 1095, 1825]

    response = client.patch("/api/sources/settings", json={"max_age_days": 365}, headers=headers)
    assert response.status_code == 200
    assert response.json()["max_age_days"] == 365
    assert client.get("/api/sources").json()["max_age_days"] == 365

    response = client.patch("/api/sources/settings", json={"max_age_days": 0}, headers=headers)
    assert response.json()["max_age_days"] == 0

    assert (
        client.patch("/api/sources/settings", json={"max_age_days": 99999}, headers=headers).status_code
        == 422
    )


def test_index_skips_documents_outside_window(auth):
    from app.db import db
    from app.services import index, recency

    with db() as conn:
        site_id = conn.execute("SELECT id FROM sites ORDER BY id LIMIT 1").fetchone()["id"]
        cursor = conn.execute(
            "INSERT INTO documents (site_id, url, title, published_at, fetched_at, content_type, "
            "sha256, text, char_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                site_id,
                "https://www.ecnu.edu.cn/ancient.html",
                "二〇〇一年的旧通知",
                "2001-01-01",
                iso(now_utc()),
                "text/html",
                "deadbeef",
                "这是一份很久以前的通知内容。",
                14,
            ),
        )
        conn.execute(
            "INSERT INTO chunks (document_id, ordinal, text) VALUES (?, 0, ?)",
            (int(cursor.lastrowid), "这是一份很久以前的通知内容。"),
        )

    recency.set_max_age_days(365)
    index.invalidate()
    stats = index.stats()
    assert stats["chunks"] == 0
    assert stats["documents"] == 0

    recency.set_max_age_days(0)
    index.invalidate()
    stats = index.stats()
    assert stats["chunks"] == 1
    assert stats["documents"] == 1
