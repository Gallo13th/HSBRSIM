# RUST_ENGINE.md — HSbg Engine（HSBRSIM 主 Rust 引擎）

> 状态：**第二阶段主引擎，已 vendor + 构建 + 验证**（2026-10-26）。
> 代码：`rust/`（workspace：`crates/hsbg-engine`、`crates/hsbg-engine-py`、
> `python/hsbg_engine`）；fork 说明：`rust/FORK.md`；测试：`tests/test_rust_engine.py`；
> 基准脚本：`rust/bench_engine.py`。
> 数据：**37.0.0.255130 最终版（2026-10-26 已集成，sha256 `c4826127…`）**，来源
> `data/p2/cards_37.json`（`gen_carddb_37.py` v1.1.0：37 官方映射 + 36.6.3 compat
> + AT 机制元数据继承 + Dark Paradox 5 形态映射；单人池 minion **277** / hero 118 /
> spell 73 / trinket 236）。替换步骤与约束见 `rust/FORK.md` §5，换数据后
> `pip install -e .` 重建即可，引擎代码不动。
> 本文所有数字均为**本机一次实测**（macOS Apple Silicon，§7），不是抄来的。

---

## 1. 定位：为什么把 TavernGym vendor 成主引擎

HSBRSIM 第一阶段是双引擎：机制精度权威是 vendored 的 Python 引擎 `hsrl2`，AutoTavern
的 Rust 引擎 TavernGym 只作为可选参照后端（`hsbg/backends/taverngym_env.py`，见
`docs/TAVERNGYM_BACKEND.md`）。第二阶段决策把关系反过来：

| 决策（用户 2026-10-26） | 落地情况 |
|---|---|
| **机制以 AutoTavern 为基准**，有误精修 | Rust 引擎 vendor 进本仓库为主引擎（本文件）；偏离上游的机制改动登记 `rust/FORK.md` §7 台账 |
| **数据用最新 37.0.0.255130** | **已集成最终版**（2026-10-26，sha256 `c4826127…`，v1.1.0 AT 机制元数据继承 + Dark Paradox 映射）：meta 驱动版本（`rust/FORK.md` §4/§5），`game_version()=37.0.0.255130` |
| **性能优先 Rust** | 主引擎为 Rust + PyO3；本机裸吞吐 ~257–277 games/s（§7），`hsrl2` 约 6.8 games/s |
| **动作/观测对齐 AT 245 + 3227 + 124** | 沿用上游固定动作空间 **245**、观测 **3227 floats + 124 cards**，见 §4.3 |
| **旧 checkpoint legacy、接受重训** | 观测/动作空间与 `hsrl2` 完全不同，旧 checkpoint 不迁移；`hsrl2` 转为 legacy/对照后端 |

**一句话**：`hsbg_engine` = TavernGym 引擎（MIT）+ 本仓库的命名/数据/文档适配；
公开 API 与行为与上游逐位一致（`rust/FORK.md` §3/§10.3），因此上游的机制实现、测试与
基准方法都可以直接复用。

---

## 2. 架构

### 2.1 分层

```
data/cards.json ──(include_str!, 编译期)──▶ cards.rs CardDb（静态卡表，CardId=稠密下标）
                                              │
content/*.rs（每张 card 的 Script 钩子）◀── script.rs 钩子表
                                              ▼
   recruit.rs / combat.rs / flow.rs  ◀──  engine.rs  Game + Ctx（召唤/增益/伤害/死亡/事件）
                                              │
        actions.rs（245 维扁平动作 + 精确合法 mask）
        obs.rs（3227 floats + 124 cards 的玩家视角观测）
        env.rs（SoloEnv：1 学习座位 vs 7 脚本 bot）
        batch.rs（BatchEnv：多局并行，任意控制座位，GIL 释放 + 线程池）
        bot.rs（启发式 bot，run_bot_games）/ debug.rs（JSON 视图/命令）
                                              ▼
             hsbg-engine-py（PyO3 abi3 扩展，模块 `hsbg_engine._core`）
                                              ▼
             python/hsbg_engine（numpy 包装：Game / SoloEnv / BatchEnv / BattlegroundsEnv）
```

模块职责与上游 `docs/ARCHITECTURE.md` 一致（`cards`/`config`/`state`/`engine`/
`recruit`/`combat`/`flow`/`event`/`script`/`content`/`actions`/`obs`/`env`/`batch`/`bot`/
`experimental`/`debug`/`invariants`/`rng`/`types`/`guard`/`workers`），此处不重复；
第一手说明见上游只读参照仓库的 `docs/ARCHITECTURE.md`。

### 2.2 关键设计（决定性能与可复现性）

- **纯数据 `Game`**：`Game` 是普通 `Clone` + serde 数据结构，`state_json()` 是**精确存档**
  （同数据表下 save→load→save 字节相等，恢复后续跑逐位一致）。
- **seed 完全决定随机**：引擎 RNG 在 `Game.rng`，同 seed + 同动作序列 ⇒ 轨迹逐位一致
  （`tests/test_rust_engine.py::test_same_seed_determinism`）。
- **固定动作空间 + 精确 mask**：245 个离散动作，`legal_mask` 精确到每个动作；非法动作
  在 `BatchEnv`/`SoloEnv` 里被拒绝并按 `illegal_penalty` 扣分，不推进状态。
- **固定观测向量**：只含客户端可见信息（global / board / hand / tavern / pending choice /
  quest / opponents 的 last-seen board …），布局由 `layout()` 自检，训练侧可硬编码切片。
- **`BatchEnv` 并行**：多局一起 step，Python 侧拿到 numpy 数组视图；GIL 释放 + Rust 线程，
  结果与 `threads` 无关（同 seed 可复现）。
- **数据编译期嵌入**：`include_str!("../data/cards.json")` + 首次使用 `OnceLock` 解析；
  换数据 = 换文件 + 重新编译（`pip install -e .`），运行时不读外部数据文件。
- **数据版本 meta 驱动**：`game_version()` / `server_rules_version()` 读数据 `meta`
  （36.6.3 → 37.0.0 只换数据文件；常量仅作 fallback）；`db_info()`/`data_info()` 一行核对。

### 2.3 仓库内目录

```
rust/
├── Cargo.toml / Cargo.lock / rust-toolchain.toml / rustfmt.toml   # workspace（Rust 1.98.1）
├── pyproject.toml            # maturin：project hsbg-engine，module-name hsbg_engine._core
├── crates/hsbg-engine/       # 纯 Rust 引擎（src 81 文件 ~4.47 万行 + data/cards.json + tests）
├── crates/hsbg-engine-py/    # PyO3 绑定（cdylib `_core`）
├── python/hsbg_engine/       # numpy 包装层（__init__ / env / batch）
├── FORK.md                   # 上游来源/许可/重命名/改动清单/数据替换/同步策略
└── bench_engine.py           # 可复现基准（本文件 §7 的数字由它产生）
```

---

## 3. 安装 / 构建

### 3.1 依赖

- Python ≥ 3.10（本机 `/opt/anaconda3/bin/python3` 3.12.2）+ `numpy`；
- Rust 1.98.1（`rustup`；`rust/rust-toolchain.toml` 固定，`cd rust` 自动选中）；
- `maturin >= 1.15`（本机 1.15.0）。

### 3.2 一条命令安装（推荐）

```bash
cd rust
python3 -m pip install -e .        # maturin 构建 release 扩展并 editable 安装
python3 -c "import hsbg_engine; print(hsbg_engine.version(), hsbg_engine.game_version())"
# 期望：1.0.0 37.0.0.255130（版本由数据 meta 驱动，换数据后自动变化）
```

- 本机实测（Apple Silicon，干净 `target/`）：`pip install -e .` **约 2 分钟**
  （maturin 构建 release 扩展，含 macOS 特有 `RUSTFLAGS` 的独立构建）；日常改代码/换数据后
  重建约 60–100 s（本机实测 touch 源文件后 99 s，release thin-LTO 重链接为主）；
- 扩展产物：`rust/python/hsbg_engine/_core.abi3.so`（macOS/Linux）或 `_core.pyd`（Windows），
  已 gitignore；
- 改了 Rust 源码或 `data/cards.json` 后**必须重跑** `pip install -e .`；
- 不安装时不进入任何默认门禁（`tests/test_rust_engine.py` 用 `pytest.importorskip` 跳过）。

### 3.3 纯 Rust 构建 / 测试

```bash
cd rust
cargo build --release                        # 冷构建 ~113 s（Apple Silicon）；macOS 可直接构建（build.rs 处理链接参数）
cargo test --release -p hsbg-engine          # 全量 Rust 测试（上游 858 tests 量级）
cargo test --release -p hsbg-engine --lib    # 只跑库内单测（快）
cargo run --release -p hsbg-engine --example bench -- 2000   # 上游自带裸吞吐示例
```

> macOS 上若删掉 `crates/hsbg-engine-py/build.rs` 的 `-undefined dynamic_lookup` 链接参数，
> 裸 `cargo build --release` 会报 `_Py*` undefined symbol（上游只支持 maturin 构建，
> 本 fork 让纯 cargo 也可用；见 `rust/FORK.md` §4 #5）。

### 3.4 数据更新（当前 37.0.0.255130，已集成）

数据只在 **`rust/crates/hsbg-engine/data/cards.json`**（编译期嵌入，不在仓库根 `data/`），
当前已是 **37.0.0.255130 最终版**（`data/p2/cards_37.json`，`gen_carddb_37.py` v1.1.0，
sha256 `c4826127…`，2026-10-26 集成；单人池 minion 277 / hero 118 / spell 73 /
trinket 236）。更新流程 = 换文件 + `cd rust && python3 -m pip install -e .` 重建，
步骤与**缺失 card id 会 panic 的硬约束**见 `rust/FORK.md` §5。核对命令：

```bash
HSBG_ENGINE_DB_INFO=1 python3 -c "import hsbg_engine"   # 打印一次卡数/版本
python3 -c "import hsbg_engine; print(hsbg_engine.data_info())"
```

---

## 4. Python 用法

### 4.1 版本/布局/数据

```python
import hsbg_engine as h

h.version()                 # "1.0.0"（fork 保留上游版本号）
h.game_version()            # "37.0.0.255130"（数据 meta 驱动）
h.server_rules_version()    # "37.0.0"
h.build_info()              # {"source_hash": "...16 hex...", "profile": "release", "file": ...}
h.data_info()               # {"cards": 3983, "game_version": ..., "server_rules_version": ..., "n_cards": 3984}
h.layout()                  # [(块名, 大小)...]：245 动作 / 3227 floats / 124 cards 的布局
h.action_name(0)            # "EndTurn"；h.action_name(244) == "Move { from: 6, to: 6 }"
```

### 4.2 一局 8 人游戏（`Game`，自走/自博弈/搜索）

```python
import json, hsbg_engine as h

g = h.Game(seed=1)                       # 8 个座位；RulesConfig 默认
while not g.is_over():
    for p in range(g.num_players):
        if g.needs_action(p):
            g.step(p, g.bot_action(p))   # 或任意合法动作下标（先看 g.legal_mask(p)）
print(list(g.placements()))              # 1..8 的排列

saved = g.state_json()                   # 精确存档（str）
g2 = h.Game.from_json(saved)             # 逐位还原（同数据表）
assert g2.state_json() == saved

# 全 bot 快速跑 N 局（纯 Rust、GIL 释放）：返回每局终局回合数
print(h.run_bot_games(1000, seed=0))
```

### 4.3 单座 Gym 环境 / 批量环境

```python
env = h.BattlegroundsEnv(seed=0)         # 1 学习座位 vs 7 脚本 bot
obs, info = env.reset(seed=0)
# obs["features"] float32[3227] / obs["cards"] int32[124] / obs["action_mask"] bool[245]
action = int(obs["action_mask"].nonzero()[0][0])
obs, reward, terminated, truncated, info = env.step(action)
# reward 只在终局给出名次奖励（1st=+1 … 8th=-1），info["placement"] 为最终名次

env = h.BatchEnv(n_games=64, seed=0, controlled=(0,), threads=8)
obs = env.observe()
# features (n_slots, 3227) / cards (n_slots, 124) / action_mask (n_slots, 245) / ready (n_slots,)
actions = [int(obs["action_mask"][i].nonzero()[0][0]) for i in range(env.n_slots)]
rewards, dones, info = env.step(actions)   # info["placement"] / info["rejected"]
state = env.save(0); env.load(0, state)    # 精确存档/恢复
```

**动作空间 245**（与 AutoTavern 对齐，`layout()` 自检）：

| 下标 | 动作 | 下标 | 动作 |
|---|---|---|---|
| 0 / 1 / 2 / 3 | end turn / refresh / freeze / upgrade | 46–125 | play hand 0–9 → 位置 0–7 |
| 4–5 | hero power 槽 0/1 | 126–195 | magnetize hand 0–9 → 棋盘 0–6 |
| 6 / 7 | Dark Gift 按钮 / Cancel | 196–244 | move 棋盘 0–6 → 位置 0–6 |
| 8–15 | buy 酒馆槽 0–7 | 30–45 | choose 选项 0–15（Discover/target/…） |
| 16–22 | sell 棋盘槽 0–6 | 23–29 | activate 棋盘槽 0–6 |

**观测 3227 floats + 124 cards**：`features` 是玩家视角的固定向量（global = 53 项、
MINION_F = 31、ITEM_F = 40、QUEST_F = 2、OPP_F = 9 …），`cards` 是卡牌词表下标
（0 = 空，`h.card_info(i)` 给出 id/中英文名/tier，`i ∈ 1..N_CARDS-1`）。

> ⚠ 与 `hsbg/env/spec.py`（`hsrl2` 的 `Observation`/`CandidateAction` 动态候选动作契约）
> **不是同一套接口**：主引擎是固定 245/3227/124 空间，训练集成需要新的适配层/编码器
> （Lead 集成任务）；旧的 `hsbg/backends/taverngym_env.py` 适配的是**上游 `taverngym`
> 包**（同一引擎，包名不同），后续可平移到 `hsbg_engine`。

### 4.4 配置

所有“非官方公布的规则数值”（卡池数量、offer 权重、大厅生成、黑暗赠礼/饰品参数、
安全上限等）都是 `RulesConfig` 字段，源码逐条标注证据等级
（`crates/hsbg-engine/src/config.rs`）。用 JSON 覆盖：

```python
import json, hsbg_engine as h
cfg = json.loads(h.default_config_json())          # 所有字段及默认值
g = h.Game(seed=1, config_json=json.dumps({"hero_choices": 4}))
env = h.BatchEnv(8, seed=0, config={"timewarp_enabled": True})
```

未知 key 会报错；`experimental_mode` 会开启固定动作空间之外的动作（阶段二默认关闭）。

### 4.5 Rust 侧直接用

```bash
cd rust
cargo run --release -p hsbg-engine --example play     # 打印一局 bot 的事件日志
cargo run --release -p hsbg-engine --example bench -- 2000   # 裸吞吐
cargo run --release -p hsbg-engine --example fuzz -- 200     # 随机动作 + 状态不变量检查
```

---

## 5. 与 `hsrl2` 后端的关系（主引擎 / legacy 对照）

| | `hsbg_engine`（本文件） | `hsrl2`（阶段一默认后端） |
|---|---|---|
| 实现 | Rust（内存安全、release thin-LTO），PyO3 abi3 扩展 | 纯 Python（`game.py` 约 5.7k 行 + 脚本库） |
| 数据 | **37.0.0.255130 最终版**（v1.1.0：37 映射 + 36.6.3 compat + AT 元数据继承；minion 277） | 37.0.0.255130 基线 |
| 动作 | 固定 **245** 维 + 精确 mask | 动态候选集（`CANDIDATE_MAX=64`，13 类 `ActionKind`） |
| 观测 | 固定 **3227 floats + 124 cards** | 实体 token + 全局标量 + `extra` |
| 吞吐（本机） | **257–277 games/s**（8 人全 bot 裸引擎）；端到端 ~3.7 ms/局 | ~6.8 games/s、~147 ms/局（`hsbg.backends.benchmark` 口径） |
| 阶段二角色 | **主引擎**：训练/评测/搜索的默认后端（集成任务切换） | **legacy / 机制对照**：规则权威参考、跨引擎对拍（`tests/conformance/`）、旧 checkpoint 保留但**接受重训** |

**过渡期约定**：

- 两套接口并存不冲突：`hsbg.backends.taverngym_env`（上游 `taverngym` 包）与
  `hsbg_engine`（本 fork）是同一引擎的两个包名，同时安装无影响；
- **旧 checkpoint 不迁移**（观测/动作空间不同，用户已决策 legacy）；训练任务在 Lead
  完成适配层后从新引擎重新训练；
- 机制修正在本 fork 进行并登记 `rust/FORK.md` §7；`hsrl2` 保持冻结（除既有回归/审计），
  跨引擎对拍台账（`docs/CONFORMANCE_AUTOTAVERN.md`）继续作为机制一致性的参考。

---

## 6. 测试

### 6.1 HSBRSIM 侧 pytest（`tests/test_rust_engine.py`）

11 个用例，`pytest.importorskip("hsbg_engine")` 保护（未安装时整文件 skip，不阻塞默认门禁）。
37 数据下实测 **10 passed + 1 skipped**（skip = 与上游逐位对拍，上游仍是 36.6.3 数据）：

1. import / 版本 / `build_info` / `data_info` 与数据 meta 一致；
2. 245/3227/124 布局常量与 `layout()` 自洽、`action_name(0..244)` 全有名且越界报错；
3. 单局 8 人 bot 对局 placements = 1..8 排列；`run_bot_games` 终局回合可复现；
4. `BattlegroundsEnv` 跑完一局：观测形状/dtype、非法动作为 0、名次奖励与 placement 一致；
5. `BatchEnv` 冒烟：观测形状、40 步推进、save→load→save 字节相等；
6. 与上游 `taverngym` 的 `layout()`/`action_name()` 逐项相等（上游未装则 skip）；
7. 同 seed 确定性（SoloEnv 轨迹 + Game state_json）；
8. `state_json` 往返：字节相等、恢复后观测一致、续跑到终局逐位一致；
9. 同数据版本时与上游逐位一致：`run_bot_games` 回合数 + 全 bot 对局 `state_json`
   字节相等（37 数据集成后自动 skip；`layout()`/`action_name()` 对比仍照跑通过）。

```bash
python3 -m pytest tests/test_rust_engine.py
# 10 passed, 1 skipped in 0.66s   （37 数据；36.6.3 替换前为 11 passed in 0.45s）
```

### 6.2 Rust 侧

```bash
cd rust && cargo test --release -p hsbg-engine --lib
# 37 最终数据下：15 passed; 0 failed

cd rust && cargo test --release -p hsbg-engine --no-fail-fast
# P3 收尾（37 数据 + Naga 大厅 + P3 内容）：39 个测试套件 887 passed; 0 failed; 0 ignored
# 37 数据（P3 前）：36 套件 878 passed / 9 failed（固定 seed 漂移，P3-C 已按 37 重算）
# 36.6.3 替换前基线：36 套件 858 passed / 0 failed（与上游同 commit 一致）
```

37 集成过程中出现过的 6 个 36.6.3 内容断言已**全部按 37 数据重算**（只改断言/注释，
不改引擎语义；详见 `rust/FORK.md` §5.4/§10.2 与 §7 台账）：

- `pool_tag_rule_excludes_rot_hide_gnoll_by_default`：`eligible 244 → 276`
  （37 单人池 277，唯一 `pool_tag=2` 是 BG25_013）；
- `gold_counters_show_the_gold_left`：卡面文本 `1 turns → 1 turn`（37 卡面修正单复数，
  文本来自数据）；
- `t19_*`：由“Naga-only 全部出池（36.6.3）”改为“Naga 回池（37）：池内 NAGA-only
  20 张 + 双种族含 NAGA 2 张”（`docs/PORTING_37_PLAN.md` §3.4/§4.1）；
- `aberration_subset_needs_aberrations_in_the_lobby` / `lobby_without_forced_aberrations`
  / `t20_yshaarj_lobby_bans`：v1.1.0 数据修复（AT 机制元数据继承 + Dark Paradox 5
  形态映射）后自动恢复，未改断言。
- `extra_offers_apply...` / `denathrius_quest...` / `trinket_avenge...` /
  `boon_of_light...` / `a_reborn_creation...` / `master_nguyen...` / `quest_reward_rules`
  + buddies_a/c fixtures：37 Naga 大厅与 P3 内容入池导致固定 seed 漂移，已按 37 数据
  重算期望或改成与抽取无关的构造/夹具（清单与依据见 `rust/FORK.md` §7 台账），
  **不放宽断言、无 skip/xfail**；
- **无 `#[ignore]` 项、无剩余失败。**

### 6.3 逐位一致证据

**36.6.3 数据下（替换前实测，历史证据）**：

| 检查 | 结果 |
|---|---|
| `layout()` / `action_name(0..244)` | 与上游逐项相等 |
| 全 bot 8 人局 `Game.state_json()` | **字节相等** |
| `run_bot_games` 终局回合 | 相同 |
| `SoloEnv`/`BatchEnv` 同 seed 同动作 | 轨迹/观测 bytes/save JSON 逐字节相等 |

**37 数据下（当前）**：`layout()`/`action_name()` **仍与上游逐项相等**（pytest 该用例
照跑通过）；引擎内部状态因两边数据不同（上游参照包仍是 36.6.3）不再逐位对拍，改由
“bot 对局/存档往返/BatchEnv/确定性”自洽性测试覆盖。

---

## 7. 基准（本机实测，2026-10-26）

### 7.1 环境与口径

- 机器：`macOS-15.2-arm64-arm-64bit` / Apple Silicon / 10 CPU；
- Python：`/opt/anaconda3/bin/python3` 3.12.2；NumPy 1.26.4；
- 引擎：`hsbg_engine` 1.0.0（release，`source_hash` 见 `rust/FORK.md` §10），
  数据 **37.0.0.255130 最终版**（v1.1.0，sha `c4826127…`；§7.2/§7.3 的数字在该数据
  下重测；§7.3 另有 36.6.3 替换前基线）；
- 所有数字由 `rust/bench_engine.py` 在同一进程/同一台机器产生：每项 **warmup +
  3 次重复取中位**；绝对值随机器负载波动 ±10%，**hsbg_engine vs 上游的比值**才是
  关键（应 ≈1.00，因为代码逐位相同）。

```bash
python3 rust/bench_engine.py --games 1000 --e2e-games 20 --solo-games 100 \
    --batch-steps 100 --repeats 3
# 对照上游 taverngym 需已安装（可选）
```

### 7.2 吞吐表

| 指标 | hsbg_engine（37 最终数据） | 上游 taverngym（36.6.3） | 备注 |
|---|---:|---:|---|
| **裸引擎** `run_bot_games`（8 座全 bot，1000 局） | **274.1 games/s，3.65 ms/局** | 272.8 games/s，3.67 ms/局 | 平均 15.4 回合；36.6.3 替换前基线 282.3/3.54。机器负载波动 ±10%，多次实测 257–282 games/s |
| **端到端 8 人局**（Python `Game`+bot 驱动） | 3.57 ms/局（279.9 games/s） | 3.79 ms/局（263.8 games/s） | 含 Python 调用开销 |
| **SoloEnv 观测+决策循环**（1 座 vs 7 bot） | 792.9 games/s，1.26 ms/局 | 793.2 games/s，1.26 ms/局 | 含 `observe()` + `legal_mask()` + `step()`，9.7 步/局 |
| **BatchEnv**（64 局，controlled=(0,)，threads=8，100 步） | 925.9 episodes/s，9406 slot-steps/s | 951.6 episodes/s，9667 slot-steps/s | 并行采样吞吐（训练口径）；步数增多进入后期（战斗重）时单步成本上升，200 步配置下约 820–840 episodes/s |

与上游（同代码、不同数据）的比值在 **0.97–1.05** 之间 → 性能与上游相同，符合预期。
> Lead 在首版 37 数据（v1.0.0）下另跑过一次（见 §7.5）：261.4 games/s（裸引擎）/
> 3.47 ms/局（端到端）/ 773.2 games/s（SoloEnv）/ 822.4 episodes/s（BatchEnv），
> 与上表差异来自机器负载，量级与结论一致（明细见 `rust/FORK.md` §10.4/§12）。

### 7.3 与 `hsrl2` 的对照（不同 harness，口径不同，勿直接相减）

| 后端 | 口径 | games/s | ms/局 |
|---|---|---:|---:|
| `hsbg_engine` | 裸引擎（纯 Rust，8 座全 bot，无观测/策略开销） | **257–282** | **3.54–3.89** |
| `hsbg_engine` | SoloEnv 观测+决策循环（含观测 bytes，1 座 vs 7 bot） | **792.9** | **1.26** |
| `hsrl2` | `hsbg.backends.benchmark`（`run_episode` + RandomPolicy + 启发式对手） | **6.81** | **146.81** |

> `hsrl2` 是纯 Python（每步都要构造 `Observation`/候选动作），本机实测 6.81 games/s、
> 146.81 ms/局（命令：`python3 -m hsbg.backends.benchmark --games 5 --seed 0
> --backends hsrl2`）。`hsbg_engine` 的裸引擎快 **~38–41×**，端到端（含观测+Python
> 决策）也快 **~4–5×**（对照 `docs/TAVERNGYM_BACKEND.md` §8 的 EnvLike 口径：taverngym
> features 端到端 ~29.5 ms/局 vs hsrl2 ~153 ms/局，约 5.2×）。
> 注：37 最终数据集成后两边**游戏数据版本一致**（37.0.0.255130），但 `hsrl2` 的接口
> （动态候选/实体 token）与本引擎（固定 245/3227/124）不同，仍不能直接相减/替换。
> 注意：引擎裸吞吐不含观测构建；训练实际吞吐取决于观测编码/策略网络，见
> `docs/TAVERNGYM_BACKEND.md` §8.4 的微基准。

### 7.4 结论

1. Rust 引擎把**单局模拟**从 ~147 ms 压到 ~3.7 ms（同一台机器），瓶颈转移到观测编码
   与策略计算（训练集成时要按 §4.3 的固定向量做向量化编码）；
2. `hsbg_engine` 与上游 TavernGym 性能一致（裸引擎/SoloEnv/BatchEnv 均在测量噪声内，
   符合“性能接近”的验收）；
3. 37.0.0.255130 **最终数据**（v1.1.0）下已**复跑本基准**：吞吐与 36.6.3 基线基本一致
   （282.3 → 274.1 games/s，局均回合 15.4 → 15.4），新数字已更新到本节与
   `rust/FORK.md` §10.4。

---

### 7.5 37.0.0.255130 首版数据复跑（Lead 集成时实测，2026-10-26）

| 指标 | hsbg_engine（37 数据） | 上游 taverngym（36.6.3） |
|---|---:|---:|
| 裸引擎 `run_bot_games`（8 座全 bot） | **261.4 games/s，3.83 ms/局** | 264.2 games/s，3.78 ms/局 |
| 端到端 8 人局（Python Game+bot） | 3.47 ms/局（288.5 games/s） | 3.85 ms/局（259.8 games/s） |
| SoloEnv 观测+决策循环 | 773.2 games/s，1.29 ms/局 | 768.7 games/s，1.30 ms/局 |
| BatchEnv（64 局，threads=8，200 步） | 822.4 episodes/s，8116 slot-steps/s | 784.1 episodes/s，7793 slot-steps/s |

> 该次实测用的是首版 37 数据（v1.0.0，sha `4ba9cdf7…`）；最终 v1.1.0 数据的本机复跑
> 见 §7.2（裸引擎 274.1 games/s / 3.65 ms/局，与上游 272.8/3.67 同量级）。37.0.0 相对
> 36.6.3 数值/回合数基本一致（平均 15.4 回合），吞吐与上游比 ≈0.99 — 证实 fork 未
> 引入性能偏离；数据替换只改变池子轮换与卡表范围。

---

## 8. 已知限制与后续 TODO

1. **数据 37.0.0.255130 最终版已集成**（2026-10-26，sha256 `c4826127…`，v1.1.0
   AT 机制元数据继承 + Dark Paradox 5 形态映射）：`game_version()=37.0.0.255130`、
   `server_rules_version()=37.0.0`、3983 卡、245/3227/124 不变、单人池 minion 277；
   bot 对局/存档往返/BatchEnv/确定性全正常，无 registry panic（compat 覆盖脚本 id）。
   测试全绿：pytest 10 passed + 1 skip、`cargo test --lib` 15 passed、全量
   `cargo test --release -p hsbg-engine` **858 passed / 0 failed**（6 个内容断言已按
   37 数据重算，见 §6.2 / `rust/FORK.md` §10.2；无 ignore 项）。
2. **训练/评测集成**：`hsbg/env/spec.py` 的动态候选动作契约与固定 245/3227/124 空间
   不同，需要新的适配层（Lead/训练任务）；旧 `TavernGymEnv` 适配的是上游包名。
3. **机制精修**：阶段二“有误精修”在 `rust/FORK.md` §7 台账登记；改机制必须带规则依据
   （E0–E4）与回归测试，并同步 `docs/CONFORMANCE_AUTOTAVERN.md`。
4. **平台验证**：macOS 已实测构建/测试/基准；Linux 预期一致但未实测；Windows 用
   maturin 构建（上游支持路径），纯 `cargo build` 未验证。
5. **上游同步**：pinned vendor，升级流程见 `rust/FORK.md` §6；保持 diff 最小、可上游化。
6. **体积**：`rust/target/` 为 GB 级（已 gitignore，不入库）；`cargo clean` 后可重建。
7. **文档联动**：`AGENTS.md` 的引擎/命令/依赖说明、`README.md` 的引擎章节由 Lead 在
   集成时更新（本文件与 `rust/FORK.md` 是引擎侧的第一手文档）。

---

---

## 9. 参考

- **`rust/FORK.md`**：上游 commit/许可归因、重命名映射、fork 改动清单、数据替换与
  缺失 id 约束、与上游同步策略、机制改动台账、构建/验证记录。
- `docs/TAVERNGYM_BACKEND.md`：上游 TavernGym 参照后端的 EnvLike 适配/观测解码/
  动作映射/基准（阶段一的产物，仍是观测解码细节的第一手文档）。
- `docs/AUTOTAVERN_UPGRADE.md`：AutoTavern 借鉴升级总报告（双引擎、跨引擎对拍）。
- `docs/CONFORMANCE_AUTOTAVERN.md`：跨引擎一致性台账（57 场景/AC 编号/数据差异）。
- 上游只读参照仓库 `/Users/letiangao/HSAgent/repos/AutoTavern`：
  `docs/ARCHITECTURE.md`（引擎架构/模块职责）、`docs/TAVERNGYM.md`（上游用法/速度/
  数据说明）、`docs/CONTENT.md`（卡牌实现覆盖）、`crates/taverngym/src/config.rs`
  （规则配置逐项证据等级）。
- 上游 GitHub：<https://github.com/MCG-NJU/AutoTavern>（MIT；TavernGym v1.0.0，
  commit `fb61201a557ddd36a411cf44aac51ce4d9b606ce`）。

---

## 10. P3 系统补齐（37 大厅 / 主英雄技能 / Dark Paradox）

P3 起引擎/内容补全都以 37.0.0 数据为准，系统改动台账见 `rust/FORK.md` §7。

### 10.1 37 大厅类型：Naga 回池（`flow.rs`）

- 37.0.0 标准大厅 = **10 种类型随机 5 种**：Beast/Demon/Dragon/Elemental/Mech/Murloc/
  **Naga**/Pirate/Quilboar/Undead（36.6.3 轮换把 Naga 移出大厅，AT 原版 `optional`
  只有 9 种；37 数据里 Naga-only 随从回池，见 `docs/PORTING_37_PLAN.md` §3.4）。
- `RulesConfig::lobby_types`（强制类型）语义不变：名取自 `Races::NAMES`（含 `NAGA`），
  用例可用 `lobby_types: vec!["NAGA"]` 定向 Naga 大厅；Aberration 仍是特殊位
  （`aberration_forced` 先占 1 席，`optional` 里的 ABERRATION 只在剩余名额时抽样），
  Naga 加入不影响。
- 类型过滤随大厅自然生效：Naga assoc 英雄（Queen Azshara `BG22_HERO_007`、Lady Vashj
  `BG23_HERO_304`）只在 Naga 大厅进入英雄池；Naga-only 随从只在 Naga 大厅进 universe。
- **回归影响**：固定 seed 的既有测试出现期望漂移（大厅抽样/池内容变化），已在 P3-C
  按 37 数据重算（见 `rust/FORK.md` §10.2，未放宽断言）；P3 内容全部合入后需重新冻结
  seed 基准。

### 10.2 Queen Azshara 主技能（`content/p3_systems.rs`）

| 卡 | 37 数据语义 | 实现 |
|---|---|---|
| `BG22_HERO_007p` Azshara's Ambition（passive，0 费） | “When your warband reaches 30 total Attack, begin your Naga Conquest.” | 监听能改变己方战队总攻的事件 + `start_of_turn`/`end_of_turn` 检查点；`Ctx::boards[side]` 存活随从攻击力和 ≥30（与 `content::check_total_attack` 同口径）→ `Ctx::set_hero_power` 替换为 p2 |
| `BG22_HERO_007p2` Naga Conquest（active，1 费） | “Discover a Naga.” | 池感知 Discover 三选一：`races.intersects(NAGA)`（ALL 种族天然命中）+ 常规 Tier 上限（Tier 7 需已解锁）；每回合 1 次，费用取数据 cost=1 |

- 英雄可通过 Naga 大厅被抽到（`hero_power` 脚本注册后 `hero_pool` 过滤放行）；
  回归：`tests/p3_systems.rs`（hero 注册/大厅抽取/29→30 阈值/变身/Discover/费用/
  每回合 1 次，共 6 例 + 1 例技能替换原语）。
- 与 hsrl2 参照一致：阈值 30（卡面字面量）、进化到 p2、无 tier 限定（hsrl2
  `Discover(race=NAGA)` 口径）。

### 10.3 `BG36_360` Dark Paradox：**保持 AT 5 形态机制**（决策）

- 37 数据：base `BG36_360` 是 tier1/1/1 的**占位壳**（`pools=[]`、无脚本、不在池），
  可玩的是 5 个 36.6.3 形态 token（`BG36_360t3/t4/t5/t6/t9`，Tier 2/5/4/3/6，
  各有脚本与 golden）；`flow.rs::PARADOX_VARIANTS` 每局随机抽 1 个入池。
- 37 卡面“每局不同 Dark Gift/属性/Tier”在**可观察玩法**上已被该机制覆盖；单卡 id
  动态化需要 per-game `CardDef` override 贯穿 pool/shop/triple/obs/state_json，
  收益仅为表征、风险高 → P3 不做，登记 `rust/FORK.md` §7 + 后续项（数据补 37 形态表 +
  引擎 per-game override）。
- 回归：`tests/p3_systems.rs::dark_paradox_37_data_and_mapping_invariants`（数据字段、
  5 形态 Tier 覆盖、每局恰 1 形态、base 不入池、200 seeds 全形态可达、存档往返）。

### 10.4 验收

```bash
cargo build --release -p hsbg-engine                       # PASS
cargo test --release -p hsbg-engine --test p3_systems      # 8 passed / 0 failed
cargo test --release -p hsbg-engine --no-fail-fast          # 39 套件 887 passed / 0 failed
python3 -m pytest tests/test_rust_engine.py                 # 10 passed + 1 skip
```

---
