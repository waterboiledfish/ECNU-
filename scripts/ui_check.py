"""端到端 UI 检查（开发用）：启动本地服务后运行。需要 playwright + 系统 Edge。

python scripts/ui_check.py
截图输出到 .ui-shots/
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = Path(__file__).resolve().parent.parent / ".ui-shots"
ROUTES = [
    ("ask", "#/ask"),
    ("tasks", "#/tasks"),
    ("plans", "#/plans"),
    ("news", "#/news"),
    ("papers", "#/papers"),
    ("study", "#/study"),
    ("sources", "#/sources"),
    ("forum", "#/forum"),
    ("forum-new", "#/forum/new"),
    ("messages", "#/messages"),
    ("notifications", "#/notifications"),
    ("me", "#/me"),
    ("admin", "#/admin"),
]


def main() -> int:
    OUT.mkdir(exist_ok=True)
    errors: list[str] = []
    console_errors: list[str] = []
    with sync_playwright() as playwright:
        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(OUT.parent / ".ui-profile"),
                channel="msedge",
                headless=True,
                viewport={"width": 1440, "height": 900},
                locale="zh-CN",
                color_scheme="light",
            )
        except Exception as exc:
            print("launch msedge failed:", exc)
            return 1
        page = context.pages[0] if context.pages else context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: console_errors.append(f"{message.type}: {message.text}")
            if message.type == "error"
            else None,
        )

        for _ in range(30):
            try:
                response = page.goto(BASE, wait_until="domcontentloaded", timeout=5000)
                if response and response.ok:
                    break
            except Exception:
                time.sleep(0.5)
        else:
            print("server not reachable")
            return 1

        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT / "01-login.png"), full_page=False)
        print("login page:", page.title())

        if page.query_selector("#devLoginForm"):
            page.fill("#devNickname", "林小满")
            page.click("#devLoginBtn")
            page.wait_for_timeout(2200)
        page.screenshot(path=str(OUT / "02-dashboard-empty.png"), full_page=False)
        print("after login:", page.title(), page.evaluate("document.querySelector('#pageTitle')?.textContent"))

        for name, route in ROUTES:
            page.evaluate("(hash) => { location.hash = hash }", route)
            page.wait_for_timeout(1100)
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            page.screenshot(path=str(OUT / f"{name}.png"), full_page=False)
            title = page.evaluate("document.querySelector('#pageTitle')?.textContent")
            snippet = page.evaluate("document.querySelector('#view')?.innerText?.slice(0, 80)")
            print(f"{name:12s} {title!r} {snippet!r}")

        mobile = context.new_page()
        mobile.set_viewport_size({"width": 390, "height": 844})
        mobile.goto(BASE + "/#/", wait_until="networkidle")
        mobile.wait_for_timeout(1200)
        mobile.screenshot(path=str(OUT / "mobile-dashboard.png"), full_page=False)
        mobile.goto(BASE + "/#/forum", wait_until="networkidle")
        mobile.wait_for_timeout(1000)
        mobile.screenshot(path=str(OUT / "mobile-forum.png"), full_page=False)

        context.close()

    print("\nPAGE ERRORS:", len(errors))
    for error in errors[:20]:
        print(" -", error[:300])
    print("CONSOLE ERRORS:", len(console_errors))
    for error in console_errors[:20]:
        print(" -", error[:300])
    return 0


if __name__ == "__main__":
    sys.exit(main())
