# 引擎 RL 适配性评估（ENGINE_RL_READINESS）

> 评估对象：`hsrl2/` vendored 引擎（S14 / patch 36.2.2 数据基线，`data/` 3683 定义）。
> 数据来源：`python tools/probe_speed.py --games 20`（本机实测，2026-10-18）。
> API 用法见 `docs/ENGINE_API.md`；本文只谈「把引擎塞进 RL 环境」的适配性。
>
> **结论先行**：引擎的**机制契约、确定性、单动作性能**都足以支撑 RL 训练；
> 环境层要自己补的胶水集中在「合法动作枚举 / PendingChoice 暴露 / 名次记录 /
> 对手驱动」四块；引擎侧有一个**必须绕开的高危性能缺陷**（D-1，实测可让
> 单回合 ERP 慢 40 倍、内存涨 90 倍），以及若干需要镜像私有逻辑/自己做防御
> 的中低危缺口（D-2 ~ D-13）。

---

## 0. 评级速览

| 维度 | 评级 | 说明 |
|------|------|------|
| 机制/规则精度 | ✅ 优 | vendored 引擎，4164 个回归测试；招募/战斗/淘汰/PendingChoice 契约清晰 |
| 单动作性能 | ✅ 优 | 公开 API 动作 mean 0.07 ms、p99 < 1.1 ms（§3.2） |
| 整局性能 | 🟡 良 | 8 人随机驱动整局 **p50 257 ms / p90 318 ms**（无缺陷路径）；有缺陷时 max 3.2 s |
| 内存 | ✅ 优（有缺陷路径除外） | `Game` 状态峰值 ~0.6-0.7 MB/局；`CardDB` ~12 MB/进程；缺陷路径 58.7 MB |
| 确定性 | ✅ 优 | 同 seed+同动作序列逐位一致（A8 实测）；无全局 RNG |
| 可中断性 | 🟡 中 | 只有「动作级」步进；`end_recruit_phase` 同步执行整桌战斗，不可中断/超时/回滚 |
| 合法动作枚举 | 🟡 需自建 | 引擎只给原语；买价/技能可用性/下一档/磁力目标需镜像（§5、D-3） |
| PendingChoice 暴露 | 🟡 需自建 | 队列契约清晰，但「选择 → 观测/动作」映射需环境实现（§5） |
| 名次/终局 | 🟡 需自建 | 引擎不提供 rank，只有淘汰事件与 `heroes` 列表变化（§4、D-5） |
| 多进程并行 | ✅ 优（进程间） | `Game` 不 picklable、模块级状态非线程安全 → **必须用进程**（D-10/D-15） |
| 训练鲁棒性 | 🟡 需防御 | 事件回调异常直接上抛；`sell_minion(Spell)` 会 `AttributeError`（D-9/D-11） |

图例：✅ 可直接用 / 🟡 需环境层胶水/防御 / ❌ 不可用（本表无 ❌）。

---

## 1. 测试方法与硬件

| 项 | 值 |
|----|----|
| CPU | 12th Gen Intel Core i5-12400F（6C/12T） |
| RAM | 32 GB |
| OS | Windows 11 10.0.26200 |
| Python | 3.13.3 |
| 数据 | `data/` S14 / patch 36.2.2，3683 定义 / 247 池内随从 / 75 池内法术 |
| 对局 | 8 人，随机驱动（每座位：英雄技能/Dark Gift/Activate/买/打/刷新/升级/卖），`--games 20 --seed 2000`，异变 1/3 局注入 |
| 计时 | `time.perf_counter()` 墙钟；每个公开 API 调用单独计时 |
| 内存 | `tracemalloc` 单独 pass（不计入耗时） |

复现命令：

```powershell
cd C:\HSagent
python tools\probe_speed.py --games 20 --json runs/probe_speed_native.json
# 诊断：绕开 D-1 缺陷后测「引擎理论上限」
python tools\probe_speed.py --games 20 --strip-entity-tags --json runs/probe_speed_stripped.json
```

> 计时噪声说明：本机同时有其他进程（多 agent 开发）。§3 的 p50/p90 可复现，
> 绝对 max 值可能随机器负载浮动 ±20%。

---

## 2. 结论：RL 环境可以直接依赖什么

**可以依赖（契约稳定）**：

1. 动作 API 的返回语义（`bool` = 是否发生；`GameStateError` = 非法状态）；
2. `end_recruit_phase()` 的完整回合流水线（EoT → 战斗 → 幽灵 → 淘汰 → 下一回合）；
3. `PendingChoice` 的 FIFO 队列 + 「`choose` 只结算不出队」契约；
4. `game.rng` 单一随机源 + `Game(seed=)` 确定性；
5. 状态读取（Hero/Minion/Spell/CardDef/池/事件）字段齐全，可直接序列化观测；
6. 引擎内部没有 I/O / 全局单例 / 线程；单进程内可以顺序跑任意多局
   （每局一个 `Game`，`CardDB` 共享）。

**不能依赖（环境层必须自建/防御）**：合法动作枚举、PendingChoice → 观测/动作、
名次记录、对手脚本、非法动作防御、观测裁剪、冻结/解冻、超时与截断。
逐项见 §5。

---

## 3. 基准数据（20 局 × 8 人）

### 3.1 加载与初始化

| 项 | 数值 |
|----|------|
| `CardDB.load(data/)` | **52-70 ms**，内存 **~11.8 MB** |
| `Game(heroes, db, seed=)` 构造 | mean **0.88 ms**（p99 1.2 ms） |
| `game.start_game()` | mean **4.8 ms**（p99 7.9 ms；含 8 英雄 on_bind + 首回合刷新） |
| 单局完整 reset（含 Hero 构造/DB 复用） | 约 **6-8 ms** |

> 建议：`CardDB` 每进程加载一次；8 个 worker 各自加载 = 8×12 MB ≈ 96 MB，
> 可接受。`CardDB` 可 pickle（1.2 MB / 19 ms），也可由主进程 pickle 后
> 传给 spawn 的 worker。

### 3.2 单次引擎 API 调用耗时（ms）

| API | 调用数 | mean | p50 | p90 | p99 | max |
|-----|-------:|-----:|----:|----:|----:|----:|
| `buy_from_tavern` | 7632 | 0.011 | 0.002 | 0.026 | 0.069 | 1.06 |
| `sell_minion` | 472 | 0.036 | 0.025 | 0.044 | 0.368 | 0.60 |
| `play_minion` | 6117 | 0.019 | 0.002 | 0.064 | 0.139 | 1.94 |
| `play_spell` | 1833 | 0.050 | 0.007 | 0.096 | 0.646 | 1.30 |
| `refresh_tavern` | 1681 | 0.467 | 0.439 | 1.175 | 2.227 | 4.13 |
| `upgrade_tavern` | 499 | 0.008 | 0.006 | 0.011 | 0.045 | 0.39 |
| `use_hero_power` | 1681 | 0.066 | 0.006 | 0.046 | 1.032 | 2.67 |
| `use_activate` | 591 | 0.128 | 0.028 | 0.455 | 1.010 | 3.14 |
| `use_dark_gift` | 1681 | 0.125 | 0.002 | 0.430 | 0.814 | 1.33 |
| **全部动作聚合** `action_step` | 22187 | **0.067** | 0.004 | 0.089 | **1.088** | 4.13 |

> 口径：`action_step` = 一次公开动作 API 调用（不含 `PendingChoice` 结算、
> ERP、战斗）；含**失败调用**（如金币不足的 buy），所以是偏保守的上界。
> 最贵的常规动作是 `refresh_tavern`（池扫描 + 加权列表，p50 0.44 ms），
> 这也是环境里 `reroll` 候选要尽量少重复调用的原因。

### 3.3 单场战斗 / `end_recruit_phase` / 整局

| 指标 | 有缺陷（原生） | 绕开 D-1 后（诊断） |
|------|---------------|---------------------|
| `run_combat` 单场 | n=871 mean 8.0 / p50 1.47 / p90 2.83 / **p99 410 / max 590** | mean 1.51 / p50 1.47 / p90 2.76 / **p99 4.57 / max 6.47** |
| `end_recruit_phase` 单回合 | n=271 mean 33.3 / p50 **11.9** / p90 22.5 / **p99 531 / max 600** | mean 11.9 / p50 **10.7** / p90 21.0 / **p99 32.1 / max 35.2** |
| 整局（到 finished） | n=20 mean **544** / p50 **281** / p90 773 / **p99 3097 / max 3240** | mean **257** / p50 **257** / p90 318 / **p99 332 / max 334** |
| 每回合平均（整局/回合） | ~40 ms（被尾部长尾拉高） | ~19 ms |
| 每次「引擎交互」平均 | 0.57 ms | 0.27 ms |

**每局规模（随机驱动，8 座位全部行动）**：

| 指标 | 均值 | p50 | p90 | max |
|------|------|-----|-----|-----|
| 回合数 | 13.55 | 13 | 16 | 17 |
| 引擎交互步数（动作+选择+ERP） | 950.9 | 940.5 | 1100.2 | 1183 |
| 其中：动作 API 调用 | 909.9 | 900.5 | 1058.6 | 1135 |
| 其中：ERP | 13.55 | 13 | 16 | 17 |
| 每局 `PendingChoice` 结算 | ~112 | — | — | — |

> 20 局全部正常结束、0 崩溃（随机驱动也会触发英雄技能/Activate/Dark Gift/
> 任务/饰品/异变/幽灵战/淘汰）。「引擎交互步数」是**整桌 8 座位**的总和；
> 单智能体决策步约为其 1/6~1/8，再叠加自己的选择步（估 150-300 步/局）。

### 3.4 内存

| 项 | 数值 |
|----|------|
| `CardDB`（3683 定义） | **~11.8 MB** / 进程 |
| `Game` 状态（start_game 后，tracemalloc 增量） | **~0.09 MB** |
| `Game` 单局峰值（正常路径） | **0.6-0.7 MB** |
| 单局峰值（**命中 D-1 缺陷**，seed 2001） | **58.7 MB**（current 44.4 MB） |
| 每局 `game.rng.decisions` | mean 1367 条（max 1771），< 0.2 MB |
| 终局残留 `pending_hand_queue` | max 55 张 |

→ 8 进程并行 = 8×(12 + 1) ≈ **~104 MB** 引擎侧常驻，预算充足。
缺陷路径（D-1）会让个别局内存瞬时 ×90，**多进程下可能触发 OOM**，必须规避。

### 3.5 吞吐估算（用于训练规划）

以「环境 = 1 智能体 + 7 脚本对手，随机驱动对手」计：

* **无 D-1 缺陷**：整局 257 ms → **~3.9 局/s/核**；8 进程 ≈ **31 局/s**；
  折算每局约 950 次引擎交互 → ~29k 引擎交互/s。
* **命中 D-1 缺陷**：整局 mean 544 ms、p99 3.1 s → 训练吞吐下降 2-10 倍，
  且单步时延抖动达数百 ms（对 PPO 的 rollout 收集是灾难）。
* **单智能体决策步成本**（估算）：动作 0.07 ms + 观测构建 ~0.1 ms（21 实体
  微基准 98 µs）+ 候选枚举 ~0.01 ms ≈ **0.2 ms**；`end_turn` 步额外
  摊上一次 ERP（clean ~12 ms / 13.5 回合 ≈ 0.9 ms）。**远低于 ENV_SPEC
  §8 的 5 ms/步目标**（前提：规避 D-1）。
* 观测/候选规模：实测一局终盘单座位 `board 7 + hand ≤10 + tavern ≤7 +
  trinkets 2`，实体 token ≤ 26；候选动作典型在几十到上百个（示例状态实测
  84 个：买 + 打×位置 + 卖 + 刷新/升级/冻结/技能/Activate…），
  `hsbg/env/spec.py` 的 `CANDIDATE_MAX=64` 需要环境层截断/排序策略（见 §7）。

---

## 4. 确定性与可中断性

### 4.1 确定性 ✅

* 引擎随机性**只有一个入口** `game.rng`：`hsrl2/` 全目录只有 `rng.py`
  `import random`；`GameRNG` 只接受构造 seed。
* 实测（A8）：同一 seed、同一 heroes 列表、同一动作/选择序列 → 两次轨迹
  （每回合酒馆内容、英雄血量、turn）**完全一致**；不同 seed 不同。
* 重放约束（ENGINE_API §8.3）：同版本 + 同数据 + 同 agents 随机源隔离 +
  **不并发线程跑同进程两局**。
* 风险点：
  * `entity.py` 的 `_stats_gained_suppress_depth` 是**模块级**计数
    （战斗快照复原抑制窗口）→ 同进程多线程跑两局会互相静默事件广播。
    **并行必须用进程**（`hsbg/env/vec_env.py` 的 multiprocessing 方向正确）。
  * 环境自己的随机（英雄选择、对手策略）必须由环境 seed 派生，且不要用
    `game.rng`——引擎 `rng.decisions` 审计日志依赖它，混用会破坏回放。

### 4.2 可中断性 🟡

* 引擎 API 全部**同步**：没有 timeout、cancel、pause、rollback。
* 粒度为「一次 API 调用」：单动作通常 < 5 ms；但
  `end_recruit_phase()` 是**原子**的——内含 EoT + 全部配对战斗 + 幽灵战 +
  淘汰 + 下一回合副作用，clean p90 21 ms / p99 32 ms（D-1 命中时 600 ms）。
  环境**不能**在战斗中途把选择暴露给策略（ENV_SPEC 已规定战斗内选择由环境
  自动结算）。
* 死循环保护：`COMBAT_MAX_ATTACK_ROUNDS=2000`、`DEATH_MAX_WAVES=100`、
  `QUEUE_MAX_ACTIONS=20000`，超限抛 `CombatLoopError`（不是静默截断）。
  环境必须 `try/except (GameStateError, CombatLoopError)` 并丢弃该局。
* 建议：环境对 `end_turn` 步做 wall-clock 计时；若单步 > 2 s（D-1 症状）
  记录告警并考虑丢弃/重开该局（训练不应被单局拖死）。

---

## 5. RL 环境必须自己补的胶水层（按优先级）

> 建议落点沿用 `docs/ARCHITECTURE.md`：`hsbg/env/driver.py`（枚举/应用/
> 选择）、`observation.py`、`game_env.py`、`hsbg/agents/`。

| # | 胶水层 | 内容 | 参考 |
|---|--------|------|------|
| G1 | **合法动作枚举** | 酒馆/手牌/棋盘 → 候选；每动作前置条件；买价镜像；技能可用性镜像；升级落点；磁力目标；目标组合 | ENGINE_API §4（含参考实现） |
| G2 | **PendingChoice 暴露** | 队列 FIFO；`owner is agent` 时转成 `phase="choice"` 观测；对手选择自动结算；options → EntityToken 映射（str/实体/tuple/CardDef/None） | ENGINE_API §5.3-5.5 |
| G3 | **名次记录** | 监听 `hero_eliminated` 记录淘汰顺序；`final_ranks` = 淘汰顺序反序 + 存活者第 1；智能体被淘汰即 terminated | ENGINE_API §6.6 |
| G4 | **对手脚本** | 7 个同构对手：逐动作走公开 API + 每次动作后结算其选择 + `max_opponent_actions` 保护 + 失败即停 | ENGINE_API §10 |
| G5 | **观测裁剪** | 只暴露：自己完整信息 + `last_opponent_warband`（上一场战前战团）+ 大厅公开信息；**禁止** `next_opponent_warband`（对手当前棋盘）/对手手牌/金币/酒馆 | ENV_SPEC §7 |
| G6 | **非法动作防御** | 候选永远合法；但外部调用/对手策略仍可能非法 → `try/except GameStateError`、检查 bool 返回、失败回滚到同一观测（不推进状态）、`info["invalid"]=True` | ENGINE_API §9 |
| G7 | **冻结/解冻** | 引擎只有冻结；解冻无 API（D-2）。要么把 freeze 建模为一次性，要么 `hero.clear(GameTag.FROZEN)`（触碰内部状态） | D-2 |
| G8 | **结束回合与全桌驱动** | 没有 per-player end turn：智能体 `end_turn` → 驱动全部对手 → 一次 `end_recruit_phase()`；驱动期间用 `list(game.heroes)` 快照（淘汰会改列表） | ENGINE_API §2.5/§6.1/§10 |
| G9 | **奖励与终局** | 名次奖励、生命 delta（`health+armor`）、战斗伤害（`CombatResult.capped_damage`）、棋盘战力；`finished`/自己被淘汰 → terminated；`max_turns`/`max_steps` → truncated | ENV_SPEC §5 |
| G10 | **DB/进程生命周期** | `CardDB` 每进程只加载一次；`Game` 不可 pickle（D-10）；vectorized env 用 spawn 进程 + 每 worker 自建 Game | §3.4, D-10 |
| G11 | **观测构建** | 实体 token（card_id/type/zone/slot/atk/health/tier/cost/races/keywords/golden/uuid）+ 全局标量；注意实体**没有** `card_type` 属性、法术**没有** `tech_level` 属性 | ENGINE_API §7 |
| G12 | **回放/审计** | 记录 (seed, heroes, 动作序列, 选择下标)；`game.rng.decisions` 可作二级审计；不要依赖真实时间 | ENGINE_API §8 |

工作量粗估：G1 是最大块（约 250-400 行；ENGINE_API §4 已给 80% 骨架），
G2/G3/G4 各 100-200 行，其余为小件。

---

## 6. 引擎侧真正的限制/缺陷（有代码/运行证据）

> 严重度：**HIGH** = 会导致训练不可用/性能崩坏；**MEDIUM** = 需要环境层
> 额外工作或存在崩溃风险；**LOW** = 维护性/一致性问题。
> 原则：**只给最小修复方案，本轮不改引擎**（vendored，改动需 Lead 批准）。

### D-1（HIGH）`Minion.snapshot_state()` 会 deepcopy 实体引用 tag → 战斗开场 100 倍慢、内存 ×90

**证据**

* `hsrl2/minion.py:202`：

  ```python
  def snapshot_state(self) -> dict:
      import copy
      return {"tags": copy.deepcopy(self.tags), "buffs": [b for b in self._buffs]}
  ```

* `GameTag.KILLER` 的值是 **Entity**（`minion.take_damage(source=...)` 设置；
  招募期可被 `Damage` 动作 / `recruit_phase_attack` 反击留下）。
  `run_combat` 开场对双方棋盘每个随从调 `snapshot_state()`
  → `deepcopy(KILLER)` 沿 `Entity.game → Game → heroes/db/events/pools`
  拉出**整张对象图**。
* 实测（seed 2001，同一驱动）：命中 7 次战斗共 14 个污染随从 →
  * 整局 **3564 ms → 496 ms**（清除该 tag 后，快进 7.2 倍）；
  * ERP 总耗时 **3479 ms → 315 ms**（快 11 倍），单回合 **~600 ms → ~26 ms**；
  * tracemalloc 峰值 **58.7 MB → 0.6 MB**（98 倍）；
  * 20 局统计：14/871 场战斗被污染（1.6%），但 3/20 局整局被拖到 0.5-3.2 s；
    `run_combat` p99 从 4.6 ms 涨到 410 ms。
* 同文件 `_frozen_clone`（`game.py:107`）已明确规避过同一陷阱：
  「实体引用类值如 KILLER 直接丢弃，避免 deepcopy 拉出整张对象图」——
  `snapshot_state` 是**同危险的两条路径中漏掉的一条**。

**最小修复方案（建议，不改引擎）**

1. `Minion.snapshot_state()` 复制 tags 时跳过 `isinstance(value, Entity)`
   （与 `_frozen_clone` 同口径）；或
2. `Entity.__deepcopy__` 对 `game` 引用返回 `None`；或
3. `Game.run_combat` 在 snapshot 前临时清 `KILLER`（治标）。

修复后应加回归测试：棋盘随从带 `KILLER` 时 `snapshot_state()` 的时间/对象数
不随 `game` 规模增长。

**环境层规避（在引擎修复前）**：环境可以在 `end_recruit_phase` 前扫一遍
存活棋盘，`m.clear(GameTag.KILLER)`（KILLER 只在效果内部语义使用、且战斗内
会被设置，招募期清掉对可见行为无影响——需要回归测试验证）。我们的基准
`--strip-entity-tags` 就是这个规避的测量版。

### D-2（MEDIUM）没有「解冻」API

**证据**：`hsrl2/game.py:1801` 只有 `freeze_tavern(hero)` 设置
`hero.FROZEN`；全库只有 `refresh_tavern` 里会 `clear(FROZEN)`
（一次性冻结）。`probe_api` A3 断言 `not hasattr(game, "unfreeze_tavern")`。

**影响**：真实游戏可以点掉冻结；环境若把 freeze 当可逆动作，要么不能实现，
要么直接改引擎内部 tag（`hero.clear(GameTag.FROZEN)`，破坏封装且无事件）。

**最小修复方案**：新增 `Game.unfreeze_tavern(hero)`（清 tag + fire
`tavern_unfrozen`），或给 `freeze_tavern` 加 `frozen: bool = True` 参数。

**环境规避**：结算步只保留「冻结」候选（不提供解冻），或接受直接清 tag
（记录为已知偏离）。

### D-3（MEDIUM）缺少只读查询 API，环境必须镜像引擎私有逻辑

**证据**：以下判定都内联在动作函数里或私有方法中，没有公开查询：

| 判定 | 现状 |
|------|------|
| 买价 | 内联 `buy_from_tavern`（含免费额度/折扣/健康购买，约 100 行） |
| 免费随从额度是否命中 | `Game._take_free_minion_buy`（**会消费**，不能预检） |
| 英雄技能是否可用 | 内联 `use_hero_power`（`available`/次数/费用/目标数） |
| 下一升级档位 | `Game._next_existing_tier`（私有；异变 101/102 阶梯） |
| 磁力目标是否合法 | `Game._magnetic_valid`（私有；含卡 id 例外） |
| 刷新是否可支付 | 内联 `refresh_tavern`（免费/健康/覆盖价） |
| 英雄枚举 / 全卡遍历 | 无公开迭代器，实际用 `db._by_id` |

**影响**：这些镜像一旦与引擎漂移，候选会变成「非法动作」（ENV_SPEC 明文
禁止），或漏掉合法动作。维护成本集中在引擎升级时。

**最小修复方案**：在 `Game` 上暴露只读方法（纯查询、无副作用）：
`quote_buy_cost(hero, entity)`、`can_use_hero_power(hero, power_id)`、
`next_tavern_tier(hero)`、`magnetic_targets(hero, minion)`、
`can_refresh(hero)`；`CardDB.iter_defs()` / `hero_defs()`。

**环境规避**：按 ENGINE_API §4.3/§4.5/§4.6 镜像，并加一条
「镜像 vs 引擎实际结果」的对拍测试（本仓库 `tools/probe_api.py` A4
已有先例：买价镜像 == 实际扣款、技能镜像 == 实际结果）。

### D-4（MEDIUM）API 错误风格不一致：`refresh_tavern` 抛异常，其它动作返回 False

**证据**：`refresh_tavern` 金币不足时走
`spend_gold → raise GameStateError`（`game.py:486/1811`）；而
`buy_from_tavern` / `upgrade_tavern` / `play_*` / `use_*` 在同类前置失败时
返回 `False`。实测同一条 `游戏步` 里两种失败模式并存。

**影响**：环境若只按返回值处理，会在「刷新」上抛异常打断 rollout；
若统一 try/except，又会吞掉真正的非法状态。

**最小修复方案**：统一为「可支付性失败返回 False + 状态不变」，
或统一抛异常并在文档声明；两者择一即可。

**环境规避**：动作应用统一 `try/except GameStateError`（ENGINE_API §9.2
模板），并把 refresh 的候选生成做前置金币/免费刷新过滤。

### D-5（LOW-MEDIUM）没有名次/淘汰顺序 API

**证据**：全库 grep 无 `rank`/`placement` 字段；`_process_eliminations` 只
fire `hero_eliminated` 并把英雄从 `game.heroes` 移除。

**影响**：环境必须自己监听事件记录顺序（标准做法见 ENGINE_API §6.6），
否则名次奖励无从计算；同回合多人淘汰时只能按事件顺序（引擎按列表顺序发）。

**最小修复方案**：`Game.elimination_order: List[Hero]` +
`Game.rank_of(hero) -> int`（或终局 `final_ranking()`），在
`_process_eliminations` 内维护。

### D-6（LOW）`GameRNG.decisions` 无上限增长

**证据**：每局 mean 1367 条（max 1771）`(label, repr)` 审计条目；
`GameRNG.__init__` 里 `self.decisions = []`，无清理/开关。

**影响**：单局可忽略（<0.2 MB）；若环境长期持有 Game 或做大量重放，
需要定期清理。对吞吐无显著影响（每局 1300 次 append）。

**最小修复方案**：`GameRNG(seed, audit=False)` 或 `decisions` 环形缓冲。

### D-7（LOW）`game.choice_policy` 是死字段

**证据**：`game.py:193` 赋值 `"first"`，全库无读取点（注释里多处提到
「自动化层 choice_policy 决策」，但引擎从未消费）。`PendingChoice` 没有内建
默认选项策略。

**影响**：容易误以为引擎会自动结算选择 → 实际不会（未结算的选择会跨回合
积压）。环境必须自己实现 FIFO + 默认/策略选择。

**最小修复方案**：删除字段，或在 `Game` 提供
`auto_resolve_choices(policy=...)` 辅助。

### D-8（LOW）CardDB 无公开迭代器

**证据**：`CardDB` 只有 `get/by_dbf/pool_minions/pool_spells/dark_gifts/
trinket_offer_pool/__len__`；英雄枚举/全量遍历只能 `db._by_id`。

**影响**：环境代码依赖私有属性（引擎重构即破坏）。**最小修复**：
`CardDB.defs()` / `CardDB.hero_defs()`。

### D-9（MEDIUM）`sell_minion` 不校验实体类型 → Spell 会 AttributeError 并污染状态

**证据**（probe A9 实测）：

```python
hero.hand.append(spell)
game.sell_minion(hero, spell)
# AttributeError: 'Spell' object has no attribute 'is_golden'
# 事后: hero.gold == 1（已加钱）、spell 已从 hand 移除、spell.zone 仍是 HAND
```

`game.py:986` 只检查「在 board 或 hand」，随后
`minion_pool.release_minion_entity(minion)` 假定是 Minion。

**影响**：环境候选若把 Spell 当 Minion 卖 → 训练进程崩溃 + 状态污染。
**最小修复**：`sell_minion` 开头 `if not isinstance(minion, Minion): return False`。
**环境规避**：sell 候选只从 `hero.board`（`list[Minion]`）生成
（ENGINE_API §4.2）。

### D-10（MEDIUM）`Game` 不可 pickle，也没有 clone/snapshot

**证据**：`pickle.dumps(game)` → `AttributeError: Can't get local object
'RokaraScript.on_bind.<locals>.on_death'`（监听器闭包）。
`copy.deepcopy(game)` 可用但 turn 1 就要 **205 ms**，且会复制整张实体图，
语义脆弱（监听器/脚本身份、RNG 状态需人工修复）。

**影响**：无法直接做 MCTS/beam search 的状态分叉，也无法把 Game 放进
回放池/Dataset。**最小修复**：提供显式 `Game.clone()`（深拷贝 + 重绑
`game`/`controller` 引用 + 监听器表重建）或「动作日志 + 从 seed 重放」的
快照协议。

**环境规避**：需要分叉时用「seed + 动作序列从头 replay」；训练 rollout
不需要 clone。

### D-11（MEDIUM）脚本/监听器异常直接上抛，无沙箱

**证据**：`EventBus.fire` 明确「回调异常向上传播（禁止静默吞掉）」；
`run_combat` 的 `finally` 会尽力复原棋盘，但异常仍会终止本轮调用。
全库 1200+ 脚本、43 Dark Gift、331 饰品，随机测试 20 局 0 崩，
但**不能假设永远不崩**（AGENTS 记录过历史压测崩溃并修复的案例）。

**影响**：训练进程一次未捕获异常 = 整个 rollout 崩溃。
**最小修复**：可选 `Game.strict=False`（把脚本异常记录到
`game.script_errors` 并继续）；或环境层兜底。
**环境规避**：`try/except (GameStateError, CombatLoopError, Exception)`，
标记 `info["engine_error"]` 并丢弃该局（不要重试同一动作）。

### D-12（LOW）`pending_hand_queue` 无上限

**证据**：满手牌时生成卡无限排队；实测随机驱动终局残留 max **55 张**
（`probe_speed` 输出）。语义上正确（RULES §3.3 等待），但长局会积累
「未来手牌」，让下一回合瞬间入手多张。

**影响**：观测里看不到这些卡（不在 `hand`），但奖励/战力预测会滞后。
**环境规避**：观测可暴露 `len(game.pending_hand_queue)` 作为标量特征；
奖励用实际 `hand/board` 即可。**最小修复**：给队列加软上限/诊断计数。

### D-13（LOW）`Hero` 构造不校验 card_id

**证据**：`Hero("NOT_A_REAL_CARD")` 正常构造；`hero_power_def()` 返回
`None`、`hero_power_ids()` 为空、`use_hero_power()` 恒 False（静默无技能）。

**影响**：环境若从脏数据/拼写错误取英雄 id，会得到「没有技能」的弱英雄而
不报错。**最小修复**：`Hero.__init__` 增加可选 `db` 校验或
`Game._validate_heroes()`。**环境规避**：只从 `CardType.HERO` 的合法 id 池选。

### D-14（LOW）没有「当前阶段 / 我可以结束回合吗」API

**证据**：无 `phase` 字段；`in_combat` 只在 `run_combat` 内部可见。
环境要自己维护状态机（ENGINE_API §2.1）。

**影响**：环境层状态机写错时会出现「在 choice 阶段发动作」等错位。
**最小修复**：`Game.phase` 属性（recruit/combat/choice/game_over）。

### D-15（MEDIUM，架构选择）模块级状态使**线程**并行不安全

**证据**：`hsrl2/entity.py:31` `_stats_gained_suppress_depth` 是模块全局；
`run_combat` 的复原窗口依赖它。若同进程两个线程各跑一个 Game，A 局的
抑制窗口会静默 B 局的 `stats_gained` 广播（脚本被动失效/数值不一致）。

**影响**：排除「线程池向量化」方案。**环境规避（推荐）**：用
`multiprocessing`（spawn）进程池，每进程独立 DB + Game（ARCHITECTURE 的
`vec_env.py` 方向）。**最小修复**：把抑制深度改成 `contextvars`/per-Game。

---

## 7. 对训练侧的影响与建议

1. **先修/绕开 D-1 再谈吞吐**：否则 p99 单步 600 ms、内存 59 MB/局，
   PPO 的 rollout 时间分布会被少数「毒局」支配。建议环境在
   `end_recruit_phase` 前清 `KILLER`（测量已证明安全且有效），或推动
   Lead 批准引擎侧一行修复。
2. **并行用进程**（D-10/D-15）：Windows spawn + 每 worker 自建 DB/Game；
   `Game` 不可 pickle，别把 Game 传进 worker。
3. **动作应用必须防御**（D-4/D-9/D-11）：统一 `try/except` + 检查返回值；
   非法动作返回原观测 + 惩罚，绝不崩。
4. **候选生成先对拍再上线**（D-3）：把 ENGINE_API §4 的镜像实现与「引擎
   实际返回/扣款」做随机对拍测试（probe_api A4 已有模板）。
5. **观测按 ENV_SPEC 裁剪**（G5）：只暴露自己 + `last_opponent_warband`
   + 大厅公开信息；`next_opponent_warband` 是隐藏信息，禁止入观测。
6. **奖励用引擎可见量**：`health+armor`、`CombatResult.capped_damage`、
   棋盘 `atk+max_health`、终局名次（自建 RankTracker）。
7. **训练稳定性**：`max_turns`/`max_steps` 截断（随机对局 13-17 回合结束，
   但异常局可能到 turn-cap）；对 `CombatLoopError` 局直接丢弃。

---

## 8. 复现与检查清单

```powershell
cd C:\HSagent

# 1) API 契约（182 条断言：动作/选择/战斗/确定性/坑）
python tools\probe_api.py --verbose

# 2) 性能/内存基准（原生，含 D-1 影响）
python tools\probe_speed.py --games 20 --json runs\probe_speed_native.json

# 3) 诊断上界（绕开 D-1；仅测量用，不改引擎）
python tools\probe_speed.py --games 20 --strip-entity-tags --json runs\probe_speed_stripped.json

# 4) 引擎回归（改动引擎前必跑；本轮未改引擎）
python -m pytest hsrl2\tests -q
python tools\smoke_random_games.py --games 8 --seed 2000
```

**RL 环境上线前的最低验收**（建议写入 `tests/`）：

- [ ] 同一 env seed 两次 rollout 的观测/动作/奖励序列完全一致；
- [ ] 20 个 seed × 8 人局 0 崩溃、0 非法候选（候选执行前可自检）；
- [ ] 候选枚举与引擎真实结果对拍（买价/技能/升级/磁力）；
- [ ] 智能体淘汰/冠军两种终局都能正确 terminated + 名次；
- [ ] `end_turn` 单步 p99 < 100 ms（规避 D-1 后实测 32 ms）；
- [ ] 8 进程 vec_env 吞吐 ≥ 10 局/s。

---

## 附录：环境层「最需要注意的 5 个坑」（摘要）

1. **买只进手牌**：`buy_from_tavern` 之后必须 `play_minion` 才上场；
   酒馆法术买后要 `play_spell`（施放免费）。
2. **`PendingChoice` 必须 `pop(0)` 再 `choose(i)`**：`choose` 不出队，
   漏 pop 会重复结算；开局/动作后/ERP 后都要 FIFO 结算，且队列里只应
   留智能体自己的选择。
3. **`refresh_tavern` 金币不足会抛 `GameStateError`**（其它动作返回
   False）——动作应用必须统一 try/except；候选生成先过滤刷新费。
4. **`game.heroes` 会被淘汰原地移除、引擎不提供名次**——每步重新取
   heroes；监听 `hero_eliminated` 自建 RankTracker（第一个死的 = 第 N 名）。
5. **`Minion.snapshot_state()` 的 deepcopy 缺陷（D-1）**：任何带
   `GameTag.KILLER` 的随从进入战斗，整局会慢 7-11 倍、内存 ×90；
   环境需在 ERP 前清 `KILLER`（或推动引擎侧修复），否则训练吞吐/稳定性
   不可控。

（第 6 个顺带提醒：`sell_minion` 不校验类型，只对 `Minion` 生成 sell 候选；
别把 Spell 传进去。）
