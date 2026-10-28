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
