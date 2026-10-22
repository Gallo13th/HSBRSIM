# 酒馆战棋 — 随从池详细描述文档

> 本文档基于 Hearthstone Wiki (hearthstone.wiki.gg/wiki/Battlegrounds) 最新内容撰写。
> 
> 版本基准：**Patch 34.6.0.235290 (2026-02-09)** — "Embers of the World Tree"
> 
> 数据基准：114 Heroes | ~2,747 Minions (含所有版本/金卡/衍生物) | 11 Races + General/Dual-type

---

## 1. 随从池核心概念

### 1.1 全局共享池

酒馆战棋使用**全局共享的随从池**。所有8名玩家从同一个池中抽取和归还随从。

- 每个可购买的随从种类在池中有固定数量的**副本（copy）**
- 玩家**购买**随从时，从池中移除1个副本
- 玩家**出售**随从时，归还1个副本到池中
- 玩家**淘汰**时，其所有随从（场上+手牌）全部归还池中
- 玩家**刷新酒馆**时，未购买的随从归还池中

### 1.2 各星级副本数量

| 星级 | 每种种类副本数 | 备注 |
|------|--------------|------|
| T1   | 16           | Patch 16.4+ 标准 |
| T2   | 15           | Patch 16.4+ 标准 |
| T3   | 13           | Patch 16.4+ 标准 |
| T4   | 11           | Patch 16.4+ 标准 |
| T5   | 9            | Patch 16.4+ 标准 |
| T6   | 7            | Patch 16.4+ 标准 |
| T7   | 5            | 仅特定模式/异变中出现 |

> **项目当前状态**：`POOL_COPIES` 已正确定义到 T6（`minion_pool.py:18-25`），但缺少 T7 支持。

---

## 2. 种族（Minion Types）

### 2.1 11个基础种族 + 特殊分类

| 种族（英文） | 种族（中文） | 备注 |
|------------|------------|------|
| Beast      | 野兽       | 亡语/召唤流派 |
| Demon      | 恶魔       | 吞噬/自残流派 |
| Dragon     | 龙         | 战斗开始/战斗触发 |
| Elemental  | 元素       | 元素链/刷新流派 |
| Mech       | 机械       | 磁力/圣盾流派 |
| Murloc     | 鱼人       | 手牌buff/毒鱼 |
| Naga       | 纳迦       | 法术/塑造法术 |
| Pirate     | 海盗       | 金币/攻击触发 |
| Quilboar   | 野猪人     | 血宝石流派 |
| Undead     | 亡灵       | 复生/死亡计数 |
| All        | 全种族     | 融合怪等，享受所有种族buff |
| General    | 无种族/通用 | 不享受任何种族专属buff |

### 2.2 双种族随从（Dual-type Minions）

部分随从同时具有 **2 个种族**，同时受两个种族的 buff/机制影响：

| 随从名 | 种族 | 星级 | 状态 |
|--------|------|------|------|
| Surf n' Surf | Naga/Beast | T1 | 可用 |
| Blazing Skyfin | Dragon/Murloc | T2 | 可用 |
| Fel Elemental | Elemental/Demon | T3 | 可用 |
| Lava Murloc | Elemental/Murloc | T4 | 可用 |
| Sinrunner Blanchy | Undead/Beast | T5 | 可用 |
| Mecha-Jaraxxus | Mech/Demon | T6 | 可用 |
| P-0UL-TR-0N | Mech/Beast | T6 | 可用 |
| Flaming Enforcer | Demon/Elemental | T4 | Patch 34.2 新增 |
| Spirit Drake | Undead/Dragon | T4 | Patch 34.2 新增 |
| Plankwalker | Undead/Pirate | T4 | Patch 34.2 新增 |

> **项目当前状态**：`minions.json` 中 `races` 字段已支持数组形式的双种族，但 `race` 字段为字符串拼接（如 `"Mech/Demon"`），需统一处理。

---

## 3. 每局游戏的随从池构成

### 3.1 种族禁用机制（Minion Type Ban）

**每局游戏开始时，系统随机禁用 5 个种族**，剩余 **6 个种族** 参与本局游戏。

- 总种族数：11
- 每局可用种族数：6
- 禁用种族数：5

被禁用的种族的随从**不会出现在酒馆中**，也不会被 Discover（发现）等机制提供。

> **示例**：如果本局禁用了 Beast、Demon、Dragon、Elemental、Naga，则酒馆中只会出现 Mech、Murloc、Pirate、Quilboar、Undead 和 All/General 随从。

### 3.2 可用随从种类数

根据 wiki 数据，**全部历史版本中**各星级各种族的随从种类总数（非每局可用数）：

| 星级 | 不同种类数（历史累计） |
|------|---------------------|
| T1   | 133                 |
| T2   | 339                 |
| T3   | 594                 |
| T4   | 441                 |
| T5   | 454                 |
| T6   | 340                 |
| T7   | 111                 |

每局游戏中，实际可用的随从种类约为 **60-80 种**（取决于当前版本和禁用种族）。

### 3.3 酒馆展示卡数

根据玩家当前酒馆等级，酒馆展示的可购买随从/法术数量：

| 酒馆等级 | 随从展示数 | 法术展示数（若启用） |
|---------|-----------|-------------------|
| T1      | 3         | 1                 |
| T2      | 4         | 1                 |
| T3      | 4         | 1                 |
| T4      | 5         | 1                 |
| T5      | 5         | 1                 |
| T6      | 6         | 1                 |

> **项目当前问题**：
> 1. `minion_pool.py` 和 `dealer.py` **没有实现种族禁用机制**。当前实现从全部种族的随从中抽取，与真实游戏规则不符。
> 2. `config/minions.json` 中包含了约 **949 种随从**，远超实际每局可购买的 60-80 种。其中混杂了大量衍生物、英雄技能随从、宝藏随从、时空扭曲随从和双打模式随从。

---

## 4. 随从分类与过滤规则

### 4.1 可购买随从（Buyable Minions）

可购买随从必须满足以下条件：

1. **是标准酒馆随从**：`card_id` 以 `BG` 开头（不含 `_t` 结尾的 token）
2. **不是衍生物**：不含 `_t`、`_t2`、`_t3`、`_t4` 等后缀（除少数例外）
3. **不是英雄技能随从**：`card_id` 不以 `TB_BaconShop_HP_` 开头
4. **不是宝藏/奖励随从**：`card_id` 不以 `BGS_Treasures_`、`BG_Reward_`、`BG34_Treasure_` 等开头
5. **不是时空扭曲随从**：`card_id` 不含 `BG34_Giant_`、`Timewarped` 等（这些是特定异变/事件专用）
6. **不是双打模式随从**：`card_id` 不以 `BGDUO` 开头
7. **不是英雄专属法术/随从**：`card_id` 不含 `_HERO_`、`_HeroPowerSpell_`、`_pt` 等

### 4.2 衍生物随从（Token Minions）

衍生物是**不可购买**的随从，只能通过卡牌效果（亡语、战吼、复仇等）召唤生成。

衍生物特征：
- `card_id` 通常以 `_t`、`_t2`、`_t3`、`_t4` 结尾
- 部分 token 有 `race`，部分为 `General`
- **不占用全局随从池的副本数**
- 金色版本的衍生物通常不在池中

根据 wiki，常见衍生物包括：

| 衍生物名 | 种族 | 攻击力 | 生命值 | 关键词 | 来源 |
|---------|------|--------|--------|--------|------|
| Tabbycat | Beast | 1 | 1 | — | Alleycat 战吼 |
| Big Bad Wolf | Beast | 3 | 2 | — | Kindly Grandmother 亡语 |
| Hyena | Beast | 2 | 2 | — | Scavenging Hyena 相关 |
| Spider | Beast | 1 | 1 | — | Infested Wolf 亡语 |
| Rat | Beast | 1 | 1 | — | Rat Pack 亡语 |
| Devilsaur | Beast | 8 | 8 | — | 多张卡生成 |
| Ironhide Runt | Beast | 5 | 5 | — | Ironhide Direhorn 相关 |
| Crab | Beast | 3 | 2 | — | Surf n' Surf Spellcraft |
| Murloc Scout | Murloc | 1 | 1 | — | Murloc Tidehunter 战吼 |
| Primalfin | Murloc | 1 | 1 | — | Primalfin Lookout 等 |
| Guard Bot | Mech | 2 | 3 | Taunt | Security Rover 等 |
| Jo-E Bot | Mech/Beast | 1 | 1 | — | Replicating Menace 等 |
| Robosaur | Mech/Beast | 8 | 8 | — | 机械相关 |
| Plant | General | 1 | 1 | — | 多种来源 |
| Backpiggy Imp | Demon | 4 | 1 | — | Imp 相关 |
| Shudderling | General | 1 | 1 | Battlecry | Shudderwock 英雄技能 |
| Treasure Chest | General | — | 2 | Deathrattle | 宝藏/事件 |
| Pip Quickwit | General | 3 | 3 | — | 特殊来源 |
| Diablo, Lord of Terror | Demon | 4 | 4 | Deathrattle | 特殊事件 |

> **项目当前问题**：`config/minions.json` 将衍生物和可购买随从混在同一个文件中，且 `MinionPool.initialize()` 将所有随从都加入了全局池。这导致：
> 1. 衍生物被错误地计入了池副本数
> 2. 玩家可能在酒馆中"购买"到本不该出现的衍生物
> 3. 三连机制可能错误地将衍生物计算在内

### 4.3 英雄技能随从（Hero Power Minions）

由英雄技能生成的随从，**不可购买**，不属于全局随从池：

| 随从名 | card_id | 来源英雄 |
|--------|---------|---------|
| Shudderling | TB_BaconShop_HP_022t | Shudderwock |
| Amalgam | TB_BaconShop_HP_033t | The Curator |
| Fish of N'Zoth | TB_BaconShop_HP_105t | N'Zoth |
| 各种皮肤版本 | `_SKIN_A`、`_SKIN_B` 等 | 对应英雄 |

### 4.4 时空扭曲随从（Timewarped / Giant Minions）

`BG34_Giant_` 系列随从是 **Anomaly（异变）"时空扭曲酒馆"** 或 **大菠萝事件** 中的特殊随从。这些随从：
- 通常只在特定异常/事件中出现
- 不可通过正常刷新获得
- 属性值或效果可能被扭曲

Patch 34.2 引入了新的 Timewarped 随从：
- Timewarped Stoneshell (Neutral, T?)
- Timewarped Tender (Neutral, T?)
- Timewarped Nine Frogs (Beast, T?)
- Timewarped Theotar (All, T?)
- Timewarped Nalaa (Neutral, T?)
- Timewarped Deios (Neutral, T?)

> **项目当前问题**：时空扭曲随从不应出现在标准随从池中。当前 `minions.json` 包含了约 100+ 种此类随从，严重污染了数据。

---

## 5. 三连（Triple）机制

### 5.1 三连规则

当玩家拥有 **3 张完全相同的基础随从**（相同 `dbf_id`）时，自动合成 **1 张金色随从**：

- 3 张基础随从可以从**场上**和**手牌**中组合
- 金色随从的属性值 = 基础属性值 × 2
- 金色随从的效果触发次数通常翻倍（如战吼触发2次、亡语触发2次）
- 金色随从的来源标记为 `is_golden=True`

### 5.2 三连奖励

合成金色随从后，玩家获得 **1 次发现奖励**：
- 发现等级 = `min(当前酒馆等级 + 1, 6)`
- 发现选项通常为 3 个随从
- 发现的随从从全局池中无放回抽取

### 5.3 金色随从的出售

- 自然三连的金色随从出售时，**归还 3 张基础副本**到池中
- 英雄技能（如 Reno Jackson）镀金的随从出售时，**仅归还 1 张副本**
- 含有磁力吸附组件的金色随从，出售时还需归还磁力组件的副本

> **项目当前状态**：`minion_pool.py:sell()` 已实现上述逻辑，但三连检测逻辑 `tavern.py:_check_triple()` 存在缺陷。

---

## 6. 磁力（Magnetic）机制

### 6.1 磁力规则

磁力是机械种族的专属机制：

- 带有 **Magnetic** 关键词的机械可以作为"组件"吸附到另一个机械上
- 吸附后，目标机械获得磁力组件的**攻击力、生命值和关键词**
- 被吸附的组件**永久**成为目标的一部分
- 金色磁力组件吸附时，提供双倍属性

### 6.2 磁力随从池

磁力随从有自己的小池子，通常通过特定卡牌效果（如 Ini Stormcoil）或发现获得。

> **项目当前问题**：
> 1. `minion_pool.py` 有 `magnetic_attachments` 字段，但没有完整的磁力吸附系统
> 2. `card_effects.json` 中的 `magnetic_attach` 效果类型未完整实现
> 3. 磁力组件的副本管理未实现

---

## 7. 项目当前数据问题汇总

### 7.1 `config/minions.json` 数据质量问题

| 问题 | 数量（估计） | 影响 |
|------|------------|------|
| 衍生物随从混入池 | ~80+ 种 | 池副本数虚高，玩家可能买到 token |
| 英雄技能随从混入池 | ~10+ 种 | 池副本数虚高 |
| 时空扭曲随从混入池 | ~100+ 种 | 池副本数严重虚高，种族分布失真 |
| 双打模式随从混入池 | ~15+ 种 | 不适用于标准模式 |
| 宝藏/奖励随从混入池 | ~20+ 种 | 不应通过购买获得 |
| 法术误标为随从 | 少量 | `is_spell=true` 但出现在 minions.json |

### 7.2 建议的数据清理方案

```
config/
├── minions.json          # 仅包含可购买的标准酒馆随从（~70-80种/版本）
├── tokens.json           # 衍生物定义（供效果系统召唤用，不入池）
├── hero_power_minions.json  # 英雄技能随从定义（不入池）
├── spells.json           # 酒馆法术（需清理非标准法术）
└── card_effects.json     # 卡牌效果（需修正 summon 的 dbf_id）
```

数据过滤规则（按优先级）：

1. **保留**：`card_id` 以 `BG` 开头，不含 `_t`/`_t2`/`_t3`/`_t4` 后缀，非 `BGDUO` 开头，非 `BG34_Giant_`
2. **移除**：`_t` 结尾的 token（移至 `tokens.json`）
3. **移除**：`TB_BaconShop_HP_` 开头的英雄技能随从
4. **移除**：`BG34_Giant_` 开头的时空扭曲随从
5. **移除**：`BGDUO` 开头的双打随从
6. **移除**：`BGS_Treasures_` / `BG_Reward_` / `BG34_Treasure_` 等宝藏随从

---

## 8. 酒馆等级与随从获取概率

### 8.1 升级费用

| 目标等级 | 标准费用 | 回合自然递减 |
|---------|---------|------------|
| T1 → T2 | 5       | 每回合 -1    |
| T2 → T3 | 7       | 每回合 -1    |
| T3 → T4 | 8       | 每回合 -1    |
| T4 → T5 | 11      | 每回合 -1    |
| T5 → T6 | 11      | 每回合 -1    |

### 8.2 随从获取概率

根据当前酒馆等级，刷新时获得各星级随从的概率：

| 酒馆等级 | T1   | T2   | T3   | T4   | T5   | T6   |
|---------|------|------|------|------|------|------|
| T1      | 100% | 0%   | 0%   | 0%   | 0%   | 0%   |
| T2      | ~67% | ~33% | 0%   | 0%   | 0%   | 0%   |
| T3      | ~50% | ~33% | ~17% | 0%   | 0%   | 0%   |
| T4      | ~40% | ~30% | ~20% | ~10% | 0%   | 0%   |
| T5      | ~30% | ~25% | ~20% | ~15% | ~10% | 0%   |
| T6      | ~25% | ~20% | ~18% | ~15% | ~12% | ~10% |

> 注：以上为近似值，实际概率可能因版本微调。

> **项目当前问题**：`dealer.py` 中似乎没有明确的按星级加权的刷新概率，而是从当前等级以下的所有随从中均匀抽取。这与真实游戏的概率分布不符。

---

## 9. 相关文件

- `hsrhl/engine/minion_pool.py` — 随从池管理
- `hsrhl/engine/dealer.py` — 酒馆发牌器
- `hsrhl/engine/tavern.py` — 酒馆阶段逻辑
- `config/minions.json` — 随从数据（需清理）
- `docs/combat_rules.md` — 战斗结算规则
