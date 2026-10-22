# HDT 游戏状态接口参考

> HrSRL Adviser 插件 — C# GameStateExtractor 暴露的完整游戏状态接口

## 1. 概述

C# 插件通过 WebSocket 以 JSON 格式发送 `game_state` 消息到 Python 推理服务器。消息顶层结构：

```json
{
  "type": "game_state",
  "game_id": "bg_20260505_211642_7737",
  "turn": 5,
  "phase": "recruit",
  "player": { ... },
  "tavern": [ ... ],
  "hand": [ ... ],
  "board": [ ... ],
  "trinkets": [ ... ],
  "opponents": [ ... ],
  "alive_count": 8,
  "damage_cap": 15,
  "anomaly_card_id": "BG_ANOMALY_001"
}
```

| # | 字段 | 类型 | 说明 |
|---|------|------|------|
| 1 | `type` | string | 固定值 `"game_state"` |
| 2 | `game_id` | string | 游戏唯一标识，格式 `bg_YYYYMMDD_HHmmss_NNNN` |
| 3 | `turn` | int | 当前回合数，≥1 |
| 4 | `phase` | string | `"recruit"`（招募阶段）或 `"combat"`（战斗阶段） |
| 5 | `player` | PlayerState | 自身玩家状态 |
| 6 | `tavern` | TavernSlot[7] | 酒馆随从/法术，空位为 `null` |
| 7 | `hand` | HandSlot[10] | 手牌，空位为 `null` |
| 8 | `board` | BoardSlot[7] | 己方战场随从，空位为 `null` |
| 9 | `trinkets` | TrinketSlot[2] | 饰品，空位为 `null` |
| 10 | `opponents` | OpponentSummary[7] | 对手概览，不足 7 人时填充 |
| 11 | `alive_count` | int | 存活玩家数量 |
| 12 | `damage_cap` | int? | 伤害上限（15），有玩家死亡时为 `null` |
| 13 | `anomaly_card_id` | string | 当前异变 CardId，无则为 `""` |

---

## 2. GameTag 参考

C# 插件通过 HDT 的 `Entity.GetTag(GameTag.XXX)` 读取实体标签。以下是所有使用的 GameTag：

### 2.1 玩家实体标签

| GameTag | 枚举值 | 字段 | 说明 |
|---------|--------|------|------|
| `HEALTH` | 21 | `player.health` | 当前血量 |
| `ARMOR` | 24 | `player.armor` | 当前护甲 |
| `RESOURCES` | 178 | `player.gold` | 当前回合基础铸币（= 最大可用） |
| `TEMP_RESOURCES` | 179 | `player.gold` | 临时铸币（如海盗效果） |
| `RESOURCES_USED` | 180 | `player.gold` | 已花费铸币 |
| `PLAYER_TECH_LEVEL` | 110 | `player.tavern_tier` | 酒馆等级 |
| `HERO_ENTITY` | 27 | `player.hero_card_id` | 英雄实体 ID → 查找英雄 CardId |
| `EXHAUSTED` | 72 | `player.hero_power_used` | 玩家实体 EXHAUSTED（备用判断） |
| `ADDITIONAL_HERO_POWER_ENTITY_1` | 167 | `player.hero_power_extra_uses` | 额外英雄技能实体 ID |
| `BACON_FREE_REFRESH_COUNT` | 142 | `player.free_refresh_remaining` | 免费刷新剩余次数 |
| `TURN` | 90 | `turn` | 当前回合数 |

### 2.2 英雄技能实体标签

| GameTag | 枚举值 | 说明 |
|---------|--------|------|
| `COST` | 30 | 英雄技能铸币花费 |
| `EXHAUSTED` | 72 | 英雄技能是否已使用 |
| `BACON_HERO_POWER_ACTIVATED` | 145 | 英雄技能是否已激活（备用） |
| `CONTROLLER` | 50 | 用于查找属于玩家的英雄技能实体 |
| `CARDTYPE` | 10 | 过滤 `HERO_POWER` 类型 |

### 2.3 酒馆实体标签

| GameTag | 枚举值 | 字段 | 说明 |
|---------|--------|------|------|
| `ATK` | 20 | `atk` | 攻击力 |
| `HEALTH` | 21 | `health` | 生命值 |
| `TECH_LEVEL` | 14 | `tier` | 酒馆等级 |
| `COST` | 30 | `cost` | 购买花费 |
| `CARDRACE` | 13 | `race` | 种族（数值 → 字符串映射） |
| `CARDTYPE` | 10 | `is_minion` / `is_spell` | 卡牌类型 |
| `TAUNT` | 50 | `taunt` | 嘲讽 |
| `DIVINE_SHIELD` | 51 | `divine_shield` | 圣盾 |
| `POISONOUS` | 52 | `poisonous` | 剧毒 |
| `REBORN` | 54 | `reborn` | 复生 |
| `FROZEN` | 71 | `frozen` | 冻结 |

### 2.4 手牌实体标签

除复用 ATK, HEALTH, TECH_LEVEL, COST, CARDRACE, CARDTYPE 外：

| GameTag | 枚举值 | 字段 | 说明 |
|---------|--------|------|------|
| `PREMIUM` | 69 | `golden` | 金色（三连） |
| `BATTLECRY` | 61 | `battlecry` | 战吼 |
| `NUM_TURNS_IN_PLAY` | 153 | `turns_in_hand` | 在手牌中的回合数 |
| `SPELLCRAFT` | 133 | `spellcraft` | 法术技艺生成的临时法术 |

### 2.5 战场实体标签

除复用 ATK, HEALTH, TECH_LEVEL, TAUNT, DIVINE_SHIELD, POISONOUS, REBORN, PREMIUM, CARDRACE 外：

| GameTag | 枚举值 | 字段 | 说明 |
|---------|--------|------|------|
| `DAMAGE` | 105 | `max_health` | 已承受伤害 → 用于推算最大生命值 |
| `VENOMOUS` | 53 | `venomous` | 剧毒（可叠加） |
| `WINDFURY` | 55 | `windfury` | 风怒 |
| `EXHAUSTED` | 72 | `exhausted` | 本回合已行动 |
| (无) | — | `cleave` | **硬编码 CardId 集合判断** |
| (无) | — | `divine_shield_intact` | 与 `divine_shield` 同值（见已知限制） |

### 2.6 饰品实体标签

| GameTag | 枚举值 | 字段 | 说明 |
|---------|--------|------|------|
| `COST` | 30 | `cost` | 饰品花费 |
| `TECH_LEVEL` | 14 | `tier` | 饰品等级 |
| `TRIGGER_VISUAL` | 106 | `has_start_of_combat` | **近似值** — 用于推断战斗开始时效果 |

### 2.7 对手实体标签

| GameTag | 枚举值 | 字段 | 说明 |
|---------|--------|------|------|
| `HEALTH` | 21 | `health` / `alive` | 血量 / 存活判定 |
| `ARMOR` | 24 | `armor` | 护甲 |
| `PLAYER_TECH_LEVEL` | 110 | `tavern_tier` | 酒馆等级 |
| (聚合) | — | `board_size` | 统计对手 PLAY zone 中 MINION 数量 |

### 2.8 实体查询基础设施标签（不输出到 JSON）

| GameTag | 用途 |
|---------|------|
| `ZONE` | 区分 PLAY / HAND / SECRET 区域 |
| `ZONE_POSITION` | 实体排序 |
| `CREATOR` | 区分 Bob 创建的酒馆实体 |
| `CARDTYPE` | 过滤 MINION / SPELL / BATTLEGROUND_SPELL / HERO_POWER |
| `CONTROLLER` | 关联实体与玩家 |
| `PLAYER_ID` | 查找玩家实体 |

---

## 3. PlayerState

```json
{
  "health": 35,
  "armor": 5,
  "gold": 7,
  "tavern_tier": 3,
  "upgrade_cost": 8,
  "hero_card_id": "TB_BaconShop_HERO_59",
  "hero_power_used": false,
  "hero_power_cost": 2,
  "hero_power_extra_uses": false,
  "free_refresh_remaining": 1,
  "next_spell_cost_reduction": 0,
  "blood_gem_atk_bonus": 0,
  "blood_gem_health_bonus": 0,
  "pending_triple_reward_tier": 0
}
```

| # | 字段 | 类型 | 数据源 | 处理逻辑 |
|---|------|------|--------|---------|
| 1 | `health` | int | Player: `HEALTH` | `>0 ? hp : 40` |
| 2 | `armor` | int | Player: `ARMOR` | `max(armor, 0)` |
| 3 | `gold` | int | Player: `RESOURCES + TEMP_RESOURCES - RESOURCES_USED` | 三标签计算，`max(0, gold)` |
| 4 | `tavern_tier` | int | Player: `PLAYER_TECH_LEVEL` | `max(tier, 1)` |
| 5 | `upgrade_cost` | int | 推导 | `5 + max(tavern_tier, 1)` |
| 6 | `hero_card_id` | string | Hero 实体: `CardId` | 通过 `HERO_ENTITY` 标签查找 |
| 7 | `hero_power_used` | bool | Hero Power 实体: `EXHAUSTED` 或 `BACON_HERO_POWER_ACTIVATED` | 任一 `>0` 即已用 |
| 8 | `hero_power_cost` | int | Hero 实体: `COST` | 默认 2 |
| 9 | `hero_power_extra_uses` | bool | Extra Hero Power 实体: `EXHAUSTED` | 实体存在且 `EXHAUSTED == 0` |
| 10 | `free_refresh_remaining` | int | Player: `BACON_FREE_REFRESH_COUNT` | `max(count, 0)` |
| 11 | `next_spell_cost_reduction` | int | **硬编码 0** | ⚠️ 未实现 |
| 12 | `blood_gem_atk_bonus` | int | **硬编码 0** | ⚠️ 未实现 |
| 13 | `blood_gem_health_bonus` | int | **硬编码 0** | ⚠️ 未实现 |
| 14 | `pending_triple_reward_tier` | int | **硬编码 0** | ⚠️ 未实现 |

---

## 4. TavernSlot

```json
{
  "card_id": "BGS_001",
  "atk": 2,
  "health": 3,
  "tier": 1,
  "cost": 3,
  "race": "BEAST",
  "is_minion": true,
  "is_spell": false,
  "taunt": false,
  "divine_shield": false,
  "poisonous": false,
  "reborn": false,
  "frozen": false
}
```

酒馆实体识别：PLAY zone 中有 `CREATOR` 标签 + `CARDTYPE ∈ {MINION, SPELL, BATTLEGROUND_SPELL}` + `TECH_LEVEL` 标签。按 `ZONE_POSITION` 排序，最多 7 个。

| # | 字段 | 类型 | 数据源 |
|---|------|------|--------|
| 1 | `card_id` | string | `Entity.CardId` |
| 2 | `atk` | int | `ATK` |
| 3 | `health` | int | `HEALTH` |
| 4 | `tier` | int | `TECH_LEVEL` |
| 5 | `cost` | int | `COST` |
| 6 | `race` | string | `CARDRACE` → RaceToString() |
| 7 | `is_minion` | bool | `CARDTYPE == MINION` |
| 8 | `is_spell` | bool | `CARDTYPE ∈ {SPELL, BATTLEGROUND_SPELL}` |
| 9 | `taunt` | bool | `TAUNT > 0` |
| 10 | `divine_shield` | bool | `DIVINE_SHIELD > 0` |
| 11 | `poisonous` | bool | `POISONOUS > 0` |
| 12 | `reborn` | bool | `REBORN > 0` |
| 13 | `frozen` | bool | `FROZEN > 0` |

---

## 5. HandSlot

```json
{
  "card_id": "BGS_030",
  "atk": 4,
  "health": 4,
  "tier": 2,
  "cost": 3,
  "race": "MECH",
  "is_minion": true,
  "is_spell": false,
  "golden": false,
  "battlecry": true,
  "turns_in_hand": 1,
  "spellcraft": false
}
```

手牌实体识别：ZONE=HAND + CONTROLLER=playerId。按 `ZONE_POSITION` 排序，最多 10 个。

| # | 字段 | 类型 | 数据源 |
|---|------|------|--------|
| 1 | `card_id` | string | `Entity.CardId` |
| 2 | `atk` | int | `ATK` |
| 3 | `health` | int | `HEALTH` |
| 4 | `tier` | int | `TECH_LEVEL` |
| 5 | `cost` | int | `COST` |
| 6 | `race` | string | `CARDRACE` → RaceToString() |
| 7 | `is_minion` | bool | `CARDTYPE == MINION` |
| 8 | `is_spell` | bool | `CARDTYPE ∈ {SPELL, BATTLEGROUND_SPELL}` |
| 9 | `golden` | bool | `PREMIUM > 0` |
| 10 | `battlecry` | bool | `BATTLECRY > 0` |
| 11 | `turns_in_hand` | int | `NUM_TURNS_IN_PLAY` |
| 12 | `spellcraft` | bool | `SPELLCRAFT > 0` |

---

## 6. BoardSlot

```json
{
  "atk": 6,
  "health": 5,
  "max_health": 5,
  "tier": 2,
  "taunt": true,
  "divine_shield": true,
  "divine_shield_intact": true,
  "poisonous": false,
  "venomous": false,
  "reborn": false,
  "windfury": false,
  "cleave": false,
  "golden": false,
  "race": "MURLOC",
  "exhausted": false
}
```

战场实体识别：CONTROLLER=playerId + IsInPlay + IsMinion，**排除**酒馆实体（按 entity ID 排除 shopIds 集合）。按 `ZONE_POSITION` 排序，最多 7 个。

| # | 字段 | 类型 | 数据源 |
|---|------|------|--------|
| 1 | `atk` | int | `ATK` |
| 2 | `health` | int | `HEALTH`（当前生命值） |
| 3 | `max_health` | int | `HEALTH + DAMAGE` |
| 4 | `tier` | int | `TECH_LEVEL` |
| 5 | `taunt` | bool | `TAUNT > 0` |
| 6 | `divine_shield` | bool | `DIVINE_SHIELD > 0` |
| 7 | `divine_shield_intact` | bool | `DIVINE_SHIELD > 0` ⚠️ 与 `divine_shield` 相同 |
| 8 | `poisonous` | bool | `POISONOUS > 0` |
| 9 | `venomous` | bool | `VENOMOUS > 0` |
| 10 | `reborn` | bool | `REBORN > 0` |
| 11 | `windfury` | bool | `WINDFURY > 0` |
| 12 | `cleave` | bool | 硬编码 CardId 集合：`BGS_022, BG21_046, BG24_306, BG25_022, BG26_158, BG27_029` |
| 13 | `golden` | bool | `PREMIUM > 0` |
| 14 | `race` | string | `CARDRACE` → RaceToString() |
| 15 | `exhausted` | bool | `EXHAUSTED > 0` |

---

## 7. TrinketSlot

```json
{
  "card_id": "BG_TRINKET_001",
  "cost": 3,
  "tier": 2,
  "has_start_of_combat": true,
  "has_end_of_turn": false,
  "has_start_of_turn": false
}
```

饰品实体识别：ZONE=SECRET + CONTROLLER=playerId。最多 2 个。

| # | 字段 | 类型 | 数据源 |
|---|------|------|--------|
| 1 | `card_id` | string | `Entity.CardId` |
| 2 | `cost` | int | `COST` |
| 3 | `tier` | int | `TECH_LEVEL` |
| 4 | `has_start_of_combat` | bool | `TRIGGER_VISUAL > 0` ⚠️ 近似值 |
| 5 | `has_end_of_turn` | bool | **硬编码 false** ⚠️ 未实现 |
| 6 | `has_start_of_turn` | bool | **硬编码 false** ⚠️ 未实现 |

---

## 8. OpponentSummary

```json
{
  "health": 38,
  "armor": 10,
  "tavern_tier": 3,
  "board_size": 5,
  "alive": true
}
```

固定 7 个元素，不足时用填充值：`health=40, armor=0, tavern_tier=1, board_size=0, alive=false`。

| # | 字段 | 类型 | 数据源 |
|---|------|------|--------|
| 1 | `health` | int | 对手 Player: `HEALTH` |
| 2 | `armor` | int | 对手 Player: `ARMOR` |
| 3 | `tavern_tier` | int | 对手 Player: `PLAYER_TECH_LEVEL` |
| 4 | `board_size` | int | 统计对手 CONTROLLED + ZONE=PLAY + CARDTYPE=MINION 实体数量 |
| 5 | `alive` | bool | `health > 0` |

---

## 9. 全局字段

| # | 字段 | 类型 | 数据源 | 说明 |
|---|------|------|--------|------|
| 1 | `type` | string | 硬编码 | 固定 `"game_state"` |
| 2 | `game_id` | string | 创建时生成 | `bg_YYYYMMDD_HHmmss_NNNN` |
| 3 | `turn` | int | Player: `TURN` | `max(turn, 1)` |
| 4 | `phase` | string | `game.IsBattlegroundsCombatPhase` | `"recruit"` 或 `"combat"` |
| 5 | `alive_count` | int | 推导 | `1 + count(opponents.alive)` |
| 6 | `damage_cap` | int? | 推导 | 有对手死亡 → `null`；全员存活 → `15` |
| 7 | `anomaly_card_id` | string | 全局实体扫描 | CardId 包含 `"ANOMALY"` 的第一个实体 |

### Placement（仅 game_end）

`GetPlacement()` 方法（不在 `game_state` 中使用）：
- 将所有玩家按存活状态 + HP 排序
- 返回当前玩家的排名（1-8）

---

## 10. 已知限制

### 10.1 未实现的 Stub 字段

| 字段 | 位置 | 当前值 | 需要的 GameTag / 方案 |
|------|------|--------|----------------------|
| `next_spell_cost_reduction` | PlayerState | `0` | `NEXT_SPELL_COST_REDUCTION` (138) |
| `blood_gem_atk_bonus` | PlayerState | `0` | `BLOOD_GEM_BONUS_ATK` (120) |
| `blood_gem_health_bonus` | PlayerState | `0` | `BLOOD_GEM_BONUS_HEALTH` (121) |
| `pending_triple_reward_tier` | PlayerState | `0` | 扫描 hand/board 中 `TRIPLE_REWARD_TIER` (111) 标签 |
| `has_end_of_turn` | TrinketSlot | `false` | `END_OF_TURN` (130) 或根据 CardId 查脚本定义 |
| `has_start_of_turn` | TrinketSlot | `false` | `START_OF_TURN` (131) 或根据 CardId 查脚本定义 |
| `divine_shield_intact` | BoardSlot | = `divine_shield` | `DIVINE_SHIELD` 标签在圣盾被消耗后会归零，因此 `DIVINE_SHIELD > 0` 本身就能区分。当前问题是如果随从天生有圣盾且未消耗，两者同值。要区分需要追踪战斗中的圣盾消耗事件，或在战斗中区分 `DIVINE_SHIELD` vs 实际状态。 |

### 10.2 近似值

| 字段 | 近似方式 | 准确性 |
|------|---------|--------|
| `cleave` | 硬编码 CardId 集合 | 新 cleave 随从需手动更新列表 |
| `has_start_of_combat` | `TRIGGER_VISUAL > 0` | 近似 — 非所有 SoC 效果都有 TRIGGER_VISUAL |
| `damage_cap` | 仅返回 `15` 或 `null` | 未处理 5/10 伤害上限的异变 |
| `upgrade_cost` | `5 + tavern_tier` | 未考虑特定英雄/异变对升级费用的修改 |

### 10.3 Race 映射差异

HDT `RaceToString()` 和训练环境 `_RACE_MAP` 的种族映射不完全一致：

| 方面 | HDT (C# RaceToString) | 训练环境 (Python _RACE_MAP) |
|------|----------------------|---------------------------|
| 覆盖范围 | ~13 个常规种族 | ~37 个（含内部引擎种族名） |
| 数值映射 | 直接使用 CARDRACE 数值 | 通过字符串名查字典 |
| 归一化 | 无（输出字符串） | `/ 12.0`（值可能 >1.0） |

> **影响**：训练环境 `_RACE_MAP` 中部分种族（如 `GOBLIN2=13`, `HALF_ORC=29` 等）的归一化值会超过 `1.0`（因为除以 `12.0`）。HDT 端通过字符串中转，StateMapper 再做字符串→数值映射，所以如果两边字符串一致，数值会一致。但 `_RACE_MAP` 的 `/12.0` 归一化对超出 12 的种族值会产生 >1.0 的结果，这可能不是设计本意。

### 10.4 对手棋盘信息有限

- 对手 `board_size` 仅统计随从数量，不包含随从的具体属性（攻击力/生命值/关键词）
- 这是 HDT 内存读取的固有限制：对手随从的详细信息不在本地内存中

---

## 11. 360 维观察空间对齐表

训练环境 `observation.py` 定义 360 维 flat 观察向量，`state_mapper.py` 将其映射到 HDT JSON 字段。

### 总览

| 组 | 形状 | 维数 | Flat 索引 | 覆盖 |
|----|------|------|-----------|------|
| Global | (20,) | 20 | 0–19 | 6/20 使用 |
| Player | (15,) | 15 | 20–34 | 11/15 实值, 4 stub |
| Tavern | (7, 12) | 84 | 35–118 | 12/12 完整 |
| Hand | (10, 12) | 120 | 119–238 | 12/12 完整 |
| Board | (7, 15) | 105 | 239–343 | 13/15 完整, 2 部分 |
| Trinkets | (2, 8) | 16 | 344–359 | 5/8 完整, 3 stub |

### 11.1 Global [0–19]

| Flat Idx | 组内 | 特征 | 归一化 | HDT 数据源 | 状态 |
|----------|------|------|--------|-----------|------|
| 0 | [0] | 回合数 | `min(turn/20, 1)` | `msg.turn` ← Player TURN (90) | ✅ |
| 1 | [1] | 招募阶段 | binary | `msg.phase == "recruit"` | ✅ |
| 2 | [2] | 存活人数 | `/8` | `msg.alive_count` | ✅ |
| 3 | [3] | 伤害上限 | `/15` | `msg.damage_cap` | ✅ |
| 4 | [4] | 异变 ID hash | `(hash(id)%100)/100` | `msg.anomaly_card_id` | ✅ |
| 5 | [5] | 玩家血量排名 | `/8` | 推导：对手中血量更高的数量 | ✅ |
| 6–19 | [6]–[19] | 填充 | 0 | — | — |

### 11.2 Player [20–34]

| Flat Idx | 组内 | 特征 | 归一化 | HDT 数据源 | 状态 |
|----------|------|------|--------|-----------|------|
| 20 | [0] | 血量 | `min(health/40, 1)` | `msg.player.health` ← HEALTH (21) | ✅ |
| 21 | [1] | 护甲 | `min(armor/20, 1)` | `msg.player.armor` ← ARMOR (24) | ✅ |
| 22 | [2] | 铸币 | `min(gold/10, 1)` | `msg.player.gold` ← RESOURCES+TEMP-RESOURCES_USED | ✅ |
| 23 | [3] | 酒馆等级 | `tier/7` | `msg.player.tavern_tier` ← PLAYER_TECH_LEVEL (110) | ✅ |
| 24 | [4] | 升级费用 | `min(cost/10, 1)` | `msg.player.upgrade_cost` | ✅ |
| 25 | [5] | 手牌数量 | `min(count/10, 1)` | 统计 `msg.hand` 中非 null 元素 | ✅ |
| 26 | [6] | 棋盘数量 | `min(count/7, 1)` | 统计 `msg.board` 中非 null 元素 | ✅ |
| 27 | [7] | 技能花费 | `min(cost/10, 1)` | `msg.player.hero_power_cost` ← Hero COST (30) | ✅ |
| 28 | [8] | 技能可用 | binary | `msg.player.hero_power_used` ← HP EXHAUSTED (72) | ✅ |
| 29 | [9] | 额外技能 | binary | `msg.player.hero_power_extra_uses` | ✅ |
| 30 | [10] | 三连奖励等级 | `tier/7` | `msg.player.pending_triple_reward_tier` | ❌ 硬编码 0 |
| 31 | [11] | 免费刷新 | `min(count/5, 1)` | `msg.player.free_refresh_remaining` ← BACON_FREE_REFRESH_COUNT | ✅ |
| 32 | [12] | 法术折扣 | `min(reduction/10, 1)` | `msg.player.next_spell_cost_reduction` | ❌ 硬编码 0 |
| 33 | [13] | 宝石攻击加成 | `min(atk/50, 1)` | `msg.player.blood_gem_atk_bonus` | ❌ 硬编码 0 |
| 34 | [14] | 宝石生命加成 | `min(hp/50, 1)` | `msg.player.blood_gem_health_bonus` | ❌ 硬编码 0 |

### 11.3 Tavern Slot i (i=0..6) [35 + i×12, 46 + i×12]

| Slot Offset | 特征 | 归一化 | HDT 数据源 | 状态 |
|-------------|------|--------|-----------|------|
| [0] | 攻击力 | `min(atk/100, 1)` | `TavernSlot.atk` ← ATK (20) | ✅ |
| [1] | 生命值 | `min(health/100, 1)` | `TavernSlot.health` ← HEALTH (21) | ✅ |
| [2] | 等级 | `tier/7` | `TavernSlot.tier` ← TECH_LEVEL (14) | ✅ |
| [3] | 购买花费 | `min(cost/10, 1)` | `TavernSlot.cost` ← COST (30) | ✅ |
| [4] | 种族 | `race_enum/12` | `TavernSlot.race` ← CARDRACE (13) → RaceToString() → _RACE_MAP | ✅ |
| [5] | 是随从 | binary | `TavernSlot.is_minion` ← CARDTYPE==MINION | ✅ |
| [6] | 是法术 | binary | `TavernSlot.is_spell` ← CARDTYPE∈{SPELL, BATTLEGROUND_SPELL} | ✅ |
| [7] | 嘲讽 | binary | `TavernSlot.taunt` ← TAUNT (50) | ✅ |
| [8] | 圣盾 | binary | `TavernSlot.divine_shield` ← DIVINE_SHIELD (51) | ✅ |
| [9] | 剧毒 | binary | `TavernSlot.poisonous` ← POISONOUS (52) | ✅ |
| [10] | 复生 | binary | `TavernSlot.reborn` ← REBORN (54) | ✅ |
| [11] | 冻结 | binary | `TavernSlot.frozen` ← FROZEN (71) | ✅ |

### 11.4 Hand Slot i (i=0..9) [119 + i×12, 130 + i×12]

| Slot Offset | 特征 | 归一化 | HDT 数据源 | 状态 |
|-------------|------|--------|-----------|------|
| [0] | 攻击力 | `min(atk/100, 1)` | `HandSlot.atk` ← ATK (20) | ✅ |
| [1] | 生命值 | `min(health/100, 1)` | `HandSlot.health` ← HEALTH (21) | ✅ |
| [2] | 等级 | `tier/7` | `HandSlot.tier` ← TECH_LEVEL (14) | ✅ |
| [3] | 花费 | `min(cost/10, 1)` | `HandSlot.cost` ← COST (30) | ✅ |
| [4] | 种族 | `race_enum/12` | `HandSlot.race` ← CARDRACE (13) → RaceToString() → _RACE_MAP | ✅ |
| [5] | 是随从 | binary | `HandSlot.is_minion` ← CARDTYPE==MINION | ✅ |
| [6] | 是法术 | binary | `HandSlot.is_spell` ← CARDTYPE∈{SPELL, BATTLEGROUND_SPELL} | ✅ |
| [7] | 金色 | binary | `HandSlot.golden` ← PREMIUM (69) | ✅ |
| [8] | 战吼 | binary | `HandSlot.battlecry` ← BATTLECRY (61) | ✅ |
| [9] | 持有回合数 | `min(turns/5, 1)` | `HandSlot.turns_in_hand` ← NUM_TURNS_IN_PLAY (153) | ✅ |
| [10] | CardId hash | `(hash(id)%1000)/1000` | `HandSlot.card_id` ← Entity.CardId | ✅ |
| [11] | Spellcraft | binary | `HandSlot.spellcraft` ← SPELLCRAFT (133) | ✅ |

### 11.5 Board Slot i (i=0..6) [239 + i×15, 253 + i×15]

| Slot Offset | 特征 | 归一化 | HDT 数据源 | 状态 |
|-------------|------|--------|-----------|------|
| [0] | 攻击力 | `min(atk/100, 1)` | `BoardSlot.atk` ← ATK (20) | ✅ |
| [1] | 当前生命值 | `min(health/100, 1)` | `BoardSlot.health` ← HEALTH (21) | ✅ |
| [2] | 最大生命值 | `min(max_hp/100, 1)` | `BoardSlot.max_health` ← HEALTH+DAMAGE | ✅ |
| [3] | 等级 | `tier/7` | `BoardSlot.tier` ← TECH_LEVEL (14) | ✅ |
| [4] | 种族 | `race_enum/12` | `BoardSlot.race` ← CARDRACE (13) → RaceToString() → _RACE_MAP | ✅ |
| [5] | 嘲讽 | binary | `BoardSlot.taunt` ← TAUNT (50) | ✅ |
| [6] | 圣盾 | binary | `BoardSlot.divine_shield` ← DIVINE_SHIELD (51) | ✅ |
| [7] | 剧毒 | binary | `BoardSlot.poisonous` ← POISONOUS (52) | ✅ |
| [8] | Venomous | binary | `BoardSlot.venomous` ← VENOMOUS (53) | ✅ |
| [9] | 复生 | binary | `BoardSlot.reborn` ← REBORN (54) | ✅ |
| [10] | 风怒 | binary | `BoardSlot.windfury` ← WINDFURY (55) | ✅ |
| [11] | 顺劈 | binary | `BoardSlot.cleave` ← 硬编码 CardId 集合 | ⚠️ 需手动维护 |
| [12] | 金色 | binary | `BoardSlot.golden` ← PREMIUM (69) | ✅ |
| [13] | 已行动 | binary | `BoardSlot.exhausted` ← EXHAUSTED (72) | ✅ |
| [14] | 圣盾完好 | binary | `BoardSlot.divine_shield_intact` ← DIVINE_SHIELD (51) | ⚠️ 与 [6] 相同值 |

### 11.6 Trinket Slot i (i=0..1) [344 + i×8, 351 + i×8]

| Slot Offset | 特征 | 归一化 | HDT 数据源 | 状态 |
|-------------|------|--------|-----------|------|
| [0] | 存在 | binary | 饰品实体存在 | ✅ |
| [1] | 花费 | `min(cost/10, 1)` | `TrinketSlot.cost` ← COST (30) | ✅ |
| [2] | 等级 | `tier/7` | `TrinketSlot.tier` ← TECH_LEVEL (14) | ✅ |
| [3] | 战斗开始时 | binary | `TrinketSlot.has_start_of_combat` ← TRIGGER_VISUAL (106) | ⚠️ 近似值 |
| [4] | 回合结束时 | binary | `TrinketSlot.has_end_of_turn` | ❌ 硬编码 false |
| [5] | 回合开始时 | binary | `TrinketSlot.has_start_of_turn` | ❌ 硬编码 false |
| [6] | CardId hash | `(hash(id)%1000)/1000` | `TrinketSlot.card_id` ← Entity.CardId | ✅ |
| [7] | 填充 | 0 | — | — |

---

## 12. 改进优先级

基于对齐分析，按影响程度排序的待修复项：

| 优先级 | 问题 | 影响维度 | 建议方案 |
|--------|------|---------|---------|
| **P0** | `next_spell_cost_reduction` 未实现 | Flat[32] | 读 Player `NEXT_SPELL_COST_REDUCTION` (138) |
| **P0** | `blood_gem_atk_bonus` 未实现 | Flat[33] | 读 Player `BLOOD_GEM_BONUS_ATK` (120) |
| **P0** | `blood_gem_health_bonus` 未实现 | Flat[34] | 读 Player `BLOOD_GEM_BONUS_HEALTH` (121) |
| **P1** | `pending_triple_reward_tier` 未实现 | Flat[30] | 扫描 hand/board 中 `TRIPLE_REWARD_TIER` (111) |
| **P1** | `divine_shield_intact` 语义不准确 | Flat[14]/slot | 战斗中检测圣盾是否被消耗（`DAMAGED` tag?） |
| **P1** | `has_end_of_turn` / `has_start_of_turn` 未实现 | Flat[4-5]/trinket | 按 CardId 查表，或读 `END_OF_TURN` (130)/`START_OF_TURN` (131) |
| **P2** | `cleave` 硬编码列表 | Flat[11]/board | 如有 `CLEAVE` (57) tag 可用则改用；否则定期同步列表 |
| **P2** | `damage_cap` 仅 15/null | Flat[3] | 处理异变中的 5/10 伤害上限 |
| **P2** | `has_start_of_combat` 用 TRIGGER_VISUAL 近似 | Flat[3]/trinket | 按 CardId 查表确认准确性 |
| **P3** | Race 归一化 `/12` 使部分种族 >1.0 | 多维度 | 将 `_RACE_MAP` 的除数值改为 `max(race_values)` 或 35 |
