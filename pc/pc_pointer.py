#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""3DS Pointer - PC 接收端

把 3DS 发来的触摸/摇杆/按键/文本，翻译成真实的鼠标键盘事件。

为什么用 SendInput 而不是 pyautogui / pynput：
  - 只依赖 ctypes + user32.dll，不用 pip 装任何东西
  - 不碰 ViGEmBus（虚拟手柄那条线有未定性的蓝屏嫌疑）
  - 支持 KEYEVENTF_UNICODE，能直接注入中文，绕过输入法

用法：
    python pc_kbm.py               正常启动
    python pc_kbm.py --debug       打印每个包
    python pc_kbm.py --no-tap      关闭"轻点即点击"，只能按 A 点击
    python pc_kbm.py --sensitivity 1.4   摇杆微调灵敏度
"""

import ctypes
import os
import socket
import struct
import sys
import time
from ctypes import wintypes

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------

PORT = 8890

PKT_STATE = 0x01
PKT_TEXT = 0x02

# libctru 按键位（低 16 位）
KEY_A, KEY_B, KEY_SELECT, KEY_START = 0x0001, 0x0002, 0x0004, 0x0008
KEY_DRIGHT, KEY_DLEFT, KEY_DUP, KEY_DDOWN = 0x0010, 0x0020, 0x0040, 0x0080
KEY_R, KEY_L, KEY_X, KEY_Y = 0x0100, 0x0200, 0x0400, 0x0800
KEY_ZL, KEY_ZR = 0x4000, 0x8000

# 下屏物理尺寸。相对位移模式下不做坐标映射，这里只作参考。
TOUCH_W, TOUCH_H = 320, 240

# SendInput 常量
INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x0020, 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x01000
MOUSEEVENTF_ABSOLUTE = 0x8000
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

# 虚拟键码
VK_BACK, VK_TAB, VK_RETURN, VK_ESCAPE, VK_SPACE = 0x08, 0x09, 0x0D, 0x1B, 0x20
VK_PRIOR, VK_NEXT = 0x21, 0x22
VK_LEFT, VK_UP, VK_RIGHT, VK_DOWN = 0x25, 0x26, 0x27, 0x28
VK_DELETE = 0x2E

# ---------- 触控板手感（对标笔记本精密触控板） ----------
TRACK_MIN_GAIN = 1.2       # 慢速滑动时的位移倍率：1 个 3DS 像素 -> 1.2 个屏幕像素
TRACK_MAX_GAIN = 6.0       # 快速滑动时的倍率：一划基本能跨屏
TRACK_SPEED_REF = 1500.0   # 手指速度达到这个值（3DS 像素/秒）就用最大倍率
INERTIA_DECAY = 0.88       # 甩动后每帧衰减，60Hz 下约 0.5 秒停住
INERTIA_MIN = 60.0         # 惯性速度低于此值就停（屏幕像素/秒）
TAP_MAX_MS = 300           # 轻点判定的最长按住时间
TAP_MAX_DIST = 12          # 轻点判定的最大位移（3DS 像素）
TAP_DRAG_MS = 300          # 轻点后多久内再次按下算"双击拖动"
DEBOUNCE_FRAMES = 2        # 按键需连续稳定几帧才认（60Hz 下约 33ms，压抖动）

# ---------- Circle Pad ----------
PAD_MAX_SPEED = 1400.0     # 推满时的速度，像素/秒
PAD_DEADZONE = 18          # 死区，摇杆回中时的抖动
PAD_CURVE = 2.0            # 加速曲线指数，越大越"细调友好"
STICK_RANGE = 156.0        # Circle Pad 的满量程

# ---------- C-Stick：滚动 ----------
CSTICK_ROLL_THRESHOLD = 28 # 推过这个量才开始滚（防误触）
CSTICK_RANGE = 90.0        # C-Stick 物理行程短得多，量程要单独给
CSTICK_ROLL_SLOW = 0.14    # 轻推时每滚一格的间隔，秒
CSTICK_ROLL_FAST = 0.05    # 推满时每滚一格的间隔

WHEEL_REPEAT = 0.045       # 按住 L/R 时滚轮重复间隔，秒
KEY_TAP_MAX = 0.45         # START/SELECT 超过这个时长就不算"短按"
IDLE_TIMEOUT = 2.0         # 超过这么久没收到包，强制释放所有按键

# --------------------------------------------------------------------------
# Win32 SendInput 封装
# --------------------------------------------------------------------------

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD),
                ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT
user32.GetSystemMetrics.argtypes = (ctypes.c_int,)
user32.GetSystemMetrics.restype = ctypes.c_int
user32.GetCursorPos.argtypes = (ctypes.POINTER(_POINT),)
user32.GetCursorPos.restype = wintypes.BOOL

SM_CXSCREEN, SM_CYSCREEN = 0, 1


def enable_dpi_awareness():
    """不开 DPI 感知的话，系统会把坐标按 125%/150% 缩放，绝对定位会偏。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


def _send(*inputs):
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    user32.SendInput(n, ctypes.cast(arr, ctypes.POINTER(INPUT)), ctypes.sizeof(INPUT))


def _mouse(dx=0, dy=0, data=0, flags=0):
    return INPUT(type=INPUT_MOUSE,
                 mi=MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, 0))


def _key(vk, up=False):
    flags = KEYEVENTF_KEYUP if up else 0
    return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(vk, 0, flags, 0, 0))


def mouse_click(flag_down, flag_up):
    _send(_mouse(flags=flag_down), _mouse(flags=flag_up))


def mouse_button(flag_down, flag_up, pressed):
    _send(_mouse(flags=flag_down if pressed else flag_up))


def mouse_wheel(notches):
    _send(_mouse(data=120 * notches, flags=MOUSEEVENTF_WHEEL))


def mouse_hwheel(notches):
    _send(_mouse(data=120 * notches, flags=MOUSEEVENTF_HWHEEL))


def key_tap(vk):
    _send(_key(vk), _key(vk, up=True))


def key_set(vk, pressed):
    _send(_key(vk, up=not pressed))


def type_unicode(text):
    """把文本作为 Unicode 字符注入，绕开输入法，中文也能直接打出来。"""
    units = []
    for ch in text:
        code = ord(ch)
        if code > 0xFFFF:                     # 补充平面字符，转 UTF-16 代理对
            code -= 0x10000
            units.append(0xD800 + (code >> 10))
            units.append(0xDC00 + (code & 0x3FF))
        else:
            units.append(code)

    arr = (INPUT * (len(units) * 2))()
    i = 0
    for u in units:
        arr[i] = INPUT(type=INPUT_KEYBOARD,
                       ki=KEYBDINPUT(0, u, KEYEVENTF_UNICODE, 0, 0))
        arr[i + 1] = INPUT(type=INPUT_KEYBOARD,
                           ki=KEYBDINPUT(0, u, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0))
        i += 2
    user32.SendInput(i, ctypes.cast(arr, ctypes.POINTER(INPUT)), ctypes.sizeof(INPUT))


# --------------------------------------------------------------------------
# 输入状态机
# --------------------------------------------------------------------------

class Pointer:
    def __init__(self, tap_enabled=True, sensitivity=1.0):
        self.sw = user32.GetSystemMetrics(SM_CXSCREEN)
        self.sh = user32.GetSystemMetrics(SM_CYSCREEN)
        self.x = self.sw / 2.0
        self.y = self.sh / 2.0
        self.tap_enabled = tap_enabled
        self.sens = sensitivity

        # 按键去抖：老机器的 B 键会抖，直接采信就会出现"没人碰它自己弹右键菜单"
        self.pending_buttons = 0
        self.pending_count = 0
        self.stable_buttons = 0
        self.prev_buttons = 0

        # 触控板
        self.prev_touching = False
        self.touch_t0 = 0.0
        self.touch_x0 = 0
        self.touch_y0 = 0
        self.touch_last_x = 0
        self.touch_last_y = 0
        self.last_move_time = 0.0
        self.touch_moved = False
        self.dragging = False

        # 双击拖动（tap-and-drag）
        self.last_tap_time = 0.0
        self.tap_drag_armed = False
        self.tap_dragging = False

        # 甩动惯性
        self.vel_x = 0.0
        self.vel_y = 0.0
        self.stick_active = False

        # 按键按住重复
        self.tap_time = {}
        self.wheel_next = 0.0
        self.wheel_dir = 0
        self.cstick_next = 0.0

        self.left_locked = False
        self.last_packet = time.time()

        self._place()

    # ---------- 光标 ----------

    def _place(self):
        """用绝对坐标把系统光标钉到 (x, y)。"""
        self.x = max(0.0, min(self.sw - 1.0, self.x))
        self.y = max(0.0, min(self.sh - 1.0, self.y))
        ax = int(self.x * 65535 / max(1, self.sw - 1))
        ay = int(self.y * 65535 / max(1, self.sh - 1))
        _send(_mouse(ax, ay, flags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE))

    def move_relative(self, dx, dy):
        if dx == 0.0 and dy == 0.0:
            return
        self.x += dx
        self.y += dy
        self._place()

    def sync_from_system(self):
        """把内部记录的坐标对齐到系统真实光标位置。

        必须做：我们用的是绝对定位，如果光标被外部移动过（真鼠标、别的程序、
        或者窗口切焦点时系统自己挪的），而内部坐标还停在旧值上，
        下一次输入就会把光标"啪"地拽回去 —— 表现为突然跳一下。
        """
        p = _POINT()
        if user32.GetCursorPos(ctypes.byref(p)):
            self.x = float(p.x)
            self.y = float(p.y)

    # ---------- 触控板 ----------

    def _slide(self, dx, dy, now):
        """手指位移 -> 光标位移。

        倍率随手指速度变化：慢慢蹭的时候 1:1.2（能精确点像素），
        快速划时放大到 6 倍（一划跨整个屏幕）。这是笔记本触控板的核心手感。
        """
        dist = (dx * dx + dy * dy) ** 0.5
        if dist < 0.5:
            return

        dt = now - self.last_move_time
        if dt <= 0:
            dt = 1.0 / 60.0
        self.last_move_time = now

        speed = dist / dt                          # 3DS 像素/秒
        t = min(speed / TRACK_SPEED_REF, 1.0)
        gain = (TRACK_MIN_GAIN + (TRACK_MAX_GAIN - TRACK_MIN_GAIN) * t) * self.sens

        mx, my = dx * gain, dy * gain
        self.move_relative(mx, my)

        # 记下速度，手指抬起后做惯性滑行（换算成屏幕像素/秒）
        self.vel_x = mx / dt
        self.vel_y = my / dt

    # ---------- 触摸 ----------

    def on_touch(self, touching, tx, ty, now):
        was = self.prev_touching
        self.prev_touching = touching

        if touching and not was:
            self.touch_t0 = now
            self.touch_x0, self.touch_y0 = tx, ty
            self.touch_last_x, self.touch_last_y = tx, ty
            self.last_move_time = now
            self.touch_moved = False
            self.dragging = False
            self.vel_x = self.vel_y = 0.0
            self.sync_from_system()   # 手指刚落下，先对齐真实光标位置

            # 双击拖动：上次轻点后 300ms 内又按下，这次的滑动就是拖拽
            self.tap_dragging = (self.tap_drag_armed and
                                 (now - self.last_tap_time) * 1000 < TAP_DRAG_MS)
            self.tap_drag_armed = False
            return

        if touching:
            dx = tx - self.touch_last_x
            dy = ty - self.touch_last_y
            self.touch_last_x, self.touch_last_y = tx, ty

            if not self.touch_moved:
                if (abs(tx - self.touch_x0) + abs(ty - self.touch_y0)) > TAP_MAX_DIST:
                    self.touch_moved = True
                    if self.tap_dragging and not self.dragging and not self.left_locked:
                        mouse_button(MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, True)
                        self.dragging = True

            if self.touch_moved:
                self._slide(dx, dy, now)
            return

        if was:  # 手指抬起
            if self.dragging:
                if not self.left_locked:
                    mouse_button(MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, False)
                self.dragging = False
                self.vel_x = self.vel_y = 0.0      # 拖拽结束不该继续滑
            elif not self.touch_moved:
                if self.tap_enabled and (now - self.touch_t0) * 1000 < TAP_MAX_MS:
                    mouse_click(MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)
                    self.last_tap_time = now
                    self.tap_drag_armed = True
                    self.vel_x = self.vel_y = 0.0
            self.tap_dragging = False

    # ---------- 按键 ----------

    def debounce(self, raw):
        """按键去抖：状态必须连续 DEBOUNCE_FRAMES 帧一致才采信。

        3DS 老机器的按键触点会抖（尤其 B 键），不去抖的话会凭空弹右键菜单。
        """
        if raw == self.pending_buttons:
            if self.pending_count < 255:
                self.pending_count += 1
        else:
            self.pending_buttons = raw
            self.pending_count = 1

        if self.pending_count >= DEBOUNCE_FRAMES:
            self.stable_buttons = raw
        return self.stable_buttons

    def _edge(self, key, buttons):
        """返回 (刚按下, 刚抬起)。"""
        return bool(buttons & key and not self.prev_buttons & key), \
               bool(not buttons & key and self.prev_buttons & key)

    def on_buttons(self, buttons, now):
        down, up = {}, {}
        for name, bit in (("A", KEY_A), ("B", KEY_B), ("X", KEY_X), ("Y", KEY_Y),
                          ("L", KEY_L), ("R", KEY_R), ("ZL", KEY_ZL), ("ZR", KEY_ZR),
                          ("START", KEY_START), ("SELECT", KEY_SELECT),
                          ("DUP", KEY_DUP), ("DDOWN", KEY_DDOWN),
                          ("DLEFT", KEY_DLEFT), ("DRIGHT", KEY_DRIGHT)):
            d, u = self._edge(bit, buttons)
            down[name], up[name] = d, u

        # A 左键（按住可拖拽） / B 右键 / X 中键
        if down["A"] or up["A"]:
            mouse_button(MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP,
                         bool(buttons & KEY_A) or self.left_locked)
        if down["B"] or up["B"]:
            mouse_button(MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, bool(buttons & KEY_B))
        if down["X"] or up["X"]:
            mouse_button(MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP, bool(buttons & KEY_X))

        # Y 左键锁定（拖选文字、拖窗口时不用一直按着）
        if down["Y"]:
            self.left_locked = not self.left_locked
            mouse_button(MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, self.left_locked)

        # L / R 滚轮，按住连滚
        if down["L"]:
            self.wheel_dir, self.wheel_next = 1, 0.0
        if down["R"]:
            self.wheel_dir, self.wheel_next = -1, 0.0
        if not (buttons & (KEY_L | KEY_R)):
            self.wheel_dir = 0

        # ZL / ZR 翻页
        if down["ZL"]:
            key_tap(VK_PRIOR)
        if down["ZR"]:
            key_tap(VK_NEXT)

        # START = Enter（短按才算，长按是 3DS 端的唤键盘手势）
        # SELECT = Esc
        for name, vk in (("START", VK_RETURN), ("SELECT", VK_ESCAPE)):
            if down[name]:
                self.tap_time[name] = now
            if up[name]:
                held = now - self.tap_time.pop(name, now)
                if held < KEY_TAP_MAX:
                    key_tap(vk)

        # 十字键 = PC 方向键
        for name, vk in (("DUP", VK_UP), ("DDOWN", VK_DOWN),
                         ("DLEFT", VK_LEFT), ("DRIGHT", VK_RIGHT)):
            if down[name]:
                key_set(vk, True)
            if up[name]:
                key_set(vk, False)

        self.prev_buttons = buttons

    # ---------- 每帧 ----------

    def tick(self, pad_x, pad_y, c_x, c_y, dt, now):
        # L / R 按住连滚
        if self.wheel_dir and now >= self.wheel_next:
            mouse_wheel(self.wheel_dir)
            self.wheel_next = now + WHEEL_REPEAT

        # Circle Pad：移动光标。刚开始推的那一帧先对齐真实光标位置。
        mag = (pad_x * pad_x + pad_y * pad_y) ** 0.5
        if mag >= PAD_DEADZONE:
            if not self.stick_active:
                self.sync_from_system()
                self.stick_active = True
            self._stick(pad_x, pad_y, dt)
        else:
            self.stick_active = False

        # C-Stick：滚动。上下 = 垂直滚轮，左右 = 水平滚轮。
        # 推得越深滚得越快（间隔从 0.14s 缩到 0.05s），和真实滚轮手感一致。
        if now >= self.cstick_next:
            depth = min(max(abs(c_y), abs(c_x)) / CSTICK_RANGE, 1.0)
            interval = CSTICK_ROLL_SLOW - (CSTICK_ROLL_SLOW - CSTICK_ROLL_FAST) * depth
            if abs(c_y) >= CSTICK_ROLL_THRESHOLD:
                mouse_wheel(1 if c_y > 0 else -1)
                self.cstick_next = now + interval
            elif abs(c_x) >= CSTICK_ROLL_THRESHOLD:
                mouse_hwheel(1 if c_x > 0 else -1)
                self.cstick_next = now + interval

        # 甩动惯性：手指已抬起时，光标沿最后的速度继续滑一小段并减速
        if not self.prev_touching:
            if abs(self.vel_x) > INERTIA_MIN or abs(self.vel_y) > INERTIA_MIN:
                self.move_relative(self.vel_x * dt, self.vel_y * dt)
                decay = INERTIA_DECAY ** (dt * 60.0)
                self.vel_x *= decay
                self.vel_y *= decay
            else:
                self.vel_x = self.vel_y = 0.0

    def _stick(self, x, y, dt):
        mag = (x * x + y * y) ** 0.5
        if mag < PAD_DEADZONE:
            return
        norm = min(mag / STICK_RANGE, 1.0)
        speed = (norm ** PAD_CURVE) * PAD_MAX_SPEED * self.sens
        # 3DS 摇杆 Y 向上为正，屏幕 Y 向下为正，所以垂直分量取反。
        # 触摸板是位移量（两边都向下为正），不取反。
        self.move_relative(x / mag * speed * dt, -y / mag * speed * dt)

    def release_all(self):
        """掉线或退出时，别把按键/左键锁死在按下状态。"""
        _send(
            _mouse(flags=MOUSEEVENTF_LEFTUP),
            _mouse(flags=MOUSEEVENTF_RIGHTUP),
            _mouse(flags=MOUSEEVENTF_MIDDLEUP),
        )
        for vk in (VK_UP, VK_DOWN, VK_LEFT, VK_RIGHT):
            _send(_key(vk, up=True))
        self.dragging = False
        self.left_locked = False
        self.prev_buttons = 0
        self.wheel_dir = 0


# --------------------------------------------------------------------------
# 网络
# --------------------------------------------------------------------------

def local_ip():
    """查自己局域网 IP：连一个不存在的地址不会真的发包，但能拿到出口网卡地址。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    debug = "--debug" in sys.argv
    tap_enabled = "--no-tap" not in sys.argv

    sens = 1.0
    if "--sensitivity" in sys.argv:
        try:
            sens = float(sys.argv[sys.argv.index("--sensitivity") + 1])
        except (IndexError, ValueError):
            pass

    enable_dpi_awareness()

    ptr = Pointer(tap_enabled=tap_enabled, sensitivity=sens)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", PORT))
    sock.settimeout(0.1)

    # CONTROL_QUIET is set by receiver_all.py, which prints the keymap itself.
    if not os.environ.get("CONTROL_QUIET") == "1":
        print("=" * 52)
        print("  3DS Control - pointer receiver")
        print("=" * 52)
        print(f"  监听端口 : {PORT}  (手柄模式用的是 8888，两者可同时开)")
        print(f"  本机 IP  : {local_ip()}")
        print(f"  屏幕     : {ptr.sw} x {ptr.sh}")
        print(f"  轻点点击 : {'开' if tap_enabled else '关'}   摇杆灵敏度: {sens}")
        print()
        print("  3DS 上输入上面的 IP，连上后：")
        print("    下屏当触控板：滑动=移动光标  轻点=左键  双击后拖动=拖拽")
        print("    Circle Pad = 移动光标        C-Stick = 滚轮（上下/左右）")
        print("    A 左键   B 右键   X 中键   Y 锁定左键")
        print("    L 滚轮上  R 滚轮下  ZL 上一页  ZR 下一页")
        print("    十字键 = 方向键   START 回车   SELECT 退出键")
        print("    退出：L+START+SELECT      切换模式：L+SELECT")
        print()
        print("  Ctrl+C 退出")
        print("=" * 52)

    connected = False
    last_now = time.time()

    try:
        while True:
            now = time.time()
            dt = min(now - last_now, 0.1)
            last_now = now

            try:
                data, addr = sock.recvfrom(2048)
            except socket.timeout:
                data = None

            if data is not None:
                if data == b"ping\x00":
                    sock.sendto(b"pong", addr)
                    if not connected:
                        print(f"\n[+] 3DS 已连接：{addr[0]}")
                        connected = True
                    ptr.last_packet = now
                elif len(data) >= 20 and data[0] == PKT_STATE:
                    (_type, touching, buttons, tx, ty,
                     px, py, cx, cy, _seq) = struct.unpack("<BBHhhhhhhI", data[:20])
                    if debug:
                        print(f"[state] touch={touching} ({tx},{ty}) "
                              f"pad=({px},{py}) cstick=({cx},{cy}) btn=0x{buttons:04x}")

                    buttons = ptr.debounce(buttons)
                    ptr.on_touch(bool(touching), tx, ty, now)
                    ptr.on_buttons(buttons, now)
                    ptr.tick(px, py, cx, cy, dt, now)
                elif len(data) >= 3 and data[0] == PKT_TEXT:
                    n = data[1] | (data[2] << 8)
                    text = data[3:3 + n].decode("utf-8", errors="replace")
                    if text:
                        type_unicode(text)
                        print(f"[文本] {text}")

            if connected and now - ptr.last_packet > IDLE_TIMEOUT:
                ptr.release_all()
                print("\n[-] 3DS 断开（超时），已释放所有按键")
                connected = False

    except KeyboardInterrupt:
        print("\n退出中...")
    finally:
        ptr.release_all()
        sock.close()
        print("已释放输入状态，安全退出。")


if __name__ == "__main__":
    main()
