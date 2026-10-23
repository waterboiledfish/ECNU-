"""公式渲染、院系下拉与官网文件导入入口的端到端检查（开发用）。

需要 playwright + 系统 Edge，并先启动服务：
    ECNU_UI_BASE=http://127.0.0.1:8799 python scripts/ui_math_check.py
"""
from __future__ import annotations

import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get("ECNU_UI_BASE", "http://127.0.0.1:8765")

RENDER_JS = r"""
async () => {
  const mod = await import('/static/js/markdown.js');
  const source = [
    String.raw`勾股定理 $a^2+b^2=c^2$，以及显示公式：`,
    '',
    String.raw`$$\int_0^1 x^2\,dx = \frac{1}{3}$$`,
    '',
    String.raw`$$\begin{pmatrix} a & b \\ c & d \end{pmatrix}$$`,
    '',
    String.raw`价格 $5 到 $10 不应被当成公式。`
  ].join('\n');
  const host = document.createElement('div');
  host.id = 'math-probe';
  host.innerHTML = mod.renderMarkdown(source);
  document.body.appendChild(host);
  mod.typeset(host);
  return {
    formulas: host.querySelectorAll('.math').length,
    blocks: host.querySelectorAll('.math-block').length,
    text: host.innerText
  };
}
"""


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
            page.fill("#devNickname", "公式检查")
            page.click("#devLoginBtn")
            page.wait_for_timeout(1800)

        loaded = page.evaluate("() => Boolean(window.MathJax && typeof window.MathJax.typesetPromise === 'function')")
        failures += 0 if check("MathJax 本地脚本已加载", loaded) else 1

        rendered = page.evaluate(RENDER_JS)
        failures += 0 if check(
            "LaTeX 被包成公式节点", rendered["formulas"] == 3 and rendered["blocks"] == 2,
            f'公式 {rendered["formulas"]} 个 / 块级 {rendered["blocks"]} 个',
        ) else 1

        typeset = page.evaluate("""() => {
          const host = document.querySelector('#math-probe');
          return {
            containers: host.querySelectorAll('mjx-container').length,
            svgs: host.querySelectorAll('mjx-container svg').length,
            text: host.innerText
          };
        }""")
        failures += 0 if check(
            "MathJax 输出 SVG 容器", typeset["containers"] == 3 and typeset["svgs"] == 3,
            f'容器 {typeset["containers"]} 个 / SVG {typeset["svgs"]} 个',
        ) else 1
        failures += 0 if check(
            "公式不再以 LaTeX 原文显示",
            not any(token in (typeset["text"] or "") for token in ("$a^2", "\\int", "\\frac", "\\begin")),
            (typeset["text"] or "").replace("\n", " ")[:60],
        ) else 1
        failures += 0 if check(
            "金额 $5 到 $10 保持原文", "$5 到 $10" in (rendered["text"] or ""),
        ) else 1

        shots = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".ui-shots")
        os.makedirs(shots, exist_ok=True)
        page.evaluate("""() => {
          const host = document.querySelector('#math-probe');
          host.style.cssText = 'position:fixed;left:0;top:0;z-index:99999;background:#fff;color:#111;padding:16px;width:520px;font-size:15px;line-height:1.9';
        }""")
        page.locator("#math-probe").screenshot(path=os.path.join(shots, "math-probe.png"))
        print("screenshot:", os.path.join(shots, "math-probe.png"))

        page.evaluate("() => { location.hash = '#/me' }")
        page.wait_for_timeout(1400)
        profile = page.evaluate("""() => {
          const select = document.querySelector('#profDepartment');
          const list = document.querySelector('#profMajorOptions');
          return {
            select: Boolean(select),
            departments: select ? select.options.length : 0,
            majors: list ? list.querySelectorAll('option').length : 0
          };
        }""")
        failures += 0 if check(
            "个人设置有院系下拉与专业候选项",
            profile["select"] and profile["departments"] >= 30 and profile["majors"] > 0,
            f'院系 {profile["departments"]} 项 / 专业 {profile["majors"]} 项',
        ) else 1

        page.evaluate("() => { location.hash = '#/sources' }")
        page.wait_for_timeout(1400)
        button = page.query_selector("#importDoc")
        failures += 0 if check("官网文件页有「导入链接」入口", bool(button)) else 1
        if button:
            button.click()
            page.wait_for_timeout(500)
            modal = page.evaluate("""() => ({
              input: Boolean(document.querySelector('#importUrl')),
              submit: Boolean(document.querySelector('#importSubmit'))
            })""")
            failures += 0 if check(
                "导入弹窗可输入链接并提交", modal["input"] and modal["submit"],
            ) else 1
            page.keyboard.press("Escape")

        failures += 0 if check("页面无 JS 异常", not errors, "; ".join(errors[:3])) else 1
        browser.close()

    print("\nRESULT:", "OK" if not failures else f"{failures} FAILED")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
