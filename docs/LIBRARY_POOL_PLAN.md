# 镜像对手库：设计、实现与混入计划

> 目标（用户要求）：把「历史高强度对局」变成训练对手，并且**随训练自动持续更新**：
> 对局越多、水平越高，库里的对手越强。
> 状态：引擎侧「精确状态注入」已完成并验证（见 §2），其余按 §3 的里程碑推进；
> 实现完成后交 PPAI gpt-6-astra 终审，通过后再混入训练。

## 1. 现状与缺口（原实现的限制）

- `hsbg/az/library.py` 已有 `BoardEntry / capture_turn / BoardLibrary / inject_board`；
- 旧注入走 `debug(cmd=add_minion/edit_minion)`：**卡牌 id 被 golden 归一化改写**（实测 2/6 保真），
  且只恢复牌面，手牌/酒馆/饰品/任务/隐藏计数都不恢复；
- 未接 `collect`。→ 只能做「强度分布消融」，不能当真对手用。

## 2. 精确注入（已完成，本轮）

Rust `PyGame` 新增两个方法：

| 方法 | 作用 |
|---|---|
| `player_json(seat)` | 取该座位完整状态 JSON（与 `state_json()["players"][seat]` 同构，卡牌 id 为原始 id） |
| `set_player_from_json(seat, player_json, keep_seat_id=True)` | 反序列化整个 `Player` 覆盖该座位：**牌面/手牌/血量/护甲/酒馆等级/金币/饰品/任务/计数器全部原样恢复** |

验证（实测）：随机中局取 seat3 的 `player_json` → 注入新局 seat3 → 再取回，`board/hand/health/tier/gold/trinkets/quests/hero` **逐字段完全一致**（`EXACT`），卡牌 id 保持 `[1405, 3876, 3309, ...]` 原值。

## 3. 里程碑

| # | 内容 | 验收 |
|---|---|---|
| M1 | ✅ 精确注入 API（§2） | 逐字段 round-trip `EXACT` |
| M2 | `LibraryPool`：JSONL 存储 + `sample(turn, target_strength)` + 去重 + 统计 | 单测：采样回同 turn 桶、强度单调、去重生效 |
| M3 | `scripts/capture_library.py`：用指定 checkpoint 打 N 局（bot 对手），按质量门采集对手牌面 | 单测/冒烟：产出 JSONL，元数据齐全（turn/placement/strength/checkpoint/source） |
| M4 | 混入采集：`--library-pool <path> --library-p p`，每回合开始对 bot 座位按概率注入同 turn 桶的强牌面 | A/B：合法率不降、decisions/局变化可解释、吞吐影响 <5% |
| M5 | 滚动更新：每次评测/每 N 个 iteration 追加新采集、按质量门过滤、旧条目衰减 | 库条目数/强度分布随时间上升 |

**质量门（M3/M5）**：只收「该座位最终名次 ≤2」且「turn ≥ 8」且「牌面 ≥4 张随从」的牌面；
`strength = Σ(atk+hp)`；同一 `(turn, signature)` 去重；每条带 `checkpoint/source/placement/turn/strength`。

## 4. 混入策略（M4）

```
每个 game 每进入新 turn：
  for seat in 全部 bot 座位（非 learner）:
     if rng() < p:
        entry = pool.sample(turn=game.turn, target_strength=best)   # 只取 turn±1 桶里最强的
        game.set_player_from_json(seat, entry.player_json)          # 精确注入
        然后交给 bot_play(seat) 继续行动
```

- **为什么是"注入牌面 + 让 bot 继续打"**：bot 会合法地买/打/卖/升级，注入后不会卡死；
- **为什么按 turn 桶采样**：避免 turn 3 的 bot 被注入 turn 15 的怪物牌面（不公平也不真实）；
- **为什么只取强牌面**：库的用途是「更难」，不是「随机」；
- 混合比例建议从 `p=0.3` 起（每个 bot 座位独立抽），跑 10–20 iter 观察合法率/回合长度后再调。

## 5. 滚动更新（M5）

- 每次 **5M 评测后**（或每 200 iter）用当前权重跑 `capture_library.py --games 256`，把新对局按质量门追加；
- 库里每条记录带 `created_iter`，超过 N 个 stage 的旧条目降权（采样概率 ×0.5/世代）；
- 每轮混入时按 `strength` 分层采样（top-2 名次的牌面优先）；
- 指标：`pool_size`、`strength p50/p90`、按 turn 桶的覆盖度；训练侧看 `decisions/局`、
  `forced` 率、C0 曲线（面板 420000）与未见面板（440000）。

## 6. 风险与回退

- 注入的对手状态可能包含与当前局不兼容的饰品/任务/英雄 → 注入后**校验 `player_json` 回读**一致，
  不一致则该座位放弃本次注入（保持 bot 原状）；
- 强对手可能让 learner 的 advantage 方差变大 → 混入比例从 0.3 起，`approx_kl/entropy` 恶化即回退；
- 回退开关：`--library-pool ""`（默认关闭，零影响）。


---

# 方案 v2（用户 a. 方案）：对手「场面轨迹」镜像库

> 关键变化：**不再逐座位移植**，而是记录/恢复**整局状态** + **逐回合对手动作**，
> 由 bot 在轨迹不够时接管后续回合。这样 `pool / eid / lobby_races / eliminated`
> 等全局结构随 `Game.from_json(state)` 一起回来，规避 v1 的引擎不变量问题。

## A. 数据格式

每局一个 `.json.gz`（实测 3 局 × 105 KB）：

```json
{"seed": 810000, "learner_seat": 0, "placements": [6,4,5,8,2,7,1,3],
 "frames": [{"turn": 6, "state": "<Game.state_json()>",
             "actions": [[1, 42], [2, 17], ...]}, {"turn": 8, ...}],
 "meta": {"checkpoint": "...", "temperature": 0.7, "steps": 1558, "truncated": false}}
```

- `state` 是整局快照（实测 ~29 KB/帧），`actions` 是该回合**所有座位**的动作；
- 采集端：`scripts/capture_trajectory.py`（8 座位全部由 checkpoint 驱动 = 自对弈，
  逐回合打帧；带与训练一致的 `max_actions_per_turn` 回合守卫）。

## B. 回放（训练侧）

- `--trajectory-pool <dir> --trajectory-p p`：每局以概率 p 被替换成某条轨迹的**第 1 帧**恢复
  （与 v1 互斥：v1 已禁用）；
- 之后每个 bot 座位优先**回放该回合记录的动作**（`ReplayScript`，按 `(seat, turn)` 顺序取）；
  动作非法/缺记录 → 该座位交回 `bot_play`（bot 接管）；
- 学习座位（seat 0）照常用当前策略决策；若恢复点里 seat 0 已淘汰则换一条轨迹；
- meta 记录 `trajectory_games`、`trajectory_p`。

## C. 已验证

| 项 | 结果 |
|---|---|
| 自对弈采集 | 3 局 / 22 s / 3 条，单条 105 KB（含 8–10 帧） |
| 整局恢复 | `Game.from_json(frame.state)` 成功，回合/存活/淘汰状态一致 |
| 回放注入 | CPU tiny 4 局 p=1.0：**trajectory_games=4, 0 illegal, 名次正常** |
| 单测 | `tests/test_trajectory_pool.py`（加载/统计/采样/回放顺序/bot 兜底） |

## D. 与 v1（单座位 Player 移植）的关系

- v1（单座位注入）**已在代码层禁用**：`collect_ppo_lockstep` 一旦发现
  `library_pool + library_p>0` 直接 `RuntimeError`；`train_entity_sync` 在
  `--library-p>0` 时直接退出（返回 2）。`library_pool.py` / `capture_library.py`
  仅作为离线分析工具保留。Astra 终审指出其 pool/eid/生命周期不变量未维护；
- v2（本方案）走整局恢复，避开这些问题；仍需 Astra 终审确认：
  恢复点的「历史强对手」是否会让 learner 面对不可学习分布、以及 `placements` 语义（从中局开始的
  名次是真实重放名次）。

## E. 中期与后期

- 中期（现在）：轨迹库 = 更强对手（自对弈产生的高水平牌面/动作序列），不碰卡池规则；
- 后期：把「轨迹回放」替换成「分裂模型策略」（每个 bot 座位由某个 checkpoint 驱动），
  就是真正的自对弈；轨迹库则退化为**开局状态采样器**（从历史强局的中局开始打），
  既省前期回合又保证对手强度。


## F. B vs C 决定性对照（2026-10-29 实测）

Astra 要求的「同一中局入口状态，bot 继续 vs 回放记录动作」对照（`scripts/ab_trajectory_vs_bot.py`）：

| 组 | 局数 | mean rank | top4 |
|---|---:|---:|---:|
| B：中局入口 + bot 继续 | 30 | **3.7** | 0.7333 |
| C：中局入口 + 回放记录动作（非法→bot） | 31 | **3.9032** | 0.6452 |

配对差（C−B）= **0.0345**，95% CI [-0.931, 1.034]，样本 32 帧。

**结论：没有显著差异。** 说明「按 turn 回放 champion 自对弈轨迹」在当前实现下**并不比 bot 更强**
（回放覆盖率不是问题：早前冒烟 replay 920/1060 ≈ 87%），CI 完全跨 0、样本量下无法证明任何收益。

**下一步建议**：放弃轨迹回放路线（Astra 本就不批准混入），改为用户设想的后期方案——
**冻结对手模型（分裂模型/self-play）**：bot 座位直接由某个 checkpoint 采样动作，
这是唯一有明确「更强对手」机制的做法；代价是每个 bot 决策多一次前向（可用同一批量叶服务摊薄）。


## §H 真实 10k+ MMR 战团库导入

> 实现：`scripts/import_real_library.py`；测试：`tests/test_import_real_library.py`。
> 结论先说：**这批观测的 `library_ready` / `hidden_counters_complete` 全为 false，严格质量门保留 0 条。**
> 诊断模式（`--allow-unready`）可导出 4,284 条牌面记录，但**不是**可用镜像对手库，不得混入训练。

### H.1 数据来源与规模

| 项 | 值 |
|---|---|
| 观测目录 | `data/real_library/obs/observations/` |
| 文件数 | **376** 个 `<game_hash>.jsonl`（`observations_10k_57games.zip` 共 383 个条目 = 376 jsonl + 7 个辅助文件） |
| 行数 | **13,120** 行（每行一条快照） |
| 体积 | **619.6 MB** |
| 解析器 | `firestone-visible-v3`（Firestone 可见信息重建） |
| 上游汇总 | 188 局解析成功 / 356 局失败；544 场对局；模式 446 battlegrounds + 93 duo + 5 friendly |
| 观测内 build | 仅 4 个：250339 / 251952 / 253216 / 254477（`summary.json` 的 22 个 build 是更早批次汇总） |
| 阶段 | `first_attack_after_start_effects` 8,622；`recruitment_end_at_phase_switch` 4,498 |
| 视角 | `self` 8,808；`observed_opponent` 4,312 |
| split | train 9,346 / evaluation 2,108 / calibration 1,666 |

zip 内另有 7 个辅助文件（未解压进 `obs/`）：`summary.json`、`README.md`、`matches.jsonl`、
`human-opponent-library.json`、`strength_reference_curves.json`、`final_boards.jsonl`、
`redaction_manifest.json`。其中两个对判断很关键：

- `matches.jsonl`（544 场）：每局 lobby 元数据 `bgsAvailableTribes` / `bgsBannedTribes` /
  `bgsTrinkets` / `bgsAnomalies` / `gameMode` / `buildNumber` / `playerCardId`。它能部分重建
  「这一局有哪些种族/饰品」，但**没有逐 turn 的池计数**（已买走/已刷新掉的随从），也没有动作；
- `human-opponent-library.json`：`personal-human-strength-proxy-v1`，对 57 局只按 turn 记录
  `attack/health/minions` **总量**，自述 `not complete human opponent states`，只校准攻防总量。
  它是评测用的强度代理，不是可注入的牌面/状态。

**重要**：上游 `summary.json` 自己就写着 `"library_ready": false`，并列明限制
`observed opponents have incomplete hidden state`、`first-attack snapshots already include
combat-start effects`、`mixed builds and modes must be separated`。也就是说，这不是「质量门误杀」，
而是数据源在采集阶段就未达到 ready。payload 里**没有 MMR 字段**，「10k+ MMR」只是上游来源描述，
无法在库内按 MMR 分层。

### H.2 字段与清洗

每行实测字段：`game_id`、`turn`（1–17）、`combat_index`、`controller`、`perspective`、
`stage`、`split`、`board[]`、`enchantments[]`、`known_hand[]`、`unknown_hand_count`、
`heroes[]`、`build_number`、`parser_version`、`quality_flags[]`、`hidden_counters_complete`、
`library_ready`、`turn_source`。

- `board[]` 元素：`card_id`（字符串，如 `BG31_803`）、`attack`、`health`、`damage`、
  `entity_id`、`position`、`tags{}`；
- 输出只保留牌面四元组 `{card:int, atk:int, hp:int, position:int}`；
- `strength = Σ(attack + health)`（按需求，直接用当前 `health`，不再减 `damage`）；
- 空牌面（226 行）不丢弃（强度 0；按 turn 去重后仅 4 条），`board > 7` 视为解析损坏（BG 牌面上限 7 张）；
- `attack`/`health` 为 `null` 的 166 处 / 162 行（`quality_flags: incomplete_minion_state`）丢弃；
- 58 行 `board > 7`（`quality_flags: invalid_board_positions`）丢弃。

### H.3 质量门（默认 strict，符合需求）

```python
keep  = (row["library_ready"] is True) and (row["hidden_counters_complete"] is True)
```

字段缺失分别记 `missing_library_ready` / `missing_hidden_counters_complete`；
显式 false 记 `library_ready_false` / `hidden_counters_incomplete`。
全量实测：

| 门 | 行数 |
|---|---:|
| `library_ready == true` | **0 / 13,120** |
| `hidden_counters_complete == true` | **0 / 13,120** |
| 严格门保留 | **0** |

因此 `data/real_library/library_real.jsonl` 按设计为 **0 行**；拒绝伪造 ready 标志。
为了仍有可分析的产物，脚本提供显式开关 `--allow-unready`：只跳过这两个质量标志，
结构校验（卡映射 / 数值完整性 / 牌面上限）仍然 fail-closed，输出标记
`quality:"degraded"` 与 `degraded_reasons`。

### H.4 卡表映射

- 卡表：`rust/crates/hsbg-engine/data/cards.json`，`cards` 为数组，共 **3,983** 张；
- **整数索引 = 数组下标**，与 Rust `cards.rs` 的 `CardId(i as u16)` 完全一致；脚本只读，不修改卡表；
- 随从：13,120 行共 67,386 张随从，成功映射 **67,220**，**0 张卡 id 映射失败**
  （映射失败率 **0.0000%**）；差额 166 是 `attack/health` 缺失而非卡表问题；
- 英雄：先直接命中，再去掉 `_SKIN_<后缀>` 归一（如 `BG23_HERO_305_SKIN_A -> BG23_HERO_305`）。
  13,120 行中 direct 7,490 + skin_base 5,484 = **12,974 可映射（98.89%）**，
  剩余 **146（1.11%）** 无基础英雄条目，输出 `hero:null` 并保留 `hero_card_id`；
- `known_hand`：19,424 张，全部可映射（0 失败）。

### H.5 去重与统计结果

去重键：`(turn, sorted((card, atk, hp)))`；同键保留文件序第一条。输出按
`(turn, strength, signature)` 排序，同 turn 连续（按 turn 分桶）。

**严格门（默认）**

| 指标 | 值 |
|---|---|
| 输入 / 保留 | 13,120 / **0** |
| 丢弃 | `library_ready_false` 13,120 |
| turn / 强度 | 无 |
| 卡映射失败 | 0 / 67,386 |

**诊断模式（`--allow-unready`，不可训练）**

| 指标 | 值 |
|---|---|
| 输入 / 保留 / 丢弃 | 13,120 / **4,284** / 8,836 |
| 丢弃原因 | `duplicate` 8,616；`incomplete_stats` 162；`board_too_large` 58 |
| 强度 p50 / p90 / p99 | **196 / 6,330.5 / 57,622.9** |
| 强度 min / mean / max | 0 / 3,441.3 / 370,510 |
| 牌面张数分布 | 0:4, 1:203, 2:238, 3:322, 4:251, 5:289, 6:527, 7:2,450 |

turn 分布与分 turn 强度：

| turn | n | p50 | p90 |
|---:|---:|---:|---:|
| 1 | 68 | 6.0 | 10.0 |
| 2 | 132 | 8.5 | 15.9 |
| 3 | 298 | 17.5 | 28.0 |
| 4 | 374 | 26.0 | 45.7 |
| 5 | 386 | 48.0 | 73.0 |
| 6 | 399 | 79.0 | 126.2 |
| 7 | 403 | 129.0 | 237.6 |
| 8 | 403 | 261.0 | 502.8 |
| 9 | 416 | 547.5 | 1,355.0 |
| 10 | 414 | 1,144.0 | 3,028.8 |
| 11 | 368 | 2,435.0 | 8,900.9 |
| 12 | 273 | 4,858.0 | 18,508.4 |
| 13 | 192 | 10,158.0 | 32,021.3 |
| 14 | 97 | 23,243.0 | 74,670.2 |
| 15 | 42 | 29,729.0 | 95,825.3 |
| 16 | 16 | 28,644.5 | 163,764.0 |
| 17 | 3 | 22,403.0 | 22,603.0 |

去重率 65.7%（8,616/13,120）主要是同一牌面在 `recruitment_end` 与下一次
`first_attack` 两个阶段重复出现，以及不同对局在低 turn 的同签名牌面。p90 以上被少量
异常缩放随从拉高（如单张 12 万攻/防，`quality_flags` 为空但数值明显是解析重复计数），
所以**不能用均值/最大值代表人类强度**；分 turn p50 曲线更可信。

产物：

```text
data/real_library/library_real.jsonl              # strict，0 行（按质量门）
data/real_library/library_real_stats.json         # strict 统计
data/real_library/library_real_degraded.jsonl     # 诊断，4,284 行，quality=degraded
data/real_library/library_real_degraded_stats.json# 诊断统计
```

复现：

```bash
PYTHONPATH=rust/python:. python scripts/import_real_library.py --stats \
    --stats-json data/real_library/library_real_stats.json
PYTHONPATH=rust/python:. python scripts/import_real_library.py --allow-unready \
    --out data/real_library/library_real_degraded.jsonl \
    --stats-json data/real_library/library_real_degraded_stats.json --stats
PYTHONPATH=rust/python:. python -m pytest tests/test_import_real_library.py -q
```

### H.6 局限与「能否直接当镜像对手」判断

**不能直接当镜像对手。** 具体缺口：

1. **没有 pool 差量**：观测只有某一座位当前牌面，没有逐 turn 的酒馆池/已被买走或刷新掉的
   随从计数。`matches.jsonl` 虽有 lobby 的可用/禁用种族与饰品，可部分重建种族构成，但无法恢复
   池消耗；注入引擎后引擎自己从满池开始，后续买牌、刷新、三连概率全部失真；
2. **没有逐决策轨迹**：没有 action、目标选择、商店刷新、金币/等级/饰品/任务/法术：
   只能恢复「某一刻的牌面」，不能恢复「对手怎么打」。轨迹回放方案（§B–§F）需要的是
   `Game.state_json()` + 动作序列，这份数据两者都没有；
3. **隐藏计数不完整**：`hidden_counters_complete=false` 全量成立；`enchantments` 是可见信息重建，
   亡语/复仇/回合计数等隐藏状态缺失，直接注入会改变机制结算；
4. **阶段语义混杂**：`first_attack_after_start_effects` 已包含战斗开始效果，和
   `recruitment_end_at_phase_switch` 不是同一时点；两者混在一个 turn 桶里会重复计强度；
5. **构建/模式混杂**：仅 4 个 build，但含 duo/friendly 模式；跨版本卡 id 语义变化未对齐；
6. **数值噪声**：162 行（166 处）数值缺失、58 行牌面超 7、异常缩放导致 max 37 万；没有 MMR 字段可过滤；
7. **没有后续动作**：即便只做「牌面注入 + bot 接管」，也仍受第 1 条 pool 不一致影响。

**可以怎么用（仅离线）**：

- 作为真实人类强度的**分 turn 参考分布**（p50 曲线）校准 `capture_library.py` 的强度档与
  `target_strength` 采样，不进入引擎；
- 作为回归/合理性检查：bot 自对弈在 turn 8/10/12 的强度分位数是否落在人类区间；
- 作为「异常值检测」语料：识别解析器的重复计数/牌面越界问题。

**要变成可用镜像对手，至少还需要**：同一时点的完整 `player_json`（含英雄/手牌/酒馆/饰品/
任务/隐藏计数）+ lobby races/pool 状态 + 逐决策动作（或可回放的 `state_json` 轨迹）。
这等价于 §B 的整局轨迹采集，而不是本目录的「可见牌面快照」。
