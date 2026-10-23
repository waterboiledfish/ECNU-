"""开发用冒烟检查：不依赖外部网络与真实 API Key。运行：python scripts/smoke.py"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA = Path(tempfile.mkdtemp(prefix="ecnu-smoke-"))
os.environ["ECNU_DATA_DIR"] = str(DATA)
os.environ["ECNU_AUTH_MODE"] = "dev"
os.environ["ECNU_DEV_LOGIN_ENABLED"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import bump_index_version, db  # noqa: E402
from app.main import app  # noqa: E402
from app.services import llm, scheduler  # noqa: E402
from app.timeutil import iso, now_utc  # noqa: E402


def show(label, response):
    ok = "OK " if response.status_code < 400 else "ERR"
    text = response.text[:160].replace("\n", " ")
    print(f"{ok} {label:38s} {response.status_code} {text}")
    if response.status_code >= 500:
        raise SystemExit(1)
    return response


def main() -> int:
    llm.chat = lambda messages, **kwargs: "这是基于资料 [1] 的回答。"
    def fake_stream(messages, **kwargs):
        yield "这是"
        yield "流式回答 [1]。"
    llm.stream_chat = fake_stream

    with TestClient(app) as client:
        show("health", client.get("/api/health"))
        show("me anonymous", client.get("/api/auth/me"))
        login = show("dev login", client.post("/api/auth/dev-login", json={"nickname": "冒烟同学"}))
        csrf = login.json()["csrf"]
        h = {"X-CSRF-Token": csrf}
        show("me auth", client.get("/api/auth/me"))
        show("meta", client.get("/api/meta"))
        show("dashboard", client.get("/api/dashboard"))
        show("sources", client.get("/api/sources"))
        show("profile patch", client.patch("/api/profile", json={"major": "计算机科学与技术", "grade": "大三", "directions": ["人工智能"], "courses": ["机器学习"]}, headers=h))
        show("profile stats", client.get("/api/profile/stats"))

        plan = show("plan create", client.post("/api/plans", json={"title": "每天背 20 个六级单词", "category": "vocab", "target_count": 20, "unit": "个", "reminder_time": "21:00"}, headers=h))
        pid = plan.json()["id"]
        show("plan progress", client.post(f"/api/plans/{pid}/progress", json={"delta": 1}, headers=h))
        show("vocab overview", client.get(f"/api/plans/{pid}/vocab/overview"))
        vocab = show("vocab start", client.post(f"/api/plans/{pid}/vocab/start", json={"size": 5, "mode": "mixed"}, headers=h))
        items = vocab.json()["items"]
        results = [{"word": item["word"], "known": i % 2 == 0, "meaning": item["meaning"], "example": item["example"]} for i, item in enumerate(items)]
        show("vocab grade", client.post(f"/api/plans/{pid}/vocab/grade", json={"session_id": vocab.json()["session_id"], "results": results}, headers=h))
        show("plan coach", client.post(f"/api/plans/{pid}/coach", json={}, headers=h))

        due = iso(now_utc())
        rem = show("reminder create", client.post("/api/reminders", json={"title": "提交作业", "due_at": due, "recurrence": "once", "channels": ["inapp"]}, headers=h))
        fired = scheduler.fire_reminders()
        print(f"OK  fired reminders: {fired}")
        show("reminders list", client.get("/api/reminders"))
        show("notifications", client.get("/api/notifications"))
        show("complete reminder", client.post(f"/api/reminders/{rem.json()['id']}/complete", headers=h))

        post = show("forum post", client.post("/api/forum/posts", json={"title": "机器学习期末怎么复习", "body": "求一份复习路线，谢谢大家。", "tags": ["学习交流"], "anonymous": False}, headers=h))
        post_id = post.json()["post"]["id"]
        anon = show("forum anon post", client.post("/api/forum/posts", json={"title": "匿名问一个选课问题", "body": "这门课给分怎么样？", "tags": ["经验分享"], "anonymous": True}, headers=h))
        show("forum list", client.get("/api/forum/posts"))
        show("forum detail", client.get(f"/api/forum/posts/{post_id}"))
        show("forum comment", client.post(f"/api/forum/posts/{post_id}/comments", json={"body": "建议先过一遍课后题。", "anonymous": False}, headers=h))
        show("forum like", client.post(f"/api/forum/posts/{post_id}/like", headers=h))
        show("forum bookmark", client.post(f"/api/forum/posts/{post_id}/bookmark", headers=h))
        show("forum report", client.post("/api/forum/reports", json={"target_type": "post", "target_id": anon.json()["post"]["id"], "reason": "其他", "detail": "测试举报"}, headers=h))
        show("message send", client.post("/api/messages", json={"to": 999, "body": "hi"}, headers=h))
        show("messages conversations", client.get("/api/messages/conversations"))
        show("notifications read", client.post("/api/notifications/read", json={"all": True}, headers=h))

        with db() as conn:
            conn.execute("UPDATE users SET role = 'admin' WHERE id = 1")
        show("admin overview", client.get("/api/admin/overview"))
        show("admin queue", client.get("/api/admin/moderation"))
        show("admin reports", client.get("/api/admin/reports"))
        show("admin users", client.get("/api/admin/users"))
        show("admin audit", client.get("/api/admin/audit"))

        with db() as conn:
            doc_id = conn.execute(
                "INSERT INTO documents (site_id, url, title, published_at, fetched_at, content_type, sha256, text, char_count) "
                "VALUES (1, 'https://www.ecnu.edu.cn/test-notice.html', '关于期末考试安排的通知', '2026-06-01', ?, 'html', 'x', ?, 120)",
                (iso(now_utc()), "期末考试安排在第十八周进行，缓考需要提前向教务处提交申请，并附相关证明材料。" * 3),
            ).lastrowid
            conn.execute(
                "INSERT INTO chunks (document_id, ordinal, text) VALUES (?, 0, ?)",
                (doc_id, "期末考试安排在第十八周进行，缓考需要提前向教务处提交申请，并附相关证明材料。" * 3),
            )
        bump_index_version()
        show("chat official", client.post("/api/chat/official", json={"question": "缓考怎么申请？"}, headers={**h, "X-LLM-Key": "sk-test-1234567890", "X-LLM-Model": "test-model"}, ))
        with client.stream("POST", "/api/chat/official/stream", json={"question": "期末考试什么时候？"}, headers={**h, "X-LLM-Key": "sk-test-1234567890", "X-LLM-Model": "test-model"}) as stream:
            body = "".join(stream.iter_text())
            print("OK  chat stream", stream.status_code, body[:200].replace("\n", " "))
        show("sources documents", client.get("/api/sources/1/documents"))
        show("delete account", client.delete("/api/profile?confirm=DELETE"))
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(DATA, ignore_errors=True)
    raise SystemExit(code)
