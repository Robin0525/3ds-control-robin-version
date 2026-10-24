#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Run both PC receivers in one console window.

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

HERE = os.path.dirname(os.path.abspath(__file__))

JOBS = [
    ("PAD", "pc.py"),
    ("PTR", "pc_pointer.py"),
]


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


def pump(tag, proc):
    for line in proc.stdout:
        print(f"[{tag}] {line.rstrip()}", flush=True)


def main():
    passthrough = [a for a in sys.argv[1:] if a in ("--debug",)]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")

    procs = []
    for tag, script in JOBS:
        path = os.path.join(HERE, script)
        if not os.path.exists(path):
            sys.exit(f"[ERROR] not found: {path}")
        proc = subprocess.Popen(
            [sys.executable, "-u", path] + passthrough,
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

    print("=" * 52)
    print("  3DS Control receiver")
    print(f"  PC IP : {local_ip() or '(not detected)'}")
    print("  PAD = gamepad mode  (UDP 8888)")
    print("  PTR = pointer mode  (UDP 8890)")
    print("  Keep this window open. Ctrl+C stops both.")
    print("=" * 52, flush=True)

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
