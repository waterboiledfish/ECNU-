from __future__ import annotations

from datetime import timedelta

from app.services import scheduler
from app.timeutil import iso, now_utc


def test_reminder_crud_and_validation(auth):
    client, headers = auth["client"], auth["headers"]
    due = iso(now_utc() + timedelta(hours=2))
    response = client.post(
        "/api/reminders",
        json={"title": "去图书馆还书", "notes": "带学生卡", "due_at": due, "channels": ["inapp", "browser"]},
        headers=headers,
    )
    assert response.status_code == 201
    reminder = response.json()
    assert reminder["channels"] == ["inapp", "browser"]
    assert reminder["due_at"] == due
    reminder_id = reminder["id"]

    listing = client.get("/api/reminders").json()
    assert len(listing["upcoming"]) == 1
    assert "cmd" in listing["meta"]["available_channels"]

    response = client.post(
        "/api/reminders",
        json={"title": "x", "due_at": due, "channels": ["email"]},
        headers=headers,
    )
    assert response.status_code == 400

    response = client.post(
        "/api/reminders",
        json={"title": "x", "due_at": "not-a-date", "channels": ["inapp"]},
        headers=headers,
    )
    assert response.status_code == 400

    response = client.post(f"/api/reminders/{reminder_id}/snooze", json={"minutes": 30}, headers=headers)
    assert response.status_code == 200
    assert "message" in response.json()

    response = client.post(f"/api/reminders/{reminder_id}/complete", headers=headers)
    assert response.status_code == 200
    assert client.get("/api/reminders").json()["done"][0]["id"] == reminder_id


def test_reminder_fires_once_and_notifies(auth):
    client, headers = auth["client"], auth["headers"]
    due = iso(now_utc() - timedelta(minutes=5))
    response = client.post(
        "/api/reminders",
        json={"title": "提交课程论文", "due_at": due, "recurrence": "once", "channels": ["inapp"]},
        headers=headers,
    )
    assert response.status_code == 201
    fired = scheduler.fire_reminders()
    assert fired == 1
    notifications = client.get("/api/notifications").json()
    assert notifications["unread"] == 1
    assert notifications["items"][0]["kind"] == "reminder"
    assert notifications["items"][0]["payload"]["title"] == "提交课程论文"
    assert scheduler.fire_reminders() == 0


def test_recurring_reminder_advances(auth):
    client, headers = auth["client"], auth["headers"]
    due = iso(now_utc() - timedelta(days=1))
    response = client.post(
        "/api/reminders",
        json={"title": "每天背单词", "due_at": due, "recurrence": "daily", "channels": ["inapp"]},
        headers=headers,
    )
    reminder_id = response.json()["id"]
    scheduler.fire_reminders()
    listing = client.get("/api/reminders").json()
    reminder = next(item for item in listing["upcoming"] if item["id"] == reminder_id)
    assert reminder["done"] is False
    assert reminder["due_at"] > iso(now_utc())
    assert reminder["fired"] is True


def test_plan_progress_and_stats(auth):
    client, headers = auth["client"], auth["headers"]
    response = client.post(
        "/api/plans",
        json={"title": "每天读 10 页书", "category": "reading", "target_count": 2, "unit": "页", "reminder_time": "20:00"},
        headers=headers,
    )
    assert response.status_code == 201
    plan = response.json()
    plan_id = plan["id"]
    assert plan["today"]["done"] == 0

    client.post(f"/api/plans/{plan_id}/progress", json={"delta": 1}, headers=headers)
    result = client.post(f"/api/plans/{plan_id}/progress", json={"delta": 1}, headers=headers).json()
    assert result["today"]["done"] == 2
    assert result["today"]["completed"] is True
    assert result["plan"]["streak"] == 1

    stats = client.get(f"/api/plans/{plan_id}/stats").json()
    assert stats["completed_days"] == 1
    assert len(stats["history"]) == 30

    undo = client.post(f"/api/plans/{plan_id}/progress", json={"delta": -1}, headers=headers).json()
    assert undo["today"]["done"] == 1
    assert undo["today"]["completed"] is False


def test_weekly_plan_requires_weekdays(auth):
    response = auth["client"].post(
        "/api/plans",
        json={"title": "每周跑步", "category": "exercise", "cadence": "weekly", "target_count": 30, "unit": "分钟"},
        headers=auth["headers"],
    )
    assert response.status_code == 400


def test_vocabulary_session(auth):
    client, headers = auth["client"], auth["headers"]
    plan = client.post(
        "/api/plans",
        json={"title": "六级词汇", "category": "vocab", "target_count": 5, "unit": "个"},
        headers=headers,
    ).json()
    plan_id = plan["id"]
    started = client.post(
        f"/api/plans/{plan_id}/vocab/start", json={"size": 5, "mode": "mixed"}, headers=headers
    )
    assert started.status_code == 200
    session = started.json()
    assert session["size"] == 5
    assert len({item["word"] for item in session["items"]}) == 5

    results = [
        {"word": item["word"], "known": index % 2 == 0, "meaning": item["meaning"], "example": item["example"]}
        for index, item in enumerate(session["items"])
    ]
    graded = client.post(
        f"/api/plans/{plan_id}/vocab/grade",
        json={"session_id": session["session_id"], "results": results},
        headers=headers,
    )
    assert graded.status_code == 200
    assert graded.json()["score"] == 3
    assert graded.json()["today"]["done"] == 5

    overview = client.get(f"/api/plans/{plan_id}/vocab/overview").json()
    assert overview["learned"] == 5
    assert overview["sessions"] == 1

    again = client.post(
        f"/api/plans/{plan_id}/vocab/grade",
        json={"session_id": session["session_id"], "results": results},
        headers=headers,
    )
    assert again.status_code == 400


def test_plan_coach_without_key(auth):
    client, headers = auth["client"], auth["headers"]
    plan = client.post(
        "/api/plans",
        json={"title": "每天练吉他", "category": "skill", "target_count": 1, "unit": "次"},
        headers=headers,
    ).json()
    response = client.post(f"/api/plans/{plan['id']}/coach", json={}, headers=headers)
    assert response.status_code == 200
    assert response.json()["mode"] == "local"
    assert "今日建议" in response.json()["advice"]


def test_plan_custom_label_without_target_count(auth):
    client, headers = auth["client"], auth["headers"]
    response = client.post(
        "/api/plans",
        json={
            "title": "每天练吉他",
            "category": "custom",
            "category_label": "吉他练习",
            "target_count": 0,
            "unit": "次",
            "note": "练 30 分钟音阶，再弹一首曲子",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    plan = response.json()
    assert plan["category_label"] == "吉他练习"
    assert plan["target_count"] == 0
    assert plan["note"] == "练 30 分钟音阶，再弹一首曲子"

    first = client.post(f"/api/plans/{plan['id']}/progress", json={"delta": 1}, headers=headers).json()
    assert first["today"]["done"] == 1
    assert first["today"]["completed"] is True

    undo = client.post(f"/api/plans/{plan['id']}/progress", json={"delta": -1}, headers=headers).json()
    assert undo["today"]["done"] == 0
    assert undo["today"]["completed"] is False


def test_plan_category_label_update(auth):
    client, headers = auth["client"], auth["headers"]
    plan = client.post(
        "/api/plans",
        json={"title": "每周练字", "category": "custom", "category_label": "书法", "target_count": 30, "unit": "分钟"},
        headers=headers,
    ).json()
    updated = client.patch(
        f"/api/plans/{plan['id']}",
        json={"category_label": "硬笔书法", "target_count": 0},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["category_label"] == "硬笔书法"
    assert updated.json()["target_count"] == 0


def test_plan_validation(auth):
    client, headers = auth["client"], auth["headers"]
    response = client.post(
        "/api/plans",
        json={"title": "", "category": "custom", "target_count": 1},
        headers=headers,
    )
    assert response.status_code == 422 or response.status_code == 400
    response = client.post(
        "/api/plans",
        json={"title": "坏时间", "category": "custom", "target_count": 1, "reminder_time": "25:00"},
        headers=headers,
    )
    assert response.status_code == 400
