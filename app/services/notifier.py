"""本地提醒弹窗：系统窗口（tkinter）或 cmd 控制台窗口。

只在用户为某条提醒勾选 system/cmd 时触发，且只在本机执行。
提醒文本写入临时文件，不拼接进命令，避免命令注入。
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import uuid

from ..config import PROJECT_ROOT, settings

WINDOWS = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000 if WINDOWS else 0


def _has_tkinter() -> bool:
    try:
        return importlib.util.find_spec("tkinter") is not None
    except (ImportError, ValueError):
        return False


def channels_available() -> list[str]:
    result = ["inapp", "browser"]
    if sys.platform in {"win32", "darwin", "linux"} and _has_tkinter():
        result.append("system")
    if WINDOWS:
        result.append("cmd")
    return result


def _write_message(reminder_id: int, title: str, body: str) -> str:
    name = f"reminder-{reminder_id}-{uuid.uuid4().hex[:8]}.txt"
    path = settings.popup_dir / name
    content = f"{title}\n\n{body}\n"
    path.write_text(content, encoding="utf-8")
    return str(path)


def send_system_popup(reminder_id: int, title: str, body: str) -> bool:
    message_file = _write_message(reminder_id, title, body)
    try:
        subprocess.Popen(
            [sys.executable, "-m", "app.notify_popup", "--file", message_file],
            cwd=str(PROJECT_ROOT),
            creationflags=CREATE_NO_WINDOW if WINDOWS else 0,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def send_cmd_popup(reminder_id: int, title: str, body: str) -> bool:
    if not WINDOWS:
        return False
    message_file = _write_message(reminder_id, title, body)
    script = settings.popup_dir / f"popup-{reminder_id}-{uuid.uuid4().hex[:8]}.bat"
    # 批处理内容全部为 ASCII 静态文本；用户输入只存在于被 type 的文本文件中。
    script.write_text(
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "title ECNU Assistant Reminder\r\n"
        f'type "{message_file}"\r\n'
        "echo.\r\n"
        "echo Close this window when done.\r\n"
        "timeout /t 120 >nul\r\n",
        encoding="utf-8",
    )
    try:
        subprocess.Popen(
            ["cmd.exe", "/c", "start", "", str(script)],
            creationflags=CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def dispatch(reminder_id: int, title: str, body: str, channels: list[str]) -> dict[str, bool]:
    result: dict[str, bool] = {}
    if "system" in channels:
        result["system"] = send_system_popup(reminder_id, title, body)
    if "cmd" in channels:
        result["cmd"] = send_cmd_popup(reminder_id, title, body)
    return result
