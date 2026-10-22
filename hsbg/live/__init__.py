"""``hsbg/live`` —— 自动化代打采集（Windows 输入 + 状态机 + 日志/内存状态）。

模块划分
--------
* :mod:`hsbg.live.config`      —— `config.json` 数据类：窗口/坐标比例/节奏/路径/安全项
* :mod:`hsbg.live.wininput`    —— Win32 输入层（找窗口、DPI、相对坐标点击/拖拽/按键、
                                 前台管理、F12 暂停、截图、dry-run）
* :mod:`hsbg.live.logwatch`    —— 实时``Power.log``/HDT 日志 watcher（会话/game/phase/turn）；
                                 优先接入 ``hsbg.bridge.live_log``（若已就绪）
* :mod:`hsbg.live.memory_state`—— 可选 ``tools.live_state_mem.read_live_state()`` 适配
* :mod:`hsbg.live.planner`     —— 纯状态机：``LiveSnapshot (+ memory) -> List[PlannedAction]``
* :mod:`hsbg.live.runner`      —— 对局主循环：记录 JSONL、错误截图、暂停、局数统计

约束
----
* 本 package 只做"输入 + 观测 + 状态机"，**不**改引擎/环境核心；
* 默认 **dry-run**：只打印计划，只有显式 ``--live`` / ``LiveBot(live=True)`` 才真正点击；
* ``pyautogui`` / ``hsbg.bridge.live_log`` / ``tools.live_state_mem`` 均为可选依赖，
  缺失时自动降级（见各模块 docstring），保证无游戏/无日志环境也能跑测试与 dry-run。
"""

from __future__ import annotations

from typing import Any

from hsbg.live.config import (
    DEFAULT_CONFIG_PATH,
    CoordsConfig,
    DelaysConfig,
    FlowConfig,
    LiveConfig,
    PathsConfig,
    SafetyConfig,
    WindowConfig,
    load_config,
    save_config,
)
from hsbg.live.planner import PlannedAction, Planner, plan_once
from hsbg.live.runner import LiveBot, RunSummary

#: 惰性导出（Win32 相关模块只在真正使用时导入；无 Windows 也能 import 本包）
_LAZY_EXPORTS = {
    "InputController": "hsbg.live.wininput",
    "WindowInfo": "hsbg.live.wininput",
    "Win32Backend": "hsbg.live.wininput",
    "DryRunBackend": "hsbg.live.wininput",
    "PauseController": "hsbg.live.wininput",
    "find_hearthstone_window": "hsbg.live.wininput",
    "PowerLogWatcher": "hsbg.live.logwatch",
    "LiveSnapshot": "hsbg.live.logwatch",
    "create_watcher": "hsbg.live.logwatch",
    "load_memory_reader": "hsbg.live.memory_state",
    "read_memory_state": "hsbg.live.memory_state",
}

__all__ = [
    # config
    "LiveConfig",
    "WindowConfig",
    "PathsConfig",
    "FlowConfig",
    "DelaysConfig",
    "CoordsConfig",
    "SafetyConfig",
    "DEFAULT_CONFIG_PATH",
    "load_config",
    "save_config",
    # planner/runner
    "PlannedAction",
    "Planner",
    "plan_once",
    "LiveBot",
    "RunSummary",
    # wininput / logwatch / memory（惰性）
    "InputController",
    "WindowInfo",
    "Win32Backend",
    "DryRunBackend",
    "PauseController",
    "find_hearthstone_window",
    "PowerLogWatcher",
    "LiveSnapshot",
    "create_watcher",
    "load_memory_reader",
    "read_memory_state",
]


def __getattr__(name: str) -> Any:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:  # pragma: no cover
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
