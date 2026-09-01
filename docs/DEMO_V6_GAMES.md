# SearchAgent v6 贪心前瞻 — 实战演示文档

生成时间: 2026-05-14 | 模型: BoardEval v2 + GameValue v6 | 搜索: Greedy One-Step Lookahead

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
| `rearrange` | 重排棋盘 |
| `use_hero_power` | 使用英雄技能 |
| `END_TURN` | 结束回合，进入战斗 |

---

## Game 1 — Seed 42

### 对局信息

| 项目 | 内容 |
|------|------|
| Agent 英雄 | **Yogg-Saron, Hope's End** |
| 对手 1 | Sneed |
| 对手 2 | Overlord Saurfang |
| 对手 3 | Ysera |
| 对手 4 | Inge, the Iron Hymn |
| 对手 5 | Professor Putricide |
| 对手 6 | Sylvanas Windrunner |
| 对手 7 | Drek'Thar |
| 最终排名 | **4th** (HP=0, 第 6 回合死亡) |
| 总操作数 | 19 |
| 状态评估次数 | 213 |

### 回合详细日志

```
─── Turn 1 ───
  State: HP=30  Gold=3  Tier=1  Armor=0
  Board: (empty)
  Tavern: [0] Minion 0/10 T1 $3 | [1] Minion 0/8 T1 $3 | [2] Minion 0/12 T1 $3 | [3] Minion 0/0 T1 $3
  Initial V_game = 0.7102

  [0] buy_tavern_0  (V: 0.7102 → 0.9391, Δ=+0.2288)
       → buy 0/10 minion
  [1] play_hand_0  (V: 0.9391 → 1.0365, Δ=+0.0974)
       → play 5/10 from hand
  [2] END_TURN  (V=1.0365)
       → Ending recruit phase, proceeding to combat

  ⚔ Combat Phase:
    Pre-combat board:  (empty)
    Post-combat board: 5/10
    Teacher predicted placement: 1.000 (1.0th place)
    Alive players: 8/8

─── Turn 2 ───
  State: HP=30  Gold=4  Tier=1  Armor=0
  Board: 5/10
  Tavern: [0] Minion 0/9 T1 $3 | [1] Minion 0/13 T1 $3 | [2] Minion 0/1 T1 $3 | [3] Minion 0/0 T1 $3
  Initial V_game = 0.7147

  [0] buy_tavern_0  (V: 0.7147 → 0.9428, Δ=+0.2280)
       → buy 0/9 minion
  [1] refresh  (V: 0.9428 → 1.0165, Δ=+0.0737)
       → refresh for better minion options
  [2] play_hand_0  (V: 1.0165 → 1.1550, Δ=+0.1385)
       → play 10/9 [G] from hand (金色合成!)
  [3] rearrange  (V: 1.1550 → 1.1550, Δ=+0.0000)
       → execute action
  [4] END_TURN  (V=1.1550)
       → Ending recruit phase, proceeding to combat

  ⚔ Combat Phase:
    Pre-combat board:  5/10
    Post-combat board: 10/9 [G], 5/10
    Teacher predicted placement: 1.000 (1.0th place)
    Alive players: 8/8

─── Turn 3 ───
  State: HP=27  Gold=5  Tier=1  Armor=0
  Board: 10/9 [G], 5/10
  Tavern: [0] Minion 0/2 T1 $3 | [1] Minion 0/8 T1 $3 | [2] Minion 0/7 T1 $3
  Initial V_game = 0.7579

  [0] buy_tavern_0  (V: 0.7579 → 0.9130, Δ=+0.1551)
       → buy 0/2 minion
  [1] play_hand_0  (V: 0.9130 → 0.9663, Δ=+0.0532)
       → play 4/2 [DS,WF] from hand
  [2] refresh  (V: 0.9663 → 1.0149, Δ=+0.0487)
       → refresh for better minion options
  [3] refresh  (V: 1.0149 → 1.0528, Δ=+0.0379)
       → refresh for better minion options
  [4] END_TURN  (V=1.0528)
       → Ending recruit phase, proceeding to combat

  ⚔ Combat Phase:
    Pre-combat board:  10/9 [G], 5/10
    Post-combat board: 10/9 [G], 5/10, 4/2 [DS,WF]
    Teacher predicted placement: 0.286 (6.0th place)
    Alive players: 8/8

─── Turn 4 ───
  State: HP=22  Gold=6  Tier=1  Armor=0
  Board: 10/9 [G], 5/10, 4/2 [DS,WF]
  Tavern: [0] Minion 0/4 T1 $3 | [1] Minion 0/8 T1 $3 | [2] Minion 0/21 T1 $3
  Initial V_game = 0.7614

  [0] buy_tavern_0  (V: 0.7614 → 0.7893, Δ=+0.0279)
       → buy 0/4 minion
  [1] buy_tavern_0  (V: 0.7893 → 0.9190, Δ=+0.1296)
       → buy 0/8 minion
  [2] play_hand_1  (V: 0.9190 → 0.9876, Δ=+0.0687)
       → play 8/8 from hand
  [3] play_hand_0  (V: 0.9876 → 1.0187, Δ=+0.0311)
       → play 4/4 from hand
  [4] END_TURN  (V=1.0187)
       → Ending recruit phase, proceeding to combat

  ⚔ Combat Phase:
    Pre-combat board:  10/9 [G], 5/10, 4/2 [DS,WF]
    Post-combat board: 10/9 [G], 5/10, 4/2 [DS,WF], 8/8, 4/4
    Teacher predicted placement: 0.143 (7.0th place)
    Alive players: 8/8

─── Turn 5 ───
  State: HP=12  Gold=7  Tier=1  Armor=0
  Board: 10/9 [G], 5/10, 4/2 [DS,WF], 8/8, 4/4
  Tavern: [0] Minion 0/4 T1 $3 | [1] Minion 0/10 T1 $3 | [2] Minion 0/1 T1 $3
  Initial V_game = 0.6399

  [0] sell_board_2  (V: 0.6399 → 0.6594, Δ=+0.0195)
       → sell 4/2 [DS,WF] for +1 gold
  [1] END_TURN  (V=0.6594)
       → Ending recruit phase, proceeding to combat

  ⚔ Combat Phase:
    Pre-combat board:  10/9 [G], 5/10, 4/2 [DS,WF], 8/8, 4/4
    Post-combat board: 10/9 [G], 5/10, 8/8, 4/4
    Teacher predicted placement: 0.143 (7.0th place)
    Alive players: 8/8

─── Turn 6 ───
  State: HP=2  Gold=8  Tier=1  Armor=0
  Board: 10/9 [G], 5/10, 8/8, 4/4
  Tavern: [0] Minion 0/2 T1 $3 | [1] Minion 0/2 T1 $3 | [2] Minion 0/8 T1 $3
  Initial V_game = 0.3558

  [0] sell_board_1  (V: 0.3558 → 0.4126, Δ=+0.0568)
       → sell 5/10 for +1 gold
  [1] refresh  (V: 0.4126 → 0.4147, Δ=+0.0021)
       → refresh for better minion options
  [2] refresh  (V: 0.4147 → 0.4167, Δ=+0.0021)
       → refresh for better minion options
  [3] refresh  (V: 0.4167 → 0.4183, Δ=+0.0016)
       → refresh for better minion options
  [4] END_TURN  (V=0.4183)
       → Ending recruit phase, proceeding to combat

  ⚔ Combat Phase:
    Pre-combat board:  10/9 [G], 5/10, 8/8, 4/4
    Post-combat board: 10/9 [G], 8/8, 4/4
    Teacher predicted placement: 0.000 (8.0th place)
    Alive players: 7/8

  💀 Agent eliminated!

─── Turn 7 ───
  State: HP=0  Gold=8  Tier=1  Armor=0
  Board: 10/9 [G], 8/8, 4/4
  Initial V_game = 0.3558
  [Agent is dead — automatic turns]
```

### 最终排名

```
  1. Ysera                    (HP=10, alive=True)
  2. Professor Putricide      (HP=4,  alive=True)
  3. Overlord Saurfang        (HP=3,  alive=True)
  4. Yogg-Saron, Hope's End   (HP=0,  alive=False)  ← AGENT
  5. Sneed                    (HP=0,  alive=False)
  6. Inge, the Iron Hymn      (HP=0,  alive=False)
  7. Sylvanas Windrunner      (HP=0,  alive=False)
  8. Drek'Thar                (HP=0,  alive=False)
```

### 游戏分析

| 维度 | 评价 |
|------|------|
| Tier 1 购买 | Turn 1 买入 → Turn 2 金色合成，节奏不错 |
| 酒馆等级 | **全程 Tier 1，从未尝试升级** |
| 刷新频率 | Turn 3-6 累计刷新 5 次浪费金币 |
| 出售策略 | Turn 5 血量低时售出 DS+WF 优质随从（仅卖 4/2）|
| 金币利用率 | Turn 6 手握 8 金币打出 3/8 + 2/3 低级随从 |
| 死亡原因 | 对手升级后成长碾压 — 低本随从无法与 Tier 3-4 对手抗衡 |

---

## Game 2 — Seed 123

### 对局信息

| 项目 | 内容 |
|------|------|
| Agent 英雄 | **Guff Runetotem** |
| 对手 1 | Cap'n Hoggarr |
| 对手 2 | Cariel Roame |
| 对手 3 | Malygos |
| 对手 4 | Time Twister Chromie |
| 对手 5 | Cookie the Cook |
| 对手 6 | Jandice Barov |
| 对手 7 | Y'Shaarj |
| 最终排名 | **4th** (HP=0, 第 6 回合死亡) |
| 总操作数 | 18 |
| 状态评估次数 | 198 |

### 回合详细日志

```
─── Turn 1 ───
  State: HP=30  Gold=3  Tier=1  Armor=0
  Board: (empty)
  Tavern: [0] Minion 0/4 T1 $3 | [1] Minion 0/8 T1 $3 | [2] Minion 0/2 T1 $3 | [3] Minion 0/0 T1 $3
  Initial V_game = 0.6652

  [0] buy_tavern_0  (V: 0.6652 → 0.9023, Δ=+0.2371)
       → buy 0/4 minion
  [1] play_hand_0  (V: 0.9023 → 0.9538, Δ=+0.0515)
       → play 4/4 from hand
  [2] END_TURN  (V=0.9538)
       → Ending recruit phase, proceeding to combat

  ⚔ Combat Phase:
    Pre-combat board:  (empty)
    Post-combat board: 4/4
    Teacher predicted placement: 1.000 (1.0th place)
    Alive players: 8/8

─── Turn 2 ───
  State: HP=30  Gold=4  Tier=1  Armor=0
  Board: 4/4
  Tavern: [0] Minion 0/9 T1 $3 | [1] Minion 0/3 T1 $3 | [2] Minion 0/1 T1 $3 | [3] Minion 0/0 T1 $3
  Initial V_game = 0.6083

  [0] buy_tavern_0  (V: 0.6083 → 0.8733, Δ=+0.2650)
       → buy 0/9 minion
  [1] refresh  (V: 0.8733 → 0.9532, Δ=+0.0799)
       → refresh for better minion options
  [2] play_hand_0  (V: 0.9532 → 1.0676, Δ=+0.1144)
       → play 8/9 [G] from hand (金色合成!)
  [3] END_TURN  (V=1.0676)
       → Ending recruit phase, proceeding to combat

  ⚔ Combat Phase:
    Pre-combat board:  4/4
    Post-combat board: 4/4, 8/9 [G]
    Teacher predicted placement: 1.000 (1.0th place)
    Alive players: 8/8

─── Turn 3 ───
  State: HP=28  Gold=5  Tier=1  Armor=0
  Board: 4/4, 8/9 [G]
  Tavern: [0] Minion 0/12 T1 $3 | [1] Minion 0/18 T1 $3 | [2] Minion 0/1 T1 $3
  Initial V_game = 0.7190

  [0] buy_tavern_0  (V: 0.7190 → 0.8733, Δ=+0.1543)
       → buy 0/12 minion
  [1] refresh  (V: 0.8733 → 0.9103, Δ=+0.0370)
       → refresh for better minion options
  [2] play_hand_0  (V: 0.9103 → 1.0037, Δ=+0.0934)
       → play 4/12 [G] from hand (第二个金色!)
  [3] refresh  (V: 1.0037 → 1.0417, Δ=+0.0380)
       → refresh for better minion options
  [4] END_TURN  (V=1.0417)
       → Ending recruit phase, proceeding to combat

  ⚔ Combat Phase:
    Pre-combat board:  4/4, 8/9 [G]
    Post-combat board: 4/4, 8/9 [G], 4/12 [G]
    Teacher predicted placement: 0.286 (6.0th place)
    Alive players: 8/8

─── Turn 4 ───
  State: HP=23  Gold=6  Tier=1  Armor=0
  Board: 4/4, 8/9 [G], 4/12 [G]
  Tavern: [0] Minion 0/5 T1 $3 | [1] Minion 0/3 T1 $3 | [2] Minion 0/8 T1 $3
  Initial V_game = 0.7246

  [0] sell_board_0  (V: 0.7246 → 0.7438, Δ=+0.0192)
       → sell 4/4 for +1 gold
  [1] play_hand_0  (V: 0.7438 → 0.7583, Δ=+0.0145)
       → play 2/2 from hand (低级随从，手牌填充)
  [2] sell_board_2  (V: 0.7583 → 0.7962, Δ=+0.0379)
       → sell 2/2 for +1 gold (刚打出就卖!)
  [3] END_TURN  (V=0.7962)
       → Ending recruit phase, proceeding to combat

  ⚔ Combat Phase:
    Pre-combat board:  4/4, 8/9 [G], 4/12 [G]
    Post-combat board: 8/9 [G], 4/12 [G]
    Teacher predicted placement: 0.143 (7.0th place)
    Alive players: 8/8

─── Turn 5 ───
  State: HP=13  Gold=7  Tier=1  Armor=0
  Board: 8/9 [G], 4/12 [G]
  Tavern: [0] Minion 0/6 T1 $3 | [1] Minion 0/4 T1 $3 | [2] Minion 0/9 T1 $3
  Initial V_game = 0.5946

  [0] play_hand_0  (V: 0.5946 → 0.6941, Δ=+0.0995)
       → play 5/5 from hand
  [1] sell_board_2  (V: 0.6941 → 0.6971, Δ=+0.0030)
       → sell 5/5 for +1 gold (又卖了刚打的!)
  [2] END_TURN  (V=0.6971)
       → Ending recruit phase, proceeding to combat

  ⚔ Combat Phase:
    Pre-combat board:  8/9 [G], 4/12 [G]
    Post-combat board: 8/9 [G], 4/12 [G]
    Teacher predicted placement: 0.143 (7.0th place)
    Alive players: 8/8

─── Turn 6 ───
  State: HP=3  Gold=8  Tier=1  Armor=0
  Board: 8/9 [G], 4/12 [G]
  Tavern: [0] Minion 0/9 T1 $3 | [1] Minion 0/9 T1 $3 | [2] Minion 0/2 T1 $3
  Initial V_game = 0.1083

  [0] sell_board_1  (V: 0.1083 → 0.1292, Δ=+0.0209)
       → sell 4/12 [G] for +1 gold (卖出金色随从!)
  [1] refresh  (V: 0.1292 → 0.1316, Δ=+0.0024)
       → refresh for better minion options
  [2] refresh  (V: 0.1316 → 0.1340, Δ=+0.0024)
       → refresh for better minion options
  [3] refresh  (V: 0.1340 → 0.1346, Δ=+0.0006)
       → refresh for better minion options
  [4] END_TURN  (V=0.1346)
       → Ending recruit phase, proceeding to combat

  ⚔ Combat Phase:
    Pre-combat board:  8/9 [G], 4/12 [G]
    Post-combat board: 8/9 [G]
    Teacher predicted placement: 0.143 (7.0th place)
    Alive players: 6/8

  💀 Agent eliminated!
```

### 最终排名

```
  1. Y'Shaarj                 (HP=30, alive=True)
  2. Cookie the Cook          (HP=25, alive=True)
  3. Malygos                  (HP=9,  alive=True)
  4. Guff Runetotem           (HP=0,  alive=False)  ← AGENT
  5. Cap'n Hoggarr            (HP=0,  alive=False)
  6. Cariel Roame             (HP=0,  alive=False)
  7. Time Twister Chromie     (HP=0,  alive=False)
  8. Jandice Barov            (HP=0,  alive=False)
```

### 游戏分析

| 维度 | 评价 |
|------|------|
| 早期合成 | Turn 2 + Turn 3 连续两回合金色合成，开局极强 |
| 酒馆等级 | **全程 Tier 1** — 与 Game 1 同样问题 |
| 操作浪费 | Turn 4 打出 2/2 立即出售 → 净亏 2 金币；Turn 5 同样打出 5/5 后立即出售 |
| 金卡出售 | Turn 6 濒死时出售 4/12 [G] — 不保留核心战力 |
| 刷新行为 | Turn 6 连续 3 次刷新，期望从 Tier 1 池中找到翻盘卡 — 无意义 |
| 对手差距 | Y'Shaarj HP=30 满血存活 — agent 从未对其造成威胁 |

---

## Game 3 — Seed 777

### 对局信息

| 项目 | 内容 |
|------|------|
| Agent 英雄 | **Sire Denathrius** |
| 对手 1 | Flobbidinous Floop |
| 对手 2 | Kerrigan, Queen of Blades |
| 对手 3 | The Lich King |
| 对手 4 | Cap'n Hoggarr |
| 对手 5 | The Jailer |
| 对手 6 | Zerek, Master Cloner |
| 对手 7 | George the Fallen |
| 最终排名 | **3rd** (HP=0, 第 6 回合死亡) |
| 总操作数 | 18 |
| 状态评估次数 | 240 |

### 回合详细日志

```
─── Turn 1 ───
  State: HP=30  Gold=3  Tier=1  Armor=0
  Board: (empty)
  Tavern: [0] Minion 0/4 T1 $3 | [1] Minion 0/2 T1 $3 | [2] Minion 0/6 T1 $3 | [3] Minion 0/0 T1 $3
  Initial V_game = 0.6652

  [0] buy_tavern_0  (V: 0.6652 → 0.9023, Δ=+0.2371)
       → buy 0/4 minion
  [1] play_hand_0  (V: 0.9023 → 0.9403, Δ=+0.0379)
       → play 8/4 [G] from hand (开局金色!)
  [2] END_TURN  (V=0.9152)
       → Ending recruit phase, proceeding to combat

  ⚔ Combat Phase:
    Pre-combat board:  (empty)
    Post-combat board: 8/4 [G]
    Teacher predicted placement: 1.000 (1.0th place)
    Alive players: 8/8

─── Turn 2 ───
  State: HP=28  Gold=4  Tier=1  Armor=0
  Board: 8/4 [G]
  Tavern: [0] Minion 0/3 T1 $3 | [1] Minion 0/7 T1 $3 | [2] Minion 0/1 T1 $3 | [3] Minion 0/0 T1 $3
  Initial V_game = 0.5788

  [0] buy_tavern_0  (V: 0.5788 → 0.7256, Δ=+0.1468)
       → buy 0/3 minion
  [1] play_hand_0  (V: 0.7256 → 0.7741, Δ=+0.0485)
       → play 6/3 from hand
  [2] refresh  (V: 0.7741 → 0.8261, Δ=+0.0520)
       → refresh for better minion options
  [3] END_TURN  (V=0.8261)
       → Ending recruit phase, proceeding to combat

  ⚔ Combat Phase:
    Pre-combat board:  8/4 [G]
    Post-combat board: 8/4 [G], 6/3
    Teacher predicted placement: 0.429 (5.0th place)
    Alive players: 8/8

─── Turn 3 ───
  State: HP=25  Gold=5  Tier=1  Armor=0
  Board: 8/4 [G], 6/3
  Tavern: [0] Minion 0/4 T1 $3 | [1] Minion 0/5 T1 $3 | [2] Minion 0/9 T1 $3
  Initial V_game = 0.6051

  [0] buy_tavern_0  (V: 0.6051 → 0.7965, Δ=+0.1915)
       → buy 0/4 minion
  [1] play_hand_0  (V: 0.7965 → 0.8535, Δ=+0.0570)
       → play 4/4 from hand
  [2] refresh  (V: 0.8535 → 0.8935, Δ=+0.0400)
       → refresh for better minion options
  [3] refresh  (V: 0.8935 → 0.9312, Δ=+0.0377)
       → refresh for better minion options
  [4] END_TURN  (V=0.9312)
       → Ending recruit phase, proceeding to combat

  ⚔ Combat Phase:
    Pre-combat board:  8/4 [G], 6/3
    Post-combat board: 8/4 [G], 6/3, 4/4
    Teacher predicted placement: 0.000 (8.0th place)
    Alive players: 8/8

─── Turn 4 ───
  State: HP=23  Gold=6  Tier=1  Armor=0
  Board: 8/4 [G], 6/3, 4/4
  Tavern: [0] Minion 0/9 T1 $3 | [1] Minion 0/4 T1 $3 | [2] Minion 0/13 T1 $3
  Initial V_game = 0.7303

  [0] buy_tavern_0  (V: 0.7303 → 0.7910, Δ=+0.0608)
       → buy 0/9 minion
  [1] buy_tavern_0  (V: 0.7910 → 0.9103, Δ=+0.1192)
       → buy 0/4 minion
  [2] play_hand_0  (V: 0.9103 → 1.0040, Δ=+0.0937)
       → play 4/9 [G] from hand (又一个金色!)
  [3] play_hand_0  (V: 1.0040 → 1.0464, Δ=+0.0424)
       → play 7/4 from hand
  [4] END_TURN  (V=1.0464)
       → Ending recruit phase, proceeding to combat

  ⚔ Combat Phase:
    Pre-combat board:  8/4 [G], 6/3, 4/4
    Post-combat board: 8/4 [G], 6/3, 4/4, 4/9 [G], 7/4
    Teacher predicted placement: 0.286 (6.0th place)
    Alive players: 8/8

─── Turn 5 ───
  State: HP=13  Gold=7  Tier=1  Armor=0
  Board: 8/4 [G], 6/3, 4/4, 4/9 [G], 7/4
  Tavern: [0] Minion 0/6 T1 $3 | [1] Minion 0/8 T1 $3 | [2] Minion 0/8 T1 $3
  Initial V_game = 0.2479

  [0] play_hand_4  (V: 0.2479 → 0.4091, Δ=+0.1612)
       → play 6/6 [G] from hand (第三个金色!)
  [1] END_TURN  (V=0.3644)
       → Ending recruit phase, proceeding to combat

  ⚔ Combat Phase:
    Pre-combat board:  8/4 [G], 6/3, 4/4, 4/9 [G], 7/4
    Post-combat board: 8/4 [G], 6/3, 4/4, 4/9 [G], 7/4, 6/6 [G]
    Teacher predicted placement: 0.143 (7.0th place)
    Alive players: 8/8

─── Turn 6 ───
  State: HP=3  Gold=8  Tier=1  Armor=0
  Board: 8/4 [G], 6/3, 4/9 [G], 9/6, 6/6 [G]
  Tavern: [0] Minion 0/4 T1 $3 | [1] Minion 0/8 T1 $3 | [2] Minion 0/4 T1 $3
  Initial V_game = 0.1495

  [0] play_hand_6  (V: 0.1495 → 0.2240, Δ=+0.0744)
       → play 3/8 from hand
  [1] play_hand_8  (V: 0.2240 → 0.2549, Δ=+0.0310)
       → play 2/3 from hand
  [2] sell_board_6  (V: 0.2549 → 0.2837, Δ=+0.0288)
       → sell 3/5 for +1 gold
  [3] rearrange  (V: 0.2837 → 0.2837, Δ=+0.0000)
       → execute action
  [4] END_TURN  (V=0.2837)
       → Ending recruit phase, proceeding to combat

  ⚔ Combat Phase:
    Pre-combat board:  8/4 [G], 6/3, 4/9 [G], 9/6, 6/6 [G]
    Post-combat board: 9/6, 8/4 [G], 6/6 [G], 6/3, 4/9 [G], 3/8
    Teacher predicted placement: 0.000 (8.0th place)
    Alive players: 6/8

  💀 Agent eliminated!
```

### 最终排名

```
  1. Cap'n Hoggarr            (HP=28, alive=True)
  2. The Jailer               (HP=6,  alive=True)
  3. Sire Denathrius          (HP=0,  alive=False)  ← AGENT
  4. Flobbidinous Floop       (HP=0,  alive=False)
  5. Kerrigan, Queen of Blades(HP=0,  alive=False)
  6. The Lich King            (HP=0,  alive=False)
  7. Zerek, Master Cloner     (HP=0,  alive=False)
  8. George the Fallen        (HP=0,  alive=False)
```

### 游戏分析

| 维度 | 评价 |
|------|------|
| 开局极度 lucky | Turn 1 直接 8/4 [G] 金色随从开局 |
| 三连合成 | Turn 1、4、5 三次金色合成 — 但全是 Tier 1 随从的三连 |
| 酒馆等级 | **全程 Tier 1** — 三局中共 57 个回合，agent 从未升级酒馆 |
| 资源浪费 | 手握 8 金币在 Tier 1 打出 3/8 + 2/3 — 低级身材无战力 |
| 最佳表现 | 排名 3rd 是三局中最好的，但纯粹靠开局 luck（金色随从多） |
| 死亡模式 | 同样在第 6 回合被淘汰，升级的对手碾压 |

---

## 综合诊断

三场 demo 的共性问题非常明显：

### 1. 酒馆等级停滞 — 最大致命伤

| 指标 | Game 1 | Game 2 | Game 3 |
|------|--------|--------|--------|
| 最高 Tier | 1 | 1 | 1 |
| 升级尝试次数 | **0** | **0** | **0** |
| 存活回合数 | 6 | 6 | 6 |

agent **从未选择升级酒馆**。根本原因：
- 升级需要花费 (Tier 2=5 金, Tier 3=7 金)，当回合不直接增加战力
- v6 价值网络在"当前回合平铺买 3 个 T1 随从"和"空过升级"之间，总是倾向前者
- Teacher 信号在整个对局中给 Tier 1 满编随从的排名预测偏高（因为能打平低级对手），网络没有学到升级的长期价值

### 2. 无效刷新泛滥

Turn 4-6 低血量时，agent 习惯性连续刷新 3 次（花费 3 金），试图从 Tier 1 池中找到"逆转卡"。实际上 Tier 1 池没有这种卡——应该升级到 Tier 3/4 寻找核心随从。

### 3. 操作短视

| 短视行为 | 出现频率 |
|----------|----------|
| 买随从 → 立即出售 | Game 2 × 2 次 |
| 连续刷新 > 2 次 | Game 1, 2, 3 均有 |
| 出售金色随从 4/12 [G] | Game 2 Turn 6 |
| 低血量出售核心战力 | 三局均如此 |

### 4. 正向信号

- **初期动作质量高**: Turn 1-3 的买入/打出选择合理
- **金色合成意识**: 能通过刷新找到相同随从完成三连（3 局累计 6 次金色合成）
- **V 值变化方向正确**: 买入 → V↑，出售垃圾 → V↑，升级的价值判断方向正确但量级不够

### 改进方向

1. **v7 per-action 训练**: 记录更多"升级后"的中间状态，让网络学会升级的长期价值
2. **升级奖励 shaping**: 在训练目标中人为提高升级后状态的 teacher 得分
3. **束搜索**: 2-3 步深度的束搜索更容易发现"升级→下回合买高本"的收益路径
