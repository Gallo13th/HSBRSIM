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

- `--trajectory-pool <dir> --trajectory-p p`：每局以概率 p 被替换成某条轨迹的**第 1 帧**恢复；
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

- v1 保留为**离线工具**（`library_pool.py` + `capture_library.py`），但**不进入训练**：
  Astra 终审指出其 pool/eid/生命周期不变量未维护；
- v2（本方案）走整局恢复，避开这些问题；仍需 Astra 终审确认：
  恢复点的「历史强对手」是否会让 learner 面对不可学习分布、以及 `placements` 语义（从中局开始的
  名次是真实重放名次）。

## E. 中期与后期

- 中期（现在）：轨迹库 = 更强对手（自对弈产生的高水平牌面/动作序列），不碰卡池规则；
- 后期：把「轨迹回放」替换成「分裂模型策略」（每个 bot 座位由某个 checkpoint 驱动），
  就是真正的自对弈；轨迹库则退化为**开局状态采样器**（从历史强局的中局开始打），
  既省前期回合又保证对手强度。
