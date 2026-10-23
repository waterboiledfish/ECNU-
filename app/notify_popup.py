"""置顶提醒窗口（tkinter）。由 notifier 以子进程启动。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def run(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n", 1)
    title = lines[0].strip() or "ECNU 小助手提醒"
    body = lines[1].strip() if len(lines) > 1 else ""
    try:
        import tkinter as tk
    except ImportError:
        print(text)
        return 1
    root = tk.Tk()
    root.title("ECNU 小助手 · 提醒")
    root.attributes("-topmost", True)
    root.configure(bg="#0b3a66")
    root.geometry("420x240+80+80")
    frame = tk.Frame(root, bg="#0b3a66", padx=24, pady=20)
    frame.pack(fill="both", expand=True)
    tk.Label(
        frame,
        text=title,
        bg="#0b3a66",
        fg="#ffffff",
        font=("Microsoft YaHei UI", 15, "bold"),
        wraplength=370,
        justify="left",
    ).pack(anchor="w")
    tk.Label(
        frame,
        text=body,
        bg="#0b3a66",
        fg="#dbeafe",
        font=("Microsoft YaHei UI", 10),
        wraplength=370,
        justify="left",
    ).pack(anchor="w", pady=(12, 0))
    tk.Button(
        frame,
        text="知道了",
        command=root.destroy,
        bg="#16a3a0",
        fg="white",
        relief="flat",
        padx=18,
        pady=6,
        font=("Microsoft YaHei UI", 10, "bold"),
    ).pack(anchor="e", pady=(16, 0))
    root.after(120_000, root.destroy)
    try:
        root.bell()
    except Exception:
        pass
    root.mainloop()
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    args = parser.parse_args(argv)
    return run(Path(args.file))


if __name__ == "__main__":
    sys.exit(main())
