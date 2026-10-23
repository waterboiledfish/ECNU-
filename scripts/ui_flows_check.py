"""关键交互流程的浏览器检查（开发用）：对话历史、计划表单、院系/专业、收录范围。

需要 playwright + 系统 Edge，并先启动服务：
    ECNU_UI_BASE=http://127.0.0.1:8799 python scripts/ui_flows_check.py
"""
from __future__ import annotations

import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get("ECNU_UI_BASE", "http://127.0.0.1:8765")


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {label}{(' · ' + detail) if detail else ''}")
    return ok


def main() -> int:
    failures = 0
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
        except Exception as exc:
            print("launch msedge failed:", exc)
            return 1
        page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="zh-CN")
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        for _ in range(40):
            try:
                if page.goto(BASE, wait_until="domcontentloaded", timeout=5000).ok:
                    break
            except Exception:
                time.sleep(0.5)
        else:
            print("server not reachable:", BASE)
            return 1
        page.wait_for_timeout(600)
        if page.query_selector("#devLoginForm"):
            page.fill("#devNickname", "流程检查")
            page.click("#devLoginBtn")
            page.wait_for_timeout(1800)

        # ---------------------------------------------------------- 对话历史
        page.evaluate("() => { location.hash = '#/ask' }")
        page.wait_for_timeout(1200)
        seeded = page.evaluate(
            """async () => {
              const me = await fetch('/api/auth/me', { credentials: 'same-origin' }).then((r) => r.json());
              const headers = { 'Content-Type': 'application/json', 'X-CSRF-Token': me.csrf };
              const create = await fetch('/api/chat/threads', {
                method: 'POST', credentials: 'same-origin', headers,
                body: JSON.stringify({ mode: 'official' })
              });
              if (!create.ok) return { ok: false, status: create.status };
              const thread = await create.json();
              const save = await fetch('/api/chat/threads/' + thread.id, {
                method: 'PUT', credentials: 'same-origin', headers,
                body: JSON.stringify({ messages: [
                  { role: 'user', content: '缓考申请需要哪些材料？' },
                  { role: 'assistant', content: '需要申请表、成绩单与任课教师签字。' }
                ] })
              });
              return { ok: save.ok, id: thread.id, status: save.status };
            }"""
        )
        failures += 0 if check("对话可以通过接口保存", bool(seeded.get("ok")), str(seeded)) else 1

        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        page.evaluate("() => { location.hash = '#/ask' }")
        page.wait_for_timeout(1500)
        history = page.evaluate(
            """() => {
              const items = document.querySelectorAll('#threadCard .thread-item');
              const titles = Array.from(items).map((node) => node.innerText.trim().slice(0, 40));
              const bubbles = document.querySelectorAll('#chatLog .msg').length;
              return { count: items.length, titles, bubbles };
            }"""
        )
        failures += 0 if check(
            "对话历史列表会出现已保存的会话", history["count"] >= 1, str(history["titles"][:2]),
        ) else 1
        failures += 0 if check(
            "打开页面会自动载入最近一次对话", history["bubbles"] >= 2, f'{history["bubbles"]} 条消息',
        ) else 1

        # ---------------------------------------------------------- 计划表单
        page.evaluate("() => { location.hash = '#/plans' }")
        page.wait_for_timeout(1400)
        page_text = page.evaluate("() => document.querySelector('#view')?.innerText || ''")
        failures += 0 if check("计划页不再显示「词汇复习」统计", "词汇复习" not in page_text) else 1

        page.click("#newPlanBtn")
        page.wait_for_timeout(500)
        form = page.evaluate(
            """() => {
              const label = document.querySelector('#categoryLabelField');
              const targets = document.querySelector('#targetFields');
              const useTarget = document.querySelector('#planUseTarget');
              const category = document.querySelector('#planCategory');
              category.value = 'reading';
              category.dispatchEvent(new Event('change'));
              const hiddenOnReading = label.style.display === 'none';
              category.value = 'custom';
              category.dispatchEvent(new Event('change'));
              const shownOnCustom = label.style.display !== 'none';
              return {
                hasLabel: Boolean(label), hasTargetToggle: Boolean(useTarget),
                targetHiddenByDefault: targets.style.display === 'none',
                hiddenOnReading, shownOnCustom
              };
            }"""
        )
        failures += 0 if check(
            "计划表单支持自定义类型名称并随类别显隐",
            form["hasLabel"] and form["hiddenOnReading"] and form["shownOnCustom"],
        ) else 1
        failures += 0 if check(
            "目标数量默认折叠（可不设数量目标）",
            form["hasTargetToggle"] and form["targetHiddenByDefault"],
        ) else 1

        page.fill("#planTitle", "流程检查·练吉他")
        page.fill("#planNote", "每天练 30 分钟音阶")
        page.fill("#planCategoryLabel", "吉他练习")
        page.click("#savePlanBtn")
        page.wait_for_timeout(1600)
        cards = page.evaluate(
            """() => Array.from(document.querySelectorAll('.plan-card')).map((card) => card.innerText)
            """
        )
        failures += 0 if check(
            "无数量目标的计划能创建并显示自定义类型",
            any("吉他练习" in text and "不设数量目标" in text for text in cards),
            str([text.split("\n")[:2] for text in cards][:1]),
        ) else 1

        # ------------------------------------------------------- 个人设置
        page.evaluate("() => { location.hash = '#/me' }")
        page.wait_for_timeout(1600)
        profile = page.evaluate(
            """() => {
              const dept = document.querySelector('#profDepartment');
              const major = document.querySelector('#profMajor');
              const custom = document.querySelector('#profMajorCustom');
              const before = major.options.length;
              dept.value = '计算机科学与技术学院';
              dept.dispatchEvent(new Event('change'));
              const after = major.options.length;
              major.value = '__custom__';
              major.dispatchEvent(new Event('change'));
              const customVisible = !custom.hidden;
              return { before, after, customVisible, options: Array.from(major.options).map((o) => o.value) };
            }"""
        )
        failures += 0 if check(
            "院系切换后专业下拉跟随刷新",
            profile["after"] >= 2 and profile["after"] != profile["before"],
            f'{profile["before"]} → {profile["after"]} 项',
        ) else 1
        failures += 0 if check(
            "选「其他」时可以手动填写专业", profile["customVisible"],
        ) else 1

        page.fill("#coursesEditor input", "高等数学")
        page.keyboard.press("Enter")
        page.wait_for_timeout(200)
        page.fill("#coursesEditor input", "线性代数，概率论")
        page.keyboard.press("Enter")
        page.wait_for_timeout(300)
        tag_count = page.evaluate("() => document.querySelectorAll('#coursesEditor [data-value]').length")
        failures += 0 if check(
            "课程标签支持回车与一次添加多个", tag_count >= 3, f"{tag_count} 个标签",
        ) else 1
        page.evaluate("() => document.querySelector('#coursesEditor input')?.blur()")
        page.wait_for_timeout(200)

        # ------------------------------------------------------- 收录范围
        page.evaluate("() => { location.hash = '#/sources' }")
        page.wait_for_timeout(1600)
        age = page.evaluate(
            """() => {
              const select = document.querySelector('#ageSelect');
              return select ? { exists: true, value: select.value, options: select.options.length } : { exists: false };
            }"""
        )
        failures += 0 if check(
            "官网文件页有「收录范围」选择", age["exists"] and age["options"] >= 4,
            f'当前 {age.get("value")} 天',
        ) else 1
        if age["exists"]:
            page.select_option("#ageSelect", "365")
            page.wait_for_timeout(1800)
            value = page.evaluate("() => document.querySelector('#ageSelect')?.value")
            failures += 0 if check("切换收录范围会保存", value == "365", f'现在 {value}') else 1

        failures += 0 if check("页面无 JS 异常", not errors, "; ".join(errors[:3])) else 1
        browser.close()

    print("\nRESULT:", "OK" if not failures else f"{failures} FAILED")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
