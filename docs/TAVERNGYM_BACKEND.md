# TavernGym 参照后端（AutoTavern Rust 引擎 → HSBRSIM EnvLike）

> 状态：**可选/参照后端，已接入但默认不启用**（默认后端仍是 `hsrl2` 的
> `hsbg.env.BattlegroundsEnv`）。
> 代码：`hsbg/backends/`（`__init__.py` / `taverngym_env.py` / `benchmark.py`）；
> 测试：`tests/test_backend_taverngym.py`；
> 上游参照实现：`/Users/letiangao/HSAgent/repos/AutoTavern`（只读，GitHub:
> [MCG-NJU/AutoTavern](https://github.com/MCG-NJU/AutoTavern)）。
> 本文所有数字均为**本机一次实测**（macOS Apple Silicon，见 §8），不是抄来的。

---

## 1. 定位：为什么要第二个模拟引擎

HSBRSIM 的模拟精度权威是 vendored 的 `hsrl2`（数据基线 37.0.0.255130）。
TavernGym 是 AutoTavern 项目用 Rust 独立实现的一套酒馆战棋模拟器
（游戏数据 36.6.3.253932），特征：

| | `hsrl2`（默认后端） | TavernGym（本后端） |
|---|---|---|
| 实现 | Python（vendored，约 5.7k 行 `game.py` + 脚本库） | Rust（PyO3 abi3 扩展，release profile） |
| 数据版本 | **37.0.0.255130**（本项目基线） | **36.6.3.253932**（server rules 36.6.3） |
| 接口形态 | 实体 token 观测 + 动态候选动作 + `PendingChoice` | 固定 3227 floats + 124 cards 观测；固定 **245 维**动作 + 精确 mask |
| 单局驱动 | `BattlegroundsEnv`（1 智能体 + 7 脚本对手） | `Game` / `SoloEnv` / `BattlegroundsEnv` / `BatchEnv` |
| 本项目中的角色 | **默认/权威** | **参照/交叉验证/吞吐基准**（不参与默认路径） |

把它接进来能拿到三类价值：

1. **独立实现交叉验证**：同一 seed 下两套引擎的规则/数值差异可以量化
   （卡池、英雄、经济曲线、战斗伤害上限等）；
2. **吞吐参照**：Rust 引擎 + 固定向量观测天然快，可量化"环境层瓶颈在哪"；
3. **可复现的存档/分支**：`Game.state_json()/from_json()` 精确存档，便于搜索/回放。

> ⚠️ 它不是 `hsrl2` 的替代品：数据版本落后一个补丁（36.6.3 vs 37.0.0）、
> 卡池/系统不同、动作/观测空间完全不同。**不要**把两边的胜率/名次直接对比，
> 也不要把 HSBRSIM 训练出的策略直接搬过去（见 §7）。

**注册状态**：已接入 `hsbg.rl` 工厂（`make_env(backend="taverngym")`，惰性导入）
与 `collector/evaluate` 的 `--backend` 透传；**默认后端仍是 hsrl2**
（`make_env()` ≡ `make_env(backend="hsrl2")`，CLI 默认 `auto` 行为逐位不变）。
用法见 §3.4，接口层说明见 `docs/RL_INTERFACE.md` §11。

---

## 2. 安装 / 构建（macOS / Linux / Windows）

TavernGym 不是纯 Python 包，需要本地编译一次 Rust 扩展（PyO3 + maturin）。

### 2.1 依赖

* Python ≥ 3.10（本机系统 Python：`/opt/anaconda3/bin/python3` = 3.12.2）；
* Rust 工具链（[rustup](https://rustup.rs)）；AutoTavern 的
  `rust-toolchain.toml` **固定 1.98.1**，在仓库目录里 rustup 会自动安装该版本；
* `numpy`（TavernGym 运行时依赖）。

### 2.2 安装步骤

```bash
# 1) 克隆参照仓库（只读使用；不要在本项目仓库内改它）
git clone https://github.com/MCG-NJU/AutoTavern.git
cd AutoTavern

# 2) 构建并安装 Python 扩展（maturin 构建 backend，产物是
#    taverngym/_core.abi3.so（macOS/Linux）或 _core.pyd（Windows））
pip install .

# 3) 验证
python3 -c "import taverngym; print(taverngym.version(), taverngym.game_version())"
# 期望输出（本机）：1.0.0 36.6.3.253932
python3 -c "import taverngym; print(taverngym.build_info())"
# {'source_hash': 'c807e9aa1a6746ee', 'profile': 'release', 'file': '.../_core.abi3.so'}
```

* 首次构建需要 Rust 编译（release 模式，数十秒~几分钟）；之后改 Rust 源码需
  **重新** `pip install .`；
* Windows 需要 MSVC Build Tools（rustup 的 `stable-x86_64-pc-windows-msvc`）；
* 若想指定解释器：`/path/to/python3 -m pip install .`；
* 卸载/重装：`pip uninstall taverngym` 后重跑 `pip install .`。

> HSBRSIM 侧**没有**把 `taverngym` 加进 `pyproject.toml` 依赖（保持可选）：
> 未安装时 `import hsbg.backends` 正常工作，构造环境才抛 ImportError 并附带上述
> 安装步骤；测试文件用 `pytest.importorskip("taverngym")` 保护。
> `hsbg.rl.envs.make_env(backend="taverngym")` 是**惰性导入**：不选该后端时
> 完全不影响 hsrl2/mock 路径；未安装且显式选择时抛带安装步骤的 ImportError。

### 2.3 本机实测版本

```
taverngym 1.0.0 / game_version 36.6.3.253932 / server_rules_version 36.6.3
profile=release, source_hash=c807e9aa1a6746ee
N_ACTIONS=245, N_CARDS=3984(含空位，实际 3983 张), OBS_FLOATS=3227, OBS_CARDS=124
```

---

## 3. 用法

### 3.1 作为 `EnvLike`（推荐）

```python
from hsbg.backends import TavernGymEnv
from hsbg.rl.api import run_episode
from hsbg.rl.policies import RandomPolicy

env = TavernGymEnv(seed=0)                 # 默认 obs_source="features"
obs = env.reset(seed=0)                    # -> hsbg.env.spec.Observation
print(obs.turn, obs.phase, len(obs.candidates), obs.rank)
print(obs.extra["taverngym"]["flat_action_indices"])  # 候选下标 → 245 维动作下标

obs, reward, terminated, truncated, info = env.step(0)   # 候选下标
print(info["invalid"], info["rank"], info["backend"], info["flat_action"])

# 也可以直接走 hsbg.rl 的单局驱动 / JSONL
rec = run_episode(env, RandomPolicy(seed=0), seed=0, max_steps=1000)
print(rec.rank, rec.steps, rec.terminated, rec.summary_dict())
env.close()
```

构造参数（全在 `hsbg/backends/taverngym_env.py::TavernGymEnv`）：

| 参数 | 默认 | 说明 |
|---|---|---|
| `num_players` | 8 | 2..8（TavernGym `RulesConfig.num_players`） |
| `seed` | 0 | `reset(seed=None)` 时使用；同 seed 完全可复现 |
| `agent_index` | 0 | 智能体座位 |
| `config` | None | `RulesConfig` 覆盖项（JSON），如 `{"hero_choices": 4}` |
| `obs_source` | `"features"` | 官方观测解码（快、公开信息）或 `"view"`（调试 JSON，字段最全但慢） |
| `reward` | `RewardConfig()` | 只用 placement / invalid_action / step_penalty / timeout |
| `max_steps` | 4000 | 单局决策步数上限（超限 truncated） |
| `max_turns` | 40 | 回合上限（超限 truncated）；None = 不限制 |
| `illegal_penalty` | None | 非法动作惩罚；None 用 `reward.invalid_action`（默认 -0.05） |
| `include_action_names` | True | `extra` 里附 `taverngym.action_name` 可读名 |

### 3.2 固定动作空间 + 精确掩码

```python
env = TavernGymEnv(seed=0)
env.reset(seed=0)

mask = env.fixed_action_mask()          # Tuple[bool] * 245（引擎实时 legal mask）
flats = env.legal_action_indices()      # 当前候选对应的 245 维动作下标（升序）
env.flat_index(obs.candidates[0])       # CandidateAction → 245 维动作下标
env.candidate_index_for_flat(30)        # 245 维动作下标 → 候选下标（-1=非法）
# 注意没有 step_flat(245维下标)：EnvLike.step 的 int 参数是**候选下标**，
# 固定 245 维空间用上面两个映射函数转到候选后再 step。
```

> 说明：`EnvLike.step` 的整数参数按 **`obs.candidates` 的下标**解释（与
> `docs/ENV_SPEC.md` / `hsbg.rl.api.resolve_action` 一致），**不是** TavernGym
> 的 245 维扁平下标；后者用 `legal_action_indices()` / `candidate_index_for_flat()`
> 做双向映射。

### 3.3 精确存档 / 恢复

```python
state = env.save_state()          # JSON 字符串：引擎完整状态 + 适配器计数
env2 = TavernGymEnv(seed=0)
env2.load_state(state)
assert env2.current_observation == env.current_observation   # 逐字段相等
assert env2.save_state() == state                            # save→load→save 字节相等
# 之后 env2.step(...) 的轨迹与 env 从存档点继续完全一致
```

存档结构：`{"format": "hsbg.backends.taverngym_env", "version": 1,
"backend": "taverngym", "game_json": "<taverngym state_json>", "meta": {...}}`。
单局状态 JSON 实测 **约 100 KB（早中期）~ 300 KB（终局）**，主要用于搜索/回放；
训练大批量不需要存档。

### 3.4 基准

```bash
# 两个后端各 10 局 + 引擎裸吞吐 + 观测微基准（结果可写 JSON）
python3 -m hsbg.backends.benchmark --games 10 --seed 0 \
    --engine-games 500 --micro-steps 300 --obs-source both \
    --json runs/backends/bench_20261026.json
```

### 3.5 通过 `hsbg.rl` 工厂 / CLI（已注册）

```python
from hsbg.rl import make_env, make_policy, run_episode

env = make_env(backend="taverngym", seed=0)                    # 默认 features 观测源
env = make_env(backend="taverngym", seed=0,
               env_kwargs={"obs_source": "view", "num_players": 8})
rec = run_episode(env, make_policy("random", seed=0), seed=0, max_steps=1000)
# make_env() / make_env(backend="hsrl2") / backend="real" / "auto" 仍是 hsrl2
# 真实环境（默认后端不变）；"mock" 仍是确定性合成环境。
```

```bash
# 采集 1~2 局 JSONL（header 里 backend="taverngym"、每步 info 带 flat_action）
python3 -m hsbg.rl.collector --policy random --envs 1 --episodes 2 \
    --backend taverngym --out runs/rl/taverngym.jsonl

# 评测（名次分布/吞吐）
python3 -m hsbg.rl.evaluate --policy random --episodes 2 --backend taverngym
```

接口层限制：`teacher`（引擎感知策略）只支持 hsrl2，选 `taverngym`/`mock` 会
提前报 `ValueError`；`opponent`/`mock_kwargs` 对 taverngym 不生效（对手固定为
引擎内置脚本 bot）。`docs/RL_INTERFACE.md` §11 有完整说明。

---

## 4. 观测映射

`Observation` 复用 `hsbg.env.spec`（`version=3`，未修改 spec）。两种观测源：

### 4.1 `obs_source="features"`（默认，推荐）

解码上游**官方 RL 观测** `Game.observe(seat)`：`features` 3227 f32 + `cards` 124
i32，按 `taverngym.obs` 的固定布局（`taverngym.layout()` 自检）逐位还原成
`EntityToken`。**只含玩家可见信息**，单次约 0.17 ms，适合采集/基准。

| `Observation` 字段 | 来源（`features`/`cards` 布局） |
|---|---|
| `hero` | global 标量（health/armor/gold/tier/upgrade_price/power*）+ `cards[0]` 英雄 id + `cards[1..2]` 技能 id |
| `board` | `N_BOARD=7 × MINION_F=31`（atk/hp/tier/golden/keywords bits/races bits）+ 卡牌下标 |
| `hand` | `N_HAND=10 × ITEM_F=40`（随从块或法术块） |
| `tavern` | `N_SHOP=8 × ITEM_F=40`（含当前价格 = price/5） |
| `trinkets` | `cards[60..67]`（最多 8 个饰品位） |
| `quest` | 任务块（卡 id/reward id/进度归一化值） |
| `opponent_board` | 上一场对手的 `seen_board`（`OPP_BOARD_F`，公开信息） |
| `lobby` | `N_OPP=7 × OPP_F=9`：alive/health/armor/tier/上次战团规模/placement/last/next |
| `alive_count` / `rank` | 官方标量 + `Game.placements()`（名次按 hsrl2 口径估算：已淘汰=最终名次，存活=1+血(甲)更高人数） |
| `pending_choice` | 9 类 one-hot + 选项物品块；选项数量由 legal mask 的 CHOOSE 位确定 |
| `extra` | `frozen_tavern/free_refresh_left/refresh_cost/powers/dark_gift/quest/trinkets/pending_hand_queue/next_opponent/last_opponent/elimination/lobby_races/env_stats` 等（键尽量对齐 hsrl2 的 `build_extra_state`） |
| `extra["taverngym"]` | 后端元信息：`n_actions=245`、`flat_action_indices`、`candidate_action_names`、`turn_raw`、`phase_raw`、`candidate_max`、`candidates_over_spec_max` |

**features 模式的已知缺失**（官方向量观测没编码）：

* 实体 uuid：`EntityToken.entity_id` 恒 0；
* `pending_choice.kind="target"` 的选项**拿不到目标实体 id**（只有卡牌 id 或空）；
* 战斗回放/`last_combat` 摘要、逐随从的 EXHAUSTED/FROZEN 等引擎标志、
  每回合英雄技能剩余次数、`deaths_by_card_id` 等 → `extra` 中留空/置 None；
* 任务进度只有 `progress/goal` 归一化值，还原为千分比（`extra` 注明）；
* 英雄选择阶段官方观测**屏蔽对手信息**（health 固定 1.0、hero 下标 0），
  本后端把对手还原为"未知默认值"（health=30/armor=0/tier=1），
  且该阶段 `rank=0`（名次无意义）；`view` 模式则能看到对手真实护甲。

### 4.2 `obs_source="view"`（调试/对照）

解码 `Game.view(seat)` JSON（含实体 uuid、中英文名、关键词名、pending 目标的
eid、英雄选择护甲、上一场战斗摘要）。字段最全，但 `view()` 的 JSON 含战斗回放
序列化，单次 **约 2.3~12 ms**（随对局阶段增长），只建议对照验证/可视化。

> ⚠️ `view()` 是"调试视图"，JSON 里**包含隐藏信息**（对手当前棋盘、他人手牌数
> 等）。本适配器**只取公开字段**（`me.*`、`opponents[].seen_board`、大厅标量、
> 己方战斗摘要），不会把隐藏信息放进 `Observation`；但不要据此把 `view` 模式
> 当作"官方 POMDP 观测"——要干净观测请用默认的 `features`。

两种观测源在 `tests/test_backend_taverngym.py::TestObservationSources` 里做了
逐实体交叉验证（同一 seed/动作序列 25 步，board/hand/tavern/opponent_board 的
全部 token 字段、候选、扁平下标、名次/大厅标量一致）。

### 4.3 与 spec 槽位上限的差异（重要）

TavernGym 的槽位比 `hsbg.env.spec` 的上限大；本适配器**不截断**（截断会让
候选动作引用不存在的槽位），因此消费方需要知道：

| 列表 | spec 上限 | TavernGym 实际上限 |
|---|---|---|
| `tavern` | `TAVERN_MAX=7` | `N_SHOP=8` |
| `trinkets` | `TRINKET_MAX=2` | 8（官方 cards 块 8 个饰品位） |
| `pending_choice.options` | `CHOICE_OPTION_MAX=5` | `N_CHOICE=16` |
| `board` | 7 | 7 ✓ |
| `hand` | 10 | 10 ✓ |

按 spec 上限 padding 的编码器会丢弃尾部槽位/选项（对参照后端可接受，训练前需
评估）。

---

## 5. 动作映射（245 维固定空间 → `CandidateAction`）

TavernGym 的 245 维布局（`crates/taverngym/src/actions.rs`）：

| 下标区间 | 动作 | 本后端的 `kind` 映射 |
|---|---|---|
| 0 / 1 / 2 / 3 | end turn / refresh / freeze / upgrade | `end_turn` / `reroll` / `freeze` / `upgrade` |
| 4-5 | hero power（主/副槽） | `hero_power`（`src_zone="power"`, `position=slot`） |
| 6 | Dark Gift 按钮 | `use_dark_gift` |
| 7 | Cancel（退出目标选择） | `"cancel"`（**spec `ActionKind` 无对应项**，见下） |
| 8-15 | buy 酒馆槽 0-7 | `buy`（`src_zone="tavern"`, `src_slot=i`, `cost=当前价格`） |
| 16-22 | sell 棋盘槽 0-6 | `sell`（`src_slot=i`） |
| 23-29 | activate 棋盘槽 0-6 | `activate`（`src_slot=i`） |
| 30-45 | choose 选项 0-15 | `choose`（`option=k`） |
| 46-125 | play 手牌 0-9 到位置 0-7 | `play_minion` / `play_spell`（`src_zone="hand"`, `position=p`） |
| 126-195 | magnetize 手牌 0-9 吸附棋盘 0-6 | `play_minion` + `tgt_zone="board"`, `tgt_slot=b` |
| 196-244 | move 棋盘 0-6 → 位置 0-6 | `move_minion`（`position=目标槽位`） |

* 候选顺序 = **扁平动作下标升序**；`obs.extra["taverngym"]["flat_action_indices"]`
  与 `obs.candidates` 一一对应，`extra["taverngym"]["candidate_action_names"]`
  给出 `taverngym.action_name(a)` 的可读名；
* **`cancel` 特例**：TavernGym 允许取消目标选择（退回法术/技能/Aactivate 目标前），
  `ActionKind` 没有该类型。本适配器用字符串 `"cancel"` 表示（`CandidateAction.kind`
  允许任意字符串）；`kind_index` 会落到 0（`buy`），训练侧若用 `ACTION_KIND_INDEX`
  需自行处理该扩展值；
* **候选数可能超过 `CANDIDATE_MAX=64`**：TavernGym 固定空间最多 245 个合法动作
  （实测常见 5~40，满场/多目标时可能超过 64）。`hsbg/train/bc.py` 等按
  `min(len(candidates), CANDIDATE_MAX)` 截断的编码器会丢动作——这是本后端定位为
  "参照/评测"而非"直接训练"的核心原因；
* 不支持 `experimental_mode` / Timewarp：它们会在 245 维空间之外追加动作，
  适配器只映射 mask 内的动作，开启后策略可能"看不到"部分合法动作。

---

## 6. 奖励 / 终止 / 确定性语义

**奖励**（对照上游 `SoloEnv`：名次奖励 + 非法动作惩罚，其余 0）：

| 项 | 本后端 | 上游 `SoloEnv` |
|---|---|---|
| 终局名次 | `placement * (1 - 2*(rank-1)/(n-1))`，第 1 名 +1、最后 -1 | 同公式 |
| 中间步 | 0 + `step_penalty`（默认 0） | 0 |
| 非法动作 | `reward.invalid_action`（默认 **-0.05**，可用 `illegal_penalty=` 覆盖） | `illegal_penalty`（默认 -0.01） |
| 截断 | `reward.timeout`（默认 -0.5） | — |
| health/combat/board shaping | **未实现**（恒 0；`RewardConfig` 对应权重不生效） | — |

**终止契约**（与 `docs/ENV_SPEC.md` §4 对齐）：

* 智能体被淘汰（`Game.placements()[agent] != 0`）→ `terminated=True`，
  `reason="eliminated"`，`info["rank"]=placements[agent]`（此时对局继续，但本
  适配器**立即收口**，与上游 `SoloEnv.done()` 一致）；
* 游戏结束（冠军）→ `terminated=True`，`reason="game_over"`，`rank` 取
  `placements[agent]`（=1）；
* 引擎保险（`max_turns` 内部上限 100 回合）触发 → `truncated=True`，
  `reason="engine_turn_limit"`（引擎会"发明"名次，只作诊断）；
* `max_steps` / `max_turns` → `truncated=True`，名次奖励不给、给 timeout；
* 引擎驱动异常（机器人无合法动作导致停摆）→ `truncated=True`，
  `reason="simulator_stopped"`（防御性，正常对局不触发）；
* 终局后再 `step()`：返回原终局观测、`terminated=True`、`invalid=False`、
  `info["episode_done"]=True`，步数不再增长。

**确定性**：`reset(seed)` 后同 seed + 同动作序列 ⇒ 观测/奖励/终止完全一致
（测试覆盖）；`bot_action()` 不消耗引擎 RNG（上游实现如此），`bot_play()` 由
引擎 RNG 驱动。复位不做 `os.urandom`（默认 seed=0），与 hsrl2 后端不同但更适合
基准/回归。

**驱动等价性**：智能体之外的 7 个座位由 `Game.bot_play()` 驱动，顺序与上游
`SoloEnv::advance` 完全一致；测试 `TestDriverReference` 逐步比对
`env.game.state_json() == SoloEnv.state_json()`（同 seed + 同动作序列，逐步相等）。

### `info` 字段

必需项与 hsrl2 后端同构：`turn / rank / agent_rank / health / armor /
alive_count / combat / wrong_action / invalid / terminated_reason / seed /
episode / episode_steps / phase`；本后端另加：

* `backend="taverngym"`；
* `flat_action`（本步的 245 维动作下标）、`action_name`（可读名）；
* `action_mask`（245 维原始 mask，`Tuple[int]`）；
* `n_candidates`、`obs_source`、`taverngym_version`、`taverngym_game_version`；
* `restore_count`（`load_state` 次数）；
* 非法动作时 `action_error`。

`hsbg.rl.api.JSONL_INFO_KEYS` 白名单里的字段全部存在，因此
`run_episode → Transition.to_dict() → validate_record()` 可直接通过（测试覆盖）。

---

## 7. 与 hsrl2 后端的差异（策略不可直接迁移）

### 7.1 数据版本与卡池

| 项 | HSBRSIM `hsrl2` 37.0.0.255130 | TavernGym 36.6.3.253932 |
|---|---|---|
| 卡牌/对象总数 | BG 相关 3534（`data/bg_summary.json`） | 3983 条卡表（`N_CARDS=3984` 含空位；implemented 2194 / reachable 1163） |
| 商店随从池 | **273**（tier 1..7：25/37/45/62/56/35/13） | **245**（默认 `content=Implemented` 只开已实现/关键词卡） |
| 酒馆法术池 | **76** | **70** |
| 英雄 | **118** | **116** |
| 饰品 | **409** | **236**（lesser 114 + greater 122） |
| 黑暗赠礼 | 47 | 47 |
| 任务奖励 | 73 | 73（但默认规则下任务只在 `experimental_mode` 出现） |
| 异变 | **108** | **不建模**（36.6.3 的 Aberration 只是种族位/大厅标记） |

卡牌 id 词表、同卡数值、英雄技能、饰品池都可能不同；即便 `id` 相同，也可能
因为补丁差异而**数值/文本不同**。因此：

* 两份引擎的"同名卡"不能假设等价；
* 基于卡 id/属性统计的数据集（BC 数据、价值网络）**不能跨后端混合**；
* 名次奖励公式可以共享，但状态分布、经济曲线（TavernGym 的
  `RulesConfig` 默认值里有若干"baseline/未公布"参数，见 `config.rs`）不同，
  胜率/名次不能直接对比。

### 7.2 动作 / 观测空间

| | HSBRSIM（spec v3） | TavernGym |
|---|---|---|
| 动作 | **动态候选集**（`CANDIDATE_MAX=64`，13 种 `ActionKind`；目标组合在 env 层展开） | **固定 245 维** + 精确 mask；目标选择是 `choose(0..15)` 选择步 |
| 观测 | 实体 token（board/hand/tavern/trinkets/quest/opponent/lobby）+ 全局标量 + `extra` | 固定 3227 f32 + 124 卡牌下标；**没有**实体结构 |
| 选择步 | `phase="choice"`，候选只有 `choose` | pending 时 mask 只有 `choose(0..15)`/`cancel` |
| 棋盘重排 | 只有相邻交换候选（`move_minion`） | 任意 from→to（7×7=49 个 `move` 动作） |
| 阶段 | `recruit`/`choice`/`game_over`，`turn` 从 1 起 | 引擎内 `hero_select`/`recruit`/`game_over`，`turn` 从 0 起（英雄选择） |

策略不能直接迁移的点：观测编码器（实体 token vs 固定向量）、动作头
（候选打分 vs 245 维 masked softmax）、卡牌词表、槽位上限、阶段/回合偏移。
可迁移的只有高层思路（经济曲线、买/卖/升级时机、阵容方向）。

### 7.3 规则/配置差异（必须在结论里注明）

* TavernGym `RulesConfig` 的默认值里包含未公布规则的"基线假设"：起始金币 3、
  金币上限 10、酒馆随从槽 3/4/4/5/5/6/6、共享池 15/15/13/11/9/7/5、
  `hero_choices=2`、伤害上限 (1,5)/(4,10)/(8,15)、`max_turns=100` 保险等
  （见上游 `crates/taverngym/src/config.rs`，文件里逐条标注证据等级）；
  这些不是"官方公布值"，与 37.0.0 的实际值可能有出入。
* 本适配器把 `max_turns` 默认设为 40（`EnvConfig` 口径）；为让引擎内部保险
  不先触发，会把引擎 `max_turns` 覆盖成 `max_turns + 2`。
* 实验模式（`experimental_mode`/Timewarp）不在支持范围（见 §5）。

---

## 8. 基准（本机实测）

### 8.1 环境

* 机器：`macOS-15.2-arm64-arm-64bit` / Apple Silicon arm64 / 10 CPU；
* Python：`/opt/anaconda3/bin/python3` 3.12.2；
* taverngym 1.0.0（`profile=release`，`source_hash=c807e9aa1a6746ee`，
  game 36.6.3.253932）；
* 命令（2026-10-26）：

```bash
python3 -m hsbg.backends.benchmark --games 10 --seed 0 \
    --engine-games 500 --micro-steps 300 --obs-source both \
    --json runs/backends/bench_20261026.json
```

### 8.2 端到端（`run_episode` + `RandomPolicy`，种 seed+0..N）

| 后端 | 观测源 | 局数 | games/s | steps/s | ms/局 | ms/步 | 平均步/局 | 平均回合 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| hsrl2（`BattlegroundsEnv`, opponent=heuristic） | — | 10 | **6.52** | 257.06 | **153.27** | **3.89** | 39.4 | 7.1 |
| taverngym（`TavernGymEnv`） | features | 10 | **33.88** | 2811.97 | **29.52** | **0.356** | 83.0 | 8.2 |
| taverngym（`TavernGymEnv`） | view | 3 | 3.21 | 278.86 | 311.98 | 3.59 | 87.0 | 8.33 |

> **测量口径（重要）**
> 1. 表中两个后端**用同一套 benchmark harness**（`hsbg/backends/benchmark.py`：
>    `run_episode` + `RandomPolicy` + 固定 seed 集 + 同一台机器、同一次运行）测得，
>    因此"hsrl2 vs taverngym"的比值是可比口径；`view` 行同样来自该 harness。
> 2. 随机策略在同 seed 下会在第 7~9 回合被淘汰；TavernGym 局内决策步更多
>    （英雄选择/多目标选择更频繁），所以"ms/局"与"ms/步"要分开看。
> 3. `view` 模式被 `Game.view()` 的 JSON（含战斗回放）拖慢，**不代表**引擎慢。
> 4. **不要与 `scripts/bench_env.py` 的数字混用**：两者口径不同——
>    `bench_env.py` 默认用**启发式 agent**（HeuristicPolicy，一局 100+ 步、
>    实测本机约 370~450 ms/局），并把 `game_ms`（不含 reset）与逐 step 的
>    `recruit_step_ms`/`end_turn_ms` 分开统计；本表用 `RandomPolicy`（一局约
>    40~90 步）。若在别处看到"1.9 s/局"级别的 hsrl2 数字，通常来自
>    不同机器/负载或"8 人全启发式"配置，不能与本表直接相减/相比。

### 8.3 引擎裸吞吐（无观测/策略开销）

`taverngym.run_bot_games(500, seed=0)`（8 座全 bot、C 侧执行）：

* **275.5 games/s**，**3.63 ms/局**，平均 15.4 回合。

### 8.4 观测/动作微基准（单局随机动作，300 步）

| 项目 | mean µs | median µs | p95 µs |
|---|---:|---:|---:|
| `legal_mask`（245 维 mask 获取） | 0.64 | 0.58 | 0.83 |
| `features` 解码（observe + EntityToken 映射） | 174.8 | 176.1 | 227.2 |
| `view()` + `json.loads`（调试视图） | 3100.9 | 3540.6 | 4229.7 |
| 单步引擎推进（`env.step` 含对手驱动 + 观测） | 317.2 | 300.7 | 448.2 |

**结论**：
1. 引擎本身极快（3.6 ms/局，8 人全 bot），TavernGym 的瓶颈在**观测构建**
   （features 解码 ~175 µs/步，view JSON ~3 ms/步）；
2. 以默认 features 源接入 `EnvLike` 后，端到端仍比 `hsrl2` 后端快约 **5.2×**
   （games/s）、每步快约 **10.9×**；
3. 若后续要榨干吞吐，可把 `EntityToken` 解码换成 numpy 向量化/缓存，
   或直接用上游 `BatchEnv`（多线程、GIL 释放）做并行训练采样——本适配器未封装
   `BatchEnv`（见 §9 后续项）。

---

## 9. 能力边界与已知问题

1. **已注册、默认不启用**：`hsbg.rl.envs.BACKENDS` 现为
   `("auto","real","hsrl2","mock","taverngym")`，`make_env(backend="taverngym")`
   与 `collector/evaluate --backend taverngym` 可用（惰性导入）；`make_env()`
   默认 `hsrl2`、CLI 默认 `auto`，不传参时行为与历史版本一致。`teacher` 类
   引擎感知策略对 taverngym 明确报错（它不是 `BattlegroundsEnv`）。
2. **不能当规则权威**：36.6.3 vs 37.0.0 的差异见 §7；taverngym 的
   `RulesConfig` 含未公布规则的基线假设。
3. **观测源限制**：features 缺 entity_id/target eid/战斗摘要/每回合技能次数；
   view 慢且是调试视图（含隐藏信息，适配器已过滤）。
4. **候选数 > `CANDIDATE_MAX`**：245 维空间可能超过 64，按 spec 上限 padding
   的编码器会丢动作（§5）。
5. **槽位超 spec 上限**：`tavern` 8 / `trinkets` 8 / `choices` 16（§4.3）。
6. **`cancel` 不在 `ActionKind`**（§5）。
7. **quest/timewarp pending 未在默认规则下出现**：默认数据/配置下，
   实测 pending 类型只出现 hero / target / discover / choose_one / trinket /
   hero_power（12 局 bot 对局统计）；quest 需要 `experimental_mode`，
   timewarp 需要 `timewarp_enabled`。这两条映射路径已实现但缺少默认规则下的
   真实对局覆盖（测试未强制构造）。
8. **`Game` 对象不能跨进程 pickle**：观测是纯数据可跨进程；多进程 worker 需在
   进程内 `reset()`。
9. **存档体积**：100~300 KB/局（state_json 含全部内部状态）；精确等价已测。
10. **非法动作惩罚默认 -0.05**（hsrl2 口径）而**非**上游 -0.01；如需对齐上游，
   传 `illegal_penalty=-0.01`。
11. **name 字段**：`EntityToken.name` 用英文名（`card_info` 的 `name`），
    中文名仅在 `view` 元数据/卡表中可得；策略不得依赖。

---

## 10. 验证证据（本机实测，可复现）

```bash
cd /Users/letiangao/HSAgent/HSBRSIM

# 1) 新后端测试：42 passed（含 make_env/collector CLI 注册测试）
python3 -m pytest tests/test_backend_taverngym.py
# 42 passed in 0.89s

# 2) RL 接口层回归（注册后既有行为不变）
python3 -m pytest tests/test_rl_api.py tests/test_rl_collector.py \
    tests/test_rl_evaluate.py tests/test_rl_gym.py tests/test_env_public_contract.py
# 73 passed in 5.89s

# 3) 基准（数字见 §8，结果文件 runs/backends/bench_20261026.json）
python3 -m hsbg.backends.benchmark --games 10 --seed 0 \
    --engine-games 500 --micro-steps 300 --obs-source both \
    --json runs/backends/bench_20261026.json

# 4) CLI 冒烟（注册后）
python3 -m hsbg.rl.collector --policy random --envs 1 --episodes 2 \
    --backend taverngym --out /tmp/tg_collect.jsonl
# backend=taverngym, 2 局 135 步, 8.11 games/s, JSONL header backend="taverngym"
python3 -m hsbg.rl.evaluate --policy random --episodes 2 --backend taverngym
# mean_rank=8.0, 14.71 games/s, errors=0
```

测试覆盖（`tests/test_backend_taverngym.py`，37 项）：

* `EnvLike`/`Observation` 契约、构造参数校验、可选依赖缺失时的安装提示；
* 确定性（reset/轨迹/不同 seed 不同）；
* 候选 == 245 维精确 mask（顺序、不丢不多、`flat_index` 双向映射、
  `CANDIDATE_MAX` 超限标注）；
* **mask 内每个动作都可执行**（决策点存档 → 逐动作独立恢复执行，两处决策点）；
  随机采样 50 个 legal 动作逐步执行；
* 非法动作（越界/非候选/bool/float/负下标）不推进状态、不抛异常；
* 终局 `rank == placements[agent]`（淘汰路径）、冠军路径（8 人全 bot 驱动到
  `game_over`，名次是 1..8 的排列，奖励 = +1）、2 人局 game over；
* `save_state/load_state`：`save→load→save` 字节相等、观测逐字段相等、
  继续 15 步轨迹一致、坏格式报错；
* 两种观测源（features vs view）25 步逐实体交叉验证；
* `run_episode` + `RandomPolicy` + JSONL schema（`validate_record`）、`info` 契约；
* 与上游 `taverngym.SoloEnv` 同 seed/动作序列**逐步状态 JSON 相等**（驱动等价）；
* 基准函数冒烟；
* **注册集成**：`make_env(backend="taverngym")` 类型正确 / `env_kwargs` 透传；
  `make_env()` 与 `backend="hsrl2"` 仍返回 hsrl2 `BattlegroundsEnv`（默认行为不变）；
  `teacher` 对 taverngym 在 collector/evaluate 提前报错；
  collector CLI `--backend taverngym` 采 1 局 JSONL 并逐行 `validate_record`。

---

## 11. 后续（需要 Lead/owner 决策）

1. ✅ **已注册进 `hsbg.rl` 工厂**（Lead 批准）：`hsbg/rl/envs.py` 增加
   `backend="taverngym"` 分支、`BACKENDS` 元组与 `hsrl2` 别名；`collector`/
   `evaluate` 的 `--backend` 透传可用（`teacher` 明确拒绝）；`docs/RL_INTERFACE.md`
   追加 §11。默认后端/CLI 行为不变（回归：73 passed）。
2. **`BatchEnv` 封装暂不做**（Lead 裁决本轮不做）：上游多线程批量环境
   （GIL 释放）可把吞吐再拉一档（引擎裸 275 games/s），但它是"固定 245 维动作/
   向量观测"接口，不是 `EnvLike`，需要单独设计接口。
3. **两引擎同 seed 交叉验证改由 WS2 conformance 负责**（Lead 裁决，避免重复）：
   本后端只提供同 seed 可复现的 bot 对局/精确存档能力作为输入。
4. **观测解码提速**：features 解码 ~175 µs/步，可 numpy 向量化到 ~20 µs
   （收益主要在大批量采集；当前端到端已够快）。
5. **`experimental_mode`/Timewarp**：若需要，需要扩展动作空间映射（245 之外）
   与 pending 类型覆盖，属于后续阶段。
