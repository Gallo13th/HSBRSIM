# SearchAgent v4 干净检查点 — 实战演示

生成时间: 2026-05-14 | 模型: BoardEval v3 + GameValue v4_clean | 搜索: Greedy One-Step Lookahead

## 重要说明

本文档对比于 `DEMO_V6_GAMES.md`（被污染检查点），使用**完全干净的数据重新训练**：

| 对比维度 | 污染版 (v6) | 干净版 (v4_clean) |
|----------|------------|-------------------|
| 英雄护甲 | 全部 0 | 5-18 (真实值) |
| 随从池 | 含 Buddy/Golden 卡牌 | 仅可购买随从 |
| 第一回合金色 | 常见 (池污染) | **不会出现** |
| 对手酒馆等级 | 全程 Tier 1 | 升级至 Tier 6 |
| 游戏回合数 | 6-7 回合 (agent 死亡) | 15 回合 (最终 2 名存活) |
| BoardEval 准确率 | 99.1% (虚高) | 97.9% (真实) |
| GameValue MAE | — | 0.151 |
| Agent avg_rank | 2.00 (v6 贪心) | 2.20 (v4 贪心) |

---

## 架构概述

```
Pipeline: Combat Simulator → BoardEval → GameValue → Search Policy

GameValueNetwork v4 (HDT-observable POMDP):
  - Per-opponent: last_seen_board(32) + staleness + combat_history +
    hp + tier + armor + board_size + triples×6 + upgrades×5 = 51 dims
  - Shared opp_proj(51→32→16) + mean pool → 16
  - Total input: 32(board) + 6(own) + 7×51(opp) + 2(global) = 397 dims
  - Teacher: CombatPredictor pairwise ranking (full-information)
  - Model: 6,705 parameters

SearchAgent:
  - Greedy one-step lookahead using GameValueNetwork
  - At each step: enumerate legal actions → simulate → evaluate V(s')
  - Chooses action with highest predicted state value
```

### 动作名称速查

| 前缀 | 含义 |
|------|------|
| `buy_tavern_N` | 购买酒馆第 N 个随从 |
| `play_hand_N` | 打出手牌第 N 张 |
| `sell_board_N` | 出售棋盘第 N 个随从 |
| `refresh` | 刷新酒馆 (消耗 1 金币) |
| `upgrade` | 升级酒馆等级 |
| `use_hero_power` | 使用英雄技能 |
| `END_TURN` | 结束回合，进入战斗 |

---

## Game 1 — Seed 42 (v4_clean)

### 对局信息

| 项目 | 内容 |
|------|------|
| Agent 英雄 | **Yogg-Saron, Hope's End** (护甲 18) |
| 对手 1 | Sneed |
| 对手 2 | Overlord Saurfang |
| 对手 3 | Ysera |
| 对手 4 | Inge, the Iron Hymn |
| 对手 5 | Professor Putricide |
| 对手 6 | Sylvanas Windrunner |
| 对手 7 | Drek'Thar |
| 最终排名 | **2nd** (HP=8, 存活至终局) |
| 总操作数 | 41 |
| 状态评估次数 | 826 |

### 回合详细日志

```
─── Turn 1 ───
  State: HP=30  Gold=3  Tier=1  Armor=18
  Board: (empty)
  Tavern: [0] False Implicator 1/1 T1 $3 | [1] False Implicator 1/1 T1 $3 | 
          [2] Windfall Tornado 4/4 T1 $3 | [3] Sick Riffs (spell) T1 $3
  Initial V_game = 0.7136

  [0] END_TURN  (V=0.7136)
       → 第一回合空过 — 3 金币未使用

  ⚔ Combat Phase:
    Pre-combat board:  (empty)
    Post-combat board: (empty)
    Teacher predicted placement: 1.000 (1.0th place)
    Alive players: 8/8

─── Turn 2 ───
  State: HP=30  Gold=4  Tier=1  Armor=16
  Board: (empty)
  Tavern: [0] False Implicator 3/2 T1 $3 | [1] False Implicator 3/2 T1 $3 |
          [2] Windfall Tornado 6/5 T1 $3 | [3] Sick Riffs (spell) T1 $3 |
          [4] Evolving Strategy (spell) T1 $3
  Initial V_game = 0.2675

  [0] upgrade  (V: 0.2675 → 0.4731, Δ=+0.2057)
       → 升级至 Tier 2 — 放弃买随从，优先升本
  [1] END_TURN  (V=0.4731)

  ⚔ Combat Phase:
    Pre-combat board:  (empty)
    Post-combat board: (empty)
    Teacher predicted placement: 1.000 (1.0th place)
    Alive players: 8/8

─── Turn 3 ───
  State: HP=30  Gold=5  Tier=2  Armor=13
  Board: (empty)
  Tavern: [0] False Implicator 5/3 T1 $3 | [1] False Implicator 5/3 T1 $3 |
          [2] Windfall Tornado 8/6 T1 $3 | [3] Sick Riffs (spell) T1 $3 |
          [4] Evolving Strategy (spell) T1 $3
  Initial V_game = 0.1163

  [0] refresh  (V: 0.1163 → 0.1547, Δ=+0.0384)
       → 刷新寻找更好的随从
  [1] END_TURN  (V=0.1547)
       → 仍未买随从 — 棋盘持续空置

  ⚔ Combat Phase:
    Pre-combat board:  (empty)
    Post-combat board: (empty)
    Teacher predicted placement: 1.000 (1.0th place)
    Alive players: 8/8

─── Turn 4 ───
  State: HP=30  Gold=6  Tier=2  Armor=8
  Board: (empty)
  Tavern: [0] Picky Eater 3/2 T1 $3 | [1] Sellemental 5/4 T2 $3 |
          [2] Picky Eater 3/2 T1 $3 | [3] Fire Baller 6/4 T2 $3
  Initial V_game = 0.0585

  [0] upgrade  (V: 0.0585 → 0.0671, Δ=+0.0086)
       → 升级至 Tier 3
  [1] upgrade  (V: 0.0671 → 0.0807, Δ=+0.0136)
       → 升级至 Tier 4
  [2] upgrade  (V: 0.0807 → 0.1026, Δ=+0.0220)
       → 升级至 Tier 5
  [3] upgrade  (V: 0.1026 → 0.1520, Δ=+0.0494)
       → 升级至 Tier 6 — 连续 4 次升级，从 Tier 2 直冲 Tier 6！
  [4] END_TURN  (V=0.1520)

  ⚔ Combat Phase:
    Pre-combat board:  (empty)
    Post-combat board: (empty)
    Teacher predicted placement: 1.000 (1.0th place)
    Alive players: 8/8

─── Turn 5 ───
  State: HP=28  Gold=7  Tier=6  Armor=0
  Board: (empty)
  Tavern: [0] Metallic Hunter 2/1 T2 $3 | [1] Twisted Wrathguard 4/4 T5 $3 |
          [2] Hot-Air Surveyor 4/8 T5 $3 | [3] Nerubian Deathswarmer 1/4 T2 $3 |
          [4] Dustbone Devastator 2/6 T3 $3 | [5] Junk Jouster 8/7 T6 $3
  Initial V_game = 0.0882

  [0] buy_tavern_0  (V: 0.0882 → 0.0901, Δ=+0.0020)
       → 购买第 1 个随从 (Turn 5 才首次购买!)
  [1] play_hand_0  (V: 0.0901 → 0.6771, Δ=+0.5869)
       → 打出随从 — V 值暴涨 +0.587
  [2] END_TURN  (V=0.6771)

  ⚔ Combat Phase:
    Pre-combat board:  (empty)
    Post-combat board: 86/59 [大型随从]
    Teacher predicted placement: 0.286 (6.0th place)
    Alive players: 8/8

─── Turn 6 ───
  State: HP=28  Gold=8  Tier=6  Armor=0
  Board: 拥有 1 个大型随从
  Tavern: 6 个高 Tier 随从 (T5-T6)
  Initial V_game = 0.6580

  [0] refresh  (V: 0.6580 → 0.6843, Δ=+0.0263)
  [1] refresh  (V: 0.6843 → 0.6915, Δ=+0.0072)
       → 连续刷新寻找升级
  [2] END_TURN  (V=0.6915)

  ⚔ Combat Phase:
    Pre-combat board:  86/59
    Post-combat board: 86/59
    Teacher predicted placement: 0.429 (5.0th place)
    Alive players: 8/8

─── Turn 7 ───
  State: HP=18  Gold=9  Tier=6  Armor=0
  Board: 86/33 (战斗受损)
  Tavern: 6 个随从 (T1-T4 混合)
  Initial V_game = 0.2395

  [0] buy_tavern_0 + play → 棋盘增至 2 个大型随从 (V: 0.2395 → 0.5100)
  [1] refresh → 寻找 buff 机会
  [2] END_TURN  (V=0.5271)

  ⚔ Combat Phase:
    棋盘: 86/33, 594/591
    Teacher predicted placement: 0.143 (7.0th place — 形势严峻)
    Alive players: 8/8
    💀 2 名对手被淘汰 (Sylvanas, Drek'Thar)

─── Turn 8 ───
  State: HP=18  Gold=10  Tier=6  Armor=0
  Board: 86/33, 594/591
  Tavern: 6 个 T4-T5 随从
  Initial V_game = 0.3719

  [0] buy → 手牌累积
  [1-2] 连续 2 次刷新
  [3] play_hand → 新随从 905/902 [DS] (获得圣盾!)
  [4] END_TURN  (V=0.4795)

  ⚔ Combat Phase:
    棋盘: 86/33, 594/591, 905/902 [DS]
    Teacher predicted placement: 0.429 (5.0th place)
    Alive players: 6/8

─── Turn 9 ───
  State: HP=18  Gold=10  Tier=6  Armor=0
  Board: 3 个大型随从 (含 1 个圣盾)
  Initial V_game = 0.4495

  [0] buy → 替换小型随从
  [1] buy → 继续扩充手牌
  [2] sell_board_0 → 出售最弱随从 (86/33) 腾出位置
  [3] END_TURN  (V=0.5081)

  ⚔ Combat Phase:
    棋盘优化: 出售弱随从 → 保留 2 个强力随从
    Teacher predicted placement: 0.429 (5.0th place)
    Alive players: 5/8
    💀 1 名对手被淘汰

─── Turn 10 ───
  State: HP=18  Gold=10  Tier=6  Armor=0
  Board: 594/591, 905/902 [DS]

  [0] buy + refresh → 寻找升级机会
  [1] END_TURN  (V=0.6297)

  ⚔ Combat Phase:
    Teacher predicted placement: 0.571 (4.0th place — 排名上升)
    Alive players: 5/8

─── Turn 11 ───
  State: HP=8  Gold=10  Tier=6  Armor=0
  Board: 594/591, 905/902 [DS]

  [0] buy + play → 新随从 1699/1699 加入棋盘
  [1-3] 刷新 + 调整
  [4] END_TURN  (V=0.5993)

  ⚔ Combat Phase:
    棋盘: 607/604, 918/915 [DS], 1702/1702
    Teacher predicted placement: 0.429 (5.0th place)
    Alive players: 4/8 (半场淘汰)

─── Turn 12 ───
  State: HP=8  Gold=10  Tier=6  Armor=0
  Board: 3 个大型随从

  [0-1] buy × 2 → 手牌蓄力
  [2] play → 新随从 1981/1982 [DS] (又一个圣盾!)
  [3] sell_board_0 → 替换最弱随从
  [4] END_TURN  (V=0.6718)

  ⚔ Combat Phase:
    棋盘: 942/939 [DS], 1702/1702, 1990/1991 [DS]
    Teacher predicted placement: 0.571 (4.0th place)
    Alive players: 3/8

─── Turn 13 ───
  State: HP=8  Gold=10  Tier=6  Armor=0
  Board: 3 个大型随从 (2 圣盾)

  [0-1] buy × 2
  [2] play_hand → 棋盘扩展到 4 个随从
  [3] END_TURN  (V=0.7720)

  ⚔ Combat Phase:
    棋盘: 954/951 [DS], 1702/1697, 2002/2003 [DS], 906/908
    Teacher predicted placement: 0.714 (3.0th place — 稳定进前三)
    Alive players: 3/8

─── Turn 14 ───
  State: HP=8  Gold=10  Tier=6  Armor=0
  Board: 4 个随从

  [0-1] buy × 2
  [2] play_hand → 加入新随从
  [3] rearrange → 重排棋盘优化站位
  [4] END_TURN  (V=0.8261)

  ⚔ Combat Phase:
    Teacher predicted placement: 0.714 (3.0th place)
    Alive players: 2/8
    💀 1 名对手被淘汰 — agent 进入决赛!

─── Turn 15 ───
  State: HP=8  Gold=10  Tier=6  Armor=0
  Board: 4 个随从

  [0-2] buy × 3 → 疯狂购物，金币全花
  [3] refresh
  [4] END_TURN  (V=0.8710)

  ⚔ Combat Phase:
    Teacher predicted placement: 0.857 (2.0th place)
    Alive players: 2/8
    Agent 存活到终局 — 第二名!
```

### 最终排名

```
  1. Overlord Saurfang        (HP=29, alive=True)
  2. Yogg-Saron, Hope's End   (HP=8,  alive=True)   ← AGENT
  3. Sneed                    (HP=0,  alive=False)
  4. Ysera                    (HP=0,  alive=False)
  5. Inge, the Iron Hymn      (HP=0,  alive=False)
  6. Professor Putricide      (HP=0,  alive=False)
  7. Sylvanas Windrunner      (HP=0,  alive=False)
  8. Drek'Thar                (HP=0,  alive=False)
```

### 游戏分析

| 维度 | 评价 |
|------|------|
| 升级策略 | **极其激进** — Turn 2 升 Tier 2，Turn 4 连续 4 次升级直冲 Tier 6 |
| 早期购买 | Turn 1-4 **零购买** — 3 回合空棋盘，完全放弃前期战力 |
| 中期崛起 | Turn 5 开始购买 Tier 6 随从，单回合棋盘从空变强 |
| 生存能力 | 18 点护甲吸收了大量伤害 — Turn 1-4 空棋盘但 HP 仅损 2 点 |
| 后期运营 | Turn 9-15 稳定替换弱随从，保持 3-4 个大型随从 + 圣盾 |
| 排名预测 | Teacher 对早期排名的预测 (1.0) 完全失效 — 空棋盘≠强 |
| 最终表现 | **2nd** — 远超污染版 demo 的 4th/4th/3rd |

---

## 对比分析: 污染 vs 干净

### 关键指标对比

| 指标 | 污染版 (v6, 3 局) | 干净版 (v4_clean, 1 局) |
|------|--------------------|------------------------|
| avg_rank | 3.67 (4th, 4th, 3rd) | **2.00** (2nd) |
| 最高酒馆等级 | Tier 1 | **Tier 6** |
| 升级次数 | 0 | 5 |
| 存活回合 | 6-7 | **15** (终局) |
| 英雄护甲 | 0 | **18 → 0** (渐进消耗) |
| Turn 1 金色 | 出现 (池污染) | **无** |
| 最终 HP | 0 (均死亡) | **8** (存活) |
| 对手等级 | 全程 Tier 1 | **升级至 Tier 6** |

### 行为变化分析

#### 1. 升级行为 — 彻底不同

```
污染版: Turn 1-6 全程 Tier 1，从未升级
干净版: Turn 2 → Tier 2, Turn 4 → Tier 6 (连续 4 次升级!)
```

**原因**: 
- 干净版的价值网络学会了升级的长期价值
- v4 POMDP 特征 (对手酒馆等级、升级回合) 提供了升级时机信号
- 对手也会升级 → 不升级就会落后 → 网络学到了这个竞争压力

#### 2. 护甲系统 — 改变游戏节奏

```
污染版: HP=30 → 27 → 22 → 12 → 2 → 0 (6 回合快速死亡)
干净版: HP=30(A=18) → 30(A=16) → 30(A=13) → 30(A=8) → 28 → 28 → ... → 8
```

18 点护甲让 agent 在前 4 回合空棋盘状态下仍然保持满血，为激进升本策略提供了安全缓冲。

#### 3. 金色合成 — 不再虚假

污染版 demo 中频繁出现 Turn 1-3 金色随从，是因为随从池混入了 `_Buddy_G` 和 `_G` 卡牌。干净版完全没有这个问题。

---

## 诊断与改进方向

### 正向信号

1. **升级策略成功**: 网络学会了升本的价值 — Turn 2 升本是正确的酒馆战棋策略
2. **护甲利用**: 18 护甲提供了安全边际，agent 在高护甲期激进升本
3. **后期运营**: Turn 9+ 的替换策略合理 (出售弱随从 → 购买更强的)
4. **生存能力**: 从污染版的 6-7 回合死亡提升到 15 回合终局存活

### 仍需改进

1. **Turn 1 空过**: 3 金币 0 购买 — 任何酒馆战棋玩家都会在 Turn 1 买一个随从。V 值预测 0.7136（空棋盘排名 1st）显然是错误的，导致 END_TURN 被认为是最佳选择
2. **Turn 3 空过**: 5 金币在手仍不购买 — 累积了过多的"升本优先"偏向
3. **连续 4 次升级**: Turn 4 从 Tier 2 → Tier 6 是极端激进的策略，实战中很可能被惩罚（但 v4 网络预测对了 — agent 最终 2nd）
4. **Teacher 早期预测失效**: Turn 1-4 空棋盘时 Teacher 预测 rank=1.0 — 这显然不对，空棋盘不可能赢

### 建议

1. **Turn 1 策略修正**: 在早期 (gold ≤ 4) 强制至少购买一个随从，或增加早期购买的奖励信号
2. **升级平滑化**: 限制单回合升级次数 (最多 2 次/回合)
3. **Teacher 修正**: 空棋盘不应该得到 rank=1.0 的预测 — 需要修正 combat predictor 对空棋盘的处理
4. **POMDP v5**: 加入战斗模拟作为价值估计的锚点，防止纯价值网络在早期产生荒谬预测
