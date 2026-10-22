"""Win32 输入层：找窗口 / DPI / 相对坐标点击拖拽 / 前台 / F12 暂停 / 截图。

设计
----
* **相对坐标**：所有接口都接收窗口内相对比例 ``(fx, fy) ∈ [0,1]``，
  由窗口矩形映射到屏幕像素（``screen = (left,top) + (fx,fy) * (width,height)``）。
  窗口 rect 含标题栏（与 ``runs/live/game_screen.png`` 一致，见 config 注释）。
* **零第三方硬依赖**：窗口枚举/输入/热键/前台全部走 ``ctypes`` 调 ``user32``；
  ``Pillow`` 仅用于截图（缺失时截图返回 ``None``，不影响主流程）；
  ``pyautogui`` 仅作为可选 fallback（未安装则不可用）。
* **可测试**：真正的系统调用都在 :class:`Win32Backend` 里；上层
  :class:`InputController` 只依赖 :class:`InputBackend` 协议，测试用
  ``DryRunBackend`` / 自定义 fake 即可验证坐标映射与操作序列（不碰真实鼠标）。
* **dry-run**：``InputController(dry_run=True)`` 不调用任何系统输入 API，
  只记录并打印计划；没有游戏窗口时使用配置里的 ``window.expected_rect``。

没有 Windows / 没有游戏窗口时，本模块仍可 import；只有真正创建
:class:`Win32Backend` 或寻找窗口时才会抛 :class:`WindowNotFoundError`。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, Tuple

from hsbg.live.config import LiveConfig

#: 常用虚拟键码
VK_CODES: Dict[str, int] = {
    "BACKSPACE": 0x08,
    "TAB": 0x09,
    "ENTER": 0x0D,
    "RETURN": 0x0D,
    "ESC": 0x1B,
    "ESCAPE": 0x1B,
    "SPACE": 0x20,
    "LEFT": 0x25,
    "UP": 0x26,
    "RIGHT": 0x27,
    "DOWN": 0x28,
    "E": 0x45,
    "F": 0x46,
    "F1": 0x70,
    "F2": 0x71,
    "F3": 0x72,
    "F4": 0x73,
    "F5": 0x74,
    "F6": 0x75,
    "F7": 0x76,
    "F8": 0x77,
    "F9": 0x78,
    "F10": 0x79,
    "F11": 0x7A,
    "F12": 0x7B,
}

#: 鼠标/键盘事件常量
_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_RIGHTDOWN = 0x0008
_MOUSEEVENTF_RIGHTUP = 0x0010
_MOUSEEVENTF_ABSOLUTE = 0x8000
_KEYEVENTF_KEYUP = 0x0002
_INPUT_MOUSE = 0
_INPUT_KEYBOARD = 1
_SW_RESTORE = 9
_SW_SHOW = 5
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_DWMWA_EXTENDED_FRAME_BOUNDS = 9


class WindowNotFoundError(RuntimeError):
    """找不到炉石窗口（或没有 Windows 窗口系统）。"""


@dataclass
class WindowInfo:
    """一个顶层窗口的信息。

    * ``rect``：窗口外框（屏幕像素，含标题栏/边框）；
    * ``client_rect``：**客户区**（屏幕像素，不含标题栏/边框），游戏画面就在其中。
      相对坐标默认按客户区映射（可切回窗口外框，见 ``WindowConfig.use_client_rect``）。
    """

    hwnd: int
    title: str = ""
    process: str = ""
    rect: Tuple[int, int, int, int] = (0, 0, 0, 0)
    client_rect: Optional[Tuple[int, int, int, int]] = None

    @property
    def width(self) -> int:
        return max(0, int(self.rect[2]) - int(self.rect[0]))

    @property
    def height(self) -> int:
        return max(0, int(self.rect[3]) - int(self.rect[1]))

    @property
    def client_width(self) -> int:
        rect = self.client_rect or self.rect
        return max(0, int(rect[2]) - int(rect[0]))

    @property
    def client_height(self) -> int:
        rect = self.client_rect or self.rect
        return max(0, int(rect[3]) - int(rect[1]))

    def mapping_rect(self) -> Tuple[int, int, int, int]:
        """相对坐标映射用的屏幕矩形（优先客户区）。"""
        return self.client_rect or self.rect

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hwnd": int(self.hwnd),
            "title": self.title,
            "process": self.process,
            "rect": list(self.rect),
            "width": self.width,
            "height": self.height,
            "client_rect": list(self.client_rect) if self.client_rect else None,
            "client_width": self.client_width,
            "client_height": self.client_height,
        }


# ══════════════════════════════════════════════════════════════════════
# 输入后端协议
# ══════════════════════════════════════════════════════════════════════


class InputBackend(Protocol):
    """系统输入/截图后端协议（真实实现在 :class:`Win32Backend`）。"""

    name: str

    def find_window(self, titles: Sequence[str], process: str = "") -> Optional[WindowInfo]:
        ...

    def screen_size(self) -> Tuple[int, int]:
        ...

    def move(self, x: int, y: int) -> None:
        ...

    def click(self, x: int, y: int, button: str = "left", double: bool = False) -> None:
        ...

    def drag(self, points: Sequence[Tuple[int, int]], duration: float) -> None:
        ...

    def key(self, vk: int) -> None:
        ...

    def is_key_down(self, vk: int) -> bool:
        ...

    def foreground(self) -> Optional[int]:
        ...

    def set_foreground(self, hwnd: int, retries: int = 5,
                       delay: float = 0.25) -> bool:
        ...

    def screenshot(self, path: Path,
                   rect: Optional[Tuple[int, int, int, int]] = None) -> Optional[Path]:
        ...


# ══════════════════════════════════════════════════════════════════════
# 纯记录后端（dry-run / 测试）
# ══════════════════════════════════════════════════════════════════════


class DryRunBackend:
    """不触碰系统的后端：记录所有调用，可注入窗口与按键状态（测试友好）。

    * ``window`` 可显式指定（默认按 ``expected_rect`` 造一个假窗口）；
    * ``keys_down`` 集合用于模拟 F12 等热键（``press_key`` / ``release_key``）；
    * ``screenshots`` 为 True 时 ``screenshot`` 写一个 1×1 PNG 占位文件（便于测试）。
    """

    name = "dry-run"

    def __init__(
        self,
        window: Optional[WindowInfo] = None,
        *,
        screenshots: bool = False,
        screen_size: Tuple[int, int] = (1920, 1080),
    ) -> None:
        self.calls: List[Tuple[str, Tuple[Any, ...]]] = []
        self.window = window
        self.screenshots = screenshots
        self.keys_down: set = set()
        self._screen_size = screen_size

    # ── 记录 ──
    def _log(self, name: str, *args: Any) -> None:
        self.calls.append((name, tuple(args)))

    # ── 协议实现 ──
    def find_window(self, titles: Sequence[str], process: str = "") -> Optional[WindowInfo]:
        self._log("find_window", list(titles), process)
        return self.window

    def screen_size(self) -> Tuple[int, int]:
        return self._screen_size

    def move(self, x: int, y: int) -> None:
        self._log("move", int(x), int(y))

    def click(self, x: int, y: int, button: str = "left", double: bool = False) -> None:
        self._log("click", int(x), int(y), button, bool(double))

    def drag(self, points: Sequence[Tuple[int, int]], duration: float) -> None:
        self._log("drag", [tuple(int(v) for v in p) for p in points], float(duration))

    def key(self, vk: int) -> None:
        self._log("key", int(vk))

    def is_key_down(self, vk: int) -> bool:
        return int(vk) in self.keys_down

    def press_key(self, vk: int) -> None:
        self.keys_down.add(int(vk))

    def release_key(self, vk: int) -> None:
        self.keys_down.discard(int(vk))

    def foreground(self) -> Optional[int]:
        return int(self.window.hwnd) if self.window is not None else None

    def set_foreground(self, hwnd: int, retries: int = 5,
                       delay: float = 0.25) -> bool:
        self._log("set_foreground", int(hwnd))
        return True

    def screenshot(self, path: Path,
                   rect: Optional[Tuple[int, int, int, int]] = None) -> Optional[Path]:
        self._log("screenshot", str(path), list(rect) if rect else None)
        if not self.screenshots:
            return None
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            from PIL import Image

            Image.new("RGB", (8, 8), (32, 32, 32)).save(path)
            return path
        except Exception:  # pragma: no cover - Pillow 缺失
            path.write_bytes(b"\x89PNG\r\n\x1a\n")
            return path


# ══════════════════════════════════════════════════════════════════════
# Win32 后端（ctypes，无第三方硬依赖）
# ══════════════════════════════════════════════════════════════════════


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wt.LONG),
        ("dy", wt.LONG),
        ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wt.ULONG)),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD),
        ("wScan", wt.WORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wt.ULONG)),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


class Win32Backend:
    """Windows 真实输入后端（ctypes user32 / dwmapi / PIL 截图）。"""

    name = "win32"

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise WindowNotFoundError("Win32Backend 仅支持 Windows")
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._enable_dpi_awareness()
        self._user32.SendInput.argtypes = (wt.UINT, ctypes.POINTER(_INPUT), ctypes.c_int)
        self._user32.SendInput.restype = wt.UINT
        self._user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
        self._user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        self._user32.GetAsyncKeyState.restype = ctypes.c_short
        self._user32.GetForegroundWindow.restype = wt.HWND
        self._user32.GetWindowRect.argtypes = (wt.HWND, ctypes.POINTER(wt.RECT))

    # ── DPI ──
    def _enable_dpi_awareness(self) -> None:
        """尽量开启 per-monitor DPI awareness，保证坐标是物理像素。"""
        try:
            fn = self._user32.SetProcessDpiAwarenessContext
            fn.argtypes = (ctypes.c_void_p,)
            fn.restype = wt.BOOL
            if fn(ctypes.c_void_p(-4)):  # PER_MONITOR_AWARE_V2
                return
        except Exception:  # noqa: BLE001
            pass
        try:
            shcore = ctypes.WinDLL("shcore", use_last_error=True)
            shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
            return
        except Exception:  # noqa: BLE001
            pass
        try:
            self._user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass

    # ── 窗口 ──
    def _window_title(self, hwnd: int) -> str:
        length = int(self._user32.GetWindowTextLengthW(wt.HWND(hwnd)))
        buf = ctypes.create_unicode_buffer(length + 1)
        self._user32.GetWindowTextW(wt.HWND(hwnd), buf, length + 1)
        return buf.value

    def _process_name(self, hwnd: int) -> str:
        pid = wt.DWORD()
        self._user32.GetWindowThreadProcessId(wt.HWND(hwnd), ctypes.byref(pid))
        handle = self._kernel32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value
        )
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wt.DWORD(1024)
            ok = self._kernel32.QueryFullProcessImageNameW(
                wt.HANDLE(handle), 0, buf, ctypes.byref(size)
            )
            return Path(buf.value).name if ok else ""
        finally:
            self._kernel32.CloseHandle(wt.HANDLE(handle))

    def _window_rect(self, hwnd: int) -> Tuple[int, int, int, int]:
        rect = wt.RECT()
        ok = self._user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(rect))
        if ok:
            return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
        # DWM 备用（窗口有阴影/边框时更准）
        try:
            dwm = ctypes.WinDLL("dwmapi", use_last_error=True)
            r = wt.RECT()
            dwm.DwmGetWindowAttribute(wt.HWND(hwnd), _DWMWA_EXTENDED_FRAME_BOUNDS,
                                      ctypes.byref(r), ctypes.sizeof(r))
            return int(r.left), int(r.top), int(r.right), int(r.bottom)
        except Exception:  # noqa: BLE001
            return (0, 0, 0, 0)

    def _client_rect(self, hwnd: int) -> Optional[Tuple[int, int, int, int]]:
        """客户区屏幕矩形（游戏画面区域，不含标题栏/边框）。"""
        try:
            rect = wt.RECT()
            if not self._user32.GetClientRect(wt.HWND(hwnd), ctypes.byref(rect)):
                return None
            width = int(rect.right - rect.left)
            height = int(rect.bottom - rect.top)
            if width <= 0 or height <= 0:
                return None
            origin = wt.POINT(0, 0)
            if not self._user32.ClientToScreen(wt.HWND(hwnd), ctypes.byref(origin)):
                return None
            left, top = int(origin.x), int(origin.y)
            return left, top, left + width, top + height
        except Exception:  # noqa: BLE001
            return None

    def find_window(self, titles: Sequence[str], process: str = "") -> Optional[WindowInfo]:
        wanted_titles = [t.lower() for t in titles if t]
        wanted_process = (process or "").lower()
        found: List[WindowInfo] = []

        @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        def _callback(hwnd: int, _lparam: int) -> bool:  # noqa: ANN001
            if not self._user32.IsWindowVisible(wt.HWND(hwnd)):
                return True
            title = self._window_title(hwnd)
            proc = self._process_name(hwnd)
            title_ok = any(t in title.lower() for t in wanted_titles)
            proc_ok = bool(wanted_process and proc.lower() == wanted_process)
            if title_ok or proc_ok:
                rect = self._window_rect(hwnd)
                if rect[2] > rect[0] and rect[3] > rect[1]:
                    found.append(WindowInfo(
                        hwnd=int(hwnd), title=title, process=proc, rect=rect,
                        client_rect=self._client_rect(hwnd),
                    ))
            return True

        self._user32.EnumWindows(_callback, 0)
        if not found:
            return None
        # 标题精确匹配优先，其次面积最大（游戏窗口通常最大）
        found.sort(
            key=lambda w: (
                0 if any(w.title.lower() == t for t in wanted_titles) else 1,
                -(w.width * w.height),
            )
        )
        return found[0]

    def screen_size(self) -> Tuple[int, int]:
        return (
            int(self._user32.GetSystemMetrics(0)),
            int(self._user32.GetSystemMetrics(1)),
        )

    # ── 输入 ──
    def _send_mouse(self, flags: int, dx: int = 0, dy: int = 0) -> None:
        inp = _INPUT(type=_INPUT_MOUSE)
        inp.mi = _MOUSEINPUT(dx=int(dx), dy=int(dy), mouseData=0,
                             dwFlags=int(flags), time=0, dwExtraInfo=None)
        self._user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))

    def move(self, x: int, y: int) -> None:
        sw, sh = self.screen_size()
        ax = int(round(max(0, min(65535, x * 65535 / max(sw - 1, 1)))))
        ay = int(round(max(0, min(65535, y * 65535 / max(sh - 1, 1)))))
        self._send_mouse(_MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE, ax, ay)

    #: 移动到目标后到按下之间的等待（Unity 的 hover/点击判定需要至少一帧）
    HOVER_SETTLE_S = 0.10

    def click(self, x: int, y: int, button: str = "left", double: bool = False) -> None:
        self.move(x, y)
        time.sleep(self.HOVER_SETTLE_S)
        down, up = ((_MOUSEEVENTF_LEFTDOWN, _MOUSEEVENTF_LEFTUP)
                    if button == "left" else
                    (_MOUSEEVENTF_RIGHTDOWN, _MOUSEEVENTF_RIGHTUP))
        clicks = 2 if double else 1
        for _ in range(clicks):
            self._send_mouse(down)
            time.sleep(0.06)
            self._send_mouse(up)
            time.sleep(0.08)

    def drag(self, points: Sequence[Tuple[int, int]], duration: float) -> None:
        pts = [(int(x), int(y)) for x, y in points]
        if not pts:
            return
        self.move(*pts[0])
        time.sleep(self.HOVER_SETTLE_S)
        self._send_mouse(_MOUSEEVENTF_LEFTDOWN)
        time.sleep(0.08)
        steps = max(2, len(pts))
        per = max(0.0, float(duration)) / steps
        for x, y in pts[1:]:
            self.move(x, y)
            time.sleep(per)
        self._send_mouse(_MOUSEEVENTF_LEFTUP)
        time.sleep(0.03)

    def key(self, vk: int) -> None:
        vk = int(vk)
        down = _INPUT(type=_INPUT_KEYBOARD)
        down.ki = _KEYBDINPUT(wVk=vk, wScan=0, dwFlags=0, time=0, dwExtraInfo=None)
        up = _INPUT(type=_INPUT_KEYBOARD)
        up.ki = _KEYBDINPUT(wVk=vk, wScan=0, dwFlags=_KEYEVENTF_KEYUP,
                            time=0, dwExtraInfo=None)
        self._user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(_INPUT))
        time.sleep(0.02)
        self._user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(_INPUT))

    def is_key_down(self, vk: int) -> bool:
        return bool(self._user32.GetAsyncKeyState(int(vk)) & 0x8000)

    # ── 前台 ──
    def foreground(self) -> Optional[int]:
        hwnd = self._user32.GetForegroundWindow()
        return int(hwnd) if hwnd else None

    def set_foreground(self, hwnd: int, retries: int = 5,
                       delay: float = 0.25) -> bool:
        hwnd = int(hwnd)
        if self._user32.IsIconic(wt.HWND(hwnd)):
            self._user32.ShowWindow(wt.HWND(hwnd), _SW_RESTORE)
        else:
            self._user32.ShowWindow(wt.HWND(hwnd), _SW_SHOW)
        time.sleep(0.05)
        for attempt in range(max(1, int(retries))):
            self._user32.SetForegroundWindow(wt.HWND(hwnd))
            time.sleep(0.05)
            if int(self._user32.GetForegroundWindow() or 0) == hwnd:
                return True
            if attempt == 1:
                # Alt 键技巧：模拟 Alt 按下/抬起可绕过部分前台限制
                try:
                    self.key(0x12)  # VK_MENU
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(max(0.0, float(delay)))
        return int(self._user32.GetForegroundWindow() or 0) == hwnd

    # ── 截图 ──
    def screenshot(self, path: Path,
                   rect: Optional[Tuple[int, int, int, int]] = None) -> Optional[Path]:
        path = Path(path)
        try:
            from PIL import ImageGrab
        except Exception:  # pragma: no cover - Pillow 缺失
            return None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            img = ImageGrab.grab(bbox=tuple(rect) if rect else None, all_screens=True)
            img.save(path)
            return path
        except Exception:  # noqa: BLE001
            return None


class PyAutoGUIBackend:
    """可选 fallback：用 ``pyautogui`` 做输入，窗口查找仍走 ctypes。"""

    name = "pyautogui"

    def __init__(self) -> None:
        try:
            import pyautogui  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            raise ImportError("pyautogui 未安装（可选 fallback）") from exc
        self._pag = sys.modules["pyautogui"]
        self._win32 = Win32Backend()

    def find_window(self, titles: Sequence[str], process: str = "") -> Optional[WindowInfo]:
        return self._win32.find_window(titles, process)

    def screen_size(self) -> Tuple[int, int]:
        size = self._pag.size()
        return int(size[0]), int(size[1])

    def move(self, x: int, y: int) -> None:
        self._pag.moveTo(int(x), int(y))

    def click(self, x: int, y: int, button: str = "left", double: bool = False) -> None:
        self._pag.click(int(x), int(y), clicks=2 if double else 1, button=button)

    def drag(self, points: Sequence[Tuple[int, int]], duration: float) -> None:
        pts = list(points)
        if not pts:
            return
        self._pag.moveTo(*pts[0])
        self._pag.mouseDown()
        per = float(duration) / max(1, len(pts))
        for x, y in pts[1:]:
            self._pag.moveTo(int(x), int(y))
            time.sleep(max(0.0, per))
        self._pag.mouseUp()

    def key(self, vk: int) -> None:
        self._pag.press(chr(vk) if 32 <= vk < 127 else str(vk))

    def is_key_down(self, vk: int) -> bool:
        return self._win32.is_key_down(vk)

    def foreground(self) -> Optional[int]:
        return self._win32.foreground()

    def set_foreground(self, hwnd: int, retries: int = 5,
                       delay: float = 0.25) -> bool:
        return self._win32.set_foreground(hwnd, retries=retries, delay=delay)

    def screenshot(self, path: Path,
                   rect: Optional[Tuple[int, int, int, int]] = None) -> Optional[Path]:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            img = self._pag.screenshot(region=tuple(rect) if rect else None)
            img.save(path)
            return path
        except Exception:  # noqa: BLE001
            return None


def make_backend(*, dry_run: bool = False, prefer: str = "auto") -> InputBackend:
    """选择输入后端：``dry-run`` / ``win32`` / ``pyautogui``。"""
    if dry_run or prefer == "dry-run":
        return DryRunBackend()
    if sys.platform == "win32" and prefer in ("auto", "win32"):
        try:
            return Win32Backend()
        except Exception:  # noqa: BLE001
            pass
    if prefer in ("auto", "pyautogui"):
        try:
            return PyAutoGUIBackend()
        except Exception:  # noqa: BLE001
            pass
    return DryRunBackend()


def find_hearthstone_window(
    cfg: Optional[LiveConfig] = None,
    *,
    titles: Optional[Sequence[str]] = None,
    process: Optional[str] = None,
    backend: Optional[InputBackend] = None,
) -> Optional[WindowInfo]:
    """查找炉石窗口；找不到返回 ``None``（不抛异常）。"""
    cfg = cfg or LiveConfig()
    backend = backend or make_backend(dry_run=False)
    try:
        return backend.find_window(
            titles or cfg.window.titles,
            process if process is not None else cfg.window.process,
        )
    except Exception:  # noqa: BLE001
        return None


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(wt.ULONG)),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", wt.LONG),
        ("dwFlags", wt.DWORD),
        ("szExeFile", wt.WCHAR * 260),
    ]


def process_running(process_name: str) -> bool:
    """判断进程是否在运行（Toolhelp32 快照，不依赖 psutil/第三方库）。"""
    if not process_name or sys.platform != "win32":
        return False
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
        if snapshot in (0, -1):
            return False
        try:
            entry = _PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
            ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            wanted = process_name.lower()
            while ok:
                if str(entry.szExeFile).lower() == wanted:
                    return True
                ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
            return False
        finally:
            kernel32.CloseHandle(snapshot)
    except Exception:  # noqa: BLE001
        return False


# ══════════════════════════════════════════════════════════════════════
# 暂停控制器（F12）
# ══════════════════════════════════════════════════════════════════════


class PauseController:
    """轮询 ``GetAsyncKeyState(VK_F12)`` 实现暂停/恢复（无需键盘钩子依赖）。

    * :meth:`poll_once` 单次轮询（测试/主循环 tick 用）；
    * :meth:`start` / :meth:`stop` 后台线程版本（响应更及时）；
    * 只在"按下沿"切换，长按不会抖动。
    """

    def __init__(
        self,
        is_key_down: Callable[[int], bool],
        *,
        vk: int = VK_CODES["F12"],
        poll_s: float = 0.1,
        logger: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._is_key_down = is_key_down
        self.vk = int(vk)
        self.poll_s = float(poll_s)
        self._logger = logger
        self._paused = False
        self._down_last = False
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    @property
    def paused(self) -> bool:
        return self._paused

    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)
        if self._logger:
            self._logger("PAUSED" if self._paused else "RESUMED")

    def toggle(self) -> bool:
        self.set_paused(not self._paused)
        return self._paused

    def poll_once(self) -> bool:
        """轮询一次；返回当前是否暂停。"""
        try:
            down = bool(self._is_key_down(self.vk))
        except Exception:  # noqa: BLE001
            down = False
        if down and not self._down_last:
            self.toggle()
        self._down_last = down
        return self._paused

    def start(self) -> "PauseController":
        if self._thread is not None and self._thread.is_alive():
            return self
        self._stop.clear()

        def _loop() -> None:
            while not self._stop.is_set():
                self.poll_once()
                time.sleep(self.poll_s)

        self._thread = threading.Thread(target=_loop, name="hsbg-pause", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._thread = None


# ══════════════════════════════════════════════════════════════════════
# 输入控制器：相对坐标 → 屏幕
# ══════════════════════════════════════════════════════════════════════


class InputController:
    """相对坐标输入控制器（真实输入 / dry-run 二合一）。

    典型用法::

        ctl = InputController(config, dry_run=True)
        ctl.click(0.485, 0.374, note="menu_battlegrounds")
        ctl.drag((0.15, 0.60), (0.15, 0.48), note="shop->board")
        ctl.key("E")

    dry-run 只打印 ``[DRY] ...`` 并把操作记录到 ``self.ops``，绝不调用系统 API。
    """

    def __init__(
        self,
        config: LiveConfig,
        *,
        backend: Optional[InputBackend] = None,
        window: Optional[WindowInfo] = None,
        dry_run: bool = False,
        logger: Optional[Callable[[str], None]] = None,
        sleep_fn: Optional[Callable[[float], None]] = None,
        screenshot_dir: Optional[Path] = None,
    ) -> None:
        self.config = config
        self.dry_run = bool(dry_run)
        self.logger = logger or (lambda msg: print(msg, flush=True))
        self.ops: List[Dict[str, Any]] = []
        self._sleep = sleep_fn or time.sleep
        self.backend = backend or make_backend(dry_run=self.dry_run)
        if window is None:
            if self.dry_run:
                window = WindowInfo(
                    hwnd=0, title="dry-run", process="(none)",
                    rect=config.window_rect,
                )
            else:
                window = self.backend.find_window(
                    config.window.titles, config.window.process
                )
        if window is None:
            raise WindowNotFoundError(
                f"找不到炉石窗口（titles={config.window.titles!r}, "
                f"process={config.window.process!r}）。"
                "请先启动游戏，或使用 --dry-run。"
            )
        self.window = window
        self.pause = PauseController(
            self.backend.is_key_down,
            vk=config.flow.pause_vk,
            poll_s=config.flow.pause_poll_s,
            logger=self._log_pause,
        )
        self.screenshot_dir = (screenshot_dir
                               or config.runs_dir_resolved() / "screenshots")
        self._last_foreground_check = 0.0

    # ── 坐标 ──
    @property
    def use_client_rect(self) -> bool:
        return bool(getattr(self.config.window, "use_client_rect", True))

    @property
    def mapping_rect(self) -> Tuple[int, int, int, int]:
        """相对坐标映射用的屏幕矩形：客户区优先（游戏画面区域）。"""
        if self.use_client_rect and self.window.client_rect:
            return self.window.client_rect
        return self.window.rect

    @property
    def rect(self) -> Tuple[int, int, int, int]:
        """窗口外框（兼容旧代码；坐标映射请用 :attr:`mapping_rect`）。"""
        return self.window.rect

    @property
    def width(self) -> int:
        left, _top, right, _bottom = self.mapping_rect
        return max(0, int(right) - int(left))

    @property
    def height(self) -> int:
        _left, top, _right, bottom = self.mapping_rect
        return max(0, int(bottom) - int(top))

    def frac_to_screen(self, fx: float, fy: float) -> Tuple[int, int]:
        left, top, right, bottom = self.mapping_rect
        width, height = max(1, right - left), max(1, bottom - top)
        x = int(round(left + float(fx) * width))
        y = int(round(top + float(fy) * height))
        try:
            sw, sh = self.backend.screen_size()
        except Exception:  # noqa: BLE001
            sw, sh = (0, 0)
        if sw > 0 and sh > 0:
            x = max(0, min(int(x), sw - 1))
            y = max(0, min(int(y), sh - 1))
        return x, y

    # ── 前台 ──
    def ensure_foreground(self, *, force: bool = False) -> bool:
        """确保游戏窗口在前台；失败返回 False（调用方可跳过本次操作）。"""
        if self.dry_run:
            return True
        if not self.config.safety.allow_focus_steal and not force:
            try:
                return self.backend.foreground() == self.window.hwnd
            except Exception:  # noqa: BLE001
                return False
        try:
            if self.backend.foreground() == self.window.hwnd:
                return True
            ok = self.backend.set_foreground(
                self.window.hwnd,
                retries=self.config.window.foreground_retries,
                delay=self.config.window.restore_delay_s,
            )
            if not ok:
                self.logger(f"[wininput] 前台切换失败（hwnd={self.window.hwnd}）")
            return bool(ok)
        except Exception as exc:  # noqa: BLE001
            self.logger(f"[wininput] 前台切换异常: {exc}")
            return False

    # ── 操作 ──
    def _record(self, kind: str, **data: Any) -> Dict[str, Any]:
        op = {"kind": kind, **data, "ts": time.time()}
        self.ops.append(op)
        return op

    def _format_xy(self, fx: float, fy: float) -> str:
        sx, sy = self.frac_to_screen(fx, fy)
        return f"({fx:.3f},{fy:.3f})->({sx},{sy})"

    def move(self, fx: float, fy: float, *, note: str = "") -> Dict[str, Any]:
        sx, sy = self.frac_to_screen(fx, fy)
        op = self._record("move", fx=float(fx), fy=float(fy), x=sx, y=sy, note=note)
        if self.dry_run:
            self.logger(f"[DRY] move {note or ''} {self._format_xy(fx, fy)}".rstrip())
        else:
            self.backend.move(sx, sy)
        return op

    def click(
        self,
        fx: float,
        fy: float,
        *,
        button: str = "left",
        double: bool = False,
        note: str = "",
        ensure_foreground: bool = True,
    ) -> Dict[str, Any]:
        sx, sy = self.frac_to_screen(fx, fy)
        op = self._record("click", fx=float(fx), fy=float(fy), x=sx, y=sy,
                          button=button, double=bool(double), note=note)
        if self.dry_run:
            self.logger(f"[DRY] click {note or ''} {self._format_xy(fx, fy)}".rstrip())
            return op
        if ensure_foreground and not self.ensure_foreground():
            op["skipped"] = True
            return op
        self.backend.click(sx, sy, button=button, double=double)
        return op

    def drag(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        *,
        duration: Optional[float] = None,
        steps: int = 12,
        note: str = "",
        ensure_foreground: bool = True,
    ) -> Dict[str, Any]:
        fx1, fy1 = float(start[0]), float(start[1])
        fx2, fy2 = float(end[0]), float(end[1])
        duration = (self.config.delays.drag_duration_s
                    if duration is None else float(duration))
        pts_frac = [
            (fx1 + (fx2 - fx1) * i / max(1, steps - 1),
             fy1 + (fy2 - fy1) * i / max(1, steps - 1))
            for i in range(max(2, int(steps)))
        ]
        pts = [self.frac_to_screen(fx, fy) for fx, fy in pts_frac]
        op = self._record(
            "drag", fx1=fx1, fy1=fy1, fx2=fx2, fy2=fy2,
            start=pts[0], end=pts[-1], duration=duration, note=note,
        )
        if self.dry_run:
            self.logger(
                f"[DRY] drag {note or ''} "
                f"({fx1:.3f},{fy1:.3f})->({fx2:.3f},{fy2:.3f}) "
                f"{pts[0]}->{pts[-1]} {duration:.2f}s"
            )
            return op
        if ensure_foreground and not self.ensure_foreground():
            op["skipped"] = True
            return op
        self.backend.drag(pts, duration)
        return op

    def key(self, key: int | str, *, note: str = "",
            ensure_foreground: bool = True) -> Dict[str, Any]:
        vk = key if isinstance(key, int) else VK_CODES.get(
            str(key).upper(), ord(str(key).upper()[:1]) if str(key) else 0
        )
        op = self._record("key", vk=int(vk), key=str(key), note=note)
        if self.dry_run:
            name = f"VK_{vk:02X}"
            self.logger(f"[DRY] key {note or ''} {name}".rstrip())
            return op
        if ensure_foreground and not self.ensure_foreground():
            op["skipped"] = True
            return op
        self.backend.key(int(vk))
        return op

    def wait(self, seconds: float, *, note: str = "") -> Dict[str, Any]:
        seconds = max(0.0, float(seconds))
        op = self._record("wait", seconds=seconds, note=note)
        if self.dry_run:
            if seconds > 0:
                self.logger(f"[DRY] wait {seconds:.2f}s {note or ''}".rstrip())
            return op
        self._sleep(seconds)
        return op

    def screenshot(self, name: Optional[str] = None) -> Optional[Path]:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        filename = name or f"screenshot_{stamp}.png"
        path = self.screenshot_dir / filename
        dot = self._record("screenshot", path=str(path))
        if self.dry_run:
            self.logger(f"[DRY] screenshot -> {path}")
            return None
        return self.backend.screenshot(path, rect=self.mapping_rect)

    def poll_pause(self) -> bool:
        return self.pause.poll_once()

    def _log_pause(self, msg: str) -> None:
        self.logger(f"[pause] {msg} (VK={self.config.flow.pause_vk})")

    def close(self) -> None:
        self.pause.stop()


__all__ = [
    "VK_CODES",
    "WindowNotFoundError",
    "WindowInfo",
    "InputBackend",
    "DryRunBackend",
    "Win32Backend",
    "PyAutoGUIBackend",
    "make_backend",
    "find_hearthstone_window",
    "process_running",
    "PauseController",
    "InputController",
]
