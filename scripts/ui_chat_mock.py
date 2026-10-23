"""用本地 mock 模型端到端验证问答、摘要、AI 教练等前端交互。

不需要真实 API Key；会启动一个仅监听 127.0.0.1 的 OpenAI 兼容 mock 服务。
运行前先启动本地应用并完成 scripts/ui_check.py 的登录。
"""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = Path(__file__).resolve().parent.parent / ".ui-shots"


class MockLLM(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: A003
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.send_error(400)
            return
        messages = payload.get("messages", [])
        text = " ".join(str(item.get("content", "")) for item in messages)
        if payload.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            pieces = ["根据已索引的官网资料 [1]，", "期末考试安排在第十八周，", "因病可提前向教务处申请缓考，", "并附医院证明。"]
            for piece in pieces:
                data = json.dumps({"choices": [{"delta": {"content": piece}}]}, ensure_ascii=False)
                self.wfile.write(f"data: {data}\n\n".encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            self.close_connection = True
            return
        if "学习教练" in text:
            content = "**今日建议**\n\n1. 先复习 20 个到期单词。\n2. 晚上 9 点前完成一轮自测。\n3. 睡前用 2 分钟回顾错词。"
        elif "新闻编辑" in text:
            content = "**今日要点**\n\n- 科技领域发布新进展 [1]\n- 教育领域关注人才培养 [2]\n\n值得继续关注产业落地。"
        elif "学习资源策划" in text:
            content = json.dumps(
                [
                    {"platform": "bilibili", "title": "机器学习速成", "query": "机器学习 速成", "reason": "快速建立框架"},
                    {"platform": "zhihu", "title": "数据库怎么复习", "query": "数据库 复习", "reason": "高赞经验"},
                    {"platform": "arxiv", "title": "方向论文", "query": "machine learning", "reason": "前沿论文"},
                ],
                ensure_ascii=False,
            )
        elif "六级词汇" in text:
            content = json.dumps(
                [
                    {"word": "meticulous", "phonetic": "/məˈtɪkjələs/", "meaning": "adj. 一丝不苟的", "example": "She is meticulous about details.", "example_cn": "她对细节一丝不苟。"},
                    {"word": "resilient", "phonetic": "/rɪˈzɪliənt/", "meaning": "adj. 有韧性的", "example": "Children are often resilient.", "example_cn": "孩子往往很有韧性。"},
                    {"word": "ambiguous", "phonetic": "/æmˈbɪɡjuəs/", "meaning": "adj. 模棱两可的", "example": "The answer was ambiguous.", "example_cn": "答案模棱两可。"},
                    {"word": "coherent", "phonetic": "/kəʊˈhɪərənt/", "meaning": "adj. 连贯的", "example": "A coherent argument matters.", "example_cn": "连贯的论证很重要。"},
                    {"word": "feasible", "phonetic": "/ˈfiːzəbl/", "meaning": "adj. 可行的", "example": "The plan is feasible.", "example_cn": "这个计划可行。"},
                ],
                ensure_ascii=False,
            )
        else:
            content = "根据资料 [1]，学校期末考试安排在第十八周，缓考需要提前向教务处申请。"
        body = json.dumps({"choices": [{"message": {"content": content}}]}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    OUT.mkdir(exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 9999), MockLLM)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    errors: list[str] = []
    console_errors: list[str] = []
    try:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(OUT.parent / ".ui-profile"),
                channel="msedge",
                headless=True,
                viewport={"width": 1440, "height": 900},
                locale="zh-CN",
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
            page.evaluate(
                """() => {
                    localStorage.setItem('ecnu-llm', JSON.stringify({
                        model: 'deepseek-chat',
                        base_url: 'http://127.0.0.1:9999/v1',
                        provider: 'custom'
                    }));
                    sessionStorage.setItem('ecnu-llm-key', 'sk-mock-1234567890');
                }"""
            )
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(1200)

            # 1. 官网问答流式回答
            page.evaluate("location.hash = '#/ask'")
            page.wait_for_timeout(1200)
            page.fill("#chatInput", "华东师范大学的期末考试和缓考怎么安排？")
            page.click("#sendBtn")
            page.wait_for_function(
                "() => document.querySelector('.msg.assistant .msg-bubble')?.innerText?.includes('期末考试安排')",
                timeout=25000,
            )
            page.wait_for_timeout(800)
            assistant = page.locator(".msg.assistant .msg-bubble").last.inner_text()
            sources = page.locator(".source-chip").count()
            page.screenshot(path=str(OUT / "interact-chat.png"))
            print("CHAT:", assistant[:120].replace("\n", " "), "| sources:", sources)

            # 2. 学业问答
            page.evaluate("location.hash = '#/academic'")
            page.wait_for_timeout(1000)
            page.fill("#chatInput", "用例子解释一下梯度下降")
            page.click("#sendBtn")
            page.wait_for_function(
                "() => document.querySelector('.msg.assistant .msg-bubble')?.innerText?.includes('缓考')",
                timeout=20000,
            )
            print("ACADEMIC:", page.locator(".msg.assistant .msg-bubble").last.inner_text()[:80])

            # 3. 今日热点 AI 摘要
            page.evaluate("location.hash = '#/news'")
            page.wait_for_selector(".news-item", timeout=30000)
            page.click("#newsDigest")
            page.wait_for_selector(".digest-box", timeout=20000)
            digest = page.locator(".digest-box").inner_text()
            page.screenshot(path=str(OUT / "interact-news-digest.png"))
            print("DIGEST:", digest[:100].replace("\n", " "))

            # 4. 学习资料 AI 定制
            page.evaluate("location.hash = '#/study'")
            page.wait_for_timeout(1200)
            page.click("#studyAI")
            page.wait_for_function(
                "() => document.querySelector('#studyList')?.innerText?.includes('机器学习速成')",
                timeout=20000,
            )
            print("STUDY AI:", "ok")

            # 5. AI 教练
            page.evaluate("location.hash = '#/plans'")
            page.wait_for_timeout(1200)
            page.locator("[data-action=coach]").first.click()
            page.wait_for_selector(".modal .md", timeout=15000)
            coach = page.locator(".modal .md").inner_text()
            page.screenshot(path=str(OUT / "interact-coach.png"))
            page.locator(".modal [data-close]").first.click()
            print("COACH:", coach[:80].replace("\n", " "))

            # 6. AI 生成单词
            page.evaluate("location.hash = '#/plans'")
            page.wait_for_timeout(1200)
            page.locator("[data-action=vocab]").first.click()
            page.wait_for_selector(".modal")
            page.check("#vocabAI")
            page.fill("#vocabSize", "5")
            page.click("#startVocabBtn")
            page.wait_for_selector(".vocab-word", timeout=20000)
            word = page.locator(".vocab-word").inner_text()
            page.locator(".modal [data-close]").first.click()
            print("VOCAB AI:", word)

            context.close()
    finally:
        server.shutdown()
        server.server_close()

    print("PAGE ERRORS:", len(errors))
    for error in errors[:10]:
        print(" -", error[:300])
    print("CONSOLE ERRORS:", len(console_errors))
    for error in console_errors[:10]:
        print(" -", error[:300])
    return 1 if errors or console_errors else 0


if __name__ == "__main__":
    sys.exit(main())
