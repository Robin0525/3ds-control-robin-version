#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""实时读取 XInput 手柄完整状态（含扳机与右摇杆）。

3DS 按键到 XInput 的映射：
  A/B/X/Y        -> A/B/X/Y
  L / R          -> LB / RB
  ZL / ZR        -> LT / RT      (左/右扳机，0-255 模拟量)
  左摇杆         -> LX / LY
  C-Stick 右摇杆 -> RX / RY
  START / SELECT -> START / BACK
  D-Pad          -> UP/DOWN/LEFT/RIGHT
"""
import ctypes
import time
from ctypes import wintypes

DLLS = ["xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll"]


class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", wintypes.WORD),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [
        ("dwPacketNumber", wintypes.DWORD),
        ("Gamepad", XINPUT_GAMEPAD),
    ]


BTN = {
    0x0001: "UP", 0x0002: "DOWN", 0x0004: "LEFT", 0x0008: "RIGHT",
    0x0010: "START", 0x0020: "BACK", 0x0040: "LTHUMB", 0x0080: "RTHUMB",
    0x0100: "LB", 0x0200: "RB", 0x1000: "A", 0x2000: "B",
    0x4000: "X", 0x8000: "Y",
}


def load_xinput():
    for name in DLLS:
        try:
            return ctypes.windll.LoadLibrary(name), name
        except OSError:
            continue
    return None, None


def snapshot(state):
    g = state.Gamepad
    btns = tuple(n for b, n in BTN.items() if g.wButtons & b)
    return (btns, g.sThumbLX, g.sThumbLY, g.sThumbRX, g.sThumbRY,
            g.bLeftTrigger, g.bRightTrigger)


def fmt(slot, snap):
    btns, lx, ly, rx, ry, lt, rt = snap
    name = ",".join(btns) if btns else "-"
    return (f"[{slot}] {name:<24} "
            f"L({lx:+6d},{ly:+6d})  R({rx:+6d},{ry:+6d})  LT={lt:3d} RT={rt:3d}")


def main():
    xinput, name = load_xinput()
    if not xinput:
        print("[FATAL] XInput DLL not found")
        return
    print(f"[OK] {name}")
    print("Watching 4 slots for 30s. Press buttons / ZL / ZR / C-Stick on the 3DS.\n")

    last = {}
    deadline = time.time() + 30
    hits = {"button": False, "trigger": False, "rstick": False}
    try:
        while time.time() < deadline:
            for slot in range(4):
                state = XINPUT_STATE()
                if xinput.XInputGetState(slot, ctypes.byref(state)) != 0:
                    if last.get(slot) is not None:
                        print(f"[{slot}] not connected")
                        last[slot] = None
                    continue
                snap = snapshot(state)
                if last.get(slot) != snap:
                    print(fmt(slot, snap))
                    last[slot] = snap
                    if snap[0]:
                        hits["button"] = True
                    if snap[5] or snap[6]:
                        hits["trigger"] = True
                    if abs(snap[3]) > 3000 or abs(snap[4]) > 3000:
                        hits["rstick"] = True
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass

    print("\n=== RESULT ===")
    print(f"buttons      : {'OK' if hits['button'] else 'no'}")
    print(f"ZL/ZR (LT/RT): {'OK' if hits['trigger'] else 'no'}")
    print(f"C-Stick (R)  : {'OK' if hits['rstick'] else 'no'}")
    print("\nIf a slot shows activity but the game ignores it, the game is reading slot 0.")
    print("Press Enter to close.")
    try:
        input()
    except EOFError:
        pass


if __name__ == "__main__":
    main()
