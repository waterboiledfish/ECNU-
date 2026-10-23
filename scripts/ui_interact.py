"""交互式前端检查：在已登录的持久化浏览器配置上操作主要功能。

先运行 scripts/ui_check.py 创建登录状态，再运行本脚本。截图输出到 .ui-shots/。
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = Path(__file__).resolve().parent.parent / ".ui-shots"


def main() -> int:
    OUT.mkdir(exist_ok=True)
    errors: list[str] = []
    console_errors: list[str] = []
    results: list[tuple[str, bool, str]] = []

    def check(name: str, fn):
        try:
            value = fn()
            results.append((name, True, str(value or "")[:120]))
            print(f"OK   {name}: {value}")
        except Exception as exc:
            results.append((name, False, str(exc)[:200]))
            print(f"FAIL {name}: {exc}")

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(OUT.parent / ".ui-profile"),
            channel="msedge",
            headless=True,
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
            color_scheme="light",
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: console_errors.append(f"{message.type}: {message.text}")
            if message.type == "error"
            else None,
        )
        page.goto(BASE, wait_until="domcontentloaded")
        page.wait_for_timeout(800)
        if page.query_selector("#devLoginForm"):
            print("not logged in; run scripts/ui_check.py first")
            return 1

        def go(route: str, wait: int = 900):
            page.evaluate("(hash) => { location.hash = hash }", route)
            page.wait_for_timeout(wait)

        # 1. 今日热点：等待真实 RSS 加载
        def news():
            go("#/news", 300)
            page.wait_for_selector(".news-item", timeout=30000)
            count = page.locator(".news-item").count()
            first = page.locator(".news-item .news-title").first.inner_text()
            page.screenshot(path=str(OUT / "interact-news.png"))
            return f"{count} items; {first[:40]}"

        check("news loads", news)

        # 2. 待办：新建并删除
        def task_flow():
            go("#/tasks")
            page.click("#newTaskBtn")
            page.wait_for_selector(".modal")
            page.fill("#taskTitle", "交互检查：提交实验报告")
            page.fill("#taskDue", "2026-10-25T09:30")
            page.click("#saveTaskBtn")
            page.wait_for_timeout(1200)
            assert "提交实验报告" in page.locator("#view").inner_text()
            item = page.locator(".task-item", has_text="交互检查：提交实验报告").first
            item.locator("[data-action=delete]").click()
            page.wait_for_selector(".modal")
            page.click("[data-ok]")
            page.wait_for_timeout(900)
            assert "交互检查：提交实验报告" not in page.locator("#view").inner_text()
            return "created and deleted"

        check("task create/delete", task_flow)

        # 3. 计划：教练、打卡
        def plan_flow():
            go("#/plans")
            page.locator("[data-action=coach]").first.click()
            page.wait_for_selector(".modal .md, .modal .notice", timeout=15000)
            advice = page.locator(".modal .md").first.inner_text()
            page.locator(".modal [data-close]").first.click()
            page.locator("[data-action=plus]").first.click()
            page.wait_for_timeout(1000)
            return advice[:40]

        check("plan coach & check-in", plan_flow)

        # 4. 单词背诵
        def vocab_flow():
            go("#/plans")
            page.locator("[data-action=vocab]").first.click()
            page.wait_for_selector(".modal")
            page.fill("#vocabSize", "5")
            page.click("#startVocabBtn")
            page.wait_for_selector(".vocab-word", timeout=10000)
            for _ in range(5):
                page.click("#revealBtn")
                page.click("[data-known='1']")
                page.wait_for_timeout(150)
            page.wait_for_selector(".vocab-score .big", timeout=15000)
            score = page.locator(".vocab-score .big").first.inner_text()
            page.screenshot(path=str(OUT / "interact-vocab.png"))
            page.locator(".modal [data-close]").first.click()
            return score

        check("vocab session", vocab_flow)

        # 5. 论坛：点赞 + 评论
        def forum_flow():
            page.goto(BASE + "/#/forum/1", wait_until="domcontentloaded")
            page.wait_for_selector(".post-detail", timeout=15000)
            page.click("#likePost")
            page.wait_for_timeout(600)
            page.locator("#commentBody").fill("交互检查：这条评论来自浏览器自动化。")
            page.click("#submitComment")
            page.wait_for_timeout(1200)
            assert "交互检查" in page.locator("#commentsList").inner_text()
            page.screenshot(path=str(OUT / "interact-forum-detail.png"))
            return "liked and commented"

        check("forum like/comment", forum_flow)

        # 6. 私信
        def message_flow():
            go("#/messages", 1300)
            first = page.locator(".conversation").first
            first.click()
            page.wait_for_selector("#messageInput", timeout=10000)
            page.fill("#messageInput", "交互检查：收到请回复～")
            page.click("#sendMessage")
            page.wait_for_timeout(1200)
            assert "交互检查" in page.locator("#threadLog").inner_text()
            return "sent"

        check("private message", message_flow)

        # 7. 管理后台：审核通过
        def admin_flow():
            go("#/admin", 1200)
            queue = page.locator(".queue-item").first
            queue.locator("[data-action=approve]").click()
            page.wait_for_selector(".modal")
            page.fill("#adminNote", "自动化检查：人工确认")
            page.click("#confirmNote")
            page.wait_for_timeout(1200)
            return "approved"

        check("admin approve", admin_flow)

        # 8. 官网文件：打开文件列表
        def sources_flow():
            go("#/sources", 1200)
            page.locator("[data-docs]:not([disabled])").first.click()
            page.wait_for_selector(".modal .list-item", timeout=10000)
            count = page.locator(".modal .list-item").count()
            page.screenshot(path=str(OUT / "interact-docs.png"))
            page.locator(".modal [data-close]").first.click()
            return f"{count} documents"

        check("sources docs modal", sources_flow)

        # 9. 个人设置：主题切换
        def profile_flow():
            go("#/me", 1200)
            page.click("[data-theme-choice=dark]")
            page.wait_for_timeout(500)
            assert page.evaluate("document.documentElement.dataset.theme") == "dark"
            page.click("#saveProfile")
            page.wait_for_timeout(900)
            page.click("[data-theme-choice=light]")
            page.wait_for_timeout(500)
            assert page.evaluate("document.documentElement.dataset.theme") == "light"
            return "theme toggled"

        check("profile theme", profile_flow)

        context.close()

    print("\nPAGE ERRORS:", len(errors))
    for error in errors[:20]:
        print(" -", error[:300])
    print("CONSOLE ERRORS:", len(console_errors))
    for error in console_errors[:20]:
        print(" -", error[:300])
    failed = [item for item in results if not item[1]]
    return 1 if failed or errors or console_errors else 0


if __name__ == "__main__":
    sys.exit(main())
