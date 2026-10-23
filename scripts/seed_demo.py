"""生成演示数据（开发/截图用）。运行前先启动本地服务并完成一次演示登录：

    $env:ECNU_DATA_DIR="..."; python scripts/seed_demo.py
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.db import bump_index_version, db, init_db  # noqa: E402
from app.services.crawler import CrawlManager  # noqa: E402
from app.timeutil import iso, local_day, now_utc  # noqa: E402


def upsert_user(conn, nickname, major, grade, avatar, bio, directions):
    row = conn.execute("SELECT id FROM users WHERE nickname = ?", (nickname,)).fetchone()
    if row:
        return int(row["id"])
    cursor = conn.execute(
        "INSERT INTO users (sso_subject, sso_provider, nickname, avatar, bio, major, grade, "
        "directions, courses, settings, created_at) VALUES (?, 'demo', ?, ?, ?, ?, ?, ?, '[]', '{}', ?)",
        (
            f"demo:{nickname}",
            nickname,
            avatar,
            bio,
            major,
            grade,
            json.dumps(directions, ensure_ascii=False),
            iso(now_utc() - timedelta(days=120)),
        ),
    )
    return int(cursor.lastrowid)


def post(conn, author_id, title, body, tags, anonymous=False, status="visible", moderation=None, hours_ago=3):
    row = conn.execute("SELECT id FROM posts WHERE title = ?", (title,)).fetchone()
    if row:
        return int(row["id"])
    created = iso(now_utc() - timedelta(hours=hours_ago))
    cursor = conn.execute(
        "INSERT INTO posts (author_id, title, body, tags, anonymous, status, moderation, views, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            author_id,
            title,
            body,
            json.dumps(tags, ensure_ascii=False),
            1 if anonymous else 0,
            status,
            json.dumps(moderation or {"risk": 0, "action": "ok", "categories": []}, ensure_ascii=False),
            hours_ago * 7 + 12,
            created,
            created,
        ),
    )
    return int(cursor.lastrowid)


def comment(conn, post_id, author_id, body, hours_ago=2, anonymous=False):
    exists = conn.execute(
        "SELECT id FROM comments WHERE post_id = ? AND body = ?", (post_id, body)
    ).fetchone()
    if exists:
        return
    conn.execute(
        "INSERT INTO comments (post_id, author_id, body, anonymous, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'visible', ?, ?)",
        (
            post_id,
            author_id,
            body,
            1 if anonymous else 0,
            iso(now_utc() - timedelta(hours=hours_ago)),
            iso(now_utc() - timedelta(hours=hours_ago)),
        ),
    )


def main() -> int:
    init_db()
    with db() as conn:
        main_user = conn.execute(
            "SELECT * FROM users WHERE last_login_at IS NOT NULL ORDER BY last_login_at DESC, id DESC LIMIT 1"
        ).fetchone()
        if not main_user:
            print("请先在浏览器中完成一次演示登录，再运行本脚本。")
            return 1
        main_id = int(main_user["id"])
        conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (main_id,))

        shen = upsert_user(conn, "沈知行", "计算机科学与技术", "大三", "preset:night", "在做 RAG，偶尔跑步。", ["人工智能", "数据可视化"])
        chen = upsert_user(conn, "陈栖迟", "汉语言文学", "大二", "preset:forest", "读书、拍照、找好吃的。", ["现代文学", "写作"])
        zhou = upsert_user(conn, "周予安", "心理学", "研一", "preset:sunset", "研究情绪与睡眠。", ["认知心理学", "睡眠"])

        p1 = post(
            conn, shen, "机器学习期末复习路线（附往年题范围）",
            "把这学期的课件过了一遍，整理了一个复习顺序：\n\n1. 线性回归 / 逻辑回归：推导 + 损失函数\n2. 决策树与集成：信息增益、bagging 和 boosting 的区别\n3. 神经网络：反向传播手推一遍\n4. 无监督：k-means、PCA\n5. 往年题：重点看证明题和调参题\n\n需要笔记的同学可以在评论区说一声，我整理成 PDF。",
            ["学习交流"], hours_ago=5,
        )
        p2 = post(
            conn, chen, "樱桃河边新开的面包店有人去过吗？",
            "傍晚路过看到排队，好像主打碱水和可颂。价格在 10-20 元之间，有去过的同学说说味道吗？",
            ["生活分享"], hours_ago=8,
        )
        p3 = post(
            conn, zhou, "在图书馆三楼捡到一张校园卡",
            "卡面姓氏是「李」，今天下午在靠窗的座位捡到的。已经交到一楼服务台，失主可以去认领。",
            ["寻物启事"], hours_ago=10,
        )
        post(
            conn, shen, "保研夏令营一般什么时候开始准备？",
            "目前大二，想提前了解一下夏令营的时间线和需要准备的材料。绩点、科研、英语哪个权重更高？",
            ["经验分享"], anonymous=True, hours_ago=12,
        )
        post(
            conn, chen, "低价代购 + 微信 xxx 领取优惠",
            "低价代购各种商品，加微信领取内部优惠，日入过千，扫码进群。",
            ["生活分享"], status="pending",
            moderation={"risk": 60, "action": "review", "categories": ["诈骗广告", "广告垃圾"]},
            hours_ago=1,
        )

        comment(conn, p1, chen, "求 PDF！往年题是在哪里找的？", hours_ago=2)
        comment(conn, p1, zhou, "反向传播那部分建议配合 3Blue1Brown 的视频看，直观很多。", hours_ago=1)
        comment(conn, p2, shen, "可颂不错，碱水偏咸，建议下午去不用排队。", hours_ago=2)
        comment(conn, p3, main_id, "谢谢！我转给住三楼的室友。", hours_ago=1)

        conn.execute(
            "INSERT OR IGNORE INTO post_likes (post_id, user_id, created_at) VALUES (?, ?, ?)",
            (p1, chen, iso(now_utc())),
        )
        conn.execute(
            "INSERT OR IGNORE INTO post_likes (post_id, user_id, created_at) VALUES (?, ?, ?)",
            (p1, zhou, iso(now_utc())),
        )
        conn.execute(
            "INSERT OR IGNORE INTO follows (follower_id, followee_id, created_at) VALUES (?, ?, ?)",
            (chen, shen, iso(now_utc())),
        )
        conn.execute(
            "INSERT OR IGNORE INTO follows (follower_id, followee_id, created_at) VALUES (?, ?, ?)",
            (zhou, shen, iso(now_utc())),
        )

        conn.execute(
            "INSERT INTO messages (sender_id, recipient_id, body, created_at) VALUES (?, ?, ?, ?)",
            (chen, main_id, "你好，看到你在论坛问保研的事，我去年参加过夏令营，可以聊聊。", iso(now_utc() - timedelta(hours=2))),
        )
        conn.execute(
            "INSERT INTO messages (sender_id, recipient_id, body, created_at) VALUES (?, ?, ?, ?)",
            (main_id, chen, "太好了，谢谢！我想先了解一下时间线。", iso(now_utc() - timedelta(hours=1))),
        )

        conn.execute(
            "INSERT INTO reports (reporter_id, target_type, target_id, reason, detail, created_at) "
            "SELECT ?, 'post', (SELECT id FROM posts WHERE status = 'pending' LIMIT 1), '诈骗广告', '疑似兼职刷单广告', ? "
            "WHERE NOT EXISTS (SELECT 1 FROM reports WHERE target_type = 'post' AND target_id = (SELECT id FROM posts WHERE status = 'pending' LIMIT 1))",
            (chen, iso(now_utc() - timedelta(minutes=30))),
        )

        # 计划
        day = local_day()
        plans = [
            ("每天背 20 个六级单词", "vocab", "daily", "[]", 20, "个", "21:00", "先复习到期词，再学新词。", 12),
            ("每天阅读 30 分钟", "reading", "daily", "[]", 30, "分钟", "22:30", "读《人类简史》", 30),
            ("每周跑步三次", "exercise", "weekly", "[1,3,5]", 30, "分钟", "07:30", "东操场，慢跑即可。", 0),
        ]
        for title, category, cadence, weekdays, target, unit, reminder, note, done in plans:
            exists = conn.execute("SELECT id FROM plans WHERE user_id = ? AND title = ?", (main_id, title)).fetchone()
            if exists:
                plan_id = int(exists["id"])
            else:
                cursor = conn.execute(
                    "INSERT INTO plans (user_id, title, category, cadence, weekdays, target_count, unit, "
                    "reminder_time, note, active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
                    (main_id, title, category, cadence, weekdays, target, unit, reminder, note, iso(now_utc() - timedelta(days=20))),
                )
                plan_id = int(cursor.lastrowid)
            completed = 1 if done >= target else 0
            conn.execute(
                "INSERT INTO plan_progress (plan_id, day, done_count, completed, updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(plan_id, day) DO UPDATE SET done_count = excluded.done_count, completed = excluded.completed",
                (plan_id, day, done, completed, iso(now_utc())),
            )
            # 过去 6 天的打卡记录
            for offset in range(1, 7):
                past = (datetime.fromisoformat(day) - timedelta(days=offset)).date().isoformat()
                if (offset + len(title)) % 3 == 0:
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO plan_progress (plan_id, day, done_count, completed, updated_at) "
                    "VALUES (?, ?, ?, 1, ?)",
                    (plan_id, past, target, iso(now_utc())),
                )

        # 待办提醒
        base = datetime.now(UTC)
        reminders = [
            ("提交课程论文", "记得在教务系统上传 PDF，文件名写学号。", base + timedelta(hours=4), "once"),
            ("预约图书馆研讨间", "周五小组讨论，需要 4 人空间。", base + timedelta(hours=20), "once"),
            ("查看本周教务通知", "周一早上看一眼教务处通知。", base + timedelta(days=3), "weekly"),
        ]
        for title, notes, due, recurrence in reminders:
            exists = conn.execute("SELECT id FROM reminders WHERE user_id = ? AND title = ?", (main_id, title)).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO reminders (user_id, title, notes, due_at, recurrence, channels, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (main_id, title, notes, iso(due), recurrence, '["inapp","browser"]', iso(now_utc())),
                )

        # 今日热点/论文/学习资料的缓存由页面实时获取，无需预置
        # 通知
        for kind, text in [
            ("comment", "陈栖迟 评论了你的帖子《机器学习期末复习路线》"),
            ("follow", "周予安 关注了你"),
            ("message", "陈栖迟 给你发来一条私信"),
        ]:
            conn.execute(
                "INSERT INTO notifications (user_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
                (main_id, kind, json.dumps({"text": text, "link": "#/forum"}, ensure_ascii=False), iso(now_utc() - timedelta(hours=2))),
            )

        # 词汇复习数据
        words = [
            ("abandon", "v. 放弃；抛弃", "They had to abandon the project."),
            ("coherent", "adj. 连贯的；有条理的", "A good essay needs a coherent structure."),
            ("diminish", "v. 减少；削弱", "Interest did not diminish over time."),
            ("empirical", "adj. 经验的；实证的", "The claim needs empirical evidence."),
            ("feasible", "adj. 可行的", "The plan is feasible within one semester."),
            ("hypothesis", "n. 假设；假说", "The experiment tested a simple hypothesis."),
            ("intrinsic", "adj. 内在的；固有的", "Curiosity is an intrinsic motivation."),
            ("plausible", "adj. 看似合理的", "The explanation sounds plausible."),
        ]
        for word, meaning, example in words:
            conn.execute(
                "INSERT INTO vocab_reviews (user_id, word, meaning, example, ease, interval_days, due_at, lapses, updated_at) "
                "VALUES (?, ?, ?, ?, 2.5, 3, ?, 0, ?) ON CONFLICT(user_id, word) DO NOTHING",
                (main_id, word, meaning, example, iso(now_utc() - timedelta(hours=1)), iso(now_utc())),
            )

    # 采集几页公开官网内容
    with db() as conn:
        site = conn.execute("SELECT * FROM sites WHERE key = 'www.ecnu.edu.cn'").fetchone()
    if site:
        manager = CrawlManager()
        settings.crawl_max_pages_per_site = 6
        settings.crawl_max_depth = 1
        settings.crawl_delay_seconds = 0.4
        ok, failed, errors = manager._crawl_site(dict(site))
        print(f"crawl: ok={ok} failed={failed} errors={errors[:2]}")
    with db() as conn:
        conn.execute(
            "UPDATE sites SET doc_count = (SELECT COUNT(*) FROM documents WHERE site_id = sites.id)"
        )
        conn.execute(
            "INSERT INTO crawl_runs (site_ids, status, started_at, finished_at, pages_ok, pages_failed, detail) "
            "SELECT '[1]', 'finished', ?, ?, ?, 0, '{}' WHERE NOT EXISTS (SELECT 1 FROM crawl_runs)",
            (iso(now_utc() - timedelta(minutes=10)), iso(now_utc() - timedelta(minutes=9)), 6),
        )
    bump_index_version()
    print(f"demo data ready for user {main_id}; data dir={settings.data_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
