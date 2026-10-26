# macOS 工程可移植性基线（PORTABILITY）

> 本文件记录 WS4 在 **macOS（Apple Silicon）** 上修复 `python3 -m pytest tests -q`
> 既有可移植性问题的基线：修复前症状、修复方式、修复后实测结果、跳过项登记与
> Windows 行为不变性论证。目标是「非 Windows 平台可完整收集、运行，0 failed；
> Windows 行为完全不变」。

## 0. 摘要

| 指标 | 修复前（2026-10-26 实测） | 修复后（2026-10-26 实测） |
|---|---|---|
| 测试收集 | **1 collection error**（`tests/test_live_clickbot.py`），整套中断 | 全部可收集，无 error |
| `python3 -m pytest tests -q` | 因收集中断，0 条用例执行 | **exit 0，0 failed** |
| 统计（`-o addopts= -q`） | 排除 clickbot 后：572 passed / 54 skipped / **6 failed** | **638 passed / 62 skipped / 0 failed**（46.7s） |
| 失败明细 | 5×BC checkpoint 缺失 + 1×Windows 路径假设 | 0 |
| 新增跳过项 | — | 7 条（5 checkpoint + 1 Windows 路径 + 1 clickbot 整模块）；另有 1 条 TavernBench 可选对拍 skip |

> 修复后数字含同轮其它 WS 新增的 `tests/conformance/*` 等用例（各 WS 并行追加中，
> 数字会随时间漂移）；WS4 自有新增为 `tests/test_tavernbench.py` 11 条
> （10 passed + 1 可选 skip；设 `AUTOTAVERN_ROOT` 时 11 passed，全量
> `639 passed / 61 skipped`）。基线数字只代表本机本次实测，不要当永久常量
> （见 `AGENTS.md` §6 门禁纪律）。

### 本机环境

| 项 | 值 |
|---|---|
| 主机 / OS | MacBookPro18,3（Apple Silicon）/ macOS 15.2（Darwin 24.2.0 arm64） |
| Python | 3.12.2（`/opt/anaconda3/bin/python3`，conda-forge） |
| pytest | 7.4.4 |
| numpy / torch | 1.26.4 / 2.2.2（CPU 版，无 CUDA；MPS 未启用） |
| 仓库 | `/Users/letiangao/HSAgent/HSBRSIM`（`master`，基线 `e84294f` + 本轮未提交改动） |

---

## 1. 修复前：3 类既有阻塞（均为工程/平台问题，非机制回归）

### 1.1 收集错误：`ctypes.windll` 只在 Windows 存在

```text
$ python3 -m pytest tests -q
ERROR collecting tests/test_live_clickbot.py
tests/test_live_clickbot.py:21: in <module>
    from hsbg.live import click_bot as cb
hsbg/live/click_bot.py:30: in <module>
    from hsbg.live.launcher import launch_hearthstone_via_battlenet
hsbg/live/launcher.py:20: in <module>
    _user32 = ctypes.windll.user32
E   AttributeError: module 'ctypes' has no attribute 'windll'
!!! Interrupted: 1 error during collection !!!
```

`hsbg/live/launcher.py` 在**模块级**调用 `ctypes.windll.user32`（Windows API），
而 `hsbg/live/__init__.py` 无惰性导入；只要收集 `test_live_clickbot.py` 就必然
触发 import 链失败，导致 **整套测试在收集阶段中断（一条用例都不跑）**。

### 1.2 失败：5 个用例依赖已清理的 BC checkpoint

```text
$ python3 -m pytest tests -q --ignore=tests/test_live_clickbot.py
FAILED tests/test_micro_mcts.py::test_puct_select_formula - FileNotFoundError
FAILED tests/test_micro_mcts.py::test_width_pruning_and_budget - FileNotFoundError
FAILED tests/test_micro_mcts.py::test_deterministic_same_seed - FileNotFoundError
FAILED tests/test_micro_mcts.py::test_no_hidden_state_injection - FileNotFoundError
FAILED tests/test_turn_search.py::test_value_prune_final_choice_is_pairwise - FileNotFoundError
E   FileNotFoundError: [Errno 2] No such file or directory: 'runs/bc/official_320/policy_bc.pt'
```

根因：这些用例并不测 checkpoint 加载，但会构造 `PolicyEvaluator()`
（`hsbg/search/evaluator.py`），其 `__post_init__` **总是**加载默认 BC
checkpoint `runs/bc/official_320/policy_bc.pt`；`runs/` 被 `.gitignore` 忽略，
开发机数据清理后即缺失。注意 `MicroMCTS(cfg, evaluator=None)` 内部是
`evaluator or PolicyEvaluator()`，所以 `evaluator=None` 也会触发加载。

### 1.3 失败：1 个 Windows 路径语义断言

```text
$ python3 -m pytest tests/test_bridge_live_log.py::test_default_log_root_is_game_logs
E   AssertionError: assert 'C:\\Program Files (x86)\\Hearthstone\\Logs' == 'Logs'
```

`hsbg/bridge/live_log.py` 的 `DEFAULT_LOG_ROOT = Path(r"C:\Program Files (x86)\Hearthstone\Logs")`
是 Windows 常量；测试断言 `DEFAULT_LOG_ROOT.name == "Logs"`，这只在 Windows 的
`WindowsPath` 成立——POSIX 的 `PosixPath` 把整串当作单个 `name`。属平台语义差异，
不是代码缺陷（该默认路径在 macOS 上本来就不适用，使用时需显式传 `log_root`）。

### 1.4 环境敏感项（**不属于**本次修复范围，不 skip）

`tests/test_policy_model.py::test_forward_latency_batch64` 是**性能断言**
（CPU batch=64 forward 中位数 < 50ms，按 RTX 机器 ~20ms 设定）。本机多 agent
并发压测（load average 100+）时实测 96–133ms 会抖红；空载复测 **34.9ms 通过**。
按门禁纪律「不得放宽/删除真实断言」，**不 skip、不放宽**，仅记录为并发负载敏感项。

---

## 2. 修复内容（2 个文件）

### 2.1 `tests/test_live_clickbot.py`：模块级平台守卫

在 docstring/`__future__` 之后、`hsbg.*` import **之前**：

```python
import sys
import pytest

if sys.platform != "win32":
    pytest.skip(
        "hsbg.live.click_bot 依赖 Windows API（ctypes.windll / Win32 SendInput），"
        "非 Windows 平台按设计跳过；Windows 上照常执行",
        allow_module_level=True,
    )
```

- 非 Windows：模块整体记为 **1 条 skip**（28 个用例的执行语义不重写），不再
  collection error；
- Windows：`sys.platform == "win32"` → 守卫不触发，28 个用例**原样全部执行**。

### 2.2 `tests/conftest.py`（新增）：集中登记平台/先决条件守卫

用 `pytest_collection_modifyitems` 按 **精确 node id** 给已收集用例补 `skip` 标记，
条件不满足才生效：

```python
DEFAULT_BC_CHECKPOINT = ROOT / "runs" / "bc" / "official_320" / "policy_bc.pt"

CHECKPOINT_GATED_TESTS = (
    "tests/test_micro_mcts.py::test_puct_select_formula",
    "tests/test_micro_mcts.py::test_width_pruning_and_budget",
    "tests/test_micro_mcts.py::test_deterministic_same_seed",
    "tests/test_micro_mcts.py::test_no_hidden_state_injection",
    "tests/test_turn_search.py::test_value_prune_final_choice_is_pairwise",
)
WIN32_PATH_SEMANTICS_TESTS = (
    "tests/test_bridge_live_log.py::test_default_log_root_is_game_logs",
)
```

| 守卫 | 触发条件 | Windows 上是否触发 |
|---|---|---|
| BC checkpoint 用例（5 条） | `not runs/bc/official_320/policy_bc.pt` | 否（Windows 开发机有该 checkpoint，5 条照常执行） |
| Windows 路径断言（1 条） | `sys.platform != "win32"` | 否 |

**为什么用 conftest 而不在各测试文件里加 `pytest.mark.skipif`？**

1. WS4 写范围只含 `tests/conftest.py`、`tests/test_live_clickbot.py`，
   `tests/test_micro_mcts.py` / `tests/test_turn_search.py` / `tests/test_bridge_live_log.py`
   属其它 owner，不能并行修改（`AGENTS.md` §4 写权限、同一文件单 writer）；
2. conftest 是仓库级统一平台守卫位（任务书也允许「新增 `tests/conftest.py`
   统一平台守卫」），条件与理由集中可审计；
3. 语义等价于 `@pytest.mark.skipif(not Path(...).exists(), reason=...)`：
   **只在先决条件缺失时跳过**，且 skip 原因写明数据来源与恢复方式。

**不会静默掩盖漂移**：node id 精确匹配；若上游测试被改名/移动，守卫不再命中，
用例会回到原本的 `FileNotFoundError` 显式失败（而不是被悄悄跳过），便于发现。

### 2.3 未改动的东西（Windows 行为不变性）

- 未改 `hsrl2/**`、`hsbg/**`、根配置、`pyproject.toml`；未改其它测试文件；
- 未删测试、未放宽断言、未改任何业务逻辑；
- 所有新增 skip 条件在 Windows 开发机（`sys.platform == "win32"` + checkpoint 存在）
  恒为 False → `python -m pytest tests -q` 在 Windows 上的执行集合与断言完全不变。

---

## 3. 修复后实测基线

### 3.1 命令与输出（2026-10-26，本机）

```text
$ cd /Users/letiangao/HSAgent/HSBRSIM
$ python3 -m pytest tests -q
（2026-10-26 11:28 exit 0；`-q` 与 pyproject `addopts=-q` 叠加为 -qq，
 不打印汇总行，但无 FAILED/ERROR）

$ python3 -m pytest tests -o addopts= -q -rs
638 passed, 62 skipped in 46.70s         # 2026-10-26 11:28，AUTOTAVERN_ROOT 未设
$ AUTOTAVERN_ROOT=/Users/letiangao/HSAgent/repos/AutoTavern \
      python3 -m pytest tests -o addopts= -q -rs
639 passed, 61 skipped in 48.96s         # 2026-10-26 11:22，含现场对拍
```

WS4 自有测试：

```text
$ python3 -m pytest tests/test_tavernbench.py -q
10 passed, 1 skipped                      # 1 skip = 未设 AUTOTAVERN_ROOT 时的可选对拍
$ AUTOTAVERN_ROOT=/Users/letiangao/HSAgent/repos/AutoTavern \
      python3 -m pytest tests/test_tavernbench.py -q
11 passed
$ python3 scripts/run_tavernbench.py --check
CHECK PASSED: 26/26 项通过
```

### 3.2 新增跳过项登记（全部写明原因，可审计）

| # | node id / 模块 | 跳过条件 | Windows 是否执行 | 原因 |
|---|---|---|---|---|
| 1 | `tests/test_live_clickbot.py`（整模块，28 用例） | `sys.platform != "win32"` | ✅ 执行 | 依赖 `ctypes.windll` / Win32 SendInput，非 Windows 无此 API |
| 2 | `tests/test_micro_mcts.py::test_puct_select_formula` | checkpoint 缺失 | ✅ 执行 | 构造 `PolicyEvaluator()` 需默认 BC checkpoint |
| 3 | `tests/test_micro_mcts.py::test_width_pruning_and_budget` | checkpoint 缺失 | ✅ 执行 | 同上 |
| 4 | `tests/test_micro_mcts.py::test_deterministic_same_seed` | checkpoint 缺失 | ✅ 执行 | 同上 |
| 5 | `tests/test_micro_mcts.py::test_no_hidden_state_injection` | checkpoint 缺失 | ✅ 执行 | 同上 |
| 6 | `tests/test_turn_search.py::test_value_prune_final_choice_is_pairwise` | checkpoint 缺失 | ✅ 执行 | 构造 `PolicyEvaluator()` 需默认 BC checkpoint |
| 7 | `tests/test_bridge_live_log.py::test_default_log_root_is_game_logs` | `sys.platform != "win32"` | ✅ 执行 | 断言 WindowsPath 语义（见 §1.3） |
| 8 | `tests/test_tavernbench.py::test_upstream_repo_parity_live` | 未设 `AUTOTAVERN_ROOT` | 视环境 | 可选：需本机 AutoTavern checkout 现场对拍；无 checkout 时用已 pin 的 golden 对拍（默认覆盖） |

> `python3 -m pytest tests -q` 的 skipped 计数按**测试项**统计：clickbot 整模块
> 在 pytest 里记为 1 条 skip（而非 28 条），因此新增 skip 数是 7（表 1–7）。

### 3.3 恢复被 skip 的 checkpoint 用例

`runs/` 被 `.gitignore` 忽略、checkpoint 不入库。需要在本机执行那 5 条用例时：

- 从 Windows 开发机拷贝 `runs/bc/official_320/policy_bc.pt`；或
- 按 [`docs/TRAINING.md`](TRAINING.md) 的 BC 训练命令重新生成到
  `runs/bc/official_320/`（`scripts/train_bc.py`，产物 `policy_bc.pt`）。

文件出现后无需改任何代码：`tests/conftest.py` 的守卫条件自动失效，5 条用例恢复执行。

---

## 4. 复现/验收命令

```bash
cd /Users/letiangao/HSAgent/HSBRSIM

# 1) 零失败（macOS；skip 见 §3.2 登记表）
python3 -m pytest tests -q; echo "rc=$?"

# 2) 看完整统计与跳过原因
python3 -m pytest tests -o addopts= -q -rs

# 3) 可选：启用 TavernBench 与原仓库现场对拍
AUTOTAVERN_ROOT=/path/to/AutoTavern python3 -m pytest tests -o addopts= -q

# 4) TavernBench 自身验收
python3 scripts/run_tavernbench.py --check
python3 -m pytest tests/test_tavernbench.py -q
```

## 5. 已知限制

- 本文件是**本机一次性实测基线**（macOS 15.2 / Py3.12.2）；换机器/换依赖版本
  请重新记录（命令、时间、passed/skipped/failed、耗时），不要把数字当常量。
- 多 agent 并发压测（其它 WS 的 rustc/pytest 任务）时，个别与本 WS 无关的用例
  可能因 CPU 争用抖动（已观察到 `test_forward_latency_batch64` 在 load average > 100
  时段抖红，空载 34.9ms 通过）；本 WS 的验收数字取空载（load average < 15）实测。
  按门禁纪律，不通过 skip/xfail 掩盖这类抖动。
- 另发现一个**与本 WS 无关的既有非确定性失败**（已上报 Lead，属 env/agents 层）：
  `tests/test_env_coverage.py::TestTerminationContract::test_self_elimination_terminates_replay_seed24`
  在本机随机复现（`PYTHONHASHSEED=0` 固定 8/8 通过；不固定 hash seed 时 8 次中 1 次失败，
  `AssertionError: unexpected early terminal`）。这不是平台/checkpoint 问题，
  本 WS 未修改该测试或 `hsbg/env/**`，也未用 skip 掩盖；需 env-builder/Lead 处理。
- 本 WS 只修复「收集/先决条件/平台语义」三类工程问题；机制/策略层失败仍需
  按 `docs/AUDIT_PROTOCOL.md` 处理。
