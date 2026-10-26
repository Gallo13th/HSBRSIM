# PERF_ROUTE — Rust / Python / C 性能路线实测与迁移建议（P2-E）

> 任务：`task-14`（WS5 之后的 P2 阶段：运算效率路线决策，60 分钟时间盒）。
> 脚本：`tools/p2_perf/`（全部可复现）；原始数据：`runs/p2_perf/*.json`（gitignore）。
> 参照项目数据：`docs/TAVERNGYM_BACKEND.md` §8（2026-10-26 早先一次实测：
> TavernGym 裸引擎 275 games/s、features 解码 175 µs/步、端到端 33.9 games/s）。

---

## 0. 一句话结论（可直接用于决策）

1. **引擎层迁移 Rust 的收益是数量级的**：同一台机器、同一口径下，Rust
   TavernGym 裸引擎 **252.9 games/s（3.95 ms/局）**，Python hsrl2 环境整局
   **5.18 games/s（193.0 ms/局，random）/ 3.26 games/s（307.2 ms/局，heuristic）**
   → **裸引擎约 49×**、TavernGym 经 Python 适配层后约 34 games/s（docs §8）→ 对 hsrl2 约 5–7×（后者差距被环境层/观测/对手策略部分摊薄）。
   **建议：引擎 = Rust（fork AutoTavern 为主引擎）**，与用户 P2 决策一致。
2. **TavernGym 端到端瓶颈已不在 Rust 引擎，而在 Python 观测解码**：
   `TavernGymEnv.step` 平均 **270.0 µs**，其中 `_build_observation`
   **211.4 µs（78.3%）**；引擎推进 + bot 驱动余量仅 **20.6 µs（7.6%）**。
   若要继续提速，应把观测/动作适配**下沉 Rust PyO3**（或 numpy 向量化到
   ~20 µs/步，见 `docs/TAVERNGYM_BACKEND.md` §11），而不是继续优化 Python 循环。
3. **C 加速（零改造）实测没有收益**：Cython 纯 Python 模式编译真实模块，
   3 个热函数加速比 **1.01× / 1.02× / 0.95×**（`entity_token` /
   `build_observation` / `model.clone`）；mypyc 需要类型标注改造且当前模块
   不满足（实测编译报类型错误）。**建议：C 不作为主路线**；仅在「不迁移
   Rust 的旧 Python 后端」或「孤立数值 kernel（批量特征打包/战斗数学）」场景
   才考虑 C 扩展/有类型 Cython，且预期收益主要来自数据布局改造而非编译。
4. **迁移优先级**：① 引擎 Rust（P0）→ ② 观测/动作适配 Rust PyO3 或
   numpy 向量化（P1）→ ③ Python 侧保留「参照后端/测试/差分 oracle」（P2）；
   C 扩展列为可选/不建议（P3）。

---

## 1. 方法、硬件与复现命令

### 1.1 硬件与软件

| 项 | 值 |
|---|---|
| CPU | Apple M1 Pro（arm64, macOS 15.2） |
| Python | 3.12.2（`/opt/anaconda3/bin/python3`） |
| Rust 后端 | taverngym 1.0.0（`profile=release`，PyO3/abi3；game 36.6.3.253932） |
| Python 后端 | hsrl2（vendored，数据 37.0.0.255130） |
| C 工具链 | Apple clang 16.0.0；Cython 3.3.0（`pip install --target /tmp`，**不写项目依赖**）；mypy/mypyc 已装 |

> 本机同时存在其它 agent 进程负载，数字会有波动；下文均给 seed/局数/迭代数，
> 且脚本可复算。同一工作树两次 `run_all.py` 复跑：TavernGym 裸引擎
> 227.6 → 252.9 games/s（±10%）、hsrl2 random 4.93 → 5.18 games/s；
> **以 `runs/p2_perf/*.json` 为准**，不影响量级/路线结论。

### 1.2 复现命令

```bash
cd /Users/letiangao/HSAgent/HSBRSIM
PYTHONPATH=. python3 tools/p2_perf/run_all.py          # 全部三组基准
# 或分开：
PYTHONPATH=. python3 tools/p2_perf/bench_engine.py --hsrl2-games 8 --engine-games 500
PYTHONPATH=. python3 tools/p2_perf/bench_e2e.py --steps 300
PYTHONPATH=. python3 tools/p2_perf/bench_c_accel.py --iters 1000 --clone-iters 1000
# 输出: runs/p2_perf/{engine,e2e_breakdown,c_accel}.json
```

### 1.3 口径说明（重要）

* **引擎裸吞吐**（taverngym `run_bot_games`）：8 座全 bot、Rust 内部执行、
  GIL 释放；**不含** Python 观测/策略/环境层——衡量"引擎本身"。
* **hsrl2 整局**：`BattlegroundsEnv` + `hsbg.rl.policies`（random/heuristic）
  + 统一 `hsbg.rl.api.run_episode`；**含** Python 引擎模拟、每步观测构建、
  对手启发式招募、奖励计算——衡量"Python 全栈"。
* **端到端步进分解**：同一 harness（随机 legal 动作、8 人局、相同 seed/步数），
  用函数级累加计时器包裹环节；**wrapping 开销 ~0.1 µs/调用**，占比可忽略。
  hsrl2 的 `step` 同时包含招募步（~0.3–0.5 ms）与 `end_turn` 整回合
  （~17–22 ms，含 7 名对手招募 + 战斗 + EoT），所以**均值被 end_turn 拉高**，
  文档同时给 median 与按类拆分。
* C 微基准：真实模块**原样复制**到 `/tmp` 用 Cython 纯 Python 模式编译
  （无类型标注改动）→ 同输入对比；因此得到的是**"零改造"的 C 加速上限**。
  有类型/数据布局改造的 C 扩展需另算（见 §4.3）。

---

## 2. 数据表 A：引擎批量吞吐（8 人局，seed=0）

| 系统 | 模式 | games/s | ms/局 | ms/步 | 平均步/局 | 平均回合 |
|---|---|---:|---:|---:|---:|---:|
| **TavernGym（Rust）** | 裸引擎 `run_bot_games(500)`（8 bot，无观测） | **252.87** | **3.95** | — | — | 15.4 |
| **TavernGym BatchEnv** | 32 局，threads=1：observe+step 循环 | 761.0 cycles/s | — | 41.1 µs/slot-step | — | — |
| **TavernGym BatchEnv** | 32 局，threads=4 | 748.3 cycles/s（≈1.0×，负载波动） | — | 41.8 µs/slot-step | — | — |
| **hsrl2（Python 引擎 + env）** | random 策略整局 | **5.18** | **193.02** | **4.00** | 48.3 | 7.3 |
| **hsrl2（Python 引擎 + env）** | heuristic 策略整局 | **3.26** | **307.25** | **2.64** | 116.5 | 9.8 |

**归因**：Rust 裸引擎比 hsrl2 全栈快 **~49×（games/s）**；而 TavernGym 经
Python 适配层（`TavernGymEnv`，features 观测）后，端到端只有
**~34 games/s**（docs §8 口径）/ 本次步进基准 **~1/270 µs ≈ 3.7k steps/s**
——即 **Rust 引擎的裸吞吐优势在 Python 边界上被吃掉了一个数量级**。
BatchEnv threads 1→4 本次约 1.0×（早先一次 1.22×；受并行负载影响）：numpy 打包/解包与 Python 调度是边界成本，
Rust 内部线程（`run_bot_games` 已 GIL 释放）才是主要并行来源。

---

## 3. 数据表 B：端到端 RL 步进开销分解

### 3.1 TavernGym 后端（`hsbg.backends.TavernGymEnv`，obs_source=features）

300 步随机 legal 动作：

| 环节 | µs/步 | 占 step | 调用中位 µs | 说明 |
|---|---:|---:|---:|---|
| `env.step` 总 | **270.0**（median 247.6, p99 697.5） | 100% | — | 含 obs+引擎+bot 驱动+reward |
| `_build_observation`（观测解码） | **211.4** | **78.3%** | 214.1 | `observe()` features/cards → EntityToken/候选 |
| `_make_info` | 26.5 | 9.8% | 24.6 | info/extra 字典构建 |
| `_advance`（驱动 bot，Python 调度） | 10.5 | 3.9% | 1.5 | Rust 侧执行，Python 循环调用 |
| `_resolve_candidate` | 0.5 | 0.2% | 0.5 | 候选→扁平动作下标 |
| `_note_candidates` | 0.5 | 0.2% | 0.5 | 统计 |
| **引擎推进 + bot 驱动余量（推断）** | **20.6** | **7.6%** | — | `game.step` 是 PyO3 只读属性无法直接包裹 → 用余量估计；Rust 引擎很快 |

> 与 docs §8.4 一致：features 解码 ~175–230 µs/步是端到端最大项；
> **Rust 引擎本身不是瓶颈**（<35 µs/步，含 bot）。

### 3.2 hsrl2 后端（`BattlegroundsEnv`，opponent=heuristic）

300 步随机 legal 动作（24 动作后终局；7 个 end_turn）：

| 环节 | µs/步（均值） | 说明 |
|---|---:|---|
| `env.step` 总 | **5393.6**（median 430.4, p99 29585.0） | 均值被 end_turn 拉高 |
| — recruit 步（17 步） | mean **446.5** / median **309.6** / p99 1875.7 | 单招生/买/打牌等 |
| — end_turn 步（7 步） | mean **17408** / median **17064** / p99 29585 | 对手招募+战斗+EoT+下一回合 |
| `build_observation` | 159.3 | 招募步内约 1/3 时间 |
| `build_extra_state`（含在 obs 内） | 50.1 | 观测 v2 extra 构建 |
| `enumerate_step`（候选枚举） | 51.9 | |
| `collect_zones` | 60.4 | |
| `apply_action` | 1564.9 | 嵌套在 `drive_opponents`/end_turn 中，**不重复计入占比** |
| `drive_opponents`（7 名启发式对手招募） | 2404.9 | call median 6.4 ms/次（每次 end_turn） |
| `drain_choices` | 64.3 | EoT/战斗/发现选择结算 |

**归因**：hsrl2 的端到端瓶颈是 **Python 引擎模拟本身**（对手招募 + 战斗 +
EoT 都在 Python 对象上逐步执行），单步环境层（obs+枚举+apply）只有
~0.2–0.4 ms；Rust 迁移直接消掉主要成本（§2 的 ~49× 裸引擎差距）。

---

## 4. 数据表 C：C 加速可行性（真实热函数 vs Cython 编译版）

Cython 3.3.0 以 `pip install --target /tmp/p2_perf_cython` 临时安装（**未写入
项目依赖**）；把 `hsbg/env/observation.py`、`hsbg/planning/model.py` **原样复制**
为 `.pyx`，`pyximport` 纯 Python 模式编译（无任何类型标注改动）。

| 热函数 | 工作负载 | Python median | Cython median | 加速比 | p99（py → cy） |
|---|---|---:|---:|---:|---:|
| `observation.entity_token` | 40 个真实实体各构 token（1 iter） | 731.1 µs | 724.8 µs | **1.01×** | 1416 → 1345 µs |
| `observation.build_observation` | 8 人局中局整步观测 | 125.5 µs | 123.0 µs | **1.02×** | 245 → 265 µs |
| `planning.model.clone` | 8 人局中局深拷贝 | 2886.0 µs | 3043.5 µs | **0.95×** | 16548 → 20069 µs |

* 1000 次微基准（clone 1000 次；warmup 20 次；median/p99 见上）；Cython 版输出
  与纯 Python **逐字段相等**（脚本内 assert）。
* 结论：**零改造的 Cython 编译没有收益**（0.95–1.02×，处于噪声区间）。这 3 个函数的时间
  几乎全在 **Python 对象/属性/字典访问**上——Cython 纯 Python 模式只是把
  字节码编译成 C，无法消除 PyObject 操作开销；clone 的递归派发同理。
* **mypyc 尝试失败**（记录原因，不强行实现）：
  `python -m mypyc --ignore-missing-imports p2_observation_mypyc.py` →
  `error: Argument 1 to "dict" has incompatible type "dict[str, Any] | None"; expected "SupportsKeysAndGetItem[str, Any]" [arg-type]`。
  结论：**mypyc 需要先把模块类型注解完整化并修复类型错误**（observation.py
  已至少有 1 处静态类型不满足），改造成本高、需持续维护注解；对本项目后续
  要迁移 Rust 的路线不划算。

### 4.1 Amdahl 上限（若"有类型 C 扩展"能到 2×/10×）

端到端加速上限 `1/(1-f+f/s)`：

| 环节占比 f | s=2× | s=10× |
|---|---:|---:|
| 25% | 1.14× | 1.08× |
| 50% | 1.33× | 1.43× |
| 78%（TavernGym obs 解码） | 1.56× | 3.36× |

即使把 TavernGym 观测解码用 C/Rust 加速 10×，端到端也只能到 ~3.4×
（270 µs → ~81 µs/步）；而**把解码直接搬到 Rust 扩展/上游引擎**可同时消掉
Python 边界（`observe()` 拷贝、EntityToken 构造、numpy 打包），实际收益更高
（docs §11 预估 numpy 向量化 ~20 µs/步 → 端到端 ~3.5–4×）。

### 4.2 定性评估"下沉 Rust PyO3"的收益

* `build_observation` 的输入（features/cards/mask）与输出（EntityToken/
  CandidateAction）都是**定长数值 + 简单结构** → 适合 Rust 侧直接产出
  numpy/结构化数组，边界成本一次性摊薄；
* 引擎已在 Rust：观测/动作适配下沉可复用同一进程、避免 Python↔Rust 数据
  往返（TavernGym 现在每步要 `observe()` 拷 3227 f32 + 124 i32 + mask 再
  逐 token Python 解码）；
* 预计端到端 **3–4×**（obs 解码 175–234 µs → ≤30 µs），且随批量摊薄更明显；
* 备选低成本方案：**numpy 向量化解码**（docs §11 预估 ~20 µs/步），
  无需 Rust 改动、可作为过渡。

### 4.3 若坚持 C 扩展：哪些环节才可能值得

| 候选 | 可行性 | 预估 | 备注 |
|---|---|---|---|
| 批量特征打包（token→numpy 固定槽位） | 中 | 3–10×（仅该 kernel） | 需改数据布局（SoA）；本质与"Rust 侧直出"重复 |
| 战斗数学（整数/浮点小循环） | 中 | 2–5× | 只占 hsrl2 整局小头；Rust 引擎已覆盖 |
| `model.clone` / obs 构建（对象图） | 低 | ~1.0× | 实测；PyObject 主导，C 无法消除 |
| 引擎模拟整体 | 低（不现实） | — | 等于重写引擎；Rust 已实现，重复投入 |

**C 路线结论：不建议作为主路线**；仅当"旧 Python 后端必须保留且观测打包成为
采集瓶颈"时，考虑有类型 Cython/C 扩展做单一 kernel（先做 numpy 向量化对照）。

---

## 5. 结论矩阵（环节 → 当前耗时 → Rust 可替代性 → C 实测/预估 → 建议）

| 环节 | 当前耗时（实测） | Rust 可替代性 | C 加速实测/预估 | 建议 |
|---|---|---|---|---|
| 引擎模拟（整局） | hsrl2 193.0 ms/局（random）；Rust 裸引擎 3.95 ms/局 | **高（已实现，~49×）** | 不现实（需重写） | **Rust 主引擎（P0）** |
| 对手招募/战斗/EoT | hsrl2 end_turn mean 17.4 ms（占整局绝大头） | 高（Rust 引擎已含） | 不现实 | 随引擎迁移 |
| 观测构建（TavernGym features 解码） | 211.4 µs/步（78%） | **高（下沉 PyO3/上游直出）** | 0.98–1.00×（Cython 零改造）；numpy 预估 ~20 µs | **Rust PyO3 / numpy 向量化（P1）** |
| 观测构建（hsrl2 `build_observation`） | 159.3 µs/步 | 中（若保留 Python 引擎） | 1.00×（Cython 实测） | 保留 Python（参照后端），不单独优化 |
| 动作枚举（hsrl2 `enumerate_step`） | 51.9 µs/步 | 中（Rust 引擎为固定 245 维 mask + legal_mask 0.6 µs） | — | Rust 后自然解决 |
| 状态快照/深拷贝（`model.clone`） | 2.89 ms/次（中局） | 中（Rust `state_json/from_json` 精确存档已可用） | 0.98× | 用 Rust 存档；Python 侧保留 snapshot 测试 |
| Python 环境/奖励/记账 | ~0.2–0.4 ms/步（hsrl2 recruit median 309.6 µs） | 低（薄层） | ~1.0× | 保留 Python（训练胶水） |
| 并行采样 | BatchEnv threads1→4 ~1.0–1.22×（负载相关） | 高（Rust 内部 Rayon/GIL 释放） | — | Rust 侧批处理（已有 `run_bot_games`/BatchEnv） |

---

## 6. 最终建议（迁移优先级）

1. **P0 — 引擎 = Rust（fork AutoTavern/taverngym 为 hsbg_engine 主引擎）**。
   证据：裸引擎 252.9 vs 5.18 games/s（~49×）、3.95 vs 193.0 ms/局；这是
   量级差异、且 Rust 侧已有精确存档/固定动作 mask/批量环境。
   前置：数据版本 36.6.3→37.0.0 迁移 + 机制对齐（WS2 conformance 台账）、
   卡池/机制差异登记。
2. **P1 — 观测/动作适配层下沉 Rust PyO3（或先 numpy 向量化）**。
   证据：TavernGym 端到端 78% 在 Python obs 解码（211 µs/步），Rust 引擎
   本体只占 ~8%；目标 ≤30 µs/步 → 端到端 ~3–4×，并让 Rust 批处理收益
   真正传导到训练采样。
3. **P1' — 保留 Python 侧为参照/测试/oracle**：hsrl2 引擎、snapshot/
   invariants、差分测试继续保留（机制权威 + 回归门禁），不追求其运行速度。
4. **P2 — 训练/评测胶水保留 Python**（reward、日志、checkpoint；薄层）。
5. **P3 — C 扩展仅可选**：若旧 Python 后端仍需采集且 numpy 向量化不足，
   对"批量特征打包"单点做有类型 Cython/C；不建议把 C 作为引擎或观测
   主路线（实测零改造 0.98–1.00×，mypyc 需类型化改造）。

**TODO（时间盒内未覆盖，需后续补测）**：
* TavernGym `BatchEnv` 的**完整对局吞吐**（本轮只测 observe+step 循环的
  cycles/s；`run_bot_games` 已给引擎裸吞吐）；
* Rust 侧观测直出（PyO3）原型与 numpy 向量化解码的实测对比（本轮只有
  docs 预估 ~20 µs/步）；
* hsrl2 在**启发式 agent** 下的逐环节分解（本轮 hsrl2 分解用随机动作驱动，
  end_turn 步占比 7/24；heuristic 整局 124.8 步，分布不同）；
* 多机/空载复测（本轮有其它 agent 进程并行，数字偏保守）。

---

## 7. 产物索引

| 文件 | 内容 |
|---|---|
| `tools/p2_perf/common.py` | 硬件/统计/JSON 工具 |
| `tools/p2_perf/bench_engine.py` | 数据表 A（引擎批量吞吐 + BatchEnv） |
| `tools/p2_perf/bench_e2e.py` | 数据表 B（step 环节分解；hsrl2 / TavernGym） |
| `tools/p2_perf/bench_c_accel.py` | 数据表 C（Cython/mypyc 微基准 + Amdahl） |
| `tools/p2_perf/run_all.py` | 一键复跑三组基准 |
| `runs/p2_perf/engine.json` | 数据表 A 原始数据（含机器信息/命令口径） |
| `runs/p2_perf/e2e_breakdown.json` | 数据表 B 原始数据 |
| `runs/p2_perf/c_accel.json` | 数据表 C 原始数据（含 Cython/mypyc 安装/编译记录） |
