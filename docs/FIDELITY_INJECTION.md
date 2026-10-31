# 完整状态注入（board + hand + hidden counters）实验通道

日期：2026-10-31 · 仓库：`/home/data/users/gaoletian/projects/HSBRSIM`
类型：**数据可得性 + Python 侧注入封装 + 三档配对验证**（不训练、不占 GPU；Rust 核心零改动）
脚本：`scripts/build_fidelity_library.py`（数据）、`scripts/fidelity_injection_audit.py`（验证）
结果：`runs/audit/fidelity_injection.json`（3.2 MB，含逐帧/逐容器明细）

---

## 0. TL;DR

1. **数据侧**：`data/real_library/obs/observations/` 的 13,120 行里，**4,498 行是真正的
   EOT 帧**（`stage=recruitment_end_at_phase_switch`，且全部是 `perspective=self`）。
   在这些帧上我们能补全：board（已有）、**golden**（`_G` 卡 id / tag 12）、
   **被授予的关键词位**（数字 tag → 引擎 `Kw` 位，见 §2.2）、**圣盾层数**、
   **tavern tier**（hero tag 1377）、**手牌**（`known_hand`，self 视角 = 完整）。
   产物：**1,961 行** `data/real_library/library_real_quasi_full.jsonl`
   （golden 46.6% 帧、关键词 71.7% 帧、手牌 59.2% 帧、tier 100% 可得）。
   **不可得**（明确标 `unavailable`，绝不编造）：gold、每随从 script counter/gems、
   attachments/亡语脚本、玩家级 counters/英雄技能、shop、共享池差量。
2. **注入侧**：新增 `hsbg.az.train.human_obs_full.inject_quasi_state()`
   （**只做 Python 封装**）：`fidelity=board` 直接走既有 `Game.inject_board`
   （逐位等价现状，测试断言 `state_json` 相同）；`hand`/`full` 走
   `Game.apply_turn_snapshots`（EID 重映射 + 逐座位事务）+ `ended_turn` 复位，
   让被注入座位**照常行动**（与现有 board-only 管线同一语义）。
3. **验证（460 帧可信完整 EOT 快照 × 3 个同 turn 容器 = 1,380 配对，按帧 cluster
   bootstrap）**：

   | 口径 | B0（现状） | B1（+hand） | B2r（+counters，真实可得） | FULL（ground truth） |
   |---|---|---|---|---|
   | combat 败率 | 0.3697 | 0.3684 | **0.3960** | 0.4330 |
   | combat 承伤 | 4.601 | 4.407 | **4.643** | 5.111 |
   | pipeline 败率 | 0.4382 | 0.4428 | **0.4518** | —（EID 不可跨局搬进活局） |

   - **hand 在战斗里没有直接效果**（B1−B0 = **−0.13pp** [−0.30,0.04]；引擎战斗路径不读
     hand）；它只在「注入后该座位继续行动」的管线里通过**recruit 出牌**起作用
     （pipeline B1−B0 = +0.46pp [−0.14,1.14]，不显著）。
   - **counters 是真实增量**：B2r−B1 = **+2.75pp** [1.90,3.66]（combat）、
     **+0.90pp** [−0.16,2.03]（pipeline）、B2r−B0 = **+2.62pp** [1.75,3.53] /
     **+1.36pp** [0.18,2.60]。
   - **B2++ ≈ FULL**：overlay 玩家级 combat 字段 + hero/powers 后，
     **−1.29pp** [−1.98,−0.68]（残差来自 EID 型字段 `owed`/`scheduled` 与 `deity`，
     Python 侧不能安全搬）→ **数据通路已闭合**，缺口分解干净。
4. **对 s13 的建议**：**开 `--human-board-fidelity full`**（配准完整库），
   代价 ≈ **0.62 ms / 座位注入**（vs board 0.007 ms，等于每局每 turn +1.2 ms 量级，
   相对每决策 ~ms 可忽略）；预期压力 **+1.36pp**（条件口径）/ **+0.06…0.16pp 每
   learner-turn**。**但它不是当前主要矛盾**：`docs/PRESSURE_AUDIT.md` 的 +64…+73pp 条件
   压力与 ~5–12%/turn 的**暴露**才是；保真度只是把「下界」抬高 1–2pp。

---

## 1. 为什么需要「准完整」注入

`docs/PRESSURE_AUDIT.md` §2.7 在同一批 460 帧上证明：完整状态 vs board-only 的败率差
**+5.12pp（同帧）/ +6.71pp（真实管线）**，CI 不含 0。但那份审计的「完整状态」用的是
**我们自己的引擎帧**（隐藏真值已知），真实人类观测里这些字段是否可得、能补到什么程度，
此前没有答案。本文回答三件事：**能补什么（§2）**、**怎么注入（§3）**、**补了以后
压力变多少（§4）**。

---

## 2. 数据可得性矩阵

### 2.1 逐字段

数据源：`data/real_library/obs/observations/*.jsonl`（376 文件 / 13,120 行，
build 250339/251952/253216/254477 混杂）。**EOT 帧 = 4,498 行**（其余 8,622 行是
`first_attack_after_start_effects`，**不是**回合末帧，全部跳过）。
EOT 帧全部是 `perspective=self` → 该玩家的 board 与 `known_hand` 都是客户端完整可见的。

| 字段 | 观测里能否得到 | 来源 / 推断方式 | 覆盖率（EOT 帧 → 落库 1,961 行） | 注入支持 |
|---|---|---|---|---|
| **board**（卡/攻/血） | ✅ 可得 | `board[].card_id/attack/health`（`card_id`→`cards.json` 下标 = 引擎 `CardId`） | 100% | ✅ `inject_board` / 帧 |
| **golden（金身）** | ✅ 可得 | `card_id` 以 `_G` 结尾，或 tag **12**（PREMIUM） | 46.6% 的帧至少 1 个（0.88 个/帧） | ✅ `golden` + 金色卡 id |
| **被授予的关键词位** | ✅ 可得（经验证） | 数字 tag → 引擎 `Kw` 位（§2.2） | 71.7% 的帧 ≥1 位（2.64 位/帧，p90 = 6） | ✅ `kw` / `bonus_kw` |
| **圣盾层数** | ✅ 可得 | tag **194** 的值（1 或 3 = Toreth/暗月paradox 的 3 层盾） | 有圣盾即有 | ✅ `shield_hits/shield_max` |
| **tavern tier** | ✅ 可得（经验证） | hero 实体 tag **1377**（按回合中位 1→6 单调，与 BG 升级节奏一致） | 100%（`tier=6` 占 29%） | ✅ `tier` |
| **hand（手牌）** | ✅（self 视角） | `known_hand[].card_id` + `tags`；`unknown_hand_count=0` | 59.2% 的帧 ≥1 张（1.44 张/帧，p90 = 4） | ✅（minion 带攻血/金身/关键词位，spell 只带 card） |
| **hero（英雄）** | ✅ 可得（不可注入） | `heroes[0].card_id`（皮肤名去 `_SKIN_*` 映射基础英雄） | 100% | ❌ 白名单保留目标值 |
| **hero power 使用次数** | ⚠️ 不可得 | 观测没有 power 实体 / `uses_turn/uses_game` 字段 | — | ❌ |
| **gold（金币）** | ❌ 不可得 | 无字段；hero 实体上没有任何随时间变化的「资源」tag（实测 tag 30/203/1037/1377，只有 1377 是 tier） | 0% | ❌ 保留当前局 gold |
| **每随从 script counter / gems / avenge** | ❌ 不可得 | 只有可视关键词位；`counter`/`gems` 没有可对齐的 tag（tag 200/313/… 是卡面 dbf/来源 id，非计数） | 0% | ❌ 置 0 |
| **attachments / 亡语脚本 / 光环** | ❌ 不可得 | 观测只有 `enchantments` 的裸 tag，无法映射回引擎 `attached: [CardId]` 语义 | 0% | ❌ 空 |
| **玩家级 effects / trinkets / quests / stats / counters** | ❌ 不可得 | 观测没有饰品/任务/光环列表（`enchantments` 是客户端实体，不是引擎 `effects`） | 0% | ⚠️ 可信帧可 overlay（§3.3），真实数据不能 |
| **shop / 共享池差量** | ❌ 不可得 | 无字段 | 0% | ❌ `pool_delta_unknown` |

落库行数：**13,120 输入 → 4,498 EOT → 4,206 结构合法 → 1,961 去重后**
（`HumanBoardPool` 载入时另有 3 行被池自己的保守过滤丢掉 → `payload_rows = 1,958`）
（丢弃：`stage` 8,622、空战团 226、`board_too_large` 12、`incomplete_stats` 54、
重复签名 2,245）。统计文件：`data/real_library/library_real_quasi_full_stats.json`。

> **为什么不替代旧库**：`library_real_degraded.jsonl`（4,275 行有效）仍是默认数据源，
> 行为逐位不变。准完整库只是 `--human-boards …_quasi_full.jsonl --human-board-fidelity
> hand|full` 时才读。

### 2.2 数字 tag → 引擎关键词位（经验证，不是猜的）

方法：把观测 `board[].tags` 的每个数字 tag 与 `cards.json` 的**印刷关键词**在全部
67,386 个战团随从上算 precision/recall；再用 `final_boards.jsonl` 的**具名 tag**
（`TAUNT`/`DIVINE_SHIELD`/`REBORN`/`VENOMOUS`/`TECH_LEVEL`…）交叉核对。结论：

| 数字 tag | 语义 | recall（印刷关键词） | 备注 |
|---|---|---|---|
| 190 / 3614 | TAUNT | **0.998** | 成对出现（一个「印刷/基础」一个「BG 关键词」） |
| 194 / 3617 | DIVINE_SHIELD | **0.994** | tag 值 = 圣盾层数（1 或 **3**） |
| 189 / 3622 | WINDFURY | **1.000** | |
| 1085 / 3621 | REBORN | 0.955 | |
| 2853 | VENOMOUS | **1.000** | |
| 363 / 3620 | POISONOUS | **1.000** | |
| 849 | MAGNETIC | **1.000** | |
| 191 / 3619 | STEALTH | **0.994** | |
| 217 | DEATHRATTLE | **1.000** | **不是**引擎 `Kw` 位（脚本效果）→ 标 unavailable |
| 218 | BATTLECRY | 0.996 | 同上 |
| 12 | PREMIUM（金身） | — | 与 `_G` 后缀一致 |

precision 低于 recall 的部分正是**被授予**的关键词（例如 Bubble Gunner 的战吼随机给
关键词、Bile Spitter 的 Rally 给毒、Toreth 的 3 层盾）：这些是我们要补的 hidden
counters，因此实现里按「tag 非零 = 该关键词存在」取值，并把「非印刷」的位单独记进
`bonus_kw`（引擎里 `bonus_kw` 就是「永久被授予」的语义，与 `Kw::BONUS` 一致）。

**没有**映射到 `MEGA_WINDFURY`/`CLEAVE`/`IMMUNE`：观测里找不到对应 tag（印刷这些词的
卡牌行数为 0），因此这些位置 0 并标 `unavailable`。

---

## 3. 注入侧（Python 封装，Rust 核心零改动）

### 3.1 入口

| 层 | 位置 | 作用 |
|---|---|---|
| 数据解析 | `hsbg/az/train/human_obs_full.py:224 parse_observation()` | 观测行 → 准完整 payload（含 `availability`） |
| 注入封装 | `hsbg/az/train/human_obs_full.py:501 inject_quasi_state()` | payload → 引擎（board/hand/full 三档） |
| 训练驱动 | `hsbg/az/train/human_board_pool.py:594 inject_turn(..., fidelity=...)` | 每回合抽座位 + 采样 + 注入 + 打点 |
| 数据构建 | `scripts/build_fidelity_library.py` | 生成准完整库 + 统计 |
| 验证 | `scripts/fidelity_injection_audit.py` | 五档配对审计 |

### 3.2 三档语义

| `fidelity` | 引擎调用 | 注入内容 | 座位是否继续行动 | 与现状关系 |
|---|---|---|---|---|
| `board`（**默认**） | `Game.inject_board(seat, [[card,atk,hp]], tier)` | 只 board（+ 派生 tier） | ✅ | **逐位等价**旧行为（单测断言 `state_json` 相同） |
| `hand` | `Game.apply_turn_snapshots` + ended 复位 | board（印刷信息）+ **手牌**；tier/gold 保持当前局 | ✅ | 新增 |
| `full` | 同上 | board（含 kw/bonus_kw/golden/盾层/attachments/counter，可信帧才有）+ 手牌 + **tier**（+ gold，仅当 payload 有） | ✅ | 新增 |

要点：

- **默认档零风险**：`fidelity=board` 走的是**完全相同的** `inject_board` 调用，RNG 消耗
  也相同（`_pick` 是唯一抽样点，`sample` 与 `sample_payload` 消耗同样的随机数），
  因此「换档」不改变座位/难度分布；
- **ended_turn 复位**：`apply_turn_snapshots` 的语义是「整场面 = 回合末」→ 会把座位标成
  `ended_turn=true`（镜像快照语义）。训练管线要的是「注入后该座位照常行动」（与
  board-only 现状一致），因此注入后把该座位 `player_json` 读回、只改
  `ended_turn=false` 再 `set_player_from_json`（**同一次写回**里顺带做玩家级 overlay）；
  这次往返读的就是本座位刚写进去的帧，逐字段恒等，`invariant_violations()` 实测为空；
- **EID**：新 board/hand 实体的 eid 由 `apply_turn_snapshots` **重新分配**（先给帧内实体
  编号 50001+，避免与当前局 shop sid / hand_queue 撞号），跨局整帧不会被直接塞进活局；
- **池**：`pool_delta_unknown`（新实体不占共享池，旧 board 归还）；实测训练 3 局
  × ~15 turn × 2 席 `pool_unbalanced = 0`（§5）；
- **失败原子性**：`apply_turn_snapshots` 被拒绝时该座位状态一位不动，`inject_turn` 只计
  `rejected`（`pending_choice`/`not_alive` 等），与 board-only 的拒绝语义一致。

### 3.3 玩家级字段 overlay（能搬什么、为什么）

`apply_turn_snapshots` 的白名单**保留**目标座位的玩家级字段。而 `combat.rs:start_of_combat`
会读 `trinkets / rewards / quests / powers / effects`——这正是「完整 vs board-only」剩余
缺口的主要来源。因此封装里多一步 **Python 侧 overlay**（仍在同一次
`set_player_from_json` 往返里）：

| overlay 组 | 字段 | 默认 | 说明 |
|---|---|---|---|
| `combat` | `trinkets`、`quests`、`rewards`、`secrets`、`levels`、`effects`、`counters`、`stats`、`tier7` | 有 payload 就用 | 全部是「卡 id + int」自包含结构，无 EntityId 引用，可安全搬运 |
| `all` | 再加 `hero`、`powers` | 关（`"all"` 才开） | 会改变后续回合的**主动玩法**（bot 会去用「别人的」英雄技能），训练不建议 |
| 永不搬 | `owed`、`scheduled`、`pending`、`hats`、`revert_golden`、`discover_targets`、`hand_queue*` | — | 含 EntityId 引用，Python 侧无法安全重映射 → 需 Rust 侧支持（本文未做） |

真实观测**没有** trinkets/quests/effects 字段，所以训练里 overlay 是 no-op（payload 里
没有 `"player"` 段）；它只在验证时用来把「数据通路」与「数据可得性」分开。

### 3.4 训练开关

```bash
# 1) 先构建准完整库（一次性，CPU，~10 s）
PYTHONPATH=rust/python:. python scripts/build_fidelity_library.py --stats

# 2) 训练（默认 board，逐位等价现状；只有显式打开才改变行为）
python scripts/train_entity_sync.py ... \
  --human-boards data/real_library/library_real_quasi_full.jsonl \
  --human-board-p 0.3 --human-board-seats 2 \
  --human-board-fidelity full        # board | hand | full
```

- `--human-board-fidelity` 默认 `board`；`hand`/`full` 在**启动期**校验：数据文件里必须
  有 `board_detail` 行（否则直接 `[error]` 退出，不会静默退化成 board-only），
  且引擎必须具备 `apply_turn_snapshots`；
- `history.jsonl` 的 `collect` 段新增（`slim_collect` 会跨 worker 聚合：
  计数求和 / 开关取 any / `unavailable_fields` 逐键求和）：

  | 字段 | 含义 |
  |---|---|
  | `human_board_fidelity` | `board` / `hand` / `full` |
  | `human_board_hand_applied` | 成功注入手牌的座位数 |
  | `human_board_counters_applied` | 成功注入 counters 的座位数（仅 full） |
  | `human_board_full_applied` | 走 `apply_turn_snapshots` 成功的座位数（hand/full） |
  | `human_board_payload_missing` | 库行没有 payload → 退化 board-only 的次数（应为 0） |
  | `human_board_unavailable_fields` | `{字段: 次数}`，逐字段记录 payload 里标 unavailable 的项 |
  | `human_board_hand_unavailable` / `_counters_unavailable` | 手牌/counters 不可得的座位数 |
  | `human_board_payload_rows` | 池里带 payload 的行数 |

---

## 4. 三档配对验证（460 帧可信完整 EOT 快照）

### 4.1 协议

- 帧：`runs/library/snaps_champ/*.json.gz` 的 **460 帧**（t∈[6,15]、有战团），
  与我们自己的引擎状态（隐藏真值已知）；
- 容器：每帧从**同 turn** 的 `runs/audit/snapshots.jsonl.gz` 容器里抽 **3 个**
  （`blake2b(frame_key|salt) % len(cands)`，与 worker 数无关）→ **1,380 配对**；
- 战斗：每对 **64** 个引擎 `combat_preview` trial（`rng = game.seed ^ 0x9E3779B9*(i+1)`，
  同帧同容器同 seed → 逐 trial 配对）；存活随从 16 个 trial 的最后一帧；
- CI：**按帧 cluster bootstrap**（4000 次；同帧 3 个容器不独立）；
- 两种口径：
  - **combat**：容器座位 = 本局真实座位，注入后**立刻**开打（隔离「信息量」；
    hand 在战斗里没有作用，见 §4.3）；
  - **pipeline**：注入发生在**回合起点**，之后该座位照常 bot 行动，再用战斗前战团
    重播种（= 训练里真正发生的事；这里 hand 才会通过出牌起作用）。

臂定义：

| 臂 | 定义 |
|---|---|
| **B0** | 现状：`Game.inject_board`（人类可见 board，`_G` 金色卡 id 保留） |
| **B1** | `fidelity=hand`：B0 的 board + **手牌** |
| **B2** | `fidelity=full`：完整帧（kw/金身/盾层/attachments/counter/gems/**tier + gold**） |
| **B2r** | 同 B2，但 **gold 保留当前局**（真实观测 gold 不可得；**训练实际形态**） |
| **B2+** | B2 + 玩家级 **combat overlay**（trinkets/quests/rewards/secrets/effects/stats/counters/tier7） |
| **B2++** | B2+ 再 overlay `hero`/`powers`（≈ ground truth；训练不建议） |
| **FULL** | ground truth：`set_player_from_json` 整帧替换（旧审计同一条路，仅 combat 口径） |

### 4.2 配对表（败率 / 承伤 / 存活）

**combat 口径**（n = 460 帧 × 3 容器 = 1,380 配对，64 trials/配对）：

| 臂 | 败率 | 承伤 | 存活 |
|---|---|---|---|
| B0 | 0.3697 | 4.601 | 1.886 |
| B1 | 0.3684 | 4.407 | 1.894 |
| B2（=B2r） | 0.3960 | 4.643 | 1.808 |
| B2+ | 0.4174 | 4.923 | 1.694 |
| B2++ | 0.4201 | 4.960 | 1.696 |
| **FULL** | **0.4330** | **5.111** | **1.638** |

| 配对 | Δ败率 (pp) [95%CI] | Δ承伤 [95%CI] | Δ存活 [95%CI] |
|---|---|---|---|
| B1 − B0（hand） | **−0.13 [−0.30, 0.04]** | −0.194 [−0.225, −0.165] | +0.009 [−0.001, 0.017] |
| B2 − B1（counters） | **+2.75 [1.90, 3.66]** | +0.236 [0.128, 0.351] | −0.086 [−0.129, −0.042] |
| B2+ − B2（玩家级 combat） | **+2.14 [1.48, 2.84]** | +0.280 [0.193, 0.370] | −0.114 [−0.150, −0.080] |
| B2++ − B2+（hero/powers） | +0.28 [−0.26, 0.83] | +0.036 [−0.019, 0.094] | +0.001 [−0.017, 0.019] |
| **B2++ − FULL（通路残差）** | **−1.29 [−1.98, −0.68]** | −0.151 [−0.225, −0.078] | +0.057 [0.031, 0.084] |
| **FULL − B0（信息缺口）** | **+6.33 [5.14, 7.58]** | +0.510 [0.364, 0.657] | −0.248 [−0.299, −0.199] |
| B2 − B0（真实可得部分） | **+2.62 [1.75, 3.53]** | +0.042 [−0.066, 0.153] | −0.078 [−0.121, −0.033] |
| B2+ − B0 | +4.76 [3.79, 5.77] | +0.322 [0.197, 0.453] | −0.192 [−0.239, −0.148] |

**pipeline 口径**（训练真实管线；n = 1,380）：

| 臂 | 败率 | 承伤 |
|---|---|---|
| B0 | 0.4382 | 5.556 |
| B1 | 0.4428 | 5.431 |
| B2 | 0.4566 | 5.490 |
| **B2r** | **0.4518** | **5.424** |
| B2+ | 0.4856 | 5.895 |

| 配对 | Δ败率 (pp) [95%CI] | Δ承伤 [95%CI] |
|---|---|---|
| B1 − B0（hand） | +0.46 [−0.14, 1.14] | −0.125 [−0.204, −0.036] |
| B2 − B1（counters + 完整帧） | +1.38 [0.28, 2.56] | +0.059 [−0.085, 0.201] |
| **B2r − B1** | **+0.90 [−0.16, 2.03]** | −0.007 [−0.213, 0.199] |
| B2 − B2r（gold 的影响） | +0.49 [0.12, 0.89] | +0.066 [−0.064, 0.196] |
| B2+ − B2（玩家级 combat） | +2.90 [1.70, 4.06] | +0.405 [0.228, 0.577] |
| **B2 − B0** | **+1.85 [0.60, 3.12]** | −0.066 [−0.217, 0.089] |
| **B2r − B0（训练实际）** | **+1.36 [0.18, 2.60]** | −0.132 [−0.332, 0.077] |
| B2+ − B0 | +4.74 [3.32, 6.18] | +0.339 [0.138, 0.545] |

### 4.3 读法（三条结论）

1. **hand 在战斗里没有直接效果**（−0.13pp，CI 跨 0；承伤甚至略降 —— 因为 hand 不参与
   combat，替换手牌不影响 board）。引擎 `combat.rs` 只在 `combat_only` 召唤等少数路径
   间接碰 hand，实测等价于 0。**手牌的作用只能通过「注入后继续出牌」体现**：pipeline
   口径 +0.46pp（CI 跨 0）——因为 bot 拿到的是人类**回合末剩下的**手牌（本来就没打出去），
   所以增量很小。这正是审计里「+6.7pp」不能全记在 hand 头上的原因。
2. **counters 是真实增量**：+2.75pp（combat，含 attachments/counter/gems/tier/gold）/
   +1.38pp（pipeline）。其中「完整帧 vs 真实可得」（B2−B2r）在 pipeline 里是 **+0.49pp**，
   纯粹来自 gold（人类 EOT 剩余金币通常 0–2，比当前局新回合的 ~10 少 → 反而让对手更弱）。
   因此**训练里应该用 B2r 形态**（gold 不可得 → 保留当前局），这也是
   `--human-board-fidelity full` 的实际行为。
3. **数据通路是闭合的**：B2++（board+hand+counters+玩家级 overlay+hero/powers）与
   ground truth FULL 只差 **−1.29pp**（CI [−1.98,−0.68]，约为缺口的 20%），残差全部来自
   `owed`/`scheduled`（含 EntityId 的待召唤/延迟效果）与 `deity` —— Python 侧不能安全搬运，
   要闭合需 Rust 侧把这些字段加进白名单并做 typed EID 重映射（本文按任务约束**不改
   Rust 核心**，留作 patch 方向）。
   于是缺口分解为：**board+hand+counters 2.62pp（41%）+ 玩家级 combat 效果 2.14pp（34%）
   + hero/powers 0.28pp（4%）+ EID 型字段 1.29pp（20%）= 6.33pp**。

### 4.4 逐 turn（B2r − B0），含 95%CI

| turn | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 |
|---|---|---|---|---|---|---|---|---|---|---|
| **combat** Δpp | +3.5 | **+6.1** | +0.9 | +4.0 | +0.4 | +2.6 | −0.2 | +0.9 | +3.6 | +2.6 |
| 95%CI | [1.3,6.4] | [3.3,9.1] | [−1.1,2.7] | [1.5,6.7] | [−1.8,2.6] | [−0.5,5.6] | [−1.8,1.4] | [−1.4,3.6] | [0.5,7.0] | [−0.1,5.5] |
| n（帧/配对） | 64/192 | 64/192 | 64/192 | 63/189 | 55/165 | 47/141 | 38/114 | 29/87 | 23/69 | 13/39 |
| **pipeline** Δpp | +4.3 | **+5.9** | +1.2 | +3.8 | −2.3 | −1.6 | −2.2 | −3.3 | −0.3 | +3.5 |
| 95%CI | [1.0,7.8] | [3.0,9.2] | [−1.1,3.3] | [−0.2,8.3] | [−5.9,1.1] | [−5.6,2.2] | [−5.3,0.8] | **[−6.4,−0.6]** | [−4.5,4.0] | [−3.2,10.1] |

combat 口径与审计的「压力最大在 t7–t12」一致；pipeline 口径在 **t13** 出现显著负值
（−3.3pp，n=29 帧）：这是**协议交互**而非「保真度更弱」——注入后该座位用**人类的回合末
手牌/等级**继续打，而 B0 用它**自己的**手牌/新商店，晚局 B0 的「自我增购」更强。
训练里真实数据没有 gold/手牌完整保证，这一项本来就偏保守；结论以 overall（+1.36pp）为准。

---

## 5. 开销

同一台机器（CPU，单进程，`hsbg_engine 1.0.0`）：

| 项目 | board（现状） | hand | full |
|---|---|---|---|
| 单次座位注入 | **0.007 ms** | 0.642 ms | **0.623 ms** |
| 相对倍率 | 1× | ~90× | ~88× |
| 训练 3 局 × 全 turn × 2 席（含 bot 推进）总耗时 | 0.02 s | 0.11 s | 0.09 s |
| 注入成功率（同 3 局，含 pending/淘汰拒绝） | 48/76 | 54/82 | 47/72 |
| 池不守恒次数 | **0** | **0** | **0** |
| `invariant_violations()` | 空 | 空 | 空 |

- 0.62 ms 的构成：`player_json`（序列化）→ `json.loads/dumps`（Python）→
  `apply_turn_snapshots`（serde + EID 重映射 + 池检查）→ 再读回 + `set_player_from_json`
  写回（overlay/ended 复位）。**每 turn 每座位一次**，2 席 × ~13 turn ≈ **16 ms/局**；
- 相对训练里每决策的 ~1 ms（lockstep 批量前向 + bot 推进）可忽略（<0.5%）；
- 若只在 `hand`/`full` 档开启，board 档完全不走这条路径（0.007 ms，与现状一致）。

---

## 6. 局限（如实）

1. **人类隐藏真值不可得**：真实 10k+ MMR 观测只给「客户端可见」的字段。gold、每随从
   script counter、gems、attachments/亡语脚本、玩家级 effects/trinkets/quests、英雄技能
   使用次数、shop、共享池差量**全部不可得**。我们只做**机制量级**验证：在**我们自己的**
   EOT 快照上（隐藏真值已知）测「board-only 会丢多少」，再用观测里**确实可见**的字段
   （关键词位/金身/盾层/tier/hand）做「准完整」注入。
2. **hand 的语义是「回合末剩下的牌」**：注入到训练管线后 bot 会去打这些牌，这**高估**了
   手牌的作用（人类是主动选择不打的）；combat 口径（不行动）则**低估**为 0。两个口径都报了。
3. **玩家级效果无法注入真实数据**：B2+ 的 +2.14pp 只在我们自己的帧上成立；真实人类对手
   的饰品/任务/光环效果在训练里仍然缺失（这部分属于「数据不可得」，不是「代码没做」）。
4. **EID 型字段仍需 Rust**：`owed`/`scheduled` 等含 EntityId 的待触发效果不能安全搬运，
   构成 B2++−FULL 的 −1.29pp 残差；`hats`/`revert_golden`/`discover_targets` 被
   `apply_turn_snapshots` 主动清空（与 EOT 语义一致，影响极小）。
5. **容器抽样方差很大（关键）**：同一帧换个「学习者/对手强度」容器，Δ 会大幅变化。
   实测逐容器 Δ(B2r−B0) 在 **−3.4…+15.6pp**、Δ(FULL−B0) 在 **−0.6…+28.1pp** 之间摆动，
   容器均值 +2.62 / +6.33pp。因此：
   - 单容器 × 460 帧的一次估计曾给出 FULL−B0 = **+2.66pp**（与本文 3 容器 +6.33 差 3.7pp），
     说明「每帧只配一个容器」不可靠；
   - 本文用 **每帧 3 个容器 + 按帧 cluster bootstrap**；旧审计（12 worker、
     `i % len(cands)` 单容器）的 +6.71pp 与本文 +6.33pp 一致，纯属容器抽样落点相近，
     **不是**独立证据；
   - 多容器 + cluster bootstrap 是复现这套数字的最低要求。
6. **bucket 覆盖**：准完整库按 `turn` 分桶后 t≥6 每桶 ~180 条（t16–17 只有 8 条），
   训练里 `turn_tier` 派生 tier 仍用于 board 档；full 档优先用观测 tier。
7. **未训练**：本文不训练、不跑 human 面板。所有结论都是引擎冻结反事实 + 配对 CI。

---

## 7. 是否建议 s13 用 `full` 保真度？——**建议开，理由与预期**

**建议：开。**（`--human-boards data/real_library/library_real_quasi_full.jsonl
--human-board-fidelity full`，其余参数不变）

理由：

1. **方向确定、CI 不含 0**：真实可得部分（B2r）在两种口径下都是正效应
   （combat **+2.62pp [1.75,3.53]**；pipeline **+1.36pp [0.18,2.60]**），
   与审计的「board-only 系统性低估压力」一致；开它只会让训练压力**更接近真实**，不会更弱。
2. **代价可忽略**：+0.62 ms/座位注入 ≈ +16 ms/局（<0.5%），且默认档逐位不变、
   池守恒/不变量实测干净、失败原子化。
3. **它是「下界修正」而非「新杠杆」**：条件效应 +1.36pp 对比审计的条件压力
   +64…+73pp 只有 ~2%；按暴露折算（s10 4.59%/turn、B 11.89%/turn）≈
   **+0.06 / +0.16pp per learner-turn**。所以**不要指望它单独把 human 面板拉起来**。
4. **真正的杠杆仍是暴露/剂量**（审计 §3.3）：每 learner-turn 命中率 4.6–11.9% vs 面板
   100%。建议 s13 同时（或优先）把 `seats/p` 拉高，`fidelity=full` 作为「不额外花钱的
   正确性修正」一起开。

预期效果（可证伪的预估）：

- 训练压力：每个「命中」的 learner-turn 败率 +1.4pp（pipeline）/ +2.6pp（战斗时口径），
  承伤 +0.13/+0.04；对手战团末强度不变（注入本身不改统计量）；
- 若 s13 同时把暴露拉到 30–50%/turn：每 turn 期望败率抬升 ≈ 0.3–0.7pp（fidelity 贡献
  ≈0.4–0.7pp，其余来自剂量），这才能对 human 面板产生可观测位移；
- 观测方式：`history.jsonl` 的 `collect.human_board_fidelity === "full"`、
  `human_board_counters_applied == human_board_applied`（full 档里注入成功即 counters 成功）、
  `human_board_applied / human_board_attempt ≈ 0.65`（pending/淘汰拒绝）、
  `human_board_payload_missing == 0`、`human_board_unavailable_fields` 恒含
  `gold/counter/attachments/...`；以及 `human_board_pool_unbalanced == 0`。

**不建议**开 `player_overlay="all"`（hero/powers）：它只值 +0.28pp（CI 跨 0），却会让
bot 使用不属于自己的英雄技能，改变后续回合玩法。

---

## 8. 复现

```bash
cd /home/data/users/gaoletian/projects/HSBRSIM

# 数据：准完整库（CPU，~10 s）
PYTHONPATH=rust/python:. python scripts/build_fidelity_library.py --stats
# -> data/real_library/library_real_quasi_full.jsonl (1,961 行, 3.1 MB)
# -> data/real_library/library_real_quasi_full_stats.json

# 验证：五档 × 2 口径（CPU，24 进程，~126 s）
PYTHONPATH=rust/python:. python scripts/fidelity_injection_audit.py \
  --frames 460 --containers 3 --battle-seeds 64 --survivor-seeds 16 --workers 24 --force
# -> runs/audit/fidelity_injection.json  /  runs/audit/fidelity_injection.log

# 冒烟（24 帧 / 8 seed / 4 worker，~12 s）
PYTHONPATH=rust/python:. python scripts/fidelity_injection_audit.py --smoke --force

# 测试
PYTHONPATH=rust/python:. python -m pytest tests/test_full_state_injection.py -q
```

依赖：`runs/audit/snapshots.jsonl.gz`（460 帧的容器，`pressure_audit.py` 产出）+
`runs/library/snaps_champ/*.json.gz`（我们自己的 EOT 帧）。两者都在仓库内已有产物。

---

## 9. 交付物

| 文件 | 内容 |
|---|---|
| `hsbg/az/train/human_obs_full.py`（新，637 行） | tag→Kw 映射、观测解析、准完整 payload、`inject_quasi_state`（board/hand/full + 玩家级 overlay） |
| `hsbg/az/train/human_board_pool.py`（改，+280/−36 行） | payload 装载、`sample_payload`、`inject_turn(fidelity=...)`、统计字段 |
| `hsbg/az/train/parallel_collect.py`（改） | `human_board_fidelity` 参数 + 启动期校验 + meta |
| `hsbg/az/train/ppo.py` / `process_pool.py` / `runlog.py`（改） | `CollectConfig` 字段、传参、`history.jsonl` 键聚合 |
| `scripts/train_entity_sync.py`（改） | `--human-board-fidelity {board,hand,full}`（默认 board） |
| `scripts/build_fidelity_library.py`（新，309 行） | 观测 → 准完整库 + 统计 |
| `data/real_library/library_real_quasi_full.jsonl`（新数据，1,961 行） | 准完整库（`.gitignore` 里 `*.jsonl` 被忽略，需随数据目录一起同步） |
| `data/real_library/library_real_quasi_full_stats.json`（新） | 可得性矩阵的分子/分母 |
| `scripts/fidelity_injection_audit.py`（新，644 行） | 五档配对审计（combat + pipeline，cluster bootstrap） |
| `runs/audit/fidelity_injection.json`（新，3.2 MB） | 全部数字（含逐帧/逐容器明细） |
| `tests/test_full_state_injection.py`（新，375 行，12 用例） | 映射/解析/默认档逐位等价/hand+counters 回读/overlay/RNG 一致/训练接线/管线冒烟 |
