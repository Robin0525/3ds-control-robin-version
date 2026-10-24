#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Run both PC receivers in one console window, with the keymap on screen.

3DS Control switches between two modes, and each mode talks to its own UDP
port, so both receivers have to be listening:

    GAMEPAD mode -> pc.py         port 8888  (vgamepad virtual Xbox pad)
    POINTER mode -> pc_pointer.py port 8890  (SendInput mouse/keyboard)

They run as separate processes on purpose: pc.py rides on ViGEmBus, the
pointer receiver only uses user32 SendInput, and keeping them apart means a
crash or a stuck virtual pad cannot take the other one down.

Usage:  python pc/receiver_all.py [--debug]
Ctrl+C stops both.
"""
import os
import socket
import subprocess
import sys
import threading
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))

JOBS = [
    ("PAD", "pc.py"),
    ("PTR", "pc_pointer.py"),
]

WIDTH = 66


def dw(text):
    """Display width: CJK characters take two cells in a console."""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)


def row(left, right, indent=2, col=34):
    gap = col - dw(left)
    if gap < 1:
        gap = 1
    return " " * indent + left + " " * gap + right


def local_ip():
    """Address the 3DS should be pointed at (no packet is actually sent)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def banner():
    ips = local_ip()
    rule = "=" * WIDTH
    thin = "-" * WIDTH
    out = [
        rule,
        "  3DS CONTROL  -  PC RECEIVER",
        f"  PC IP  {ips or '(not detected)'}      <- 3DS 上按 L+START 输入这个地址",
        "  PAD = 手柄 8888     PTR = 键鼠 8890     Ctrl+C 结束",
        rule,
        "",
        "  通用快捷键（两种模式都一样）",
        thin,
        row("L + START", "长按 0.6 秒    改 PC IP"),
        row("L + SELECT", "长按 0.6 秒    切换 手柄 / 键鼠"),
        row("L + START + SELECT", "退出程序"),
        "",
        "  手柄模式  GAMEPAD  ->  UDP 8888",
        thin,
        row("A / B / X / Y", "B / A / Y / X   (AB、XY 互换)"),
        row("Circle Pad / C-Stick", "左摇杆 / 右摇杆"),
        row("D-Pad", "方向键"),
        row("L / R", "LB / RB"),
        row("ZL / ZR", "LT / RT   (模拟扳机)"),
        row("START / SELECT", "START / BACK"),
        row("触摸屏 左半 / 右半", "L3 / R3   (按住持续)"),
        "",
        "  键鼠模式  POINTER  ->  UDP 8890",
        thin,
        row("下屏滑动", "移动光标"),
        row("下屏轻点 / 双击拖动", "左键 / 拖拽"),
        row("Circle Pad / C-Stick", "移动光标 / 滚轮"),
        row("A / B / X", "左键 / 右键 / 中键"),
        row("Y", "锁定左键"),
        row("L / R", "滚轮上 / 下"),
        row("ZL / ZR", "PageUp / PageDown"),
        row("D-Pad", "方向键"),
        row("START / SELECT", "Enter / Esc"),
        rule,
        "",
    ]
    print("\n".join(out), flush=True)


def pump(tag, proc):
    for line in proc.stdout:
        print(f"[{tag}] {line.rstrip()}", flush=True)


def main():
    passthrough = [a for a in sys.argv[1:] if a in ("--debug",)]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1",
               CONTROL_QUIET="1")

    banner()

    for tag, script in JOBS:
        path = os.path.join(HERE, script)
        if not os.path.exists(path):
            sys.exit(f"[ERROR] not found: {path}")

    procs = []
    for tag, script in JOBS:
        proc = subprocess.Popen(
            [sys.executable, "-u", os.path.join(HERE, script)] + passthrough,
            cwd=HERE,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        procs.append((tag, proc))
        threading.Thread(target=pump, args=(tag, proc), daemon=True).start()

    print("  等待 3DS 连接...", flush=True)

    try:
        while True:
            alive = [p for _, p in procs if p.poll() is None]
            if not alive:
                print("[ERROR] both receivers exited", flush=True)
                return 1
            for tag, p in procs:
                if p.poll() is not None and not getattr(p, "_reported", False):
                    p._reported = True
                    print(f"[{tag}] exited with code {p.returncode}", flush=True)
            threading.Event().wait(0.5)
    except KeyboardInterrupt:
        print("\nStopping receivers...", flush=True)
    finally:
        for _, p in procs:
            if p.poll() is None:
                p.terminate()
        for _, p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
