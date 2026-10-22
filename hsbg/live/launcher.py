"""Window/process helpers for fully automatic live launches.

Battle.net is started as a normal UI process; the bot restores its main window
and clicks the big '进入游戏' button (1600x1000 client-relative 0.08, 0.895).
If Hearthstone is already running, its window is reused.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import subprocess
import time
from pathlib import Path
from typing import Optional

from hsbg.live.config import LiveConfig
from hsbg.live.wininput import Win32Backend, find_hearthstone_window

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_CALLBACK = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

#: Battle.net main window "进入游戏" button (client-relative)
BN_PLAY = (0.08, 0.895)


def _process_path(pid: int) -> str:
    h = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(len(buf))
        if _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        _kernel32.CloseHandle(h)


def _iter_windows():
    out = []

    def cb(hwnd, lparam):
        pid = wt.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        rect = wt.RECT()
        _user32.GetWindowRect(hwnd, ctypes.byref(rect))
        out.append((hwnd, pid.value, rect))
        return True

    _user32.EnumWindows(_CALLBACK(cb), 0)
    return out


def find_battlenet_window() -> Optional[int]:
    best = None
    best_area = 0
    for hwnd, pid, rect in _iter_windows():
        if "battle.net" not in _process_path(pid).lower():
            continue
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w < 500 or h < 300:
            continue
        area = w * h
        if area > best_area:
            best, best_area = hwnd, area
    return best


def _client_origin(hwnd: int) -> tuple[int, int, int, int]:
    rect = wt.RECT()
    _user32.GetClientRect(hwnd, ctypes.byref(rect))
    origin = wt.POINT(0, 0)
    _user32.ClientToScreen(hwnd, ctypes.byref(origin))
    return origin.x, origin.y, rect.right, rect.bottom


def launch_hearthstone_via_battlenet(*, timeout_s: float = 180.0,
                                     log=print) -> bool:
    cfg = LiveConfig()
    bn_exe = Path(getattr(cfg.paths, "battle_net", r"C:\Program Files (x86)\Battle.net\Battle.net.exe"))
    hwnd = find_battlenet_window()
    if hwnd is None:
        if not bn_exe.exists():
            log(f"[launcher] Battle.net not found: {bn_exe}")
            return False
        log("[launcher] starting Battle.net UI")
        subprocess.Popen([str(bn_exe)])
        deadline = time.time() + 60
        while time.time() < deadline:
            time.sleep(2)
            hwnd = find_battlenet_window()
            if hwnd is not None:
                break
    if hwnd is None:
        log("[launcher] no Battle.net window")
        return False
    _user32.ShowWindow(hwnd, 9)
    _user32.SetForegroundWindow(hwnd)
    time.sleep(0.8)
    ox, oy, cw, ch = _client_origin(hwnd)
    x = ox + int(BN_PLAY[0] * cw)
    y = oy + int(BN_PLAY[1] * ch)
    log(f"[launcher] click Battle.net play at {x},{y} (client {cw}x{ch})")
    Win32Backend().click(x, y)
    deadline = time.time() + float(timeout_s)
    while time.time() < deadline:
        time.sleep(2)
        try:
            w = find_hearthstone_window()
        except Exception:
            w = None
        if w is not None:
            log("[launcher] Hearthstone window ready")
            _user32.ShowWindow(w.hwnd, 9)
            _user32.SetForegroundWindow(w.hwnd)
            return True
    log("[launcher] Hearthstone window did not appear in time")
    return False


if __name__ == "__main__":
    print("battlenet hwnd:", find_battlenet_window())
