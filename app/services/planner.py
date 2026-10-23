"""计划教练：无 Key 时给出本地可执行建议，有 Key 时让模型定制。"""
from __future__ import annotations

from ..services import llm


def _history_line(history: list[dict]) -> str:
    return "、".join(
        f"{item['label']} {item['done']}/{item.get('target', '')}" if item.get("done") else item["label"]
        for item in history
    )


def local_advice(plan: dict, history: list[dict]) -> str:
    title = plan.get("title", "计划")
    target = plan.get("target_count", 1)
    unit = plan.get("unit", "次")
    completed = sum(1 for item in history if item.get("completed"))
    recent = sum(int(item.get("done", 0)) for item in history)
    category = plan.get("category", "custom")
    tips = {
        "vocab": [
            "先复习到期单词，再学新词；每个词只记「词义 + 一个搭配」。",
            "把今天最容易忘的 5 个词写进手机备忘录，晚饭后再翻一次。",
            "睡前用 3 分钟自测：遮住中文，说出词义即可。",
        ],
        "reading": [
            "先读摘要和结论，再回头读方法；每段只抓一个论点。",
            "读完后用三句话复述：问题、方法、结论。",
            "遇到不懂的术语先标记，读完再统一查。",
        ],
        "exercise": [
            "把目标拆成两段完成，中间休息 5 分钟。",
            "优先保证动作质量，不追求数量。",
            "结束后记录体感，第二天据此调整强度。",
        ],
        "skill": [
            "今天只练一个最小可交付动作，例如写出 20 行代码或完成一个例题。",
            "结束后写一句「今天卡在哪」，明天从这里开始。",
            "把练习成果保存下来，方便周末复盘。",
        ],
        "custom": [
            "把任务拆成 25 分钟一段，先完成第一段再决定是否继续。",
            "开始前先写下「完成的标准是什么」。",
            "结束后记录实际用时，下次估时会更准。",
        ],
    }.get(category, [])
    lines = [
        f"**今日建议 · {title}**",
        "",
        f"- 目标：{target} {unit}；过去 7 天累计完成 {recent}，完整达成 {completed} 天。",
        "",
        "**直接开始**",
    ]
    lines += [f"{i + 1}. {tip}" for i, tip in enumerate(tips)]
    lines += [
        "",
        "**两分钟收尾**",
        "- 记录今天实际完成了多少；没完成也没关系，把剩下的写进明天的第一步。",
    ]
    return "\n".join(lines)


def ai_advice(creds: dict, plan: dict, history: list[dict]) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                "你是一名务实、温和的学习教练。根据用户的计划和最近 7 天记录，"
                "给出今天可以直接执行的 3-4 步建议，以及一个两分钟收尾动作。"
                "用简体中文 markdown，控制在 200 字以内，不要空泛鼓励。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"计划：{plan.get('title')}；类别：{plan.get('category')}；"
                f"频率：{plan.get('cadence')}；目标：{plan.get('target_count')} {plan.get('unit')}；"
                f"备注：{plan.get('note') or '无'}\n"
                f"最近 7 天：{_history_line(history)}\n"
                "请给出今天的执行建议。"
            ),
        },
    ]
    return llm.chat(
        messages,
        key=creds["key"],
        model=creds["model"],
        base_url=creds.get("base_url"),
        temperature=0.5,
        timeout=45,
        max_tokens=500,
    )
