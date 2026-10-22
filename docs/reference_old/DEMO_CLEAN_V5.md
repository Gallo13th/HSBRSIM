# Hearthstone Battlegrounds — SearchAgent v2 演示文档（v5 干净版本）

**日期**: 2026-05-14  
**种子**: 42  
**模型**: BoardEval v2 + GameValue v4 (POMDP 397-dim)  
**关键修复**: 升级费用系统（金币扣除 + 费用梯度 5/7/8/9/10）

---

## 修复说明

v4 演示中发现两个严重 bug:

| Bug | 描述 | 影响 |
|-----|------|------|
| 升级不扣金币 | `UpgradeTavern.do()` 从未调用 `SpendGold` | 所有升级免费 |
| 升级费用不增长 | `TAVERN_UPGRADE_COST` 始终为 5（仅逐回合减 1） | 升到任何等级费用相同 |
| 状态恢复遗漏 | `demo_game.py`/`search_agent.py` 保存/恢复未包含 `TAVERN_UPGRADE_COST` | 前瞻模拟后实际执行静默失败 |

**修复后升级费用表**:

| 目标酒馆等级 | 基础费用 | Turn 2 实际费用（减 2） | Turn 5 实际费用（减 5） |
|-------------|---------|----------------------|----------------------|
| Tier 1→2 | 5 | 3 | — |
| Tier 2→3 | 7 | — | 2 |
| Tier 3→4 | 8 | — | 3 |
| Tier 4→5 | 9 | — | 4 |
| Tier 5→6 | 10 | — | 5 |

---

## 对局日志

### 阵容

| 角色 | 英雄 |
|------|------|
| **智能体** | Yogg-Saron, Hope's End (护甲 18) |
| 对手 1 | Sneed |
| 对手 2 | Overlord Saurfang |
| 对手 3 | Ysera |
| 对手 4 | Inge, the Iron Hymn |
| 对手 5 | Professor Putricide |
| 对手 6 | Sylvanas Windrunner |
| 对手 7 | Drek'Thar |

---

### Turn 1

```
State: HP=30  Gold=3  Tier=1  Armor=18
Board: (empty)
```

| # | 动作 | V_before → V_after | 说明 |
|---|------|-------------------|------|
| 0 | buy_tavern_0 | 0.9473 → 1.0119 | 购买 1/1 随从 |
| 1 | play_hand_0 | 1.0119 → 1.1134 | 打出 1/1 |
| 2 | END_TURN | V=1.1134 | 结束招募 |

**战斗结果**: 存活 1/1，预测排名 1.0（第 1 名）  
**剩余玩家**: 8/8

---

### Turn 2

```
State: HP=30  Gold=4  Tier=1  Armor=16
Board: 1/1
```

| # | 动作 | V_before → V_after | 说明 |
|---|------|-------------------|------|
| 0 | upgrade | 0.8903 → 1.0626 | **升级至 Tier 2**（费用 3 金币） |
| 1 | refresh | 1.0626 → 1.1025 | 刷新酒馆 |
| 2 | END_TURN | V=1.1025 | 结束招募 |

**关键观察**: 升级消耗 3 金币（基础 5 - 2 回合递减）。升级后金币: 4 → 1。刷新后金币: 0。

---

### Turn 3

```
State: HP=30  Gold=5  Tier=2  Armor=14
Board: 1/1
Tavern: 4 个 Tier 2 随从（比 v4 的 Tier 6 tavern 合理得多）
```

| # | 动作 | V_before → V_after | 说明 |
|---|------|-------------------|------|
| 0 | buy_tavern_0 | 0.7646 → 0.9050 | 购买 6/2 随从 |
| 1 | play_hand_0 | 0.9050 → 1.0131 | 打出 6/2 |
| 2 | refresh | 1.0131 → 1.0688 | 刷新 |
| 3 | refresh | 1.0688 → 1.1207 | 再次刷新 |
| 4 | END_TURN | V=1.1207 | 结束招募 |

**关键观察**: 升级至 Tier 3 费用为 6（基础 7 - 1 回合递减），Gold=5 < 6，**无法升级**。智能体正确选择了购买和刷新路径。

---

### Turn 4

```
State: HP=30  Gold=6  Tier=2  Armor=11
Board: 1/1, 6/2
```

| # | 动作 | V_before → V_after | 说明 |
|---|------|-------------------|------|
| 0 | upgrade | 0.9245 → 1.1446 | **升级至 Tier 3**（费用 6 金币） |
| 1 | refresh | 1.1446 → 1.1826 | 刷新 |
| 2 | END_TURN | V=1.1826 | 结束招募 |

---

### Turn 5

```
State: HP=30  Gold=7  Tier=3  Armor=5
Board: 1/1, 6/2
```

| # | 动作 | V_before → V_after | 说明 |
|---|------|-------------------|------|
| 0 | upgrade | 0.7399 → 1.1303 | **升级至 Tier 4**（费用 ~7 金币） |
| 1 | END_TURN | V=1.1303 | 结束招募 |

---

### Turn 6

```
State: HP=27  Gold=8  Tier=4  Armor=0
Board: 1/1, 6/2
```

| # | 动作 | V_before → V_after | 说明 |
|---|------|-------------------|------|
| 0 | upgrade | 0.6317 → 1.1317 | **升级至 Tier 5** |
| 1 | END_TURN | V=1.1317 | 结束招募 |

---

### Turn 7

```
State: HP=17  Gold=9  Tier=5  Armor=0
Board: 1/1, 6/2
```

| # | 动作 | V_before → V_after | 说明 |
|---|------|-------------------|------|
| 0 | upgrade | 0.2857 → 0.8492 | **升级至 Tier 6** |
| 1 | END_TURN | V=0.8492 | 结束招募 |

---

### Turn 8

```
State: HP=7  Gold=10  Tier=6  Armor=0
Board: 1/1, 6/2
```

| # | 动作 | V_before → V_after | 说明 |
|---|------|-------------------|------|
| 0 | sell_board_0 | 0.0546 → 0.0770 | 卖出 1/1 (+1 金币) |
| 1 | sell_board_0 | 0.0770 → 0.0812 | 卖出 6/2 (+1 金币) |
| 2 | refresh | 0.0812 → 0.0812 | 刷新（Δ=0，无更好选择） |
| 3 | END_TURN | V=0.0812 | 结束招募 |

**战斗结果**: 棋盘全灭，被淘汰。最终排名 **第 3 名**。

---

## 最终排名

| 排名 | 英雄 | HP | 状态 |
|------|------|-----|------|
| 1 | Overlord Saurfang | 30 | 存活 |
| 2 | Drek'Thar | 2 | 存活 |
| **3** | **Yogg-Saron** | **0** | **阵亡 ← 智能体** |
| 4 | Sneed | 0 | 阵亡 |
| 5 | Ysera | 0 | 阵亡 |
| 6 | Inge, the Iron Hymn | 0 | 阵亡 |
| 7 | Professor Putricide | 0 | 阵亡 |
| 8 | Sylvanas Windrunner | 0 | 阵亡 |

---

## 与 v4（污染版本）的关键对比

| 指标 | v4（免费升级 bug） | v5（修复后） |
|------|-------------------|-------------|
| Turn 4 酒馆等级 | Tier 1→6（4 次连续免费升级） | Tier 2→3（1 次付费升级，5 金币） |
| Turn 5 酒馆等级 | Tier 6 | Tier 3→4 |
| Turn 5 对局 | Post-combat: 86/59 大型随从（bug） | Post-combat: 1/1, 6/2（正常） |
| 首次购买 | Turn 5（太晚，全在免费升级） | Turn 1（正常） |
| 金币使用 | 升级 0 金币，全部买随从 | 升级消耗 5-10 金币，节奏正常 |
| 平均酒馆等级曲线 | 1→2→3→4→5→6（4 回合完成） | 1→2→3→4→5→6（7 回合完成） |
| 智能体最终排名 | 第 3 名 | 第 3 名 |
| 智能体动作数 | ~20 | 16 |
| 状态评估次数 | ~200 | 189 |

---

## 已知问题分析

### 智能体策略缺陷：升级优先度过高

智能体在 Turn 2-7 几乎每回合优先升级，导致:
- 棋盘发展严重滞后（Turn 7 仅有 2 个 Tier 1 随从）
- 护甲在 Turn 6-7 耗尽
- Turn 8 卖出全部随从后被淘汰

**根因**: GameValue v4 训练数据来自启发式智能体（也已修复升级逻辑但仍有升级偏向），V(s') 预测高估了高酒馆等级的价值。

**改进方向**: 
1. GameValue v5 应使用更激进的购买策略教师数据
2. 或在奖励函数中增加对低酒馆等级买随从的显式激励

### 升级费用系统的递减机制

当前 `game.py:1297-1299` 每回合减少 `TAVERN_UPGRADE_COST` 1 点。这模拟了 Hearthstone 原版的"每回合升级费用 -1"机制。但在修复后，需确认递减后的费用不低于 1:

```python
# game.py:1296-1299
current_cost = p.get_tag(GameTag.TAVERN_UPGRADE_COST, 0)
if current_cost > 0:
    p.set_tag(GameTag.TAVERN_UPGRADE_COST, current_cost - 1)
```

修复版本在 `UpgradeTavern.do()` 中使用 `max(cost, 1)` 作为保底，防止费用降至 0。

---

## 架构总结

```
Combat Simulator → BoardEval v2 (99.1% pairwise acc) → GameValue v4 (397-dim POMDP) → SearchAgent v2 (greedy)
```

| 组件 | 参数 | 描述 |
|------|------|------|
| BoardEmbedder | 15,168 | (7,15) minion features → 32-dim embedding |
| CombatPredictor | 1,986 | Pairwise interaction prediction |
| GameValue v4 | 6,705 | 397-dim HDT-observable POMDP with per-opponent combat memory |
| SearchAgent v2 | — | Greedy one-step lookahead, avg_rank 2.00 |

---

## 下一步

- [ ] 重新训练 BoardEval v4（干净数据 + 正确升级费用）
- [ ] 重新训练 GameValue v5（干净环境 + 正确金币系统）
- [ ] 优化智能体策略：降低升级优先级，提升购买决策质量
- [ ] Phase 2: 提升英雄技能覆盖率 19.5% → 50%
