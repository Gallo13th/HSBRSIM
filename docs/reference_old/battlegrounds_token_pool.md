# 酒馆战棋 — 衍生物随从池详细描述文档

> 本文档基于 Hearthstone Wiki (hearthstone.wiki.gg/wiki/Battlegrounds) 最新内容撰写。
> 
> 版本基准：**Patch 34.6.0.235290 (2026-02-09)**
> 
> 衍生物（Token）是**不可购买**的随从，只能通过卡牌效果、英雄技能或特殊机制生成。

---

## 1. 衍生物核心概念

### 1.1 什么是衍生物

衍生物（Token Minions）是：
- **不可从酒馆购买**
- **不占用全局随从池的副本数**
- 只能通过**亡语、战吼、复仇、英雄技能、法术**等效果生成
- 部分衍生物有独立的生成规则（如从特定池中随机召唤）
- 金色衍生物的属性通常为基础值 × 2

### 1.2 衍生物与主池的关系

| 特性 | 可购买随从 | 衍生物 |
|------|-----------|--------|
| 可在酒馆购买 | ✅ | ❌ |
| 占用全局池副本 | ✅ | ❌（大部分）|
| 出售归还副本 | ✅ | N/A |
| 可触发三连 | ✅ | ❌ |
| 可被 Discover | ✅ | ❌ |
| 可参与战斗 | ✅ | ✅ |

> **例外**：少数衍生物（如 Amalgam）由英雄技能生成，但它们的行为类似可购买随从，只是获取途径不同。

---

## 2. 衍生物分类

### 2.1 按生成方式分类

#### A. 亡语召唤类（Deathrattle Summons）

最常见的一类，随从死亡时召唤衍生物。

| 来源随从 | 星级 | 衍生物 | 衍生物属性 | 衍生物种族 | 关键词 |
|---------|------|--------|-----------|-----------|--------|
| Alleycat (雄斑虎) | T1 | Tabbycat | 1/1 | Beast | — |
| Kindly Grandmother | T2 | Big Bad Wolf | 3/2 | Beast | — |
| Rat Pack (瘟疫鼠群) | T2 | Rat | 1/1 | Beast | — |
| Infested Wolf | T3 | Spider | 1/1 | Beast | — |
| The Beast | T3 | Finkle Einhorn | 3/3 | — | — |
| Savannah Highmane | T4 | Hyena | 2/2 | Beast | — |
| Mechano-Egg | T4 | Robosaur | 8/8 | Mech/Beast | — |
| Imp Mama | T5 | Backpiggy Imp | 4/1 | Demon | — |
| Voidlord | T5 | Voidwalker | 1/3 | Demon | Taunt |
| Sneed's Old Shredder | T5 | 随机传说 |  varies | varies | — |
| Ghastcoiler | T6 | 2个随机亡语 | varies | varies | — |

#### B. 战吼召唤类（Battlecry Summons）

| 来源随从 | 星级 | 衍生物 | 衍生物属性 | 衍生物种族 | 关键词 |
|---------|------|--------|-----------|-----------|--------|
| Murloc Tidehunter | T1 | Murloc Scout | 1/1 | Murloc | — |
| Sellemental | T1 | Water Droplet | 1/1 | Elemental | — |
| Deck Swabbie | T1 | 无（减费效果）| — | — | — |
| Harvest Golem | T2 | Damaged Golem | 2/1 | Mech | — |
| Kaboom Bot | T2 | 无（亡语伤害）| — | — | — |
| Deflect-o-Bot | T3 | 无（圣盾效果）| — | — | — |
| Piloted Shredder | T4 | 随机T2 | varies | varies | — |
| Piloted Sky Golem | T5 | 随机T4 | varies | varies | — |

#### C. 复仇召唤类（Avenge Summons）

| 来源随从 | 星级 | 复仇阈值 | 衍生物 | 属性 | 种族 |
|---------|------|---------|--------|------|------|
| Onyxia (英雄) | — | 4 | Whelp | 3/1 | Dragon |
| Impulsive Trickster | T1 | — | 无（转移属性）| — | — |
| Spawn of N'Zoth | T2 | — | 无（全体buff）| — | — |

#### D. 英雄技能衍生物（Hero Power Minions）

| 英雄 | 衍生物 | 属性 | 种族 | 特殊说明 |
|------|--------|------|------|---------|
| The Curator (馆长) | Amalgam | 2/2 | All | 开局自带，全种族 |
| N'Zoth (恩佐斯) | Fish of N'Zoth | 1/1 | All | 获得所有亡语 |
| Shudderwock (沙德沃克) | Shudderling | 1/1 | General | 重复所有战吼 |
| Pyramad (金字塔) | Brick | 1/1 | General | Taunt |
| Ragnaros (拉格纳罗斯) | Sulfuras | — | — | 武器/被动 |

#### E. 法术/饰品召唤类（Spell/Trinket Summons）

| 来源 | 衍生物 | 属性 | 种族 | 关键词 |
|------|--------|------|------|--------|
| 香蕉（Banana）| 无 | +1/+1 buff | — | — |
| 血宝石（Blood Gem）| 无 | +1/+1 buff | — | — |
| 大菠萝事件 | Diablo | 4/4 | Demon | Deathrattle |
| 暗月奖品 |  varies | varies | varies | varies |

---

## 3. 常见衍生物详细列表

### 3.1 T1 衍生物

| 衍生物名 | 攻击力 | 生命值 | 种族 | 关键词 | 典型来源 |
|---------|--------|--------|------|--------|---------|
| Tabbycat | 1 | 1 | Beast | — | Alleycat 战吼 |
| Murloc Scout | 1 | 1 | Murloc | — | Murloc Tidehunter 战吼 |
| Water Droplet | 1/2 | 1/2 | Elemental | — | Sellemental 出售 |
| Microbot | 1 | 1 | Mech | — | Mechano-Egg 等 |
| Imp | 1 | 1 | Demon | — | Imp Gang Boss 等 |
| Spider | 1 | 1 | Beast | — | Infested Wolf 亡语 |
| Rat | 1 | 1 | Beast | — | Rat Pack 亡语 |
| Snake | 1/1 | 1/1 | Beast | — | Snake Trap 等 |
| Hyena | 2/2 | 2/2 | Beast | — | Savannah Highmane 亡语 |
| Skeleton | 1/1 | 1/1 | Undead | — | 多种亡灵卡 |
| Plant | 1/1 | 1/1 | General | — | 多种来源 |
| Jo-E Bot | 1 | 1 | Mech/Beast | — | Replicating Menace |
| Crab | 3 | 2 | Beast | — | Surf n' Surf Spellcraft |
| Whelp | varies | varies | Dragon | — | 多种龙卡 |

### 3.2 T2+ 衍生物

| 衍生物名 | 攻击力 | 生命值 | 种族 | 关键词 | 典型来源 |
|---------|--------|--------|------|--------|---------|
| Big Bad Wolf | 3 | 2 | Beast | — | Kindly Grandmother 亡语 |
| Damaged Golem | 2 | 1 | Mech | — | Harvest Golem 亡语 |
| Voidwalker | 1 | 3 | Demon | Taunt | Voidlord 亡语 |
| Robosaur | 8 | 8 | Mech/Beast | — | Mechano-Egg 亡语 |
| Guardian Bot | 2 | 3 | Mech | Taunt | Security Rover |
| Backpiggy Imp | 4 | 1 | Demon | — | Imp Mama 亡语 |
| Treasure Chest | — | 2 | General | Deathrattle | 特殊事件 |

### 3.3 特殊衍生物

| 衍生物名 | 说明 |
|---------|------|
| Shudderling | 沙德沃克英雄技能产物，战吼重复本局所有其他战吼 |
| Amalgam | 馆长开局产物，具有所有种族类型 |
| Fish of N'Zoth | 恩佐斯开局产物，获得所有友方亡语 |
| Diablo, Lord of Terror | 大菠萝事件产物，死亡给对方2个战利品 |
| Golden Minion (from Triple) | 三连奖励发现的金色随从 |

---

## 4. 衍生物的生成规则

### 4.1 从手牌/场上召唤到场上

大部分衍生物直接召唤到场上：
- 位置通常在**最右侧**（或触发者相邻位置）
- 如果场上已满（7个随从），通常**无法召唤**
- 部分效果在满场时会提供替代收益（如 +1/+1 buff）

### 4.2 从池中随机召唤

部分效果（如 Sneed's Old Shredder 亡语、Ghastcoiler 亡语）从**特定池中随机召唤**：
- Sneed's: 随机传说随从池
- Ghastcoiler: 随机亡语随从池
- 这些召唤**可能从全局池中抽取**，也可能使用独立的随机池

### 4.3 战斗中生成的衍生物

战斗中生成的衍生物规则：
- 召唤到场上最右侧
- 立即参与战斗（如果轮到该方攻击）
- 可以触发复仇计数
- 死亡时触发亡语（如果有）
- **不继承战斗前的任何 buff**（除非是明确复制效果）

---

## 5. 项目当前问题与修复建议

### 5.1 当前问题

| 问题 | 严重程度 | 说明 |
|------|---------|------|
| 衍生物混入随从池 | 🔴 严重 | `minions.json` 包含 ~80+ 衍生物，被错误计入全局池 |
| 无独立衍生物定义文件 | 🟡 中等 | 所有 token 定义混杂在 minions.json 中 |
| summon 效果的 dbf_id 指向错误 | 🟡 中等 | `card_effects.json` 中的 summon dbf_id 可能指向主随从而非 token |
| 金色衍生物规则缺失 | 🟡 中等 | 未定义 token 的金色版本生成规则 |
| 满场召唤处理缺失 | 🟡 中等 | 未实现"场上满7时召唤失败/替代收益"逻辑 |

### 5.2 修复建议

**步骤1：分离数据**
```
config/
├── minions.json        # 仅可购买随从
├── tokens.json         # 衍生物定义
└── card_effects.json   # 修正 summon 的 dbf_id 指向 token
```

**步骤2：建立 Token 注册表**
```python
class TokenRegistry:
    """衍生物注册表 — 管理所有不可购买随从的定义。"""
    
    def __init__(self):
        self._tokens: dict[int, TokenDef] = {}  # dbf_id -> TokenDef
        
    def load(self, path: str) -> None:
        """从 tokens.json 加载衍生物定义。"""
        ...
        
    def get(self, dbf_id: int) -> TokenDef | None:
        """获取衍生物定义。"""
        return self._tokens.get(dbf_id)
        
    def create_instance(self, dbf_id: int, is_golden: bool = False) -> CombatMinion:
        """创建衍生物实例（不入池）。"""
        ...
```

**步骤3：修正效果系统**
- `card_effects.json` 中所有 `type: "summon"` 的效果，其 `dbf_id` 应指向 `tokens.json` 中的条目
- 区分 "从池中召唤随机随从" 和 "生成特定衍生物"

**步骤4：实现满场处理**
```python
# 在战斗引擎和环境引擎中
def summon_token(board, token_def, position=-1):
    if len(board) >= 7:
        # 满场时的替代处理
        return {"action": "summon_failed", "alternative": "buff_board"}
    ...
```

---

## 6. 相关文件

- `hsrhl/engine/minion_pool.py` — 随从池（不应包含 token）
- `hsrhl/engine/effects.py` — 效果执行引擎（ summon 效果）
- `hsrhl/engine/combat.py` — 战斗引擎（战斗中 token 生成）
- `config/minions.json` — 需清理，分离 token
- `docs/battlegrounds_minion_pool.md` — 主随从池文档
