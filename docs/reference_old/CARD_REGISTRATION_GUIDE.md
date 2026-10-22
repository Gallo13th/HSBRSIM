# HSRL 卡牌注册指南

> 本文档详细说明如何将一张炉石传说卡牌从自然语言描述转化为 HSRL 引擎中的可运行代码。
>
> **核心流程**：自然语言文本 → 结构化描述 → 函数注册 → **语义一致性测试**
>
> **版本**: 1.0.0 | **更新日期**: 2026-05-01

---

## 目录

1. [注册流程概览](#1-注册流程概览)
2. [语义精确性原则](#2-语义精确性原则) ← **必读**
3. [无效果随从（白板）](#3-无效果随从白板)
4. [关键词随从](#4-关键词随从)
5. [战吼随从](#5-战吼随从)
6. [亡语随从](#6-亡语随从)
7. [战斗开始时随从](#7-战斗开始时随从)
8. [复仇随从](#8-复仇随从)
9. [Rally（集结）随从](#9-rally集结随从)
10. [鲜血宝石随从](#10-鲜血宝石随从)
11. [复杂多效果随从](#11-复杂多效果随从)
12. [进阶卡牌模式](#12-进阶卡牌模式) ← **新增**
    - 12.1 AttackImmediately（立即攻击）
    - 12.2 TriggerBattlecry（触发战吼）
    - 12.3 ScheduleNextTurn（延迟动作）
    - 12.4 GetRandomMinion（随机获取）
    - 12.5 战斗死亡追踪
    - 12.6 死亡上下文 (in_combat)
    - 12.7 动态缩放追踪
    - 12.8 回合结束时（End of Turn）
    - 12.9 回合开始时（Start of Turn）
    - 12.10 出售时（On Sell）
    - 12.11 变形（Transform）
    - 12.12 吞噬（FodderConsume）
    - 12.13 Spellcraft（法术技艺）
    - 12.14 After Tavern Refreshed（酒馆刷新后）
    - 12.15 After Battlecry Trigger（战吼触发后）
    - 12.16 Start of Combat — 手牌属性聚合
    - 12.17 Rally — 每种族 buff
    - 12.18 Tavern Spell Cast（酒馆法术施放）
    - 12.19 光环翻倍（Aura Doubling）← **Phase G**
    - 12.20 事件驱动 + 条件（Event-Driven + Condition）← **Phase G**
    - 12.21 临时 Buff + Golden 永久保留 ← **Phase G**
    - 12.22 Rally 传播（Rally Propagation）← **Phase H**
    - 12.23 Refresh 追踪 + Fodder 授予 ← **Phase H**
13. [最新赛季机制（Season 13）](#13-最新赛季机制season-13)
    - 13.1 Fodder（恶魔吞噬）— ✅
    - 13.2 Chromadrake（龙变形）— ✅
    - 13.3 酒馆 Buff 追踪 — ✅
    - 13.4 Improves 增强追踪 — ✅
    - 13.5 饰品（Trinkets）
14. [英雄注册](#14-英雄注册)
15. [测试要求](#15-测试要求)

---

## 1. 注册流程概览

### 1.1 四步流程

```
┌──────────────┐     ┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ 自然语言描述  │ ──→ │  程式化规格描述   │ ──→ │  Python 代码注册  │ ──→ │  语义一致性测试   │
│ (卡牌游戏文本) │     │ (精确操作语义)    │     │ (register_card)  │     │  (效果与文本一致)  │
└──────────────┘     └─────────────────┘     └──────────────────┘     └──────────────────┘
```

**关键原则**：代码实现必须与卡牌文本描述的**操作语义**一致，而非"近似替代"。

### 1.2 卡牌实现的二元状态

每张卡牌必须处于以下两种状态之一，**不存在第三种状态**：

| 状态 | 含义 | 代码约定 |
|------|------|---------|
| **CORRECT** | 实现与卡牌文本的操作语义精确一致 | `@staticmethod` 返回正确的 `Action` |
| **DEFERRED** | 引擎尚不支持所需机制，暂不实现 | 方法返回 `None`，docstring 写清楚依赖 |

**"简化实现"不可接受。** 用语义不同的行为替代正确的效果是一个 bug，不是一个简化。

典型错误示例：

```python
# ═══ 错误示例 ═══
class ShellCollectorScript:
    """Battlecry: Get a Tavern Coin."""
    @staticmethod
    def battlecry(source, game):
        return GainGold(source.controller, 1)  # ❌ "Get a Coin" ≠ "Gain 1 Gold"
        # Coin 是可以跨回合保留的手牌资源，GainGold 是立即获得金币
        # 这是语义错误，不是简化

# ═══ 正确做法 ═══
class ShellCollectorScript:
    """
    Natural language: Battlecry: Get a Tavern Coin.

    Status: DEFERRED — requires Coin spell card system
    Dependency: Coin spell card registration + GetCoin Action
    """
    @staticmethod
    def battlecry(source, game):
        return None  # 等待 Coin 系统实现
```

### 1.3 DEFERRED 卡牌格式

```python
class MyCardScript:
    """
    Natural language: <卡牌原始文本>

    Status: DEFERRED — <需要什么引擎特性>
    Dependency: <依赖什么先决条件>
    """

    @staticmethod
    def battlecry(source, game):
        return None
```

### 1.4 脚本类文档规范

每个脚本类必须包含**三段式注释**：

```python
class MyCardScript:
    """
    Natural language: <卡牌原始文本>
    
    Formal spec:
      1. <步骤 1 — 精确描述发生了什么操作>
      2. <步骤 2 — 尽可能精确>
      ...
    
    Test: <用一句话描述测试如何验证形式规格>
    """
    
    @staticmethod
    def battlecry(source, game):
        ...
```

### 1.5 注册函数签名

```python
from hsrl.core.card_db import register_card
from hsrl.core.enums import CardType, GameTag, Race, Rarity

register_card(
    card_id="BGS_001",              # 唯一标识符
    name="卡牌名称",                 # 显示名称
    text="卡牌描述文本",             # 自然语言描述（保留原样）
    cardtype=CardType.MINION,        # 卡牌类型
    race=Race.BEAST,                 # 种族（可为 None）
    tech_level=2,                    # 酒馆等级 1-7
    rarity=Rarity.COMMON,            # 稀有度
    tags={                           # 所有可见属性
        GameTag.BASE_ATK: 3,
        GameTag.BASE_HEALTH: 4,
        GameTag.TAUNT: True,
    },
    script_class=MyCardScript,       # 行为脚本类（可选）
)
```

### 1.6 脚本类规范

如果卡牌有效果，必须定义一个脚本类：

```python
class MyCardScript:
    """
    卡牌效果脚本。
    所有效果方法都必须是 @staticmethod，签名统一为 (source, game) -> Action。
    """

    @staticmethod
    def battlecry(source, game):
        """战吼效果"""
        return Buff(source, atk=2, health=2)

    @staticmethod
    def deathrattle(source, game):
        """亡语效果"""
        return Summon(source.controller, game.create_minion("TOKEN_001"))

    @staticmethod
    def start_of_combat(source, game):
        """战斗开始时效果"""
        return DealDamageToRandomEnemy(source.controller, 3)

    @staticmethod
    def avenge(source, game):
        """复仇效果（当 AVENGE_COUNTER 达到阈值时触发）"""
        return GainKeyword(source, GameTag.DIVINE_SHIELD)

    @staticmethod
    def rally(source, game):
        """集结效果（攻击宣告时触发，伤害结算前）"""
        target = game._last_attack_target
        if target is None:
            return None
        return Hit(target, 2, source)
```

**重要规则**:
- 方法名必须是官方机制名的小写形式：`battlecry`, `deathrattle`, `start_of_combat`, `avenge`, `rally`。
- 返回值必须是 `Action` 实例或 `Action` 列表。
- 如果效果需要选择目标，目标选择逻辑应封装在 Action 内部（如 `DealDamageToRandomEnemy`）。
- Rally 方法通过 `game._last_attack_target` 获取攻击目标。Rally 触发于攻击宣告时（伤害结算前），目标必定存活。

---

## 2. 语义精确性原则

### 2.1 核心原则

**代码实现必须与卡牌文本的操作语义精确一致，禁止"近似替代"。**

炉石传说的卡牌文本使用精确的动词来描述操作：

| 动词 | 操作语义 | 引擎实现 |
|------|---------|---------|
| **Get** (获得) | 卡牌加入手牌，供后续选择目标使用 | `GetBloodGem` — 创建法术实体加入 `player.hand` |
| **Play** (施放) | 立即对目标执行效果（不经过手牌） | `PlayBloodGems` — 直接施加 Buff |
| **Summon** (召唤) | 将随从放置到场上 | `Summon` — 创建 Minion 加入 board |
| **Give** (给予) | 永久属性增益 | `Buff` — 添加 BuffEnchantment |
| **Gain** (获得) | 临时/永久获得关键词 | `GainKeyword` |
| **Deal** (造成) | 造成伤害 | `Hit` |
| **Destroy** (消灭) | 直接杀死 | `Destroy` |

**违反此原则的例子：将 "Get 2 Blood Gems" 实现为 "Play 2 Blood Gems on self"。**
- Get → 手牌（玩家可自由选择目标）
- Play on self → 立即对本随从生效
- 这两个操作的**游戏策略影响完全不同**。

### 2.2 典型案例：Blood Gem "Get" vs "Play"

#### 错误实现（已被修正）

```python
# BG20_100: "Battlecry: Get 2 Blood Gems."
class RazorfenGeomancerScript:
    @staticmethod
    def battlecry(source, game):
        # ❌ 错误："Get" 变成了 "Play on self"
        return PlayBloodGems(source, count=2)
```

**为什么错？**
- 卡牌文本说 **Get**（获得鲜血宝石到手牌）
- 实现做了 **Play on self**（立即对自己施放鲜血宝石）
- 在真实游戏中，"Get" 意味着玩家可以在招募阶段自由选择目标施放
- "Play on self" 剥夺了玩家的目标选择权，完全改变了策略价值

#### 正确实现

```python
# BG20_100: "Battlecry: Get 2 Blood Gems."
class RazorfenGeomancerScript:
    """
    Natural language: Battlecry: Get 2 Blood Gems.
    
    Formal spec:
      1. Create 2 Blood Gem spell entities (card_id="BLOOD_GEM")
      2. Add them to the source's controller's hand (Zone.HAND)
      3. Each Blood Gem can later be played on a friendly minion
         to buff it by (1 + BLOOD_GEM_BONUS_ATK)/(1 + BLOOD_GEM_BONUS_HEALTH)
    
    Test: verify player.hand contains 2 cards of type BLOOD_GEM_CARD
          after the Battlecry resolves.
    """
    @staticmethod
    def battlecry(source, game):
        return GetBloodGem(source.controller, count=2)
```

#### 如何判断是否"准确"？

| 检查项 | 问题 |
|--------|------|
| 动词 | "Get"、"Play"、"Summon" 是否与卡牌文本一致？ |
| 目标 | 效果目标是否与卡牌文本一致（自身/友方/全部/相邻）？ |
| 数值 | 加成数值是否与卡牌文本一致（包括后续修饰）？ |
| 条件 | "If..." "Avenge(N)" 等条件是否在正确时机检查？ |
| 时机 | 触发时机是否与游戏规则一致？ |

### 2.3 不支持的机制：标记为暂缓

如果某个卡牌使用了引擎尚未支持的机制（如手牌法术、选择界面、招募阶段），正确的做法是：

```python
class MyCardScript:
    """
    Natural language: Battlecry: Get a Blood Gem.
    
    Formal spec: Add 1 Blood Gem spell to player's hand.
    
    Status: DEFERRED — requires Phase 6 (Spell/Token system)
    for the "play Blood Gem from hand" mechanic.
    """
    # 暂不实现，等待依赖系统就绪
```

**绝对不要**为了"先运行起来"而用语义不同的行为替代。

---

## 3. 无效果随从（白板）

### 3.1 自然语言

> "3/4 Beast."

### 2.2 结构化描述

- 类型: Minion
- 种族: Beast
- 攻击力: 3
- 生命值: 4
- 关键词: 无
- 效果: 无

### 2.3 代码注册

```python
register_card(
    card_id="BGS_VANILLA_BEAST",
    name="Vanilla Beast",
    text="",
    cardtype=CardType.MINION,
    race=Race.BEAST,
    tech_level=1,
    tags={
        GameTag.BASE_ATK: 3,
        GameTag.BASE_HEALTH: 4,
    },
)
```

### 2.4 测试

```python
def test_vanilla_beast():
    game = Game([])
    game.card_db = CARDS
    m = game.create_minion("BGS_VANILLA_BEAST")
    assert m.atk == 3
    assert m.health == 4
    assert m.race == Race.BEAST
```

---

## 4. 关键词随从

### 3.1 自然语言

> "Taunt. Divine Shield."

### 3.2 结构化描述

- 关键词: `TAUNT=True`, `DIVINE_SHIELD=True`
- 效果: 无额外脚本（关键词逻辑由引擎自动处理）

### 3.3 代码注册

```python
register_card(
    card_id="BGS_TAUNT_SHIELD",
    name="Shieldbearer",
    text="Taunt. Divine Shield.",
    cardtype=CardType.MINION,
    race=Race.NONE,
    tech_level=2,
    tags={
        GameTag.BASE_ATK: 2,
        GameTag.BASE_HEALTH: 4,
        GameTag.TAUNT: True,
        GameTag.DIVINE_SHIELD: True,
    },
)
```

**注意**: 纯关键词随从不需要 `script_class`。引擎在 `Hit.do()`、`game._choose_attack_target()` 等位置自动检查关键词标签。

---

## 5. 战吼随从

### 4.1 自然语言

> "Battlecry: Give a friendly minion +2/+2."

### 4.2 结构化描述

- 关键词: `BATTLECRY=True`
- 效果: 对友方随从施加 Buff(+2, +2)

### 4.3 代码注册

```python
from hsrl.core.actions import Buff
from hsrl.core.events import EventListener

class BGS_BattlecryBuff_Script:
    @staticmethod
    def battlecry(source, game):
        # 简化示例：buff 自己
        # 真实实现中应使用 Selector 选择随机友方随从
        return Buff(source, atk=2, health=2)

register_card(
    card_id="BGS_BATTLECRY_BUFF",
    name="Battlecry Buffer",
    text="Battlecry: Give a friendly minion +2/+2.",
    cardtype=CardType.MINION,
    race=Race.NONE,
    tech_level=2,
    tags={
        GameTag.BASE_ATK: 2,
        GameTag.BASE_HEALTH: 2,
        GameTag.BATTLECRY: True,
    },
    script_class=BGS_BattlecryBuff_Script,
)
```

### 4.4 触发时机

战吼在招募阶段由玩家手动打出随从时触发。触发代码示例：

```python
def play_minion_from_hand(player, minion, target_board_position):
    game.summon(player, minion, position=target_board_position)
    if minion.battlecry:
        action = minion.battlecry(minion, game)
        if action:
            game.queue_action(action, source=minion)
            game.resolve_queue()
```

---

## 6. 亡语随从

### 5.1 自然语言

> "Deathrattle: Summon a 2/2 Token."

### 5.2 结构化描述

- 关键词: `DEATHRATTLE=True`
- 效果: 死亡时召唤 2/2 Token

### 5.3 代码注册

```python
class BGS_DeathrattleSummon_Script:
    @staticmethod
    def deathrattle(source, game):
        token = game.create_minion("BGS_TOKEN_2_2")
        return Summon(source.controller, token)

register_card(
    card_id="BGS_DEATHRATTLE_SUMMON",
    name="Token Spawner",
    text="Deathrattle: Summon a 2/2 Token.",
    cardtype=CardType.MINION,
    race=Race.BEAST,
    tech_level=2,
    tags={
        GameTag.BASE_ATK: 2,
        GameTag.BASE_HEALTH: 3,
        GameTag.DEATHRATTLE: True,
    },
    script_class=BGS_DeathrattleSummon_Script,
)
```

### 5.4 触发时机

亡语由 `game._check_deaths()` 在死亡处理阶段自动触发。

---

## 7. 战斗开始时随从

### 6.1 自然语言

> "Start of Combat: Deal 3 damage to a random enemy minion."

### 6.2 代码注册

```python
class BGS_StartOfCombat_Script:
    @staticmethod
    def start_of_combat(source, game):
        return DealDamageToRandomEnemy(source.controller, 3)

register_card(
    card_id="BGS_START_OF_COMBAT",
    name="Sniper",
    text="Start of Combat: Deal 3 damage to a random enemy minion.",
    cardtype=CardType.MINION,
    race=Race.MECH,
    tech_level=3,
    tags={
        GameTag.BASE_ATK: 3,
        GameTag.BASE_HEALTH: 3,
        GameTag.START_OF_COMBAT: True,
    },
    script_class=BGS_StartOfCombat_Script,
)
```

### 6.3 触发时机

由 `game._trigger_start_of_combat()` 在战斗阶段开始前调用。

---

## 8. 复仇随从

### 7.1 自然语言

> "Avenge (3): Gain Divine Shield."

### 7.2 结构化描述

- 关键词: `Avenge=True`
- 阈值: `AVENGE_TARGET=3`
- 效果: 获得圣盾

### 7.3 代码注册

```python
class BGS_Avenge_Script:
    @staticmethod
    def avenge(source, game):
        return GainKeyword(source, GameTag.DIVINE_SHIELD)

register_card(
    card_id="BGS_AVENGE_SHIELD",
    name="Avenging Guardian",
    text="Avenge (3): Gain Divine Shield.",
    cardtype=CardType.MINION,
    race=Race.UNDEAD,
    tech_level=3,
    tags={
        GameTag.BASE_ATK: 3,
        GameTag.BASE_HEALTH: 4,
        GameTag.Avenge: True,
        GameTag.AVENGE_TARGET: 3,
    },
    script_class=BGS_Avenge_Script,
)
```

### 7.4 触发时机

由 `AvengeIncrement` Action 在友方随从死亡时自动处理。开发者无需手动触发。

---

## 9. Rally（进击）随从

### 8.1 自然语言

> "Rally: Remove Reborn and Taunt from the target."

### 8.2 结构化描述

- 关键词: `RALLY=True`
- 效果: 攻击宣告时（伤害结算前），移除目标的复生和嘲讽
- 脚本方法: `rally(source, game)` — 通过 `game._last_attack_target` 获取攻击目标

### 8.3 代码注册

```python
class BGS_RallyExample_Script:
    @staticmethod
    def rally(source, game):
        target = game._last_attack_target
        if target is None:
            return None
        actions = []
        if target.reborn:
            actions.append(LoseKeyword(target, GameTag.REBORN))
        if target.taunt:
            actions.append(LoseKeyword(target, GameTag.TAUNT))
        return actions if actions else None

register_card(
    card_id="BGS_RALLY_EXAMPLE",
    name="Rally Example",
    text="Rally: Remove Reborn and Taunt from the target.",
    cardtype=CardType.MINION,
    race=Race.NONE,
    tech_level=3,
    tags={
        GameTag.BASE_ATK: 3,
        GameTag.BASE_HEALTH: 4,
        GameTag.RALLY: True,
    },
    script_class=BGS_RallyExample_Script,
)
```

### 8.4 触发时机

Rally 由 `Attack.do()` 在攻击宣告时**自动触发**，位于 `BEFORE_ATTACK` 广播之后、攻击者造成伤害之前。脚本通过 `game._last_attack_target` 获取本次攻击的目标。由于 Rally 在伤害前触发，目标必定存活，脚本无需检查 `target.dead`。

### 8.5 重要注意事项

- **文本检测**：Rally 关键词在数据 JSON 中**不是**布尔字段。`pool.py` 通过 `_TEXT_KEYWORDS` 从卡牌文本中检测 `"Rally"` 字符串来设置标签。
- **同类**：`Start of Combat` 也通过相同的文本检测机制设置标签。
- **双重机制卡牌**：如果卡牌同时有 Battlecry、Deathrattle 和 Rally（如 `BG34_319`），需同时实现三个方法。

---

## 10. 鲜血宝石随从

鲜血宝石（Blood Gem）是野猪人（Quilboar）种族的专属机制。卡牌文本中使用两个不同的动词来表达截然不同的操作：

| 动词 | 操作 | 引擎 Action | 说明 |
|------|------|-----------|------|
| **Get** | 获得血宝石到**手牌** | `GetBloodGem(player, count, variant)` | 法术卡加入手牌，等待玩家选择目标 |
| **Play** | 立即对目标**施放**血宝石 | `PlayBloodGems(target, count)` | 直接施加 Buff，不经过手牌 |

### 10.1 Get（获得）— 血宝石加入手牌

**自然语言**: > "Battlecry: Get 2 Blood Gems."

**程式化规格**:
1. 创建 N 张 Blood Gem 法术卡（类型 `BLOOD_GEM_CARD`）
2. 将它们加入 source 的 controller 的 hand 列表
3. 每张 Blood Gem 可在招募阶段对友方随从打出

**代码注册**:

```python
class RazorfenGeomancerScript:
    """
    Natural language: Battlecry: Get 2 Blood Gems.

    Formal spec:
      1. Create 2 Blood Gem spell entities (card_id="BLOOD_GEM")
      2. Add them to source.controller.hand (Zone.HAND)
      3. Each Blood Gem can later be played on a friendly minion
         to buff it by (1 + BONUS_ATK) / (1 + BONUS_HEALTH)

    Test: verify player.hand contains 2 cards of type BLOOD_GEM_CARD
          after the Battlecry resolves.
    """
    @staticmethod
    def battlecry(source, game):
        return GetBloodGem(source.controller, count=2)
```

**特殊变体血宝石**:

| 变体 | 卡牌 ID | 效果 |
|------|--------|------|
| 基础 | `BLOOD_GEM` | 给友方随从 +1/+1 |
| 圣盾 | `BLOOD_GEM_DS` | 给友方野猪人 +1/+1 和圣盾 |
| 嘲讽 | `BLOOD_GEM_TAUNT` | 给友方野猪人 +1/+1 和嘲讽 |

```python
# BG33_888: Hog Watcher
class HogWatcherScript:
    """
    Natural language: Battlecry: Get a Blood Gem that also gives
    a Quilboar Divine Shield.

    Formal spec:
      1. Create 1 Divine Shield Blood Gem spell (card_id="BLOOD_GEM_DS")
      2. Add it to source.controller.hand

    Test: verify player.hand contains 1 BLOOD_GEM_DS card.
    """
    @staticmethod
    def battlecry(source, game):
        return GetBloodGem(source.controller, count=1, variant="divine_shield")
```

### 10.2 Play（施放）— 立即施加血宝石效果

**自然语言**: > "Battlecry: Play 2 Blood Gems on all your other minions."

**程式化规格**:
1. 遍历 source.controller.board
2. 对每个存活且不是 source 的随从，执行 PlayBloodGems(m, count=2)
3. PlayBloodGems 从 controller 读取 BLOOD_GEM_BONUS_* 计算最终 buff 值

**代码注册**:

```python
class GemSmugglerScript:
    """
    Natural language: Battlecry: This plays 2 Blood Gems on all your
    other minions.

    Formal spec:
      1. For each m in source.controller.board where m != source and not m.dead:
         PlayBloodGems(m, count=2)
      2. PlayBloodGems applies Buff(+1+bonus, +1+bonus) * count per target

    Test: verify other minion gains +2/+2 (2× base Blood Gem),
          verify source is unaffected.
    """
    @staticmethod
    def battlecry(source, game):
        actions = []
        for m in source.controller.board:
            if m is not source and not m.dead:
                actions.append(PlayBloodGems(m, count=2))
        return actions
```

### 10.3 Improve — 永续增强血宝石效果

**自然语言**: > "Battlecry and Deathrattle: Your Blood Gems give an extra +1/+1 this game."

**程式化规格**:
1. 递增 controller 的 `BLOOD_GEM_BONUS_ATK` 和 `BLOOD_GEM_BONUS_HEALTH` 标签
2. 之后所有 PlayBloodGems 和从手牌打出的 Blood Gem 都会使用新加成值

```python
class SanguineChampionScript:
    """
    Natural language: Battlecry and Deathrattle: Your Blood Gems give
    an extra +1/+1 this game.

    Formal spec:
      1. Increment controller.BLOOD_GEM_BONUS_ATK by 1
      2. Increment controller.BLOOD_GEM_BONUS_HEALTH by 1
      3. All future Blood Gem plays use the increased values

    Test: verify controller BLOOD_GEM_BONUS_* tags increase by 1.
    """
    @staticmethod
    def battlecry(source, game):
        return ImproveBloodGem(source.controller, atk_bonus=1, health_bonus=1)

    @staticmethod
    def deathrattle(source, game):
        return ImproveBloodGem(source.controller, atk_bonus=1, health_bonus=1)
```

### 10.4 Blood Gem 相关的 GameTag

| GameTag | 存储位置 | 含义 |
|---------|---------|------|
| `BLOOD_GEM_BONUS_ATK=120` | Player | 每颗血宝石额外攻击力加成 |
| `BLOOD_GEM_BONUS_HEALTH=121` | Player | 每颗血宝石额外生命值加成 |
| `BLOOD_GEM=59` | Minion | 该随从与血宝石机制交互 |

### 10.5 Blood Gem 法术卡注册

```python
register_card(
    card_id="BLOOD_GEM",
    name="Blood Gem",
    text="Give a friendly minion +1/+1.",
    cardtype=CardType.BLOOD_GEM_CARD,
    race=Race.INVALID,
    tech_level=1,
    tags={},
)
```

---

## 11. 复杂多效果随从

### 9.1 自然语言

> "Battlecry and Deathrattle: Give your other minions +1 Attack."

### 9.2 代码注册

```python
class BGS_MultiEffect_Script:
    @staticmethod
    def battlecry(source, game):
        actions = []
        for m in source.controller.get_board_minions():
            if m is not source:
                actions.append(Buff(m, atk=1, health=0))
        return actions  # 返回 Action 列表

    @staticmethod
    def deathrattle(source, game):
        actions = []
        for m in source.controller.get_board_minions():
            if m is not source:
                actions.append(Buff(m, atk=1, health=0))
        return actions

register_card(
    card_id="BGS_MULTI_EFFECT",
    name="Leader",
    text="Battlecry and Deathrattle: Give your other minions +1 Attack.",
    cardtype=CardType.MINION,
    race=Race.NONE,
    tech_level=3,
    tags={
        GameTag.BASE_ATK: 2,
        GameTag.BASE_HEALTH: 2,
        GameTag.BATTLECRY: True,
        GameTag.DEATHRATTLE: True,
    },
    script_class=BGS_MultiEffect_Script,
)
```

### 9.3 返回 Action 列表

脚本方法可以返回单个 `Action` 或 `Action` 列表/元组。引擎会自动迭代处理。

---

## 12. 进阶卡牌模式

本节涵盖使用高级引擎特性的卡牌模式。这些模式建立在基础机制（战吼、亡语等）之上，但引入了更复杂的时序、追踪和跨回合交互。

### 12.1 AttackImmediately（立即攻击）

**自然语言**: > "Deathrattle: Summon a Whelp that attacks immediately."

**使用场景**: 召唤一个衍生物并让它立刻攻击一个敌方随从（不等待常规战斗顺序）。

```python
class TwilightHatchlingScript:
    """
    Natural language: Deathrattle: Summon a {0}/{1} Whelp that attacks immediately.

    Formal spec:
      1. Create a Twilight Whelp token
      2. Summon it on source.controller's board
      3. The Whelp attacks an enemy minion immediately (respects Taunt)
    """
    @staticmethod
    def deathrattle(source, game):
        token = game.create_minion("BG34_630t")
        return [
            Summon(source.controller, token),
            AttackImmediately(token),
        ]
```

**引擎实现**: `AttackImmediately` 查找 `attacker.controller` 的敌方玩家，从敌方 board 中随机选择目标（Taunt 优先），然后 queue `Attack(attacker, target)`。

**关键**: `AttackImmediately` 返回一个 Action 列表时，`Summon` 必须先执行（将 token 放入 board），然后 `AttackImmediately(token)` 才能找到敌方目标。

### 12.2 TriggerBattlecry（触发战吼）

**自然语言**: > "Deathrattle: Trigger the Battlecry of an adjacent minion."

**使用场景**: 重新触发一个相邻随从的战吼效果。

```python
class RylakMetalheadScript:
    """
    Natural language: Deathrattle: Trigger the Battlecry of an adjacent minion.

    Formal spec:
      1. Find adjacent minions (left and right)
      2. Filter those that have a battlecry
      3. Randomly select one
      4. Trigger its battlecry as if it were just played
    """
    @staticmethod
    def deathrattle(source, game):
        import random
        board = source.controller.board if source.controller else []
        try:
            idx = board.index(source)
        except ValueError:
            return None
        adj_options = []
        for offset in (-1, 1):
            adj_idx = idx + offset
            if 0 <= adj_idx < len(board):
                m = board[adj_idx]
                if not m.dead and m.battlecry:
                    adj_options.append(m)
        if not adj_options:
            return None
        target = random.choice(adj_options)
        return TriggerBattlecry(target)
```

**引擎实现**: `TriggerBattlecry` 调用 `target.battlecry` 方法并将结果加入队列。如果战吼返回 Action 列表，引擎正确迭代。已触发过战吼的随从可以被再次触发（`battlecry` 属性始终可调用）。

### 12.3 ScheduleNextTurn（延迟动作）

**自然语言**: > "Battlecry: Gain 1 Gold next turn."

**使用场景**: 将效果推迟到下一个招募阶段执行。

```python
class SouthseaBuskerScript:
    """
    Natural language: Battlecry: Gain 1 Gold next turn.

    Formal spec:
      1. Schedule a GainGold(1) action for the start of the next Recruit phase
      2. The gold is NOT gained immediately — it is deferred
    """
    @staticmethod
    def battlecry(source, game):
        return ScheduleNextTurn(source.controller, GainGold(source.controller, 1))
```

**引擎实现**: `ScheduleNextTurn` 将 `(player, action)` 存入 `game._deferred_actions`。调用 `game.process_deferred_actions()` 时逐个执行。

**测试策略**: 测试分两步验证：
1. 触发战吼后，立即断言金币未变化（验证延迟）
2. 调用 `game.process_deferred_actions()` 后，断言金币已增加（验证执行）

### 12.4 GetRandomMinion（随机获取）

**自然语言**: > "Battlecry: Get a random Elemental."

**使用场景**: 从卡牌池中随机选择一个满足条件的随从加入手牌。

```python
class TavernTempestScript:
    """
    Natural language: Battlecry: Get a random Elemental.

    Formal spec:
      1. Select a random Elemental from the minion pool
      2. Add it to source.controller.hand (Zone.HAND)
    """
    @staticmethod
    def battlecry(source, game):
        return GetRandomMinion(source.controller, race=Race.ELEMENTAL)
```

**引擎实现**: `GetRandomMinion` 从 `game.card_db._cards` 中过滤候选（按 race、min_tier、max_tier、card_type），随机选择一张，创建 Minion 加入 `player.hand`。

**参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `player` | Player | 接收卡牌的玩家 |
| `race` | Race | 种族过滤（None = 不限） |
| `min_tier` | int | 最低酒馆等级（None = 不限） |
| `max_tier` | int | 最高酒馆等级（None = 不限） |
| `card_type` | CardType | 卡牌类型过滤（None = 不限） |

### 12.5 战斗死亡追踪

**自然语言**: > "Deathrattle: Summon plain copies of your first 2 Mechs that died this combat."

**使用场景**: 需要知道在当前战斗中哪些随从死亡过（以及死亡顺序）。

```python
class KangorsApprenticeScript:
    """
    Natural language: Deathrattle: Summon plain copies of your
    first 2 Mechs that died this combat.

    Formal spec:
      1. Read game._combat_death_log, filtered by source.controller
      2. Take the first 2 that have race=MECH
      3. For each, create a fresh minion from the same card_id
      4. Summon them on source.controller's board
    """
    @staticmethod
    def deathrattle(source, game):
        actions = []
        count = 0
        for dead in game._combat_death_log:
            if dead.controller is not source.controller:
                continue
            if dead.race != Race.MECH:
                continue
            if dead.get_tag(GameTag.CARD_ID) == source.get_tag(GameTag.CARD_ID):
                continue  # Don't copy self
            if count >= 2:
                break
            copy_minion = game.create_minion(dead.get_tag(GameTag.CARD_ID))
            actions.append(Summon(source.controller, copy_minion))
            count += 1
        return actions
```

**引擎支持**:
- `game._combat_death_log: List[Minion]` — 在 `_check_deaths()` 中追加已死亡的随从
- 在 `_run_combat()` 开始时清空

**注意**: 战斗死亡日志中的随从对象在 `_check_deaths()` 中已被 `remove_from_board()`，其 `zone == Zone.GRAVEYARD`。通过 `get_tag(GameTag.CARD_ID)` 获取原始卡牌 ID 而不是直接访问对象属性。

### 12.6 死亡上下文 (in_combat)

**自然语言**: > "Deathrattle: Your Undead have +{0} Attack this game. (+{1} if this died outside combat!)"

**使用场景**: 效果根据随从死亡时的上下文（战斗内 vs 战斗外）有不同的行为。

```python
class PlaguerunnerScript:
    """
    Natural language: Deathrattle: Your Undead have +{0} Attack this game,
    wherever they are. (+{1} if this died outside combat!)

    Formal spec:
      1. If game.in_combat is True:
         a. Read PLAGUERUNNER_SCALE (default 3), apply aura, increment scale
      2. If game.in_combat is False:
         a. Apply +1 ATK aura, do NOT increment scale
    """
    @staticmethod
    def deathrattle(source, game):
        controller = source.controller
        if controller is None:
            return None
        if game.in_combat:
            x = controller.get_tag(GameTag.PLAGUERUNNER_SCALE, 3)
            controller.set_tag(GameTag.PLAGUERUNNER_SCALE, x + 1)
            return ApplyGlobalAura(controller, atk=x, health=0, race_filter=Race.UNDEAD)
        else:
            return ApplyGlobalAura(controller, atk=1, health=0, race_filter=Race.UNDEAD)
```

**引擎支持**:
- `game.in_combat: bool` — 在 `_run_combat()` 入口设为 `True`，出口设为 `False`
- 招募阶段死亡 (`game.queue_action(Destroy(...))`) → `in_combat=False`

### 12.7 动态缩放追踪

**自然语言**: > "Battlecry: Give your other Murlocs +{0} Attack. (Improved by each Mrrglton you played this game!)"

**使用场景**: 卡牌效果随本局游戏中特定事件的发生次数而增长。

```python
class MamaMrrgltonScript:
    """
    Natural language: Battlecry: Give your other Murlocs +{0} Attack.
    (Improved by each Mrrglton you played this game!)

    Formal spec:
      1. Increment source.controller's MRRGLTON_COUNT tag by 1
      2. Buff all other friendly Murlocs by +count Attack
    """
    @staticmethod
    def battlecry(source, game):
        player = source.controller
        count = player.get_tag(GameTag.MRRGLTON_COUNT, 0) + 1
        player.set_tag(GameTag.MRRGLTON_COUNT, count)
        actions = []
        for m in player.get_board_minions():
            if m is not source and m.race in (Race.MURLOC, Race.ALL):
                actions.append(Buff(m, atk=count, health=0))
        for m in player.get_hand_minions():
            if m.race in (Race.MURLOC, Race.ALL):
                actions.append(Buff(m, atk=count, health=0))
        return actions
```

**引擎支持**:
| GameTag | 存储位置 | 含义 |
|---------|---------|------|
| `MRRGLTON_COUNT=87` | Player | 已打出的 Mrrglton 数量 |
| `PLAGUERUNNER_SCALE=122` | Player | Plaguerunner 下一次触发时的 Attack 加成 |

**测试策略**: 验证第二次打出的 buff 比第一次大（证明缩放生效），且前一次打出的随从受到第二次 buff 时也使用新的倍率。

### 12.8 回合结束时（End of Turn）

**自然语言**: > "At the end of your turn, give this minion +1/+1."

**使用场景**: 在每个招募阶段结束时自动触发效果。

```python
class ExampleEndOfTurnScript:
    """
    Natural language: At the end of your turn, give this minion +1/+1.

    Formal spec:
      1. At end of each Recruit phase, Buff(source, atk=1, health=1)

    Test: Advance to END_RECRUIT, verify source has +1/+1.
    """
    @staticmethod
    def end_of_turn(source, game):
        return Buff(source, atk=1, health=1)
```

**引擎实现**: `_trigger_end_of_turn()` 遍历所有玩家 board 上的 minion，调用 `end_of_turn()` 方法并 resolve。

**注册标签**: 需要 `GameTag.END_OF_TURN: True`

### 12.9 回合开始时（Start of Turn）

**自然语言**: > "At the start of your turn, gain 1 Gold."

**使用场景**: 在每个招募阶段开始时自动触发效果。

```python
class ExampleStartOfTurnScript:
    """
    Natural language: At the start of your turn, gain 1 Gold.

    Formal spec:
      1. At start of each Recruit phase, GainGold(1) for controller
    """
    @staticmethod
    def start_of_turn(source, game):
        return GainGold(source.controller, 1)
```

**引擎实现**: `_trigger_start_of_turn()` 在 `_start_recruit_phase()` 中调用。

**注册标签**: 需要 `GameTag.START_OF_TURN: True`

### 12.10 出售时（On Sell）

**自然语言**: > "When you sell this, get a random Murloc."

**使用场景**: 随从被出售时触发效果。

```python
class ExampleOnSellScript:
    """
    Natural language: When you sell this, get a random Murloc.

    Formal spec:
      1. When sold, GetRandomMinion(MURLOC) for controller
    """
    @staticmethod
    def on_sell(source, game):
        return GetRandomMinion(source.controller, race=Race.MURLOC)
```

**引擎实现**: `sell_minion()` 在返还卡牌到池后检查 `on_sell` 属性并触发。

**注册标签**: 需要 `GameTag.ON_SELL: True`

### 12.11 变形（Transform）

**自然语言**: > "Start of Combat: Transform into an 8/8 Dragon."

**使用场景**: 将一个随从完全替换为另一个，保留 buff 和 Golden 状态。

```python
class ExampleTransformScript:
    """
    Natural language: Start of Combat: Transform into an 8/8 Dragon.

    Formal spec:
      1. Replace source with EXAMPLE_TRANSFORMED minion
      2. Preserve all buffs and Golden status
      3. Keep same board position
    """
    @staticmethod
    def start_of_combat(source, game):
        return Transform(source, "EXAMPLE_TRANSFORMED")
```

**引擎实现**: `Transform(target, new_card_id)` — 创建新随从，转移所有 `BuffEnchantment`，继承 Golden 状态，在 board 中替换位置。

**关键**: `Transform` 保留 buff。如果不想保留 buff，应先调用 `target.clear_buffs()` 再 Transform。

### 12.12 吞噬（FodderConsume）

**自然语言**: > "Battlecry: Consume a minion in your hand to gain its stats."

**使用场景**: 恶魔吞噬手牌或场上的随从，获得其攻击力和最大生命值。

```python
class ExampleFodderScript:
    """
    Natural language: Battlecry: Consume a minion in your hand to gain its stats.

    Formal spec:
      1. Select the highest ATK minion in hand
      2. FodderConsume it — remove from hand, buff source with its stats
    """
    @staticmethod
    def battlecry(source, game):
        hand = source.controller.get_hand_minions()
        if hand:
            target = max(hand, key=lambda m: m.atk)
            return FodderConsume(source, target)
        return None
```

**引擎实现**: `FodderConsume(demon, consumed_minion)` — 读取 consumed 的 `atk` 和 `max_health`，移除 consumed，对 demon 施加 Buff。

**重要**: 使用 `max_health`（而非 `health`），因为吞噬获得的是"属性值"（最大属性）。

### 12.13 Spellcraft（法术技艺）

**自然语言**: > "Spellcraft: Give a friendly minion +2/+1."

**使用场景**: 每个招募阶段开始时，自动生成一张临时法术卡加入手牌。

**引擎实现**: `_generate_spellcraft_spells()` 在每个招募阶段开始时调用 `spellcraft()` 脚本方法。该方法返回一个 **card_id 字符串**（不是 Action），引擎据此创建法术实体。

```python
class ExampleSpellcraftMinionScript:
    """
    Natural language: Spellcraft: Give a friendly minion +2/+1.

    Formal spec:
      1. At start of each Recruit phase, generate spell card EXAMPLE_SC_SPELL
      2. Spell goes to hand with SPELLCRAFT_SPELL tag
      3. Unused spells are cleaned up at end of Recruit phase
    """
    @staticmethod
    def spellcraft(source, game):
        return "EXAMPLE_SC_SPELL"
```

**关键**: `spellcraft()` 方法签名是 `(source, game) -> str`，返回 card_id，不是 Action。生成的卡牌打上 `GameTag.SPELLCRAFT_SPELL = True` 标签以用于结束回合清理。

### 12.14 After Tavern Refreshed（酒馆刷新后）

**自然语言**: > "Battlecry: After the Tavern is Refreshed this game, give a random minion in it +2/+2."

**使用场景**: 卡牌在打出时注册一个持久化事件监听器，每次酒馆刷新时触发效果。效果目标为**酒馆中的随从**，而非友方棋盘。

**关键语义**: "give a random minion **in it**" → `player.tavern`（酒馆），不是 `player.board`（棋盘）。

**引擎 Action**: `BuffRandomTavernMinion(player, atk=X, health=Y)` — 从 `player.tavern` 中随机选择一个存活随从，对其施加 Buff。

**事件**: `TAVERN_REFRESH` — 在 `game.refresh_tavern()` 末尾广播。

**注意**: `battlecry`/`deathrattle` 方法注册 EventListener 作为副作用，返回 `None`。测试时需注意：`m.battlecry` 触发副作用即可，不应将 `None` 加入 Action 队列。

```python
class EnDjinnBlazerScript:
    """
    Natural language: Battlecry: After the Tavern is Refreshed this game,
    give a random minion in it +3/+3.

    Formal spec:
      1. Register a TAVERN_REFRESH EventListener for source's controller
      2. On each TAVERN_REFRESH: BuffRandomTavernMinion(+3/+3)
      3. Listener persists for the rest of the game

    Test: verify listener registered, then refresh tavern and
          verify a tavern minion got +3/+3.
    """
    @staticmethod
    def battlecry(source, game):
        from hsrl.core.events import EventListener
        from hsrl.core.actions import BuffRandomTavernMinion
        listener = EventListener(
            event_name="TAVERN_REFRESH",
            action=BuffRandomTavernMinion(source.controller, atk=3, health=3),
        )
        game.register_listener(source, listener)
        return None  # Side effect only — no Action to queue
```

### 12.15 After Battlecry Trigger（战吼触发后）

**自然语言**: > "After you trigger a Battlecry, gain +1/+1."

**使用场景**: 卡牌在召唤时注册一个持久化事件监听器，每次友方战吼被触发时自动获得增益。

**引擎事件**: `BATTLECRY_TRIGGER` — 在 `TriggerBattlecry.do()` 末尾广播，参数为 `(target, target.controller)`。

**条件过滤**: 使用 `EventListener` 的 `condition` 参数限制为仅同控制器触发：
```python
condition=lambda t, p: p == source.controller
```

**脚本方法**: `on_summon(source, game)` — 通过 `entity.py` 中的 `on_summon` 属性在随从被召唤到棋盘时自动调用。

```python
class BlazingSkyfinScript:
    """
    Natural language: After you trigger a Battlecry, gain +1/+1.

    Formal spec:
      1. Register a BATTLECRY_TRIGGER EventListener for source
      2. On each BATTLECRY_TRIGGER from source's controller: Buff(source, +1/+1)
      3. Listener persists for the rest of the game

    Test: register listener via on_summon, trigger a battlecry,
          verify source gained +1/+1.
    """
    @staticmethod
    def on_summon(source, game):
        from hsrl.core.events import EventListener
        from hsrl.core.actions import Buff
        listener = EventListener(
            event_name="BATTLECRY_TRIGGER",
            action=Buff(source, atk=1, health=1),
            condition=lambda t, p: p == source.controller,
        )
        game.register_listener(source, listener)
        return None
```

**多目标 buff 变体** (Kalecgos):

当效果需要 buff 多个目标时（如"give your Dragons +1/+1"），使用内嵌 Action 子类：

```python
class _BuffAllFriendlyDragons(Action):
    def __init__(self, player, atk, health):
        super().__init__()
        self.player = player
        self._atk = atk
        self._health = health

    def do(self, source, game, target=None):
        for m in self.player.board:
            if not m.dead and m.race in (Race.DRAGON, Race.ALL):
                Buff(m, atk=self._atk, health=self._health).do(source, game)
```

### 12.16 Start of Combat — 手牌属性聚合

**自然语言**: > "Start of Combat: Gain the combined Attack and Health of the minions in your hand."

**使用场景**: 战斗开始时，读取手牌中所有随从的属性，聚合到自身。

```python
class ChoralMrrrglrScript:
    """
    Natural language: Start of Combat: Gain the combined Attack
    and Health of the minions in your hand.

    Formal spec:
      1. Sum atk and max_health of all MINION-typed cards in hand
      2. Buff source by total_atk / total_health
      3. Return None if hand has no minions

    Test: put 2 minions in hand (3/2 and 4/5), verify source
          gains +7/+7 from SoC.
    """
    @staticmethod
    def start_of_combat(source, game):
        hand = source.controller.hand
        hand_minions = [m for m in hand if m.get_tag(GameTag.CARDTYPE) == CardType.MINION]
        total_atk = sum(m.atk for m in hand_minions)
        total_health = sum(m.max_health for m in hand_minions)
        if total_atk == 0 and total_health == 0:
            return None
        return Buff(source, atk=total_atk, health=total_health)
```

**注意**: 使用 `max_health` 而非 `health`，因为聚合的是"属性值"（最大属性），而非当前血量。

### 12.17 Rally — 每种族 buff

**自然语言**: > "Rally: Give one friendly minion of each type +2/+2."

**使用场景**: Rally 触发时，从己方棋盘收集每种种族各一个随从（不含自身），对每个收集到的随从施加 Buff。

```python
class TheLastOneStandingScript:
    """
    Natural language: Rally: Give one friendly minion of
    each type +2/+2.

    Formal spec:
      1. Collect one minion per unique race from friendly board
         (excluding source)
      2. Buff each collected minion +2/+2
      3. Each race gets at most one buff target

    Test: board with 1 Beast, 1 Murloc, 1 Dragon → each gets +2/+2.
    """
    class _BuffOnePerRace(Action):
        def __init__(self, player, atk, health):
            super().__init__()
            self.player = player
            self._atk = atk
            self._health = health

        def do(self, source, game, target=None):
            boarded = {}
            for m in self.player.board:
                if not m.dead and m != source:
                    race = m.get_tag(GameTag.RACE)
                    if race and race not in boarded:
                        boarded[race] = m
            for m in boarded.values():
                Buff(m, atk=self._atk, health=self._health).do(source, game)

    @staticmethod
    def rally(source, game):
        return TheLastOneStandingScript._BuffOnePerRace(
            source.controller, atk=2, health=2
        )
```

### 12.18 Tavern Spell Cast（酒馆法术施放）

**自然语言**: > "Start of Combat: Give your Dragons +{0}/+{1}. Improves permanently after you cast a Tavern spell."

**使用场景**: 卡牌通过注册 `TAVERN_SPELL_CAST` 事件监听器或读取 `TAVERN_SPELLS_CAST_THIS_TURN` 回合计数器来追踪酒馆法术施放。

**引擎 Action**: `CastTavernSpell(player)` — 广播 `TAVERN_SPELL_CAST` 事件并递增 `TAVERN_SPELLS_CAST_THIS_TURN` 计数器。

**两种使用模式**:

1. **永久计数** (Fire-forged Evoker) — 与 Ultraviolet Ascendant 相同的模式：
   - `on_summon` 注册 `TAVERN_SPELL_CAST` 监听 → `IncrementImproveCounter(source)`
   - 效果时读取 `IMPROVE_COUNTER` 作为乘数

2. **回合快照** (Roving Sailor) — 与 Lovesick Balladist 相同的模式：
   - Battlecry 时直接读取 Player 的 `TAVERN_SPELLS_CAST_THIS_TURN`
   - 每回合开始时自动重置为 0

```python
# Fire-forged Evoker — 永久计数模式
class FireForgedEvokerScript:
    """
    Natural language: Start of Combat: Give your Dragons +{0}/+{1}.
    Improves permanently after you cast a Tavern spell.

    Formal spec:
      1. on_summon: register TAVERN_SPELL_CAST listener → IncrementImproveCounter(source)
      2. start_of_combat: read IMPROVE_COUNTER, buff random friendly Dragon
         by (1+counter)*(+1/+2)

    Test: cast 2 tavern spells, trigger SoC, verify Dragon gets +3/+6.
    """
    @staticmethod
    def on_summon(source, game):
        from hsrl.core.events import EventListener
        from hsrl.core.actions import IncrementImproveCounter
        listener = EventListener(
            event_name="TAVERN_SPELL_CAST",
            action=IncrementImproveCounter(source),
        )
        game.register_listener(source, listener)
        return None

    @staticmethod
    def start_of_combat(source, game):
        from hsrl.core.actions import Buff
        from hsrl.core.enums import GameTag, Race as GameRace
        counter = source.get_tag(GameTag.IMPROVE_COUNTER, 0)
        candidates = [m for m in source.controller.board
                      if not m.dead and m != source and m.race == GameRace.DRAGON]
        if not candidates:
            return None
        import random
        target = random.choice(candidates)
        mult = 1 + counter
        return Buff(target, atk=1 * mult, health=2 * mult)

# Roving Sailor — 回合快照模式
class RovingSailorScript:
    """
    Natural language: Battlecry: Give a friendly minion +{0}/+{1}.
    Improved by each Tavern spell you cast this turn!

    Formal spec:
      1. battlecry: read player's TAVERN_SPELLS_CAST_THIS_TURN
      2. Buff random friendly minion (excluding self) by spell_count*(+1/+2)
      3. Return None if no candidates or spell_count==0

    Test: cast 3 tavern spells, play Roving Sailor,
    verify friendly minion gets +3/+6.
    """
    @staticmethod
    def battlecry(source, game):
        from hsrl.core.actions import Buff
        from hsrl.core.enums import GameTag
        spell_count = source.controller.get_tag(
            GameTag.TAVERN_SPELLS_CAST_THIS_TURN, 0)
        candidates = [m for m in source.controller.board
                      if not m.dead and m != source]
        if not candidates or spell_count == 0:
            return None
        import random
        target = random.choice(candidates)
        return Buff(target, atk=1 * spell_count, health=2 * spell_count)
```

**状态**: 完整酒馆法术系统已实现（Spell 实体 + SpellPool + buy/play + NEXT_SPELL_COST_REDUCTION 折扣）。Ominous Seer (BG31_330) 已激活 — 战吼设置折扣，`buy_spell()` 消费折扣。

### 12.19 光环翻倍（Aura Doubling）— ✅ Phase G

**自然语言**: "Your Battlecries/End of Turn effects trigger twice."

**模式**: Player-tag 方案 — 卡牌召唤时在 Player 上设置持久 GameTag，引擎在触发时检查。

**已实现卡牌**:
| 卡牌 | 效果 | 机制 |
|------|------|------|
| `BG_LOE_077` Brann Bronzebeard | 战吼翻倍 | `BATTLECRY_DOUBLED` tag on Player |
| `BG26_ICC_901` Drakkari Enchanter | 回合结束翻倍 | `END_OF_TURN_DOUBLED` tag on Player |

**引擎检查点**:
- `play_minion()` — 检查 `BATTLECRY_DOUBLED`，翻倍 queue 战吼
- `TriggerBattlecry.do()` — 同样检查翻倍
- `_trigger_end_of_turn()` — 检查 `END_OF_TURN_DOUBLED`，翻倍 queue

```python
class BrannScript:
    @staticmethod
    def on_summon(source, game):
        source.controller.set_tag(GameTag.BATTLECRY_DOUBLED, True)
        return None
```

### 12.20 事件驱动 + 条件（Event-Driven + Condition）— ✅ Phase G

**自然语言**: "After your hero takes damage on your turn, gain +2/+2."

**模式**: `on_summon` 注册持久 `EventListener`，带 `condition` 检查游戏状态。

```python
class FloatingWatcherScript:
    @staticmethod
    def on_summon(source, game):
        listener = EventListener(
            event_name=PLAYER_DAMAGE_TAKEN,
            action=Buff(source, atk=2, health=2),
            condition=lambda p, dmg, src: (
                p == source.controller and game.step == Step.RECRUIT
            ),
        )
        game.register_listener(source, listener)
        return None
```

**关键点**: 条件使用闭包捕获 `source`，检查 `game.step == Step.RECRUIT`（己方回合）和 `p == source.controller`（自己受伤）。

### 12.21 临时 Buff + Golden 永久保留 — ✅ Phase G

**自然语言**: "Deathrattle: Give your minions +2/+2 (permanent if Golden)."

**模式**: `Buff(temporary=True)` 创建临时 buff，战斗结束时引擎自动清除。Golden 时 `temporary=False`。

**引擎**: `_end_combat_phase()` 遍历存活随从，过滤 `temporary=True` 的 buff。

```python
class ShipMasterEudoraScript:
    @staticmethod
    def deathrattle(source, game):
        is_permanent = source.is_golden
        actions = []
        for m in source.controller.get_board_minions():
            if not m.dead:
                actions.append(Buff(m,
                    atk=2, health=2, temporary=not is_permanent))
        return actions
```

### 12.22 Rally 传播（Rally Propagation）— ✅ Phase H

**自然语言**: "Rally: Give your other Beasts +{0} Attack and this Rally."

**模式**: 使用 `_script_overrides` 字典（每实体脚本覆盖）+ `GainKeyword` 将带函数的 Rally 关键词授予非原生 Rally 随从。

**已实现卡牌**:
| 卡牌 | 效果 | 机制 |
|------|------|------|
| `BG33_840` Stomping Stegodon | Rally 传播到其他 Beasts | `_script_overrides["rally"]` + `GainKeyword(RALLY)` |

```python
class StompingStegodonScript:
    @staticmethod
    def _propagated_rally(source, game):
        actions = []
        for m in source.controller.get_board_minions():
            if m is not source and not m.dead and m.race in (Race.BEAST, Race.ALL):
                actions.append(Buff(m, atk=1, health=0))
                actions.append(GainKeyword(m, GameTag.RALLY))
                m._script_overrides["rally"] = StompingStegodonScript._propagated_rally
        return actions
```

**引擎**: `entity.py:_call_script_method()` 优先查询 `_script_overrides` 字典，再回退到静态 `data.scripts`。

### 12.23 Refresh 追踪 + Fodder 授予 — ✅ Phase H

**自然语言**: "Battlecry: Add a Fodder to your next {0} Refreshes."

**模式**: 战吼设置计数器（`FODDER_REFRESH_REMAINING`）+ 注册 `TAVERN_REFRESH` 监听器，使用自包含 Action `AddFodderToRandomTavernMinion` 递减计数器并在随机酒馆随从上加 `FODDER` 关键词。

**已实现卡牌**:
| 卡牌 | 效果 | 基础计数 | 金色计数 |
|------|------|---------|---------|
| `BG35_150` Laboratory Assistant | Add Fodder to next N Refreshes | 3 | 6 |

```python
class LaboratoryAssistantScript:
    @staticmethod
    def battlecry(source, game):
        count = 6 if source.is_golden else 3
        source.set_tag(GameTag.FODDER_REFRESH_REMAINING, count)
        listener = EventListener(
            event_name="TAVERN_REFRESH",
            action=AddFodderToRandomTavernMinion(source.controller),
        )
        game.register_listener(source, listener)
        return None
```

**引擎 Action**: `AddFodderToRandomTavernMinion(player)` — 读取 `FODDER_REFRESH_REMAINING`，若 > 0 则递减并在随机酒馆随从上设置 `FODDER=True`。达到 0 时变为无操作。

---

## 13. 最新赛季机制（Season 13）

> Season 13 "CATACLYSM CALLS!" (Patch 35.2, 2026-04-06) 引入了两个新关键词和饰品系统回归。

### 13.1 Fodder（恶魔吞噬）— ✅ 已实现

**自然语言**: "Fodder: When you play this, consume a minion in your hand to gain its stats."

**关键词**: `FODDER=True` (GameTag 已定义)。`FodderConsume` Action 已实现，详见 [Section 12.12](#1212-吞噬fodderconsume)。

### 13.2 Chromadrake（龙变形）— ✅ Transform 已实现

**关键词**: `CHROMADRAKE=True` (GameTag 已定义)。`Transform` Action 已实现，可用于 Chromadrake 卡牌效果，详见 [Section 12.11](#1211-变形transform)。

### 13.3 酒馆 Buff 追踪 — ✅ 已实现

**自然语言**: "Battlecry: Give minions in the Tavern +X/+Y this game."

**Action**: `BuffTavern(player, atk=X, health=Y, race_filter=可选, max_tier=可选)` — 添加持久化 `TavernBuff` 到 `player.tavern_buffs`。每次 `refresh_tavern()` 时，新生成的随从自动应用匹配的 TavernBuff。

**已实现卡牌**:
| 卡牌 | 效果 | 实现状态 |
|------|------|---------|
| `EXAMPLE_TAVERN_BUFF` | +2/+2 全酒馆随从 | ✅ |
| `BG25_041` Felemental | +1/+1 全酒馆随从 | ✅ |
| `BG31_815` Dune Dweller | +1/+1 仅元素 | ✅ |
| `BG35_152` Void Pup Trainer | +2/+2 仅 T1-T3 | ✅ |
| `BG27_016` Champion of Sargeras | +2/+1 全酒馆随从 (BC & DR) | ✅ |

### 13.4 Improves 增强追踪 — ✅ 已实现

**自然语言**: "Start of Combat/Battlecry: Give a friendly minion +{0}/+{1}. Improves after X!"

**两种模式**:

1. **永久计数** (Ultraviolet Ascendant):
   - `on_summon` 注册 EventListener → 条件触发时 `IncrementImproveCounter(target)`
   - 计数器存储在卡牌的 `GameTag.IMPROVE_COUNTER`，整场游戏持久化
   - 效果读取 `1 + counter` 作为乘数

2. **回合快照** (Lovesick Balladist):
   - Battlecry 时直接读取 Player 的 `GameTag.GOLD_SPENT_THIS_TURN`
   - 每回合开始时重置，无需事件监听

**Action**: `IncrementImproveCounter(target, amount=1)` — 增加目标卡牌的 IMPROVE_COUNTER。

**事件**: `ELEMENTAL_PLAYED`（在 `game.summon()` 中广播）, `GOLD_SPENT`（在 `SpendGold.do()` 中广播）

**Self-exclusion**: `EventListener` 使用 `condition=lambda m, p: m != source` 防止卡牌自身召唤触发计数器。

**已实现卡牌**:
| 卡牌 | 效果 | 模式 | 状态 |
|------|------|------|------|
| `EXAMPLE_IMPROVE` | SoC: Give friendly minion +1/+2, Improves (Elemental) | 永久计数 | ✅ |
| `BG31_810` Ultraviolet Ascendant | SoC: Give other Elementals +1/+2, Improves (Elemental) | 永久计数 | ✅ |
| `BG26_814` Lovesick Balladist | BC: Give a Pirate +1/+2, Improved (Gold spent) | 回合快照 | ✅ |
| `BG32_822` Fire-forged Evoker | SoC: Give Dragons +{0}/+{1}, Improves (Tavern spell) | 永久计数 | ✅ |
| `BG35_702` Roving Sailor | BC: Give friendly minion +{0}/+{1}, Improved (Tavern spell) | 回合快照 | ✅ |

**状态**: 完整酒馆法术系统已实现 (Phase E): Spell 实体 + SpellPool + buy/play + CastTavernSpell + 折扣系统。

### 13.5 饰品（Trinkets）

饰品是装备在英雄身上的特殊物品，提供被动或触发效果。当前赛季在第 6 回合（Lesser）和第 9 回合（Greater）提供购买机会。

**实现状态**: 已实现 302/314 active 饰品脚本，覆盖 SoC buff、EoT buff、关键词赋予、Avenge、Spellcraft、Rally Doubler、BC Doubler、DR Doubler、Hero Power Doubler、金币获取、随从获取、法术获取、血宝石改善、酒馆 Buff 光环等主要机制。3 个空脚本为 UI-only timer 或 DEFERRED。

**脚本 hooks**: Trinket 脚本类支持以下 hooks（均为 classmethod/staticmethod，签名 `(source, game)` 或 `(source, game, **kwargs)`）：

| Hook | 触发时机 |
|------|---------|
| `on_summon` | 饰品装备时（购买/发现） |
| `start_of_combat` | 战斗开始时 |
| `start_of_turn` | 回合开始时 |
| `end_of_turn` | 回合结束时 |
| `on_buy` | 随从购买后 |
| `on_play` | 随从/法术打出后 |
| `avenge` | 复仇触发时 |
| `spellcraft` | 生成 Spellcraft 法术 |
| `on_spend_gold` | 花费金币后 |
| `on_magnetized` | 磁力吸附后 |
| `on_summon_in_combat` | 战斗中召唤后 |
| `on_friendly_death_combat` | 战斗中友方死亡后 |
| `on_tavern_refresh` | 酒馆刷新后 |
| `on_minion_bought` | 随从购买后 |
| `on_minion_sold` | 随从出售后 |
| `on_turn_begin` | 新回合开始时 |

**注册方式**: 饰品使用 `CardType.TRINKET` 注册，脚本类通过 `TRINKET_SCRIPT_REGISTRY` 映射：

```python
register_card(
    card_id="BG30_MagicItem_422",
    name="Lorewalker Scroll",
    text="Whenever you cast a spell on a minion, give it +4/+4.",
    cardtype=CardType.TRINKET,
    race=Race.NONE,
    tech_level=1,
    tags={GameTag.COST: 0},
    script_class=LorewalkerScrollLesserScript,
)
```

**EventListener 模式**: 部分饰品通过 `on_summon` 注册 EventListener 监听游戏事件（如 TAVERN_SPELL_CAST、AFTER_ATTACK、KEYWORD_LOST 等），而非直接使用 Trinket hook。这适用于事件驱动的触发效果。

---

## 13. 英雄与英雄技能注册

### 13.1 英雄与普通随从的区别

- 英雄使用 `cardtype=CardType.HERO`，英雄技能使用 `CardType.HERO_POWER`
- 英雄通过 `game.create_player(card_id)` 创建，返回 `Player` 实例
- 英雄技能脚本定义 `hero_power(source: Player, game: Game)` 静态方法
- 英雄卡牌和英雄技能卡牌共享同一个 `script_class`
- 英雄技能的 cost 通过 `HERO_POWER_COST` tag 存储

### 13.2 代码注册

实际注册分两步（英雄技能 + 英雄）：

```python
from hsrl.cards.heroes.scripts import HERO_POWER_SCRIPT_REGISTRY

# 步骤 1: 注册英雄技能卡牌
register_card(
    card_id="BG20_HERO_103p",
    name="Bloodbound",
    text="Hero Power (1): Give a random friendly minion +1/+1.",
    cardtype=CardType.HERO_POWER,
    tech_level=1,
    tags={GameTag.HERO_POWER_COST: 1},
    script_class=HERO_POWER_SCRIPT_REGISTRY["BG20_HERO_103p"],
)

# 步骤 2: 注册英雄卡牌（共享相同的 script_class）
register_card(
    card_id="BG20_HERO_103",
    name="Death Speaker Blackthorn",
    text="",
    cardtype=CardType.HERO,
    tech_level=1,
    tags={
        GameTag.BASE_HEALTH: 30,
        GameTag.ARMOR: 0,
        GameTag.HERO_POWER: "BG20_HERO_103p",
        GameTag.HERO_POWER_COST: 1,
    },
    script_class=HERO_POWER_SCRIPT_REGISTRY["BG20_HERO_103p"],
)
```

### 13.3 已注册的英雄与技能

| 类型 | Card ID | 名称 | 费用 | 状态 |
|------|---------|------|------|------|
| 示例英雄 | `EXAMPLE_HERO` | Example Hero | 0 | ACTIVE |
| 示例技能 | `EXAMPLE_HERO_POWER_BUFF` | +1/+1 Buff | 0 | ACTIVE |
| 示例技能 | `EXAMPLE_HERO_POWER_GOLD` | Gain 2 Gold | 2 | ACTIVE |
| 示例技能 | `EXAMPLE_HERO_POWER_MULTI` | Beasts +2 ATK | 1 | ACTIVE |
| 真实英雄 | `BG20_HERO_103` | Death Speaker Blackthorn | 1 | ACTIVE |
| 真实技能 | `BG20_HERO_103p` | Bloodbound | 1 | ACTIVE |
| 真实英雄 | `BG20_HERO_100` | Rokara | 0 | ACTIVE (被动框架) |
| 真实技能 | `BG20_HERO_100p` | Glory of Combat | 0 | ACTIVE (Phase II KILLER追踪) |
| 真实英雄 | `BG20_HERO_101` | Xyrella | 2 | ACTIVE |
| 真实技能 | `BG20_HERO_101p` | See the Light | 2 | ACTIVE |

---

## 14. 测试要求

### 12.1 每个新卡牌的最低测试要求

| 卡牌类型 | 必测场景 |
|---------|---------|
| 白板 | 属性正确、种族正确 |
| 关键词 | 关键词生效、关键词交互 |
| 战吼 | 打出时触发、效果正确 |
| 亡语 | 死亡时触发、召唤物位置正确 |
| 复仇 | 计数正确、阈值触发、多次触发 |
| Rally | 攻击宣告时触发（伤害前）、目标正确、效果叠加 |
| 战斗开始时 | 战斗前触发、目标选择正确 |
| End of Turn | 招募阶段结束时触发、效果正确、多次触发叠加 |
| Start of Turn | 招募阶段开始时触发、效果正确 |
| On Sell | 出售时触发、效果正确 |
| Transform | 变形后卡牌正确、保留 buff、保留 Golden |
| Fodder | 吞噬正确、增益正确（max_health）、手牌减少 |
| Spellcraft | 生成法术正确、未被使用法术自动清理 |
| Chromadrake | 条件满足时变形、条件不满足时不变 |
| 英雄技能 (主动) | 属性正确、费用扣除、效果正确、同回合不可重复使用、金币不足时阻塞 |
| 英雄技能 (被动) | on_summon 注册监听器、事件触发时效果正确 |
| 饰品 | 购买后生效、触发时机正确 |
| 复杂效果 | 每个子效果单独测试 + 组合测试 |

### 12.2 测试模板

```python
class TestMyNewCard(unittest.TestCase):
    def setUp(self):
        self.game = Game([])
        self.game.card_db = CARDS
        self.player = Player(CARDS.get("HERO_EXAMPLE"), game=self.game)
        self.game.players.append(self.player)

    def test_effect_scenario(self):
        minion = self.game.create_minion("BGS_MY_NEW_CARD")
        self.game.summon(self.player, minion)
        
        # 触发效果...
        # 断言状态...
```

### 12.3 测试运行

```bash
cd HSRL
python -m pytest hsrl/tests/ -v
```

---

## 附录：Card ID 命名规范

| 前缀 | 含义 | 示例 |
|------|------|------|
| `BGS_` | 标准酒馆战棋随从 | `BGS_001` |
| `HERO_` | 英雄 | `HERO_001` |
| `HP_` | 英雄技能 | `HP_001` |
| `SPELL_` | 法术/鲜血宝石 | `SPELL_BLOOD_GEM` |
| `REWARD_` | 三连奖励/任务奖励 | `REWARD_TRIPLE` |
| `TOKEN_` | 衍生物 | `TOKEN_1_1_BEAST` |
| `TRINKET_` | 饰品 | `TRINKET_VALOROUS_MEDALLION` |
| `EXAMPLE_` | 标准示例 | `EXAMPLE_TAUNT` |

---

*文档版本：1.0.0 | 最后更新：2026-05-01*
