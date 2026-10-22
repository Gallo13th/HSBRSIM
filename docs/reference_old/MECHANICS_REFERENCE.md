# HSRL 机制实现参考

> 本文档面向开发者，详细说明每个机制在 HSRL 引擎中的实现位置、核心逻辑和边界情况。
>
> **版本**: 0.10.0 | **更新日期**: 2026-05-25

---

## 目录

1. [Action 系统核心](#1-action-系统核心)
2. [伤害与攻击](#2-伤害与攻击)
3. [关键词机制映射](#3-关键词机制映射)
4. [事件广播](#4-事件广播)
5. [死亡处理流水线](#5-死亡处理流水线)
6. [Buff 系统](#6-buff-系统)
7. [战斗循环详解](#7-战斗循环详解)
8. [随从池系统](#8-随从池系统)
9. [延迟动作系统](#9-延迟动作系统)
10. [鲜血宝石系统](#10-鲜血宝石系统)
11. [战斗死亡追踪](#11-战斗死亡追踪)
12. [动态缩放追踪](#12-动态缩放追踪)
13. [回合触发效果](#13-回合触发效果)
14. [出售触发效果](#14-出售触发效果)
15. [变形与吞噬](#15-变形与吞噬)
16. [Spellcraft 系统](#16-spellcraft-系统)
17. [临时关键词](#17-临时关键词)
18. [最新赛季机制（Season 13）](#18-最新赛季机制season-13)
19. [酒馆 Buff 追踪](#19-酒馆-buff-追踪)
20. [战斗召唤系统](#20-战斗召唤系统)
21. [Improves 增强追踪系统](#21-improves-增强追踪系统)
22. [After Tavern Refresh 系统](#22-after-tavern-refresh-系统)
23. [After Battlecry Trigger 系统](#23-after-battlecry-trigger-系统)
24. [Tavern Spell Cast 系统](#24-tavern-spell-cast-系统)
25. [酒馆法术系统 (Spell Entity, Pool, Buy, Play)](#25-酒馆法术系统-spell-entity-pool-buy-play)

---

## 1. Action 系统核心

### 1.1 Action 基类

**文件**: `hsrl/core/actions.py`

```python
class Action:
    def trigger(self, source, game, target=None):
        self.do(source, game, target)
        for action in self._then:
            action.trigger(source, game, target)
```

所有状态变更必须通过 Action。`Game.resolve_queue()` 按 FIFO 顺序处理 Action 队列。

### 1.2 Action 执行时序

1. `action_start`（隐式）
2. `Action.do()` — 实际修改状态
3. `game.broadcast()` — 广播相关事件
4. `game._check_deaths()` — 检查并处理死亡
5. `action_end`（隐式）

---

## 2. 伤害与攻击

### 2.1 Attack Action

**文件**: `hsrl/core/actions.py` — `class Attack`

**流程**:
1. 检查 attacker/defender 是否已死亡
2. 检查 attacker 攻击力是否 > 0
3. 广播 `BEFORE_ATTACK`
4. **Rally（集结）触发**: 如果 attacker 有 `RALLY` 标签，设置 `game._last_attack_target` 并触发 `attacker.rally` 效果。Rally 在伤害结算**之前**执行。
5. **Attacker 对 Defender 造成伤害**: `Hit(defender, attacker.atk)`
6. **顺劈判定**: 如果 attacker 有 `CLEAVE`，对 defender 相邻位置各造成一次等值伤害
7. **Defender 反击**: 如果 defender 存活且攻击力 > 0，`Hit(attacker, defender.atk)`
8. 增加 attacker 的 `WINDFURY_ATTACKS` 计数器
9. 检查是否达到最大攻击次数（风怒=2，普通=1），设置 `EXHAUSTED`
10. 广播 `AFTER_ATTACK`

**边界情况**:
- **同时伤害**: HSRL 通过先排队双方 `Hit` Action 实现官方同时伤害语义。attacker 的 `Hit` 和 defender 的反击 `Hit` 都在 FIFO 队列中排队，`defender.dead` 检查发生在**排队之前**（而非 `Hit` 执行时），因此即使 defender 在 attacker 的 `Hit` 中死亡，其反击 `Hit` 仍然会执行。
- Cleave 伤害是独立的 `Hit`，会独立触发圣盾、剧毒等。
- 0 攻随从不会发起 Attack（在战斗循环中通过 `can_attack` 过滤）。

### 2.2 Hit Action

**文件**: `hsrl/core/actions.py` — `class Hit`

**流程**:
1. 检查 target 是否已死亡
2. 广播 `BEFORE_HIT`
3. **圣盾判定**: 如果 target 有 `DIVINE_SHIELD`:
   - 移除 `DIVINE_SHIELD`
   - 设置 `DIVINE_SHIELD_INTACT = False`
   - 广播 `DIVINE_SHIELD_LOST`
   - **直接返回，不造成任何伤害**
   - **剧毒不触发**（因为没有造成伤害）
4. **扣血**: `target.health -= amount`
5. 广播 `DAMAGE`
6. **剧毒判定**: 如果 source 有 `POISONOUS` 且 `actual_damage > 0`:
   - 设置 target `DEAD = True`, `health = 0`
   - 广播 `POISON_KILL`
7. **毒液判定**: 如果 source 有 `VENOMOUS` 且 `actual_damage > 0`:
   - 检查 source 是否存活（`not source.dead`）
   - 若存活，设置 target `DEAD = True`, `health = 0`
   - 广播 `VENOM_KILL`
8. 广播 `AFTER_HIT`

**关键边界**:
- `actual_damage > 0` 是剧毒/毒液触发的必要条件。
- 圣盾被击中时，无论伤害值多大，都完全免疫。

### 2.3 AttackImmediately Action

**文件**: `hsrl/core/actions.py` — `class AttackImmediately`

**用途**: 在非攻击方回合强制一个随从进行攻击（例如 Twilight Hatchling 亡语召唤的 Whelp 立即攻击）。

**流程**:
1. 寻找 attacker 的敌方玩家（`enemy = next(p for p in game.players if p is not attacker.controller and p.board)`）
2. 收集敌方存活随从，优先选择 Taunt 目标
3. 随机选择目标，queue `Attack(attacker, target)`

**使用场景**:
| 卡牌 | 效果 | 触发时机 |
|------|------|---------|
| BG34_630 Twilight Hatchling | DR 召唤 Whelp 并立即攻击 | 亡语 |
| BG34_403 Eternal Tycoon | Avenge 召唤 Eternal Knight 并立即攻击 | 复仇 |
| BG33_371 P-0UL-TR-0N | Avenge 获得圣盾并立即攻击 | 复仇 |

**重要**: `AttackImmediately` 本身不执行攻击，它将 `Attack` 加入队列，由正常的攻击结算流程处理。

---

## 3. 关键词机制映射

### 3.1 机制 ↔ 代码映射表

| 关键词 | 实现文件 | 核心类/方法 | 依赖事件 |
|--------|---------|------------|---------|
| **Taunt** | `core/game.py` | `_choose_attack_target()` | — |
| **Divine Shield** | `core/actions.py` | `Hit.do()` | `DIVINE_SHIELD_LOST` |
| **Poisonous** | `core/actions.py` | `Hit.do()` | `POISON_KILL` |
| **Venomous** | `core/actions.py` | `Hit.do()` | `VENOM_KILL` |
| **Reborn** | `core/actions.py` | `Reborn` class | `REBORN_TRIGGER` |
| **Windfury** | `core/minion.py` | `can_attack` property | — |
| **Cleave** | `core/actions.py` | `Attack.do()` | — |
| **Deathrattle** | `core/game.py` | `_check_deaths()` | `DEATHRATTLE_TRIGGER` |
| **Battlecry** | `core/minion.py` | `battlecry` property | 手动触发 |
| **TriggerBattlecry** | `core/actions.py` | `TriggerBattlecry` class | — |
| **Avenge(X)** | `core/actions.py` | `AvengeIncrement` | `AVENGE_TRIGGER` |
| **Start of Combat** | `core/game.py` | `_trigger_start_of_combat()` | `START_OF_COMBAT` |
| **AttackImmediately** | `core/actions.py` | `AttackImmediately` class | — |
| **Buff** | `core/actions.py` | `Buff` class | `BUFF` |
| **Blood Gem — Play** | `core/actions.py` | `PlayBloodGems` class | — |
| **Blood Gem — Get** | `core/actions.py` | `GetBloodGem` class | `BLOOD_GEM_RECEIVED` |
| **Blood Gem — Improve** | `core/actions.py` | `ImproveBloodGem` class | — |
| **Magnetic** | — | 关键词标签 | 手动触发（招募阶段） |
| **Golden** | `core/enums.py` | `GameTag.GOLDEN` | — |
| **Rally** | `core/actions.py` | `Attack.do()` (step 4) | `RALLY` |
| **ScheduleNextTurn** | `core/actions.py` | `ScheduleNextTurn` class | — |
| **GetRandomMinion** | `core/actions.py` | `GetRandomMinion` class | — |
| **End of Turn** | `core/game.py` | `_trigger_end_of_turn()` | — |
| **Start of Turn** | `core/game.py` | `_trigger_start_of_turn()` | — |
| **On Sell** | `core/game.py` | `sell_minion()` | — |
| **Spellcraft** | `core/game.py` | `_generate_spellcraft_spells()` / `_cleanup_spellcraft_spells()` | — |
| **Transform** | `core/actions.py` | `Transform` class | `TRANSFORM` |
| **FodderConsume** | `core/actions.py` | `FodderConsume` class | `FODDER_CONSUME` |
| **GiveKeyword** | `core/actions.py` | `GiveKeyword` class | — |
| **BuffTavern** | `core/actions.py` | `BuffTavern` class + `TavernBuff` | `TAVERN_BUFF_ADDED` |
| **SummonFromHandForCombat** | `core/actions.py` | `SummonFromHandForCombat` + `ReturnCombatSummons` | `COMBAT_SUMMON` |
| **BuffRandomTavernMinion** | `core/actions.py` | `BuffRandomTavernMinion` class | `TAVERN_REFRESH` |
| **CastTavernSpell** | `core/actions.py` | `CastTavernSpell` class | `TAVERN_SPELL_CAST` |
| **TavernSpellCastListener** | `core/events.py` | `EventListener(TAVERN_SPELL_CAST)` | `TAVERN_SPELL_CAST` |
| **After Tavern Refreshed** | `core/events.py` | `EventListener(TAVERN_REFRESH)` | `TAVERN_REFRESH` |
| **After Battlecry Trigger** | `core/events.py` | `EventListener(BATTLECRY_TRIGGER)` | `BATTLECRY_TRIGGER` |
| **Fodder** | — | 关键词标签 | 恶魔吞噬机制 |
| **Chromadrake** | — | 关键词标签 | 龙变形机制 |

### 3.2 新增机制的标准实现模板

如果添加一个全新机制（如 Fodder 或 Chromadrake），必须按以下模板实现：

**Step 1**: 在 `core/enums.py` 的 `GameTag` 中添加标签
```python
NEW_KEYWORD = 200
```

**Step 2**: 在 `core/actions.py` 中实现该机制触发逻辑（如果需要）
```python
class TriggerNewKeyword(Action):
    def do(self, source, game, target=None):
        # 机制逻辑
        game.broadcast("NEW_KEYWORD_TRIGGER", source)
```

**Step 3**: 在适当的时机调用（如 `Hit.do()`、`Attack.do()`、`_check_deaths()` 等）

**Step 4**: 在 `core/events.py` 中添加事件常量
```python
NEW_KEYWORD_TRIGGER = "NEW_KEYWORD_TRIGGER"
```

**Step 5**: 创建标准示例卡牌并测试

---

## 4. 事件广播

### 4.1 广播范围

`Game.broadcast(event_name, *args)` 会遍历 `game._event_listeners` 中所有注册的监听器。

**注册方式**:
- 静态注册：`entity.events = [EventListener(...)]`
- 动态注册：`game.register_listener(entity, listener)`

### 4.2 标准事件列表

| 事件名 | 触发时机 | 参数 |
|--------|---------|------|
| `ENTITY_CREATED` | 实体创建 | entity |
| `ZONE_CHANGE` | 区域变更 | entity, old_zone, new_zone |
| `BEFORE_ATTACK` | 攻击前 | attacker, defender |
| `AFTER_ATTACK` | 攻击后 | attacker, defender |
| `BEFORE_HIT` | 伤害前 | target, amount, source |
| `AFTER_HIT` | 伤害后 | target, actual_damage, source |
| `DAMAGE` | 造成伤害 | target, amount, source |
| `HEAL` | 治疗 | target, amount |
| `DIVINE_SHIELD_LOST` | 圣盾破裂 | target |
| `POISON_KILL` | 剧毒击杀 | target, source |
| `VENOM_KILL` | 毒液击杀 | target, source |
| `BEFORE_DESTROY` | 销毁前 | target |
| `DEATH` | 死亡 | target |
| `DEATHRATTLE_TRIGGER` | 亡语触发 | target |
| `REBORN_TRIGGER` | 复生触发 | old_minion, new_minion |
| `SUMMON` | 召唤 | minion, player |
| `BUFF` | 增益 | target, atk, health |
| `AVENGE_TRIGGER` | 复仇触发 | minion |
| `START_OF_COMBAT` | 战斗开始 | — |
| `END_OF_COMBAT` | 战斗结束 | — |
| `TAVERN_UPGRADED` | 酒馆升级 | player, new_tier |
| `PLAYER_DAMAGE_TAKEN` | 玩家受伤 | player, damage, attacker |
| `PLAYER_DEFEATED` | 玩家被淘汰 | player |
| `RECRUIT_BEGIN` | 招募阶段开始 | turn |
| `RECRUIT_END` | 招募阶段结束 | turn |
| `COMBAT_BEGIN` | 战斗阶段开始 | turn |
| `COMBAT_END` | 战斗阶段结束 | turn |
| `BLOOD_GEM_RECEIVED` | 鲜血宝石加入手牌 | player, spell |
| `BATTLECRY_TRIGGER` | 战吼效果被触发后（任何来源） | target, player |
| `BATTLE_CRY_TRIGGERED` | 战吼被 TriggerBattlecry 触发 | target |
| `TAVERN_REFRESH` | 酒馆刷新后 | player |
| `GOLD_GAINED` | 金币增加 | player, amount |
| `GOLD_SPENT` | 金币消耗 | player, amount |
| `FODDER_CONSUME` | 吞噬随从 | demon, consumed, atk_gain, health_gain |
| `TRANSFORM` | 变型 | old_minion, new_minion |
| `SPELLCRAFT_SPELL_GENERATED` | 生成法术 | spell, source |

---

## 5. 死亡处理流水线

### 5.1 死亡判定

**文件**: `hsrl/core/game.py` — `_check_deaths()`

死亡条件：`minion.dead == True` 或 `minion.health <= 0`

### 5.2 死亡处理顺序

对于每一个死亡随从（按场上从左到右顺序）:

1. 广播 `BEFORE_DESTROY`
2. 广播 `DEATH`
3. **触发亡语**: 如果 `minion.deathrattle` 存在:
   - 广播 `DEATHRATTLE_TRIGGER`
   - 将亡语 Action 加入队列
4. **触发复生**: 如果 `minion.reborn` 且未使用过:
   - 加入 `Reborn(minion)` Action
5. **复仇计数**: 对死亡随从的控制者的每个友方 Avenge 随从，计数器 +1
   - 如果达到阈值，触发 `avenge` 效果
6. 将随从移至 graveyard
7. 处理队列中的新 Action（可能产生新的死亡）
8. 重复直到没有新死亡

**重要**: 死亡处理是递归的。亡语召唤的新随从如果立即死亡，会在同一轮死亡处理中解决。

### 5.3 死亡处理中的 Action 队列

```
_check_deaths()
  → 发现死亡随从
  → 对每个死亡随从:
    - queue deathrattle actions
    - queue Reborn action
    - queue AvengeIncrement action
  → resolve_queue()  ← 这会触发更多 Hit/Attack/Buff，可能导致新死亡
  → _check_deaths() 递归调用（由 resolve_queue 内部自动触发）
```

---

## 6. Buff 系统

### 6.1 Buff 结构

**文件**: `hsrl/core/actions.py` — `BuffEnchantment`

```python
class BuffEnchantment:
    def __init__(self, atk=0, health=0):
        self.tags = {GameTag.ATK: atk, GameTag.HEALTH: health}
```

### 6.2 属性计算

**文件**: `hsrl/core/entity.py` — `Minion.atk` / `Minion.max_health`

```
最终攻击力 = base_atk + sum(buff.atk for buff in _buffs)
最终最大生命 = base_health + sum(buff.health for buff in _buffs)
```

Buff 是叠加的，没有持续时间限制（在酒馆战棋中，大部分 buff 是永久的）。

### 6.3 清除 Buff

- `clear_buffs()` 移除所有 buff。
- 沉默（Silence）尚未在标准示例中实现，但设计为调用 `clear_buffs()` + 清除事件监听器。

---

## 7. 战斗循环详解

### 7.1 战斗准备

**文件**: `hsrl/core/game.py` — `_run_combat()`

1. **创建快照**: 使用玩家当前 board 的副本进行战斗（在真实 8 人对战中，你面对的是对手 board 的副本）。
2. **重置战斗状态**: `reset_combat_state()` 清除 `EXHAUSTED`、`WINDFURY_ATTACKS`。
3. **触发 Start of Combat**: 按优先级依次触发：
   - 饰品（Trinkets）
   - 任务奖励（Quest Rewards）
   - 随从效果（Minion abilities）
   - 英雄技能（Hero Powers）

### 7.2 先攻判定

```python
if len(board_a) > len(board_b):
    attacker_side = board_a
elif len(board_b) > len(board_a):
    attacker_side = board_b
else:
    attacker_side = random.choice([board_a, board_b])
```

### 7.3 攻击循环

```python
for _ in range(1000):  # 防止无限循环
    attacker = _get_next_attacker(attacker_side)
    if attacker is None:
        break
    
    target = _choose_attack_target(defender_side)
    if target is None:
        break
    
    queue_action(Attack(attacker, target))
    resolve_queue()
    
    # 交换攻守方
    attacker_side, defender_side = defender_side, attacker_side
    
    # 检查战斗结束
    if not living_a or not living_b:
        break
```

### 7.4 无限循环保护

- 硬上限 1000 轮攻击。
- 正常战斗中，由于随从数量和攻击力有限，很少超过 50 轮。

### 7.5 战斗后状态恢复

```python
# END_COMBAT
for p in players:
    p.board = [m for m in p.board if not m.dead]
    p.graveyard.clear()
```

战斗阶段的所有临时状态（如战斗中获得的 buff）不会保留到招募阶段。

---

## 8. 随从池系统

### 8.1 实现概述

**文件**: `hsrl/core/minion_pool.py` — `class MinionPool`

MinionPool 管理所有玩家的共享随从池。已完全实现并集成到 Game 引擎中。

### 8.2 池结构

```python
class MinionPool:
    POOL_SIZES = {1:16, 2:15, 3:13, 4:11, 5:9, 6:7}

    def __init__(self, card_db):
        self._pools = {tier: [] for tier in range(1, 7)}
        for card_id in card_db.all_ids():
            data = card_db.get(card_id)
            if data and data.cardtype == CardType.MINION and data.tech_level in self.POOL_SIZES:
                # 排除示例卡牌和衍生物
                if card_id.startswith("EXAMPLE_") or card_id.startswith("TOKEN_") or card_id.endswith('t'):
                    continue
                count = self.POOL_SIZES[data.tech_level]
                self._pools[data.tech_level].extend([card_id] * count)
```

### 8.3 核心方法

| 方法 | 签名 | 说明 |
|------|------|------|
| `draw()` | `draw(tavern_tier, count=1, race_filter=None) -> List[str]` | 从 <= tavern_tier 的池中随机抽取 |
| `return_card()` | `return_card(card_id) -> bool` | 返还单张卡牌到对应等级池（不超过上限） |
| `remove_card()` | `remove_card(card_id) -> bool` | 从池中移除一张（不返还） |
| `return_all_player_cards()` | `return_all_player_cards(player)` | 玩家死亡时返还所有卡牌 |
| `available_count()` | `available_count(tavern_tier, race_filter=None) -> int` | 可用数量查询 |
| `get_available_cards()` | `get_available_cards(tavern_tier, race_filter=None) -> List[str]` | 去重后的可用卡牌列表 |
| `tier_count()` | `tier_count(tier) -> int` | 某等级当前剩余数量 |

### 8.4 Game 集成

**文件**: `hsrl/core/game.py`

- `Game.init_pool()` — 惰性初始化 MinionPool（首次使用触发）
- `Game.refresh_tavern(player)` — 刷新鲍勃的酒馆，从池中抽取 minions 并创建实体
- `Game.buy_minion(player, minion)` — 购买随从，从手牌移除并放置到战场
- `Game.sell_minion(player, minion)` — 出售随从，返回池中（如非 EXAMPLE_/TOKEN_）

### 8.5 金色随从与池的交互

- 3 个普通随从合成金色时，从池中移除的 3 个副本被金色随从"占用"。
- 出售金色随从时，返还 3 个副本到池中。
- 例外：Reno Jackson 的英雄技能将普通随从变金色**不消耗**池中的额外副本；出售时仅返还 1 份。

### 8.6 发现（Discover）与池

- Discover 效果（如三连奖励）也从共享池中抽取。
- 池中没有的随从不会出现在 Discover 选项中。
- Primalfin Lookout 不能发现自己。

---

## 9. 延迟动作系统

### 9.1 概述

**文件**: `hsrl/core/actions.py` — `class ScheduleNextTurn`, `hsrl/core/game.py` — `process_deferred_actions()`

延迟动作系统允许将 Action 推迟到下一个招募阶段执行。这用于实现 "next turn" 类效果。

### 9.2 ScheduleNextTurn Action

```python
class ScheduleNextTurn(Action):
    def __init__(self, player, action):
        self.player = player
        self.action = action  # 延迟执行的 Action

    def do(self, source, game, target=None):
        game._deferred_actions.append((self.player, self.action))
```

**流程**:
1. `ScheduleNextTurn.do()` 将 `(player, action)` 存入 `game._deferred_actions`
2. 在当前回合结束时或下一招募阶段开始时，调用 `game.process_deferred_actions()`
3. `process_deferred_actions()` 遍历所有延迟动作，逐个 queue 并 resolve

### 9.3 存储结构

```python
# Game.__init__
self._deferred_actions: List[Tuple[Player, Action]] = []
```

### 9.4 使用场景

| 卡牌 | 效果 | 调度内容 |
|------|------|---------|
| BG26_135 Southsea Busker | BC: Gain 1 Gold next turn | `ScheduleNextTurn(player, GainGold(player, 1))` |

### 9.5 重要边界

- 延迟动作在 resolve 时以 player 作为 source，而非原始卡牌
- 如果玩家在延迟动作执行前死亡，动作可能仍然执行（需在 future 版本中处理）
- 延迟动作队列在 `process_deferred_actions()` 后被清空

---

## 10. 鲜血宝石系统

### 10.1 概述

鲜血宝石（Blood Gem）是野猪人（Quilboar）种族的专属资源系统。引擎区分三种不同的操作语义。

### 10.2 三种操作

| 操作 | Action 类 | 语义 | 文件 |
|------|----------|------|------|
| **Play** | `PlayBloodGems(target, count)` | 立即对目标施加 Buff，不经过手牌 | `actions.py` |
| **Get** | `GetBloodGem(player, count, variant)` | 创建法术卡加入手牌，等待玩家选择目标 | `actions.py` |
| **Improve** | `ImproveBloodGem(player, atk_bonus, health_bonus)` | 永续增强所有血宝石的效果加成 | `actions.py` |

### 10.3 PlayBloodGems — 立即施放

```python
class PlayBloodGems(Action):
    def do(self, source, game, target=None):
        bonus_atk = self.player.get_tag(GameTag.BLOOD_GEM_BONUS_ATK, 0)
        bonus_health = self.player.get_tag(GameTag.BLOOD_GEM_BONUS_HEALTH, 0)
        total_atk = (1 + bonus_atk) * self.count
        total_health = (1 + bonus_health) * self.count
        game.queue_action(Buff(target, atk=total_atk, health=total_health))
```

**关键**: 从 player 读取 `BLOOD_GEM_BONUS_*` 标签计算实际加成值。

### 10.4 GetBloodGem — 加入手牌

```python
class GetBloodGem(Action):
    def __init__(self, player, count=1, variant="base"):
        # variant: "base" | "divine_shield" | "taunt"

    def do(self, source, game, target=None):
        card_id = {"base": "BLOOD_GEM", "divine_shield": "BLOOD_GEM_DS",
                    "taunt": "BLOOD_GEM_TAUNT"}[self.variant]
        for _ in range(self.count):
            spell = game.create_minion(card_id)
            spell.controller = self.player
            spell.zone = Zone.HAND
            self.player.hand.append(spell)
            game.broadcast("BLOOD_GEM_RECEIVED", self.player, spell)
```

### 10.5 血宝石变体

| 变体 | card_id | 效果 |
|------|--------|------|
| base | `BLOOD_GEM` | 给友方随从 +1/+1 |
| divine_shield | `BLOOD_GEM_DS` | 给友方野猪人 +1/+1 和圣盾 |
| taunt | `BLOOD_GEM_TAUNT` | 给友方野猪人 +1/+1 和嘲讽 |

### 10.6 ImproveBloodGem — 永续增强

```python
class ImproveBloodGem(Action):
    def do(self, source, game, target=None):
        current_atk = self.player.get_tag(GameTag.BLOOD_GEM_BONUS_ATK, 0)
        current_health = self.player.get_tag(GameTag.BLOOD_GEM_BONUS_HEALTH, 0)
        self.player.set_tag(GameTag.BLOOD_GEM_BONUS_ATK, current_atk + self.atk_bonus)
        self.player.set_tag(GameTag.BLOOD_GEM_BONUS_HEALTH, current_health + self.health_bonus)
```

**关键**: 存储在 Player 级别的标签上，影响所有后续 PlayBloodGems 调用。

---

## 11. 战斗死亡追踪

### 11.1 概述

**文件**: `hsrl/core/game.py` — `_combat_death_log`

战斗死亡日志记录在当前战斗中死亡的每个随从，用于 Kangor's Apprentice 等卡牌效果。

### 11.2 数据结构

```python
# Game.__init__
self._combat_death_log: List[Minion] = []

# 在 _run_combat() 开始时重置
self._combat_death_log = []

# 在 _check_deaths() 中记录死亡
for m in dead_minions:
    self._combat_death_log.append(m)
```

### 11.3 使用场景

| 卡牌 | 效果 | 读取方式 |
|------|------|---------|
| BGS_012 Kangor's Apprentice | DR: Summon plain copies of first 2 dead Mechs | 遍历 `_combat_death_log`，过滤 race=MECH |

### 11.4 死亡上下文 (in_combat)

**文件**: `hsrl/core/game.py` — `in_combat` 标志

```python
# Game.__init__
self.in_combat: bool = False

# 在 _run_combat() 中
self.in_combat = True
# ... 战斗结算 ...
self.in_combat = False
```

**用途**: 区分战斗死亡和招募阶段死亡。

| 卡牌 | 效果 | 上下文影响 |
|------|------|-----------|
| BG34_690 Plaguerunner | DR: +{0} ATK if died in combat, +{1} if outside | `in_combat=True` → +3 并递增 scale；`False` → +1 不变 |

---

## 12. 动态缩放追踪

### 12.1 MRRGLTON_COUNT 缩放

**文件**: `hsrl/core/enums.py` — `GameTag.MRRGLTON_COUNT = 87`

用于追踪玩家本局游戏中打出过的 Mrrglton 系列卡牌数量。

```python
# Mama Mrrglton / Papa Mrrglton — Battlecry
count = player.get_tag(GameTag.MRRGLTON_COUNT, 0) + 1
player.set_tag(GameTag.MRRGLTON_COUNT, count)
# 使用 count 作为 buff 倍率
```

### 12.2 PLAGUERUNNER_SCALE 缩放

**文件**: `hsrl/core/enums.py` — `GameTag.PLAGUERUNNER_SCALE = 122`

用于追踪 Plaguerunner 在战斗中的触发次数，每次 +1。

```python
# Plaguerunner — Deathrattle (in combat only)
x = controller.get_tag(GameTag.PLAGUERUNNER_SCALE, 3)
controller.set_tag(GameTag.PLAGUERUNNER_SCALE, x + 1)
```

### 12.3 TriggerBattlecry

**文件**: `hsrl/core/actions.py` — `class TriggerBattlecry`

允许重新触发一个随从的战吼效果（用于 Rylak Metalhead）。

```python
class TriggerBattlecry(Action):
    def __init__(self, target):
        self.target = target

    def do(self, source, game, target=None):
        if self.target.dead:
            return
        bc = self.target.battlecry
        if bc:
            if isinstance(bc, (list, tuple)):
                for action in bc:
                    game.queue_action(action, source=self.target)
            else:
                game.queue_action(bc, source=self.target)
```

| 卡牌 | 效果 |
|------|------|
| BG26_801 Rylak Metalhead | DR: Trigger Battlecry of an adjacent minion |

---

## 13. 回合触发效果

### 13.1 结束回合效果（End of Turn）

**文件**: `hsrl/core/game.py` — `_trigger_end_of_turn()`

在招募阶段结束时触发所有 friendly minion 的 `end_of_turn` 脚本方法。

**实现**:
```python
def _trigger_end_of_turn(self):
    for p in self.players:
        for m in p.board:
            if m.end_of_turn:
                action = m.end_of_turn(m, self)
                if action:
                    self.queue_action(action, source=m)
        self.resolve_queue()
```

**GameTag**: `END_OF_TURN = 130`

### 13.2 开始回合效果（Start of Turn）

**文件**: `hsrl/core/game.py` — `_trigger_start_of_turn()`

在招募阶段开始时触发所有 friendly minion 的 `start_of_turn` 脚本方法。

**GameTag**: `START_OF_TURN = 131`

**调用点**: `_start_recruit_phase()` → `_trigger_start_of_turn() → resolve_queue()`

---

## 14. 出售触发效果

### 14.1 On-Sell 效果

**文件**: `hsrl/core/game.py` — `sell_minion()`

当玩家出售一个带有 `ON_SELL` 标签的随从时触发。

**实现**:
```python
def sell_minion(self, player, minion):
    # ... 返还卡牌到池 ...
    if minion.on_sell:
        action = minion.on_sell(minion, self)
        if action:
            self.queue_action(action, source=minion)
            self.resolve_queue()
```

**GameTag**: `ON_SELL = 132`

---

## 15. 变形与吞噬

### 15.1 Transform Action

**文件**: `hsrl/core/actions.py` — `class Transform`

将目标随从变形为另一张卡牌，保留所有 buff、Golden 状态和场上位置。

**流程**:
1. 创建新 Minion (目标 card_id)
2. 将原随从的所有 `BuffEnchantment` 转移到新随从
3. 如果原随从是 Golden，新随从也设为 Golden
4. 在 board 中替换原随从（保持 zone_position）
5. 设置新随从 controller、zone=PLAY
6. 原随从移至 graveyard
7. 广播 `TRANSFORM`

**使用场景**:
| 卡牌 | 效果 | 变形为 |
|------|------|--------|
| EXAMPLE_TRANSFORM | Start of Combat: Transform to 8/8 Dragon | EXAMPLE_TRANSFORMED |

### 15.2 FodderConsume Action

**文件**: `hsrl/core/actions.py` — `class FodderConsume`

恶魔吞噬一个随从，获得其攻击力和最大生命值。

**流程**:
1. 读取被吞噬随从的 `atk` 和 `max_health`
2. 从手牌或 board 中移除被吞噬随从
3. 对吞噬者施加 `Buff(demon, atk=consumed_atk, health=consumed_max_health)`
4. 广播 `FODDER_CONSUME`

**关键**: 使用 `max_health` 而非 `health`，因为吞噬获得的是最大属性值。

---

## 16. Spellcraft 系统

### 16.1 概述

**文件**: `hsrl/core/game.py` — `_generate_spellcraft_spells()`, `_cleanup_spellcraft_spells()`

Spellcraft 在每个招募阶段开始时为带有 Spellcraft 关键词的随从生成临时法术卡。临时法术在招募阶段结束时自动清除（未使用的部分）。

### 16.2 生成流程

```python
def _generate_spellcraft_spells(self):
    for p in self.players:
        for m in p.board:
            if m.has_tag(GameTag.SPELLCRAFT):
                spell_id = m.data.scripts.spellcraft(m, self)
                spell = self.create_minion(spell_id)
                spell.set_tag(GameTag.SPELLCRAFT_SPELL, True)
                p.hand.append(spell)
```

**关键设计**: `spellcraft()` 脚本方法返回 `str` (card_id)，而非 `Action`。因为生成法术是创建卡牌实体的行为，而非状态变更效果。

### 16.3 清理流程

```python
def _cleanup_spellcraft_spells(self):
    for p in self.players:
        to_remove = [m for m in p.hand if m.has_tag(GameTag.SPELLCRAFT_SPELL)]
        for spell in to_remove:
            p.hand.remove(spell)
```

**GameTag**: `SPELLCRAFT_SPELL = 133` — 标记由 Spellcraft 生成的临时法术，用于回合结束清理。

---

## 17. 临时关键词

### 17.1 GiveKeyword Action

**文件**: `hsrl/core/actions.py` — `class GiveKeyword`

给予目标一个临时关键词（仅在本次招募阶段/战斗阶段有效）。

**与 GainKeyword 的区别**:
- `GainKeyword`: 永久性添加关键词标签
- `GiveKeyword`: 临时性授予关键词（通常持续到回合结束）

---

## 18. 最新赛季机制（Season 13）

> Season 13 "CATACLYSM CALLS!" (Patch 35.2, 2026-04-06) 引入了两个新关键词（Fodder、Chromadrake）和饰品系统回归。

### 18.1 Fodder（恶魔吞噬）— ✅ 已实现

**文件**: `hsrl/core/actions.py` — `class FodderConsume`

Fodder 关键词标签和 `FodderConsume` Action 已完全实现。详见 [Section 15.2](#152-fodderconsume-action)。

### 18.2 Chromadrake（龙变形）— 标签已定义

**GameTag**: `CHROMADRAKE = 68` 已在 enums.py 中定义。`Transform` Action 已实现（详见 [Section 15.1](#151-transform-action)），可用于 Chromadrake 卡牌效果。

### 18.3 饰品（Trinkets）系统

饰品是装备在英雄身上的特殊物品，提供被动或触发效果。当前赛季在第 6 回合（Lesser）和第 9 回合（Greater）提供购买机会。

**实现状态**: 已实现 302/314 active 饰品脚本。购买、发现、替换均通过 `buy_trinket()`/`DiscoverTrinket` 入口。`on_summon` 返回值自动排队处理。详见 `docs/CARD_REGISTRATION_GUIDE.md` §13.5。

**饰品触发时机**:

| 触发时机 | 实现位置 | 示例饰品 |
|---------|---------|---------|
| 战斗开始时 | `_trigger_start_of_combat()` | Automaton Portrait, Eternal Portrait |
| 回合结束时 | `_trigger_end_of_turn()` | Charging Staff, Goldgrubber |
| 购买随从时 | `buy_minion()` | Kodo Leather Pouch |
| 施放法术时 | 法术施放逻辑 | Lorewalker Scroll |
| Avenge 触发时 | `AvengeIncrement.do()` | Quilligraphy Set |

---

## 19. 酒馆 Buff 追踪

### 19.1 概述

酒馆 Buff 是"使酒馆中的随从获得 +X/+Y 本局对战"类效果的持久化追踪系统。与 GlobalAura（持续棋盘光环）不同，TavernBuff 仅在 `refresh_tavern()` 时一次性应用到新生成的酒馆随从上。

**关键区别**:

| 属性 | GlobalAura | TavernBuff |
|------|-----------|------------|
| 应用目标 | 棋盘上的友方随从（持续） | 酒馆中新生成的随从（一次性） |
| 触发时机 | 属性查询时动态计算 | `refresh_tavern()` 时应用 |
| 存储位置 | `player.auras` | `player.tavern_buffs` |
| 支持过滤 | 种族 | 种族 + 最大等级 |

### 19.2 数据结构

**文件**: `hsrl/core/actions.py`

```python
class TavernBuff:
    """持久化酒馆随从 buff，在每次 refresh_tavern() 时应用。"""
    
    def __init__(self, atk=0, health=0, race_filter=None, max_tier=None):
        self.atk = atk
        self.health = health
        self.race_filter = race_filter  # None = 全种族
        self.max_tier = max_tier        # None = 全等级
    
    def matches(self, minion) -> bool:
        # 种族过滤
        if self.race_filter is not None:
            if minion.race != self.race_filter and minion.race != Race.ALL:
                return False
        # 等级过滤
        if self.max_tier is not None:
            if minion.tech_level > self.max_tier:
                return False
        return True
```

### 19.3 BuffTavern Action

```python
class BuffTavern(Action):
    """添加一个持久化酒馆 buff。"""
    
    def __init__(self, player, atk=0, health=0, race_filter=None, max_tier=None)
    
    def do(self, source, game, target=None):
        tb = TavernBuff(atk, health, race_filter, max_tier)
        self.player.tavern_buffs.append(tb)
```

### 19.4 Game 集成

**文件**: `hsrl/core/game.py` — `refresh_tavern()`

在 `refresh_tavern()` 中，每个新生成的随从都会遍历 `player.tavern_buffs`，通过 `tb.matches(minion)` 检查后，使用 `add_buff(BuffEnchantment)` 应用 buff：

```python
for tb in player.tavern_buffs:
    if tb.matches(minion):
        minion.add_buff(BuffEnchantment(atk=tb.atk, health=tb.health))
        minion.health = minion.max_health  # 同步当前血量
```

### 19.5 标准示例

**卡牌ID**: `EXAMPLE_TAVERN_BUFF`
- 战吼：使酒馆中的随从获得 +2/+2 本局对战。

### 19.6 已实现卡牌

| 卡牌ID | 名称 | 效果 | 过滤条件 |
|--------|------|------|---------|
| `EXAMPLE_TAVERN_BUFF` | Tavern Buff Minion | +2/+2 | 全种族, 全等级 |
| `BG25_041` | Felemental | +1/+1 | 全种族, 全等级 |
| `BG31_815` | Dune Dweller | +1/+1 | 仅元素 |
| `BG35_152` | Void Pup Trainer | +2/+2 | 全种族, T1-T3 |

### 19.7 测试

| 测试类 | 文件 | 测试数 |
|--------|------|--------|
| `TestTavernBuff` | `test_core_mechanics.py` | 6 |
| `TestFelemental` | `test_token_cards.py` | 2 |
| `TestDuneDweller` | `test_token_cards.py` | 2 |
| `TestVoidPupTrainer` | `test_token_cards.py` | 2 |

---

## 20. 战斗召唤系统

### 20.1 概述

"仅本次战斗从手牌召唤"是 Battlegrounds 的核心机制之一。随从从手牌临时移动到棋盘参与当前战斗，战斗结束后返回手牌。战斗期间获得的 buff 在返回手牌后消失（标准战斗规则）。

### 20.2 GameTag

**`COMBAT_SUMMON = 134`** — 标记通过本系统临时召唤到棋盘的随从。

### 20.3 SummonFromHandForCombat Action

**文件**: `hsrl/core/actions.py`

```python
class SummonFromHandForCombat(Action):
    def __init__(self, controller, minion):
        # minion: 要召唤的具体随从（由脚本根据筛选条件选择）
    
    def do(self, source, game, target=None):
        # 1. 检查棋盘是否满（7个）
        # 2. 从手牌移除
        # 3. 放到棋盘最右侧（position=len(board)）
        # 4. 设置 COMBAT_SUMMON = True
        # 5. 重置战斗状态（reset_combat_state）
```

### 20.4 ReturnCombatSummons Action

```python
class ReturnCombatSummons(Action):
    def do(self, source, game, target=None):
        # 遍历所有存活玩家的棋盘
        # 对每个标记了 COMBAT_SUMMON 且未死亡的随从：
        #   从棋盘移除 → 设置 COMBAT_SUMMON = False → 移回手牌
```

### 20.5 Game 集成

在 `_end_combat_phase()` 中，**先返回战斗召唤随从**，再清理死亡随从：

```python
def _end_combat_phase(self):
    ReturnCombatSummons().do(None, self)
    for p in self.players:
        p.board = [m for m in p.board if not m.dead]
```

### 20.6 标准示例

**卡牌ID**: `EXAMPLE_COMBAT_SUMMON` — Start of Combat: Summon the highest-Attack minion from your hand for combat.

### 20.7 已实现卡牌

| 卡牌ID | 名称 | 触发器 | 筛选条件 |
|--------|------|--------|---------|
| `EXAMPLE_COMBAT_SUMMON` | Combat Summon Minion | SoC | 最高攻击 |
| `BG27_556` | Diremuck Forager | SoC | 最高攻击鱼人 |
| `BG34_140` | Expert Aviator | Rally | 最高攻击 |
| `BG31_835` | Deathly Striker | DR | 复仇获得的指定不死族 |

### 20.8 测试

| 测试类 | 文件 | 测试数 |
|--------|------|--------|
| `TestCombatSummon` | `test_core_mechanics.py` | 6 |
| `TestDiremuckForager` | `test_token_cards.py` | 1 |
| `TestExpertAviator` | `test_token_cards.py` | 1 |
| `TestDeathlyStriker` | `test_token_cards.py` | 2 |

---

## 21. Improves 增强追踪系统

**中文名**: "Improves after X" 增强追踪

**实现文件**: `core/actions.py` (IncrementImproveCounter), `core/game.py` (summon/buy_minion), `core/entity.py` (on_summon), `core/events.py` (ELEMENTAL_PLAYED)

**核心数据结构**:
- `GameTag.IMPROVE_COUNTER = 135` — 永久计数器，存储在卡牌的 tags 中
- `GameTag.GOLD_SPENT_THIS_TURN = 136` — 回合级追踪，存储在 Player 的 tags 中

**两种追踪模式**:

| 模式 | 触发方式 | 存储位置 | 生命周期 | 示例 |
|------|---------|---------|---------|------|
| 永久计数 | `on_summon` 注册 EventListener → 事件触发时 `IncrementImproveCounter` | 卡牌的 `IMPROVE_COUNTER` | 整场游戏 | Ultraviolet Ascendant |
| 回合快照 | Battlecry/SoC 时直接读取 Player tag | Player 的 `GOLD_SPENT_THIS_TURN` | 每回合重置 | Lovesick Balladist |

**游戏流程集成**:
1. `game.summon()`: 调用 `minion.on_summon` 注册事件监听器 + 广播 `ELEMENTAL_PLAYED`
2. `SpendGold.do()`: 广播 `GOLD_SPENT` 事件
3. `game._start_recruit_phase()`: 重置 `GOLD_SPENT_THIS_TURN` 为 0

**相关 Action**:
| Action | 位置 | 功能 |
|--------|------|------|
| `IncrementImproveCounter(target, amount=1)` | `actions.py:912` | 增加目标卡牌的 IMPROVE_COUNTER |
| `SpendGold` (已修改) | `actions.py:415` | 扣金币时广播 GOLD_SPENT 事件 |

**注意**: self-exclusion — 事件监听器使用条件 `lambda m, p: m != source` 防止随从自身触发计数器。

**已实现卡牌**:
| Card ID | 名称 | 模式 | 状态 |
|---------|------|------|------|
| BG31_810 | Ultraviolet Ascendant | 永久计数 (ELEMENTAL_PLAYED) | CORRECT |
| BG26_814 | Lovesick Balladist | 回合快照 (GOLD_SPENT_THIS_TURN) | CORRECT |
| BG32_822 | Fire-forged Evoker | 永久计数 (TAVERN_SPELL_CAST) | DEFERRED |
| BG35_702 | Roving Sailor | 回合快照 (TAVERN_SPELLS_CAST) | DEFERRED |

**测试覆盖**:
| 测试类 | 文件 | 测试数 |
|--------|------|--------|
| `TestImprove` | `test_core_mechanics.py` | 8 |
| `TestUltravioletAscendant` | `test_token_cards.py` | 4 |
| `TestLovesickBalladist` | `test_token_cards.py` | 3 |

---

## 22. After Tavern Refresh 系统

### 22.1 概述

"After the Tavern is Refreshed" 是一种持久化事件监听机制。带有此效果的卡牌在打出时注册一个 `TAVERN_REFRESH` 事件监听器，每次酒馆刷新时自动触发效果。

**关键语义**: "give a random minion **in it**" 指的是酒馆中的随从（`player.tavern`），而非友方棋盘。

### 22.2 实现

**事件**: `TAVERN_REFRESH` — 在 `game.refresh_tavern()` 末尾广播，参数为 `player`。

**Action**: `BuffRandomTavernMinion(player, atk, health)` — 从 `player.tavern` 中随机选择一个存活随从，对其施加 Buff。

**脚本模式**: `battlecry`/`deathrattle` 方法注册 EventListener 作为副作用，返回 `None`（不加入 Action 队列）。

```python
class MyAfterRefreshScript:
    @staticmethod
    def battlecry(source, game):
        listener = EventListener(
            event_name="TAVERN_REFRESH",
            action=BuffRandomTavernMinion(source.controller, atk=2, health=2),
        )
        game.register_listener(source, listener)
        return None  # 副作用已注册，无 Action 需要入队
```

### 22.3 已实现卡牌

| 卡牌ID | 名称 | 触发器 | 效果 |
|--------|------|--------|------|
| `EXAMPLE_AFTER_REFRESH` | After Refresh Test Minion | Battlecry | Refresh 后给随机酒馆随从 +2/+2 |
| `BG34_865` | En Djinn Blazer | Battlecry | Refresh 后给随机酒馆随从 +3/+3 |
| `BG34_856` | Waveling | Deathrattle | Refresh 后给随机酒馆随从 +3/+1 |

### 22.4 测试

| 测试类 | 文件 | 测试数 |
|--------|------|--------|
| `TestAfterRefresh` | `test_core_mechanics.py` | 4 |
| `TestEnDjinnBlazer` | `test_token_cards.py` | 2 |
| `TestWaveling` | `test_token_cards.py` | 2 |

---

## 23. After Battlecry Trigger 系统

### 23.1 概述

"After you trigger a Battlecry" 是一种持久化事件监听机制。每次任何友方战吼被触发时（无论是打出时自然触发还是通过 TriggerBattlecry 重新触发），注册的监听器自动执行效果。

### 23.2 实现

**事件**: `BATTLECRY_TRIGGER` — 在 `TriggerBattlecry.do()` 末尾广播，参数为 `(target, target.controller)`。

**条件过滤**: 使用 `EventListener` 的 `condition` 参数限制为同控制器：
```python
condition=lambda t, p: p == source.controller
```

**脚本模式**: `on_summon` 方法（通过 `entity.py` 中的 `on_summon` 属性触发）注册 EventListener，返回 `None`。

```python
class MyBattlecryTriggerScript:
    @staticmethod
    def on_summon(source, game):
        listener = EventListener(
            event_name="BATTLECRY_TRIGGER",
            action=Buff(source, atk=1, health=1),
            condition=lambda t, p: p == source.controller,
        )
        game.register_listener(source, listener)
        return None
```

**注意**: 当自动化的"从手牌打出"流程最终实现时，自然战吼触发也需要广播 `BATTLECRY_TRIGGER`。当前 `BATTLECRY_TRIGGER` 仅在 `TriggerBattlecry.do()` 中广播（覆盖了重触发路径）。

### 23.3 已实现卡牌

| 卡牌ID | 名称 | 触发器 | 效果 |
|--------|------|--------|------|
| `EXAMPLE_BATTLECRY_TRIGGER` | Battlecry Trigger Test Minion | on_summon | 战吼触发后自身 +1/+1 |
| `BG25_040` | Blazing Skyfin | on_summon | 战吼触发后自身 +1/+1 |
| `BGS_041` | Kalecgos | on_summon | 战吼触发后所有友方龙 +1/+1 |

Kalecgos 使用内嵌 Action 子类 `_BuffAllFriendlyDragons` 实现多目标 buff。

### 23.4 测试

| 测试类 | 文件 | 测试数 |
|--------|------|--------|
| `TestBattlecryTrigger` | `test_core_mechanics.py` | 4 |
| `TestBlazingSkyfin` | `test_token_cards.py` | 2 |
| `TestKalecgos` | `test_token_cards.py` | 2 |

---

## 附录：已知的边缘情况和实现决策

| 边缘情况 | 决策 |
|---------|------|
| 圣盾 + 0 攻剧毒 | 圣盾抵消 0 伤，剧毒不触发 |
| 复生 + 亡语顺序 | 先亡语，后复生（与官方一致） |
| 风怒第一次攻击死亡 | 第二次攻击不会发生（`can_attack` 检查死亡状态） |
| 顺劈打中已死随从 | `Hit` 内部检查 `dead`，跳过 |
| 满 board 召唤 | 召唤失败，随从不进场（标准 BG 规则） |
| 死亡处理中再次死亡 | 递归处理，直到无新死亡 |
| Reno 金色化 | 不消耗池副本，出售仅返还 1 份 |
| 手牌满时生成卡牌 | 卡牌"等待"，不销毁（Patch 35.2 统一规则） |

---

## 24. Tavern Spell Cast 系统

### 24.1 概述

"After you cast a Tavern spell" 是一种事件驱动机制。引擎提供 `CastTavernSpell` Action 广播 `TAVERN_SPELL_CAST` 事件并递增回合计数器，卡牌通过注册 EventListener 响应此事件。

**当前状态**: 完整实现 — 包括 Spell 实体、SpellPool、`buy_spell()`/`play_spell()` 和 NEXT_SPELL_COST_REDUCTION 折扣系统。

### 24.2 实现

**Action**: `CastTavernSpell(player)` — 广播 `TAVERN_SPELL_CAST(source, player)` 并递增 `TAVERN_SPELLS_CAST_THIS_TURN`。

**GameTag**: `TAVERN_SPELLS_CAST_THIS_TURN = 137` — 本回合已施放酒馆法术数量，存储在 Player 上。

**回合重置**: `_start_recruit_phase()` 中 `TAVERN_SPELLS_CAST_THIS_TURN` 重置为 0。

### 24.3 两种使用模式

| 模式 | 触发方式 | 存储位置 | 生命周期 | 示例 |
|------|---------|---------|---------|------|
| 永久计数 | `on_summon` 注册 EventListener → 事件触发时 `IncrementImproveCounter` | 卡牌的 `IMPROVE_COUNTER` | 整场游戏 | Fire-forged Evoker |
| 回合快照 | Battlecry 时直接读取 Player tag | Player 的 `TAVERN_SPELLS_CAST_THIS_TURN` | 每回合重置 | Roving Sailor |

### 24.4 已实现卡牌

| 卡牌ID | 名称 | 模式 | 状态 |
|--------|------|------|------|
| `EXAMPLE_TAVERN_SPELL_CAST` | Tavern Spell Cast Test Minion | 永久计数 (TAVERN_SPELL_CAST → self +1/+1) | ✅ |
| `BG32_822` | Fire-forged Evoker | 永久计数 (TAVERN_SPELL_CAST → IncrementImproveCounter) | ✅ |
| `BG35_702` | Roving Sailor | 回合快照 (TAVERN_SPELLS_CAST_THIS_TURN) | ✅ |
| `BG31_330` | Ominous Seer | 法术折扣 (NEXT_SPELL_COST_REDUCTION) | ✅ |

### 24.5 测试

| 测试类 | 文件 | 测试数 |
|--------|------|--------|
| `TestTavernSpellCast` | `test_core_mechanics.py` | 4 |
| `TestFireForgedEvoker` | `test_token_cards.py` | 2 |
| `TestRovingSailor` | `test_token_cards.py` | 2 |
| `TestOminousSeer` | `test_token_cards.py` | 3 |
| `TestTavernSpellSystem` | `test_core_mechanics.py` | 13 |

---

## 25. 酒馆法术系统 (Spell Entity, Pool, Buy, Play)

### 25.1 概述

酒馆法术是 Season 6 引入的核心机制。完整系统包括：Spell 实体类、SpellPool 共享池、购买流程（含折扣）、打出流程（含事件广播）。

### 25.2 Spell 实体类

**文件**: `hsrl/core/spell.py` — `class Spell(BaseEntity)`

Spell 继承自 `BaseEntity`（而非 `Minion`），没有 ATK、Health、race 等战斗属性。核心标签：
- `COST`: 金币费用 (1-5)
- `TECH_LEVEL`: 酒馆等级 (1-7)
- `CARDTYPE`: `SPELL`

### 25.3 SpellPool 法术池

**文件**: `hsrl/core/spell_pool.py` — `class SpellPool`

与 MinionPool 的关键区别：每个法术仅有 **1 个副本**（法术不重复出现）。

| 属性 | MinionPool | SpellPool |
|------|-----------|-----------|
| 副本数 | 7-16 份/种 | 1 份/种 |
| `draw()` | 按权重随机 | 纯随机 |
| `return_card()` | 按 copies 返还 | 返还 1 份 |

**方法**:
- `draw(tavern_tier, count=1)`: 从 ≤ tier 的法术中随机抽取
- `return_card(card_id)`: 施放后返还池
- `is_pool_spell(card_id)`: 检查是否为池法术
- `available_count(tavern_tier)`: 剩余可用法术数

### 25.4 购买流程

**文件**: `hsrl/core/game.py` — `Game.buy_spell(player, spell)`

1. 验证法术在酒馆中
2. 获取 `COST` 并应用 `NEXT_SPELL_COST_REDUCTION` 折扣
3. 检查金币是否足够
4. `SpendGold(player, actual_cost)` 扣除金币
5. 递增 `GOLD_SPENT_THIS_TURN`
6. 消费折扣（重置 `NEXT_SPELL_COST_REDUCTION` 为 0）
7. 法术从酒馆移入手牌

### 25.5 打出流程

**文件**: `hsrl/core/game.py` — `Game.play_spell(player, spell)`

1. 验证法术在手牌中
2. `CastTavernSpell(player)` — 广播 `TAVERN_SPELL_CAST` 事件 + 递增回合计数器
3. 法术从手牌移出 (`Zone.REMOVED`)
4. 法术返还 `SpellPool`（如果是池法术）

### 25.6 折扣系统

**GameTag**: `NEXT_SPELL_COST_REDUCTION = 138` — 存储在 Player 上

**设置**: Ominous Seer (BG31_330) 战吼: `controller.NEXT_SPELL_COST_REDUCTION += 1`

**应用**: `buy_spell()` 中 `actual_cost = max(0, cost - discount)`

**重置**: 购买法术时，折扣使用后立即归零。多次战吼可叠加折扣。

### 25.7 卡牌注册

**文件**: `hsrl/cards/spells/__init__.py`

从 `data/bg_pool_spells.json` 自动注册 71 张池法术。每张法术注册为 `CardType.SPELL`，带有 `COST` 和 `TECH_LEVEL` 标签。

### 25.8 酒馆展示

**文件**: `hsrl/core/game.py` — `Game.refresh_tavern()`

每次刷新酒馆时，在随从之外额外提供 **1 张酒馆法术**（固定数量，不随等级变化）。法术的 `TECH_LEVEL` ≤ 玩家当前酒馆等级。

### 25.9 已实现卡牌

| 卡牌ID | 名称 | 机制 | 状态 |
|--------|------|------|------|
| `EXAMPLE_TAVERN_SPELL` | Example Tavern Spell | 标准示例法术 (cost=2, tier=1) | ✅ |
| 71 张池法术 | bg_pool_spells.json | 自动注册 | ✅ |
| `BG31_330` | Ominous Seer | NEXT_SPELL_COST_REDUCTION | ✅ |
| `BG32_822` | Fire-forged Evoker | TAVERN_SPELL_CAST → IncrementImproveCounter | ✅ |
| `BG35_702` | Roving Sailor | TAVERN_SPELLS_CAST_THIS_TURN snapshot | ✅ |

### 25.10 测试

| 测试类 | 文件 | 测试数 |
|--------|------|--------|
| `TestTavernSpellSystem` | `test_core_mechanics.py` | 13 |
| `TestOminousSeer` | `test_token_cards.py` | 3 |

---

## 26. 三连 / Golden 系统 (Triple System)

### 26.1 概述

三连是酒馆战棋核心机制：3张相同的非金色随从自动合成为1张金色随从。金色随从打出时获得发现奖励。

### 26.2 play_minion（随从打出）

**文件**: `hsrl/core/game.py` — `Game.play_minion(player, minion, position)`

随从从手牌移动到战场：
1. 验证在手牌中 + 战场未满 (max 7)
2. 从手牌移除 → summon 到战场
3. 触发战吼 → 广播 `BATTLECRY_TRIGGER`
4. 如果是 golden → 触发三连奖励 Discover (`_grant_triple_reward`)
5. 检查是否形成三连 (`_check_for_triple`)

**Action 包装**: `hsrl/core/actions.py` — `PlayMinion(Action)`

### 26.3 三连检测

**文件**: `hsrl/core/game.py` — `Game._check_for_triple(player, entity)`

触发时机：minion 进入手牌时（buy/Discover/AddToHand/GetRandomMinion）或打出到战场后。

```
检测逻辑:
  - 扫描 player.hand + player.board
  - 查找相同 CARD_ID 的非 golden 副本
  - 排除自身 (uuid)
  - 收集到 ≥2 个额外副本 → 触发 _combine_triple
```

### 26.4 三连组合

**文件**: `hsrl/core/game.py` — `Game._combine_triple(player, copies)`

```
1. 将3个副本从各自zone移除 → Zone.SETASIDE
2. 创建全新 golden minion:
   - GOLDEN = True
   - BASE_ATK *= 2, BASE_HEALTH *= 2
   - HEALTH = max_health
3. 合并3个源副本的全部 buff → 叠加到 golden 上
4. 设置 TRIPLE_REWARD_TIER = min(tier+1, 6)
5. golden → player.hand
6. 广播 TRIPLE_COMBINED 事件
```

### 26.5 三连奖励

**文件**: `hsrl/core/game.py` — `Game._grant_triple_reward(player, golden)`

Golden 随从打出时：
- 读取 `TRIPLE_REWARD_TIER`
- `DiscoverMinion(player, max_tier=reward_tier)`
- 清除 `TRIPLE_REWARD_TIER`
- 广播 `TRIPLE_REWARD_DISCOVERED`

### 26.6 事件常量

| 事件 | 常量 | 触发时机 |
|------|------|---------|
| 三连组合完成 | `TRIPLE_COMBINED` | 3张合成golden后 |
| 三连奖励发现 | `TRIPLE_REWARD_DISCOVERED` | golden打出后给Discover |

### 26.7 边界情况

- Board满 (7随从): `play_minion` 不做任何操作
- 不在手牌: `play_minion` 不做任何操作
- Golden 副本不参与三连: `_check_for_triple` 跳过 `is_golden` 副本
- 三连奖励 tier 封顶: `min(tier+1, 6)`
- 三连 buff 合并: 遍历3个源的 `_buffs`，全部 `add_buff` 到 golden
- 非 golden 打出不触发奖励

### 26.8 已实现卡牌

| 卡牌ID | 名称 | 机制 | 状态 |
|--------|------|------|------|
| `EXAMPLE_TRIPLE` | Triple Test Minion | 三连测试 (Tier 1 Beast 2/3) | ✅ |
| `EXAMPLE_TIER2` | Tier 2 Test Minion | Discover测试 (Tier 2 Mech 3/3) | ✅ |
| `BG25_034` | Captain Sanders | Golden变换 (BC: 友方T6-随从→Golden) | ✅ |
| `BG24_009` | Picky Eater | 吞噬酒馆随从 (BC: FodderConsume) | ✅ |
| `BG28_303` | Disguised Graverobber | 摧毁Undead得plain copy (BC: Destroy+AddToHand) | ✅ |

### 26.9 测试

| 测试类 | 文件 | 测试数 |
|--------|------|--------|
| `TestPlayMinion` | `test_core_mechanics.py` | 4 |
| `TestTripleSystem` | `test_core_mechanics.py` | 8 |
| `TestTripleReward` | `test_core_mechanics.py` | 3 |
| `TestCaptainSanders` | `test_core_mechanics.py` | 3 |
| `TestPickyEater` | `test_core_mechanics.py` | 2 |
| `TestDisguisedGraverobber` | `test_core_mechanics.py` | 2 |

---

## 27. 光环翻倍 (Aura Doubling)

### 27.1 概述

某些随从（Brann Bronzebeard, Drakkari Enchanter）具有光环效果，使特定类型的触发效果执行两次。采用 player-tag 方案：随从打出时在 Player 上设置持久标记，引擎方法在触发时查询。

### 27.2 战吼翻倍 — Brann Bronzebeard

**文件**: `hsrl/core/game.py:play_minion()` L319-328, `hsrl/core/actions.py:TriggerBattlecry.do()` L660-670

**引擎检查点**:
1. `play_minion()` — 打出随从时，检查 `player.get_tag(GameTag.BATTLECRY_DOUBLED)`
2. `TriggerBattlecry.do()` — "触发一个友方随从的战吼"效果时，同样检查

翻倍逻辑：将战吼返回的 Action(s) queue 两次，BATTLECRY_TRIGGER 事件仅广播一次。

**卡牌脚本**: `BrannScript.on_summon` → `source.controller.set_tag(GameTag.BATTLECRY_DOUBLED, True)`

### 27.3 回合结束翻倍 — Drakkari Enchanter

**文件**: `hsrl/core/game.py:_trigger_end_of_turn()` L653-667

**引擎检查点**: 遍历每个玩家时，检查 `p.get_tag(GameTag.END_OF_TURN_DOUBLED)`

**卡牌脚本**: `DrakkariScript.on_summon` → `source.controller.set_tag(GameTag.END_OF_TURN_DOUBLED, True)`

### 27.4 英雄受伤事件标准化 — Floating Watcher

**文件**: `hsrl/core/actions.py:DealDamageToHero.do()` L645-648, `hsrl/core/events.py` L110

`DealDamageToHero.do()` 现在广播 `PLAYER_DAMAGE_TAKEN` 常量（而非硬编码 `"HERO_DAMAGE"`），统一英雄伤害事件。

**卡牌脚本**: `FloatingWatcherScript.on_summon` → 注册 `PLAYER_DAMAGE_TAKEN` 事件监听器，condition 检查 `game.step == Step.RECRUIT`（战斗伤害不计为"on your turn"）。

### 27.5 边界情况

- **Brann + 列表型战吼**: 整个 Action 列表执行两次
- **Brann + TriggerBattlecry**: "触发友方战吼"效果也受翻倍影响
- **Brann/Drakkari 移除后**: player-tag 方案下效果永久存在（简化实现，对 RL 模拟足够）
- **Floating Watcher 战斗伤害不触发**: condition 检查 step 为 RECRUIT
- **敌方受伤不触发**: condition 检查 damaged player == source.controller

### 27.6 已实现卡牌

| 卡牌ID | 名称 | 机制 | 状态 |
|--------|------|------|------|
| `BG_LOE_077` | Brann Bronzebeard | 战吼翻倍 (on_summon) | ✅ |
| `BG26_ICC_901` | Drakkari Enchanter | 回合结束翻倍 (on_summon) | ✅ |
| `BG_GVG_100` | Floating Watcher | 英雄受伤+2/+2 (event listener) | ✅ |

### 27.7 测试

| 测试类 | 文件 | 测试数 |
|--------|------|--------|
| `TestBrann` | `test_core_mechanics.py` | 3 |
| `TestDrakkari` | `test_core_mechanics.py` | 2 |
| `TestFloatingWatcher` | `test_core_mechanics.py` | 3 |

---

## 28. 临时 Buff 系统 (Temporary Buff)

### 28.1 概述

某些 buff（如非 Golden Ship Master Eudora 的 +2/+2）应仅在当前战斗中有效，战斗结束后清除。引擎支持 `Buff(temporary=True)` 标记，在 `_end_combat_phase()` 中自动清理。

### 28.2 Buff 系统扩展

**文件**: `hsrl/core/actions.py:Buff.__init__()` L220, `BuffEnchantment.__init__()` L841

- `Buff.__init__(target, atk=0, health=0, temporary=False)` — 新增 `temporary` 参数
- `BuffEnchantment.__init__(atk=0, health=0, temporary=False)` — 新增 `self.temporary` 属性

### 28.3 战斗结束清理

**文件**: `hsrl/core/game.py:_end_combat_phase()` L781-793

在清理死亡随从前，遍历所有存活随从，过滤掉 `temporary=True` 的 buff：
```python
for p in self.players:
    for m in p.board:
        if not m.dead:
            m._buffs = [b for b in m._buffs
                        if not getattr(b, 'temporary', False)]
```

### 28.4 已实现卡牌

| 卡牌ID | 名称 | 机制 | 状态 |
|--------|------|------|------|
| `BG33_828` | Ship Master Eudora | 非golden给临时buff, golden给永久buff | ✅ |

### 28.5 边界情况

- **非临时 buff 不受影响**: `temporary=False` (默认) 的 buff 在战斗后保留
- **多场战斗**: 每场战斗后临时 buff 都被清除
- **死亡随从**: 临时 buff 不影响死亡处理（死亡随从在 buff 清理后被移除）

### 28.6 测试

| 测试类 | 文件 | 测试数 |
|--------|------|--------|
| `TestShipMasterEudora` | `test_core_mechanics.py` | 3 |
| `TestTemporaryBuff` | `test_core_mechanics.py` | 2 |

---

---

## 29. Rally 传播 (Rally Propagation)

### 29.1 概述

Rally 传播允许随从通过 Rally 效果将 Rally 关键词和对应的效果函数赋予其他随从。典型卡牌：Stomping Stegodon (BG33_840) — "Rally: Give your other Beasts +{0} Attack and this Rally."

### 29.2 实现位置

| 组件 | 文件 | 行号 |
|------|------|------|
| 每实体脚本覆盖 | `entity.py` | `_script_overrides` 字典 |
| 覆盖优先调度 | `entity.py` | `_call_script_method()` |
| 卡牌脚本 | `scripts.py` | `StompingStegodonScript._propagated_rally` |

### 29.3 机制

`BaseEntity._script_overrides` 是一个 `Dict[str, Any]`，存储方法名到可调用对象的映射。`_call_script_method` 在查询静态 `data.scripts` 之前先检查此字典。

```python
# 传播 Rally
m._script_overrides["rally"] = StompingStegodonScript._propagated_rally
GainKeyword(m, GameTag.RALLY)  # 设置 RALLY=True tag
```

### 29.4 调度顺序

1. `Attack.do()` 检查 `attacker.has_tag(GameTag.RALLY)` → 调用 `attacker.rally`
2. `rally` 属性 → `_call_script_method("rally")`
3. `_call_script_method` → 先查 `_script_overrides["rally"]`，再回退到 `data.scripts.rally`

### 29.5 边界情况

- **Rally 链式传播**: Rally 每次攻击只触发一次，不会无限循环
- **已死亡随从**: `_propagated_rally` 在迭代时检查 `not m.dead`
- **非原生 Rally 随从**: 通过 `_script_overrides` + `GainKeyword` 获得完整 Rally 能力
- **函数引用持久性**: `@staticmethod` 作为裸函数引用存储，正确接收新 `source`

### 29.6 测试

| 测试类 | 文件 | 测试数 |
|--------|------|--------|
| `TestRally` | `test_core_mechanics.py` | 3 (含传播测试) |

---

## 30. Refresh 追踪 + Fodder 关键词授予

### 30.1 概述

允许卡牌追踪酒馆刷新次数，并在每次刷新时向酒馆随从添加 FODDER 关键词。典型卡牌：Laboratory Assistant (BG35_150) — "Battlecry: Add a Fodder to your next {0} Refreshes."

### 30.2 实现位置

| 组件 | 文件 | 行号 |
|------|------|------|
| 计数器 GameTag | `enums.py` | `FODDER_REFRESH_REMAINING = 139` |
| Action | `actions.py` | `AddFodderToRandomTavernMinion` |
| 事件广播 | `game.py` | `refresh_tavern()` → `TAVERN_REFRESH` |
| 卡牌脚本 | `scripts.py` | `LaboratoryAssistantScript.battlecry` |

### 30.3 机制

战吼设置 `FODDER_REFRESH_REMAINING` 计数器（普通 3，金色 6），并注册持久 `TAVERN_REFRESH` 监听器。`AddFodderToRandomTavernMinion` Action 在每次触发时读取并递减计数器，在随机酒馆随从上调用 `GainKeyword(..., FODDER)`。计数器达到 0 后 Action 变为无操作。

```python
class AddFodderToRandomTavernMinion(Action):
    def do(self, source, game, target=None):
        remaining = source.get_tag(GameTag.FODDER_REFRESH_REMAINING, 0)
        if remaining <= 0:
            return
        source.set_tag(GameTag.FODDER_REFRESH_REMAINING, remaining - 1)
        # 随机选择酒馆随从并设置 FODDER=True
```

### 30.4 调度顺序

1. `refresh_tavern(player)` → 清除酒馆 → 抽取新随从 → 广播 `TAVERN_REFRESH`
2. `broadcast()` → 检查监听器 → 触发 `AddFodderToRandomTavernMinion.trigger()`
3. Action 读取计数器 → 若 >0 则递减并添加 FODDER 关键词

### 30.5 边界情况

- **计数器不会变为负数**: `remaining <= 0` 时提前返回
- **监听器持久化**: 计数器耗尽后监听器保留，但无害无操作
- **金色检测**: `source.is_golden` 在战吼触发前由三连系统设置
- **酒馆随从仅限 MINION**: Action 使用 `CARDTYPE == 1` 过滤法术
- **重复标记**: 对已有 FODDER 标签的随从重复设置标签为无操作

### 30.6 测试

| 测试类 | 文件 | 测试数 |
|--------|------|--------|
| `TestLaboratoryAssistant` | `test_token_cards.py` | 5 |

---

## 31. 英雄技能 (Hero Powers)

### 31.1 概述

英雄技能是英雄实体的特殊能力，可在招募阶段使用。英雄技能遵循与随从脚本相同的模式：
- 主动技能：玩家花费金币手动激活
- 被动技能：使用`on_summon`在游戏开始时注册事件监听器（Phase II 完整实现）

### 31.2 架构

```
Hero (CardType.HERO) ──HERO_POWER tag──→ HeroPower (CardType.HERO_POWER)
    │                                         └── script_class
    └── script_class (与 HeroPower 相同的脚本类)
```

### 31.3 注册

英雄和英雄技能使用 `register_card()` 注册：

```python
# 英雄技能卡牌
register_card(
    card_id="BG20_HERO_103p",
    name="Bloodbound",
    text="Hero Power (1): Give a random friendly minion +1/+1.",
    cardtype=CardType.HERO_POWER,
    tags={GameTag.HERO_POWER_COST: 1},
    script_class=BloodboundScript,
)

# 英雄卡牌
register_card(
    card_id="BG20_HERO_103",
    name="Death Speaker Blackthorn",
    cardtype=CardType.HERO,
    tags={
        GameTag.BASE_HEALTH: 30,
        GameTag.ARMOR: 0,
        GameTag.HERO_POWER: "BG20_HERO_103p",
        GameTag.HERO_POWER_COST: 1,
    },
    script_class=BloodboundScript,
)
```

### 31.4 UseHeroPower Action

文件: `hsrl/core/actions.py`

检查流程:
1. 检查 `HERO_POWER_USED` 是否已设置 → 如已使用则返回
2. 检查金币是否足够 → 不足则返回
3. 扣减金币（`SpendGold`）
4. 设置 `HERO_POWER_USED = True`
5. 执行脚本中的 `hero_power()` 方法
6. 广播 `HERO_POWER_USED` 事件

### 31.5 game.use_hero_power(player)

文件: `hsrl/core/game.py`

将 `UseHeroPower` 加入队列并解析：
```python
def use_hero_power(self, player):
    self.queue_action(UseHeroPower(player), source=player)
    self.resolve_queue()
```

### 31.6 英雄技能脚本模式

```python
class BloodboundScript:
    @staticmethod
    def hero_power(source, game):
        board = source.get_board_minions()
        if not board:
            return None
        target = random.choice(board)
        return Buff(target, atk=1, health=1)
```

`hero_power(source: Player, game: Game) -> Optional[Action]` 签名：
- `source` 是 Player 实体（英雄）
- 返回单个 Action、Action 列表、或 None（无效果）

### 31.7 被动英雄技能

被动技能（如 Rokara 的"Glory of Combat"）使用 `on_summon()` 在游戏开始时注册事件监听器。`start_game()` 直接调用 `on_summon` 脚本方法。

**注意**: 完整的被动英雄技能系统（KILLER 追踪、持续触发）属于 Phase II 范围。

### 31.8 费用处理

英雄技能成本通过 `HERO_POWER_COST` tag 存储：
- 在英雄卡牌注册时设置
- Player 通过 `hero_power_cost` 属性访问
- 成本为 0 时跳过金币扣除

### 31.9 边界情况

- **空棋盘**: 脚本返回 None，但已使用的标记仍设置
- **金币不足**: Action 提前返回，不设置已使用标记，不扣金币
- **同回合两次使用**: 第二次被 `HERO_POWER_USED` 检查拦截
- **每回合重置**: `HERO_POWER_USED` 在 `_start_recruit_phase()` 中重置为 False

### 31.10 测试

| 测试类 | 文件 | 测试数 |
|--------|------|--------|
| `TestHeroCreation` | `test_heroes.py` | 4 |
| `TestHeroPowerUsage` | `test_heroes.py` | 5 |
| `TestHeroPowerGoldCost` | `test_heroes.py` | 3 |
| `TestHeroPowerEffects` | `test_heroes.py` | 4 |
| `TestPassiveHeroPower` | `test_heroes.py` | 2 |

---

*文档版本：0.14.0 | 最后更新：2026-05-01*
