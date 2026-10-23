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
        shots = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".ui-shots")
        os.makedirs(shots, exist_ok=True)
        page.screenshot(path=os.path.join(shots, "flows-chat-history.png"))

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
        page.screenshot(path=os.path.join(shots, "flows-plans.png"))

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
            original_age = age.get("value")
            page.select_option("#ageSelect", "365")
            page.wait_for_timeout(1800)
            value = page.evaluate("() => document.querySelector('#ageSelect')?.value")
            failures += 0 if check("切换收录范围会保存", value == "365", f'现在 {value}') else 1
            # 检查完复原，避免把真实数据窗口改成一年
            if original_age and str(original_age) != "365":
                page.select_option("#ageSelect", str(original_age))
                page.wait_for_timeout(1200)

        # ------------------------------------------------------- 官网目录加载
        page.evaluate("() => { location.hash = '#/tasks' }")
        page.wait_for_timeout(300)
        page.evaluate("() => { location.hash = '#/sources' }")
        loaded = False
        for _ in range(24):
            page.wait_for_timeout(500)
            text = page.evaluate("() => document.querySelector('#view')?.innerText || ''")
            if "收录范围" in text and "正在读取官网目录" not in text:
                loaded = True
                break
        failures += 0 if check("官网文件页能在 12 秒内加载完成", loaded) else 1

        # ------------------------------------------------------- 学习资料直链
        page.evaluate("() => { location.hash = '#/study' }")
        page.wait_for_timeout(4000)
        study = page.evaluate(
            """() => ({
              hasLiveBox: Boolean(document.querySelector('#studyLive')),
              liveLinks: document.querySelectorAll('#studyLive .live-item').length,
              listItems: document.querySelectorAll('#studyList .resource-card').length,
              error: (document.querySelector('#studyList')?.innerText || '').includes('暂时不可用')
            })"""
        )
        failures += 0 if check(
            "学习资料页正常渲染（含可直接点开的条目）",
            study["hasLiveBox"] and not study["error"] and (study["liveLinks"] > 0 or study["listItems"] > 0),
            f'直链 {study["liveLinks"]} 条 / 检索卡片 {study["listItems"]} 张',
        ) else 1

        # ------------------------------------------------------- 热点自定义话题
        page.evaluate("() => { location.hash = '#/news' }")
        page.wait_for_timeout(1200)
        news = page.evaluate(
            """() => ({
              topics: Boolean(document.querySelector('#newsTopics')),
              categories: document.querySelectorAll('#newsTabs .tab').length
            })"""
        )
        failures += 0 if check(
            "热点页有自定义话题入口", news["topics"] and news["categories"] >= 5,
        ) else 1

        # ------------------------------------------------------- 论坛版面与筛选
        page.evaluate("() => { location.hash = '#/forum' }")
        page.wait_for_timeout(1800)
        forum = page.evaluate(
            """() => ({
              boards: document.querySelectorAll('#forumBoards .chip').length,
              ranges: document.querySelectorAll('#forumRange button').length
            })"""
        )
        failures += 0 if check(
            "论坛有版面与时间筛选", forum["boards"] >= 5 and forum["ranges"] == 4,
            f'版面 {forum["boards"]} 个 / 时间 {forum["ranges"]} 档',
        ) else 1
        page.click("#forumRange [data-range='day']")
        page.wait_for_timeout(1200)
        page.click("#forumBoards [data-board='study']")
        page.wait_for_timeout(1200)
        active = page.evaluate("() => Boolean(document.querySelector('#forumBoards .chip.active'))")
        failures += 0 if check("切换版面与时间后列表仍可用", active) else 1

        # ------------------------------------------------------- 论坛首页模块
        seeded_posts = page.evaluate(
            """async () => {
              const me = await fetch('/api/auth/me', { credentials: 'same-origin' }).then((r) => r.json());
              const headers = { 'Content-Type': 'application/json', 'X-CSRF-Token': me.csrf };
              const listing = await fetch('/api/forum/posts?size=20', { credentials: 'same-origin' }).then((r) => r.json());
              const need = Math.max(0, 6 - (listing.total || 0));
              const ids = [];
              for (let i = 1; i <= need; i += 1) {
                const response = await fetch('/api/forum/posts', {
                  method: 'POST', credentials: 'same-origin', headers,
                  body: JSON.stringify({
                    title: '流程检查·第 ' + i + ' 条经验分享',
                    body: '这是一条用于检查论坛首页模块的示例帖子，包含保研与选课的经验。',
                    tags: ['经验分享'], board: 'exam'
                  })
                });
                if (!response.ok) return { ok: false, status: response.status, ids, existing: listing.total };
                ids.push((await response.json()).post.id);
              }
              return { ok: true, ids, existing: listing.total, need };
            }"""
        )
        failures += 0 if check(
            "论坛首页示例数据就绪", bool(seeded_posts.get("ok")),
            f'已有 {seeded_posts.get("existing")} 条，新建 {len(seeded_posts.get("ids") or [])} 条',
        ) else 1
        page.evaluate("() => { location.hash = '#/tasks' }")
        page.wait_for_timeout(400)
        page.evaluate("() => { location.hash = '#/forum' }")
        page.wait_for_timeout(1800)
        home = page.evaluate(
            """() => ({
              announcement: Boolean(document.querySelector('.forum-announce-text')),
              slides: document.querySelectorAll('#forumCarousel .carousel-slide').length,
              dots: document.querySelectorAll('#forumCarousel .carousel-dot').length,
              recommended: document.querySelectorAll('.reco-row').length
            })"""
        )
        failures += 0 if check("论坛首页显示全站公告", home["announcement"]) else 1
        failures += 0 if check(
            "论坛首页有轮播且切换点与条目一致",
            home["slides"] >= 3 and home["dots"] == home["slides"],
            f'{home["slides"]} 条 / {home["dots"]} 个点',
        ) else 1
        failures += 0 if check(
            "论坛首页有推荐阅读", home["recommended"] >= 1, f'{home["recommended"]} 条',
        ) else 1
        switched = page.evaluate(
            """() => {
              const dots = document.querySelectorAll('#forumCarousel .carousel-dot');
              if (dots.length < 2) return false;
              dots[1].click();
              return document.querySelectorAll('#forumCarousel .carousel-slide')[1]?.classList.contains('active') === true;
            }"""
        )
        failures += 0 if check("轮播可以手动切换", switched) else 1
        page.wait_for_timeout(700)  # 等切换动画结束再截图
        page.screenshot(path=os.path.join(shots, "flows-forum-home.png"))
        page.evaluate(
            """async (ids) => {
              const me = await fetch('/api/auth/me', { credentials: 'same-origin' }).then((r) => r.json());
              const headers = { 'X-CSRF-Token': me.csrf };
              for (const id of ids) {
                await fetch('/api/forum/posts/' + id, { method: 'DELETE', credentials: 'same-origin', headers });
              }
              return true;
            }""",
            seeded_posts.get("ids") or [],
        )

        # ------------------------------------------------------- 计划词库选择
        page.evaluate("() => { location.hash = '#/plans' }")
        page.wait_for_timeout(1200)
        page.click("#newPlanBtn")
        page.wait_for_timeout(400)
        vocab = page.evaluate(
            """() => {
              const category = document.querySelector('#planCategory');
              category.value = 'vocab';
              category.dispatchEvent(new Event('change'));
              const field = document.querySelector('#wordLevelField');
              const select = document.querySelector('#planWordLevel');
              return { visible: field && field.style.display !== 'none', options: select ? select.options.length : 0 };
            }"""
        )
        failures += 0 if check(
            "词汇计划可选四级 / 六级词库", vocab["visible"] and vocab["options"] == 2,
        ) else 1
        page.keyboard.press("Escape")

        # --------------------------------------------------- 切换页面不中断输出
        page.route(
            "**/api/chat/official/stream",
            lambda route: route.fulfill(
                status=200,
                headers={"Content-Type": "text/event-stream", "Cache-Control": "no-store"},
                body=(
                    'data: {"type": "sources", "sources": []}\n\n'
                    'data: {"type": "delta", "text": "这是跨页面继续输出的回答。"}\n\n'
                    'data: {"type": "done", "answer": "这是跨页面继续输出的回答。", "sources": [], "insufficient": false}\n\n'
                ),
            ),
        )
        page.evaluate(
            """async () => {
              const mod = await import('/static/js/store.js');
              mod.saveLLM({ key: 'sk-test-0000000000', model: 'mock-model', base_url: 'http://127.0.0.1:1/v1', provider: '' });
            }"""
        )
        page.evaluate("() => { location.hash = '#/ask' }")
        page.wait_for_timeout(1200)
        page.fill("#chatInput", "测试跨页面输出")
        page.keyboard.press("Enter")
        page.wait_for_timeout(1500)
        page.evaluate("() => { location.hash = '#/tasks' }")
        page.wait_for_timeout(500)
        page.evaluate("() => { location.hash = '#/ask' }")
        page.wait_for_timeout(1500)
        kept = page.evaluate("() => (document.querySelector('#chatLog')?.innerText || '').includes('跨页面继续输出')")
        failures += 0 if check("切到别的页面再回来，回答仍在", kept) else 1

        failures += 0 if check("页面无 JS 异常", not errors, "; ".join(errors[:3])) else 1
        browser.close()

    print("\nRESULT:", "OK" if not failures else f"{failures} FAILED")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
