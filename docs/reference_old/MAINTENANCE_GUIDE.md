# 酒馆战棋模拟器 (HrSRL) 维护更新 Agent 总指南

> **目标读者**：用于维护和更新 HrSRL 酒馆战棋模拟器的 AI Agent。
> **最后更新**：2026-06-03
> **当前基线版本**：Patch 35.6.0.243002

---

## 目录

1. [模拟器架构与实现逻辑](#1-模拟器架构与实现逻辑)
2. [关键 API 规范](#2-关键-api-规范)
3. [数据更新与读取逻辑 (hsdata)](#3-数据更新与读取逻辑-hsdata)
4. [从官方交叉验证版本与内容](#4-从官方交叉验证版本与内容)
5. [维护工作流清单](#5-维护工作流清单)
6. [常见问题与排错](#6-常见问题与排错)

---

## 1. 模拟器架构与实现逻辑

### 1.1 整体架构层次

```
┌─────────────────────────────────────────────────────────────────┐
│  RL 环境层 (hsrl/env/)                                          │
│  Discrete(50) 动作空间 + 374-dim 观察 + 多智能体环境               │
├─────────────────────────────────────────────────────────────────┤
│  Agent 层 (hsrl/agents/)                                        │
│  SearchAgent / AZ MCTS Agent / Heuristic                        │
├─────────────────────────────────────────────────────────────────┤
│  游戏引擎核心 (hsrl/core/)                                       │
│  Game → Action Queue → Entity System → Event Broadcast           │
├─────────────────────────────────────────────────────────────────┤
│  卡牌定义 (hsrl/cards/)                                          │
│  minions/ heroes/ spells/ trinkets/ rewards/ anomalies/          │
├─────────────────────────────────────────────────────────────────┤
│  数据层 (data/*.json + hsdata/CardDefs.xml)                      │
│  卡牌数据库 JSON → CardDB 注册 → MinionPool/SpellPool             │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 游戏主循环 (game.py)

`Game` 类是模拟器的核心，管理完整的游戏生命周期。关键成员变量：

| 变量 | 类型 | 说明 |
|------|------|------|
| `turn` | `int` | 当前回合 (1-based) |
| `step` | `Step` | 当前阶段枚举 |
| `state` | `State` | RUNNING 或 COMPLETE |
| `players` | `List[Player]` | 所有玩家 (含已淘汰) |
| `rng` | `random.Random` | 全局可控随机数生成器 |
| `minion_pool` | `MinionPool` | 共享随从池 (延迟初始化) |
| `spell_pool` | `SpellPool` | 共享法术池 (延迟初始化) |
| `active_tribes` | `Optional[set]` | 本局可用种族 (None=全部) |
| `active_anomaly` | `Optional[Anomaly]` | 本局异变实体 |

#### 阶段状态机

```
Step.INVALID (0)
  └─→ Step.RECRUIT (2) ──→ Step.END_RECRUIT (3)
         ↑                        │
         │                        ↓
         │              Step.BEGIN_COMBAT (4)
         │                        │
         │                        ↓
         │              Step.COMBAT (5)
         │                        │
         │                        ↓
         └──────── Step.END_COMBAT (6)
```

详细的阶段流转：

1. **`_start_recruit_phase()`** → 设置 `step = RECRUIT`
   - 处理延迟动作和回合调度回调
   - 广播 `RECRUIT_BEGIN`、`TURN_BEGIN`
   - 对每个存活玩家：饰品回合开始触发、重置技能使用标记、清空回合计数器
   - 第 6 回合提供次级饰品、第 9 回合提供高级饰品
   - 第 4 回合提供任务
   - 加金币：`min(3 + turn - 1, 10)`
   - 降低酒馆升级费用 (每次 -1)
   - 触发回合开始效果 (异变 → 饰品 → 随从)
   - 生成 Spellcraft 法术
   - 自动刷新酒馆 (保留冻结随从，冻结随从获得 +2/+1)

2. **`end_recruit_phase()`** → 设置 `step = END_RECRUIT`
   - 触发回合结束效果 (饰品 → 随从)
   - 清除临时 buff (`.temporary=True`)
   - 清除临时亡语 (`TEMPORARY_DEATHRATTLE`)
   - 清理未使用的 Spellcraft 法术
   - 广播 `TURN_END`、`RECRUIT_END`
   - 调用 `_start_combat_phase()`

3. **`_start_combat_phase()`** → 设置 `step = COMBAT`
   - 快照每个存活玩家的棋盘 (`last_combat_board`)
   - 贪心配对 (避免与前 2 轮重复)
   - 对每对执行 `_run_combat()` 或 `_run_ghost_combat()`

4. **`_end_combat_phase()`** → 设置 `step = END_COMBAT`
   - 广播 `END_OF_COMBAT`、`COMBAT_END`
   - 填充伙伴计量槽
   - 归还战斗召唤随从
   - 清除临时 buff
   - 清理棋盘和墓地
   - `_check_game_over()` → 如 ≤1 存活，设置 `State.COMPLETE`
   - 否则 `turn += 1`，回到 `_start_recruit_phase()`

### 1.3 Action 系统 (actions.py)

**这是模拟器最核心的设计模式。所有状态变更必须通过 Action 对象执行。**

#### Action 基类

```python
class Action:
    def trigger(self, source, game, target=None):
        self.do(source, game, target)            # 执行实际状态变更
        for action in self._then:                 # 链式执行后续动作
            action.trigger(source, game, target)
```

#### Action Queue 生命周期

```
queue_action(action, source, target)
  → _action_queue.append((action, source, target))
  → resolve_queue()
      → _resolve_queue(_wave=0)
          → pop (action, source, target)
          → action.trigger(source, game, target)
          → _check_deaths()          ← 每个 Action 后都检查死亡
              → 处理亡语、复生、复仇
              → _resolve_queue() 递归 (wave+1)
```

**关键安全限制**：
- `_MAX_DEATH_WAVES = 20`：防止无限死亡递归
- `_MAX_ACTIONS_PER_RESOLVE = 5000`：防止无限动作循环
- 每次 Action 后立即执行 `_check_deaths()`，确保亡语/复生/复仇的准确触发顺序

#### 主要 Action 类别

| 类别 | 代表 Action | 说明 |
|------|-----------|------|
| **战斗** | `Attack`, `Hit`, `Destroy`, `AttackImmediately` | 战斗核心逻辑 |
| **召唤/打出** | `Summon`, `PlayMinion`, `Reborn` | 随从进场 |
| **关键词/Buff** | `Buff`, `GainKeyword`, `Silence`, `GiveKeyword`, `GainDeathrattle` | 属性修改 |
| **光环** | `ApplyGlobalAura`, `BuffTavern` | 持久光环 |
| **经济** | `SpendGold`, `GainGold`, `UpgradeTavern`, `UseHeroPower` | 资源操作 |
| **血宝石** | `PlayBloodGems`, `ImproveBloodGem`, `GetBloodGem` | 野猪人机制 |
| **发现/选择** | `DiscoverMinion`, `DiscoverSpell`, `ChooseOne` | 三选一 |
| **变形** | `Transform`, `FodderConsume`, `ConsumeTavernMinion` | 随从替换 |
| **酒馆** | `FreezeTavernMinion`, `UpgradeTavernMinionTier` | 酒馆操作 |

#### Hit (伤害结算) 的精确语义

```
Hit.do(source, target, amount):
  1. BEFORE_HIT 广播
  2. 圣盾检查 → 有圣盾且完好？挡掉全部伤害，移除圣盾，返回
  3. target.health -= amount
  4. DAMAGE / MINION_DAMAGED 广播
  5. 剧毒检查 → 造成伤害(>0) → 目标死亡
  6. 烈毒检查 → 造成伤害(>0) 且来源存活 → 目标死亡，来源失去烈毒
  7. AFTER_HIT 广播
```

#### Attack (攻击) 的精确语义

```
Attack.do(attacker, defender):
  1. BEFORE_ATTACK 广播
  2. MINION_ATTACKED 广播
  3. Rally 触发 (攻击者的 Rally 效果，在伤害前)
  4. Hit(defender, attacker.atk) ← 攻击方打防守方
  5. Cleave 检查 → Hit(相邻随从, attacker.atk)
  6. Hit(attacker, defender.atk) ← 防守方反击 (如果在排队时活着)
  7. 风怒/消耗状态更新
  8. AFTER_ATTACK 广播
```

**关键设计：同时伤害语义。** 防守方的 `Hit` 在 `Attack.do()` 时就加入队列（而非执行时判断），因此即使防守方被攻击方击杀，其反击仍会执行。这是通过 FIFO 队列实现的正确结算。

### 1.4 Entity 系统 (entity.py)

#### BaseEntity — 一切游戏对象的基类

```python
class BaseEntity:
    tags: Dict[GameTag, Any]           # 所有可见状态的唯一来源
    data: CardData                      # 不可变的模板/蓝图
    uuid: str                           # 运行时唯一标识
    controller: Optional[Player]        # 所属玩家
    _buffs: List[BuffEnchantment]       # 活跃 buff 列表
    _script_overrides: Dict[str, Any]   # 运行时注入的脚本方法
    _events: List[EventListener]        # 实体级事件监听
```

**核心设计原则**：
- `tags` 是所有可见状态的唯一来源 (single source of truth)
- `atk` 和 `health` 是**计算属性** (非缓存值)，每次访问时动态计算：基础值 + buffs 总和 + 全局光环 + 异变加成 + 脚本覆盖
- `snapshot()` 和 `restore_snapshot()` 用于 MCTS 前向模拟的完美回滚

#### CardData — 不可变卡牌模板

```python
@dataclass(frozen=True)
class CardData:
    id: str                    # 卡牌 ID (如 "BG19_010")
    name: str                  # 显示名称
    text: str                  # 卡牌文本
    cardtype: CardType         # 卡牌类型枚举
    race: Race                 # 种族枚举
    tech_level: int            # 酒馆等级
    rarity: Rarity             # 稀有度
    tags: Dict[GameTag, Any]   # 初始标签
    scripts: Optional[Type]    # 脚本类 (行为定义)
```

### 1.5 卡牌脚本系统

#### 注册流程

```
data/bg_pool_minions.json
  → hsrl/cards/minions/pool.py (auto-register loop)
      → _get_script(): SCRIPT_REGISTRY 优先，JSON flags 兜底
      → register_card(id, name, text, cardtype, race, tech_level, rarity, tags, script_class)
          → CARDS._cards[id] = CardData(...)
```

#### 脚本类模式

每个脚本类是一个普通 Python 类，使用 `@staticmethod` 或 `@classmethod` 定义效果方法：

```python
class SomeMinionScript:
    """Natural language: <官方卡牌文本>
    Formal spec:
      1. <精确操作步骤>
      2. <精确操作步骤>
    Test: <如何验证>
    """
    @staticmethod
    def battlecry(source, game):
        return Buff(source, atk=2, health=2)
```

**强制规范**：
- 每个脚本类必须使用**三段式文档注释** (Natural language / Formal spec / Test)
- 卡牌只有 **CORRECT** 或 **DEFERRED** 两种状态，禁止 "简化实现"
- DEFERRED 卡牌方法返回 `None`，文档注释中标注 `Status: DEFERRED` 和 `Dependency`

#### 各类型钩子方法

| 卡牌类型 | 可用钩子 |
|---------|---------|
| **Minion** | `battlecry`, `deathrattle`, `start_of_combat`, `avenge`, `rally`, `end_of_turn`, `start_of_turn`, `on_sell`, `on_summon`, `spellcraft` |
| **Hero Power** | `hero_power(source, game)` (source = Player) |
| **Spell** | `on_play` |
| **Trinket** | `start_of_combat`, `end_of_turn`, `on_buy`, `on_summon`, `avenge`, `spellcraft`, `on_play`, `on_spend_gold` 等 |
| **Quest Reward** | `on_unlock`, `on_summon`, `start_of_combat`, `end_of_turn` |
| **Anomaly** | `on_apply`, `start_of_combat`, `start_of_turn`, `on_upgrade` |

### 1.6 战斗系统

#### 战斗循环

```
_run_combat(p1, p2):
  1. 保存原始棋盘/墓地
  2. 深拷贝创建战斗克隆 (tags, buffs, script_overrides；清除事件监听器)
  3. 清空墓地，重置战斗状态
  4. 触发 Start of Combat (异变 → 饰品 → 随从)
  5. 确定先手：随从多的一方；平手则随机
  6. 战斗循环 (最多 1000 轮)：
     a. _get_next_attacker(): 最左侧存活、攻击力>0、未消耗的随从
     b. _choose_attack_target(): 有嘲讽优先嘲讽，否则随机存活目标
     c. queue + resolve Attack(attacker, target)
     d. 交换攻守方
     e. 检查一方全灭 → 退出循环
  7. 计算伤害：攻击方酒馆等级 + 存活随从酒馆等级之和
  8. 施加伤害上限
  9. 恢复原始棋盘/墓地
```

#### 死亡处理

```
_check_deaths():
  对每个新死亡的随从 (health <= 0):
    1. 广播 BEFORE_DESTROY, DEATH
    2. 加入战斗死亡日志
    3. 触发 Reborn (在亡语之前)
    4. 触发 Deathrattle (递增 DEATHRATTLE_TRIGGERED)
    5. 递增 Avenge 计数器
    6. 分发饰品 on_friendly_death_combat
    7. 从棋盘移除，加入墓地
  递归调用 _resolve_queue(wave+1)
```

### 1.7 随从池与酒馆系统

#### MinionPool

- 池大小: T1=16, T2=15, T3=13, T4=11, T5=9, T6=7, T7=5 份/每种
- 排除 EXAMPLE_, TOKEN_, BGDUO_, _G (金色), _t (token) 卡牌
- 种族过滤：`Race.ALL` 始终匹配，`Race.NONE` 仅当无过滤时匹配

#### SpellPool

- 每种法术 1 份 (不重复)
- 使用后归还池中 (可重新出现)

#### 酒馆刷新

```
refresh_tavern(player):
  1. 清除当前酒馆 (除了冻结的)
  2. 冻结随从获得 +2/+1
  3. 按等级抽取 minions_per_tavern[tier] 个随从 + 1 个法术
  4. 创建实体，应用 TavernBuff
```

#### Triple 系统

```
_check_for_triple(player, entity):
  - 扫描手牌+棋盘，找 3 张相同非金色 card_id
  - PIRATES_NEED_2_COPIES 时只需 2 张
  - Elemental of Surprise 可使用任意元素

_combine_triple(player, copies):
  1. 移除 3 张 → SETASIDE
  2. 创建金色 (2x 基础身材)
  3. 合并 buffs
  4. TRIPLE_REWARD_TIER = min(tier+1, 6)
  5. 加入手牌
```

---

## 2. 关键 API 规范

### 2.1 Game 类公开方法

| 方法 | 签名 | 说明 |
|------|------|------|
| `create_game` | `(hero_ids, card_db, seed) → Game` | 工厂方法，创建游戏、初始化池、调用 start_game() |
| `run_game` | `(hero_ids, card_db, max_turns) → Game` | 便捷方法：create + run 完整游戏 |
| `start_game` | `() → None` | 应用异变、选择种族、分配伙伴、开始第一个招募阶段 |
| `run_full_game` | `(max_turns=None) → Optional[Player]` | 运行直到结束或达到最大回合数 |
| `buy_minion` | `(player, minion) → None` | 从酒馆购买随从到手牌 |
| `sell_minion` | `(player, minion) → None` | 出售随从 (获得金币, 触发 on_sell, 归还池中) |
| `play_minion` | `(player, minion, position, magnetic_target=None) → None` | 从手牌打出随从 |
| `play_spell` | `(player, spell) → None` | 施放酒馆法术 |
| `use_hero_power` | `(player) → None` | 使用英雄技能 |
| `refresh_tavern` | `(player, preserve_frozen=True) → None` | 刷新酒馆 |
| `queue_action` | `(action, source, target=None) → None` | 将动作加入队列 |
| `resolve_queue` | `() → None` | 处理所有队列中的动作 |
| `broadcast` | `(event_name, *args) → None` | 向所有注册的监听器发送事件 |
| `snapshot_player_state` | `(player) → dict` | 深保存玩家状态 (MCTS) |
| `restore_player_state` | `(player, saved) → None` | 恢复玩家状态 (MCTS) |
| `get_board` | `(player) → List[Minion]` | 获取玩家棋盘 |
| `get_living_enemies` | `(player) → List[Minion]` | 获取所有存活敌方随从 |
| `get_current_combat_opponent` | `(player) → Optional[Player]` | 获取当前战斗对手 |
| `init_pool` | `() → None` | 延迟初始化 MinionPool 和 SpellPool |

### 2.2 Action 类构建器模式

```python
# 链式调用
GainGold(player, 3).then(
    Buff(minion, atk=2, health=2)
).then(
    Summon(player, token)
)

# 条件动作
TargetedAction(
    filter_fn=lambda m: m.race == Race.BEAST,
    action_factory=lambda target: Buff(target, atk=3, health=3),
    label="Buff a Beast"
)
```

### 2.3 事件系统

#### 注册监听器

```python
game.register_listener(entity, EventListener(
    event_name=DEATH,
    action=Buff(self, atk=1, health=0),
    condition=lambda e, g, t: t.race == Race.MECH,
    once=False
))
```

#### 主要事件常量

| 事件 | 触发时机 |
|------|---------|
| `BEFORE_ATTACK`, `AFTER_ATTACK` | 攻击前后 |
| `BEFORE_HIT`, `AFTER_HIT` | 伤害前后 |
| `DAMAGE`, `MINION_DAMAGED` | 造成伤害 |
| `BEFORE_DESTROY`, `DEATH` | 随从死亡 |
| `DEATHRATTLE_TRIGGER`, `REBORN_TRIGGER` | 亡语/复生触发 |
| `SUMMON`, `MINION_PLAYED` | 召唤/打出随从 |
| `BUFF`, `KEYWORD_GAINED`, `KEYWORD_LOST` | Buff/关键词变更 |
| `TAVERN_UPGRADED`, `GOLD_SPENT`, `MINION_BOUGHT`, `MINION_SOLD` | 经济操作 |
| `TURN_BEGIN`, `TURN_END`, `COMBAT_BEGIN`, `COMBAT_END` | 回合/战斗边界 |
| `DIVINE_SHIELD_LOST`, `POISON_KILL`, `VENOM_KILL` | 关键词交互 |

### 2.4 枚举值参考

#### GameTag (关键标签)

| 组别 | GameTag | 值 | 说明 |
|------|---------|---|------|
| Identity | NAME, CARD_ID, ENTITY_ID | 3, 8, 9 | 身份标识 |
| Combat | ATK, HEALTH, MAX_HEALTH, DAMAGE | 20-23 | 战斗属性 |
| Economy | COST, GOLD, MAX_GOLD | 30, 31, 32 | 经济 |
| Keywords | TAUNT, DIVINE_SHIELD, POISONOUS, VENOMOUS | 50-53 | 攻击关键词 |
| Keywords | REBORN, WINDFURY, CLEAVE, MAGNETIC | 54-58 | 复活/攻击关键词 |
| Keywords | BATTLECRY, DEATHRATTLE, Avenge, RALLY | 60-65 | 触发关键词 |
| State | FROZEN, EXHAUSTED, SILENCED | 70-72 | 状态 |
| Tavern | TAVERN_TIER, TAVERN_UPGRADE_COST | 110-111 | 酒馆 |
| Bonuses | BATTLECRY_DOUBLED, DEATHRATTLE_DOUBLED | 120-121 | 双倍光环 |
| Bonuses | START_OF_COMBAT_DOUBLED, END_OF_TURN_DOUBLED | 122-123 | 双倍光环 |
| Blood Gem | BLOOD_GEM_BONUS_ATK, BLOOD_GEM_BONUS_HEALTH | 130-131 | 血宝石加成 |

#### Race → DBF ID 映射 (DBF_RACE_TO_ENUM)

```python
{
    None: Race.NONE,     # 12
    11:   Race.UNDEAD,   # 10
    14:   Race.MURLOC,   # 6
    15:   Race.DEMON,    # 2
    17:   Race.MECH,     # 5
    18:   Race.ELEMENTAL,# 4
    20:   Race.BEAST,    # 1
    23:   Race.PIRATE,   # 8
    24:   Race.DRAGON,   # 3
    26:   Race.ALL,      # 11
    43:   Race.QUILBOAR, # 9
    92:   Race.NAGA,     # 7
}
```

### 2.5 CardDB 注册 API

```python
from hsrl.core.card_db import register_card
from hsrl.core.enums import CardType, Race, Rarity, GameTag

register_card(
    card_id="BGXX_001",           # 卡牌ID (必须与官方CardDefs.xml一致)
    name="Card Name",              # 显示名称
    text="[x]<b>Battlecry:</b> Give a friendly minion +2/+2.",  # 官方文本
    cardtype=CardType.MINION,      # 卡牌类型
    race=Race.BEAST,               # 种族
    tech_level=3,                  # 酒馆等级
    rarity=Rarity.COMMON,          # 稀有度
    tags={
        GameTag.BASE_ATK: 3,
        GameTag.BASE_HEALTH: 4,
        GameTag.BATTLECRY: True,   # 有战吼
    },
    script_class=SomeScriptClass,   # 行为脚本
)
```

---

## 3. 数据更新与读取逻辑 (hsdata)

### 3.1 数据文件结构

```
hsdata/                              # Git 子模块 (HearthSim 官方数据)
├── CardDefs.xml                     # 主数据库 (103MB, 34,954 个 Entity)
│   └── <Entity CardID="..." ID="..."> 元素
│       └── <Tag enumID="..." name="..." value="..."/>
├── Strings/                         # 14 种语言本地化
│   ├── enUS/, zhCN/, zhTW/, ...
├── RaceTagMap.xml                   # 种族名称 → XML 标签号映射
└── README.md                        # 版本号 (当前: 35.6.0.243002)

data/                                # 预处理 JSON (从 CardDefs.xml 派生)
├── bg_cards.json                    # 全量 5,189 张 BG 卡牌
├── bg_pool_minions.json             # 可购买随从池 (270 张)
├── bg_pool_spells.json              # 可购买法术池 (71 张)
├── bg_tavern_spells.json            # 全量酒馆法术 (200 张)
├── bg_heroes.json                   # 英雄 (119 位)
├── bg_hero_powers.json              # 英雄技能 (164 个)
├── bg_trinkets.json                 # 饰品 (326 个)
├── bg_anomalies.json                # 异变 (104 个)
├── bg_quest_rewards.json            # 任务奖励 (73 个)
├── bg_summary.json                  # 汇总统计 + 版本号
├── pool_minion_texts.json           # 随从文本 (card_id → 卡牌文本)
└── pool_trinket_texts.json          # 饰品文本 (card_id → wiki 数据)
```

### 3.2 hsdata 子模块

hsdata 是 HearthSim 项目的 Git 子模块，包含从 Hearthstone 游戏客户端提取的 `CardDefs.xml`。

**当前状态**：子模块已克隆但可能未在 `.gitmodules` 中注册。目录存在于 `hsdata/`。

**更新 hsdata 的方法**：

```bash
# 方法 1: 通过 git submodule
cd /home/glt/HrSRL
git submodule update --remote hsdata

# 方法 2: 手动更新 (如果上述失败)
cd hsdata
git pull origin master
# 或从 HearthSim/hsdata 仓库重新克隆
```

**版本号来源**：
- `hsdata/README.md` → 当前 CardDefs.xml 的版本 (如 `35.6.0.243002`)
- `data/bg_summary.json` → JSON 文件的生成版本 (如 `35.6.0.243002`)

> **注意**：`hsdata/README.md` 和 `bg_summary.json` 中的版本号**通常不一致**，因为 JSON 文件是手动重新生成的，可能滞后于 hsdata 更新。

### 3.3 CardDefs.xml 关键标签映射

| XML enumID | 名称 | 类型 | 说明 |
|-----------|------|------|------|
| 45 | HEALTH | Int | 基础生命值 |
| 47 | ATK | Int | 基础攻击力 |
| 48 | COST | Int | 费用 |
| 144 | CARDRACE | Int | 种族 (DBF ID) |
| 183 | CARD_SET | Int | 1453 = Battlegrounds |
| 184 | CARDTEXT | LocString | 卡牌文本 |
| 185 | CARDNAME | LocString | 卡牌名称 |
| 202 | CARDTYPE | Int | 3=Hero, 4=Minion, 6=Enchant, 10=HeroP, 40=Reward, 42=Spell, 43=Anomaly, 44=Trinket |
| 380 | HERO_POWER | Int | 英雄技能 ID (DBF 引用) |

### 3.4 从 CardDefs.xml 生成 JSON 数据

**当前状态**：项目中没有自动化生成脚本。JSON 文件是外部生成的（可能使用 HearthstoneJSON 或自定义管道），并直接提交到仓库。

**生成步骤**（需要实现自动化时）：

1. 解析 `hsdata/CardDefs.xml`
2. 过滤 `CARD_SET == 1453` (Battlegrounds) 的所有 Entity
3. 按 `CARDTYPE` 分类：
   - `4` (Minion) → `bg_pool_minions.json` (需要额外过滤 is_pool_minion)
   - `42` (Spell) → `bg_pool_spells.json`
   - `3` (Hero) → `bg_heroes.json`
   - `10` (Hero Power) → `bg_hero_powers.json`
   - `44` (Trinket) → `bg_trinkets.json`
   - `43` (Anomaly) → `bg_anomalies.json`
   - `40` (Reward) → `bg_quest_rewards.json`
4. 对每张卡提取：`id`, `dbf_id`, `name`, `card_type`, `card_race`, `tech_level`, `atk`, `health`, `cost`, 关键词 flag
5. 同时提取 `CARDTEXT` (从 `enUS` 本地化) 生成 `pool_minion_texts.json`
6. 更新 `bg_summary.json` 中的版本号和统计数据

### 3.5 数据读取路径

```
hsrl/cards/__init__.py → init_cards()
  ├── import hsrl.cards.minions.pool       # 读 bg_pool_minions.json + pool_minion_texts.json
  ├── import hsrl.cards.minions.scripts    # 读 Python SCRIPT_REGISTRY
  ├── import hsrl.cards.minions.tokens     # 注册 token 随从
  ├── import hsrl.cards.heroes.pool        # 读 bg_heroes.json + CardDefs.xml (Tag 380)
  ├── import hsrl.cards.heroes.scripts     # 读 HERO_POWER_SCRIPT_REGISTRY
  ├── import hsrl.cards.spells.scripts     # 读 bg_pool_spells.json
  ├── import hsrl.cards.trinkets.scripts   # 读 bg_trinkets.json + pool_trinket_texts.json
  ├── import hsrl.cards.rewards.scripts    # 读 bg_quest_rewards.json
  └── import hsrl.cards.anomalies.scripts  # 读 bg_anomalies.json
```

唯一在运行时解析 `CardDefs.xml` 的模块是 `hsrl/cards/heroes/pool.py`，用于：
1. 构建 `{hero_card_id: hero_power_dbf_id}` 映射 (Tag `enumID=380`)
2. 构建 `{card_id: cost}` 映射 (Tag `enumID=32` 或 `48`)

---

## 4. 从官方交叉验证版本与内容

### 4.1 版本号验证

#### 步骤 1：获取官方当前版本号

```bash
# 方法 A: 从 hsdata 读取
cat /home/glt/HrSRL/hsdata/README.md
# 输出: 35.6.0.243002

# 方法 B: 检查 bg_summary.json
python3 -c "import json; print(json.load(open('data/bg_summary.json'))['patch'])"
# 输出: 35.6.0.243002
```

#### 步骤 2：交叉验证官方最新版本

通过以下官方渠道确认当前赛季和版本：

1. **Hearthstone 官方补丁说明**：访问 `https://hearthstone.blizzard.com/en-us/news` 获取最新补丁说明
2. **Hearthstone Wiki**：访问 `https://hearthstone.wiki.gg/wiki/Battlegrounds` 确认赛季主题和版本
3. **HearthSim 数据仓库**：检查 `https://github.com/HearthSim/hsdata` 的最新提交，确认最新的 CardDefs.xml 版本
4. **GitHub HearthstoneJSON**：访问 `https://github.com/HearthSim/hs-bg-card-json` 等自动化卡牌数据库仓库
5. **PlayHearthstone 官方新闻**：访问 `https://playhearthstone.com/en-us/news` 获取赛季更新公告
6. **酒馆战棋官方公告**：通过 `https://hearthstone.blizzard.com/en-us/battlegrounds` 了解当前赛季机制

#### 步骤 3：版本号解读

版本号格式：`{major}.{minor}.{patch}.{build}`

- 如 `35.6.0.243002`：
  - `35.4.2` = 游戏版本 (扩展包 + 大补丁 + 小补丁)
  - `242566` = 内部构建号

#### 步骤 4：判断是否需要更新

| 情况 | 动作 |
|------|------|
| `hsdata/README.md` 版本 > `bg_summary.json` 版本 | 需要重新生成 JSON 数据文件 |
| 官方最新版本 > `hsdata/README.md` 版本 | 需要更新 hsdata 子模块 + 生成 JSON |
| 有新的赛季机制 | 需要评估引擎改动范围 |
| 有新的随从/英雄/法术 | 需要注册新卡牌 + 编写脚本 |

### 4.2 随从池验证

#### 步骤 1：从官方获取当前池

官方数据来源：
1. **Hearthstone Wiki Battlegrounds Minion 页面**：`https://hearthstone.wiki.gg/wiki/Battlegrounds/Minion`
   - 按酒馆等级分组，列出所有可用随从及其效果文本
2. **CardDefs.xml**：过滤 `CARD_SET=1453, CARDTYPE=4` 的所有 Entity
   - 使用 `bg_pool_minions.json` 的 `is_pool_minion` 字段判断是否在池中
3. **第三方数据 API** (如 hs-bg-card-json) 自动追踪池变化

#### 步骤 2：对比差异

```bash
# 获取当前模拟器中已注册的池随从数
python3 -c "
import json
d = json.load(open('data/bg_pool_minions.json'))
print(f'Pool minions: {len(d)}')
# 按等级分组
from collections import Counter
tiers = Counter(m['tech_level'] for m in d)
for t in sorted(tiers):
    print(f'  Tier {t}: {tiers[t]}')
"
```

#### 步骤 3：检查移除和新增

对比补丁说明中列出的变动：
- **移除的随从**：从 `bg_pool_minions.json` 和 `minions/pool.py` 中移除
- **新增的随从**：添加到 `bg_pool_minions.json`、`pool_minion_texts.json`，在 `minions/scripts.py` 编写脚本类
- **数值调整**：更新 `bg_pool_minions.json` 中的 atk/health/tech_level 值
- **效果重做**：更新对应的脚本类实现

### 4.3 法术池验证

同样流程，通过 `bg_pool_spells.json` 和 `bg_tavern_spells.json` 管理。

```bash
# 获取当前法术池概况
python3 -c "
import json
d = json.load(open('data/bg_pool_spells.json'))
print(f'Pool spells: {len(d)}')
from collections import Counter
tiers = Counter(s['tech_level'] for s in d)
for t in sorted(tiers):
    print(f'  Tier {t}: {tiers[t]}')
"
```

### 4.4 英雄与英雄技能验证

数据来源：
1. `data/bg_heroes.json` — 英雄定义（名称、血量、护甲、dbf_id）
2. `data/bg_hero_powers.json` — 英雄技能定义（名称、费用、效果文本）
3. `hsrl/cards/heroes/pool.py` — 运行时从 CardDefs.xml 解析技能映射
4. `hsrl/cards/heroes/scripts.py` + `HERO_POWER_SCRIPT_REGISTRY` — 技能脚本实现

验证流程：
1. 确认英雄列表与官方一致（数量、名称、护甲值）
2. 确认每个英雄的技能映射正确（`Tag 380` 关系）
3. 确认技能脚本实现正确（费用、效果、目标选择、使用限制）
4. 检查英雄是否有护甲 tier 更新 (护甲值随平衡补丁变化)

### 4.5 赛季机制验证

酒馆战棋赛季结构：
- **赛季 13 "Cataclysm Calls"** (当前)：
  - **伙伴系统**：伙伴计量槽增长、购买时机、金色伙伴
  - **饰品系统**：次级饰品 (T6) + 高级饰品 (T9)
  - **异变系统**：每局随机异变修改全局规则

验证要点：
- 确认当前赛季的所有专属机制是否正确实现
- 检查 `hsrl/core/game.py` 中对应的阶段触发代码
- 检查 `hsrl/cards/trinkets/` 和 `hsrl/cards/anomalies/` 的完整性

### 4.6 关键词与战斗机制验证

#### 验证清单

| 关键词 | 验证要点 | 代码位置 |
|--------|---------|---------|
| Taunt | `_choose_attack_target()` 优先选择嘲讽 | `game.py` |
| Divine Shield | `Hit.do()` 挡掉首次伤害 | `actions.py` |
| Poisonous | 造成伤害后直接击杀 | `actions.py:Hit.do()` |
| Venomous | 造成伤害后击杀，一次性消耗 | `actions.py:Hit.do()` |
| Reborn | 死亡后以 1 血复活 | `game.py:_check_deaths()` |
| Windfury | 每回合攻击两次 | `game.py:_attack_loop` |
| Cleave | 同时伤害相邻目标 | `actions.py:Attack.do()` |
| Deathrattle | 死亡时触发 | `game.py:_check_deaths()` |
| Battlecry | 从手牌打出时触发 | `game.py:play_minion()` |
| Avenge(N) | N 个友方亡语后触发 | `actions.py:AvengeIncrement` |
| Rally | 攻击前触发 (伤害前) | `actions.py:Attack.do()` step 3 |
| Start of Combat | 战斗开始前触发 | `game.py:_trigger_start_of_combat()` |
| Spellcraft | 每回合生成临时法术 | `game.py:_generate_spellcraft_spells()` |
| Magnetic | 磁力吸附到机械 | `game.py:play_minion()` |

验证方法：为每个关键词编写对应的单元测试，对比官方行为描述和游戏内实际表现。

### 4.7 补丁内容验证管道

建立一个标准化的跨版本验证流程：

```
1. 获取官方补丁说明 (Patch Notes)
   ├── 提取移除/新增/调整的随从列表
   ├── 提取移除/新增/调整的法术列表
   ├── 提取英雄平衡调整 (护甲/技能)
   ├── 提取赛季机制变更
   └── 提取 Bug 修复

2. 更新 hsdata 子模块
   └── git submodule update --remote hsdata

3. 从新 CardDefs.xml 重新生成 JSON
   ├── bg_cards.json
   ├── bg_pool_minions.json + pool_minion_texts.json
   ├── bg_pool_spells.json + bg_tavern_spells.json
   ├── bg_heroes.json + bg_hero_powers.json
   ├── bg_trinkets.json + pool_trinket_texts.json
   ├── bg_anomalies.json
   ├── bg_quest_rewards.json
   └── bg_summary.json

4. 更新 Python 脚本
   ├── minions/scripts.py — 新增/更新/移除脚本类
   ├── minions/pool.py — 更新 _DEFERRED、添加 SCRIPT_REGISTRY 映射
   ├── heroes/scripts.py — 更新 HERO_POWER_SCRIPT_REGISTRY
   ├── spells/scripts.py — 更新 SPELL_SCRIPT_REGISTRY
   ├── trinkets/scripts.py — 新增/更新 trinket 脚本
   ├── rewards/scripts.py — 更新 REWARD SCRIPT REGISTRY
   ├── anomalies/scripts.py — 更新 ANOMALY SCRIPT REGISTRY
   └── tokens.py — 新增 token 卡牌

5. 如需新机制，更新引擎 (hsrl/core/)
   ├── enums.py — 新增 GameTag
   ├── actions.py — 新增 Action 子类
   ├── game.py — 新增阶段/触发逻辑
   └── entity.py — 新增 base entity 行为

6. 运行审计工具
   ├── python tools/audit_card_registry.py
   └── python tools/audit_for_simplified_scripts.py

7. 运行测试套件
   └── python -m pytest hsrl/tests/ -v

8. 添加新卡牌回归测试
   └── 新增 test_patch_XX_X_X_*.py
```

---

## 5. 维护工作流清单

### 5.1 新补丁发布时

- [ ] 阅读官方补丁说明，提取所有变更
- [ ] 更新 hsdata 子模块：`git submodule update --remote hsdata`
- [ ] 验证 hsdata 版本号 (`hsdata/README.md`)
- [ ] 从新 CardDefs.xml 重新生成所有 `data/bg_*.json` 文件
- [ ] 更新 `data/bg_summary.json` 版本号
- [ ] 更新随从 JSON → 检查 `data/bg_pool_minions.json` 变动
- [ ] 更新法术 JSON → 检查 `data/bg_pool_spells.json` 变动
- [ ] 更新英雄 JSON → 检查护甲值变化
- [ ] 检查 `minions/pool.py` 中的 `_DEFERRED` 列表是否需要更改
- [ ] 为新卡牌编写脚本类 (按 CARD_REGISTRATION_GUIDE.md 规范)
- [ ] 更新 `SCRIPT_REGISTRY` 映射
- [ ] 为新机制添加 `GameTag` (在 `enums.py`)
- [ ] 为新机制添加 `Action` 类 (在 `actions.py`)
- [ ] 编写新卡牌测试 (`test_patch_XX_X_X_*.py`)
- [ ] 运行 `python tools/audit_card_registry.py` (必须 PASS)
- [ ] 运行 `python tools/audit_for_simplified_scripts.py` (必须 PASS)
- [ ] 运行 `python -m pytest hsrl/tests/ -v` (所有测试必须通过)

### 5.2 新增随从卡牌时

1. 将卡牌数据添加到 `data/bg_pool_minions.json`
2. 将卡牌文本添加到 `data/pool_minion_texts.json`
3. 在 `hsrl/cards/minions/scripts.py` 中：
   - 编写 `XxxScript` 类，使用三段式文档注释
   - 将 `"card_id": XxxScript` 添加到 `SCRIPT_REGISTRY`
4. 如果卡牌召唤 token 随从，在 `hsrl/cards/minions/tokens.py` 注册
5. 如果卡牌属于 `_DEFERRED`，在 `minions/pool.py` 的 `_DEFERRED` 列表中记录
6. 在 `test_patch_XX_X_X_*.py` 中编写测试

### 5.3 新增关键词/机制时

1. 在 `hsrl/core/enums.py` 添加新 `GameTag`
2. 在 `hsrl/core/actions.py` 添加新的 `Action` 子类（如果需要新的状态变更操作）
3. 在 `hsrl/core/game.py` 添加新机制的触发点（如果需要新的阶段逻辑）
4. 在 `hsrl/core/events.py` 添加新的事件常量（如果需要新的事件广播）
5. 更新 `docs/MECHANICS_REFERENCE.md`
6. 更新 `docs/BATTLEGROUNDS_RULES.md`

### 5.4 运行完整性检查

```bash
# 审计 1: 确保所有有效果标签的卡牌都有脚本
python tools/audit_card_registry.py

# 审计 2: 确保没有未授权的简化实现
python tools/audit_for_simplified_scripts.py

# 全量测试
python -m pytest hsrl/tests/ -v

# 注册表完整性测试
python -m pytest hsrl/tests/test_registry_integrity.py -v

# 核心机制测试
python -m pytest hsrl/tests/test_core_mechanics.py -v
```

### 5.5 跨版本对比命令

```bash
# 对比两个版本的随从池差异
diff <(python3 -c "import json; [print(m['id']) for m in json.load(open('data/bg_pool_minions.json'))]" | sort) \
     <(python3 -c "import json; [print(m['id']) for m in json.load(open('data/bg_pool_minions_new.json'))]" | sort)

# 检查哪些已注册的随从缺少脚本
python3 -c "
from hsrl.core.card_db import CARDS
from hsrl.core.enums import CardType, GameTag
import hsrl.cards.minions.pool  # trigger registration
for cid, data in CARDS._cards.items():
    if data.cardtype == CardType.MINION and data.scripts is None:
        triggers = [t.name for t in [GameTag.BATTLECRY, GameTag.DEATHRATTLE, GameTag.Avenge]
                    if data.tags.get(t)]
        if triggers:
            print(f'{cid}: {data.name} — triggers: {triggers} — NO SCRIPT')
"
```

---

## 6. 常见问题与排错

### Q1: hsdata 版本和 JSON 版本不一致

**症状**：`hsdata/README.md` 显示 `35.6.0.243002`，`bg_summary.json` 显示 `35.6.0.243002`

**原因**：JSON 数据文件是手动生成的，更新滞后于 hsdata 子模块

**解决**：从当前 CardDefs.xml 重新生成所有 JSON 文件

### Q2: 卡牌注册但无脚本

**症状**：运行 `audit_card_registry.py` 报告 FAIL

**原因**：新增了带有效果标签的卡牌，但没有编写对应的脚本类

**解决**：为每张缺失的卡牌编写 `XxxScript` 类，或将其添加到 `ALLOWED_DEFERRED` 白名单

### Q3: 测试失败但代码逻辑正确

**症状**：测试中的数值预期与新补丁不符

**原因**：卡牌数值被补丁调整（如 atk/health/cost 变化）

**解决**：更新测试中的预期数值，或在 `bg_pool_minions.json` 中更新相应数值

### Q4: CardDefs.xml TAG 映射找不到

**症状**：新卡牌的某个属性无法从 JSON 数据中提取

**原因**：使用了新的 XML enumID，但代码中的映射表未更新

**解决**：使用 `grep 'enumID="XXX"' hsdata/CardDefs.xml | head -5` 查找新标签的语义，然后更新映射

### Q5: 新赛季机制未知

**症状**：不清楚当前赛季引入了什么机制

**原因**：赛季机制（伙伴/任务/异变）在补丁说明中描述

**解决**：
1. 阅读官方补丁说明中的 "Battlegrounds" 部分
2. 检查 `game.py` 中 `_offer_trinkets()`、`_assign_buddies()`、`start_game()` 等方法
3. 参考 `docs/BATTLEGROUNDS_RULES.md` 中的赛季机制章节

### Q6: 新增种族的 DBF ID

**症状**：需要为新种族添加 `DBF_RACE_TO_ENUM` 映射

**解决**：
1. 在 `hsdata/RaceTagMap.xml` 中查找新种族名称
2. 在 `CardDefs.xml` 中使用 `enumID=144` 搜索该种族的 `value`
3. 在 `hsrl/core/enums.py` 的 `DBF_RACE_TO_ENUM` 和 `Race` 枚举中添加

---

## 附录 A: 文件快速参考

| 文件 | 大小 | 角色 |
|------|------|------|
| `hsrl/core/game.py` | ~2825 行 | 游戏引擎主控 |
| `hsrl/core/actions.py` | ~2384 行 | 所有 Action 类 |
| `hsrl/core/enums.py` | ~345 行 | GameTag、枚举定义 |
| `hsrl/core/entity.py` | ~387 行 | BaseEntity + CardData |
| `hsrl/core/player.py` | ~189 行 | Player 类 |
| `hsrl/core/minion_pool.py` | ~210 行 | 共享随从池 |
| `hsrl/core/spell_pool.py` | ~109 行 | 共享法术池 |
| `hsrl/core/card_db.py` | ~158 行 | CardDB + register_card |
| `hsrl/core/events.py` | ~150 行 | EventListener + 事件常量 |
| `hsrl/cards/minions/pool.py` | ~ | 自动注册 270+ 随从 |
| `hsrl/cards/minions/scripts.py` | ~6000+ 行 | 随从脚本类 |
| `hsrl/cards/minions/tokens.py` | ~ | Token 卡牌注册 |
| `hsrl/cards/heroes/pool.py` | ~ | 英雄注册 + XML 解析 |
| `hsrl/cards/heroes/scripts.py` | ~3000+ 行 | 英雄技能脚本 |
| `hsrl/cards/spells/scripts.py` | ~ | 法术脚本 |
| `hsrl/cards/trinkets/scripts.py` | ~ | 饰品脚本 (302/314 活动) |
| `hsrl/cards/rewards/scripts.py` | ~ | 任务奖励脚本 |
| `hsrl/cards/anomalies/scripts.py` | ~ | 异变脚本 |
| `hsrl/tests/test_core_mechanics.py` | ~6186 行 | 核心机制测试 |
| `docs/BATTLEGROUNDS_RULES.md` | ~ | 权威规则手册 |
| `docs/MECHANICS_REFERENCE.md` | ~ | 机制实现参考 |
| `docs/CARD_REGISTRATION_GUIDE.md` | ~1848 行 | 卡牌注册指南 |
| `tools/audit_card_registry.py` | ~111 行 | 注册完整性审计 |
| `tools/audit_for_simplified_scripts.py` | ~219 行 | 简化实现检测 |

## 附录 B: 关键枚举速查

### Step (阶段)

```python
INVALID = 0
BEGIN_RECRUIT = 1
RECRUIT = 2
END_RECRUIT = 3
BEGIN_COMBAT = 4
COMBAT = 5
END_COMBAT = 6
```

### CardType (卡牌类型)

```python
INVALID = 0; MINION = 1; HERO = 2; SPELL = 3; HERO_POWER = 4
REWARD = 5; TRINKET = 6; BLOOD_GEM_CARD = 7; ANOMALY = 8; QUEST = 9
```

### Race (种族)

```python
BEAST = 1; DEMON = 2; DRAGON = 3; ELEMENTAL = 4; MECH = 5; MURLOC = 6
NAGA = 7; PIRATE = 8; QUILBOAR = 9; UNDEAD = 10; ALL = 11; NONE = 12
```

### Zone (区域)

```python
PLAY = 1; HAND = 2; DECK = 3; GRAVEYARD = 4; SETASIDE = 5; REMOVED = 6; TAVERN = 7; SECRET = 8
```

### State / PlayState

```python
State: RUNNING = 1; COMPLETE = 2
PlayState: PLAYING = 1; WON = 2; LOST = 3; TIED = 4
```
