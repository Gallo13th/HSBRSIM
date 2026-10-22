# 炉石传说酒馆战棋单打模式 — 完整规则手册

> **来源说明**：本文档综合整理自 hearthstone.wiki.gg、hearthstone.fandom.com、Blizzard 官方补丁说明（Patch 34.x–35.4.2，截至 2026-05-19）及社区权威指南。所有外部信息已交叉验证并冻结在项目内部，后续开发不依赖网络访问。
>
> **版本**: 0.5.0 | **更新日期**: 2026-05-25

---

## 目录

1. [游戏概述](#1-游戏概述)
2. [随从池与出现概率](#2-随从池与出现概率)
3. [招募阶段（Recruit Phase）](#3-招募阶段recruit-phase)
4. [战斗阶段（Combat Phase）](#4-战斗阶段combat-phase)
5. [伤害计算与伤害上限](#5-伤害计算与伤害上限)
6. [核心关键词机制](#6-核心关键词机制)
7. [最新赛季特殊机制（Season 13）](#7-最新赛季特殊机制season-13)
8. [种族与类型](#8-种族与类型)
9. [英雄与英雄技能](#9-英雄与英雄技能)
10. [三连与金色随从](#10-三连与金色随从)
11. [季节性系统](#11-季节性系统)
12. [异常（Anomalies）](#12-异常anomalies)
13. [已退役机制](#13-已退役机制)
14. [附录：战斗流程状态机](#附录战斗流程状态机)

---

## 1. 游戏概述

### 1.1 基本目标

酒馆战棋是 **8 人自动战斗模式**。玩家的目标是通过在鲍勃的酒馆中招募随从、组建阵容，在自动战斗中击败对手，成为最后存活的玩家。

### 1.2 回合结构

每个回合由两个交替进行的阶段组成：

1. **招募阶段（Recruit Phase）**：玩家在鲍勃的酒馆中购买、出售、调整随从位置、升级酒馆等级。
2. **战斗阶段（Combat Phase）**：玩家之间自动进行战斗，无法手动干预。

两个阶段循环交替，直到只剩一名玩家存活。

### 1.3 玩家生命值与护甲

- 大多数英雄起始生命值为 **30 点**。
- 每个英雄拥有额外的 **护甲值（Armor）**，范围为 **5 到 20 点**，根据英雄的强度等级分配。
- 护甲叠加在生命值之上，构成有效生命值（例如：30 生命 + 10 护甲 = 40 有效生命）。
- 受到伤害时，先扣除护甲，护甲归零后才扣除生命值。

### 1.4 金币经济

| 项目 | 数值 |
|------|------|
| 起始金币 | 3 金（第 1 回合） |
| 每回合增长 | +1 金/回合 ，持续7回合后停止（第8回合10金为止）|
| 金币上限 | 99 金 （自然增长到第8回合10金停止，但通过其他方法获得铸币上限最多到达99金）|
| 随从购买 | 3 金 |
| 随从出售 | 返还 1 金 |
| 刷新酒馆 | 1 金 |
| 冻结酒馆 | 免费 |

金币回合结束不会保留，不可以储蓄。

---

## 2. 随从池与出现概率

### 2.1 共享随从池

酒馆战棋使用**所有玩家共享的随从池**。当一名玩家购买某个随从时，该随从的副本从池中移除；当玩家出售随从或被淘汰时，其拥有的随从全部返还池中。

### 2.2 各等级随从副本数

截至 Patch 35.x，各酒馆等级随从在池中的副本数量如下：

| 酒馆等级 | 每种种类的副本数 | 备注 |
|---------|----------------|------|
| Tier 1 | **16** 份 | 最高供应量 |
| Tier 2 | **15** 份 | |
| Tier 3 | **13** 份 | |
| Tier 4 | **11** 份 | |
| Tier 5 | **9** 份 | |
| Tier 6 | **7** 份 | 最稀有 |

**历史变更**：早期版本中 Tier 1 为 18 份、Tier 6 为 6 份，后经多次调整达到当前数值。

### 2.3 随从池的返还规则

- **出售随从**：出售的随从（包括 Token）立即返还池中。
- **金色随从**：金色随从占用 **3 份**副本。出售金色随从时，**返还 3 份**到池中。
- **磁力吸附**：被磁力的随从在主体被出售时返还池中。
- **玩家淘汰**：被淘汰玩家的所有随从立即返还池中。
- **淘汰者收口**（2026-09-13 压测 seed 5066）: `_process_eliminations`
  除回池外**必须清空**该英雄的 `board`/`hand`/`tavern` 三个区域，并注销
  其本人 + 棋盘/手牌/酒馆实体 + 饰品 + 任务奖励实体名下的全部事件
  监听器。否则淘汰者的 `turn_end`/`turn_start` 监听器在后续回合仍会
  触发，读到 `zone=REMOVED` 的陈旧实体（实例: BG24_Reward_309 "两端
  随从吞噬酒馆随从" 对已 REMOVED 的随从调用 `ConsumeMinion` →
  `GameStateError` 中断整局）。淘汰者不再行动。
- **发现（Discover）**：通过三连奖励或发现效果获得的随从**从池中移除**。
- **Reno Jackson 的金色化**：不消耗池中的随从；但出售该金色随从时**仅返还 1 份**。
- **Rafaam / Murozond 偷取**：偷取的随从从池中移除 1 份。
- **效果生成的副本**（"get a copy" / `_plain_copy` / `copy_trinket`
  族）: 生成时**不占池**（副本是凭空多出来的，不检查也不扣减剩余量
  ——与上一条"Discover/偷取占池"相对）; 但该副本之后被出售/淘汰时，
  按本节第一条"出售随从立即返还池"处理（普通 1 份 / 金色 3 份，金色
  例外同 Reno）。裁定依据: 本节是池记账的权威条款且**未**为效果副本
  设例外（唯一的"返还 1 份"例外是 Reno 金色化），2026-09-02 复查
  无相反证据; 旧引擎的"副本售出后池净增 +1"于是**不是**缺陷。
  实现: `MinionPool.release_minion_entity`（副本实体不带池来源信息，
  出售走同一路径）。

- **永久移除**（Emergency Landing / Eject! `BG31_Anomaly_117`，2026-09-13
  主线原语）: `MinionPool.purge(card_id)` 把该卡池内**全部剩余副本**永久
  移出本局池，`is_purged(card_id)` 查询。与 `acquire`/`release` 的临时
  扣减不同，被 purge 的卡**不再进入池**——`available` 恒 0、`candidates`
  不列出、`acquire`/`ensure_available`/`release`/`release_minion_entity`
  四路全部拒绝回池（`ensure_available` 是异变注入路径，同样被拒）。
  已抽出的副本（酒馆展示位 / 棋盘 / 手牌）**不受影响**——卡面字面量
  "remove all copies of it **from your pool**" 只清池，不含已抽出副本;
  它们之后出售/淘汰的 `release` 亦被拒 → 不回归池。purge 幂等（第二次
  返回 0），只作用于本卡 id（金色定义与同族其它卡不连带; 金色展示位经
  `triple_base_id` 归一到池内的基础定义）。实现见
  `hsrl2/tests/test_engine_primitives.py::TestMinionPoolPurge`
  （批次行为面见 `test_batch_anomalies7.py`）。

### 2.4 出现概率计算

酒馆提供的随从从以下范围内随机抽取：

| 酒馆等级 | 提供随从数 | 可选范围 |
|---------|-----------|---------|
| Tier 1 | 3 个 | Tier 1 |
| Tier 2 | 4 个 | Tier 1-2 |
| Tier 3 | 4 个 | Tier 1-3 |
| Tier 4 | 5 个 | Tier 1-4 |
| Tier 5 | 5 个 | Tier 1-5 |
| Tier 6 | 6 个 | Tier 1-6 |

- 池中剩余数量越少的随从，被提供的概率越低。
- 如果某随从在池中的副本全部被拿走，则**任何玩家都无法再通过刷新或发现获得该随从**（直到有副本返还）。

### 2.5 随从总数统计

截至 Patch 35.4.2 (2026-05-19)：

- **英雄**: 127 位
- **随从**: 超过 2600 张（含历史版本和双打专属）
- **当前可用随从**: 约 200+（含各等级和种族）

---

## 3. 招募阶段（Recruit Phase）

### 3.1 酒馆等级系统

酒馆等级（Tavern Tier）决定了你能招募到的随从质量和数量：

| 酒馆等级 | 提供随从数 | 升级费用 |
|---------|-----------|---------|
| Tier 1 | 3 个 | — |
| Tier 2 | 4 个 | 5 金 |
| Tier 3 | 4 个 | 7 金 |
| Tier 4 | 5 个 | 8 金 |
| Tier 5 | 5 个 | 9 金 |
| Tier 6 | 6 个 | 10 金 |
| Tier 7* | 6 个 | 11 金 |

\* Tier 7 仅在有特殊效果（如诺甘农的奖励）时可达。

**升级费用递减规则**：每回合未升级时，升级费用减少 1 金（最低 0 金）。

### 3.2 酒馆中的操作

| 操作 | 费用 | 说明 |
|------|------|------|
| 购买随从 | 3 金 | 将随从从酒馆移入手牌 |
| 出售随从 | 返还 1 金 | 从手牌或战场上的随从出售给鲍勃 |
| 刷新酒馆 | 1 金 | 重新生成酒馆中的随从 |
| 冻结酒馆 | 免费 | 锁定当前酒馆阵容至下回合 |
| 升级酒馆 | 当前费用 | 提升酒馆等级 |

### 3.3 手牌与战场限制

- **战场（Board）上限**：最多 7 个随从。
- **手牌（Hand）上限**：最多 10 张（包括随从和法术）。
- 满 board 时无法从手牌打出随从；满手牌时生成的卡牌（如法术塑造）会"等待"直到有空位。

### 3.4 随从位置

- 玩家可以在招募阶段自由调整战场上随从的左右顺序。
- **最左侧的随从在战斗中首先攻击**。
- 位置策略至关重要：嘲讽保护后排、剧毒/圣盾放左侧尽早输出、亡语产生 token 的随从需要考虑召唤位置。

### 3.5 战斗阶段Buff与招募阶段Buff的区别

- **招募阶段Buff**（通过战吼、回合结束效果等获得）是**永久**的，会累积到后续回合。
- **战斗阶段Buff**（如战斗中触发的增益）在战斗结束后**消失**，随从状态恢复到战斗前。

**引擎实现注记（非卡牌权威；记录实现现实，2026-09-18 复核）**: 以下三段落
是**引擎行为记录**，**不构成卡牌规则权威**，也不得反过来为任何近似实现
背书。卡面写 "give … **permanently**" 而数值在战斗内更大时（Bewitched
Ribbon `BG35_MagicItem_923` "…permanently. (+2/+2 while in combat!)"），
该次授予**不**属于上一条的"战斗阶段Buff"，必须跨战斗保留——这一句的权威在
卡面**同一句**的 "permanently" 自身，见 §7.4.18。

**引擎实现注记（续）**: 引擎 `Game.run_combat` 的恢复阶段（`finally`）对
**未命中以下通道**的实体做全量快照回滚; 当前实现 4 条例外:

1. `GameTag.PERSIST_COMBAT_CHANGES` —— **单实体全量**保留（Tarecgosa
   Sticker / Persistent Poet 族; 总量在伤害前捕获）;
2. Persistent Poet 相邻龙（`poet_persist`）;
3. 伤害窗口增量（`dmg_deltas`——战败伤害触发器写入的增益，官方随复活保留）;
4. `Buff(persist=True, source_id=…)` —— **逐附魔、按来源**保留
   （来源规则经 `Game.add_persist_source(hero, source, card_ids)` 登记;
   读取时校验 source 仍在 `hero.trinkets`/`quest_rewards`/`board`，
   离场即失效; 家族按 `GameTag.TRIPLE_BASE_CARD_ID` 回落，金色同族命中）。
   消费者: Bewitched Ribbon `BG35_MagicItem_923`、Cyclist Portrait
   `BG36_MagicItem_362`（载荷 `BG31_925` Showy Cyclist 的亡语）。

例外 1 与例外 4 **正交**: 命中例外 4 的实体，其**其它**战内变化照常回滚
（例外 4 只重放被标记的那批附魔）。

**无官方权威的披露（就近重复，2026-09-18）**: 例外 1 × 例外 4 的**归属
规则**（被 `persist` 标记的附魔归例外 4、其余战内变化归例外 1，因而同一
实体不会在 `PERSIST_DOUBLE` 重放中被计两次）**没有官方权威**——它是引擎为
消除重复计数的**实现契约**（`game.py` 例外 4 重放去重与例外 1 增量扣除），
不是从卡面或官方文本推导出的规则; 详见 §7.4.18 与 `ENGINE_BACKLOG` #38。

### 3.6 酒馆法术（Tavern Spells）

酒馆法术是第 6 赛季引入的核心机制，丰富了招募阶段的操作深度。

#### 3.6.1 法术池

- 酒馆法术使用**独立的共享法术池**（与随从池分开）。
- 当前池中有 **71 张**酒馆法术（Patch 35.2.2）。
- **每张法术按 tier 有固定副本数**（2026-08-23 依据
  hearthstone.wiki.gg/wiki/Battlegrounds/Tavern_spell Table 节修正，
  引自 BG 前负责人 Mitchell Loewen 2024-03-10 X post）:
  | Tier | 1 | 2 | 3 | 4 | 5 | 6 |
  |------|---|---|---|---|---|---|
  | 副本 | 5 | 7 | 9 | 11 | 9 | 7 |
- 施放法术或玩家被淘汰时，法术**返还池中**（不超该 tier 上限）。
- 法术池按酒馆等级分布：

| 酒馆等级 | 法术数量 |
|---------|---------|
| Tier 1 | 8 |
| Tier 2 | 6 |
| Tier 3 | 16 |
| Tier 4 | 16 |
| Tier 5 | 16 |
| Tier 6 | 5 |
| Tier 7 | 4 |

#### 3.6.2 酒馆展示

- 每次刷新酒馆时，**固定提供 1 张酒馆法术**（外加随从）。
- 酒馆法术的可选范围 ≤ 当前酒馆等级。
- 冻结操作同时影响随从和法术。

#### 3.6.3 费用

- 酒馆法术具有独立的金币费用，**范围 1-5 金**。
- 费用存储在 `GameTag.COST` 中（与随从的 3 金购买费用不同）。
- 费用可能被卡牌效果修改（如 Ominous Seer "the next Tavern spell you buy costs (1) less"）。

#### 3.6.4 购买流程

1. 玩家从鲍勃的酒馆中选择法术并支付其金币费用。
2. 法术从酒馆移入手牌。
3. 法术在手上**跨回合保留**（不同于 Spellcraft 临时法术，后者回合结束自动清除）。

#### 3.6.5 施放流程

1. 玩家从手牌打出酒馆法术。
2. 法术立即生效（类似标准模式法术），然后移出游戏。
3. 施放时广播 `TAVERN_SPELL_CAST` 事件（供 "Improves after you cast a Tavern spell" 卡牌使用）。
4. 施放时递增 `TAVERN_SPELLS_CAST_THIS_TURN` 计数器（每回合重置）。

#### 3.6.6 与 Spellcraft 的区别

| 属性 | 酒馆法术 | Spellcraft 法术 |
|------|---------|---------------|
| 来源 | 鲍勃的酒馆（刷新/购买） | 随从的 Spellcraft 关键词生成 |
| 费用 | 1-5 金 | 免费 |
| 跨回合保留 | 是 | 否（回合结束自动清除） |
| 池管理 | 共享法术池 | 不属于池 |
| 标签 | — | `SPELLCRAFT_SPELL = True` |

#### 3.6.7 费用分布

法术费用按酒馆等级大致分布：

| 费用 | 典型法术 | 常见等级 |
|------|---------|---------|
| 1 金 | Tavern Coin、Careful Investment、Fleeting Vigor | T1-T5 |
| 2 金 | Shiny Ring、Chef's Choice、Enchanted Lasso | T2-T5 |
| 3 金 | Armor Stash、Hasty Excavation、Strike Oil | T3-T6 |
| 4 金 | Azerite Empowerment、Sacred Gift、Planar Telescope | T4-T6 |
| 5 金 | Golden Touch、Bargain Bundle、Hallowed Ritual | T5-T7 |

---

## 4. 战斗阶段（Combat Phase）

### 4.1 战斗流程概览

1. **战斗开始前**：触发所有"战斗开始时（Start of Combat）"效果。
2. **确定先攻方**：随从数量多的一方先攻击；数量相同则随机决定。
3. **交替攻击**：双方从左到右轮流攻击，直到至少一方无存活随从。
4. **伤害结算**：胜方对败方造成基于存活随从的伤害。

### 4.2 战斗开始前效果触发顺序

多个来源的 Start of Combat 效果按以下优先级触发：

1. **饰品（Trinkets）** — 于 Patch 30.6 调整，饰品现在在**最早**触发
2. **任务奖励（Quest Rewards）**
3. **随从的 Start of Combat 效果**
4. **英雄技能（如 Illidan 的左右攻击）**

### 4.3 攻击顺序

- 攻击方从最左侧的**存活且可攻击**的随从开始。
- 双方**交替攻击**，每次只有一个随从出手。
- 新召唤的随从（如亡语产生）会按照其位置加入攻击序列。
- **攻击力为 0 的随从跳过其攻击**。

### 4.4 目标选择

- **默认情况**：攻击目标完全**随机**选择敌方存活随从。
- **存在嘲讽时**：攻击方必须优先选择具有**嘲讽（Taunt）**的敌方随从。如果有多个嘲讽，随机选择其中一个。
- **极少数例外**：某些随从效果可以无视嘲讽直接攻击指定目标（如 Zap Slywick 攻击最低攻击力随从）。

### 4.5 攻击伤害结算

- 攻击是**同时双向**的：攻击者对目标造成伤害，同时目标对攻击者造成反击伤害。
- 攻击力决定造成的伤害值。
- 伤害触发各种关键词效果（圣盾、剧毒、猛毒、复生等）。

### 4.6 战斗结束条件

战斗在以下任一情况发生时结束：

1. 至少一方没有存活随从。
2. 双方都没有存活随从（平局）。
3. 双方仅剩攻击力为 0 的随从（平局）。

### 4.7 平局处理

- 如果双方都没有存活随从，或仅剩 0 攻随从，则该回合为**平局**。
- 平局时**不造成任何伤害**。

### 4.8 克尔苏加德（Kel'Thuzad / Ghost）

- 当玩家死亡后，其**最后一场战斗的阵容**会变成"幽灵"（Kel'Thuzad）。
- 存活的玩家可能匹配到这个幽灵。
- 幽灵阵容**不会成长或变化**，保持死亡时的状态。
- 这相当于给存活玩家一个"休息回合"，但强大的幽灵仍可能造成致命伤害。
- 每 3 个战斗回合中，你不会连续两次面对克尔苏加德（除非只剩 2 名玩家）。

### 4.8a 配对时机与"对手引用"（下一对手 / 上一对手）

- **配对在招募阶段开始时确定**：玩家在招募期就能看到本回合的对手
  （酒馆内的"下一对手"预览），本回合的战斗结算沿用同一份配对。
- 引擎契约（`hsrl2/game.py`）:
  - `game.next_opponent(hero)` — 本回合对手（招募期开始时已确定;
    幽灵战/未配对 → `None`）
  - `game.next_opponent_warband(hero)` — 下一对手**当前**战团
    （Scabbs "I Spy: Discover a plain copy of a minion from your
    **next** opponent's warband"）
  - `game.last_opponent(hero)` — 上一场战斗对手（幽灵战 → `None`）
  - `game.last_opponent_warband(hero)` — 上一场对手的战前战团快照
    （Tess "Bob's Burgles ... your **last** opponent's warband"、
    任务奖励 R806; 幽灵战记幽灵阵容）
- 依据: 三张卡的数据文本显式区分 "next opponent"（Scabbs、Murloc
  Holmes "your next opponent had last combat"）与 "last opponent"
  （Tess、R806）——单一"事后快照"无法同时满足两种引用，故配对必须
  在招募期内即已确定并缓存（2026-09-02 对抗审查裁定）。
- 幽灵战（奇数存活者）没有对手 Hero 实体，故 `next_opponent` /
  `last_opponent` 为 `None`，而 `last_opponent_warband` 仍返回幽灵的
  冻结阵容。
- Murloc Holmes 读"下一对手**上一场战斗**的阵容" =
  `next_opponent(hero).last_combat_board`。

---

## 5. 伤害计算与伤害上限

### 5.1 伤害计算公式

胜者造成的伤害 = **胜者当前酒馆等级** + **所有存活随从的酒馆等级之和**

- Token（不可购买的召唤物）始终按 **Tier 1** 计算。
- 金色随从**不**获得额外的伤害加成。

### 5.2 伤害上限（Damage Cap）

伤害上限仅适用于**单打模式**，在特定回合限制单次战斗造成的最大伤害：

| 回合 | 伤害上限 |
|------|---------|
| 第 1-3 回合 | 5 点 |
| 第 4-7 回合 | 10 点 |
| 第 8 回合及以后 | 15 点 |
| 剩余 4 人时 | **取消上限** |

**注意**：一旦存活玩家数 ≤ 4，伤害上限完全移除，无论当前是第几回合。

---

## 6. 核心关键词机制

以下机制按官方描述的精确语义进行定义。HSRL 引擎中每个机制都有独立的标准示例卡牌和测试用例。

### 6.1 Taunt（嘲讽）

> **官方描述**：Enemies must attack this minion.

- 当敌方进行攻击时，如果场上存在嘲讽随从，攻击者**必须**选择嘲讽随从作为目标。
- 多个嘲讽存在时，在嘲讽池中**随机**选择。
- 嘲讽随从本身没有额外的战斗属性，纯粹是目标选择机制。

### 6.2 Divine Shield（圣盾）

> **官方描述**：The first time a Shielded minion takes damage, ignore it.

- 圣盾会**完全抵消**随从受到的**第一次伤害实例**。
- 圣盾被触发后，该随从失去圣盾状态，后续伤害正常结算。
- **关键交互**：如果伤害被圣盾完全抵消（即实际造成 0 点伤害），则**剧毒（Poisonous）不会触发**，因为剧毒要求"造成伤害"。

### 6.3 Poisonous（剧毒）

> **官方描述**：Destroy any minion damaged by this.

- 具有剧毒的随从对任何目标造成伤害时，该目标**立即死亡**，无视其剩余生命值。
- 剧毒触发的前提是**实际造成了伤害**（即伤害值 > 0）。
- **与圣盾的交互**：如果目标有圣盾且伤害被完全抵消，则剧毒不触发。
- 剧毒是**永久性**的，每次攻击都会触发（只要造成伤害）。

### 6.4 Venomous（猛毒）

> **官方描述**：Kill the target if this survives combat.

- 猛毒是剧毒的"一次性"变体。
- 具有猛毒的随从造成伤害后，如果**该随从在伤害结算后仍然存活**，则目标死亡。
- 如果猛毒随从在反击中死亡，则猛毒效果不触发。
- 猛毒在生效一次后即被消耗（随从失去猛毒）。

### 6.5 Reborn（复生）

> **官方描述**：Resurrects with 1 Health the first time it dies.

- 具有复生的随从第一次死亡时，会在**原位置**重新召唤一个自身复制。
- 复生后的随从生命值为 **1**（而非满血）。
- 复生后的随从**失去复生关键词**（不会再次触发）。
- 复生属于死亡处理的一部分，在亡语之前或之后触发（视具体实现，HSRL 采用亡语后复生的顺序）。
- 复生随从保留所有其他状态、增益和关键词（除了复生本身）。

### 6.6 Windfury（风怒）

> **官方描述**：Can attack twice each turn.

- 具有风怒的随从在每个战斗回合中可以**连续攻击两次**。
- 两次攻击之间不会插入敌方的攻击（除非该随从在第一次攻击后死亡）。
- 风怒是**永久性**的，每回合都生效。

### 6.7 Mega-Windfury（超级风怒）

> **官方描述**：Can attack four times each turn.

- 超级风怒允许随从每回合攻击 **4 次**。
- 该机制已**退役**（Retired），标准卡池中不再出现，但引擎保留支持以便处理历史数据或特殊模式。

### 6.8 Cleave（顺劈）

> **官方描述**：Also damages the minions next to whomever he attacks.

- 具有顺劈的随从攻击目标时，还会对目标**相邻的随从**造成等同于其攻击力的伤害。
- 顺劈伤害是独立的伤害实例，也会触发相应的关键词交互（如破盾、剧毒等）。
- 顺劈是攻击者一方的效果，目标进行反击时**不会**触发顺劈。

### 6.9 Deathrattle（亡语）

> **官方描述**：Does something when it dies.

- 亡语在随从死亡时触发。
- 可以产生各种效果：召唤新随从、造成伤害、增益友方随从等。
- 亡语触发的召唤物会立即加入战斗序列（按位置从左到右参与攻击）。
- 多个亡语按顺序依次触发。

### 6.10 Battlecry（战吼）

> **官方描述**：Does something when you play it from your hand.

- 在酒馆战棋中，战吼在**招募阶段**购买并打出随从时触发。
- 战吼效果在招募阶段即生效，属于**永久性增益**。
- 通过三连或 Discover 获得的随从在打出时也会触发战吼。

### 6.11 Avenge (X)（复仇）

> **官方描述**：Does something after X friendly minions die in a single combat.

- 复仇是酒馆战棋**专属机制**。
- 计数器追踪本场战斗中死亡的**友方随从数量**。
- 当死亡数达到 **X** 时，触发效果，计数器重置为 0。
- 计数不可以在多个战斗回合间累积。
- 复仇效果可以非常多样：获得圣盾、召唤随从、获得金币、永久增益等。

### 6.12 Start of Combat（战斗开始时）

> **官方描述**：Does something at the beginning of the Combat Phase.

- 在战斗阶段正式开始、任何随从发动攻击**之前**触发。
- 可以产生各种效果：增益友方随从、召唤复制、对敌方造成伤害等。
- 所有"战斗开始时"效果在攻击顺序确定之前一并处理。

### 6.13 Spellcraft（法术塑造）

> **官方描述**：Gain a temporary spell every turn.

- 法术塑造是纳迦（Naga）种族的专属机制，于 Patch 23.2 引入。
- 具有法术塑造的随从每个回合（招募阶段开始时）给予玩家一张**临时法术**。
- 临时法术提供的增益**持续到下一个招募阶段开始**。
- 如果回合结束未使用，法术塑造法术会从手牌中消失。
- 打出法术塑造随从时**立即**获得第一张法术。
- 手牌满时，法术会"等待"直到有空位，不会被销毁。
- **金色法术塑造随从**会产生金色的法术版本，效果翻倍。

### 6.14 Magnetic（磁力）

> **官方描述**：Can attach to friendly Mechs.

- 磁力是机械（Mech）种族的专属机制。
- 具有磁力的机械随从可以"吸附"到另一个友方机械身上。
- 吸附后，两个随从的**攻击力和生命值相加**，效果合并。
- 被吸附的随从保留其所有增益和状态。
- 合并后的随从仍视为一个随从占用一个格子。

### 6.15 Blood Gem（鲜血宝石）

> **官方描述**：Give a friendly minion +1/+1.

- 鲜血宝石是野猪人（Quilboar）种族的专属机制。
- 鲜血宝石是可使用的法术牌，效果为给友方随从 +1/+1。
- 许多野猪人随从会生成或与鲜血宝石互动。
- 鲜血宝石的效果可以通过某些卡牌或奖励进行增强（如额外 +2/+2）。

### 6.16 Rally（集结）

> **官方描述**：After this minion attacks, do something.

- 集结于 Season 11 (Patch 30.x) 正式成为关键词。
- **精确时机**：集结在随从宣告攻击时触发，**在伤害结算之前**。这与"攻击后"不同——集结效果先于攻击伤害结算。
- 集结效果可以触发各种后续效果：移除关键词、对目标造成额外伤害、给其他随从加 Buff、触发鲜血宝石、获得属性等。
- HSRL 引擎实现位置：`Attack.do()` 在 `BEFORE_ATTACK` 广播后、`Hit` 排队前触发 Rally。`game._last_attack_target` 在 Rally 触发前设置，供脚本引用攻击目标。

### 6.17 Freeze（冻结）

- 在酒馆战棋中，"冻结"指锁定鲍勃酒馆中的当前随从阵容。
- 被冻结的随从在下次刷新时不会更换。
- 冻结操作**免费**。

### 6.18 Discover（发现）

- 发现允许玩家从随机三张卡牌中选择一张加入手牌。
- 三连奖励使用发现机制，让玩家从**更高一级酒馆**的三张卡牌中选择。
- 发现池受共享随从池限制：池中没有的随从不会出现在发现选项中。

### 6.19 属性光环（Aura）的作用域
- 引擎统一口径：`hero.race_auras`（`ApplyRaceAura`）对**棋盘 + 手牌 +
  之后获得的**全部匹配随从实时生效——即 "wherever they are" 语义
  （`Minion._aura_atk` / `_aura_health`）。
- 因此 "Your minions have +X/+Y" 与显式写 "wherever they are" 的卡
  共用同一作用域；差额只体现在手牌内显示的属性，不影响战斗/池/经济。
- 依据与不确定性：酒馆战棋的手牌展示同样显示光环加成，且引擎自
  `ApplyRaceAura` 引入以来即为该语义（Enigmatic Headstone / Feral
  Talisman / Artisanal Urn 等既有卡共用）。**若后续取得官方反证
  （无 "wherever they are" 后缀 = 仅棋盘），改法为给 `ApplyRaceAura`
  增加 scope 字段并逐卡声明。** 该裁定台账同步记录在
  `hsrl2/scripts/batches/batch_trinkets3.py` 模块 docstring（A1–A7）。
- 种族匹配规则: 随从种族 == 光环种族 或 任一侧为 `ALL`; 光环种族为
  `ALL` 时命中所有随从（含无类型 `NONE`）。

### 6.20 额外触发（Extra Trigger）配额

- 文本族: "Your end of turn effects trigger an extra time" /
  "Your Start of Combat effects trigger an extra time" /
  "Your first Deathrattle each combat triggers an extra time" /
  "Your first spell each turn casts an extra time" /
  "Your first two Spellcraft spells each turn cast an extra time" /
  "Your Dragons' Battlecries trigger an extra time" /
  "You can use your Hero Power an extra time each turn"。
- 引擎契约（`hsrl2/hero.py` 的 `extra_triggers` / `extra_trigger_used`
  两个 hero 级字典，脚本侧只写永久**额度**，引擎消费"已用次数"）:

  | key | 语义 | 引擎消费点 | 重置 |
  |---|---|---|---|
  | `eot_extra` | 每个己方 EoT 效果额外触发 N 次 | `end_recruit_phase`（与 Drakkari 叠加） | — |
  | `soc_extra` | 每个己方 SoC 效果额外触发 N 次 | `CombatScheduler._start_of_combat_phase` | — |
  | `soc_first` | 每场战斗**前 N 个**己方 SoC 效果各额外触发 1 次 | 同上（按既有顺序: 饰品→奖励→棋盘→手牌 hand_soc） | 每场战斗 |
  | `dr_first` | 每场战斗**前 N 个**己方亡语各额外触发 1 次 | `_process_single_death`（仅战斗内） | 每场战斗 |
  | `spell_first` | 每回合**前 N 个**己方法术额外结算 1 次 | `_finish_play_spell` | 每回合 |
  | `spellcraft_first` | 同上，仅法术塑造（Spellcraft）法术 | 同上（按 `SPELLCRAFT` tag 分流） | 每回合 |
  | `hp_uses` | 英雄技能每回合可用次数 +N | `use_hero_power`（叠加在 `uses_per_turn` 上） | — |
  | `hp_times` | 单次使用的技能效果**结算次数** +N（"Your Hero Power triggers twice"——Ancient Wishbone `BG30_MagicItem_804`；与"多使用几次"的 `hp_uses` **独立**，两者可叠乘） | `_finish_hero_power`（`1 + extra_trigger("hp_times")` 次） | — |
  | `dr_extra` | 每个己方亡语额外触发 N 次（与 Titus 叠加） | `_process_single_death` | — |
  | `rally_extra` | 每个己方 Rally 效果额外触发 N 次 | `game.run_rally`（攻击宣告/招募期攻击两处） | — |
  | `bc_times` | 全部己方战吼额外触发 N 次（Gilnean War Horn） | `_finish_play_minion` | — |
  | `bc_times_race` + `bc_race` | **种族限定**的战吼额外触发 N 次（Dragon's Eye）；与全局 `bc_times` **独立叠加**（2026-09-02 D3: 旧版单 `bc_race` 会让种族限定改写全局配额） | 同上 | — |
  | `bc_first` (+ `bc_first_times`) | **每回合前 N 个**战吼各额外触发 **M** 次（War Drum 36.2.2 文本 "One Battlecry each turn triggers **two** extra times. ({0} left!)" → `bc_first=num(0)=1` + `bc_first_times=num(1)=2`）; `bc_first_times` 缺省 1。每回合开始重置 `extra_trigger_used`，与永久全量的 `bc_times` 独立（脚本侧不得为"每回合"语义复用 `bc_times`——会覆盖其它来源） | `_finish_play_minion` | 每回合 |

- 叠加: 额外触发与既有 doubler（Brann/Titus/Drakkari）**累加**——
  Drakkari 让每个己方 EoT 效果再触发 2 次（金色 3 次），`eot_extra`
  在此之上再加 N。
- **消费口径（对抗审查修正后）**: "前 N 个效果"类配额（`soc_first` /
  `dr_first`）只在实体**确有对应钩子**时消费（`_has_soc_hook` /
  `_has_deathrattle_hook`，含磁力栈叠）; `spell_first` 与
  `spellcraft_first` 是**两个独立配额**，法术塑造法术同时属于"spell"
  故可同时消费两者（1 次施放最多额外结算 2 次 = 共 3 次）;
  `rally_extra` 每次 Rally 宣告各触发一次; `bc_first` 同理只在实体
  **确有战吼**时消费（`_has_battlecry_hook`: `BATTLECRY` tag 或
  `battlecry` 脚本钩子，含磁力栈叠）——先打一张白板不再吃掉配额
  （2026-09-02 对抗审查证伪 War Drum `BG32_MagicItem_416`）。
- **统一亡语入口 `game.trigger_deathrattle(target, *, hero=None,
  position=0, count=True)`**: 真实死亡（`_process_single_death`）与
  一切 "Trigger a Deathrattle" 效果（Floating Candle Set
  `BG36_MagicItem_208t` 法术 / Deathstrider / JaWS / Secret Schematic）
  **必须**走同一入口——Titus `DEATHRATTLE_DOUBLER` 倍率、`dr_extra`、
  `dr_first`、`COUNTER_DEATHRATTLES` 计数与 `deathrattle_trigger` 广播
  全部生效。脚本直调 `run_script_hook(m, "deathrattle")` 属缺陷
  （2026-09-02 对抗审查证伪: Plaguerunner 亡语增量在 Titus 在场与不在场
  同为 +4）。
- **计数/广播资格（2026-09-13 对抗验证）**: `COUNTER_DEATHRATTLES` 与
  `deathrattle_trigger` 的资格 = 实体带 `DEATHRATTLE` tag **或** 其脚本
  有 `deathrattle` 钩子（含磁力栈同钩子）。仅按 tag 判定会漏计
  "只有钩子"的实体（Fish of N'Zoth `TB_BaconShop_HP_105t` / 金色
  `TB_BaconUps_307`），令 Falling Sky Golem `BG35_342` 与 Dark Gift
  "Death's Embrace" 少计。
- **已知作用域限制**: SoC 配额只覆盖**脚本钩子**路径（饰品/任务奖励/
  棋盘随从/手牌 `hand_soc`）; 以 `start_of_combat` 事件**监听器**实现的
  法术类效果（BG31_889 Sharing is Caring / BG28_573 Upper Hand /
  BG28_603 Boon of Beetles 等）暂不在覆盖内——需为监听器型 SoC 建立统一
  登记点后补齐（引擎架构改动，尚未排期）。
- 裁定（"once per game" 与额外次数）: 技能声明 `uses_per_game = N` 时
  `hp_uses` 的额外次数不得突破每局上限（"Once per game" 是硬上限，
  额外次数只放宽每回合上限）。
- 覆盖卡: Ghastly Sticker（`eot_extra`）/ Valdrakken Wind Chimes
  （`soc_extra`）/ Promo Portrait（`soc_first`）/ Deathly Phylactery
  （`dr_first`）/ Replica Cathedral（`spell_first`）/ Spitescale Sushi
  Roll（`spellcraft_first`）/ Sous Chef Sticker（`hp_uses`）/
  Dragon's Eye（`bc_times` + `bc_race=DRAGON`）/ Gilnean War Horn
  （`bc_times` 全局）/ Turbulent Tombs（`dr_extra`）/ Rallying Cry
  （`rally_extra`）。
- 实现见 `hsrl2/tests/test_engine_gaps.py::TestExtraTriggerQuotas`。

### 6.21 Transform（变身）与被动的重接线

- `Transform(target, new_card_id, keep_buffs=, gilded_not_tripled=)`
  （`hsrl2/actions/stats.py`）: 原位替换实体、金色状态继承、旧实体
  `zone=REMOVED` 并注销其全部监听器、广播 `transform`。
- **裁定**: Transform **不**触发召唤类（`on_summon`）与战吼类效果
  （官方语义: 变身不是召唤），但新实体的**被动**能力必须立即生效——
  引擎在 `transform` 广播后调用 `run_script_hook(new, "on_transform",
  ctx={"old": old})`。
- 脚本契约: 凡在 `on_summon` 里**注册持久监听器或设置被动 tag** 的卡
  （Titus / Brann / Drakkari 的 doubler tag、Groundbreaker 的
  "After you play a Naga" 监听等）必须同时实现 `on_transform`（通常
  直接复用同一安装函数）。缺失该钩子的脚本为 no-op。
- **战斗内变身的持久性**（RULES §3.5 的例外）: 变身是**永久卡身份变更**
  （非战斗 buff）——`Transform` 在战斗内执行时记入 `game._combat_transforms`，
  `run_combat` 复原棋盘后**原位换回**新实体（清 DEAD/攻击资格、血量回满）
  并重跑 `on_transform`（监听器表已被快照覆盖，被动须重新注册）。
  依据: "Start of Combat: Make your highest-Tier Dragon Golden"（Yu'lon
  Sticker `BG32_MagicItem_419`）的金色化必须跨战斗保留；旧实现
  `hero.board = list(board_before[hero])` 会把它回滚。
- 反例（旧实现缺陷）: 变身成 `BG31_035` Groundbreaker 后打纳迦 → 本体
  不增益，只有镜像饰品（`BG35_MagicItem_924`）增益（2026-09-02 对抗
  审查证伪）。修复后本体与左邻镜像同步。
- 实现见 `hsrl2/tests/test_engine_primitives.py::TestTriggerDeathrattleEntry`
  同文件的 `test_transform_reruns_passive_init`。

### 6.22 监听器生命周期：离场即注销（区域赋值单一收口）

- **契约（离场方向）**: 监听器的生命周期宿主是实体本身
  （`events.register(Listener(owner=实体))`）。实体**从棋盘离场**（`PLAY` →
  手牌 / 酒馆 / `REMOVED` / `GRAVEYARD`）时其监听器立即注销（"光环
  生命周期"，`hsrl2/entity.py` 首段既有契约）; **随从**从**任何**区域进入
  `REMOVED`/`GRAVEYARD`（永久离场）同样立即注销。
  **反向不成立**: "持久监听器只在实体位于棋盘（`PLAY`）期间生效"**不是**
  引擎的普遍保证——在**离场期**（手牌/酒馆）注册的监听器本就不依赖
  `PLAY`（Dark Gift `_make_counter_gift`、`on_enter_hand` 被动、
  `LOCKED_IN_HAND` 解锁 tick），见下"边界"。
- **实现收口**: `Entity.zone` setter 是**唯一的区域赋值出口**（`__init__`
  的 `Zone.INVALID` 初始化除外; 无任何脚本/动作直接写 `GameTag.ZONE`）。
  满足下列任一条件即自动 `game.events.unregister_owner(self)`:
  (i) **随从**新值 ∈ {`REMOVED`, `GRAVEYARD`}（自任何区域——覆盖 Malygos
  Arcane Alteration 的手牌 → `REMOVED` 等从未上过棋盘的路径）;
  (ii) 旧值 `Zone.PLAY` 且新值 ∉ {`PLAY`, `SETASIDE`}。所有
  `x.zone = Zone.*` 的离场赋值因此自动注销，无需每个脚本/动作显式调用
  （既有显式调用变为幂等冗余）。`Zone.SETASIDE` 例外: 它是复生处理期间的
  **临时**离场（同一实体稍后回 `Zone.PLAY`，不重跑 `on_summon`），其监听器
  必须保留; **`Spell` 不在 (i) 之列**（见下"不受影响"）。
- **不受影响**: 英雄 / 饰品 / 任务奖励实体的 `zone` 恒为 `Zone.INVALID`
  （不参与棋盘区域系统），其跨回合持久监听器照旧。法术实体可处于
  `Zone.HAND`（手牌法术）或 `Zone.TAVERN`，但**从不进入 `PLAY`**; 法术
  owner 在 `on_play` 注册的监听器是**效果期接线**（如 Chillmere Mosaic
  法术的 `TURN_END` 清除本回合费用规则），必须活过
  `_finish_play_spell` 末尾的 `zone = Zone.REMOVED`——故引擎级"任何区域 →
  `REMOVED` 即注销"刻意只覆盖随从。**销毁**一张手牌法术（如 Malygos 的
  替换，非"打出后的常规结算终态"）由该路径显式 `unregister_owner`。
  他者（饰品/英雄）注册的、**引用**某随从的监听器 owner 不是该随从，
  不随该随从离场注销。
- **战斗快照的两处补充**: `Game.run_combat` 会快照并复原监听器表——
  (a) 战斗内 `Transform` 的旧实体在战后重放换出棋盘时显式置
  `zone=REMOVED`（否则 `restore_state` 把它留在 `PLAY` 且监听器被快照
  复原）; (b) 复原后仍处 `REMOVED`/`GRAVEYARD` 的**随从**（战斗期间永久
  离场者）的监听器被丢弃（快照复原不看 owner 存活状态）——该收口优先于
  `survives_combat` 的重新挂回: 后者只保证"**快照回滚**不抹掉战斗内接线
  的持久监听器"，不保证"已永久离场实体的监听器可以复活"。
- **边界（离场期监听器）**: 在**离场期**（手牌/待入手）注册的监听器不由
  "从棋盘离场"触发（它们本就不在棋盘上）——例如 `LOCKED_IN_HAND` 解锁
  tick（owner=手牌随从）、Dark Gift 在 `pending_hand_add` 前注册的 gift
  监听器、`on_enter_hand` 注册的被动; 宿主仍在手牌/酒馆时它们照常存活并
  按各自回调生效（`_make_card_played_gift` 带 `zone != PLAY` 守卫）。
  但宿主一旦进入 `REMOVED`/`GRAVEYARD`（永久离场）即被 (i) 注销——这正是
  Malygos 替换手牌随从的缺陷修复（此前一个 Dark-Gifted 手牌随从被移入
  `REMOVED` 后监听器残留，继续在后续事件里改写其属性）。
- **裁定**: 故**不**采用"事件分发时按 owner 的 zone 惰性失效"方案——
  它会连带让仍在手牌/酒馆的离场期监听器（手牌解锁 tick 等）失效。
- 实现见 `hsrl2/tests/test_engine_gaps.py::TestLeavePlayListenerInvariant`;
  缺陷史见 `docs/agents/ENGINE_BACKLOG.md` #40。

---

## 7. 最新赛季特殊机制（Season 13）

> **当前赛季**: Battlegrounds Season 13 — "CATACLYSM CALLS!"
> **上线日期**: 2026年4月6日
> **当前补丁**: Patch 35.2.2 (2026-04-22)

### 7.1 新关键词：Fodder（恶魔专属）

> **官方描述**：Demons with Fodder consume a specific type of minion to gain powerful effects.

- **Fodder** 是恶魔（Demon）种族在 Season 13 获得的新关键词。
- 具有 Fodder 的恶魔在**打出时**或**特定时机**会"吞噬"一个指定类型的随从（通常是从手牌或酒馆中）。
- 被吞噬的随从被移除，恶魔获得强大的永久增益或触发效果。
- Fodder 机制让恶魔流有了更强的资源转换能力，可以将不需要的随从转化为战力。

### 7.2 新关键词：Chromadrake（龙专属）

> **官方描述**：Dragons with Chromadrake transform or evolve based on board state or game progression.

- **Chromadrake** 是龙（Dragon）种族在 Season 13 获得的新关键词。
- 具有 Chromadrake 的龙随从会根据特定条件**变形**或**进化**为更强的版本。
- 触发条件可能包括：战斗开始时、回合结束时、友方龙死亡时等。
- Chromadrake 为龙族提供了后期成长的全新维度。

### 7.3 随从更新

Season 13 引入了 **48 个新随从**，并对大量旧随从进行了平衡调整：

- **恶魔**：围绕 Fodder 机制重新设计了恶魔流的核心随从。
- **龙**：围绕 Chromadrake 机制添加了新的成长型随从。
- **其他种族**：也获得了一批新随从以保持平衡。

### 7.4 饰品系统回归（Trinkets）

饰品系统于 Season 13 回归，并带有**增强规则**：

#### 7.4.1 饰品类型

| 类型 | 获取时机 | 说明 |
|------|---------|------|
| **小型饰品（Lesser Trinket）** | 第 6 回合 | 费用较低，效果相对温和 |
| **大型饰品（Greater Trinket）** | 第 9 回合 | 费用较高，效果更强大 |

#### 7.4.2 饰品规则更新（Patch 35.2）

- 所有饰品现在在卡牌底部显示其**关联的随从类型**。
- 饰品生成的卡牌在手牌满时会**等待**（与法术塑造、任务奖励一致），不会销毁。
- **类型关联规则**：
  - 第 6 回合：若战场上有 **2 个**某类型随从，则属于该类型。
  - 第 9 回合：若战场上有 **3 个**某类型随从，则属于该类型。
  - 拥有 **3 种或以上**不同类型时，属于"杂耍（Menagerie）"类型。
  - 某些英雄（如 Azshara）始终可以获取其关联类型的饰品。
- **每次提供 4 张**（Turn 6 四张 Lesser / Turn 9 四张 Greater，+1 放弃
  选项）——官方 Developer Insights "Updated Trinket Rules"
  （Mitchell Loewen, 2026-04-09）原文: "you will be offered **four**
  different Lesser Trinkets on Turn 6 and Greater Trinkets on Turn 9
  to buy with Gold"。
  https://eu.forums.blizzard.com/en/hearthstone/t/battlegrounds-developer-insights-updated-trinket-rules/12768
- 每次提供的选项中至少包含：
  - 一个**无类型**饰品
  - 一个费用 **≤ 2 金**的饰品
- 不会提供重复的饰品（**per-player** 判定: "a Trinket **you** already
  have"），但同一饰品的小型和大型版本可以同时获得。
- 每次提供中**必然包含 1 张"你所属的最常见类型"的饰品**。
- 不属于你最常见类型的饰品**至多 1 张**，且其费用 **-2**。
- **单张限制**（同一 offer 内至多出现 1 张）: Shrine of Evolution 与
  Sacrificial Altar 合计 ≤1; **Souvenir Stand / Trip Vouchers /
  Ornate Clock 合计 ≤1**; Menagerie 类型饰品 ≤1。
- 大量**条件/身份门禁**（该文列举），例如:
  - Souvenir Stand / Ornate Clock / Trip Vouchers 不对 Marin / Buttons 提供;
  - Corrupted Tome 不对 Mr. Clocksworth; Cho'Gall Sticker 不对 Cho/Gall;
    Goblin Wallet / Bob's Tip Jar 不对 Gallywix; Fish Portrait 不对 Greybough;
  - Divine Signet 需你控制带圣盾的随从; Herald Sticker / Blood Amulet /
    Unholy Sanctum / Thornspike Pauldron 需控制亡语随从;
    Gilded Anchor 需控制金色随从; Scraper Sticker / Beatboxer Portrait
    需 Tier ≥3; Lens Case 需控制 Tier 3 随从; Tiger Carving 需控制
    Trigore the Lasher / Iridescent Skyblazer / Spiked Savior / Rabid Panther 之一;
    Safety Patch 需总生命+护甲 <16; Magician's Top Hat 需手牌+棋盘 <5;
    Fancy Spellbook / Heart of the Forest 需本局 buff 过酒馆法术;
    Ur'zul Sticker / Flaming Portrait 需本局 buff 过酒馆;
    Murky Sticker 需本局多次触发战吼; Dramaloc Sticker 需手牌有 ≥10 攻随从;
    Baller Portrait 需本局出售过 Baller; Shrine of Evolution /
    Sacrificial Altar 需控制 ≥6 随从; Demonic Tapestry / The Eye of
    Sargeras / Nether Pendant / Felburned Ledger 需有生命回复(Health
    rewinder)效果; Bob-blehead 在恶魔局不可提供。
- **实现状态（引擎 `_offer_trinkets`，2026-09-02）**: 已实现"4 选 1+
  放弃 / 档位过滤 / per-player 去重 / ≥1 无类型 / ≥1 费≤2"。
  **未实现**（有权威但属"提供规则"子系统，逐条留档待办）:
  最常见类型保证、非本类型 ≤1 且 -2 费、单张限制（含 Souvenir Stand /
  Trip Vouchers / Ornate Clock 合计 ≤1）、上列条件/身份门禁。
  影响面: 仅"哪些饰品被展示"，不影响已注册脚本的语义;
  由 `hsrl2/constants.py::TRINKET_CHOICES` 与 `Game._offer_trinkets`
  承载，实现前不得声称该子系统 CORRECT。

#### 7.4.3 小型饰品示例（Turn 6 池）

- **Automaton Portrait** [5金]：获得一个 Ancestral Automaton。战斗开始时：召唤一个 Ancestral Automaton。
- **Kaboom Bot Portrait** [2金]：获得一个 Kaboom Bot。你的 Kaboom Bot 的亡语额外造成 8 点伤害。
- **Charging Staff** [3金]：每回合结束时，使你的圣盾随从获得 +4 攻击力。
- **Hoggy Bank** [3金]：战斗开始时：使你的野猪人获得"亡语：获得一个鲜血宝石"。

#### 7.4.4 大型饰品示例（Turn 9 池）

- **Valorous Medallion** [3金]：战斗开始时：使你的随从获得 +5/+5。
- **Twin Sky Lanterns** [2金]：当你有空位时，召唤你本战斗第一个召唤的随从的复制。
- **Nomi Sticker** [5金]：在你打出元素后，酒馆中的元素本局对战获得 +2/+2。
- **Spitescale Sushi Roll** [6金]：获得一个 Spitescale Special。你的法术塑造法术施放两次。

### 7.4.3 饰品获取协议（商店购买 / 直接授予 / 替换）

- **商店购买**: T6（Lesser, `spell_school=11`）/ T9（Greater, 12）三选一 +
  放弃; 购买成功广播 `trinket_bought(hero, trinket, kind)`
  （"When you buy a Lesser/Greater Trinket" 类效果的数据源）。
- **直接授予**（非商店路径，文本族 "Get a random Trinket" /
  "transform into a copy of it" / "replace this"）:
  - `game.grant_trinket(hero, trinket_id, source=)` — 唯一入口: 跨局不重复
    记账（已获得 → 返回 None）、实体入 `hero.trinkets`、跑 `on_bind`、
    广播 `trinket_granted(hero, trinket, source)`
  - `game.grant_random_trinket(hero, kind="lesser"/"greater")` — 从
    `db.trinket_offer_pool()` 中**该英雄**未获得的集合随机
  - **记账是 per-player 的**（2026-09-02 修复）: 判定一律读
    `hero.trinkets_granted`（官方 "a Trinket **you** already have"）——
    对手持有的同名饰品不得从我的候选池/商店中剔除（旧实现用 game 级
    并集，实测对手拿到 X 后我的池里 X 永久消失）。
    `game._trinkets_granted` 保留为**全桌并集**（仅观察/诊断用）
  - `game.replace_trinket(hero, old, new_id)` — 移除旧实体（注销监听器）
    后走 `grant_trinket`
  - **副本条款（"transforms into a copy of it"）**: 官方允许同一饰品
    同时持有**两份副本**（Souvenir Stand `BG30_MagicItem_888`
    "When you buy a Greater Trinket, this transforms into a copy of it"
    —— wiki bug 报告确认玩家须"HOLD BODY + COPY"，即购买所得那份保留、
    Stand 变成第二份; Crystal Ball 族 `BG35_Anomaly_007t`/`_008t`
    同样把技能槽变成所购饰品的副本）。因此:
    - `game.grant_trinket(hero, id, duplicate=True)` — 跳过跨局去重
      （仍记账 `_trinkets_granted`，商店不再提供该 id）
    - `game.copy_trinket(hero, id, replace=实体)` — 先移除/注销 `replace`
      再走副本授予
    - 副本的 `on_bind` **照常接线**（两副本的光环/监听各自注册 = 效果
      叠加，这正是副本的意义）
- 依据: 数据文本要求"免费直接获得/替换"路径与商店购买解耦; 旧的商店
  resolve 内联实现无法表达（Mystery Cube / Souvenir Stand / Trip
  Vouchers / Rune of Transmutation / Orb of the Unknown / Crystal Ball 族
  因此长期 DEFERRED; 副本条款 2026-09-02 补齐后 Souvenir Stand 解锁）。
- 实现见 `hsrl2/tests/test_engine_gaps.py::TestTrinketGrantProtocol` /
  `TestTrinketCopyProtocol`。

### 7.4.4 免费购买协议（Free Purchases）

- **免费随从购买**: `hero.set(GameTag.FREE_MINION_BUYS_THIS_TURN, N)`
  表示"本回合还能免费买 N 个随从"。可加限定:
  - `GameTag.FREE_MINION_BUY_RACE`（Race 值; Grifter Portrait "The first
    Pirate you buy each turn is free"）
  - `GameTag.FREE_MINION_BUY_KEYWORD`（GameTag 值; Warcry Totem "The
    first two Battlecry minions you buy each turn are free"）
  - 两者都未设 = 全部随从（Aranna "the first minion you buy each turn is
    free"）
  引擎在 `buy_from_tavern` 中**仅在限定匹配时**消费（不匹配不消耗）。
- **免费酒馆法术购买**: `GameTag.FREE_SPELL_BUYS_THIS_TURN`（Peacebloom
  Candle "The first {1} Tavern spells you buy each turn are free"）——
  优先于 `NEXT_SPELL_COST_REDUCTION` 且只在**成交时**消费（与折扣同守则）。
- 计数由脚本在 `on_bind`（绑定当回合）与 `start_of_turn`（每回合）写入，
  引擎不自行重置（与 `FREE_MINION_BUYS_THIS_TURN` 既有语义一致）。
- 实现见 `hsrl2/tests/test_engine_gaps.py::TestFreePurchaseProtocol`。

### 7.4.5 折扣 / 售价覆写协议（Discount & Sell Overrides）

- **持久酒馆法术折扣**: `GameTag.TAVERN_SPELL_COST_MOD`（英雄级）——
  "Your Tavern spells cost (1) less"（Beyond the Mirage）。`buy_from_tavern`
  先减持久折扣再减一次性 `NEXT_SPELL_COST_REDUCTION`; 两者都只在
  **成交**时消费（购买失败不烧折扣）。
- **额外酒馆法术展示位**: `hero._tavern_spell_extra`（**hero 级**）——
  "Your Refresh shows an extra Tavern spell"（Lubber Sticker）。
  `refresh_tavern` 优先读 hero 级、回落 `game` 级异变字段——
  饰品不得污染对手酒馆。
- **出售价覆写**: `GameTag.SELL_VALUE_OVERRIDE`（**英雄级**）——
  "Your minions sell for 0 Gold"（Uncompensated Upset）。实体自身
  `SELL_VALUE` tag 仍优先于英雄级覆写（`sell_minion` 判定顺序）。
- 一次性折扣（`NEXT_SPELL_COST_REDUCTION`）与免费额度
  （`FREE_*_BUYS_THIS_TURN`）的消费时机见 §7.4.4。
- 实现见 `hsrl2/tests/test_engine_gaps.py::TestDiscountAndSellOverrides`。

### 7.4.6 饰品关联卡协议（"Get a <卡>" / "Cast <法术>"）
- 饰品卡面里点名的卡（Portrait 族 "Get a Titus Rivendare"、Tome /
  Sticker 族 "Get a Cloning Conch" / "Cast Ice Block"）由**数据链**
  `CardDef.evolution_card_id` → `db.by_dbf` 解析（与异变"授予第二技能"
  用的同一个字段; 对饰品它指向关联卡）。**禁止**从卡名硬编码猜测 id。
- `game.trinket_related_card(trinket_id)` → 关联 CardDef 或 None;
  `game.grant_trinket_related_card(hero, trinket_id)` / 通用
  `game.grant_card_copy_to_hand(hero, card_def)` → 授予**白板**副本进手牌。
- **池记账**（与 `{0}` 奖励副本 batch_quest_rewards4
  `_grant_reward_copy` 同一口径）: 池随从/池法术先 `acquire` 占池，
  池中无副本 → 本次获取**落空**（RULES §2.4）; 非池卡（token / 池外
  专属卡）→ 零池操作。
- **"Get a X" 的 CORRECT 判定标准（2026-09-02 主线裁定）**: 本卡效果
  即为"交付卡 X"，因此只要 (a) 关联卡定义经数据链正确解析、(b) 交付
  路径正确（池随从/池法术按池占返、非池卡零池操作、满手排队）即算
  CORRECT。**关联卡自身的脚本迁移状态是那张卡的台账**（按 §7.4.6 数据
  链登记在本批 docstring 的"关联卡台账"节），不阻塞饰品注册——
  先例: `BG32_MagicItem_301` Bassgill Portrait（关联卡 `BG26_350` 未
  迁移，经对抗审查 VERIFIED_OK）、`batch_quest_rewards4` 的 `{0}` 副本。
  **例外**: 若本卡效果**依赖** X 的行为（例: "Your X's **Spellcrafts**
  are permanent" 需要 X 有 Spellcraft 脚本; "After you cast a
  **Spellcraft** spell" 需要 X 真能产生 Spellcraft 法术），则整卡维持
  DEFERRED（载荷未就绪，SOP §12 item 14）。
- **返回值语义（2026-09-02 对抗审查修正）**: `grant_card_copy_to_hand`
  返回 True = 副本**已产生**（已入手**或**已入 `pending_hand_queue`
  等待队列——队列必然交付）; False = 落空（池中无副本 / 卡定义非法）。
  "N times per game/combat" 额度类脚本据返回值扣减额度，因此**满手排队
  必须算成功**——旧语义把"已排队"与"落空"都返回 False，满手即可无限
  白拿副本（证伪: Funeral Wreath `BG36_MagicItem_217` / Transcribing
  Typewriter `BG35_MagicItem_931`）。需要"此刻是否真的已进手牌"的
  调用方自行检查 `game.pending_hand_queue`（`pending_hand_add` 的原始
  返回值仍是"是否入手"）。
- **"是否已持有 X" 判定必须双查手牌 + 等待队列**（`hero.hand` +
  `pending_hand_queue`）——满手时"已有则改用另一分支"类文本（Lockbox
  Portrait `BG36_MagicItem_301` "若已有则提前开启"）只扫手牌会在每个
  SoT 重复排队（实测 queue 1→2→3→4）。
- 实现见 `hsrl2/tests/test_engine_gaps.py::TestRelatedCardGrant`。

**tier 维度光环（2026-09-02 引擎原语）**: `game.add_tier_aura(source,
max_tier, atk, health)` —— "Your minions from Tier N or lower have +X/+Y"
（`BG30_MagicItem_843t` Horde Keychain；XML `AURA=1`）。读取点与
`hero.race_auras` 并列（`Entity._aura_atk/_aura_health`），只作用于该
英雄**棋盘上** `tech_level <= N` 的随从：对任何入板路径（summon /
`Transform` / Jandice 换入）恒生效；注册时对在场匹配随从同步抬升当前
血量（与 `ApplyRaceAura` 同口径）；source 离场（饰品被替换）后自动
失效。测试见 `TestTierAura`。

### 7.4.7 "以生命代金购买"协议（costs Health instead of Gold）

- 文本族: "One Demon each turn costs Health instead of Gold to buy"
  （`BG32_MagicItem_821`）/ "One Tavern spell each turn costs Health
  instead of Gold to buy"（`BG32_MagicItem_822`）/
  "After you Refresh {1} times, the highest-Tier minion in the Tavern
  costs Health instead of Gold to buy"（`BG35_MagicItem_152`）/
  卡自身 `CardDef.health_cost`（Hasty Excavation）。
- **支付语义**: 以该卡的**金币价**支付等量生命（护甲先扣）; 生命
  （+护甲）不足以支付且不会致死时**购买失败**——不提供"改用金币"的
  选择（与 Hasty Excavation 同口径，"costs Health instead of Gold"
  是强制替换而非可选）。
- 三种来源（`buy_from_tavern` 统一判定）:
  1. 卡自身 `health_cost`（数据字段）
  2. 实体级 `GameTag.HEALTH_BUY`（给**当前酒馆中**某个随从打标——
     刷新后需重新打标）
  3. 英雄级本回合配额: `GameTag.HEALTH_MINION_BUYS_THIS_TURN` +
     `GameTag.HEALTH_BUY_RACE`（种族限定; 未设=不限; 全种族随从视为
     匹配，RULES §8）/ `GameTag.HEALTH_SPELL_BUYS_THIS_TURN`
- 配额只在**成交**时消费（生命不足 / 免费购买 cost=0 均不消费）;
  每回合重置口径与 `FREE_*_BUYS_THIS_TURN` 一致（脚本在 `on_bind` /
  `start_of_turn` 写入，引擎不自行重置）。
- 实现见 `hsrl2/tests/test_engine_gaps.py::TestHealthPurchaseProtocol`。

### 7.4.6b 获得卡牌事件（`card_gained`）

- `hero.add_to_hand` 成功入手时广播 `card_gained(hero=, card=)`
  （hero 级"获得一张牌"的观察点；此前只有实体级 `on_enter_hand`）。
- 用于 "After you get a card" 类效果（`BG35_MagicItem_713` Trusty Crowbar）。
- 触发范围: 购买/发现/生成/复制等**所有**入手指经（`pending_hand_add` /
  `buy_from_tavern` / `hero.add_to_hand`），满手入队时不广播（尚未获得）。
- 实现见 `hsrl2/tests/test_engine_gaps.py::TestCardGainedEvent`。

### 7.4.6d 发现完成事件边界（`card_discovered`，2026-09-13）

- `PendingChoice.choose` 在 `kind` 以 `"discover"` 开头、或 `kind ==
  "triple_reward"`、或 `kind == "dark_gift"` 时广播
  `card_discovered(kind=, hero=, option=, golden=)`。
- **例外**（`_NON_CARD_DISCOVER_KINDS`）: `discover_hero_power`
  （Cosmic Reward `BG33_Reward_017` / Finley / 异变第二英雄技能槽三选一）
  **不**广播——"After you Discover a **card**"（Hooktusk `BG36_344`）
  的"card"不含英雄技能，否则技能发现会误触发海盗增益
  （2026-09-13 对抗验证实测: 选项结算后 Hooktusk 给海盗白加 +num/GMP）。
- 自定义 `discover_*` kind（`discover_minion`/`discover_spell`/
  `discover_tavern_spell`/`discover_choose_one`）仍是卡牌发现 → 照常广播。

### 7.4.6c 元素 give-stats 加成（`ELEMENTAL_EXTRA_ATK/HEALTH`）

- 写入方: Fountain Pen `BG32_MagicItem_802`（+2/+1）/ Amplifying Essence
  `BG36_MagicItem_380`（+num(1)/+num(2)，每 5 元素 improve）/
  Sand Swirler `BG32_841` / Glowing Cinder `BG32_842` /
  Moat Custodian `BG36_351`。
- **唯一消费点** `hsrl2/actions/racefx.py::elemental_give_bonus(source)`:
  仅当**给予者本身是元素**（`race ∈ {ELEMENTAL, ALL}`）时返回
  `(extra_atk, extra_health)`；调用方把它叠加到自己的 give-stats 数额上。
- **必须接线的全部给予者**（2026-09-02 对抗审查 F1: 曾只接 5 张）:
  Dancing Barnstormer `BG26_162` / Unleashed Mana Surge `BG32_846` /
  Fire·Snow·Air Baller `BG31_816`/`_818`/`BG36_181` / Waveling `BG34_856` /
  En-Djinn Blazer `BG34_865` / Stone Age Slab `BG34_950` /
  **Motley Phalanx `BG27_080` / The Last One Standing `BG34_320` /
  One-Amalgam Tour Group `BG30_102`**（三张 `Race.ALL` 卡：ALL 视为元素）。
- **裁定（"give" vs "gain"）**: 文本是 "Your Elementals that **give** stats
  grant an extra +X/+Y" → **自增益**（"gain"）不算给予，故
  Living Prison `BG36_180` / Molten Rock `BGS_127` / Unbound Tempest
  `BG36_352` / Meteorite Crasher `BG31_843` **不吃加成**。
- 实现见 `hsrl2/tests/test_batch_trinkets24.py::TestFountainPen`
  （含 ALL 给予者覆盖回归）。

### 7.4.7a Spellcraft 永久化规则（被动实体）

- `game.add_permanent_spellcraft_rule(hero, source, predicate)` ——
  "Your Thaumaturgists' **Spellcrafts** are permanent"
  （`BG32_MagicItem_920` Thaumaturgist Portrait）。
- 机制: 生成 Spellcraft 法术时对**来源随从**求值 `predicate`（命中的法术
  标记 `permanent_spellcraft`）→ 该次施放对目标的 `temporary` buff 翻转
  为永久（复用 Lava Lurker 的永久化拦截窗口），且 `_expire_at_next_turn`
  不会回收（`scripts/spells.py` 已跳过 `temporary=False`）。
- 生命周期: 读取规则时校验 `source` 仍属于该英雄（饰品被替换即失效）。
- **关键词口径（2026-09-14 第二十三轮）**: "permanent" 不只保留 temporary
  **buff**，也保留临时**关键词**。`BG32_MagicItem_933` Weary Portrait
  （"Your Weary Mages' Spellcrafts are permanent"）的载荷 Reinvigoration
  是 "+2/+2; 若是纳迦额外给 **Reborn** until next turn"——+2/+2 本就永久，
  唯一临时项是 Reborn。权威: 34.0.1 官方 hotfix（2025-11-03）
  "Lava Lurker now retains Reborn from Weary Mage's Reinvigoration
  Spellcraft"（同机制; wiki `Battlegrounds/Lava_Lurker` Bug fixes 节）。
  实现: 载荷脚本 `on_play` 读 `spell.permanent_spellcraft` 为真时**不注册**
  Reborn 的 `TURN_START once` 过期监听（关键词过期由载荷自身注册，非
  `clear_temporary_buffs`）。
- **时序**: 法术可能在本回合**早于**饰品生成/入手 → 施放路径需在
  `spell_resolving` 前反查来源随从（`spellcraft_source_uuid` +
  `_permanent_spellcraft_matches`）并**回写** `spell.permanent_spellcraft`
  （载荷脚本读同一标记; 2026-09-14 补回写）。
- **效果施法入口（2026-09-14 第二十四轮补齐）**: `cast_spell_effect(hero,
  card_id, target=None, source=None)` 的 `source` 传原始法术实体 → 继承
  `spellcraft_source_uuid` 并复用 `_resolve_cast_permanence`（与手牌路径同
  一函数），两族在重施放场景下同样永久化; 调用方不传 `source` 时来源不可
  知 → 不永久化（残余契约，见 `ENGINE_BACKLOG` #26）。
- 既有对照实现（单个随从自永久化）: Lava Lurker（`batch_unfreeze`）用
  `spell_resolving` 自行设置 `_permanence_pending`。
- 实现见 `hsrl2/tests/test_engine_gaps.py::TestPermanentSpellcraftRule`。

### 7.4.7b 效果施法（"Cast X"）统一入口

- `game.cast_spell_effect(hero, card_id, target=None)` —— 非手牌打出的
  "施放法术"（Lavish Cape / Cagey Conjurer / Rally 施法等）。
- 裁定（`batch_rally2` 先例）: 不经手牌、不耗金币、**不动法术池**（"施放
  即回池"净变化 0）、不计 `TAVERN_SPELLS_CAST_*`、不广播
  `tavern_spell_cast` / `card_played` / `spell_bought`。
- 定向法术（脚本 `needs_target=True`）: `target=None` 时从
  `target_candidates`（未声明则本人存活随从）随机取一个; **无合法目标 →
  落空返回 False**（不抛错中断回合）; 显式 target 已离场同样落空。
- **会**广播 `spell_resolving`（每次施放一次——永久化拦截窗口与"施放后"
  类被动监听器据此生效，Blessing Portrait 手牌分支即依赖它）;
  **不**计 `TAVERN_SPELLS_CAST_*`、不广播 `tavern_spell_cast` /
  `card_played` / `spell_bought`（2026-09-02 对抗审查修正）。
- 实现见 `hsrl2/tests/test_engine_gaps.py::TestCastSpellEffect`。

### 7.4.8 随机数量 / 互异口径 与 "N cards" 口径（AMBIGUOUS 留档）

- **"Get N random <X>" 是否允许重复**: 目前**全仓统一按"互异"实现**
  （`game.rng.sample` 无放回: Spitescale Special `BG28_606`
  "Get 3 random Spellcraft spells"、Mecha-Jaraxxus Sticker
  `BG30_MagicItem_942` "Get 2 random Magnetic Mecha-Demons"）。
  与之相对，`BG32_MagicItem_282` Turbocharged Drill 的文本显式写
  "Get {0} **different** Magnetic Mechs" —— "different" 的显式存在
  **可能**暗示无该词时允许重复（独立随机、可有重复）。
  两种读法都无官方/数据权威（wiki 该卡无 Notes），**留档待实测**;
  若后续取得权威，两处需同步（`_grant_mecha_demons` /
  `SpitescaleSpecialScript`）。
- **"The Tavern always has N cards"**: 引擎实现为 N 个**随从位**
  （`hero._tavern_offer_override`，法术位另行追加 → 总牌数可达 N+法术数）。
  先例: Glowing Gauntlet `BG30_MagicItem_841`、Felbat Portrait
  `BG30_MagicItem_991`、异变 Seven Cards。wiki 无 Notes 裁定"总牌数"
  还是"随从位"; 体系级改动前保持现状。
- **"Get a X" 关联卡自身的脚本状态不阻塞饰品**（见 §7.4.6）; 但若该卡
  是文本核心（如 "Your X's Spellcrafts are permanent"），整卡维持
  DEFERRED。

### 7.4.9 酒馆入馆事件与"酒馆内随从"Buff

- **统一入馆入口 `game.add_tavern_entity(hero, entity, *,
  position=None, replace=None)`**（`refresh_tavern` 抽卡 / Fodder token
  注入 / `inject_tavern_minion` / 脚本换卡与复制全部经此）:
  - 应用 `hero.tavern_buffs` 持久酒馆 Buff（仅 `Minion` 实体，
    `TavernBuff.matches(defn)` 过滤）
  - `zone = TAVERN` + append / insert / 就地替换
  - 广播 **`tavern_entity_added`（hero=, entity=）** —— "whenever a
    minion enters the Tavern" 与所有"入馆即结算"效果的观察点。事件在
    **入馆后**广播，监听器可安全改属性/加 buff。
- **裁定（顺序无关）**: 依赖"入馆"的酒馆 Buff（"Fodders in the Tavern
  have +X/+Y" Defiler Portrait `BG35_MagicItem_151`）**不得**在
  `tavern_refresh` 事件里按实体打标 + 依赖监听器注册顺序——Laboratory
  Assistant `BG35_150` 的 Demon Fodder 由同一 `tavern_refresh` 事件里
  更晚注册的监听器入馆，顺序敏感会让它恒吃不到 Buff（2026-09-02 对抗
  审查证伪）。正确做法 = 监听 **`tavern_entity_added`**（入馆即授，
  本卡资格集命中）; 而"**刷新后**结算"型（"After the Tavern is
  Refreshed, give its minions +X/+Y this turn" Cursed Crystal
  `BG35_MagicItem_150`）监听 **`tavern_refresh_complete`**。
- **`tavern_refresh_complete(hero=, auto=)`**（2026-09-02 主线原语）:
  `refresh_tavern` 在 `tavern_refresh` 的**全部监听器跑完后**广播 →
  此刻酒馆即"刷新后的完整酒馆"（含各监听器在同一窗口内追加的 Fodder
  等），因此结算与注册顺序无关、也天然覆盖"刷新窗口内入馆"的实体。
  在 `tavern_refresh` 内结算 + 另设"入馆补授"两套机制的写法已废弃
  （两套会互相叠加、结果依赖顺序）。
- 授予形式 = **实体级永久 Buff**（文本无 "this turn" → 买入后带走，与
  `hero.tavern_buffs` 同口径）; 显式 "this turn" 的卡（Cursed Crystal）
  在下一招募阶段 `start_of_turn` 移除仍留在酒馆中的 buff。
- 实现见 `hsrl2/tests/test_batch_trinkets17.py`（150/151）与
  `hsrl2/tests/test_engine_primitives.py`（入馆事件）。

### 7.4.10 计数域：per-play 事件不得用于 per-cast 文本

- "After/Whenever **you cast** a spell" 类被动必须监听
  **`spell_resolving`（每次施放广播）**，不得监听 `card_played`
  （每次**打出**只广播一次）或 `spellcraft_cast`（同样每 play 一次）:
  双施（`SPELL_DOUBLER` Balinda / `spell_first` / `spellcraft_first`）
  与效果施法（`cast_spell_effect`，同样广播 `spell_resolving`）都会
  漏算。先例: Bloodbound Earrings / Archaic Scroll / Coral Spear
  `BG35_MagicItem_925` / Lovely Locket `BG36_MagicItem_211`。
- 反之，"**play** a card / play a Naga / play a Blood Gem from hand"
  类文本的计数域是 `card_played`（play 域）——效果施法与非手牌路径
  不应计入。
- 递归护栏: 监听 `spell_resolving` 且自身会 `cast_spell_effect` 的
  脚本必须置重入闸（如 game 级 `_lovely_locket_recast`），避免再施放
  自我触发、以及多份副本互相触发的死循环。

### 7.4.10b 卡家族光环 / 最后随从死亡 / 复制战团刷新（2026-09-02 原语）

- **`game.add_card_aura(source, card_ids, atk=0, health=0)`** ——
  "your **<卡名家族>** have +X/+Y this game"（Eternal Portrait
  `BG36_MagicItem_216` 等）。家族按 `TRIPLE_BASE_CARD_ID` 回落匹配
  （金色算同族）; **任意区域**生效（"wherever this is"）; **增量式**
  注册（同 source 重复调用按差值更新——累积型文本如"每个友方亡灵死亡
  +1/+1"）; source 离场即失效。读取点 `Entity._aura_atk/_aura_health`。
- **`last_minion_died(hero=)`** —— 战斗内某英雄棋盘不再有存活随从时
  广播（**每场战斗每英雄一次**；要求本场该英雄确有随从死亡，空板不出兵
  不触发）。文本族: "After your last minion dies each combat"
  （S'Thara Sticker `BG32_MagicItem_907` / Soul Fermenter
  `BG35_MagicItem_732`）。
- **`hero._combat_dead_snaps`** —— 每场战斗按死亡顺序的**轻量快照**
  （card_id / golden / race / atk / max_health / keywords）。供
  "summon your **first Demon** that died with its **maximum stats**"
  （907）读取。**禁止**在死亡后对实体做 `snapshot_state()`
  （deepcopy tags 会沿 KILLER 引用爆炸——实测 8 次死亡 132 秒）。
- **`refresh_tavern(..., copies_of_warband=True)`** —— "a free Refresh
  that contains **plain copies of minions in your warband**"
  （Warband Whistle `BG35_MagicItem_930`）: 内容 = 本人棋盘随从的白板副本
  （零池操作），仍受持久酒馆 Buff 影响（`add_tavern_entity` 入口）。
- **Bonus Keyword 定义域**（RULES §9.6）: `game.BONUS_KEYWORD_TAGS` =
  官方 **6 张**（Divine Shield / Reborn / Stealth / Taunt / Venomous /
  Windfury; wiki.gg `Battlegrounds/Bonus_Keyword` oldid 830663）。
  `game.grant_bonus_keyword(entity, tag)` 授予并记录到
  `GameTag.BONUS_KEYWORDS`（非六集 → fail-loud）;
  `game.random_bonus_keyword()` 走 `game.rng` 均匀取一个。
  `GameTag.PERSIST_BONUS_ONLY` 让战斗持久化**只**保留这 6 张
  （Tarecgosa Sticker `BG32_MagicItem_417`），区别于 Dark Gift/PERSIST 的
  8 集口径（含 Poisonous/Cleave）——两者不可混用。
- **`minion_triggered(minion=, hook=, ctx=)`**（RULES §7.4.10c）:
  `Game.run_script_hook` 在钩子**实际分发后**广播（仅当存在监听者时才建
  kwargs——热路径开销≈0）。用于 "Whenever your <X> **trigger**, ..."
  （Flaming Portrait `BG35_MagicItem_156`）——与 `minion_consumed` 组合可
  区分"自身 EoT 触发"与"被其它卡驱动吞噬"（后者只广播 consumed）。
- **死亡快照的关键词集合 = `Game.keyword_tags_of(entity)` 白名单**（不含
  `DEAD`/`ZONE`/`HEALTH` 等状态 tag）——"exact copy" 复原时若把 `DEAD` 一并
  贴回，副本会**死着入场**（不能攻击、立即触发自身亡语；2026-09-02 对抗
  验证 MAJOR，Boom Controller `BG30_MagicItem_440`）。`summon` 亦防御性
  `clear(DEAD)`。
- **`combat_slot_freed(hero=)`** —— 战斗内友方随从**离场瞬间**（早于亡语/
  复生）若棋盘出现空位则广播；同一时刻已记录该实体的死亡快照
  （`hero._combat_dead_snaps`），故消费者可在事件内直接读快照。文本族:
  "When you have space, ..."（Boom Controller `BG30_MagicItem_440` /
  Twin Sky Lanterns `BG30_MagicItem_822`）。**消费者自行保证有界**
  （每场至多一次），禁止形成无界补召。
- **`combat_restored(hero_a=, hero_b=)`** —— `run_combat` 在**棋盘快照
  已还原后**广播（finally 内、`in_combat=False` 之前）。供"战后收敛"类
  脚本使用（Tarecgosa Sticker `BG32_MagicItem_417` 需清掉被快照复活的
  旧标记；`combat_end` 只在 `end_recruit_phase` 广播，直调 `run_combat`
  的路径收不到——2026-09-02 对抗验证 BUG-2）。
- 实现见 `hsrl2/tests/test_engine_primitives.py::TestCardAuraAndCombatHooks`
  / `test_bonus_keyword_domain_and_persist_only`
  / `test_minion_triggered_observation`。

### 7.4.11 摧毁（Destroy）统一入口与观察点

- **`game.destroy_minion(minion, *, source=None, hero=None,
  process_deaths=True)`** —— 一切 "Destroy a minion" 效果的唯一入口
  （RULES §6.x 伤害无关）:
  - Destroy 与伤害的差别（wiki mechanics "Destroy"）: 无视圣盾/免疫、
    非伤害; `health = 0` → 完整死亡链（亡语/复生/回池照常）
  - 广播 **`minion_destroyed(hero=施动方, minion=, source=,
    in_combat=)`** —— `hero` 默认取 `source.controller`（无 source 时
    取随从自己的 controller）
  - `process_deaths=False`: 调用方在更外层跑死亡链（亡语连锁场景），
    事件仍立即广播
  - 已死 / 不在 `Zone.PLAY` → no-op（返回 False）
- **裁定**: 脚本**禁止**再手写 `target.health = 0` +
  `game.check_deaths()`——那样 `death` 事件无施动者，无法表达
  "After/Whenever **you destroy** a minion outside combat"
  （Kel'Thuzad Portrait `BG32_MagicItem_204` / Maw Caster Portrait
  `BG32_MagicItem_205`）。消费方按 `in_combat` 过滤 "outside combat"。
- 实现见 `hsrl2/tests/test_engine_primitives.py::TestDestroyMinionEntry`。

### 7.4.12 施法事件的两个时点（前置 vs 后置）

引擎对每次**施放**广播两个事件（手牌路径与 `cast_spell_effect` 同源）:

| 事件 | 时点 | 载荷 | 适用文本 |
|------|------|------|----------|
| `spell_resolving` | 法术效果**结算前**（每次 cast） | `spell=, target=, cast_no=` | 永久化拦截窗口（Lava Lurker / `add_permanent_spellcraft_rule`）; "每当施放"类**计数**（不依赖结算后场面） |
| `spell_resolved` | 法术效果**结算后**（每次 cast） | `spell=, target=, cast_no=` | **"After you cast a spell on a minion, ..."** 类被动（RULES §7.4.10 的计数域 + 后置语义）：Honeycomb Ring `BG36_MagicItem_371` / Lovely Locket `BG36_MagicItem_211` |

- **裁定**: 文本含 "**After** you cast" 的被动的时点必须是 `spell_resolved`
  —— 用 `spell_resolving`（前置）会让"本次施放"自己吃到刚触发的加成/进化
  （Honeycomb Ring 旧实现即因此把 improve 结算在触发法术之前）。
- `card_played` / `spellcraft_cast` 每次**打出**只广播一次 → 只适用于
  "**play** a card" 语义（RULES §7.4.10）。
- 双施（`SPELL_DOUBLER` / `spell_first` / `spellcraft_first`）下两个事件都
  按 cast 各广播一次。
- 实现见 `hsrl2/tests/test_batch_trinkets20.py`（211）与
  `test_batch_trinkets22.py`（371）。

### 7.4.13 经济与展示位读取点（2026-09-02 主线原语）

- **`gold_gained(hero=, amount=)`**: `Hero.gold` setter 在金币**增加**时
  广播，`amount` = 上限截断后的**实际**增量（99 持有上限溢出不算获得）。
  覆盖全部收入路径（回合收入 / 售卖 / `GainGold` Action / 脚本直改）——
  "After you gain Gold"（Splinter of Aurum `BG32_MagicItem_350`）的唯一
  观察点（旧仓只有 `gold_spent`）。
- **`GameTag.MINIONS_SOLD_THIS_TURN`**（hero 级）: `sell_minion` 成交后 +1、
  `_begin_recruit_for` 每回合清零——"for each minion you've sold this turn"
  （Darnassus Pie `BG30_MagicItem_992` / Windfall Portrait
  `BG32_MagicItem_832`）。
- **展示位档位协议**（`refresh_tavern`）:
  - `GameTag.TAVERN_OFFER_TIER_EXACT`（hero 级）: 本次刷新**全部**随从位
    取自恰好该档；优先于 Elven Elite 的"仅本档"限定（Guiding Candle
    `BG32_MagicItem_366`，脚本自行按"每回合前 N 次刷新"计数并清除）。
  - `GameTag.TAVERN_EXTRA_TIER_SLOTS` + `GameTag.TAVERN_EXTRA_TIER`:
    额外 N 个展示位取自恰好 `TAVERN_EXTRA_TIER`（缺省 `tavern_tier + 1`，
    封顶 `max_tavern_tier`）——Innkeeper's Stein `BG30_MagicItem_423`
    "an extra minion of a higher Tier"。
  - 与 `TAVERN_OFFER_MOD`（通用加位）/ `hero._tavern_offer_override`
    （固定总位数）的区别: 前二者**只改档位**，后者**只改数量**。
- 实现见 `hsrl2/tests/test_engine_primitives.py::TestGoldGainedObservation`
  / `TestMinionsSoldThisTurn` / `TestTavernOfferTierHooks`。
- **其它英雄级读取点**（2026-09-02 补充）:
  - `hero.CHOOSE_BOTH` tag: "Your Choose One cards have both effects
    combined"（Trailblazer Sticker `BG36_MagicItem_308`）——随从与法术两条
    Choose One 路径都读它（棋盘随从的 `CHOOSE_BOTH` 光环仍有效）。
  - `hero._next_trinket_kind`（"lesser"/"greater"）: "Your next Trinket is
    a Lesser Trinket"（Mysterious Orb `BG35_MagicItem_818`）——
    `_offer_trinkets` 读取并**消费即清**。
  - `refresh_tavern(..., consume_free=False)`: **引擎/卡牌赠送的免费刷新**
    不得消耗玩家自有 `FREE_REFRESH_REMAINING`（Warband Whistle
    `BG35_MagicItem_930` "Gain a free Refresh"——2026-09-02 对抗验证
    BUG-4）。
  - `Game.trigger_friendly_rallies(hero, ctx=None)`: "trigger all friendly
    **Rallies**"（Insurrectionist's Blade `BG36_MagicItem_214`）——对棋盘上
    每个带 `rally` 钩子的实体调用 `run_rally`（`rally_extra` 配额同源）。
  - `hero._tavern_cost_rules` / `hero._tavern_extra_keyword` 的 `source`
    有效性检查要求 source ∈ `trinkets`/`quest_rewards`/`board`；**法术自身
    不能作 source**——由饰品授予的 Spellcraft 法术应经
    `spell.spellcraft_source_uuid` 反查其饰品（Chillmere Mosaic
    `BG35_MagicItem_755` 口径）。

### 7.4.14 任务奖励读取点（2026-09-15 主线原语）

- **`hero.extra_triggers["tavern_spell_extra_cast"]`**（永久额度）:
  "Your Tavern spells cast an extra time"（Temporal Tampering
  `BG28_Reward_501`）。消费点 `game.py::_finish_play_spell`——仅当
  `card_def.is_pool_spell` 时 `casts += N`（酒馆法术；Spellcraft/血宝石/
  生成 token 法术不适用）。**永久**（不消费/不按回合重置），与 Balinda 的
  棋盘 `SPELL_DOUBLER` 光环、`spell_first` 配额三者**独立叠加**。
- **`hero._tavern_race_guarantee = (race, n)`**（hero 级，回落 game 级）:
  "The Tavern always offers 2 {0} whenever it is Refreshed"（Scepter of
  Guidance `BG27_Reward_812`，`num(0)`=92=NAGA）。消费点
  `refresh_tavern`——本次刷新的**前 n 个随从位专供**该种族（含
  `Race.ALL` 多类型随从），其余位走通用/`races=` 白名单池；池不足 N →
  按可得数回落通用池（**不注入**）。与 `races=` 全量白名单（"排除其它
  种族"）语义不同，不得互相近似。
- **`Game.make_golden_until_next_turn(minion)`**（临时金色）:
  "Make a friendly minion Golden until next turn"（The Golden Hammer
  `BG24_Reward_719t`）。目标换为**金色独立卡定义**（`db.golden_version`,
  保留附魔）+ 打 `GILDED_NOT_TRIPLED`（非三连金 → 金色状态出售/淘汰只
  回池 1 份，§2.3 Reno 口径）+ 登记控制者**下一个** `turn_start` 回滚为
  非金（单 tick，§6.13）。已是金色 → no-op 返回 True；目标不在棋盘/
  无金色定义 → 落空 False。实现依赖
  `Transform(..., force_golden=True/False)`（覆写金色状态，缺省继承
  目标）——临时金色需要"非金 → 金"与"金 → 非金"两个方向。
- 实现见 `hsrl2/tests/test_engine_primitives.py::TestTavernSpellExtraCast`
  / `TestTavernRaceGuarantee` / `TestTemporaryGolden`。

### 7.4.15 家族"给予者加成"读取点（2026-09-13 主线原语）

- **`hero.giver_bonus_rules: [(source, 基础卡 id, {atk,health,copies})]`**:
  Portrait 类饰品对**载荷效果量**的加成——
  "Your **Nalaa the Redeemers** give an extra +{0}/+{1}"
  （Redeemer Portrait `BG30_MagicItem_944`，num=4/4）/
  "Your **Zesty Shakers** give an extra copy of the spell"
  （Shaker Portrait `BG30_MagicItem_828`，1 份，文本字面量）。
- **写点** `Game.add_giver_bonus(hero, card_id, *, atk, health, copies,
  source=None)`: 只写**绑定该饰品的英雄**（owner 隔离）；`card_id` 按
  **基础卡 id** 归一（金色载荷 `BG28_551_G`/`BG26_505_G` 与基础同族命中，
  数值仍取各自 CardDef）；`source=None` = 永久规则（测试/引擎直写）。
- **读点** `Game.giver_bonus(hero, card_id)`（全 0 缺省，只读副本）:
  `NalaaTheRedeemerScript.on_cast` 用 `num(0)+atk / num(1)+health`；
  `ZestyShakerScript.on_played` 用 `(1 或金色 2) + copies`。载荷脚本
  **不得**读他脚本私有属性（SOP §12）——本通道是唯一协议。
- **生效期**: 读取时校验 `source` 仍在 `hero.trinkets` /
  `quest_rewards` / 棋盘；效果实体被替换/移除即失效（同
  `_card_aura_active` §6.19 / `permanent_spellcraft_rules` §7.4.7a）。
- 实现见 `hsrl2/tests/test_batch_trinkets33.py` /
  `test_engine_primitives.py::TestGiverBonusChannel`。

### 7.4.16 家族"行为开关"读取点（2026-09-13 主线原语）

- **`hero.family_flags: [(source, 基础卡 id, 开关名)]`**: Portrait 类饰品
  对载荷**行为分支/目标集合**的改写（§7.4.15 `giver_bonus` 只承载**数值**
  加成——前者管"打谁/是否多做一件事"，后者管"+多少"，二者互补）。
  文本族: "Your **Bristlebachs** play Blood Gems on **all friendly
  minions**"（Bristlebach Portrait `BG32_MagicItem_274`）。
- **写点** `Game.add_family_flag(hero, card_id, flag, *, source=None)`:
  只写**绑定该饰品的英雄**（owner 隔离）；`card_id` 按**基础卡 id** 归一
  （金色载荷同族命中）; `source=None` = 永久规则（测试/引擎直写）。
  `flag` 与 `card_id` 必须是非空 str——拼写错误 **fail-loud**
  （`GameStateError`），禁止静默 `False`（漏开关 = 静默半实现）;
  **读点同样校验**（2026-09-13 对抗验证 MINOR: 读点曾对未初始化/拼错的
  `card_id` 静默返回 `False`）。
- **读点** `Game.family_flag(hero, card_id, flag) -> bool`（缺省 False）:
  载荷脚本在效果分支处读取（`BristlebachScript.avenge` 用
  `FLAG_SCOPE_ALL_FRIENDLY`）; 开关名常量定义在**载荷侧**（唯一消费点），
  饰品侧 import 同一常量。载荷脚本**不得**读他脚本私有属性（SOP §12）。
- **生效期**: 读取时校验 `source` 仍在 `hero.trinkets` /
  `quest_rewards` / 棋盘；效果实体被替换/移除即失效（同 §7.4.15 /
  §6.19 口径）。
- 覆盖卡: `BG32_MagicItem_274`（Bristlebach，batch_trinkets34）;
  2026-09-19 起另覆盖 A 组 5 张的"also give X"数值增量——
  `BG30_MagicItem_868` / `BG30_MagicItem_987` / `BG32_MagicItem_283` /
  `BG30_MagicItem_869`（batch_trinkets31 + batch_payload_minions）。
- 实现见 `hsrl2/tests/test_batch_trinkets34.py` /
  `test_engine_primitives.py::TestFamilyFlagChannel`。

#### 7.4.16b 吞噬**目标选择策略**读取点（2026-09-19 主线原语，§7.4.16 扩展）

- **`hero.consume_policies: [(source, 策略名)]`**: 改写持有者**全部恶魔**
  吞噬效果的目标选择策略。与 `family_flags` 的区别: 后者的键是**卡家族
  id**，而 "Your **Demons** always consume the **highest-Health** minion
  in the Tavern"（Implicator Portrait `BG32_MagicItem_824`）的作用域是
  **种族**（消费方为 `BG21_004` Ur'zul / `BG23_357` Mind Muck /
  `BG36_880` Methodical Madness / `BG29_140` False Implicator 等**不同
  家族**的恶魔路径），按卡 id 归一无法承载。
- **写点** `Game.add_consume_policy(hero, kind, *, source=None)`:
  只写绑定该饰品的英雄（owner 隔离）; `kind` 必须是非空 str
  （当前唯一取值 `hsrl2.actions.consume.CONSUME_POLICY_HIGHEST_HEALTH`
  = `"highest_health"`），否则 `GameStateError`（fail-loud）。
- **读点** `Game.consume_policy(hero) -> str | None` 与目标选择原语
  `Game.pick_consume_victim(consumer, candidates, *, label)`:
  仅当 `consumer.controller` 命中策略**且** `consumer.race in
  (DEMON, ALL)` 时，在**酒馆候选**中取 `max_health` 最大者; 并列极大
  时在并列集内走 `game.rng`（卡面未定义同值次序，保留引擎确定性协议）。
  无策略 / 非恶魔 / 无候选 → 均匀随机（既有 `game.rng.choice` 口径）。
- **生效期**: 读取时校验 `source` 仍在 `hero.trinkets` /
  `quest_rewards` / 棋盘；效果实体被替换/移除即失效（同 §7.4.15 /
  §7.4.16 / §6.19 口径）。
- 覆盖卡: `BG32_MagicItem_824`（Implicator Portrait，batch_trinkets31）。
- 实现见 `hsrl2/tests/test_batch_trinkets31.py::TestImplicatorPortrait`
  （真实 `grant_trinket` + EoT 吞噬 + 多 seed 随机负对照 +
  `ConsumeRandomTavernMinion` 通用路径）。

### 7.4.17 条件化战吼（2026-09-13 主线原语）

Portrait 类饰品可在**持有期间给家族载荷追加战吼**（"Your X also trigger
on Battlecry"）。载荷脚本以类属性声明开关，引擎/脚本的"是否有战吼"门禁
统一按开关判定——**不允许**用"脚本里有没有 `battlecry` 钩子"这种静态判据。

**协议**

- 载荷侧: 类属性 `battlecry_flag: str | None`（开关名，常量定义在载荷侧）
  + `battlecry(source, game, ctx)` 钩子；钩子体内**必须**自守
  `if not game.granted_battlecry(source): return None`（`TriggerBattlecry`
  与 `_gift_echoing_voice` 会直接调脚本钩子，不经过引擎门禁）。
- 饰品侧: `on_bind` 用 §7.4.16 `Game.add_family_flag(hero, 载荷卡 id,
  flag, source=source)` 写开关（金色载荷按基础卡 id 归一同族命中）。
- 引擎门禁（单一事实源）:
  - `Game.granted_battlecry(m) -> bool`: `battlecry_flag` 已声明且
    `family_flag(m.controller, m.card_id, flag)` 生效;
  - `Game.has_battlecry(m) -> bool`: `BATTLECRY` tag **或** 脚本钩子
    （无 `battlecry_flag` = 无条件；有则须 `granted_battlecry`）**或**
    磁力栈同钩子。`_has_battlecry_hook` 是其后向兼容别名。
- **实体级"是否具有战吼"的判定必须走 `Game.has_battlecry`**，包括:
  打出结算的 `bc_first`（War Drum）配额消费、`COUNTER_BATTLECRIES` 与
  `battlecry_trigger` 广播、`actions/trigger.py:TriggerBattlecry` 门禁、
  `batch_trinkets8._has_battlecry_hook`、`scripts/minions.py` 的
  Activate 战吼候选、`batch_hero_passives` 的"买 N 个战吼随从"计数。
  `has_battlecry` 的通道 = `BATTLECRY` tag ∨ 无条件脚本钩子 ∨ 实体级
  `set_script_override("battlecry", …)` ∨ **已生效**的条件化钩子 ∨
  磁力栈叠的同钩子（带 flag 的附件按**附件卡 id** 查同一 hero 的开关）。
- **例外（有意不覆盖，2026-09-13 对抗验证留档）**: **酒馆/数据驱动**的
  关键词过滤按卡面与实体关键词判定，不读 Portrait 授予——
  `CardDef.keywords`（池/奖励筛选）、`_free_buy_qualifiers_match` 的任意
  tag 限定（如 Warcry Totem `BG36_MagicItem_202`）、Chillmere Mosaic 的
  刷新筛选。理由: 尚未拥有的**酒馆报价**不吃"你的无私英雄"授予，且当前
  Portrait 家族均为非池卡（不可出现在酒馆）。若未来出现**池内**的条件化
  战吼卡，需重新裁定这些过滤是否应感知开关。
- **金色口径**: 沿用"金色模型约定"（`scripts/minions.py` 模块 docstring）
  ——金色战吼 = **每次触发取基础值**、引擎触发 2 次。故载荷的
  `battlecry_targets`（每次触发目标数）**不随金色覆盖**；`_targets`
  （单次触发的亡语/SoC 值）才用金色文本值。

**反例（为什么不能用静态判据）**: `BG32_MagicItem_804` Selfless Portrait
的直接做法是给 `SelflessHeroScript` 加 `battlecry` 钩子——但那样**无饰品
时**本体也会被 `_has_battlecry_hook` 判为战吼随从（2026-09-13 实测:
`extra_trigger_used['bc_first']` 0 → 1），从而误消费 War Drum 配额、误计入
`BG30_MagicItem_982`、误入 Young Murk-Eye `BG35_MagicItem_752` 的最左/
最右战吼目标集。

**权威**: 32.4 补丁说明（2025-06-02，playhearthstone.com blog 24205006）
"Snicker Snacks: Fixed a bug where it couldn't trigger Selfless Hero's
effect when **it has a Battlecry from Selfless Portrait**" —— 官方明确
持该饰品时家族**"具有战吼"**且可被"trigger a Battlecry"效果（`BG24_Reward_107`）
触发；反向亦意味着**无饰品时它没有战吼**。

- 覆盖卡: `BG32_MagicItem_804`（已注册，batch_trinkets35）。
- 实现见 `hsrl2/tests/test_batch_trinkets35.py` /
  `test_engine_primitives.py::TestConditionalBattlecryChannel`。

**第二形态：Portrait 给家族 **追加一次触发**（batch_trinkets36）**

`BG32_MagicItem_803` Macaw Portrait（"Get a Monstrous Macaw. Your
Monstrous Macaws **also trigger your left-most Battlecry**"）与 804 共用
同一开关通道（§7.4.16 flag + 本节的 `has_battlecry` 门禁），但消费点在
载荷 `MonstrousMacawScript.rally`，**不声明 `battlecry_flag`**
（`battlecry_flag` 的语义是"本脚本的 `battlecry` 钩子条件化"; Macaw 本体
并无战吼钩子，声明它只会让 `granted_battlecry` 恒真、语义误导）：

- `rally` 在亡语项之后读 `family_flag(hero, 本卡 id,
  FLAG_MACAW_EXTRA_BATTLECRY)`；生效则在同一 Rally **追加**
  "trigger your left-most Battlecry"。
- **资格集口径**: "your left-most Battlecry" = 存活友方中**具有战吼者**
  （`game.has_battlecry`）里棋盘顺序最左的一个——与本体卡面 "your
  left-most Deathrattle"（= 最左**挂有亡语者**）同构。
  权威: 32.2 官方论坛复现串 "[32.2] Macaw Portrait + Glowgullet Warlord"
  （2025-05-15）棋盘 `M G x B y z`——Macaw 攻击**同时**触发最左亡语 G
  与最左**战吼** B，**跳过中间的非战吼 x**。
- **次数**: 每次 Rally 追加触发 **1 次**（饰品文本无 "twice"；金色
  `TB_BaconUps_135` 的 "twice" 只修饰亡语 → `passes=2` 只管亡语）。
- 走 `TriggerBattlecry` **统一入口**（Brann 翻倍 / `COUNTER_BATTLECRIES` /
  `battlecry_trigger` 广播 / 无战吼门禁全生效）。
- 时序: 先亡语（`passes` 次）后追加战吼（"also" 项）; 亡语项落空不影响
  追加项，反之亦然。含本体（文本无 "except this minion's"）。
- 实现见 `hsrl2/tests/test_batch_trinkets36.py`（含与 804 的复合用例:
  最左战吼 = 被 804 授予战吼的无私英雄）。

### 7.4.18 逐附魔"按来源跨战斗持久化"（2026-09-18 主线原语）

卡面把"永久"与"战斗内更大数值"写在同一句时（"give your minions +{0}/+{1}
**permanently**. *(+{2}/+{4} while in combat!)*"），该次授予必须跨战斗保留
——见 §3.5 例外 4。引擎原语（**逐附魔**，与 §3.5 例外 1 的单实体全量通道
正交）:

- **写点**: `Buff(..., persist=True, source_id=<来源卡 id>)`（附魔实体
  `hsrl2/entity.py::Buff`）; `actions/stats.Buff` 透传同名字段。
- **恢复阶段**: `Game.run_combat` 的 `finally` 在快照回滚**前**收集命中
  `persist` 的附魔，回滚后用 `m.add_buff(b)` 重放——同一实体的**其它**
  战内变化照常回滚; `dmg_deltas`（例外 3）重放跳过 `persist` 附魔以免双计;
  例外 1 的增量重放（`persist_totals`）**扣除** `persist` 附魔份量后再按
  倍率重放（否则同一实体同时命中例外 1 与例外 4 时该增量被计两次;
  2026-09-18 实测缺陷 + 回归）。该**归属规则**（`persist` 附魔归例外 4、
  其余战内变化归例外 1，故不被 `PERSIST_DOUBLE` 双计）**无官方权威**，
  是引擎实现契约（§3.5 有就近告示）。
- **来源规则**: `Game.add_persist_source(hero, source, card_ids)` 在 hero 上
  登记（`hero.persist_sources`）; 命中判定
  `Game.minion_persist_source(hero, minion) -> bool` /
  `Game.persist_source_id(hero, minion) -> str`（审计/`source_id` 用）。
  家族按 `GameTag.TRIPLE_BASE_CARD_ID` 回落匹配（金色同族命中）;
  生命周期在**读取时**判定（source 必须仍在 `hero.trinkets` /
  `quest_rewards` / 棋盘），效果实体离场即失效（同 §7.4.15 / §7.4.16）。
  参数校验 fail-loud（`hero`/`source` 为 `None`、`card_ids` 为空 →
  `GameStateError`），重复登记合并集合。
- **消费点**: 载荷脚本在**授予时**读来源规则，命中才把该次 `Buff` 标
  `persist=True`（`batch_deathrattle.ShowyCyclistScript.deathrattle`）;
  饰品自授时直接标（`batch_trinkets31.BewitchedRibbonScript`）。
- **家族匹配的边界（已备案，非静默近似）**: 家族/复制语义**由卡面直接
  支持**——"**Your** Showy Cyclists' Deathrattles give permanent stats" 是
  该**卡家族**的属性（"Your Showy Cyclists'" 限定的是家族身份，不是增益
  接受者），故家族成员（含金色，`TRIPLE_BASE_CARD_ID` 回落）的亡语才
  持久化。**范围注记**: 同一亡语被**复制到非家族随从**上时，它已不再是
  "Your Showy Cyclists' Deathrattle" ⇒ 该次授予**不**享受持久化（按卡 id
  匹配的实现边界，已由负对照断言，非静默近似）。
- 覆盖卡: `BG35_MagicItem_923` Bewitched Ribbon、"`BG36_MagicItem_362`"
  Cyclist Portrait（均 batch_trinkets31）。
- 权威: 923 = 卡面**同一句**中的 "…permanently"（wiki.gg
  `Battlegrounds/Bewitched_Ribbon`; zhCN/JA/KO 把括号渲染为**替换**语义
  "战斗中改为+{2}/+{4}"）⇒ 括号是同一份永久授予的战斗内数值档，非第二次
  临时效果; 该页 Patch changes（35.2.2/35.6.2 只改括号数字、基础 +1/+1 与
  "permanently" 从未移动）**仅作旁证**，不是排除性证明; 362 = 官方 S14
  饰品全表（Blizzard 论坛 163710）"Get a Showy Cyclist. Your Showy
  Cyclists' Deathrattles give **permanent** stats."。
- 实现见 `hsrl2/tests/test_batch_trinkets31.py::TestBewitchedRibbon /
  TestCyclistPortrait`。

### 7.5 新英雄

Season 13 引入了 **2 位新英雄**：

- **英雄详情**需参考官方公告或卡牌数据库。

### 7.6 其他平衡调整（Patch 35.0.3–35.2.2）

- **Metal Dispenser**（机械）：Avenge 阈值从 3 提高到 4，攻击力从 2 提升到 4。
- **Silky Shimmermoth**（野兽/亡灵）：生命值从 8 提升到 12。
- **Twilight Watcher**（龙）：从 Tier 5 降到 Tier 4。
- **Goldgrubber**（海盗）：生命值从 2 提升到 3。
- **Mrglin' Burglar**（鱼人）：攻击力从 8 提升到 10，生命值从 6 提升到 8。

---

## 8. 种族与类型

酒馆战棋中的随从属于以下种族（Tribe）：

| 种族 | 英文 | 特色机制 |
|------|------|---------|
| 野兽 | Beast | 亡语、召唤、战斗阶段Buff |
| 恶魔 | Demon | Fodder（吞噬）、自残、高攻高血 |
| 龙 | Dragon | Chromadrake（变形进化）、战斗开始时 |
| 元素 | Elemental | 刷新酒馆联动、法术互动 |
| 机械 | Mech | 磁力、圣盾、亡语 |
| 鱼人 | Murloc | 剧毒/猛毒、手牌Buff |
| 纳迦 | Naga | 法术塑造、法术互动 |
| 海盗 | Pirate | 金币经济、攻击联动 |
| 野猪人 | Quilboar | 鲜血宝石、Rally |
| 亡灵 | Undead | 复生、死亡联动 |
| 全种族 | All | 视为所有种族 |
| 无种族 | None | 无特殊种族联动 |

**种族禁用（Ban System）**：每局游戏会随机禁用部分种族，确保不同对局的多样性。

**Patch 30.6 变更**：野兽和龙现在**可以**同时出现在同一局游戏中（此前某些版本中两者互斥）。

---

## 9. 英雄与英雄技能

### 9.1 英雄选择

- 每局游戏开始时，玩家从 **2 个英雄**中选择（拥有赛季通行证可选择 4 个）。
- 同一局游戏中不会向多个玩家提供同一个英雄。
- 英雄重掷代币（Hero Reroll Token）可以用来刷新英雄选项。

### 9.2 英雄技能类型

| 类型 | 说明 | 示例 |
|------|------|------|
| **被动（Passive）** | 始终生效，无需消耗 | 购买随从时获得Buff、开局额外生命 |
| **酒馆主动（Tavern Active）** | 消耗金币在招募阶段使用 | 刷新后给随从加关键词、降价购买 |
| **战斗主动（Combat Active）** | 消耗金币为下一场战斗提供临时加成 | 对敌方随从造成伤害、临时Buff |

### 9.3 护甲等级

- 英雄根据强度被分配 **5-20 点护甲**。
- 强度较低（较弱）的英雄获得更多护甲，以平衡胜率。
- 护甲是动态调整的，会随着补丁更新而变化。

### 9.4 伙伴（Buddy）

- 每个英雄拥有独特的**伙伴随从**。
- 玩家可以使用特殊按钮购买伙伴（每局最多 2 次）。
- 第一次购买：获得 1 个；第二次购买：获得 2 个（可合成金色）。
- 伙伴费用：胜利/平局减少 3 费，失败减少 2 费。

**项目数据/引擎现状（2026-09-02 核实）**:
- **数据链可得**: 英雄 CardDef 的 `companion_id`（XML 2130，dbf）→ 伙伴卡
  （`BACON_BUDDY=1`，随从）; 109 位英雄有该链（如 `BG20_HERO_100` Rokara
  → dbf 77876 = `BG20_HERO_100_Buddy` Icesnarl the Mighty 6/2 T3）。
- **缺口**: 伙伴按钮的**初始费用**不在任何数据文件（CardDefs 无该 tag，
  客户端硬编码）——只有"胜/平 −3、负 −2"的递减规则有文档。因此
  "买伙伴"动作的定价无权威来源 → **Buddy 子系统整体 DEFERRED**。
- 依赖该子系统的卡（届时一并解锁）: 异变 `BG27_Anomaly_810`
  "Buddies are in the Tavern"、`BG33_Anomaly_001` Summoning Pact /
  `002` Spirit of Friendship / `003` Third Nature（第 3 次按金色）/
  `005` Colorful Camaraderie / `008` Partner in Crime（T4 选任务换金色
  伙伴）/ `009` Amicable Amendment（费用 +50%，买卡后 −1）;
  任务奖励 `BG24_Reward_310` Partner in Crime（本仓已用
  `hero.companion_id → golden_version` 实现，属已就绪部分）。
- 若未来取得初始费用权威（官方补丁说明/客户端导出），实现路径:
  `hero.companion_id` 解析伙伴卡 + 新引擎动作 `buy_buddy(hero)`
  （每局 ≤2 次、第 1 次 1 只/第 2 次 2 只、`combat_end` 结果递减费用）。

### 9.5 英雄技能槽（Hero Power Slots）

- 英雄默认有 **1 个技能槽**；异变/任务奖励可授予**第二技能槽**
  （文本族: "Start with '{X}' as your second Hero Power" /
  "Make '{X}' your second Hero Power"）。
- 第二个技能与主技能**各自独立**: 各自的每回合次数、每局次数、费用与
  `available` 门槛互不影响（用过一个不影响另一个）。
- 引擎契约（`hsrl2/game.py` / `hsrl2/hero.py`）:
  - `hero._second_power_id` — 第二技能槽的 power id，由异变/奖励在
    `on_bind` 中写入
  - `game.hero_power_ids(hero)` — `[主技能, 第二技能]`
  - `game.hero_power_def_for(hero, power_id)` — 按 id 解析技能 CardDef
  - `game.use_hero_power(hero, target=None, power_id=None)` — 未指定时用
    主技能; 指定第二技能即使用第二槽
  - 每技能独立计数: `hero._power_uses_this_turn` /
    `_power_uses_this_game`; `HERO_POWER_USED_THIS_TURN` /
    `HERO_POWER_USES_THIS_GAME` 仍作为**全局累计** tag（"After you use
    your Hero Power" 类效果读事件 `hero_power_used`（带 `power_id`），
    不受技能身份影响）
  - **次数配额在结算点复查**（2026-09-13 对抗验证 MAJOR）: 计数发生在
    `_finish_hero_power`。定向技能的目标选择**挂起期间**可再次发起
    `use_hero_power`（发起时计数尚未发生），若不在结算点复查，N 个挂起
    结算会把 `uses_per_turn=2` 叠加成 N 次（实测连发 5 次全部 True）。
    结算复查点与金币不足 / 目标离场复查同构: 超额 → 该次使用**作废**
    （不扣费、不计数、无效果），`refund_hero_power_use` 只用于脚本侧
    落空（引擎自动作废的无需回滚）。实现见
    `hsrl2/tests/test_engine_primitives.py::TestHeroPowerPendingQuota`。
  - `start_game` 接线顺序: 主技能 `on_bind` → 异变 `on_bind`（声明第二
    槽）→ **第二技能槽 `on_bind`**（保证其监听器在首回合开始前就位）
  - **槽位可被"饰品副本"占用**（Crystal Ball 族 `BG35_Anomaly_007t`/
    `_008t` "When you buy a Lesser/Greater Trinket, this transforms
    into a copy of it"）: `game.set_second_slot_trinket(hero, trinket_id,
    replace=)` —— 槽位标记改写为该**饰品 id**（此时 `hero_power_ids`
    只列真正的 HERO_POWER 卡，饰品不进可用技能表，`use_hero_power`
    不会以其名义扣费），副本实体入 `hero.trinkets` 走副本路径
    （RULES §7.4.3 副本条款）。槽位仍视为**已占用**
    （`set_second_hero_power` 抛 `GameStateError`）。
- 覆盖卡（**已注册**）: `BG32_Anomaly_001/002`（第二技能 = Growing
  Collection / Fantastic Treasure）、`BG31_Anomaly_123`、`BG31_Anomaly_117`
  （第二技能 = Eject!，配 RULES §2.3 永久移除 `MinionPool.purge`）、
  `BG35_Anomaly_002t/007t/008t`、`BG33_Reward_017`。
- 未注册（DEFERRED）: `BG31_Anomaly_106`（需 `replace_hero_identity`
  身份替换协议）、`BG35_HERO_001p` Genn（"Discover **two** Hero Powers to
  replace this" 的二择一语义与候选集无权威）、`BG20_HERO_202p`（每回合轮换
  需技能 rebind/unbind 协议——引擎无 unbind，被替换被动会残留）——台账见
  `batch_anomalies_final` §H / `batch_hero_remaining`。
- 实现见 `hsrl2/tests/test_engine_gaps.py::TestHeroPowerSlots` /
  `TestTrinketCopyProtocol`。

---

## 10. 三连与金色随从

### 9.6 Bonus Keyword（额外关键词）——语义与数据缺口

> **2026-09-02 更新（已落地）**: 定义域已按 wiki.gg
> `Battlegrounds/Bonus_Keyword`（oldid 830663）定为 **官方 6 集**
> {Divine Shield, Reborn, Stealth, Taunt, Venomous, Windfury}（**不含**
> Poisonous/Cleave）；引擎提供 `game.BONUS_KEYWORD_TAGS` /
> `grant_bonus_keyword(entity, tag)`（记录进 `GameTag.BONUS_KEYWORDS`，
> 非六集 fail-loud）/ `random_bonus_keyword()` /
> `GameTag.PERSIST_BONUS_ONLY`（战斗持久化只保留 6 集）。据此
> **417 Tarecgosa Sticker / 891 Finley's Helmet / 892 Vibrant Bubble
> (+892t) 已注册**，`BG36_MagicItem_801` Consuming Claw 的"移转 Bonus
> Keywords"亦按 6 集实现。原文的"定义域无数据字段 → DEFERRED"裁定已被
> 取代；仍待权威的只剩"逐实体被授予记录"的展示口径（不影响结算）。


- 文本族: "give ... a random <b>Bonus Keyword</b>" /
  "permanently keep <b>Bonus Keywords</b> and stats" /
  "it also gains its <b>Bonus Keywords</b>"。
- **本仓既有先例**: `BG24_HERO_204p` Enhance-o Mechano 的"随机关键词"
  取 6 集 {TAUNT, DIVINE_SHIELD, WINDFURY, POISONOUS, VENOMOUS,
  REBORN}（batch_hero_passives2 已按此实现并被对抗审查验证）。
- **缺口（2026-09-02 核实）**: 官方"Bonus Keyword"的**定义域**与
  "哪些关键词算 bonus（相对随从天生关键词）"没有任何数据字段
  （CardDefs 无 tag; 文本无枚举）。且 Consuming Claw "gains its Bonus
  Keywords" 需要"逐实体记录被授予的 bonus 关键词"这一新机制。
- 因此以下 4 张饰品维持 **DEFERRED**:
  `BG32_MagicItem_417` Tarecgosa Sticker / `BG32_MagicItem_891`
  Finley's Helmet / `BG32_MagicItem_892` Vibrant Bubble /
  `BG36_MagicItem_801` Consuming Claw。
- 实现路径（取得权威后）: (1) 定义 `BONUS_KEYWORD_SET`（需官方/patch
  notes 佐证）; (2) 新 tag `BONUS_KEYWORDS_GRANTED`（list）记录逐实体
  授予; (3) 授予走 `GainKeyword` 并追加该 tag; (4) Consuming Claw 读取
  被吞噬者的该 tag; (5) Tarecgosa Sticker 复用 `PERSIST_COMBAT_CHANGES`
  的保留路径（含该 tag）。

### 10.1 三连规则

- 收集 **3 个相同的随从**时，它们会自动合成为一个**金色（Golden）**版本。
- 金色随从保留所有三个原始随从身上的**增益和状态**。
- 三个金色随从**不会**进一步合成。

### 10.2 金色随从效果

- 基础**攻击力和生命值翻倍**。
- 相关能力通常也会**翻倍或增强**。
- 打出金色随从时，获得一张**三连奖励（Triple Reward）**卡牌。

### 10.3 三连奖励

- 使用三连奖励可以**发现（Discover）**一张免费随从。
- 可发现的随从来自**更高一级酒馆**（若已在 Tier 6，则发现 Tier 6）。
- 三连奖励是推进游戏的重要节奏点。

---

## 11. 季节性系统

酒馆战棋会周期性引入季节性系统，它们并非永久存在。

### 11.1 任务与任务奖励（Quest & Reward）

- 玩家在第 4 回合从三对"任务+奖励"中选择一对。
- 完成任务目标后获得对应的**任务奖励**。
- Season 11 时有 35 个奖励，其中 13 个是全新的。
- 示例奖励：
  - "Cooked Book"：购买随从时永久Buff它们。
  - "Pilfered Lamps"：2 个相同随从自动变金色。
  - "Doppelganger's Locket"：从对手阵容中发现随从。

### 11.2 饰品（Trinkets）

- 当前赛季（Season 13）饰品系统回归。
- 玩家可以在第 6 回合购买**小型饰品**，第 9 回合购买**大型饰品**。
- 详细规则见 [7.4 饰品系统回归](#74-饰品系统回归trinkets)。

### 11.3 异常（Anomalies）

- 对局开始时的特殊规则修改。
- 可以改变核心玩法（见第 12 章）。

### 11.4 暗月奖品（Darkmoon Prizes）

- 已退役的季节性系统，但某些异常规则下可能回归。

### 11.5 时间扭曲酒馆（Timewarped Tavern）

- 于 Patch 34.2 (2025年12月) 引入。
- 提供来自其他时间线的独特卡牌和机制。
- 是 Season 12 的核心系统。

### 11.6 任务进度（Quest Progress）——数值权威与实现口径

- 游戏内显示的任务进度（任务牌文本里的 `{0}`）**不是**任务牌的固定值，
  而是围绕基线上下浮动后的运行时数值。社区拆包（Patch 25.0）给出:

  > **任务难度 = 任务基础值 × 任务种族修正 × 奖励基础值 × 奖励种族修正 × 护甲等级**
  > （来源: 旅法师营地「酒馆战棋 任务难度&其他数据」2023-07，作者拆包导出
  > CardDefs 后归纳；作者声明"拆包数据不一定能代表实际数据"）

- **权威序（项目所有者 2026-09-18 直接裁定）**: wiki 详细说明 > 卡面自然
  语言理解。wiki 各卡页 "Patch changes" 段的 **"baseline requirement"
  当前值**即本模拟器的目标值（`docs/agents/QUEST_DEFERRED_SPEC.md` §1 有
  逐卡 URL + oldid + 逐字引文）。四因子只是围绕该基线的 ±修正，其修正表
  XML 与 wiki 均无数据源 → **不模拟**（已知近似，记录在案）。

- **本项目的数据可得性（2026-09-02 逐 tag 核实；2026-09-13 复核；
  2026-09-18 订正）**:
  - 任务基线值: `hsdata/CardDefs.xml` 的 `QUEST_PROGRESS_TOTAL`
    （enumID 535）——21 张任务卡**全部有**（如
    `BG24_Quest_112` Track the Footprints = 8、`BG24_Quest_114`
    Assemble a Lineup = 16、`BG24_Quest_124` = 17、`BG24_Quest_126` = 27、
    `BG24_Quest_328` = 1、`BG24_Quest_Bob` = 3）。逐张数值与 wiki 各卡页
    "baseline requirement" 当前值**一致**（见
    `docs/agents/QUEST_DEFERRED_SPEC.md` §1 表）。
  - **任务卡族 > `BG24_Quest_*`**: 同 tag 还有
    `BG27_Quest_800` Burn the Evidence=6、`BG27_Quest_801` Pressure the
    Authorities=28、`BG27_Quest_802` Round Up the Suspects=17、
    `BG28_Quest_500` Fill the Cauldron=11、`BG27_Reward_812`=2、
    `BG33_Anomaly_008_Quest`=3（Bob 公告的异变版）。其中
    `BG27_Quest_801/802`、`BG28_Quest_500` 在当前任务池内（wiki
    `Battlegrounds/Quest`「These Quests can appear in games」）——任务系统
    在本数据基线（36.2.2）仍活；`Game.quest_defs()` 按整族计数。
  - 奖励基础值: 66 张 `BG24_Reward_*` 中**仅 1 张**（`BG24_Reward_134`
    的 `QUEST_PROGRESS_TOTAL=2`）——不构成数据源; 这不影响目标值（目标值
    来自任务卡基线，不依赖奖励侧字段）。
  - 任务/奖励的种族修正、护甲等级修正: **无任何数据文件**（纯客户端）
    → 本项目不做逐局 ±修正。
  - 外部权威（2026-09-18 复核）: wiki `Battlegrounds/Quest`（oldid 916067）
    的「Baseline requirements」列表**陈旧**（Crack the Case 写 15 而实际
    9、Cry for Help 写 3 而实际 4、Dust for Prints 22 vs 23、Pressure 35
    vs 28、Unlikely Duo "Play 5" vs "Buy 4"）→ 以**各卡页 Patch changes**
    为准; 各卡页均**无 Notes 段**（`?action=raw` 核实）→ 判定口径全部走
    卡面自然语言解读，逐条记档。

- **实现现状（2026-09-18 第四十九轮）**: 19 张任务已注册
  （`hsrl2/scripts/batches/batch_quests.py`）:
  `BG24_Quest_112/114/120/123/124/125/126/151/311/313/314/318/320/351/352`
  + `BG27_Quest_800/801/802` + `BG28_Quest_500`。
  - 引擎侧任务框架: `game.quest_defs()`（整族筛选 + 公告 token 排除）/
    `quest_offer_pool()`（池门禁 = `quest_defs() ∩ REGISTRY`）/
    `quest_target(hero)` / `advance_quest_progress(hero, n)`（**唯一计数
    写入点**）/ `set_quest_progress(hero, value)`（阈值式，只升不降）/
    `complete_quest(hero)`（**唯一发奖入口**）/ `Hero._quest_completed`
    （二次计分闸）。
  - **DEFERRED 1 张**: `BG24_Quest_328` Close the Case——**阻塞 = "Win the
    game." 的胜义无权威**（第 1 名 / 前 4 / 单场战斗胜利无法消歧），
    **不是缺目标值**: 卡数据有 `quest_progress_total=1`（见上）；wiki 卡页
    无 baseline 行只说明 wiki 未印出数值。从未入池、无 `QUEST` tag →
    保持 DEFERRED（语义权威缺口，不是近似）。
  - **公告 token 2 张**（`BG24_Quest_Bob` / `BG33_Anomaly_008_Quest`）:
    无进度条件，语义已由 `Game._offer_quests` 覆盖 → `quest_defs()` 显式
    排除（注册即"注册但空转"第三态）。
  - **依赖任务载荷的英雄技能**: `BG24_HERO_100p` Whodunit? 仍 DEFERRED，
    但理由已从"任务载荷不可推进"变为**接线工作项**（候选池须改用
    `game.quest_offer_pool()`）——见 `ENGINE_BACKLOG` #20。
  - **逐卡条件口径、近似边界、DEFERRED 台账**见
    `docs/agents/QUEST_DEFERRED_SPEC.md`（2026-09-18 重写）。

---

## 12. 异常（Anomalies）

异常是对局开始前的全局规则修改，会从根本上改变游戏玩法。

### 12.1 异常类型分类

| 类型 | 示例 |
|------|------|
| **经济修改** | Money Match（起始 10 金）、Golganneth's Tempest（随从 2 金，不能刷新） |
| **等级修改** | Big League（只有 T3-T6）、Little League（只有 T1-T4）、How to Even（只有 T2/T4/T6） |
| **种族限制** | Oops, All Beasts!（只有野兽）、Oops, All Demons!（只有恶魔）等 |
| **战斗修改** | Anomalous Twin（复制最高生命随从）、Blessed or Blighted（左获圣盾右获复生） |
| **英雄统一** | Nguyen's Shifting Disks（所有人都是 Nguyen）、Marin's Treasure Box（所有人都是 Marin） |
| **特殊机制** | Buddies（伙伴系统）、Quests（任务系统）、Trinkets（饰品系统） |
| **三连修改** | False Idols（2 个合成金色）、A Faire Reward（三连奖励变暗月奖品） |

### 12.2 部分异常详细说明

#### False Idols（虚假偶像）
- 只需要 **2 个相同随从**即可合成金色。
- 三连奖励改为获得 **1 枚金币**。
- 金色随从泛滥，经济优势巨大。

#### Golganneth's Tempest（高戈奈斯的暴风雨）
- 所有随从费用为 **2 金**。
- **不能主动刷新**酒馆；购买一张卡牌后酒馆自动刷新。
- 适合 APM 流派（海盗、鱼人、元素）。

#### Money Match（金钱对决）
- 起始拥有 **10 金**。
- 可以快速升级酒馆或大量购买随从。

#### Mimiron's Clockwork Stadium（米米尔隆的机械竞技场）
- **不能用金币升级酒馆**；酒馆每 2 回合自动升级。
- 金币只能用于购买随从和刷新。

---

## 13. 已退役机制

以下机制已不在标准卡池中使用，但引擎保留支持：

| 机制 | 说明 | 退役时间 |
|------|------|---------|
| **Mega-Windfury** | 每回合攻击 4 次 | 早期赛季 |
| **Frenzy** | 首次受到伤害时触发 | Patch 25.x |
| **Poisonous（旧版鱼人广泛分布）** | 已被 Venomous 部分替代 | Season 10+ |

---

## 附录：战斗流程状态机

```
BEGIN_RECRUIT
  ↓ (玩家操作：购买、出售、刷新、冻结、升级)
END_RECRUIT
  ↓
BEGIN_COMBAT
  → 按优先级触发 Start of Combat 效果：
    1. 饰品 (Trinkets)
    2. 任务奖励 (Quest Rewards)
    3. 随从效果 (Minion abilities)
    4. 英雄技能 (Hero Powers)
  → 确定先攻方（数量多者优先，相同则随机）
  → 循环：左起第一个存活随从攻击 → 随机目标（优先嘲讽）
    → 伤害结算（双向）
    → 检查死亡 → 触发亡语/复生/复仇
  → 直到一方无存活随从
  → 伤害计算（酒馆等级 + 存活随从等级）
  → 应用伤害上限（若适用）
END_COMBAT
  ↓
BEGIN_RECRUIT (下一回合)
```

---

*文档版本：0.4.0 | 最后更新：2026-05-01*

### 7.4.16c 家族**类型身份**通道（`add_family_races`，2026-09-21 记录实现现实）

本小节补充 §7.4.16（家族**标记**通道）与 §7.4.16b（吞噬策略通道）之外的第三类
owner 级家族改写: **类型身份集合**。用于 "Your <family> are both Murlocs and
Dragons" / "…have all minion types" / "…are Dragons"（`BG30_MagicItem_418` /
`BG32_MagicItem_179` / `BG30_MagicItem_971` / `BG30_MagicItem_825`）。

- 契约: `Game.add_family_races(hero, card_id, races, source=)` 写入 owner 级规则;
  `Game.family_races(hero, card_id)` / `Game.effective_races(hero, card_id)` 读取;
  `Minion.races` 返回**基础身份 ∪ 家族改写**（并集, 绝不削减——wiki
  `Multi-type minion` revid 855346 "additions, never exclusions"）;
  `Minion.has_race(race)` 为匹配读取点; `Race.ALL` 经 `race_set` 展开为全 10 族;
  金色经 `TRIPLE_BASE_CARD_ID` 归一; `source` 离场即失效（同 §7.4.16 / §7.4.16b）。
- 作用域: **owner 视角**（棋盘/手牌/酒馆/发现候选）, 对手与共享池本体不改——
  依据官方 Dev Comment（Patch 30.2.0.205267, wiki revid 814123）。
- 权威: wiki `Minion` revid 817925（双类型"benefit from the effects of both
  types"）、`Multi-type minion` revid 855346、`All` revid 893299。
- 已知残留: 部分脚本/引擎读取点仍按**单值** `.race` 读取（`ENGINE_BACKLOG` §A1/B2-4
  记录了已转换与保留清单）——这是**已记录的边界**, 不是隐藏近似。
