"""``tests/`` 平台与外部数据守卫（macOS/Linux 工程可移植性）。

背景
----
HSBRSIM 的开发机是 Windows（Python 3.13），但交付/复核环境可能是 macOS/Linux。
本文件集中登记两类**先决条件不满足**的跳过规则，使项目测试在非 Windows 平台上
可完整收集、0 failed；规则在 Windows 上恒不触发，**不改变 Windows 行为**：

1. ``runs/bc/official_320/policy_bc.pt`` 缺失（``runs/`` 被 ``.gitignore`` 忽略）：
   若干 search 测试虽不测 checkpoint 加载，但会构造 ``PolicyEvaluator()``，
   其 ``__post_init__`` 必然加载默认 BC checkpoint，缺失时在 setup 阶段
   ``FileNotFoundError``（不是断言失败）。checkpoint 存在时这些用例照常执行。
2. ``DEFAULT_LOG_ROOT`` 的 WindowsPath 语义：``test_default_log_root_is_game_logs``
   断言 ``Path(r"C:\\Program Files (x86)\\Hearthstone\\Logs").name == "Logs"``，
   这只在 Windows 的 ``WindowsPath`` 成立；POSIX 的 ``PosixPath`` 把整串当作
   单个 name，属于平台语义差异，非代码缺陷。

设计原则：只跳过「平台/外部数据不满足」的用例并写明原因，不隐藏真实断言失败；
其余测试（含 checkpoint 存在时的这些用例）逻辑完全不变。基线见
``docs/PORTABILITY.md``。

注：``tests/test_live_clickbot.py`` 的平台守卫在模块内实现（其 import
``hsbg.live.launcher`` 即触发 ``ctypes.windll``，必须在收集期前跳过）；
``PolicyEvaluator`` 相关用例按 node id 精确匹配，避免整模块 skip 掩盖同文件其他用例。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: 默认 BC checkpoint（hsbg/search/evaluator.py: DEFAULT_BC_CHECKPOINT）
DEFAULT_BC_CHECKPOINT = ROOT / "runs" / "bc" / "official_320" / "policy_bc.pt"

#: 构造 PolicyEvaluator() 因而依赖默认 checkpoint 的用例（其余用例不受影响）
CHECKPOINT_GATED_TESTS = (
    "tests/test_micro_mcts.py::test_puct_select_formula",
    "tests/test_micro_mcts.py::test_width_pruning_and_budget",
    "tests/test_micro_mcts.py::test_deterministic_same_seed",
    "tests/test_micro_mcts.py::test_no_hidden_state_injection",
    "tests/test_turn_search.py::test_value_prune_final_choice_is_pairwise",
)

#: 断言 Windows 默认日志路径（WindowsPath 语义）的用例
WIN32_PATH_SEMANTICS_TESTS = (
    "tests/test_bridge_live_log.py::test_default_log_root_is_game_logs",
)

CHECKPOINT_SKIP_REASON = (
    "依赖默认 BC checkpoint runs/bc/official_320/policy_bc.pt"
    "（runs/ 被 .gitignore 忽略，本机未生成/已清理）；"
    "checkpoint 存在时（如 Windows 开发机）照常执行，见 docs/PORTABILITY.md"
)

WIN32_PATH_SKIP_REASON = (
    "断言 hsbg.bridge.live_log.DEFAULT_LOG_ROOT 的 WindowsPath 语义"
    "（C:\\Program Files (x86)\\Hearthstone\\Logs 的 .name == 'Logs'）；"
    "非 Windows 平台 PosixPath 语义不同，属平台差异，见 docs/PORTABILITY.md"
)


def _normalize(nodeid: str) -> str:
    return nodeid.replace("\\", "/")


def _matches(nodeid: str, targets: tuple[str, ...]) -> bool:
    norm = _normalize(nodeid)
    return any(norm == target or norm.endswith("/" + target) for target in targets)


def pytest_collection_modifyitems(config, items) -> None:
    """按先决条件给已收集用例补 skip 标记（不改变用例本身与 Windows 行为）。"""
    skip_markers: list[tuple[tuple[str, ...], pytest.Mark]] = []
    if not DEFAULT_BC_CHECKPOINT.is_file():
        skip_markers.append(
            (CHECKPOINT_GATED_TESTS, pytest.mark.skip(reason=CHECKPOINT_SKIP_REASON))
        )
    if sys.platform != "win32":
        skip_markers.append(
            (WIN32_PATH_SEMANTICS_TESTS, pytest.mark.skip(reason=WIN32_PATH_SKIP_REASON))
        )
    if not skip_markers:
        return
    for item in items:
        for targets, marker in skip_markers:
            if _matches(item.nodeid, targets):
                item.add_marker(marker)
                break
