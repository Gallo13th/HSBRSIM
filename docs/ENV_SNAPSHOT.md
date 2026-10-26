# ENV_SNAPSHOT — 环境级精确存档/恢复与结构不变量（WS5）

> 模块：`hsbg/env/snapshot.py`、`hsbg/env/invariants.py`
> 测试：`tests/test_env_snapshot.py`、`tests/test_env_invariants.py`
> 脚本：`python scripts/validate_env.py --check-invariants`（默认关闭）
> 参照实现：AutoTavern `crates/taverngym/src/invariants.rs`（结构不变量 +
> pool 守恒）、TavernGym `EnvLike` 的确定性/可复现要求。

本文是 WS5 的契约、验收证据与**已知问题登记**（含复现命令/实测数字）。
改动 `hsbg/env/snapshot.py` / `hsbg/env/invariants.py` 前必读。

---

## 1. 定位与 API

`hsbg.planning.checkpoint` 提供的是**引擎层**快照（`Game` 的 clone）；
RL 环境在引擎之上还有一层状态：名次追踪（`_rank_by_hero` /
`_elimination_order`）、大厅视图（`_all_heroes`）、事件监听绑定、
每步候选（`_step_actions`）、观测缓存（`_obs`）、预算/无进展计数、
统计与选择留痕。只 clone `Game` 无法恢复这些（恢复后事件回调仍指向
快照时的“幽灵 env”，名次映射的 `id(hero)` 键全部失效）。

`hsbg/env/snapshot.py`：

```python
from hsbg.env.snapshot import snapshot, restore, clone_env

snap = snapshot(env)              # O(几 ms)；不改变原 env
...                               # env 被 step 任意多次
restore(env, snap)                # 原地恢复：obs/候选/统计/RNG 逐位一致
obs, r, ... = env.step(action)    # 与“不 snapshot 的原始轨迹”逐步一致
twin = clone_env(env)             # 独立 env 副本（可并行推进）
```

| API | 语义 |
|---|---|
| `snapshot(env) -> EnvSnapshot` | 生成**不可变**环境快照；不改变 env。不可快照状态抛 `SnapshotError`（见 §3） |
| `restore(env, snap, verify=True) -> env` | 原地恢复；`verify=True` 校验 digest/观测/候选/统计（默认开）。同一快照可反复恢复 |
| `clone_env(env) -> BattlegroundsEnv` | 快照 + 恢复到新 env 外壳；与源 env 相互独立 |
| `canonical_observation(obs)` | 把引擎**随机 uuid 派生**字段（`entity_id`、`PendingChoice.kind` 内嵌 uuid）归一化，用于跨轨迹观测比较（见 §5.4） |
| `SnapshotError` | 快照/恢复契约违反（不可快照状态、快照被外部修改、目标 env 不兼容等） |

### 快照覆盖范围

* **引擎状态**：`clone(env.game)`（`hsbg.planning.model.clone`）——含 RNG
  内部状态、`PendingChoice` 队列、`pending_hand_queue`、
  `deferred_actions`、卡池、卡牌缓存、战斗记忆等；
* **名次追踪**：`_rank_by_hero` 按 `hero.uuid` 存（恢复后 `id()` 全变）；
  `_elimination_order` 存被淘汰英雄最小重建信息
  （uuid/name/card_id/health/armor/tier），恢复时重建 `Hero` 对象；
* **大厅视图**：`_all_heroes` 与 `game.heroes` 在 `reset` 里是**同一个
  list 对象**（§5.3）——恢复时重建该别名关系；
* **事件监听**：快照时把绑定到本 env 的监听器（`HERO_ELIMINATED` /
  `COMBAT_END`）从临时 clone 源上**剥离**（避免 clone 出“幽灵 env”），
  记录 `(event, 位置, 回调名, owner uuid, once/survives_combat/_fired)`；
  恢复时重建 `Listener`：回调绑到**目标 env**、owner 指向恢复后的智能体
  英雄；末尾再扫描一次监听器表把残留旧 env 回调重绑到目标 env（双保险）；
* **环境计数器/历史**：`_step_count`/`_turn_count`/`_done`/
  `_was_truncated`/`_budget_turn`/`_actions_this_turn`/`_no_progress`/
  `_stats`/`_turn_stats`/`_errors`/`_auto_resolved_choices`/
  `_choice_failures`/`_engine_error`/`_seed`/`_episode`/`_agent_index`；
* **观测与候选**：恢复后调用真实 `env._observe()` 重建 `_obs` 与
  `_step_actions`；为不污染统计，重建期间把 `_stats` 临时替换为“丢弃
  写入”的统计袋，结束后恢复快照统计并校正
  `obs.extra["env_stats"]` → 恢复出的观测与快照时刻**逐字段相等**。

### clone 回调重绑补丁（WS5-CLONE-1/2，规划模块修复后可回退）

`hsbg.planning.model.clone` 的闭包重绑不完整，快照/恢复额外做完整重绑：

1. **函数默认参数不重绑**（WS5-CLONE-1）：引擎脚本大量使用
   `def on_x(..., _owner=hero)` 捕获绑定英雄（`hsrl2/scripts` 内 20+ 处），
   clone 后回调仍写**原** hero（实测 seed=42 恢复后 P4 Edwin
   `_edwin_buys` 计数写进原对象 → hero_power 增益差 1）；
2. **共享可变捕获被逐函数复制**（WS5-CLONE-2）：同一 `state` dict 被多个
   闭包共享时（Dark Gift `_gift_replication`/`_gift_incubation` 的 SoT+EoT
   闭包对）被拆成独立副本（实测 seed=3 恢复后 EoT 复制效果永不触发）；
3. **图外实体未映射 controller**：只被回调捕获的已离场来源随从（“承诺
   型”效果）若按原对象共享，`hero is source.controller` 判等失败（实测
   Laboratory Assistant 的 Fodder 承诺在恢复后失效）；
4. **递归闭包**（如 `Game.play_spell._continue` 自引用）会无限展开；
5. **frozen dataclass**（`CardDef`）被复制成空壳（`name=""`）→ choose
   结算效果漂移。

实现：`_CloneRebinder` 在 `clone(..., rebind=False)` 之后统一重绑：
共享映射保持闭包间可变状态身份；实体按 uuid 映射（含默认参数
`_owner=hero`）；图外实体重建为脱离副本并映射 `controller`/`game`；frozen
只读值对象直接共享；递归闭包用“占位函数 + 先登记 memo 再填 cell”。
**建议上游**：把同样逻辑并入 `hsbg/planning/model.py::_rebind_function`
（覆盖 `__defaults__`/`__kwdefaults__` + 共享捕获 memo），本补丁即可删除。

---

## 2. 恢复契约（可测试断言）

`restore(env, snap, verify=True)` 默认断言（失败抛 `SnapshotError`）：

1. `state_digest(snap.game) == snap.game_digest`（快照未被外部推进/修改）；
2. 目标 env `num_players`/`agent_index` 与快照一致；
3. 恢复后 `state_digest(env.game) == snap.game_digest`；
4. 恢复后 `env.current_observation == snap.obs`（逐字段）；
5. `env.legal_actions()` 签名序列 == 快照候选；
6. `env.stats == snap.stats`；
7. `_all_heroes is env.game.heroes`（大厅视图别名，见 §5.3）；
8. env 监听器已重绑到目标 env、owner = 恢复后的智能体英雄。

`verify=False` 是热路径快路径：跳过上述 1/3（`state_digest` 全图遍历，
见 §6 开销拆解），仍恢复全部状态并重建观测。

**语义验收测试**（`tests/test_env_snapshot.py`）：
snapshot → 原始 env 继续跑 N 步记录轨迹 → restore → 相同动作序列重跑，
逐步比较「观测结构（`canonical_observation`）/候选/奖励/终止/info」；
覆盖 heuristic/random 对手、淘汰局、终局。

---

## 3. 快照限制（明确不可用/不支持）

1. **终止后不可快照**：`_done=True`、`close()` 之后、reset 之前、
   智能体已死亡 → 抛 `SnapshotError`。终局回放请保存 `obs`/`info`。
2. **只在决策步稳态有效**：要求 `_turn_count == game.turn` 且
   `_budget_turn == game.turn`（`reset()`/`step()` 正常返回后成立；外部
   直接改 game 状态后不保证）→ 不满足时抛错而不是产出不一致快照。
3. **对手策略实例状态不重建**：`restore` 保留目标 env 的 `_policies` 实例；
   `clone_env` 优先 `deepcopy` 策略（不可拷贝时共享）。`HeuristicPolicy`
   内部状态按 `(id(hero), turn)` 懒重置，决策步边界上不影响逐步一致性；
   **自定义跨回合有状态对手**不在契约内。
4. **env 监听器不支持 condition/partial**（当前只有普通绑定方法）：
   不满足时 `snapshot` 抛错而不是静默丢监听器。
5. **策略外部 RNG/采样器状态**不在 env 状态内，需调用方自行管理。
6. **快照不可跨构造配置恢复**：`restore` 到 `num_players`/`agent_index`
   不同的 env 抛错。

---

## 4. 结构不变量（`hsbg/env/invariants.py`）

入口：

```python
from hsbg.env.invariants import check_game, check_env, state_digest

check_game(game, *, agent=None, strict_tavern_slots=False) -> List[str]
check_env(env, *, strict_tavern_slots=False, strict_unique_ranks=False) -> List[str]
state_digest(game) -> str            # 稳定状态摘要（snapshot 对拍用）
```

契约：**只读**（不改状态/不消耗 RNG/不触发事件/不改统计）、**不崩溃**
（防御式 `getattr`+局部 try/except，单点失败记 `check_error:*`）、
**返回违反项列表**（空 = 通过，禁止内部 assert）。

### 4.1 移植自 AutoTavern `invariants.rs` 的检查

| AutoTavern | HSBRSIM 实现 | 备注 |
|---|---|---|
| board ≤ board_size | 每个英雄 `board ≤ 7` | `C.BOARD_SIZE` |
| hand ≤ hand_size | `hand ≤ 10` | `C.HAND_SIZE`（手牌可含随从/法术） |
| shop ≤ shop_max_cards | `tavern` 硬上限检查（默认不做 7 硬约束） | 见 §5.1 OBS-GAP-1 |
| tier ∈ 1..=7 | `tavern_tier ∈ 1..7` | |
| gold ≥ 0 | `gold ≥ 0` | |
| alive ⇒ health > 0 | 同（另查 health/armor 非负） | 引擎 `is_alive = health+armor>0` |
| 棋盘无死亡随从 | `board` 上无 `dead` | |
| atk ≥ 0 / max_hp > 0 / hp ≤ max_hp | 同（棋盘+手牌+酒馆随从；攻击/生命用有效属性含光环） | |
| 实体唯一性（eid） | 同一对象/uuid 不得同时出现在两个区域（跨英雄全局） | uuid 即引擎实体 id |
| 名次合法（1..N 不重复） | `_rank_by_hero`/`_elimination_order` 合法（1..N、非递增、唯一名次上界、与存活数一致） | 并列语义见 §5.2 |
| pool 守恒（`pool_balance`/`pool_species_violations`） | **不移植**（见 §4.2） | |

### 4.2 不移植/改写及理由

1. **pool 守恒**：HSBRSIM 明确允许「效果生成的副本不占池」（RULES §2.3；
   金色返还 3 份、Reno 金色化返还 1 份、`purge` 永久移除、`_injected`
   注入……），逐卡/总量守恒按设计就**不成立**。改为池簿记弱检查：
   剩余量非负、purge 后不得回池、值可解析。
2. **名次不重复**：见 §5.2（同回合多淘汰会并列）→ 默认关闭，
   `strict_unique_ranks=True` 显式报告。
3. **酒馆展示位 ≤7**：见 §5.1 → 默认关闭，`strict_tavern_slots=True`
   按 spec 契约报告。
4. AutoTavern 内部界面常量（`N_SHOP`/`N_CHOICE`/`N_POWERS`/`N_QUESTS`/
   `N_SECRETS`）在本引擎不存在；改查 `spec.CANDIDATE_MAX=64` 等观测契约。

### 4.3 环境层附加不变量（AutoTavern 无对应物）

* `_all_heroes` 与 `game.heroes` 元素同一性（大厅视图别名，§5.3）；
* `len(game.heroes) + len(_elimination_order) == num_players`（非终局）；
* `_rank_by_hero` 与淘汰集合一致（key 恰好指向淘汰英雄、名次范围/非递增）；
* `_turn_count == game.turn`、`_stats["steps"] == _step_count`；
* `_obs` 与当前状态一致（phase / 候选 / 大厅 / 名次 / 别名）；
* 候选动作结构合法（≤ `CANDIDATE_MAX`、签名不重复、
  `action_mask` 全 True、`legal_actions() == obs.candidates`）；
* `PendingChoice` 队列队首必须是智能体选择（非智能体选择应由 env 自动
  结算；其后的对手选择可暂存）；
* 有界历史容器不超上限（`_errors≤200`、`_auto_resolved_choices≤64`、
  `_choice_failures≤64`）。

---

## 5. 已知问题登记（复现/证据/状态）

### 5.1 OBS-GAP-1：酒馆展示位可 > `spec.TAVERN_MAX=7`（观测契约缺口）

* **现象**：engine 酒馆展示位 = 基础位 `C.TAVERN_OFFERS[tier]`（T1=3 … T6=6）
  + `TAVERN_OFFER_MOD` + 额外关键词位（Electrode Attractor）+ 额外档位位
  （Innkeeper's Stein）+ `TAVERN_SPELLS_PER_REFRESH=1` 张酒馆法术 +
  Fodder token + 刷新后效果追加（Varden `BG22_HERO_004p` 复制最高 Tier
  随从；Laboratory Assistant Fodder…）→ **8 张是合法状态**。
* **构造性复现**（不依赖随机对局路径，10 行内必现 8 张）：

  ```python
  from hsbg.env.game_env import BattlegroundsEnv
  from hsbg.env import driver
  from hsrl2.tags import GameTag

  env = BattlegroundsEnv(num_players=2, opponent="heuristic", seed=7)
  env.reset(seed=7)
  driver.resolve_pending_choices(env.game, None, None)
  agent = env.agent_hero
  agent.set(GameTag.TAVERN_TIER, 6)          # T6 基础 6 个随从位
  env.game._tavern_spell_extra = 1           # 模拟 "额外酒馆法术位"（Lubber Sticker）
  env.game.refresh_tavern(agent, auto=True)
  print(len(agent.tavern))                   # -> 8（6 随从 + 2 法术）
  ```

* **真实对局观察**：在任意对局中监测 `len(h.tavern)`；引擎额外展示位机制
  （见上）触发时即可出现 8（曾实测 seed=3005 turn=9 随机对局：7 随从 +
  1 法术 = 8；当前 hashseed 确定性修复后轨迹变化，构造性复现为稳定入口）。
* **连带**：`observation.build_observation` **不截断** tavern（obs.tavern
  有 8 个 token，超出 spec 的 7 槽）；`policy/encoder.entity_index(slot=7)`
  返回 `-1` → 第 8 个展示位在策略输入中**静默丢失**（动作仍可按候选下标
  选出，但无法指向该实体）。
* **处理**：不改 spec/encoder（避免破坏已训练 checkpoint/协议）；
  `check_env(strict_tavern_slots=True)` 可显式按 spec 契约报告；
  默认不报（避免对合法引擎状态报警）。建议 obs v4 统一（或 encoder
  支持变长 slot）。**状态：OPEN（待 Lead 决策，已上报）**。

### 5.2 CONVENTION_DIFF：同回合多淘汰 → 名次并列

* **现象**：`env._on_hero_eliminated` 记录 `rank = 被淘汰时存活人数 + 1`；
  同一批淘汰（同一 `_process_eliminations` 循环）名次相同。
* **复现**：`env.game.heroes` 中 3 名对手同时 `health=0` →
  `game._process_eliminations()` → `_rank_by_hero` 出现 3 个相同名次
  （实测 seed=2003：P3/P4/P7 同回合死亡 → 全部 rank=5）。
* **参照差异**：AutoTavern `invariants.rs` 断言名次不重复（其引擎按
  Health+Armor、再按座位打破同批淘汰）。HSBRSIM 环境 docstring 明确采用
  “存活人数+1”公式 → 视为**参照实现约定差异（CONVENTION_DIFF）**，不是
  本轮引入的缺陷。
* **处理**：默认不变量只查范围/非递增/唯一名次上界/计数一致；
  `check_env(strict_unique_ranks=True)` 显式报告并列。
  **状态：CONVENTION_DIFF（不改默认行为）**。

### 5.3 `_all_heroes` 与 `game.heroes` 是同一个 list 对象

* **实测**：`reset()` 里 `self._all_heroes = heroes`，而 `Game(heroes,…)`
  保存同一 list 引用；`_process_eliminations` 的 `self.heroes.remove(...)`
  会**一起原地缩短** `_all_heroes`。因此当前实现中 `_all_heroes` **不含**
  被淘汰英雄（与部分文档/口头描述不符）；被淘汰英雄只保留在
  `_elimination_order` / `_rank_by_hero`。
* **影响**：snapshot/restore **必须保留该别名关系**（恢复为
  `env._all_heroes = game.heroes`，不能复制），否则后续淘汰只改
  `game.heroes` → 大厅视图漂移。`check_env` 内置该同一性检查。
* **状态：已知语义（已按实际实现修正设计，上报 Lead）**。

### 5.4 OBS-DET-1：观测内含引擎随机 uuid 派生字段（跨轨迹不可逐位比较）

* **现象**：`Entity.__init__` 的 `uuid = uuid.uuid4()`（**不来自
  `game.rng`**）→ 观测把 uuid 映射为 `EntityToken.entity_id`，并以它为
  `extra["minion_flags"]` 的键；部分 `PendingChoice.kind` 内嵌 uuid
  （如 `discover_portable_factory:<uuid>`）。同 seed 两次 rollout / 快照
  恢复后的继续推进中，**新建实体**的 uuid 不同 → obs 这些字段不同。
* **影响面**：动作/奖励不受影响（引擎决策不读 uuid；`_combat_*` 用
  uuid 仅做成员判断）；但「观测完全一致」的确定性/对拍断言必须归一化。
  现有 `tests/test_env_game.py::test_determinism_same_seed_same_trajectory`
  只比较候选签名/奖励，故未暴露。
* **处理**：`snapshot.canonical_observation(obs)` 归一化 `entity_id` 与
  `PendingChoice.kind` 内嵌 uuid（`tests/test_env_snapshot.py` 用它做
  跨轨迹比较；同 seed 两局原始 obs != 归一化后 ==，见测试）。**不改引擎
  uuid 生成**（需 Lead 决策：改为 `game.rng` 派生或确定性计数）。
  **状态：OPEN（已上报，建议 obs v4/引擎侧统一）**。

### 5.5 F-31 Volumizer `health > max_health` — **FIXED**（engine-fixer）

* `BG34_170t` Red Volumizer 曾被 Blue 系健康光环抬当前血量但不抬
  `max_health` → `check_game` 报 `health > max_health`（构造性复现：
  summon Red 后再 summon Blue → Red `4/1`）。
* engine-fixer 已补 Red 的 `health` 动态钩子（与 atk 对称）并新增
  `hsrl2/tests/test_volumizer_health_f31.py`。本仓库不变量测试**不含
  KNOWN-1 allowlist**；`tests/test_env_invariants.py` 在 20 局中 0 违反。
* 复现命令（修复前会红 / 现应绿）：
  `python3 -m pytest hsrl2/tests/test_volumizer_health_f31.py -q`。

### 5.7 F-37 Reborn 满盘溢出 `board=8` — **FIXED**（engine-fixer；不变量门禁捕获）

* **发现路径**：`python scripts/validate_env.py --games 20 --check-invariants`
  报 `structural invariant violations: 1`（seed=5019 `hero[P6]: board=8 >
  上限 7`）；60 局报 5 处。这是 `--check-invariants` 开关抓到的**真实引擎
  bug**（证明该门禁的价值，建议纳入常规门禁）。
* **最小链路**：6 白板 + 1 个「Reborn + 亡语召唤」随从 → 摧毁它 → 亡语
  召唤填满 7 格 → 旧 `_process_death_inner` Reborn 分支仍
  `hero.board.insert(...)` 不检查 `board_full()` → 8 只。
* **修复**（engine-fixer）：Reborn 插入前检查 `hero.board_full()`；满则
  复生体不返回（不 fire `reborn`，按普通死亡处理：进墓地/注销监听器/
  招募期回池）。依据 AutoTavern `engine.rs::reborn` 走 `summon`（满盘
  返回 None）与其 `invariants.rs` `board<=7`。
* **回归**：引擎层 `hsrl2/tests/test_reborn_board_cap_f37.py`；env 层
  `tests/test_env_invariants.py::test_reborn_full_board_keeps_board_cap`
  （7 满盘 + Reborn + 亡语填满后 `check_game(game) == []` 且 board≤7）。
* **验证**：修复后 `validate_env --games 20/60 --check-invariants` 均
  `ok=True / failures=[]`。**状态：FIXED**。

### 5.6 KNOWN-DET-1 PYTHONHASHSEED 跨进程不确定性 — **FIXED**（engine-fixer F-36）

* **现象（修复前）**：同 seed + 同动作序列，`PYTHONHASHSEED=0/1` 两进程
  轨迹分裂（seed=4001：前 129 步一致，终局 reward/存活数不同）。
* **根因**：`hsrl2/scripts/choose_one_authority.py::pool_choose_one_*_ids()`
  返回 `frozenset[str]`，迭代顺序随哈希种子变化，被两个脚本直接作为
  RNG 候选列表（BrambleTunneler rally / Fandral's Fortune on_play）。
* **修复**：候选喂 RNG 前 `sorted()`；新增
  `hsrl2/tests/test_hashseed_determinism.py`（子进程 + 不同哈希种子）。
* **验证（本 WS 复跑）**：`runs/env_snapshot/hashseed_repro.py`（确定性
  动作选择，只依赖 seed）在 `PYTHONHASHSEED=0/1` 两进程：
  seed 4001/4002/4003 → `trace_sha256_16` **完全一致**
  （`e1024d42d647e456` / `1dd2c80d619e0bb3` / `90590472f2475fb9`）。
  证据文件：`runs/env_snapshot/hashseed_repro.txt`（**状态 FIXED**）。
* **建议**：脚本留作 CI 慢检（`PYTHONHASHSEED=0/1` 双进程跑完整 rollout）。
  **状态：FIXED**。

---

## 6. 开销（实测）与优化

环境：macOS / CPython 3.12 / 8 人局 / 启发式对手 / seed=0，
确定性动作策略推进到目标回合，21 次取中位数（`time.perf_counter()`）：

| 回合 | 步数 | snapshot（中位） | restore（verify=True） | restore（verify=False） |
|---|---|---|---|---|
| T1 | 0 | 4.2 ms | 6.1 ms | 2.2 ms |
| T5 | 130 | 10.5 ms | 15.1 ms | 5.5 ms |
| T10 | 338 | 17.7 ms | **24.2 ms** | 11.5 ms |

组件拆解（T5）：`clone(rebind=False)` ≈1.9ms；clone+完整回调重绑
≈5.3ms；`state_digest` ≈4.5ms（**随对局状态规模增长，是 T10 的主要开销**）；
obs 深拷贝 ≈0.3ms；`_observe` 重建 <1ms。

结论：`verify=False` 全回合 <20ms；`verify=True` 在 T10 为 24.2ms，
**超 20ms 的唯一原因**是校验路径调用了两次 `state_digest`（约 2×7ms，
T10 全图遍历），以及一次完整观测等值比较。优化空间：
① 若不需要“快照被外部修改”检测，用 `verify=False`；
② 上游 `state_digest` 可改结构化摘要（增量/缓存）；
③ 若把 clone 回调重绑并入 `hsbg/planning/model.py`（共享 memo），
`clone_env`/restore 可省一次补丁遍历。

复现：

```bash
cd /Users/letiangao/HSAgent/HSBRSIM
PYTHONPATH=. python3 - <<'PY'
# T1/T5/T10 snapshot/restore 中位耗时（同 docs 表）
import statistics, time
from hsbg.env.game_env import BattlegroundsEnv
from hsbg.env.snapshot import snapshot, restore

PRIORITY = ("buy","play_minion","play_spell","reroll","upgrade",
            "hero_power","activate","use_dark_gift","freeze",
            "move_minion","end_turn")

def choose(env):
    acts = env.legal_actions()
    for kind in PRIORITY:
        for i, c in enumerate(acts):
            if c.kind == kind:
                return i
    return len(acts) - 1

def reach(turn):
    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=0,
                           max_turns=40)
    env.reset(seed=0)
    while env.game.turn < turn and not env._done:
        env.step(choose(env))
    return env

for turn in (1, 5, 10):
    env = reach(turn)
    snap = snapshot(env)
    for _ in range(3):
        restore(env, snap)
    times = []
    for _ in range(21):
        t = time.perf_counter(); s = snapshot(env); times.append((time.perf_counter()-t)*1000)
        t = time.perf_counter(); restore(env, s); times.append((time.perf_counter()-t)*1000)
    print(turn, round(statistics.median(times[0::2]), 2),
          round(statistics.median(times[1::2]), 2), "ms")
PY
```

---

## 7. 复现命令（验收）

```bash
cd /Users/letiangao/HSAgent/HSBRSIM

# WS5 两个测试文件（快照语义 + 结构不变量）
# 实测（2026-10-26，本工作树）：19 passed，约 4.3s
PYTHONPATH=. python3 -m pytest tests/test_env_snapshot.py tests/test_env_invariants.py -q

# 不变量抽查（默认关闭；有违反项 exit 1）
PYTHONPATH=. python3 scripts/validate_env.py --games 20 --check-invariants

# F-31（Volumizer health 不变量）与 F-36（跨进程确定性）回归
PYTHONPATH=. python3 -m pytest hsrl2/tests/test_volumizer_health_f31.py -q
PYTHONPATH=. python3 -m pytest hsrl2/tests/test_hashseed_determinism.py -q

# 跨进程哈希确定性复现脚本（当前应两进程一致）
PYTHONHASHSEED=0 PYTHONPATH=. python3 runs/env_snapshot/hashseed_repro.py 4001
PYTHONHASHSEED=1 PYTHONPATH=. python3 runs/env_snapshot/hashseed_repro.py 4001
```

---

## 8. 与其他模块的边界

* **不改** `hsrl2/**`（引擎/脚本，属 engine-fixer/card-script-builder）；
  本 WS 只读引擎并在 env 层做补偿（clone 重绑补丁在 snapshot.py 内）。
* **不改** `hsbg/env/spec.py` / `observation.py` / `policy/**`：
  OBS-GAP-1、OBS-DET-1 登记为缺口交 Lead 决策，不在本 WS 擅自升版本。
* `scripts/validate_env.py` 仅新增 `--check-invariants`
  （`--invariant-every`）开关，**默认关闭、默认行为不变**；
  不变量违反会使脚本 exit 1（不当作 PASS）。
* `hsbg.planning.model.clone` 的完整修复（默认参数/共享捕获）建议由
  Lead/规划模块 owner 跟进；本 WS 的 `_CloneRebinder` 是**快照模块内**
  的可靠补偿，上游修复后可移除。
