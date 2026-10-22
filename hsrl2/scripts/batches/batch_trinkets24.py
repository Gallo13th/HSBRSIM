"""批次 trinkets24 — 饰品第二十四批（作业单 2026-09-13，20 张）。

台账来源: `docs/agents/TRINKET_LEDGER.md` 片 2（`BG30_MagicItem_944` …
`BG32_MagicItem_806`）。20/20 均在 `CardDB.trinket_offer_pool()` 中
（运行核验），与既有 `batch_trinkets1..26` 的 id 集合互不相交。

数值一律 `CardDef.num(i)`（缺失且文本无占位符时按 SOP §3 用文本字面量，
逐卡在 `Params:` 行声明）；关联卡一律走数据链
`CardDef.evolution_card_id` → `CardDB.by_dbf`（RULES §7.4.6），
**禁止**凭卡名硬编码 id；随机一律 `game.rng`（带可读 label）；
金色 = `db.golden_version(def)` 独立卡定义；状态写在 hero 作用域 tag /
source 实体属性 / 监听闭包（无 game 级 flag——SOP §12 item 9）。

**本轮新引擎原语逐张复核**（作业单列出的"可解冻"清单 + 工作区实际
落地情况）:
  - `game.minion_destroyed` 事件 + `game.destroy_minion()`（`hsrl2/
    events.py` / `hsrl2/game.py`；工作区已落地，docstring 明确点名本批
    的 204/205）→ **解冻 `BG32_MagicItem_204` Kel'Thuzad Portrait 与
    `BG32_MagicItem_205` Maw Caster Portrait**（"After you destroy a
    minion outside combat" 首次有了施动方 + 阶段可判的唯一观察点）。
  - `hsrl2.actions.racefx.elemental_give_bonus(source)` **已有真实生产
    消费点**（`batch_deathrattle.DancingBarnstormerScript` BC/DR 三处 +
    `batch_econ_misc.UnleashedManaSurgeScript` 一处；
    `grep -rn "elemental_give_bonus(" hsrl2/` 命中调用而非仅定义）→
    `ELEMENTAL_EXTRA_ATK/HEALTH` 不再是"写 tag 无人读"（旧台账
    ENGINE_BACKLOG §A10 已过期）→ **解冻 `BG32_MagicItem_802`
    Fountain Pen**。
  - `game.add_tavern_entity` + `tavern_entity_added` 入馆观察点
    （RULES §7.4.9）→ **解冻 `BG30_MagicItem_992` Darnassus Pie**:
    "Minions in the Tavern have +1/+1 for each minion you've sold this
    turn" 以"`minion_sold` 全馆重算 + 入馆即授 + 回合开始回收"表达
    （ENGINE_BACKLOG §B13 给出的两条实现路径之一，无需新引擎原语）。
  - `trigger_deathrattle` / `grant_combat_deathrattle` /
    `add_tier_aura` / `add_permanent_spellcraft_rule` /
    `cast_spell_effect` / `grant_card_copy_to_hand` 语义 / Transform
    `on_transform` / `run_combat` `_magnetic_stack` 恢复 /
    `card_gained` / `card_discovered` / `spell_resolving`: 本批 20 张
    **无一张**的文字命中这些原语族（逐张核对文本后确认）——
    其余 15 张的阻塞点是**另外**的缺口（见下 DEFERRED 台账）。
  - `BG32_MagicItem_280` Eclectic Shrine 的两处历史 AMBIGUOUS 已由
    仓内既有先例裁决（见该类 docstring 的 Evidence）。

注册 5 张（CORRECT）
═══════════════════════════════════════════════════════════════════════
  BG32_MagicItem_204  Kel'Thuzad Portrait  — 数据链交付 Archlich
      Kel'Thuzad + 监听 `minion_destroyed`（施动方=本人 ∧ 战斗外）→
      全体己方存活随从 +2/+2（文本字面量）。
  BG32_MagicItem_205  Maw Caster Portrait  — 数据链交付 Maw Caster
      （池随从 T4，占池）+ 同一摧毁观察点 → `GainGold(num(0)=2)`。
  BG32_MagicItem_280  Eclectic Shrine      — SoC: 对 10 个标准种族各
      随机选一只合格友方随从 +num(0)/+num(1)；每次触发后永久递增
      （"Improve this permanently" = 后续触发按印面值累加）。
  BG32_MagicItem_802  Fountain Pen         — 永久
      `ELEMENTAL_EXTRA_ATK += 2` / `ELEMENTAL_EXTRA_HEALTH += 1`
      （文本字面量 "+2/+1"）; 消费点 `racefx.elemental_give_bonus`。
  BG30_MagicItem_992  Darnassus Pie        — 每售出 1 只随从，本人酒馆
      内全部随从 +1/+1（文本字面量）; 入馆随从继承当前计数; 回合开始
      回收仍留在酒馆中的已授 buff 并清零计数（买入带走的保留）。

DEFERRED 15 张 → **13 张**（**不注册**；逐张 Status / Dependency /
Implementation path——SOP §6b 二态铁律）。
**2026-09-21 迁出 2 张**: 971 Enforcer / 179 Drakkari Portrait 由
`batch_family_races` 注册（RACES 家族类型身份改写）。
═══════════════════════════════════════════════════════════════════════
  BG30_MagicItem_944 Redeemer Portrait — "Get a Nalaa the Redeemer.
      Your Nalaa the Redeemers give an extra +{0}/+{1}."
      Dependency: (a) 载荷 `BG28_551` Nalaa the Redeemer **未注册**
      （"Whenever you cast a Tavern spell, give a friendly minion of
      each type +4/+3" 无实现）; (b) "give an extra +{0}/+{1}" 需要
      **给予者家族级的加成读取通道**（数值 `{0}/{1}` 已由饰品 CardDef
      提供 = num(0)/num(1)=4/4，但读取方必须是 Nalaa 本体脚本）。
      Implementation path: 先迁 `BG28_551`（"of each type" 用
      `ALL_BG_RACES` 先例 + `rng.choice`），并在其脚本内读 hero 级
      `_nalaa_extra_atk/_nalaa_extra_health`（本饰品 on_bind 递增 +
      数据链交付）；读取点必须真实可达（W3）。
  BG30_MagicItem_971 Enforcer Portrait — "Your Lightfang Enforcers have
      all minion types."
      Dependency: `GameTag.RACE` 单值; `Race.ALL` = "匹配一切种族查询"
      而非"同时属于多个类型"（`Race.ALL` 用于 Amalgam 是**天生**全
      类型，不是运行时追加）; 且载荷 `BGS_009` 未注册（其 EoT
      "give a friendly minion of each type +4/+4" 无实现）。
      Implementation path: `RACES` 集合/位掩码 tag + 全部 race 读取点
      改造（ENGINE_BACKLOG §A1）+ 迁 `BGS_009`（金色
      `TB_BaconUps_082`）。
  BG30_MagicItem_987 Balladist Portrait — "Get a Lovesick Balladist.
      At the start of each turn, get another. Your Lovesick Balladists
      also give Attack."
      Dependency: "also give Attack" 的**数值无权威**——`BG26_814` XML
      只有 `TAG_SCRIPT_DATA_NUM_2=1`（Health 基值），`{0}`（Attack）
      在 base/golden 两个 CardDef 均为 None，饰品 CardDef 无任何模板
      参数; wiki 卡页（Balladist Portrait / Lovesick Balladist）无
      Notes，仅有 [Targeted] 与 34.6 "+0→+1 Health" 变更记录。
      已查信源: hearthstone.wiki.gg 两页、官方 32.2.3/34.6/35.x 补丁
      说明、Bug 报告帖（us.forums 136525 确认"Rylak 触发时同时给
      Attack 与 Health"，但未给增量）。候选读法: (A) Attack = Health
      增量（等值）; (B) 固定 +1; (C) 隐藏常量。三者无证据可裁。
      Implementation path: 权威落地后——(i) 交付 + SoT "get another"
      走 `grant_card_copy_to_hand`（池随从 BG26_814 占池）;
      (ii) `BG26_814` 脚本读 hero 级 "also give Attack" 标记（本饰品
      on_bind 写入），battlecry 的 Buff 增补同额 Attack。
  BG30_MagicItem_994 Yogg-Tastic Pastry — "Spin the Wheel of Yogg-Saron.
      At the start of each turn, spin it again."
      Dependency: 全库无 Wheel of Yogg-Saron 实现，数据中亦无结果表
      token（`grep -i wheel hsrl2/` 只命中无关卡名 Dalaran Cheese
      Wheel / Water Wheel）。同缺口已由 batch_quest_rewards3
      （BG24_Reward_135）与 batch_anomalies3（BG27_Anomaly_503）备案。
      Implementation path: 引擎 `game.spin_wheel(hero)` + 每个结果的
      card_id/数值数据权威 → 本卡 on_bind / start_of_turn 各调用一次。
  BG32_MagicItem_179 Drakkari Portrait — "Your Drakkari Enchanters are
      both Mechs and Elementals."
      Dependency: 与 971 同一 `RACES` 缺口（**两个具体种族**，用
      `Race.ALL` 会错误匹配 Beast/Dragon/…）。载荷 `BG26_ICC_901`
      已注册（交付侧就绪）但半实现 = 第三态。
      Implementation path: 同 §A1; 改造后 on_bind 为本人 Drakkari
      Enchanter **实例**追加 MECH/ELEMENTAL（未来副本经入板钩子）。
  BG32_MagicItem_274 Bristlebach Portrait — "Get a Bristlebach. Your
      Bristlebachs play Blood Gems on all friendly minions."
      Dependency: 载荷 `BG26_157` Bristlebach **未注册**（本体
      "Avenge (2): This plays 2 Blood Gems on all your Quilboar" 无实现）
      → 授予的 Bristlebach 永不触发，"把目标范围改成全体友方"的改写
      对象不存在（RULES §7.4.6 例外条款: 效果**依赖** X 的行为）。
      Implementation path: 先迁 BG26_157（`avenge_threshold=2` +
      `PlayBloodGems`），其脚本读 hero 级 target-scope 标记
      （本饰品 on_bind 写入 + 数据链交付）。
  BG32_MagicItem_283 Czarina Portrait — "Get a Charging Czarina. Your
      Charging Czarinas also give Health."
      Dependency: (a) "also give Health" 的**数值无权威**——`BG28_741`
      XML 只有 `TAG_SCRIPT_DATA_NUM_1=4`（Attack），Health 增量在
      base/golden/饰品三个 CardDef 均无字段; wiki 卡页无 Notes;
      (b) `BG28_741` `ChargingCzarinaScript` 只给 Attack、不读任何
      加成通道（在饰品侧另注册监听 = 归属错误: Czarina 被出售后仍
      生效 → 近似，SOP §6b 禁止）。
      Implementation path: 补 Health 增量的数据/官方权威 + 载荷脚本读
      hero 级标记（本饰品 on_bind 写入 + 数据链交付）。
  BG32_MagicItem_300 Putricide Sticker — "Craft a custom Undead. At the
      start of every 2 turns, repeat this. ({0} turns left!)"
      Dependency: "Craft a custom Undead" 是 Putricide 多步部件合成链
      （种族 + 关键词 + 属性选择 → `BG25_HERO_100pt` token）; 全仓无
      `craft` 实现，`BG25_HERO_100p` Build-An-Undead 技能亦因此
      DEFERRED。数值 {0}=num(0)=2 已就绪。
      Implementation path: 建立多步 PendingChoice 合成协议（部件卡片
      池 + 参数落点）后 on_bind / 每 {0} 回合 start_of_turn 触发。
  BG32_MagicItem_350 Splinter of Aurum — "When you have {1} Gold, get a
      random Golden Tier 5 minion. (Once per game.)"
      Dependency: 引擎无金币**增加**观察点——`events.py` 只有
      `gold_spent`; 收入路径（`_begin_recruit_for` 基础收入 /
      `sell_minion` 的 `hero.gold +=` / `GainGold` action）均不广播
      （`grep -rn "gold_gained" hsrl2/` 只命中他批 docstring）。
      回合收入在饰品 `start_of_turn` **之前**结算，故 start_of_turn
      只覆盖回合收入、漏掉回合内收入（出售/海盗/法术给金）→ 近似，
      SOP §6b 禁止。数值 {1}=num(1)=15; 交付侧（随机金色 T5 +
      `GILDED_NOT_TRIPLED` 配平）已就绪。
      Implementation path: 引擎在金币增加点 fire
      `gold_gained(hero=, amount=)`（或 hero 级
      `MINIONS_SOLD_THIS_TURN` 式观察点）→ 本卡监听并判
      `hero.gold >= num(1)`，once per game 记在 source 实体。
  BG32_MagicItem_366 Guiding Candle — "Your first two Refreshes each
      turn contain only Tier 6 cards. ({0} left!)"
      Dependency: `refresh_tavern` 只有 `_tavern_offer_tier_only`
      （=与本人酒馆等级同档，Elven Elite）与 `_tavern_min_tier` 下限，
      **无**"指定第 N 档"的精确过滤（`grep -rn
      "_tavern_offer_tier_exact" hsrl2/` 只命中他批 docstring）;
      T9 购买时本人等级可能 < 6，`tavern_tier` 上界封顶使
      `min_tier=6` 无效。数值 {0}=num(0)=2 已就绪。
      Implementation path: 引擎增 `hero._tavern_offer_tier_exact = N`
      读取点（`refresh_tavern` 内 `min_tier = max_tier = N`）+ 每回合
      前 num(0) 次**玩家主动**刷新计数（`auto=True` 排除，Frigid
      Blossom 口径）。
  BG32_MagicItem_417 Tarecgosa Sticker — "Your left and right-most
      Dragons permanently keep Bonus Keywords and stats gained in
      combat."
      Dependency: 双重阻塞——(a) `Bonus Keyword` 定义域无任何数据字段
      （RULES §9.6，与 Finley's Helmet 891 / Vibrant Bubble 892 同族）;
      (b) 引擎 PERSIST 是**单实体全量** tag
      （`PERSIST_COMBAT_CHANGES`），无"按位置（最左/最右）+ 种族持续
      授予"的光环原语，且 `run_combat` 的 Poet 通道只覆盖"相邻龙"。
      Implementation path: 见 RULES §9.6 + ENGINE_BACKLOG §B9。
  BG32_MagicItem_419 Yu'lon Sticker — "Start of Combat: Make your
      highest-Tier Dragon Golden."
      Dependency: 战斗→招募的 **Transform 持久化**缺失——
      `run_combat` 的 finally 用 `hero.board = list(board_before[hero])`
      整体复原，SoC 期间 `Transform` 出的金色实体不在战前列表中，被
      丢弃（官方预期 = 下一招募阶段仍为金色，Blizzard 论坛 bug 报告
      多玩家确认）。`Transform` 的 `on_transform` 重接线只解决被动
      重接线，不解决快照身份保留。数值/选取（最高档并列取最左、
      race ∈ (DRAGON, ALL)、`golden_version` 存在）均已就绪。
      Implementation path: `GameTag.PERSIST_TRANSFORM` 白名单 + restore
      阶段对"战前实体已被 Transform"的情形保留新实体（含 GOLDEN /
      TRIPLE_BASE_CARD_ID / `GILDED_NOT_TRIPLED`）。
  BG32_MagicItem_803 Macaw Portrait — "Get a Monstrous Macaw. Your
      Monstrous Macaws also trigger your left-most Battlecry."
      Dependency（2026-09-13 订正）: 载荷 `BGS_078`（金色
      `TB_BaconUps_135`）**已注册**（`batch_payload_minions`，本体
      Rally "Trigger your left-most Deathrattle" 就绪）——本条"未注册"
      记载已过期; "also trigger your left-most Battlecry" 由载荷
      `rally` 读 `FLAG_MACAW_EXTRA_BATTLECRY` 追加最左战吼项。
      Implementation path: 见 batch_trinkets36。
      Status: 已迁出 → batch_trinkets36（2026-09-13，RULES §7.4.17
      条件化战吼第二消费者）; 原阻塞（"最左战吼"资格集权威）已消除:
      论坛 32.2 复现串 `M G x B y z`（跳过非战吼 x）→ 资格集 =
      带战吼者。
  BG32_MagicItem_804 Selfless Portrait — "Get a Selfless Hero. Your
      Selfless Heroes also trigger on Battlecry."
      Dependency（2026-09-13 订正）: 载荷 `BG_OG_221`（金色
      `TB_BaconUps_014`）**已注册**（`batch_payload_minions`，亡语就绪）
      ——本条"未注册"记载已过期。真实残余阻塞 = "also trigger on
      Battlecry"的读法（两读法均未被官方文本排除）+ **条件化战吼**
      引擎协议（直增 `battlecry` 钩子会让无饰品时的本体误吃
      `bc_first` 配额/误入战吼目标集——见 batch_trinkets29/30 台账
      2026-09-13 实测补充）。
      Implementation path: 主线裁定读法 + 落地条件化战吼声明。
      Status: 已迁出 → batch_trinkets35（2026-09-13，RULES §7.4.17
      条件化战吼协议; 读法由 32.4 补丁说明裁定）; 原阻塞: "also
      trigger on Battlecry"缺条件化战吼引擎协议 + 读法未定。
  BG32_MagicItem_806 Battlecruiser Portrait — "Get an 12/12
      Battlecruiser. Whenever the Tavern is Refreshed, add a
      Battlecruiser Upgrade to it."
      Dependency: 三处缺口——(a) 载荷 `BG31_HERO_801pt`（2/2 白板
      token）**未注册**且需 12/12 属性覆盖（"Get an 12/12"）;
      (b) `Battlecruiser Upgrade` 子系统未实现（10 张
      `BG31_HERO_801pta..j` card_type=42 存在但 Jim Raynor
      `BG31_HERO_801p` 整条技能链 DEFERRED，batch_hero_combat3 台账）;
      (c) "add ... to it" 是**馆内/棋盘已有卡追加部件**协议，
      `inject_tavern_minion` 无法表达。
      Implementation path: 先实现 Jim Raynor 的 Upgrade 商店/附着协议。

关联卡台账（RULES §7.4.6——关联卡自身脚本状态不阻塞本批 CORRECT）
═══════════════════════════════════════════════════════════════════════
  | 饰品 | 关联卡（数据链 `evolution_card_id` → `db.by_dbf`） | 脚本状态 |
  |------|--------------------------------------------------|-----------|
  | BG30_MagicItem_944 | BG28_551 Nalaa the Redeemer（非池） | **未注册**
  |                    |                                     | → 整卡
  |                    |                                     | DEFERRED
  | BG30_MagicItem_971 | BGS_009 Lightfang Enforcer（非池）  | **未注册**
  |                    | （金色 TB_BaconUps_082）             | → 整卡
  |                    |                                     | DEFERRED
  | BG30_MagicItem_987 | BG26_814 Lovesick Balladist（池 T4）| 已注册
  |                    |                                     | （batch_battlecry）
  | BG32_MagicItem_179 | BG26_ICC_901 Drakkari Enchanter（池 T5）| 已注册
  | BG32_MagicItem_204 | BG28_308 Archlich Kel'Thuzad（非池）| 未注册（**不
  |                    |                                     | 阻塞**——本
  |                    |                                     | 饰品效果与
  |                    |                                     | 其行为无关）
  | BG32_MagicItem_205 | BG32_340 Maw Caster（池 T4）        | 已注册
  |                    |                                     | （batch_misc）
  | BG32_MagicItem_274 | BG26_157 Bristlebach（非池）        | 已注册（batch_trinkets34）
  |                    |                                     | → 整卡
  |                    |                                     | DEFERRED**
  | BG32_MagicItem_283 | BG28_741 Charging Czarina（池 T5）  | 已注册
  |                    |                                     | （batch_econ_misc）;
  |                    |                                     | 但缺加成读取
  |                    |                                     | 通道 → 整卡
  |                    |                                     | DEFERRED
  | BG32_MagicItem_803 | BGS_078 Monstrous Macaw（非池）     | 已注册（batch_payload_minions）
  |                    |                                     | ；已迁出 →
  |                    |                                     | batch_trinkets36
  | BG32_MagicItem_804 | BG_OG_221 Selfless Hero（非池）     | 已注册（batch_payload_minions）
  |                    |                                     | ；已迁出 →
  |                    |                                     | batch_trinkets35
  | BG32_MagicItem_806 | BG31_HERO_801pt Battlecruiser（token）| **未注册
  |                    |                                     | → 整卡
  |                    |                                     | DEFERRED**
  说明: 992 / 280 / 802 / 417 / 419 / 994 / 300 / 350 / 366 的
  `evolution_card_id` 为空（无关联卡），其效果完全由本脚本表达。

引擎缺口（本批新上报 / 需主线排期；阻塞卡 id 附）
═══════════════════════════════════════════════════════════════════════
  1. **`MINIONS_SOLD_THIS_TURN` hero 级读取点**（阻塞 992 的**边界
     精度**，非阻塞注册）: `minion_sold` 只在售出当下广播，无历史查询
     点 → 本饰品在**获得当回合**、于购买饰品**之前**售出的随从不可见
     （Windfall Portrait `BG32_MagicItem_832` 已备案同一缺口）。实现
     路径: `sell_minion` 成交后 `hero.set(MINIONS_SOLD_THIS_TURN, n+1)`
     + 每回合 `Hero.clear` 归零 → 脚本 on_bind 读该 tag 即得全回合
     精确值。
  2. **`gold_gained` 观察点**（阻塞 350 + 他批）。
  3. **`hero._tavern_offer_tier_exact`（精确档位展示位）**（阻塞 366 +
     BG30_MagicItem_423）。
  4. **多值种族 `RACES`**（阻塞 179 / 971 + 他批 418 / 825）。
  5. **Bonus Keyword 定义域 + 逐实体授予记录**（阻塞 417 + 891 / 892）。
  6. **战斗→招募 Transform 持久化**（阻塞 419）。
  7. **Wheel of Yogg-Saron 结果表 + `spin_wheel`**（阻塞 994）。
  8. **Craft 合成选择链**（阻塞 300 + BG25_HERO_100p）。
  9. **家族级"给予者加成"读取通道 + 增量权威**（阻塞 944 / 987 /
     283 / 274）——引擎侧无需新原语，但需载荷卡脚本 + hero 级读取点
     （W3 必须可达）。
  10. **Battlecruiser Upgrade 附着子系统**（阻塞 806 + Jim Raynor）。

接线审计读取点（W1/W2/W3 核对）
═══════════════════════════════════════════════════════════════════════
  饰品仅分发 `on_bind` / `start_of_turn` / `end_of_turn` /
  `start_of_combat`（W1 白名单）。监听事件全部有真实生产点:
  `minion_destroyed`（`Game.destroy_minion`——唯一广播点）、
  `minion_sold`（`Game.sell_minion`）、`tavern_entity_added`
  （`Game.add_tavern_entity`）。私有标记写入全部落在 `source._x`
  （W3 只扫 `game|g|hero|h._x =`）: `_eclectic_triggers`（本类
  `start_of_combat` 自读）、`_pie_sold` / `_pie_buffs` /
  `_pie_stamped`（本类 on_bind/start_of_turn 自读）。hero 作用域只写
  引擎 tag: `ELEMENTAL_EXTRA_ATK/HEALTH`（唯一读取方
  `racefx.elemental_give_bonus`，有真实生产调用点）。
"""

from __future__ import annotations

from typing import List

from hsrl2 import entity
from hsrl2.actions import Buff, GainGold
from hsrl2.events import MINION_DESTROYED, MINION_SOLD, Listener
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race

# ── 本批卡 id（CardDB 按名核实，禁止凭记忆写） ──
REDEEMER_PORTRAIT = "BG30_MagicItem_944"
ENFORCER_PORTRAIT = "BG30_MagicItem_971"
BALLADIST_PORTRAIT = "BG30_MagicItem_987"
DARNASSUS_PIE = "BG30_MagicItem_992"
YOGG_TASTIC_PASTRY = "BG30_MagicItem_994"
DRAKKARI_PORTRAIT = "BG32_MagicItem_179"
KELTHUZAD_PORTRAIT = "BG32_MagicItem_204"
MAW_CASTER_PORTRAIT = "BG32_MagicItem_205"
BRISTLEBACH_PORTRAIT = "BG32_MagicItem_274"
ECLECTIC_SHRINE = "BG32_MagicItem_280"
CZARINA_PORTRAIT = "BG32_MagicItem_283"
PUTRICIDE_STICKER = "BG32_MagicItem_300"
SPLINTER_OF_AURUM = "BG32_MagicItem_350"
GUIDING_CANDLE = "BG32_MagicItem_366"
TARECGOSA_STICKER = "BG32_MagicItem_417"
YULON_STICKER = "BG32_MagicItem_419"
FOUNTAIN_PEN = "BG32_MagicItem_802"
MACAW_PORTRAIT = "BG32_MagicItem_803"
SELFLESS_PORTRAIT = "BG32_MagicItem_804"
BATTLECRUISER_PORTRAIT = "BG32_MagicItem_806"

# ── 文本字面量（CardDef 无模板参数且文本无占位符 —— SOP §3 允许，
#    逐值在各类 `Params:` 行声明，禁止静默漂移） ──
_PIE_ATK = 1                # BG30_MagicItem_992 "for each minion you've
_PIE_HEALTH = 1             # sold this turn"（每售 1 只 +1/+1）
_KELTHUZAD_ATK = 2          # BG32_MagicItem_204 "give your minions +2/+2"
_KELTHUZAD_HEALTH = 2
_FOUNTAIN_ATK = 2           # BG32_MagicItem_802 "grant an extra +2/+1"
_FOUNTAIN_HEALTH = 1

# 全部标准种族（Amalgam 规则: ALL 型随从对每个种族都合格——
# batch_rally.ALL_BG_RACES / batch_trinkets3 `_ALL_MINION_RACES` 同源）
_ALL_BG_RACES = tuple(
    r for r in Race if r not in (Race.INVALID, Race.NONE, Race.ALL)
)

_ECLECTIC_LABEL = "eclectic_shrine_pick"


def _hero(ctx):
    """on_bind ctx → 饰品持有英雄（引擎 grant_trinket 传 ctx={"hero": h}）。"""
    return (ctx or {}).get("hero")


def _num(game, card_id: str, index: int) -> int:
    """CardDef 模板参数（缺失 → fail-loud，SOP §3）。"""
    d = game.db.get(card_id)
    value = d.num(index) if d is not None else None
    if value is None:
        raise GameStateError(
            f"{card_id}: missing num({index}) template parameter")
    return value


def _living(hero) -> List[Minion]:
    return [m for m in hero.board if not m.dead]


# ══════════════ BG32_MagicItem_204 Kel'Thuzad Portrait ══════════════


class KelThuzadPortraitScript:
    """
    Natural language: [x]Get an Archlich Kel'Thuzad. After you destroy a
    minion outside combat, give your minions +2/+2.

    Formal spec:
      1. on_bind: 数据链交付——`game.trinket_related_card(本饰品)`
         （`evolution_card_id` 105518 → `BG28_308` Archlich Kel'Thuzad，
         36.2.2 数据核实; 非池卡 `is_pool_minion=False` → 统一入口
         **零池操作**，RULES §7.4.6）→ `grant_card_copy_to_hand`
         （白板副本进手牌; 满手入等待队列 RULES §3.3）。关联卡本体
         （EoT "destroy the Undead to the left … resummon an exact
         copy"）尚未迁移——按 RULES §7.4.6 不阻塞本饰品（本饰品的
         触发条款与其行为**无关**）
      2. 注册 `minion_destroyed` 持久监听（owner=饰品; 引擎
         `Game.destroy_minion` 是**唯一**广播点——RULES §7.4.11 / 该
         API docstring）:
           a) 施动方过滤 `hero is 本人`（"**you** destroy"——对手用
              Destroy 效果不触发）
           b) 阶段过滤 `in_combat is False`（"outside combat"——战斗内
              摧毁由 `run_combat` 的死亡链处理，无该事件）
      3. 触发: 全体本人棋盘**存活**随从 `Buff(+2/+2)` 永久（"give your
         minions +X/+Y" = 永久增益，SOP §3 动词表; 被摧毁者此时已离场
         ——`destroy_minion` 先跑死亡链再广播，故不入增益集）
      4. 数值: 文本字面量 "+2/+2"（BG32_MagicItem_204 num(0..3) 全
         None 且文本无占位符——SOP §3 允许字面量，此处声明）
      5. 落空: 棋盘无存活随从 → 不产生 Action（不报错、不消耗资源）;
         摧毁一个**已经死亡/非 PLAY** 的实体 → `destroy_minion` 返回
         False 且不广播 → 不触发
      6. 只作用于本人; 副本条款: 两份副本各注册监听 → 每次摧毁各叠
         一份（= 官方副本语义）

    Test: test_batch_trinkets24.py — 绑定后手牌出现 BG28_308（非池 →
      池余量不变）/ 真实 `destroy_minion(hero=本人)` 后全体己方存活
      随从 +2/+2（正对照: 无饰品不变）/ `in_combat=True` 时不触发 /
      对手施动不触发 / 无存活随从落空（不报错）/ 已死实体不广播 →
      不触发 / 两份副本叠加 / 真实 `end_recruit_phase` 后监听仍在

    Params: atk=2 health=2（文本字面量 "+2/+2"; CardDef 无模板参数）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        rel = game.trinket_related_card(source.card_id)
        if rel is not None:
            game.grant_card_copy_to_hand(h, rel)

        def cond(hero=None, in_combat=None, **kw):
            return hero is h and not in_combat

        def on_destroyed(g, minion=None, **kw):
            targets = _living(h)
            if not targets:
                return
            g.run_actions([Buff(m, atk=_KELTHUZAD_ATK,
                                health=_KELTHUZAD_HEALTH)
                           for m in targets])

        game.events.register(Listener(event=MINION_DESTROYED, owner=source,
                                      callback=on_destroyed, condition=cond))
        return None


# ══════════════ BG32_MagicItem_205 Maw Caster Portrait ══════════════


class MawCasterPortraitScript:
    """
    Natural language: [x]Get a Maw Caster. Whenever you destroy a minion
    outside combat, gain {0} Gold.

    Formal spec:
      1. on_bind: 数据链交付——`evolution_card_id` 121508 → `BG32_340`
         Maw Caster（**池随从** T4，`is_pool_minion=True` 36.2.2 核实）
         → `grant_card_copy_to_hand` 先 `minion_pool.acquire` 占池 1 份;
         池中无副本 → 本次交付落空（RULES §2.4/§7.4.6），但监听照常
         接线（落空只影响本次交付）。其本体（Battlecry "Destroy a
         friendly Undead to Discover an Undead"）已由 batch_misc 迁移，
         且已走 `game.destroy_minion` 统一入口（本饰品因此能观察到
         自己 Maw Caster 的摧毁——端到端联动）
      2. 注册 `minion_destroyed` 持久监听（同 204 的过滤口径）:
         `hero is 本人` ∧ `in_combat is False` → `GainGold(本人, num(0))`
      3. 数值: `{0}` = num(0)（36.2.2 = 2）——`CardDef.num()` 唯一权威
      4. 触发不要求被摧毁者属于任何一方（"destroy a minion" 含敌方，
         `destroy_minion` 的 `hero=` 是施动方）; 只要求施动方是本人
      5. 落空: 无
      6. 副本条款: 两份副本各注册监听 → 每次摧毁各 +num(0) 金

    Test: test_batch_trinkets24.py — 绑定后手牌出现 BG32_340 且池 -1 /
      真实 `destroy_minion(hero=本人)` 后本人金币 +num(0)（正对照:
      无饰品不变）/ `in_combat=True` 不加金 / 对手施动不加金 /
      真实 Maw Caster 战吼（`destroy_minion` 路径）同样触发 /
      两份副本叠加 / 池守恒（摧毁回池 + 交付占池）

    Params: {0}=num(0)=2（BG32_MagicItem_205）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        game.grant_trinket_related_card(h, source.card_id)

        def cond(hero=None, in_combat=None, **kw):
            return hero is h and not in_combat

        def on_destroyed(g, minion=None, **kw):
            g.run_actions(GainGold(h, _num(g, source.card_id, 0)))

        game.events.register(Listener(event=MINION_DESTROYED, owner=source,
                                      callback=on_destroyed, condition=cond))
        return None


# ══════════════ BG32_MagicItem_280 Eclectic Shrine ══════════════


class EclecticShrineScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Give a friendly minion
    of each different type +{0}/{1}. Improve this permanently.

    Evidence:
      - 资格集口径 = 仓内既有先例（同款 "a friendly minion of each
        type"）: `batch_spells3.MisplacedTeaSetScript` 与
        `batch_rally.TheLastOneStandingScript`——对**全部 10 个标准
        种族**各自独立随机选一只（`ALL_BG_RACES`），ALL 型随从对每个
        种族都合格且**可被多族重复选中**（官方 Amalgam 语义;
        Misplaced Tea Set 的 reddit 实测问句 + 官方 34.6 The Last One
        Standing 文本）。"each different type" 与 "each type" 同义。
      - "Improve this permanently" 的增量 = 印面值、且作用于**后续**
        触发（Improve 家族全仓惯例: `batch_choose_one` Lurking
        Leviathan / `batch_hero_combat3` Onyxia Broodmother /
        `batch_trinkets18` Fang Anklet / `batch_quest_rewards3` Tumbling
        Disaster——首次触发用基准值，之后累加）。wiki 卡页 tags 含
        `Upgradable` / `Increment attack` / `Increment health`，无
        相反 Notes。

    Formal spec:
      1. `start_of_combat`（饰品 SoC 钩子——引擎顺序 饰品→奖励→棋盘→
         手牌）: 读 `source._eclectic_triggers` = n（本饰品已触发次数，
         跨战斗永久）; 本次数值 = num(0)×(1+n) / num(1)×(1+n)
      2. 对 `r ∈ _ALL_BG_RACES`（10 个标准种族）:
         候选 = 本人棋盘**存活**、`race ∈ (r, ALL)` 的随从; 有候选 →
         `game.rng.choice(候选, label="eclectic_shrine_pick")` →
         `Buff(pick, atk=atk, health=health)`（战斗期增益——战后由
         `run_combat` 快照恢复回滚，RULES §3.5; 无需 temporary 标记，
         与 Holy Mallet / Fang Anklet 同口径）
      3. 同一随从可被多个种族分别选中（每命中一次一份 buff）;
         无任何候选（空棋盘 / 全 NONE 型）→ 本次不产生 Action（落空，
         不报错）
      4. 触发后 `source._eclectic_triggers = n + 1`（**每次 SoC 结算
         各改善一次**——含 `soc_extra` / `soc_first` 的额外触发:
         "Your Start of Combat effects trigger an extra time" 会额外
         结算一次效果，改善随之再 +1）
      5. 只作用于本人棋盘（对手随从不被 buff——owner 由
         `source.controller` 确定）
      6. 副本条款: 两份副本各有独立计数与各自 SoC 钩子 → 基础与每次
         改善各叠加两份

    Test: test_batch_trinkets24.py — 棋盘 鱼人/机械/龙 各一只 → 各
      +num(0)/+num(1) 恰一次（总量断言，随机无关; 正对照: 无饰品不变）/
      第二次 SoC → 2×（改善永久: 跨 `run_combat` 保留）/ ALL 型随从
      单独在场 → 10 份 buff（每族各命中一次）/ 对手棋盘不变 /
      空棋盘落空且计数仍 +1（不报错）/ 同 seed 两次运行选取序列一致 /
      真实 `run_combat` 走引擎 SoC 派发（战斗内探针）

    Params: {0}=num(0)=3 {1}=num(1)=2（BG32_MagicItem_280）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        base_atk = _num(game, source.card_id, 0)
        base_health = _num(game, source.card_id, 1)
        n = getattr(source, "_eclectic_triggers", 0)
        atk = base_atk * (1 + n)
        health = base_health * (1 + n)
        actions = []
        for race in _ALL_BG_RACES:
            cands = [m for m in h.board
                     if not m.dead and m.race in (race, Race.ALL)]
            if not cands:
                continue
            pick = game.rng.choice(cands, label=_ECLECTIC_LABEL)
            actions.append(Buff(pick, atk=atk, health=health))
        source._eclectic_triggers = n + 1
        return actions or None


# ══════════════ BG32_MagicItem_802 Fountain Pen ══════════════


class FountainPenScript:
    """
    Natural language: Your Elementals that give stats grant an extra
    +2/+1.

    Evidence:
      - 官方/数据文本 +2/+1（BG32_MagicItem_802 num(0..3) 全 None、
        文本无占位符 → 文本字面量，SOP §3）; 升级变体
        `BG32_MagicItem_802t`（+4/+2）不在商店池（
        `CardDB.trinket_offer_pool()` 不含）且不在本批 20 张范围内。
      - **消费点已就绪**（旧台账 ENGINE_BACKLOG §A10 / batch_trinkets22
        "写 tag 无人读" 已过期）: `hsrl2/actions/racefx.py::
        elemental_give_bonus(source)` 是元素 give-stats 加成的规范出口
        ——仅当**给予者本身** `race ∈ (ELEMENTAL, ALL)` 时返回
        hero 级 `ELEMENTAL_EXTRA_ATK(1057)` / `ELEMENTAL_EXTRA_HEALTH
        (1055)` 增量; 生产调用点 = `batch_deathrattle.
        DancingBarnstormerScript`（BC/DR/金色 DR 三处）与
        `batch_econ_misc.UnleashedManaSurgeScript`（一处）。

    Formal spec:
      1. on_bind: `hero.ELEMENTAL_EXTRA_ATK += 2` /
         `hero.ELEMENTAL_EXTRA_HEALTH += 1`（hero 作用域 tag——只影响
         本人; 叠加式，不覆盖其它来源如 Amplifying Essence /
         Sand Swirler / Glowing Cinder / Moat Custodian）
      2. 语义: 此后本人**元素**给出的 give-stats 效果按
         `base + extra` 结算（"grant an extra +X/+Y"——extra 是叠加在
         原数值之上的增量）; 非元素给予者（如 Champion of Sargeras /
         Nomi 无种族）不吃加成（`elemental_give_bonus` 的种族守卫）
      3. 数值: 文本字面量 "+2/+1"（CardDef 无模板参数）
      4. 只作用于本人（tag 为 hero 级）; 对手的该 tag 不变
      5. 副本条款: 两份副本各 on_bind → 各叠加 2/1（共 +4/+2）

    Test: test_batch_trinkets24.py — 绑定后 tag == 2/1 且对手 tag 为
      0 / 真实打出 Dancing Barnstormer（元素，战吼给馆内元素
      +num(0)/+num(1)）→ 馆内元素实际获得 (num(0)+2)/(num(1)+1)
      （正对照: 无饰品 = num(0)/num(1)）/ 非元素给予者不吃加成 /
      两次效果叠加 / 两份副本叠加 / 真实 `end_recruit_phase` 后 tag
      仍在（跨回合永久）

    Params: atk=2 health=1（文本字面量 "+2/+1"; CardDef 无模板参数）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        h.set(GameTag.ELEMENTAL_EXTRA_ATK,
              h.get(GameTag.ELEMENTAL_EXTRA_ATK, 0) + _FOUNTAIN_ATK)
        h.set(GameTag.ELEMENTAL_EXTRA_HEALTH,
              h.get(GameTag.ELEMENTAL_EXTRA_HEALTH, 0) + _FOUNTAIN_HEALTH)
        return None


# ══════════════ BG30_MagicItem_992 Darnassus Pie ══════════════


class DarnassusPieScript:
    """
    Natural language: Minions in the Tavern have +1/+1 for each minion
    you've sold this turn.

    Formal spec:
      1. 动态酒馆光环以"`minion_sold` 全馆重算 + 入馆即授 + 回合开始
         回收"表达（ENGINE_BACKLOG §B13 给出的两条实现路径之一; 实体级
         永久 Buff，买入后带走——与 `hero.tavern_buffs` 持久面同口径，
         RULES §7.4.9）:
           - on_bind: 计数 `source._pie_sold =
             hero.MINIONS_SOLD_THIS_TURN`（引擎维护的"本回合已售随从数"
             ——绑定前当回合售出的同样计入; 2026-09-02 对抗审查修正）;
             登记表
             `source._pie_buffs = [(实体, buff)]`（回合开始回收用）
             与 `source._pie_stamped = {uuid: 已授份数}`
           - 注册 `minion_sold` 持久监听（owner=饰品; 引擎
             `Game.sell_minion` 在移出棋盘**前**广播，故
             `minion.controller` 可读）: `minion.controller is 本人` →
             `_pie_sold += 1` 并对全馆**每个 `Minion`** 补齐差值
             （`_pie_sold - stamped`）份 `+1/+1`
           - 注册 `tavern_entity_added` 持久监听（RULES §7.4.9 入馆
             统一观察点——覆盖刷新抽卡 / `inject_tavern_minion` /
             Fodder 注入 / 脚本换卡全部路径，**与监听器注册顺序无关**）:
             `hero is 本人` 的 `Minion` → 立即授 `_pie_sold` 份
             `+1/+1`（"出售后新入馆的随从继承当前计数"）
      2. "for each minion you've sold this turn" 的计数按回合：
         `start_of_turn`（下一招募阶段开始，引擎在 SoT 钩子后才自动
         刷新）移除**仍在本人酒馆中**的已登记 buff（clamp 当前血至
         上限）并清空计数/登记表; 已被**买入**（离开酒馆）的实体保留
         其属性（购买带走的战利品不回收——这正是本饰品的用途）
      3. 数值: 文本字面量 "+1/+1"（BG30_MagicItem_992 num(0..3) 全
         None 且文本无占位符）
      4. 冻结点: `start_of_turn` 早于 `refresh_tavern(auto=True)`，
         故冻结保留的旧随从先被回收（计数已归零 = "+0/+0"），
         随后刷新抽入的新随从按 0 份授予——与本回合计数语义一致
      5. 只作用于本人酒馆（对手售出不计入、对手酒馆不被 buff——
         owner + controller 双过滤）; 副本条款: 两份副本各自计数与
         登记 → 每售一只各 +1/+1（共 2 份）
      6. **已知边界精度缺口**（已上报主线，见模块 docstring "引擎缺口"
         #1）: 计数闭包自 `on_bind` 起算 → **获得当回合、在购买本饰品
         之前**售出的随从不可见（引擎无历史查询点; Windfall Portrait
         `BG32_MagicItem_832` 备案同一缺口）。该窗口之外（此后的每个
         回合）语义精确。

    Test: test_batch_trinkets24.py — 真实 `sell_minion` 后馆内全部
      随从 +1/+1（正对照: 无饰品不变）/ 连售 2 只 → +2/+2; 此后
      `add_tavern_entity` 入馆的新随从立即 +2/+2 / `start_of_turn` 后
      仍在馆的实体失去全部已授 buff、计数归零（再售 1 只只 +1/+1）/
      已买入的随从跨 `start_of_turn` 保留 buff / 对手售出不计入且
      对手酒馆不变 / 真实 `end_recruit_phase`（冻结保留）后馆内旧实体
      已回收 / 池守恒

    Params: atk=1 health=1（文本字面量 "+1/+1"; CardDef 无模板参数）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        # 计数取**引擎历史**（`MINIONS_SOLD_THIS_TURN`，`sell_minion` 累加、
        # 每回合清零）——本饰品获得**之前**当回合售出的随从同样计入
        # （"for each minion you've sold this turn"; 2026-09-02 对抗审查
        # 证伪: 旧实现从 0 起算 → 先卖后绑少授）
        source._pie_sold = h.get(GameTag.MINIONS_SOLD_THIS_TURN, 0)
        source._pie_buffs = []          # [(实体, buff)] 回合回收用
        source._pie_stamped = {}        # uuid -> 已授予份数

        def _grant(e, stacks):
            if stacks <= 0:
                return
            for _ in range(stacks):
                b = entity.Buff(atk=_PIE_ATK, health=_PIE_HEALTH,
                                source_id=source.card_id)
                e.add_buff(b)
                source._pie_buffs.append((e, b))
            source._pie_stamped[e.uuid] = \
                source._pie_stamped.get(e.uuid, 0) + stacks

        def _top_up(g):
            for e in list(h.tavern):
                if not isinstance(e, Minion) or e.dead:
                    continue
                _grant(e, source._pie_sold
                       - source._pie_stamped.get(e.uuid, 0))

        def on_sold(g, minion=None, **kw):
            if minion is None or minion.controller is not h:
                return
            source._pie_sold += 1
            _top_up(g)

        def on_entry(g, hero=None, entity=None, **kw):
            if hero is not h or not isinstance(entity, Minion):
                return
            if entity.dead:
                return
            _grant(entity, source._pie_sold)

        game.events.register(Listener(event=MINION_SOLD, owner=source,
                                      callback=on_sold))
        game.events.register(Listener(event="tavern_entity_added",
                                      owner=source, callback=on_entry))
        # 绑定即按已有计数补齐（覆盖"获得饰品前当回合已售出"的历史）
        _top_up(game)
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        """下一招募阶段开始: 回收仍留在酒馆中的已授 buff 并清零计数。"""
        h = source.controller
        if h is None:
            return None
        for e, b in list(getattr(source, "_pie_buffs", [])):
            if e in h.tavern:
                e.remove_buff(b)     # 生命超上限自动 clamp
        source._pie_buffs = []
        source._pie_stamped = {}
        source._pie_sold = 0
        return None


# ══════════════ DEFERRED（不注册 REGISTRY） ══════════════


class RedeemerPortraitScript:
    """
    Natural language: [x]Get a Nalaa the Redeemer. Your Nalaa the
    Redeemers give an extra +{0}/+{1}.

    Status: DEFERRED — requires 载荷 BG28_551 本体脚本 + 家族级加成通道

    Dependency:
      1. 授予物 `BG28_551` Nalaa the Redeemer **未注册**（REGISTRY 无此
         id）——"Whenever you cast a Tavern spell, give a friendly
         minion of each type +4/+3" 无实现。载荷未就绪时宿主一并
         DEFERRED（SOP §12 item 14）。
      2. "give an extra +{0}/+{1}" 需要**改写另一张卡脚本行为**的
         hero 级通道（数值 num(0)=num(1)=4 已由本饰品 CardDef 提供，
         但读取方必须是 Nalaa 脚本; 且不得影响对手的 Nalaa）。
      3. Implementation path: (a) 迁 `BG28_551`（"of each type" 用
         `_ALL_BG_RACES` + `rng.choice` 先例）; (b) 其脚本读 hero 级
         `_nalaa_extra_atk/_nalaa_extra_health`（引擎侧需有可达读取点
         以满足 W3）; (c) 本饰品 on_bind 递增该加成 + 数据链交付。

    Params: {0}=num(0)=4 {1}=num(1)=4（BG30_MagicItem_944）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class EnforcerPortraitScript:
    """
    Natural language: [x]Get a Lightfang Enforcer. Your Lightfang
    Enforcers have all minion types.

    Status: DEFERRED — requires 多值种族身份（`RACES`）+ 载荷 `BGS_009`

    Dependency:
      1. `GameTag.RACE` 是**单值** tag; `Race.ALL` 的语义是"匹配一切
         种族查询"（Amalgam **天生**全类型），用它改写一个本来有确定
         种族的随从属近似实现（SOP §6b 禁止）。同缺口已由
         batch_trinkets8 / 11 / 13 / 14 与 ENGINE_BACKLOG §A1 备案。
      2. 载荷 `BGS_009` Lightfang Enforcer **未注册**（EoT "give a
         friendly minion of each type +4/+4" 无实现; 金色
         `TB_BaconUps_082` 同样缺失）。
      3. Implementation path: `RACES` 集合/位掩码 tag + 全部 race 读取
         点改造后，为本人 Lightfang Enforcer 实例改写种族身份（含
         未来副本的入板钩子）+ 迁 `BGS_009`。

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class BalladistPortraitScript:
    """
    Natural language: [x]Get a Lovesick Balladist. At the start of each
    turn, get another. Your Lovesick __Balladists also give Attack.

    Status: ✅ **已迁出 → batch_trinkets31**（2026-09-19，owner 权威序: wiki 页无 Notes → 卡面天然语言）; 原阻塞 — requires "also give Attack" 增量权威 + 载荷加成
            读取通道

    Dependency:
      1. `BG26_814` XML 只有 `TAG_SCRIPT_DATA_NUM_2=1`（Health 基值）;
         `{0}`（Attack）在 base（num(0)=None）与 golden（num(0)=None）
         两个 CardDef 均缺失，本饰品 CardDef 亦无任何模板参数。
         wiki 卡页（Balladist Portrait / Lovesick Balladist）无 Notes;
         官方 32.2.3 / 34.6 / 35.x 补丁说明无该数值; Bug 报告帖
         us.forums 136525 只确认"Rylak 触发时同时给 Attack 与 Health"，
         未给增量。候选读法 (A) Attack=Health 增量 / (B) 固定 +1 /
         (C) 隐藏常量——三者均无证据（SOP §6b 第 4 步）。
      2. `BG26_814` 脚本给 `Buff(atk=0, health=...)` 且不读任何加成
         通道。
      3. Implementation path: 权威落地后 (a) 交付 + SoT "get another"
         走 `grant_card_copy_to_hand`（池随从占池）; (b) `BG26_814`
         脚本读 hero 级标记（本饰品 on_bind 写入）并增补同额 Attack。

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class YoggTasticPastryScript:
    """
    Natural language: Spin the Wheel of Yogg-Saron. At the start of each
    turn, spin it again.

    Status: DEFERRED — requires Wheel of Yogg-Saron 子系统 + 结果表数据

    Dependency: 全库无 Wheel 实现，数据中亦无 Wheel token/结果表
      （`grep -i wheel hsrl2/` 只命中无关卡名; 数据侧只有 Dalaran
      Cheese Wheel / Water Wheel 等同名无关卡）。同缺口已由
      batch_quest_rewards3（BG24_Reward_135）与 batch_anomalies3
      （BG27_Anomaly_503）备案。
      Implementation path: 引擎实现轮盘奖池（每个结果的 card_id/数值需
      数据权威）+ `game.spin_wheel(hero)` 原语 → 本卡 on_bind /
      start_of_turn 各调用一次。

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class DrakkariPortraitScript:
    """
    Natural language: [x]Get a Drakkari Enchanter. Your Drakkari
    Enchanters are both Mechs and Elementals.

    Status: DEFERRED — requires 多值/双种族身份原语（`RACES`）

    Dependency:
      1. `GameTag.RACE` 单值; 本卡要求**两个具体种族**（MECH +
         ELEMENTAL）——`Race.ALL` 会把 Beast/Dragon/… 一并匹配 = 近似
         （ENGINE_BACKLOG §A1）。
      2. "Get a Drakkari Enchanter" 半场已可交付（载荷
         `BG26_ICC_901` 已注册、池随从占池），但半实现 = 第三态。
      3. Implementation path: `RACES` 集合 tag（或位掩码）+ 全部 race
         读取点统一改造后，在 on_bind 为本人 Drakkari Enchanter 实例
         追加 MECH/ELEMENTAL。

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class BristlebachPortraitScript:
    """
    Natural language: [x]Get a Bristlebach. Your Bristlebachs play
    <b>Blood Gems</b> on all friendly minions.

    Status: 已迁出 → batch_trinkets34（2026-09-13，RULES §7.4.16 家族行为开关通道 `hero.family_flags`）; 原阻塞: requires 载荷 BG26_157 本体脚本（SOP §12 item 14）

    Dependency:
      1. 关联卡 `BG26_157` Bristlebach **未注册**（REGISTRY 无此 id），
         本体 "Avenge (2): This plays 2 Blood Gems on all your
         Quilboar" 无实现 → 授予的 Bristlebach 永不触发，本饰品
         "把目标范围改为全体友方"的改写对象不存在。
      2. RULES §7.4.6 例外条款（本卡效果**依赖**被授予卡的行为）→
         整卡维持 DEFERRED。
      3. Implementation path: (a) 先迁 `BG26_157`（`avenge_threshold=2`
         + `PlayBloodGems`; 金色 `BG26_157_G` 独立定义）;
         (b) 该脚本读取 hero 级 target-scope 标记（本饰品 on_bind
         写入 + 数据链交付）并据此选目标集合。

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class CzarinaPortraitScript:
    """
    Natural language: Get a Charging Czarina. Your Charging Czarinas
    also give Health.

    Status: ✅ **已迁出 → batch_trinkets31**（2026-09-19，owner 权威序: wiki 页无 Notes → 卡面天然语言）; 原阻塞 — requires Health 增量权威 + 载荷加成读取通道

    Dependency:
      1. "also give Health" 的**数值无权威**: `BG28_741` XML 只有
         `TAG_SCRIPT_DATA_NUM_1=4`（Attack）; Health 增量在
         base / golden / 本饰品三个 CardDef 均无字段; wiki 卡页
         （Czarina Portrait / Charging Czarina）无 Notes。
      2. `BG28_741` `ChargingCzarinaScript` 在 `tavern_spell_cast` 时对
         带圣盾随从各 `Buff(atk=num(0))`，只给 Attack、不读任何加成
         通道。在饰品侧另注册同事件监听 = **归属错误**（Czarina 被
         出售后仍生效）→ 近似，SOP §6b 禁止。
      3. Implementation path: (a) 补 Health 增量的数据/官方权威;
         (b) `BG28_741` 脚本读 hero 级 `_czarina_bonus_health`（引擎/
         该脚本侧需有可达读取点）并在 Buff 时一并给 Health;
         (c) 本饰品 on_bind 写入标记 + 数据链交付。

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class PutricideStickerScript:
    """
    Natural language: [x]Craft a custom Undead. At the start of every 2
    turns, repeat this. <i>({0} |4(turn, turns) left!)</i>

    Status: DEFERRED — requires "Craft a custom Undead" 合成子系统

    Dependency:
      1. "Craft a custom Undead" 是 Putricide 的多步部件合成链（种族 +
         关键词 + 属性选择 → 产出 `BG25_HERO_100pt` token）; 全仓无
         `craft` 实现，`BG25_HERO_100p` Build-An-Undead 英雄技能亦因此
         DEFERRED（batch_hero_remaining / batch_hero_remaining2 台账）。
      2. 数值 {0}=num(0)=2（"every 2 turns"）已就绪。
      3. Implementation path: 建立合成选择链协议（多步 PendingChoice +
         部件卡片池 + 参数落点）后，本卡 on_bind / 每 num(0) 回合
         start_of_turn 各触发一次。

    Params: {0}=num(0)=2（BG32_MagicItem_300）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class SplinterOfAurumScript:
    """
    Natural language: [x]When you have {1} Gold, get a random Golden
    Tier 5 minion. <i>(Once per game.)</i>

    Status: DEFERRED — requires 金币增加观察点 `gold_gained`

    Dependency:
      1. 引擎无金币**增加**事件: `events.py` 只有 `gold_spent`（支出）;
         收入路径（`_begin_recruit_for` 基础收入 / `sell_minion` 的
         `hero.gold +=` / `GainGold` action）**均不广播**
         （`grep -rn "gold_gained" hsrl2/` 只命中他批 docstring）。
         回合收入在饰品 `start_of_turn` **之前**结算，故 start_of_turn
         检查只覆盖回合收入、漏掉回合内收入（出售 / 海盗 / 法术给金）
         → 近似，SOP §6b 禁止。
      2. 交付侧已就绪: 随机金色 T5 + `GILDED_NOT_TRIPLED` 池配平协议;
         数值 {1}=num(1)=15。
      3. Implementation path: 引擎在金币增加点 fire
         `gold_gained(hero=, amount=)` → 本卡监听并判
         `hero.gold >= num(1)`（once per game 记在 source 实体）。

    Params: {1}=num(1)=15（BG32_MagicItem_350）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class GuidingCandleScript:
    """
    Natural language: [x]Your first two <b>Refreshes</b> each turn
    contain only Tier 6 cards. <i>({0} left!)</i>

    Status: DEFERRED — requires 精确档位刷新过滤
             `hero._tavern_offer_tier_exact`

    Dependency:
      1. `refresh_tavern` 只有 `hero._tavern_offer_tier_only`（= 与本人
         酒馆等级同档，Elven Elite）与 `_tavern_min_tier` 下限，无
         "指定第 N 档"的精确过滤（`grep -rn
         "_tavern_offer_tier_exact" hsrl2/` 只命中他批 docstring）。
         T9 购买时本人等级通常 < 6，`max_tier = hero.tavern_tier` 使
         `min_tier=6` 无法表达。
      2. 还需"每回合前 num(0)=2 次刷新"的计数与**玩家主动**刷新判定
         （`auto=True` 排除——Frigid Blossom "you Refresh" 口径）。
      3. Implementation path: 引擎增 `hero._tavern_offer_tier_exact = N`
         读取点（`refresh_tavern` 内 `min_tier = max_tier = N`）+
         每回合计数。

    Params: {0}=num(0)=2（BG32_MagicItem_366）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class TarecgosaStickerScript:
    """
    Natural language: [x]Your left and right-most Dragons permanently
    keep <b><b>Bonus Keyword</b>s</b> and stats gained in combat.

    Status: DEFERRED — requires Bonus Keyword 定义域 + 位置/种族 PERSIST
             光环

    Dependency:
      1. "Bonus Keyword" 定义域无任何数据字段（CardDefs 无 tag、文本无
         枚举; RULES §9.6 2026-09-02 裁定），且需"逐实体记录被授予的
         bonus 关键词"机制; 同族 = Finley's Helmet 891 / Vibrant
         Bubble 892 / Consuming Claw。
      2. 引擎 PERSIST 是**单实体全量** tag（`PERSIST_COMBAT_CHANGES`，
         Tarecgosa / Persistent Poet），无"按位置（最左/最右）+ 种族
         持续授予"的光环原语; Poet 通道只覆盖"相邻龙"。
      3. Implementation path: RULES §9.6 + ENGINE_BACKLOG §B9。

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class YuLonStickerScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Make your highest-Tier
    Dragon Golden.

    Status: DEFERRED — requires 战斗→招募的 Transform 持久化

    Dependency:
      1. `run_combat` 的 finally 用 `hero.board = list(board_before[
         hero])` 整体复原; SoC 期间 `Transform` 出的金色实体不在战前
         列表中，被丢弃（官方预期 = 下一招募阶段**仍为金色**:
         Blizzard 论坛 bug 报告 "Persistent Poet does not keep Dragons
         golden after combat" 多玩家确认）。`Transform` 新增的
         `on_transform` 钩子只解决被动重接线（RULES §6.21），不解决
         快照身份保留。
      2. 选取/数值侧均已就绪: 本人棋盘存活、`race ∈ (DRAGON, ALL)`、
         非金色、`golden_version` 存在的最高 `tech_level`（并列取最左
         ——R508 裁定）。
      3. Implementation path: `GameTag.PERSIST_TRANSFORM` 白名单 +
         restore 阶段对"战前实体已被 Transform"的情形保留新实体
         （含 GOLDEN / TRIPLE_BASE_CARD_ID / `GILDED_NOT_TRIPLED`）。
         脚本侧替代方案（COMBAT_END 二次金色化）属近似，**不采用**。

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        return None


class MacawPortraitScript:
    """
    Natural language: Get a Monstrous Macaw. Your Monstrous Macaws also
    trigger your left-most <b>Battlecry</b>.

    Status: 已迁出 → batch_trinkets36（2026-09-13，RULES §7.4.17 条件化
    战吼第二消费者）; 原阻塞: requires 载荷 BGS_078 本体脚本 + hero 级
    标记

    Dependency:
      1. 关联卡 `BGS_078` Monstrous Macaw（+ 金色 `TB_BaconUps_135`）
         **已注册**（`batch_payload_minions`，本体 Rally "Trigger your
         left-most Deathrattle (except this minion's)" 就绪）——本条
         "未注册"记载已过期; 追加最左战吼的触发载体已存在。
      2. 载荷 `MonstrousMacawScript.rally` 读
         `FLAG_MACAW_EXTRA_BATTLECRY`（RULES §7.4.17 条件化战吼）追加
         最左**带战吼**随从的 `TriggerBattlecry`。
      3. Implementation path: 见 batch_trinkets36 的
         `MacawPortraitScript`（2026-09-13 已注册）。

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class SelflessPortraitScript:
    """
    Natural language: [x]Get a Selfless Hero. Your Selfless Heroes also
    trigger on <b>Battlecry</b>.

    Status: 已迁出 → batch_trinkets35（2026-09-13，RULES §7.4.17
    条件化战吼协议）; 原阻塞: requires 载荷 BG_OG_221 本体脚本 + hero
    级标记

    Dependency:
      1. 关联卡 `BG_OG_221` Selfless Hero（+ 金色 `TB_BaconUps_014`）
         **已注册**（`batch_payload_minions`，亡语 "Give a random
         friendly minion Divine Shield" 就绪）——本条"未注册"记载已
         过期; "also trigger on Battlecry" 需把该亡语接到战吼触发点。
      2. 单独在饰品侧重放该亡语 = 与"由 Selfless Hero 给出"的归属
         不符，且与其**未实现的死亡路径**不一致（半实现 = 第三态，
         SOP §6b 禁止）。
      3. Implementation path: 先迁 `BG_OG_221`（亡语 + 金色），再加
         共享 hero 级标记。

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class BattlecruiserPortraitScript:
    """
    Natural language: [x]Get an 12/12 Battlecruiser. Whenever the Tavern
    is <b>Refreshed</b>, add a Battlecruiser Upgrade to it.

    Status: DEFERRED — requires Battlecruiser 本体 + Upgrade 附着子系统

    Dependency:
      1. 载荷 `BG31_HERO_801pt` Battlecruiser **未注册**（白板 2/2
         token），且 "Get an **12/12** Battlecruiser" 需要属性覆盖
         （`BASE_ATK/BASE_HEALTH/HEALTH` = 12/12，Beetle 先例）。
      2. "Battlecruiser Upgrade" 子系统未实现: 10 张
         `BG31_HERO_801pta..j`（card_type=42）数据存在，但 Jim Raynor
         `BG31_HERO_801p` "Lift Off" 整条技能链 DEFERRED
         （batch_hero_combat3 `JimRaynorScript` 台账: 需 Upgrade 商店
         子系统）。
      3. "add ... to it" 是**已有卡追加部件**协议，
         `inject_tavern_minion`（新增展示位）与 `add_tavern_entity`
         （入馆）均无法表达部件附着。
      4. Implementation path: 先实现 Jim Raynor 的 Upgrade 商店 +
         部件附着/累计协议，再评估本卡（`tavern_refresh` 监听 → 附着）。

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


# ══════════════ 注册 ══════════════


def register() -> list[str]:
    """注册本批 5 张 CORRECT 饰品（15 张 DEFERRED 见模块 docstring）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        (KELTHUZAD_PORTRAIT, KelThuzadPortraitScript),
        (MAW_CASTER_PORTRAIT, MawCasterPortraitScript),
        (ECLECTIC_SHRINE, EclecticShrineScript),
        (FOUNTAIN_PEN, FountainPenScript),
        (DARNASSUS_PIE, DarnassusPieScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
