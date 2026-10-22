# 引擎缺口待办（2026-09-02 第十一轮汇总）

> 来源: 本轮 7 份对抗验证报告 + 9 个迁移批次的 DEFERRED 台账（每张卡在各自
> `batch_*.py` docstring 内有逐条依赖与实现路径）。本文件按**阻塞卡数/影响面**
> 排序，供主线排期；卡 id 均可在 `docs/agents/TRINKET_LEDGER.md` 查到文本。

## A. 阻塞多张卡的原语（优先）

| # | 缺口 | 阻塞卡 | 实现路径要点 |
|---|------|--------|--------------|
| 1 | ✅ **已完成（2026-09-21，`batch_family_races`）** **多值/全种族身份** `RACES`（集合）—— `GameTag.RACES` + `Minion.races` / `has_race` + owner 家族类型改写（`Game.add_family_races` / `family_races` / `effective_races`）; 权威见「C 组」**2026-09-21 闭环**节。以下为当时（2026-09-19）的阻塞记录 | `BG32_MagicItem_179` Drakkari Portrait / `BG30_MagicItem_418` Bronzebeard Portrait / `BG30_MagicItem_825` Smuggler Portrait（**单类型**，不计入本集合模型缺口——见「C 组」; 其阻塞 = 家族单值类型改写读取点 + 载荷 `BG21_013` 效果缺 `stats_gained` 观察点） / `BG30_MagicItem_971` Enforcer Portrait | `GameTag.RACE` 目前单值，`Race.ALL` 语义是"匹配一切"而非"同时是两个种族"。需 `RACES` 集合 tag + 所有 `race` 读取点改造（`Minion.race` → 集合视图 + 单值兼容读取）。**规模盘点（2026-09-19 实测）**: `.race` 读取点 = 引擎 **39 处 / 7 文件**（`game` 14 / `actions/discover` 8 / `actions/racefx` 5 / `pools` 4 / `darkgifts` 4 / `actions/tavern_buff` 3 / `actions/bloodgem` 1）+ 脚本 **247 处 / 62 文件** = **286 处 / 69 文件**——须先分类"实例匹配点"（改集合语义）与"CardDef 静态读取"（保持单值），建议拆 2–3 轮: (1) 引擎 `RACES` tag + `Minion.races` 视图 + 引擎侧匹配点; (2) 脚本侧匹配点按批次推进; (3) 注册四张 Portrait。**前置阻塞（本轮新增）**: 成员的**集合**可由文本+数据决定（下节 [AUTHORITY FOUND]），但**每个消费者如何解释多值身份无权威**（计数/选取/关联/入池/光环作用域，下节 [NO AUTHORITY FOUND] N1–N7），且仓内三个计数口径互相冲突 → 不得动全仓读取点。 |
| 2 | ~~**`grant_combat_deathrattle` 公开化**~~ **已完成（2026-09-02）** | `BG30_MagicItem_917` Rusty Trident / `BG30_MagicItem_952` Jarred Frostling 已迁移（batch_trinkets23） | `Game.grant_combat_deathrattle(hero, minion, fn)` 已落地（链式顺序 + Action 返回值合并 + `run_combat` 统一恢复 override）；`batch_hero_combat3` / `batch_trinkets11` 已迁移，`batch_trinkets11._restore_granted_deathrattles` 仅作兼容保留（新脚本勿用）。 |
| 3 | ✅ **已完成（2026-09-02，`Game.cast_spell_effect`，RULES §7.4.7b）** | `BG32_MagicItem_286` Lavish Cape 已注册（batch_trinkets21）; `BG36_508` Cagey Conjurer 可迁移 | 效果施法统一入口：建法术实体（不入手牌）→ `needs_target` 时随机取目标或落空 → 广播 `spell_resolving`（每次施放）、**不**计 `TAVERN_SPELLS_CAST_*` / 不广播 `card_played`。**待裁定**: 官方 bugfix 暗示效果施放应计入 "After you cast a Tavern spell"（Lavish Cape × Fire-forged Evoker）——若采用，需在 `cast_spell_effect` 补计数/广播。 |
| 4 | ✅ **已完成（2026-09-02，提交 481617f）** `game.destroy_minion` + `minion_destroyed(hero=, minion=, source=, in_combat=)`（13 处脚本 Destroy 路径已收口，RULES §7.4.11） | `BG30_MagicItem_204` Kel'Thuzad Portrait / `BG30_MagicItem_205` Maw Caster Portrait 现可迁移 | 消费方按 `in_combat` 过滤 "outside combat"。 |
| 5 | ✅ **已完成（2026-09-02）** | `BG32_MagicItem_416` War Drum 已注册（batch_trinkets21）; 已闭环（提交 37eee76：`_has_battlecry_hook` 守卫） | `bc_first`（每回合前 N 个战吼）+ `bc_first_times`（每次额外触发几次）= 36.2.2 文本 "One Battlecry each turn triggers **two** extra times"（num(0)=1 / num(1)=2）。 |
| 6 | **金币增加观察点 `gold_gained`** | `BG32_MagicItem_350` Splinter of Aurum | 目前只有 `gold_spent`; 收入路径（回合收入/售卖/卡效果）不广播。另需 hero 级"本回合已售随从数"（`BG32_MagicItem_832`）与"本回合已触发战吼数"（`BG32_MagicItem_890`）读取点。 |
| 6b | ✅ **已完成（2026-09-02；本行 2026-09-13/18 复核为陈旧）** `TAG_SCRIPT_DATA_NUM_5` 已导出 → `CardDef.script_data_num_5` / `num(4)`（`hsrl2/defs.py::num` docstring 记载生成器改动） | 431t / 920 / 923 的**数值通道已通**（923 实测 num(0..4)=**1/1/2/None/2**——`{4}`=num(4)=2，2026-09-18 重测订正旧记 "1/1/2/2"） | 三张卡的**残余**阻塞均**已关闭**: 923 的战斗内"永久"口径由 `Buff(persist=True)` 按来源跨战斗持久化实现（batch_trinkets31，2026-09-18，RULES §3.5 例外 4）; 431t/920 为升级变体（非商店池） |
| 7 | **`hero._tavern_offer_tier_exact`（精确档位展示位）** | `BG30_MagicItem_366` Guiding Candle / `BG30_MagicItem_423` Innkeeper's Stein | `TAVERN_OFFER_MOD` 只加通用位、抽取上界恒为 `hero.tavern_tier`。需"额外 N 个位从恰好 tier+1 抽取"的协议。 |
| 8 | ✅ **已完成（2026-09-02，提交 9828153）** `_magnetic_stack` 已纳入 `run_combat` 快照/恢复（战斗内吸附不跨战斗） | `BG36_MagicItem_841` Assembler Portrait 仍余一项: "an Auto Assembler"（`BG32_172`）的池占返/副本来源语义无权威 | 剩余裁定: 生成 copy 语义 vs 池占 1 份。 |
| 9 | **动态 `TAVERN_SPELL_EXTRA` 提供者**（当前只读静态 hero tag，棋盘类型数变化无读取点）+ **[NO AUTHORITY FOUND] ×2**（2026-09-18 查证） | `BG36_MagicItem_373` Multilayered Shield | 路径: `hero.tavern_spell_extra_providers` 读取时求值（生命周期同 tier/race aura）。**[NO AUTHORITY FOUND: 增量口径]** 印面 `num(0)/num(1)`=1/2 与“每个不同随从类型”的步进量关系无直接权威——仓内 “Improved by each X!” 家族按**加法 +1/实例**裁定（`batch_trinkets20.GoldMalletScript` / `batch_unfreeze.HooktuskScript` / `batch_battlecry.LovesickBalladistScript`，依 34.6.0 补丁历史），但那些是“每金色随从/每金币 +1”; 本卡步进是否同为 `+1/+2`（而非 `+1/+1`）只能类比，无直接权威。**[NO AUTHORITY FOUND: 类型计数]** `.race` 为单值枚举、`Race.ALL` 语义是“匹配一切”（`hsrl2/tags.py:41`），本地数据 `card_race` **全部单值**（4 张 `Race.ALL`）→ Amalgam 计 1 类还是补满全部类型、双种族随从如何计 2 类，均无权威且受 C 组（多值种族）缺口阻塞。已查信源: 官方 S14 全表（163710, `Multilayered Shield | 4 | Your Tavern spells give an extra +1/+2. (Improved by each different friendly minion type!)`——cost 4，**本地数据 `cost=2`，按 SOP 以本地数据为准**）、wiki.gg 卡页（无 Notes）。 |
| 10 | ✅ **已完成（2026-09-02，提交 44a9af0 + efe0370）** `racefx.elemental_give_bonus` = 唯一消费点; 消费方**全族**接线（含 `Race.ALL` 三张: Motley Phalanx `BG27_080` / The Last One Standing `BG34_320` / One-Amalgam Tour Group `BG30_102`——2026-09-02 对抗审查 F1 补齐） | `BG36_MagicItem_380` / `BG32_MagicItem_802` 完整 | 裁定: 自增益（"gain"）不算给予（Living Prison / Molten Rock / Unbound Tempest / Meteorite Crasher 不吃加成）; Nomi 族无种族亦不吃。RULES §7.4.6c。 |
| 11 | ✅ **已完成（2026-09-18）** 逐附魔**按来源**跨战斗持久化通道: `Buff(persist=True, source_id=...)`（`hsrl2/entity.py`）+ `run_combat` 恢复阶段"例外 4"按 `persist` 重放（`add_buff`）+ 来源规则读取点 `Game.add_persist_source` / `minion_persist_source` / `persist_source_id`（`hero.persist_sources`，source 离场即失效、`TRIPLE_BASE_CARD_ID` 家族归一） | `BG36_MagicItem_362` Cyclist Portrait 已注册（batch_trinkets31）; `BG35_MagicItem_923` Bewitched Ribbon 同批注册 | 与 `PERSIST_COMBAT_CHANGES`（单实体**全量**）正交：只重放该批附魔，同一实体其它战内变化照常回滚（`dmg_deltas` 重放已跳过 persist 附魔，避免双计）。RULES §3.5 例外 4; 测试 `hsrl2/tests/test_batch_trinkets31.py`（含 4 项突变探针）。 |
| 12 | ✅ **已完成（2026-09-02）** 引擎在 `_finish_play_spell` 维护 `hero._last_tavern_spell_id`（每次酒馆法术施放写入，绑定前施放亦可见） | `BG36_MagicItem_372` Sphere of Memory 已改读该字段 | 残余: `BG35_123` / `BG31_HERO_003p` 仍自维护监听（功能不受影响，可陆续迁移）。 |
| 13 | ✅ **已完成（2026-09-02，提交 31b312f）** `BG26_537` Flourishing Frostling 已迁移（`COUNTER_ELEMENTALS_PLAYED` + `elemental_played` 生产点 + batch_counters 动态属性钩子） | `BG30_MagicItem_952` Jarred Frostling 的召唤体现为动态成长体 | — |
| 14 | ✅ **已完成（2026-09-02）** `_finish_play_spell` 在施放时反查来源随从的永久化规则（生成时未标记的法术同样永久化） | `BG32_MagicItem_920` Thaumaturgist Portrait 完整 | RULES §7.4.7a 更新为「生成时标记 **或** 施放时反查」。 |
| 15 | ✅ **已完成（2026-09-13，提交 b5fa293）** 池**永久移除**原语 `MinionPool.purge(card_id)` / `is_purged`（RULES §2.3） | `BG31_Anomaly_117` Emergency Landing + 载荷技能 `BG31_Anomaly_117t` Eject! 已注册（batch_anomalies7） | 六路全拒（`available`/`candidates`/`acquire`/`ensure_available`/`release`/`release_minion_entity`）; 与现有实现路径一致（旧台账预写的 `remove_all` 即本轮 `purge`）。 |
| 17 | ✅ **已完成（2026-09-13）** 家族**行为开关**通道 `hero.family_flags` + `Game.add_family_flag` / `family_flag`（RULES §7.4.16） | `BG32_MagicItem_274` Bristlebach Portrait 已注册（batch_trinkets34） | 与 §7.4.15 分工: 本通道管**行为/目标集合**，giver_bonus 管**数值**。载荷消费点 = `BristlebachScript.avenge` 的 `FLAG_SCOPE_ALL_FRIENDLY`; 金色按基础卡 id 归一; source 离场即失效。 |
| 18b | ✅ **已完成（2026-09-13，对抗验证后硬化）** `has_battlecry` 增实体级 `_script_overrides` 通道 + 磁力附件的条件化开关（按附件卡 id），并加**行为级**金色口径测试（每次触发取基础值） | `TriggerBattlecry` 门禁曾会静默挡掉「仅由 override 提供战吼」的随从（潜在缺口，唯一生产者 `batch_unfreeze` 当前安全） | 见 A 表 18 行。 |
| 18 | ✅ **已完成（2026-09-13）** **条件化战吼**协议 `battlecry_flag` + `Game.has_battlecry` / `granted_battlecry`（RULES §7.4.17） | `BG32_MagicItem_804` Selfless Portrait 已注册（batch_trinkets35） | 门禁**单一事实源**: 打出配额 `bc_first`、`COUNTER_BATTLECRIES`/`battlecry_trigger` 广播、`TriggerBattlecry`、`batch_trinkets8._has_battlecry_hook`、`minions.py` Activate 候选、`batch_hero_passives` 买 N 计数全部改走 `has_battlecry`。权威: 32.4 补丁说明（it has a Battlecry from Selfless Portrait）。金色口径: 每次触发取基础值（`battlecry_targets` 不随金色覆盖）、引擎触发 2 次。 |
| 16 | ✅ **已完成（2026-09-13，提交 b5fa293）** 挂起路径的次数配额复查（`_finish_hero_power` 结算点复查 `uses_per_turn`/`uses_per_game`） | 影响**全部**定向英雄技能（对抗验证实测 Malygos `TB_BaconShop_HP_052` 同缺陷） | 原缺陷: N 个挂起目标结算把 "Twice per turn" 叠加成 N 次; 修复后超额作废（不扣费/不计数/无效果），RULES §9.5 已记载 + `TestHeroPowerPendingQuota` 回归。 |

## B. 子系统级缺口（单卡或影响面大）

| # | 缺口 | 阻塞卡 | 备注 |
|---|------|--------|------|
| 7b | **Secrets 子系统** | `BG35_MagicItem_820` Safety Patch | `TB_Bacon_Secrets_12` 无脚本; 需 `hero.secrets` + 致命伤害预防钩子。 |
| 7c | **Minor Timewarp 成员定义域** | `BG35_MagicItem_823` Timeworn Candelabra（+ `BG34_Giant_605`） | XML 只有 `BACON_TIMEWARPED` 布尔标记且生成器未导出。 |
| 7d | ~~**战斗内施法事件/结算入口**~~ **已关闭（2026-09-17）** | ~~`BG35_MagicItem_922` Tide Raiser Portrait~~ | 原陈述有误: `cast_spell_effect`（`game.py` L1488/L1493）**无条件**广播 `spell_resolving`/`spell_resolved`（RULES §7.4.7b/§7.4.12），战斗上下文经 `game.in_combat` 判定（`StalwartKodoScript` 既有口径）；载荷 `BG34_920` 亦已注册 → 922 由 `batch_trinkets38` 注册。`BG35_MagicItem_923` 的"战斗内 permanent"于 2026-09-18 由 §A11 通道解决（batch_trinkets31 注册）。 |
| 7e | **`minion_triggered(hook=, source=, value=)` 观察点** | `BG35_MagicItem_156` Flaming Portrait / `BG35_MagicItem_433` Vinespeaker Portrait（+ 载荷未迁） | 引擎无"某随从钩子已触发（含数值增量）"广播; `minion_consumed` 无法区分增量来源。 |
| 7f | **"give stats" 法术效果类别定义域** | `BG35_MagicItem_921` Cowrie Necklace | 数据层无标记（`TAVERN_SPELL_COST_MOD` 是无条件 hero 级）。 |
| 8 | **饰品"提供规则"子系统**（RULES §7.4.2 未实现部分） | 全部 offer（非单卡） | 最常见类型保证 / 非本类型 ≤1 且 -2 费 / Souvenir Stand·Trip Vouchers·Ornate Clock 合计 ≤1 / 条件与身份门禁清单。已有官方权威文本（RULES §7.4.2 链接）。 |
| 9 | ✅ **已完成（2026-09-02）** `BONUS_KEYWORD_TAGS`(6 集) + `grant_bonus_keyword` + `BONUS_KEYWORDS` 记录 + `PERSIST_BONUS_ONLY` | `BG32_MagicItem_417` Tarecgosa Sticker / `_891` Finley's Helmet / `_892` Vibrant Bubble | 定义域无数据字段 + 需「逐实体记录被授予的 bonus 关键词」。官方定义域已按 wiki 收为 **6 张**（DS/Reborn/Stealth/Taunt/Venomous/Windfury）——`BG36_MagicItem_801` Consuming Claw 已按该 6 集实现（batch_trinkets22 + 对抗审查订正）。 |
| 10 | **Craft（合成）选择链** | `BG30_MagicItem_300` Putricide Sticker | 全仓无实现。 |
| 11 | **Wheel of Yogg-Saron** | `BG30_MagicItem_994` Yogg-Tastic Pastry / `BG24_Reward_135` Yogg-tastic Tasties | 结果表数据与 `spin_wheel` 均缺。**2026-09-18 第四十九轮复核（更精确）**: wiki **无** Wheel 独立页（`titles=` 三候选 missing、`intitle:` ns 0 全 0 命中）; `BG24_Reward_135t` 在 wiki/hearthstonejson 都不存在; 6 结果 + 「Rod of Roasting 5% / 其它 19%」只记在 `Acolyte_of_Yogg-Saron` oldid=898529 与 `Yogg-Tastic_Pastry` oldid=921146，wiki 未声明 `BG24_Reward_135` 共用，且该表与 `Patch 31.2.0.212197`（dbf 80436 移出游戏）+ 现行 `t7`(93390)/`t8`(93391) 冲突 → 结果集与概率均无权威。 |
| 12 | **弃牌系统** `CARD_DISCARDED` + `game.discard_card` | `BG30_MagicItem_402` Conductor Portrait（及其载荷 `BG28_585`） | 目前全仓零弃牌机制。 |
| 13 | **本回合已售随从计数 tag** `MINIONS_SOLD_THIS_TURN`（hero 级，每回合清零） | `BG30_MagicItem_992` Darnassus Pie（**已注册**；精度缺口 = 获得当回合、购买饰品**之前**售出的随从不可见）/ `BG32_MagicItem_832` Windfall Portrait | 现实现用 `minion_sold` 全馆重算 + `tavern_entity_added` 继承，缺"绑定前已售数"的历史读取点。 |
| 14 | **战斗内"腾位"触发协议**（`when you have space`） | `BG30_MagicItem_822` Twin Sky Lanterns | `combat_summon_log` 只写不读; SOP §13 禁止无界 AFTER_ATTACK 补召。 |
| 15 | ✅ **已完成（2026-09-02）** `Game._script_for(def)`: 金色无独立脚本时回落**基础卡脚本**（数值仍按实体自身金色 CardDef 读取） | `BG30_MagicItem_821t2` Fishy Sticker 现可迁移（`TB_BaconUps_307` → `FishOfNZothScript` 实测）; Kaboom Bot 金色已由 batch_remaining2 直接注册（2026-09-16，`TB_BaconUps_028`），不经回落 | 回归测试 `test_golden_falls_back_to_base_script`。 |
| 16 | **效果施法的 cast 事件** | 全库系统性 | "效果施法"（Spellbook/Wrench 等）不广播 `card_played`/不计 `TAVERN_SPELLS_CAST_*`——官方是否触发 "whenever you cast a Tavern spell" 未定。 |
| 19 | **酒馆/数据驱动关键词过滤不感知条件化战吼**（RULES §7.4.17 例外） | `Game._free_buy_qualifiers_match`（Warcry Totem `BG36_MagicItem_202` 免费买战吼随从）/ `batch_unlock_final` Chillmere Mosaic 的刷新捕获 | **当前不可达**: Portrait 家族均非池卡（`BG_OG_221.is_pool_minion=False`），酒馆报价也不应吃「你的无私英雄」授予。若未来出现**池内**条件化战吼卡，需裁定这些过滤是否感知开关（2026-09-13 对抗验证 MINOR）。 |
| 18 | **战吼 `BATTLECRY` tag 数据缺口（14 张 = 7 组基础/金色）** | `BG31_320` Crater Miner / `BG36_330` Sly Infiltrator / `BG36_332` Snare Trapper / `BG36_341` Veteran Brigand / `BG32_237` Intrepid Botanist 等 | 脚本有 `battlecry` 钩子但 CardDef 无 `BATTLECRY` tag（文本派生关键词漏）；2026-09-13 起全部「是否有战吼」门禁走 `has_battlecry` 脚本通道 → 行为已正确，但数据面 tag 仍缺，**数据驱动路径**（酒馆 `keywords=` 过滤）看不到它们——若后续有「按关键词筛选」需求须补 tag。 |
| 17 | **载荷卡脚本未迁移** | 见各批"关联卡台账" | 多数按 RULES §7.4.6 不阻塞饰品 CORRECT; 但会让交付的卡功能残缺（如 `BG26_350` Bassgill / `BG34_Giant_035` Glowscale / `BG25_807` Mecha-Jaraxxus 本体 / `BG28_551` Nalaa / `BG34_Giant_314` Timewarped Poet 等）。**已迁出**: `BG30_104`/`BG30_104_G` Goose 次生载荷 Lucky Egg（batch_goose_lucky_egg，2026-09-17——`BG29_801` 已于 batch_remaining2 注册）; **`BG29_873`/`BG29_873_G`/`BG29_877`/`BG29_877_G` Felblood**（batch_payload_minions，2026-09-19——869 Felblood Portrait 行为层随之闭环）。 |

| 23 | ✅ **已完成（2026-09-14 第二十三轮）** "permanent Spellcraft" 的**第二类口径**（临时**关键词**） | `BG32_MagicItem_933` Weary Portrait（+ 载荷 `batch_payload_minions.ReinvigorationScript`） | 台账原记"双重阻塞（载荷未迁 + 永久化协议缺失）"**两条均已不成立**（载荷 2026-09-02 注册; 协议 `batch_trinkets23` 落地）。真缺口是**口径分歧**: 同族 `BG32_MagicItem_920` 的法术是 "…until next turn" 临时 **buff**（`add_permanent_spellcraft_rule` 通用通道在施放时翻转），而 Reinvigoration 的 +2/+2 本就永久、唯一临时项是 **Reborn 关键词**（`GainKeyword` + 独立 `TURN_START once` 监听）→ 通用通道对本卡空转（照抄 920 即为"简化实现"）。解法: `on_play` 读 `source.permanent_spellcraft`（生成期由 `spellcraft.generate_for_hero` 打标 / **施放期反查回写**——见 #26），命中则不注册 Reborn 过期监听。权威: 34.0.1 官方 hotfix（2025-11-03） "retains Reborn from Weary Mage's Reinvigoration Spellcraft"（`batch_econ_misc.LavaLurkerScript` 台账同引; wiki "permanent" = keep enchantment）。`BG23_009` Lava Lurker 仍 DEFERRED——它的拦截点在**施放时**（"the first Spellcraft spell played from hand on this each turn"），晚于生成期打标，用不上该通道。 |
| 29 | ✅ **已落地（2026-09-18 第四十九轮）** 任务族（Quest）实现 | `BG24_Quest_*` 15 张 + `BG27_Quest_800/801/802` + `BG28_Quest_500` = 19 张 | **本轮实测**: 19/19 注册（`hsrl2/scripts/batches/batch_quests.py`），64 项真实路径测试全绿。**权威（取代本行旧的"权威不足"结论）**: 项目所有者 2026-09-18 裁定权威序 = wiki 详细说明 > 卡面自然语言理解。目标值 = 各卡页 "baseline requirement" 当前值（逐卡 URL/oldid/引文见 `QUEST_DEFERRED_SPEC.md` §1），与 CardDefs `QUEST_PROGRESS_TOTAL`（535）逐张一致; 全族卡页**无 Notes**（`?action=raw` 核实）→ 全部判定口径走自然语言解读，逐条记档（`QUEST_DEFERRED_SPEC.md` §2/§3.1）。**实现**: 原语 `quest_defs`/`quest_offer_pool`/`quest_script`/`quest_target`/`advance_quest_progress`（唯一计数写入点）/`set_quest_progress`（阈值式只升不降）/`complete_quest`（唯一发奖入口）+ `Hero._quest_completed` 二次计分闸; `_offer_quests` 改为"先暂存奖励再 `on_bind`"（阈值式任务可能 on_bind 当场达标）+ 候选池门禁 = `quest_defs() ∩ REGISTRY`。数据链: 生成器新增导出 `quest`（tag 2466）与 `quest_progress_total`（tag 535）→ `CardDef.quest` / `CardDef.quest_progress_total`。**`stats_gained` 未引入**: 123 用 `buff_applied`+`temporary` 过滤，边界（`copy_buffs_to`/快照重放会一并计入）**显式记档**（`QUEST_DEFERRED_SPEC.md` §3.1 第 2 条）——§E 的触发域裁定仍开放，落地后本卡迁移。 |
| 39 | **验收行笔误（第 3 次）+ 提交规范** | 无卡阻塞 | 第四十六轮提交 `7f4e39e` 信息写 smoke seed 31415 "completed=150", 实际输出为 **`games=150 completed=149 incomplete=1 crashes=0`**（与 #34/#36 同类笔误, 三次均为"未完成 1 局属允许项"被误写成 completed=150）。**规范**: 提交信息中的 smoke 行必须**逐字引用**命令输出, 不得复述或改写；incomplete>0 时须注明其性质（50 回合未完成, 允许项）与是否 A/B 验证为既有现象。 |

| 38 | **persist 原语重复应用（已修）+ 两项表述待办** | 无卡阻塞 | 第四十三轮对抗验证: (1) **必须修的真实缺陷**——`run_combat` 例外 4 在恢复后重放 persist 附魔时未去重, 而战斗前快照本已含该附魔 → 每场战斗重复叠加（实测 923: 4/5→5/6; 362 招募期亡语: 4/4→6/5; 多场 4/5→6/7→8/9）。已按**对象身份**去重（`game.py` 例外 4: 快照 `buffs` 中已存在则跳过; 值相等判定不足——第二场战斗会新建同值附魔）, 并新增回归文件 `hsrl2/tests/test_persist_no_double_apply.py`（真实卡路, 2 项; 变异删除去重 → 2 failed ✓）。前一轮 5 组变异全杀但**缺该正向控制**（新测试都只在战斗内授予 persist, 命中不到快照路径）。(2) **923 权威叙述订正**: 决定性是卡面同一句中的 "…permanently"（zhCN/JA/KO 把括号渲染为**替换**语义）; 补丁史（35.2.2/35.6.2 只改括号数字、"permanently" 与基础 +1/+1 从未变）仅作**旁证**, 不应写成排除性证明——待同步脚本 docstring/RULES 措辞。(3) **RULES §3.5 增量块定位**: 应标注为"引擎实现注记"并把"例外 1 × 例外 4 归属规则无官方权威"的告示**就近**重复一次（现仅见于 §7.4.18 与提交信息）。经判定该增量**不构成文档洗白**（纯增量、且标注为记录实现现实）。(4) 362 家族/复制语义经判定**由卡面直接支持**（"Your Showy Cyclists' Deathrattles…" 是家族属性）, 原"复制语义无权威"的自述过度保守。 |

| 37 | **Blood Gem 效果打出的 spell 事件口径 —— [NO AUTHORITY FOUND]，维持现状（不改引擎）** | 跨卡引擎谓词（12 个 spell 事件监听点中 8 张受影响） | 第四十轮复核（2026-09-17）: 拟议「在 `PlayBloodGems` 广播 `spell_resolving/spell_resolved`」**无权威支撑**，且与本仓三条卡面正确性断言直接冲突 → **不修**，留待官方裁定。**已确立（[AUTHORITY FOUND: RULES §7.4.7b / §7.4.10:1064-1066 / §7.4.12 + 卡面）]**: (a) **手牌**打出的宝石 = cast: `play_spell`→`_finish_play_spell` 广播两事件（§7.4.12）+ `card_played`（§7.4.10 play 域），已是现状; (b) 效果「Cast X」(`cast_spell_effect`) = cast: 广播两事件、不广播 `card_played`（§7.4.7b）; (c) 「play a Blood Gem **from your hand**」文本的计数域是 `card_played`（play 域），**效果施法与非手牌路径不应计入**（§7.4.10 第二条）; (d) 卡面用词区分 cast/play: `BG32_MagicItem_808`「After you **cast** 4 spells, this **plays** a Blood Gem」、`BG36_341`「This **plays** {0} Blood Gems … ; or **cast** Blood Gem Barrage {1} times」。**未确立（[NO AUTHORITY FOUND]）**: (1) 官方是否把效果「plays N Blood Gems」计为「you cast a spell」（RULES / patch notes / wiki `Battlegrounds/Blood_Gem` oldid 904378 均无 Notes / 无 Blizzard 裁定）; (2) 若裁定为「算」，**哪些宝石施加点**算 cast——`PlayBloodGems`? 还是也包括 `BG34_689` Blood Gem Barrage 的**刷新时**施加（`batch_spells_final.py:545`）与 Surveyor 的附加宝石（`batch_trinkets13.py:701`）？三者时点不同，无统一「cast 时刻」。**变异实测（本轮实施后即刻回退）**: 在 `PlayBloodGems.do` 加两事件 → 3 条卡面正确性测试红: `test_batch_trinkets13::TestSurveyorPortrait::test_direct_play_blood_gems_gets_no_extra`（943 卡面 from your hand）、`test_batch_trinkets14::TestToughTuskSticker::test_direct_played_gem_does_not_grant_ds`（279 卡面 from your hand）、`test_batch_trinkets15::TestBloodboundEarrings::test_spellcraft_counts_but_direct_gems_do_not`（808 卡面 cast≠play）; 另 808 **自反馈死循环**: 己方 5 随从 + 阈值 4 时其自身宝石喂回自身计数 → `hsrl2.queue.CombatLoopError: queue exceeded 20000 actions`（无重入闸）。**受影响卡逐条**（12 个 spell 事件监听点）: 变且**变错** = `BG32_MagicItem_279` Tough Tusk Sticker / `BG30_MagicItem_943` Surveyor Portrait（卡面明写 from your hand）; 变且**自反馈** = `BG32_MagicItem_808` Bloodbound Earrings; 变、正确性未定 = `BG36_MagicItem_211` Lovely Locket / `BG32_MagicItem_922` Charming Panpipes / `BG32_MagicItem_930` Archaic Scroll / `BG36_MagicItem_371` Honeycomb Ring / `BG35_MagicItem_922` Tide Raiser Portrait; **不受影响**（脚本自带 card_id/tag 过滤）= `BG32_MagicItem_894` Blessing Portrait（Natural Blessing）/ `BG33_825` Proud Privateer（Bounty id）/ `BG35_MagicItem_925` Coral Spear（SPELLCRAFT）/ `BG23_009` Lava Lurker（SPELLCRAFT）。**事实订正**: 旧行「91 处 `PlayBloodGems` 调用点」——91 是 `PlayBloodGems` 的**出现次数**（28 个脚本文件），实际**调用点 36 处**（非测试）; 旧行「Glambot 先例已把血宝石计为施法」**不成立**——`GlambotScript` 监听的是 `card_played`（play 域，`batch_consume.py`），只覆盖**手牌**宝石，不证明效果宝石是 cast。另: 全仓**无任何生产脚本**监听 `blood_gem_played`（唯一 fire 在 `batch_spells_final.py:548`，仅注释/测试引用）→ 不存在「同时监听 blood_gem_played 与 spell 事件」的卡，双重计数风险表现为上述 spell 监听器的越权/自反馈。**未来裁定必须回答**: (1) 官方是否把效果 played 的宝石计为 cast？(2) 若算，哪些施加点算 cast？(3) `spell=` 载荷如何区分 hand/effect 路径，使 279/943 仍只看手牌、808 不自反馈？(4) 808 自反馈重入护栏归引擎还是脚本？ |

| 36 | **验收行更正（e5e8437）+ 待续** | 无卡阻塞 | 第三十八轮提交 `e5e8437` 信息中的 smoke 验收行写为 seed 55501 `completed=150`, 实际为 **`completed=149 incomplete=1 crashes=0`**（incomplete 属允许的 50 回合未完成档, 非回归; 与 #34 同类笔误, 不应复用）。另: 该轮 4 处"过期异变台账"订正与 Tide Raiser 注册已由独立对抗验证受理（结论见 #37 起后续记录）。 |

| 35 | **Lucky Egg/Goose Portrait 测试层收尾（已修 4 项, 残余 2 项）** | 无卡阻塞 | 第三十七轮对抗验证判定实现 CORRECT、803 DEFERRED 成立、台账诚实, 但测试层存在过claim与不敏感负对照。已修: (a) 金色单次总额守卫此前完全未覆盖（测试用 `LUCKY_EGG_G` 卡面定义 `golden=False` → 引擎只触发 1 次战吼, 删除守卫仍 22/22 全绿）→ 改用真实金色实体 `to_hand(..., golden=True)`, 变异删守卫现 1 failed; (b) 非家族负对照只召唤 2 次（阈值 3 达不到）→ 补为 3 次不同 id, 删除家族过滤现 1 failed; (c) 池记账改用施放前基线 + 新增"结算前三个候选各预留 1 份"断言; (d) `BG30_104` 数据链断言去同义反复（原 `getattr(...,"evolution_card_id_2",None) or 113130` 恒走 fallback → 直接 `by_dbf(113130)`; 该 CardDef tag 未由 `defs.py` 导出）。**残余**: (i) "source 已离场"竞态守卫零覆盖; (ii) 脚本 docstring 对守卫时机的解释有误（`_run_play_effects` 的 N 次触发在任何选择结算前完成, 第 2 次触发时蛋仍在场）——守卫行为正确, 措辞待改。 |

| 34 | **两个收尾备注（对抗验证 d981df6 的 minor 项, 未修）** | 无卡阻塞 | (a) `batch_hero_remaining2._combat_opponent` 在控制者不属于战斗双方时返回 side `a`, 而 `batch_consume` 同类函数返回 `None`——Solo 下不可达, 但口径不一致; (b) `KaboomBotScript` docstring 声称 `num(0)` 缺失 fail-loud, 实际无显式 `GameStateError(PARAM_MISSING)` 守卫（会以 TypeError 暴露; 数据存在, 无运行时影响）。另: 第三十五轮提交信息中的 smoke 验收行（seed 24680）实测为 `completed=199 incomplete=1 crashes=0`（seed 24777 turn=50 未完成, A/B 剔除新 id 后同样未完成 → 与本次改动无关的既有现象）; 该行不应被复用为"200/0/0"。**补测（第三十六轮）**: 已补金色重选（两个 1 血敌人在场, 断言 2 次实例命中 2 个不同存活实体）与 Goose 战斗内致死召唤 Fledgling; 变异探针（目标在循环外一次性选取）使重选测试失败 → 非空转。 |

| 33 | **审计盲区: `audit_card_registry_v2.is_effective()` 的 `TEXT_EFFECT_MARKERS` 不含裸 "Discover"（未修）** | 无卡阻塞（工具口径） | 第三十三轮发现: 池法术 `EBG_Spell_037`（Unmasked Identity, "**Discover** a new Hero Power."）因此长期未被门禁计入"effect-bearing"→ 长期滞留 DEFERRED 而无人复核。补该 marker 会连带要求为 3 张 Duos 池法术建台账（`BG31_242/243/244`, 双打越界）→ 需与"Duos 不入范围"的口径一并裁定后再改工具。 |

| 32 | ✅ **已修复（第四十七轮）** `grant_depth` 全局窗口过宽（传递性注册误持久）+ 一处"行为收窄"的裁定 | 无卡阻塞（引擎正确性） | **诊断确认（第三十一/三十二轮记录属实）**: `EventBus.register` 在 `grant_depth>0` 期间对**所有**注册打 `survives_combat`（无 owner 判定）→ (a) on_bind 副作用召唤的**临时实体**的监听器被误持久（`BG31_843` Meteorite Crasher 的 `on_summon` 注册 `MINION_SOLD owner=随从`）; (b) 由新授予实体**回调**（on_bind 窗口外）注册的监听器被丢弃（相对 HEAD^ 的 owner 判定为收窄）。**修复**: 删除 `EventBus.grant_depth`，改为**显式身份作用域** `EventBus.persistent_bind_scope(*owners)` + `EventBus._bind_owners`; `register` 仅在 `listener.owner is 作用域内某一身份` 时打 `survives_combat`（**按 `is`，非值相等**）; 三处派发入口压入作用域: `Game.run_on_bind(entity, ctx)` = {绑定实体, 接收英雄（`ctx["hero"]`，缺省 `entity.controller`）}、`Game.wire_hero_power_on_bind(hero, pid)` = {hero}、异变 `on_bind` = {全部英雄}。`run_combat` finally 仍按 `l.survives_combat`（身份比较判"新"）保留。**持久接线权威（卡面/引擎契约）**: Pocket Cyclone `BG35_MagicItem_850` "Cast Easterly Winds. At the start of each turn, cast it again." → 载荷 `BG34_444` Easterly Winds on_play "…this game…" 注册 `TAVERN_REFRESH owner=hero`（法术实体已 REMOVED，hero 是生命周期宿主）; 英雄技能接线 `TB_BaconShop_HP_036t` Nether Portal "At the start of each turn, get 2 random Demons" 注册 `TURN_START owner=hero`（Lord Jaraxxus `TB_BaconShop_HERO_37` 跨 150 伤害 → 替换 + 接线）; 战斗内任务/奖励 `on_bind`（如 `BG24_Reward_125`）owner=奖励实体; 饰品 `BG32_MagicItem_830` 注册 `BATTLECRY_TRIGGER owner=trinket` → 三类身份都在作用域内 → 战后保留。**仍丢弃（负对照）**: `BG32_MagicItem_960` Crocheted Sungill 在 `start_of_combat` 注册 `AFTER_ATTACK owner=trinket`（非 on_bind 派发、战前已存在）→ 不标记，实测 (0, 0)（旧 owner 判定会 1→2 逐场累积）。**#32b 裁定（非缺陷, 保留丢弃）**: 持久性由**注册时机**（处于 on_bind 派发内）决定, 而非 owner 身份——新实体在窗口外由其回调注册的监听器仍是战斗作用域。依据: 引擎监听器表快照契约（战斗内注册不延续）+ Sungill 负对照同一原则; 若按 owner 保留（HEAD^），任何"每场注册一次"的回调都会在新实体上逐场累积。当前**无生产卡实例**走该路径; 未来若有卡需要，须显式 opt-in（不实现引擎按 owner 猜测）。**回归**: `test_engine_gaps.py::TestCombatGrantedListenerSurvival` +3: (i) 真实路径传递性召唤（`grant_trinket(BG32_MagicItem_830)` on_bind → `entity_created` → `summon BG31_843`）的监听器被丢弃（正对照: 绑定实体自身存活）; (ii) 窗口外回调注册（同 owner）被丢弃（同 owner 的 on_bind 内注册存活）; (iii) 身份 vs 值相等: `__eq__` 命中绑定实体的代理 owner 被丢弃，存活集合恰为 {绑定实体, 接收英雄}。**变异探针（2 文件 305 测试）**: M1 恢复全局窗口标记 → 2 failed（i/iii）; M2 改按值相等（`owner in scope`）→ 1 failed（iii）; M3 恢复 HEAD^ owner 判定 → 1 failed（ii）; M4 删除持久标记 → 6 failed（#30/#31 正对照 + 新）。**验收**: 全量 `3873 passed, 2 skipped, 14 subtests`; 六件 strict 全 PASS; smoke seed 606060 `games=150 completed=150 incomplete=0 crashes=0`。 |

> **订正（第四十八轮完备性审计 finding 3）**: `BG30_MagicItem_869` 的载荷 `BG29_873`/`BG29_877` 当时**未注册**（`batch_trinkets31.py:106` 记录正确）——此前本行把它归入"载荷已注册"分组有误。**2026-09-19 更新**: 四份载荷（含金色）已由 `batch_payload_minions` 注册，869 Felblood Portrait 同批注册（A 组闭环），本条订正已完成使命。

| 31 | ✅ **已修复（2026-09-14 第三十一轮）** 战斗中授予的 Hero-owned 持久监听器丢失（#30 同类） | 无卡阻塞（引擎正确性） | 第二十九轮对抗验证实测两例: (a) **Lord Jaraxxus** `TB_BaconShop_HERO_37` 跨越 150 伤害后`replace_hero_power` → `NetherPortalScript.on_bind` 注册 `TURN_START owner=hero`, 战后被快照抹掉 → **Nether Portal 永久失效**（HEAD 与修复前同）; (b) **Pocket Cyclone** `BG35_MagicItem_850` 战斗内授予后, 其 Easterly Winds `TAVERN_REFRESH owner=hero` 丢失。根因: 这些监听器 owner 是 **Hero**（而非新授予实体），故 #30 的"新授予实体"判定覆盖不到。**修复（第三十一轮, 按本条给出的正交方案）**: 新增 `EventBus.grant_depth` + `Listener.survives_combat`; `Game.run_on_bind(entity, ctx=)` 在 `on_bind` 执行期间置位（4 处任务/奖励/饰品接线改走该入口），英雄技能接线（`wire_hero_power_on_bind`）与异变 `on_bind` 同样置位 → 期间注册的监听器标记为**持久接线**。`run_combat` 的 finally 改为按 `l.survives_combat`（身份比较判"新"）保留, 不再按 owner 猜测。回归 `test_engine_gaps.py`: 战斗内 `wire_hero_power_on_bind` 的 Hero-owned 监听器战后存活（正）/ 战斗内直接注册的 Hero-owned 监听器仍丢弃（负, 含触发前置断言）/ 战前持久实体的战斗作用域注册仍丢弃（Sungill 负对照）。**第三十二轮补正（对抗验证驳回原"已修复"结论）**: 真实 Lord Jaraxxus 路径并不经过 `wire_hero_power_on_bind`——`batch_hero_econ3.JaraxxusScript.on_attack` **直接**调用 `NetherPortalScript.on_bind(hero, game)`（绕过引擎接线入口, `grant_depth==0`）→ 监听器仍被抹掉、技能永久失效。已改为调用 `game.wire_hero_power_on_bind(hero, "TB_BaconShop_HP_036t")`, 并新增**真实卡**回归 `test_jaraxxus_real_card_nether_portal_survives`（真实 `Hero("TB_BaconShop_HERO_37")` + 一场战斗跨 150 伤害 → 技能确实替换为 `_036t`、新监听器战后存活、第二场不累积）。另将 3 处裸 `run_script_hook(..., "on_bind")` （`batch_anomalies_final`/`batch_hero_remaining`/`batch_quest_rewards`）改走 `run_on_bind`。 **（第四十七轮 #32 起机制已替换: `EventBus.grant_depth` 删除，改为 `EventBus.persistent_bind_scope` 显式身份作用域——本行所述 `grant_depth` 仅存于当时提交历史；现行为见 #32 行。）** |

| 30 | ✅ **已修复（2026-09-14 第二十九轮）** 战斗中授予的奖励/监听器被 `run_combat` 快照回滚吞掉 | 无卡阻塞（引擎正确性） | `run_combat` 的 finally 会恢复战前监听器快照（`hsrl2/game.py:3072-3075`）→ **任何在战斗中被授予的奖励**（`complete_quest` 的 `on_bind`、以及其他战斗内授予的饰品/奖励）所注册的 `Listener` 会被整体抹掉, 效果静默失效。确定性复现（第二十八轮验证）: `BG24_Quest_124` 配 `BG24_Reward_125`, 进度 16 时在真实战斗中有友方 3/1 死亡 → 奖励到手且战斗内注册 1 个 `summon` 监听器 → 战斗结束后 `present in bus = False`; 对照（非战斗内完成）= True。随机 20 局 8 人局: 90 次完成中 **43 次发生在战斗中**, 28 个奖励监听器丢失; `batch_quest_rewards.py` 单文件有 45 处 `Listener(`。**修复（第二十九轮, 第三十轮按对抗验证收窄）**: `run_combat` 的 finally 在快照回滚后只重新挂回"战斗中**新授予**的持久实体（`hero.trinkets`/`hero.quest_rewards` 中战前不存在者）"的 `on_bind` 监听器——用 `_persistent_before` 战前快照判定"新"，成员判定用**身份**（`is`）而非 dataclass 值相等; 战前已存在的持久实体在战斗中注册的监听器仍是战斗作用域并随快照丢弃。反向验证发现原"凡持久 owner 一律保留"的写法会保留 `BG32_MagicItem_960`（Crocheted Sungill）在 `start_of_combat` 注册的 `AFTER_ATTACK` 监听器 → **逐场累积**（实测 1→2→…），已收窄并新增该负对照。回归 `test_engine_gaps.py::TestCombatGrantedListenerSurvival`: 真实 `run_combat` + `AFTER_ATTACK` 钩子在战斗内 `grant_trinket`（正对照: 监听器战后仍在）+ 负对照（战斗内注册的非持久监听器仍被丢弃）。 |

| 28 | ✅ **已完成（2026-09-14 第二十七轮）** 三连合并未注销被并随从监听器（引擎缺陷） | 无卡阻塞（引擎正确性） | `Game.check_for_triple._combine` 把被并随从移出 board/hand 并置 `Zone.REMOVED`，但**未** `events.unregister_owner(m)` → 其监听器**永久残留**。可观察后果（对抗验证实测）: 3 张 `BG28_741` Charging Czarina 三连后，施放酒馆法术时金色随从被 buff **+20 攻**（3 个残留基础监听器各 +4 与金色自身 +8），正确值 +8；该缺陷对**所有** `on_summon` 注册持久监听器的随从成立（光环/触发类）。修复: 两处合并分支（棋盘合并 / 纯手牌合并）在 `zone = Zone.REMOVED` 后补 `unregister_owner`; 回归 `test_engine_gaps.py::TestTripleMergedListenerCleanup`（监听器注销 + 金色只按自身 num(0)=8 计一次）。 |

| 27 | ✅ **已完成（2026-09-19 复盘）** **Czarina Portrait `BG32_MagicItem_283`（"also give Health"）** | `BG32_MagicItem_283` | **真实机制**: 载荷 `BG28_741` Charging Czarina 是 "Whenever you cast a Tavern spell, give your minions with **Divine Shield** +num(0) Attack"（`batch_econ_misc.ChargingCzarinaScript`: 监听 `TAVERN_SPELL_CAST` → 本人**棋盘**存活的圣盾随从 +num(0) 攻; 基础 4 / 金色 8）。**落地实现（与第二十七轮方案等价但更贴 §7.4.16 先例）**: 饰品 `on_bind` 交付载荷（数据链 `evolution_card_id=110321`）后 `game.add_family_flag(hero, BG28_741, FLAG_CZARINA_ALSO_HEALTH, source=饰品)`; 载荷 `on_tavern_spell` 经 `game.family_flag` 读取，同一次 `Buff` 追加 `health=d.num(0)`（同一选择集、同一触发、per-Czarina 缩放; 金色按基础 id 归一 → num(0)=8 同时用于两属性）。**权威**: wiki.gg `Battlegrounds/Czarina_Portrait`（revid=921161）`?action=raw` 全文仅 Card template、**无 Notes** → 卡面天然语言 "also give Health" 增量 = 同句唯一数字 `num(0)`（否决固定 +1 / 自身 Health / 隐藏 {1} 参数，见 `batch_trinkets31.CzarinaPortraitScript` docstring）。**台账迁移已完成**: trinkets14/24/28/29/31/35/36 的 DEFERRED 条目与计数、`_CARD_CLASSES`/`_TEXT_SIGNATURES`/`_RELATED_CARDS` 字典条目全部同步; 行为测试 6 项（`test_batch_trinkets31.py::TestCzarinaPortrait`）走真实 `grant_trinket` + `play_spell`。 |

| 26 | ✅ **已完成（2026-09-14 第二十四轮）** `cast_spell_effect`（效果施法）下"永久 Spellcraft"失效（无生成期标记 + 无来源出处） | `BG32_MagicItem_920`（temporary buff 口径）与 `BG32_MagicItem_933`（Reborn 关键词口径）两族 | 2026-09-14 对抗审查 BUG-2: 手牌路径本轮已补**施放期反查 + 回写** `spell.permanent_spellcraft`（game.py 施放路径; 修 BUG-1），但 `cast_spell_effect` 在 game.py:1408 新建法术既不打标、也无 `spellcraft_source_uuid` → 来源随从不可知，"永久"条款在该入口（RULES §7.4.7b）整体失效（920 同样失效，非 933 引入）。修复（本轮）: `cast_spell_effect(hero, card_id, target=None, source=None)` 新增 `source`（原始法术实体）→ 继承 `spellcraft_source_uuid`，并在 fire `spell_resolving` 前调用与手牌路径**共用**的 `_resolve_cast_permanence`（标记回写 + `_permanence_pending`），故 920 的 buff 口径与 933 的关键词口径在效果施法下同样生效; Lovely Locket 重施放已传 `source=spell`。残余契约: 调用方不传 `source` 时来源不可知 → 不永久化（诚实行为，非空转）。
另两处由二轮对抗审查追加并已修: **FALSIFIER 1** `source=` 一并继承**已解析**的 `permanent_spellcraft`（来源已售出/饰品失效时签名反查失手，同一法术两条路径须同结论）; **FALSIFIER 2**（引擎既有缺陷，影响 920 等 `_permanence_pending` 使用者）嵌套效果施法（Coral Spear `BG35_MagicItem_925` 在 `spell_resolving` 内再施放）不再清掉外层窗口——`cast_spell_effect` 入口保存并在出口恢复 `_permanence_pending`。回归: `test_batch_trinkets37.py` 的 `test_recast_inherits_resolved_flag_when_source_left` / `test_nested_effect_cast_does_not_clobber_permanence_window`（stash game.py 双向验证: 无修复即 FAIL）。遗留观察（既有、当前不可达）: 嵌套的**非永久**施法若落在与外层永久施法**同一**随从上，其临时 buff 也会被翻转（内层 `on_play` 在外层窗口内执行）——现役卡无此组合（唯一 `spell_resolving`→效果施法 是 Coral Spear，其 `BG35_951` 本就是永久属性），若未来出现内层临时 buff 施法者需按施法粒度加窗口令牌。 |

| 24 | **Buddy（伙伴）按钮购买子系统整体缺失** | 异变 `BG27_Anomaly_810`/`BG27_Anomaly_Buddies`、`BG33_Anomaly_002/003/005/009`、`BG33_Anomaly_001` Summoning Pact（升级后下次 Buddy 减费 2） | 2026-09-14 全仓核实: `companion_id`/buddy **零引擎读取点**（`hsrl2/game.py`、`hero.py`、`actions/*` 皆无），伙伴只在脚本里作为"发现池"载荷被引用 → 任何"Buddy 按钮费用/购买/减费"条款无落点。注意 `tavern_upgraded(hero=, tier=)` 事件**已存在**（game.py:1561/1572），故 `BG33_Anomaly_001` 的缺口纯粹在 buddy 侧。 |
| 25 | ✅ **已完成（2026-09-20）** **酒馆等级白名单 + Triple Reward 档位覆写钩子** | 异变 `BG27_Anomaly_101`（仅 T1/3/5 存在）、`BG27_Anomaly_102`（仅 T2/4/6）**已注册**；`BG27_Anomaly_716`（升级后 Discover Darkmoon Prize）**仍 DEFERRED**（阻塞不在本钩子——缺的是 Darkmoon Prize 池数据） | **落地**: `game._tavern_tier_ladder`（存在档元组; 读取点 = `_next_existing_tier` 升级落点 / `_ladder_tier_filter` → `MinionPool`+`SpellPool.draw_tavern(tiers=)` 酒馆展示 / `actions.discover._pool_candidates` + 显式候选 Discover）与 `game._triple_reward_of_own_tier`（`_grant_triple_reward` 取 `hero.tavern_tier`）。注册 `batch_anomalies3.WhatAreTheOddsAnomaly`/`HowToEvenAnomaly`; 测试 `test_batch_anomalies3.TestTierLadderAnomalies`（9 条真实路径 + 负控制）; 覆盖率 异变 **73/108**。**逐问裁定（URL + revid + 引文见 `docs/ANOMALY_101_102_EVIDENCE.md`「最终裁定（2026-09-20）」）**: 起手档 = 最低存在档（101→T1，102→**T2**; 先例 Big League 起手 T3）; 升级落点 = 下一存在档; 升级费 = **步数序列**（wiki Tavern Tier revid 762299 "Upgrading starts at 5 Coins, and each upgrade costs more than the last." → 首次 5 金、其后 `BASE[3]=7`，非目标档计价）; 展示白名单 = `[下限,本人档] ∩ 存在档`（随从 + 酒馆法术; wiki Tavern spell revid 916040）; 三连奖励档 = 本人档（卡面 "of your Tier" + token `BG27_Anomaly_101t` 的 CardDefs `Tier @`——wiki 渲染出的 "Tier 0" 是 `@` 占位符，本轮已订正）; T7 不越档（他卡 "Unlock Tier 7" 无效）; 快照时序 moot（同步发奖）。**边界（显式未实现）**: 脚本级"显式指定 Tier 的发现"（约 25 处法术候选自建）与他卡"高一档"算术（Innkeeper's Stein）不做档位重映射——白名单只**移除**非存在档（该位落空），不改成"下一存在档"; Big League/Little League 的法术展示口径未动。原 2026-09-16 "维持 DEFERRED" 裁定据此撤销（缺的是**读取点**而非数值权威; 费用有 wiki 通用规则权威、其余按卡面自然语言解读并记录被否决读法）。 |

| 20 | ✅ **已解除（2026-09-18 第四十九轮，项目所有者权威序）** 任务系统难度数据（整族阻塞） | `BG24_Quest_*` 17 张 + `BG27_Quest_800/801/802` + `BG28_Quest_500` + 依赖任务载荷的 `BG24_HERO_100p` Whodunit? | **解除依据**: 项目所有者 2026-09-18 直接裁定的权威序（wiki 详细说明 > 卡面自然语言理解）。wiki 各卡页 "Patch changes" 段的 **"baseline requirement" 当前值**即权威目标值（四因子只是围绕该基线的 ±修正，表无数据源 → 按近似边界记录在案，不再阻塞）。19 张任务已注册（`batch_quests`，`BG27_Quest_801` 为阈值式），1 张 DEFERRED（`BG24_Quest_328` "Win the game." 胜义无权威——**语义权威缺口而非近似，也不是缺目标值**: 卡数据有 `quest_progress_total=1`，tag 535），2 张公告 token 由 `Game.quest_defs()` 排除。`CardDef.quest_progress_total`（tag 535）已导出为数据字段 + 交叉校验源。逐卡 URL/oldid/引文、条件口径、近似边界见 `docs/agents/QUEST_DEFERRED_SPEC.md`（2026-09-18 重写）。**遗留独立工作项**: `BG24_HERO_100p` Whodunit? 仍 DEFERRED，但理由已从"任务载荷不可推进"变为**接线**（现有 `WhodunitScript` 候选池写死 `BG24_Quest_*` 前缀，会把已 DEFERRED 的 328 与公告 token `BG24_Quest_Bob` 一并发出 → 接线须改用 `game.quest_offer_pool()`）。 |
| 21 | ✅ **已完成（2026-09-14 第二十五轮）** `MINION_PLAYED` 死常量 | 无卡阻塞（观察点卫生） | 已选"在 `play_minion` 补 fire"路线: **从手牌打出**随从（含磁力吸附）fire `minion_played(minion=)`（game.py 两处成型点），`summon`（效果召唤）**不** fire; 回归 `test_engine_gaps.py::TestMinionPlayedEvent`（正对照 + 召唤负对照）。原状:——`Game.play_minion` 只 fire `card_played(card=)`（`minion_played` 全仓无 fire，2026-09-13 实测）。消费方若要"打出随从"事件须用 `card_played` + `isinstance(card, Minion)`；建议后续二选一: 在 `play_minion` 补 fire（使声明成真）或删除常量。 |
| 22 | ✅ **已完成（2026-09-14 第二十二轮）** 覆盖率仪表与**可实现集**对齐 | `tools/audit_card_registry_v2.py::report_coverage` | 仪表此前三个失真: (a) quest 只数 `BG24_Quest_*`（17，且含公告 Spell `BG24_Quest_Bob`）→ 2026-09-18 对抗审查再订正为**与引擎 `Game.quest_defs()` 同源**（`hsrl2.game.quest_defs_from_db` / `is_quest_card`）= **20**（19 注册 + `BG24_Quest_328` DEFERRED; 两张公告 token `BG24_Quest_Bob`/`BG33_Anomaly_008_Quest` 不再计入分母——它们满足 SPELL + tag 535 + id 含 quest 三条谓词，是"注册即空转"的第三态，只由 `_QUEST_ANNOUNCE_TOKENS` 排除）; `tools/audit_script_wiring.py::category_of` 同步改用同一谓词（此前 wiring=21 含 Bob、registry=21 含 Anomaly，集合互异）; (b) trinket 用全域 `card_type=44`（379，含 `BG30_Trinket_1st/2nd` 报价 token 与 `_t/_t2` 载荷变体）→ 改用 `CardDB.trinket_offer_pool()` 的**商店可提供集**（331，与 `TRINKET_LEDGER.md` 同口径; 全域数仍作附注打印）; (c) `quest_reward` 分母含 2 张已注册父卡的载荷 token（`BG28_Reward_518t`/`_G`）→ 保留分母并在输出标注。现口径（2026-09-19 后，含 batch_trinkets31 A 组 5 张）: 英雄技能 101/116、饰品 **312/331**（全域 320/379）、异变 **73/108**（2026-09-20 `batch_anomalies3` 的 101/102 注册后）、任务奖励 **70/73**（+`batch_quest_rewards8` 的 362）、**任务 19/20**。 |
> **订正（第四轮 stats_gained 对抗验证, 2026-09-20）**: 上文三处「wiki 金色文本 vs 本地数据」记录**不成立**——当时引用的是历史页面文本; 当前 wiki 金色卡页与本地数据一致（[Defiant_Shipwright_(golden)](https://hearthstone.wiki.gg/wiki/Battlegrounds/Defiant_Shipwright_(golden)) oldid=800838 / [Timewarped_Whelp_Smuggler_(golden)](https://hearthstone.wiki.gg/wiki/Battlegrounds/Timewarped_Whelp_Smuggler_(golden)) oldid=883170 / [Sepulchral_Sergeant_(golden)](https://hearthstone.wiki.gg/wiki/Battlegrounds/Sepulchral_Sergeant_(golden)) oldid=882855。**金色卡页须用 `…_(golden)` URL**: 裸 dbf/id 形式 `…_G` 的**标题不存在**（既不重定向到基础页也不渲染金色文本; 对抗验证实测），其 "Golden" 标签渲染的是**过时**文本——oldid 本身正确，但页面锚点须指向金色页）。另: CardDefs build 249896 为 **14 个语系**（非 13）; `ActionQueue` 逐动作来源重置后, 既有**已注册卡结果**不变, 但嵌套监听授予的 `source` 载荷会变化（套件未覆盖该链路）。

> **订正（第四轮 RACES 对抗验证, 2026-09-21）**: 提交信息中「四张卡页…均无 Notes」**不实**——`Battlegrounds/Drakkari_Portrait` revid **921179** 携带 `article_notes` = 『The player cannot be offered more than 1 of this Trinket.』（与类型改写正交, 未实现, 已记档）。

| 40 | ✅ **已收口（引擎侧单一收口，2026-09-19；复现路径 2026-09-18）** **离场实体监听器泄漏**（"an entity that has left play keeps a live listener"） | 任何在棋盘 `on_summon` 注册监听器、又经非"死亡/出售/三连"路径离场的随从; 复现卡 `BG26_174` Soul Rewinder（`HERO_DAMAGE_TAKEN` 回退监听） | **实测证据（修复前）**: smoke `--games 150 --seed 909090` = `games=150 completed=149 incomplete=1 crashes=0`; 不完整局 **seed 909199 turn=50**——仅 **H7** 被冻结（hp=22 / armor=0; H2 hp=16/armor=5 未被冻结），事件总线仅有 **1 个** `HERO_DAMAGE_TAKEN` 监听器，owner=`BG26_174`、`zone=TAVERN(3)`、**不在任何** board/hand/tavern 列表 → 每场战斗把 H7 的战败伤害回退到伤害前值。删掉该**唯一**监听器（不动其它状态）→ `turn=13 finished=True`; `turn_cap=200` 仍 `turn=200 finished=False`（非 hang，也非"合法僵局"）。**复现**: `python tools/smoke_random_games.py --games 150 --seed 909090`（修复前出 INCOMPLETE seed=909199）; 时间线 = 实体经 Dark Gift resolve 创建 → 上板（`on_summon` 注册监听）→ 多次战斗死亡/复原 → **Jandice `TB_BaconShop_HP_084` 将其从棋盘换入酒馆**。**根因**: `hsrl2/scripts/batches/batch_hero_actives.py::JandiceScript.hero_power` 在 `target.zone = Zone.TAVERN` 后**未调用** `game.events.unregister_owner(target)`（与 `sell_minion` / 三连合并的既有离场注销口径不一致）。**复现路径已修复（small + precedented）**: 补该调用; 真实路径测试 + 变异探针 `hsrl2/tests/test_batch_hero_actives.py::TestJandice::test_swap_unregisters_swapped_minion_listeners`（去掉调用即失败）; 修复后 seed 909090 = `games=150 completed=150 incomplete=0 crashes=0`，seed 909199 → `turn=13 finished=True`。**同类路径已全部收口（2026-09-19，引擎侧单一收口）**: 缺陷根因是"监听器生命周期依赖**每个**离场路径显式调用 `unregister_owner`"（脆弱）。改为在**唯一区域赋值出口** `Entity.zone` setter 上强制契约——(i) **随从**新值 ∈ {`REMOVED`,`GRAVEYARD`}（自任何区域）; (ii) 旧值 `Zone.PLAY` → 非 `PLAY`/非 `SETASIDE`——自动 `game.events.unregister_owner(self)`（`Zone.SETASIDE` = 复生处理期间的临时离场，例外; 英雄/饰品/任务奖励 zone 恒为 `Zone.INVALID`，不受影响; **法术**可处于 `HAND`，但**从不进入 `PLAY`**，其 owner 监听器是效果期接线、须活过 `_finish_play_spell` 的 `REMOVED`，故 (i) 刻意不含法术——见 RULES §6.22）。全仓生产代码 51 处 `x.zone = Zone.*`（其中 28 处此前无显式注销）经此收口，无需逐脚本迁移; 既有显式注销变为**幂等冗余**（`unregister_owner` 可重复调用）。**后续对抗验证补口（2026-09-20，Malygos）**: (i) 分支是 64443b0 之后补上的——此前 `batch_hero_actives.py::MalygosScript.hero_power`（技能 `TB_BaconShop_HP_052` Arcane Alteration）把一张带 Dark Gift 的**手牌随从**移入 `REMOVED`（旧值 `HAND`，不触发 (ii)）→ `_make_counter_gift` 监听器残留、在后续 `battlecry_trigger`/`tavern_spell_cast` 上继续给已离场实体加属性（真实英雄技能 + 真实 Dark Gift 确定性复现）; 现由 (i) 覆盖，法术分支（**销毁**一张手牌法术，非"打出后的常规结算终态"）另加显式 `unregister_owner`。真实路径回归 + 变异探针 `test_batch_hero_actives.py::TestMalygos::test_replaced_minion_listeners_unregistered_and_stats_frozen`。另修两处 `run_combat` 快照机制的**二次复活**漏洞: (a) 战斗内 `Transform` 重放把旧实体换出棋盘，但 `restore_state` 已把旧实体 zone 复原为 `PLAY` → 重放处补 `old.zone = Zone.REMOVED`（同时消除"离场但 zone=PLAY"静默第三态）; (b) `events_snapshot` 监听器表复原是**全局**的（不区分 owner 是否仍在场）→ 战斗期间永久离场的随从监听器被复活 → `finally` 末尾加离场收口（丢弃 owner 处于 `REMOVED`/`GRAVEYARD` 的监听器）。**测试**: `test_engine_gaps.py::TestLeavePlayListenerInvariant`（8 例: board→hand/tavern/REMOVED、负对照在场保留、复生 SETASIDE 例外、英雄持久监听器不受影响、战斗内 Transform 旧实体收口、快照复原不复活离场监听器）、`test_batch_trinkets19.py::TestDoubleStitchNeedle::test_return_to_hand_unregisters_minion_listeners`、`test_batch_rally.py::TestExpertAviator::test_expired_combat_copy_unregisters_listeners`; 变异探针（去掉 setter 注销 / transform 重放 zone / 快照收口）各自令对应测试失败。 |
 **实测分类与残留（2026-09-19 全仓审计; 计数 2026-09-20 订正为 51）**: 51 处生产 `x.zone = Zone.*` 分类: (i) **进入 PLAY**（`summon`/复生/Transform 新实体，6 处）→ 无需注销; (ii) **自酒馆/手牌/新建实体离场**（Enchanted Lasso `batch_spells1`、Decoy Conjurer `batch_activate`、Snarky Shark 替换、Rally 手牌副本、`attach_magnetic` 手牌机械等——从未跑过 `on_summon`）→ **多数**安全（已被 setter 兜底）。**`attach_magnetic` 经核实为 latent-unreachable（2026-09-20）**: Dark Gift `eligible_minions` 明确排除 Magnetic 随从（`darkgifts.py` 过滤条件 5），而 `LOCKED_IN_HAND` 又阻断打出，故没有生产路径能让手牌磁力机械携带存活的**离场前注册**监听器到达吸附点（且现由 setter 兜底）。**订正（2026-09-20）**: 旧分类把 **Arcane Alteration**（Malygos 手牌→`REMOVED`）列在此类"安全"中——**不成立**: "无 in-play 监听器" ≠ "无监听器"; Dark Gift `_make_counter_gift` 等**离场前注册**的监听器可挂在手牌随从上，移入 `REMOVED` 后继续触发（audited-but-previously-uncovered; 现由 setter (i) 分支收口）; (iii) **法术/宝箱/`card` 实体的 REMOVED**（spell 不注册 in-play 监听器）→ 安全; (iv) **淘汰/死亡清场**（本已有显式注销）→ 安全; (v) **棋盘随从离场**（Double Stitch board→hand、Expert Aviator 副本→REMOVED、Jandice board→tavern、Trash for Treasure/Stir the Pot/Rusty Trinket 批量移除）→ 本类，现已由 setter 收口。150 局随机审计（seed 828282..828431）**在默认随机策略下**后**不再存在** owner 处于 `REMOVED`/`GRAVEYARD`、或 `zone=PLAY` 但不在任何棋盘的监听器。**该结论是策略作用域的（2026-09-20 限定）**: 那些对局不会把 Malygos `TB_BaconShop_HP_052` 的英雄技能定向到一张带 Dark Gift 的手牌随从，故 Arcane Alteration 路径**未被采样**——"审计未发现"不等于"不存在"（audited-but-previously-uncovered）。剩余 19 个 distinct 状态全部是 **`zone=HAND(2)`/`zone=INVALID(0)`** 的**离场前注册**监听器（Dark Gift `apply_dark_gift` 在 `pending_hand_add` 前注册、`on_enter_hand` 注册的 Bream Counter/Groundbreaker、Discover resolve 期间的 `_unlock`/`_on_played`、`_schedule_unlock` 手牌锁定 tick）——它们是设计上的**离场期**监听器（手牌解锁/手牌 Dark Gift），不是"离场后残留"，本类不涉及。**另记（未改）**: `_make_counter_gift`/`_soc_listener` 注册的 gift 监听器无 `zone != PLAY` 守卫（手牌期间可触发），`_make_card_played_gift` 有守卫——"离场前注册的 gift 监听器在手牌期间是否应生效"是**另一个**既存缺口（2026-09-20 仍未动: 无 wiki 权威; 且 `_schedule_unlock` 依赖离场期监听器存活 → 不能笼统按 zone 惰性失效，故未采用"事件分发时按 owner zone 惰性失效"方案）。**2026-09-20 已闭合的相邻一半**: 该 gift 监听器在宿主被移入 `REMOVED`/`GRAVEYARD` 后**不再存活**（setter (i) 分支 + Malygos 法术分支显式注销）——即"手牌期间可触发"保留、"离场后仍触发"关闭。 |
## B2. 第五波迁移（trinkets24/25/26，2026-09-02）新上报缺口

| # | 缺口 | 阻塞卡 | 实现路径要点 |
|---|------|--------|--------------|
| B2-1 | **本回合已售随从计数 tag** `MINIONS_SOLD_THIS_TURN`（hero 级，`sell_minion` 成交后 +1、每回合清零） | `BG30_MagicItem_992`（精度：绑定前已售不可见）/ `BG32_MagicItem_832` Windfall Portrait | 引擎 tag + `sell_minion` 写入；`BG32_MagicItem_890`（本回合已触发战吼数）同族。 |
| B2-2 | ✅ **已完成（2026-09-02，提交 66eaa35）** `Hero.gold` setter 广播 `gold_gained(hero=, amount=)`（上限截断后增量）; 对抗验证实测出售 +1 / `GainGold(3)` +3 / 溢出截断 +92 | `BG32_MagicItem_350` Splinter of Aurum 现可迁移（残余 AMBIGUOUS: "you have 15 Gold" 是"达到即触发"还是"获得后恰好"） | — |
| B2-3 | ✅ **已完成（2026-09-02，提交 66eaa35）** `GameTag.TAVERN_OFFER_TIER_EXACT`（全部随从位取自恰好该档）+ `TAVERN_EXTRA_TIER_SLOTS`/`TAVERN_EXTRA_TIER`（额外位取自高一档） | `BG32_MagicItem_366` Guiding Candle / `BG30_MagicItem_423` Innkeeper's Stein 现可迁移（主动刷新计数由 `tavern_refresh(auto=)` 区分） | — |
| B2-4 | ✅ **已完成（2026-09-21，`batch_family_races`）** 多值种族 `RACES`（集合）——实现同 §A1 | `BG32_MagicItem_179`（Drakkari）/ `BG30_MagicItem_971`（Enforcer）/ `BG30_MagicItem_418`（Bronzebeard）/ `BG30_MagicItem_825`（Smuggler，**单类型**——非集合缺口，阻塞为家族单值类型改写读取点 + 载荷效果缺 `stats_gained`，见「C 组」） | 同 §A1；`Race.ALL` 是"匹配一切"而非"同时属于多族"。**（2026-09-21 订正: 该表述已过期——现已实现 `GameTag.RACES` 集合身份, `Race.ALL` 展开为全 10 族, 家族改写为并集; 见 §A1「C 组」闭环节与 RULES §7.4.16c。）****id 前缀订正（2026-09-19 数据核实）**: 825 实为 `BG30_MagicItem_825`、179 实为 `BG32_MagicItem_179`（旧记前缀相反）。详见「C 组 RACES 权威核查」。 |
| B2-5 | ✅ **已完成（2026-09-02）** 战斗内 `Transform` 记入 `game._combat_transforms`，`run_combat` 复原后原位换回新实体 + 重跑 `on_transform`（RULES §6.21/§3.5 例外） | `BG32_MagicItem_419` Yu'lon Sticker 现可迁移（旧 gap 守卫测试已改为持久性断言） | 实现见 `test_engine_primitives.py::TestCombatTransformPersistence`。 |
| B2-6 | ✅ **已完成（2026-09-02，提交 152dd7b）** `minion_consumed` 增 `from_tavern=` / `stats_atk=` / `stats_health=` / `consumer=`（吞噬瞬间快照，受害实体已 REMOVED 也能读） | `BG32_MagicItem_902` Statue of Hir'eek 现可迁移; `BG35_MagicItem_156` Flaming Portrait 剩 `minion_triggered` 语义（见 B2-15，可用本载荷的 `consumer=` 镜像实现，待逐卡裁定） | — |
| B2-7 | ✅ **已完成（2026-09-02）** `last_minion_died(hero=)`（每场一次、需本场有死亡）+ `hero._combat_dead_snaps` 轻量死亡快照 | `BG32_MagicItem_907` / `BG35_MagicItem_732` 现可迁移 | `combat_death_log` 顺序保留（Kangor 用）。 |
| B2-8 | ✅ **已完成（2026-09-02）** `refresh_tavern(keywords=)`（关键词白名单）+ `hero._tavern_extra_keyword`（额外关键词展示位）+ `hero._tavern_cost_rules`（条件化购买价） | `BG35_MagicItem_743` / `_755` 现可迁移 | 见 `TestCardAuraAndCombatHooks`。 |
| B2-9 | ✅ **已完成（2026-09-02）** 生成器导出 `TAG_SCRIPT_DATA_NUM_5`(2920) + `CardDef.num(4)` | `BG35_MagicItem_431t` / `_920` / `_923` 现可迁移 | `data/` 重算差异仅 +16 行。 |
| B2-10 | ✅ **已完成（2026-09-02，提交 45ca9c0）** `_offer_trinkets` 读 `hero._next_trinket_kind` 并消费即清 | `BG35_MagicItem_818` Mysterious Orb 现可迁移（"Gain 10 Gold" 侧用 `GainGold`） | — |
| B2-11 | **三连奖励替换钩子 + Darkmoon Prize 候选表** | `BG35_MagicItem_812` Corrupted Tome | `_grant_triple_reward` 无覆写读取点；Prize 无候选数据（RULES §11.4）。 |
| B2-12 | ✅ **部分完成（2026-09-13，提交见第十六轮）** `Hero.giver_bonus` + `Game.add_giver_bonus(hero, card_id, *, atk, health, copies)` / `Game.giver_bonus(hero, card_id)`（金色→基础 id 归一，RULES §7.4.15） | `BG30_MagicItem_944` Redeemer Portrait / `_828` Shaker Portrait 已注册（batch_trinkets33）; ~~`_987` / `_283` 仍缺 "+Attack/+Health" 增量权威~~ → **2026-09-19 已闭环**（987/283 由 batch_trinkets31 经 `family_flags` 数值增量落地，非 giver_bonus; 见 A 组行）; `_274` 已由 batch_trinkets34 闭环 | 载荷消费点: `NalaaTheRedeemerScript.on_cast` / `ZestyShakerScript.on_played` |
| B2-13 | **Battlecruiser Upgrade 附着子系统** | `BG32_MagicItem_806` Battlecruiser Portrait（+ Jim Raynor `BG31_HERO_801p`） | `BG31_HERO_801pta..j` 部件附着无法用 `inject_tavern_minion`/`add_tavern_entity` 表达。 |
| B2-14 | **Minor Timewarp 成员定义域** | `BG35_MagicItem_823`（+ `BG34_Giant_605`） | XML 只有 `BACON_TIMEWARPED` 布尔且生成器未导出。 |
| B2-15 | **`minion_triggered(hook=, source=, value=)` 观察点** | `BG35_MagicItem_156` Flaming Portrait（+ `_433`） | 现有 `minion_consumed` 无法区分"自身 EoT 触发"与"被别的卡驱动吞噬"→ 会过触发。 |
| B2-16 | ✅ **已完成（2026-09-02，提交 45ca9c0）** `Game.trigger_friendly_rallies(hero, ctx=None)` + `_has_rally_hook`（含磁力栈叠） | `BG36_MagicItem_214` Insurrectionist's Blade 现可迁移（EoT 调用即可） | ctx 以空 dict 传入；Rally 目标由各卡脚本 `_rally_target` 自取。 |
| B2-17 | ✅ **已完成（2026-09-02）** `add_card_aura(source, card_ids, atk, health)`（增量式、任意区域、金色按基础 id 匹配） | `BG36_MagicItem_216` 现可迁移; 亦为"家族加成通道"（944/987/283/274 的一部分）提供读取点 | — |
| B2-18 | ✅ **已完成（2026-09-02，提交 45ca9c0）** Choose One 双效判定增读 **hero 级** `CHOOSE_BOTH` tag（随从与法术两条路径） | `BG36_MagicItem_308` Trailblazer Sticker 现可迁移 | 棋盘随从光环路径保留。 |
| B2-19 | ✅ **已完成（2026-09-02）** `refresh_tavern(copies_of_warband=True)` | `BG35_MagicItem_930` 现可迁移 | 白板副本零池操作。 |
| B2-20 | **"give stats" 法术类别位** | `BG35_MagicItem_921` Cowrie Necklace | 数据层无标记（`TAVERN_SPELL_COST_MOD` 是无条件 hero 级）。 |
| B2-21 | **`BG35_MagicItem_702` 缺 `BACON_EVOLUTION_CARD_ID`** | Stegodon Portrait（已注册，走"唯一名解析"回退） | 生成器/数据补 2519 后自动回数据链；当前 `_related_card` 用文本抠名 + 唯一名匹配 + 命中≠1 落空 + 审计日志。 |
| B2-22 | **载荷卡脚本未迁移（第五波新增）** | `BG21_006` / `BG29_140` / `BG25_041` / `BG31_148` / `BG31_830`(+`BG31_830t`) / `BG35_437` / `BG26_801` / `BG34_920` / `BGS_078` / `BG_OG_221` / `BG31_HERO_801pt` | 多数按 RULES §7.4.6 不阻塞交付类饰品，但会让"依赖载荷行为"的饰品维持 DEFERRED。 |

| B2-23 | ✅ **已完成（2026-09-02）** `hero.triple_threshold_race = {Race: n}`（引擎 `check_for_triple` 按被合成卡的种族取最低阈值; Race.ALL 命中一切） | `BG30_MagicItem_439` Designer Eyepatch 现可迁移 | 全局 `TRIPLE_THRESHOLD` 仍为兜底。 |
| B2-24 | ✅ **已完成（2026-09-02）** `minion_triggered(minion=, hook=, ctx=)`（`run_script_hook` 分发后广播，无监听者零开销） | `BG35_MagicItem_156` 现可迁移（与 `minion_consumed` 组合区分自身触发 vs 外部驱动） | 见 RULES §7.4.10c。 |
| B2-25 | **"improve this"（饰品自我档位升级）协议/数据** | `BG30_MagicItem_711` Marine Signet | `triple_upgrade_id` 为空、无升级变体、无官方权威。 |
| B2-26 | **战吼变形后的 "Whenever you summon" 追加阶段未建模（横切全部 `Transform` 卡）** | `BG30_104` Lucky Egg（战吼 Discover 金色 T3/T4 变形，batch_goose_lucky_egg）+ 既有全部 Transform 脚本（Robust Evolution / 临时金色 等） | wiki `Transform` 页 Notes（2026-09-17 复核）: "minions transformed **as the result of a Battlecry** will activate some of their triggered effects appropriate to the resulting minion, at the end of the summoning process"，且明确 "This double processing of the 'Whenever you summon' effect specifically happens when the transform is the result of a Battlecry"。引擎 `actions/stats.py::Transform.do` 只 fire "transform" + `run_script_hook(on_transform)`，不重放召唤流程; RULES §6.21 裁定 "Transform 不触发召唤/战吼类（官方语义: 变身不是召唤）"——**按项目权威序（CardDefs > RULES > patch notes > wiki）以 RULES 为准**，故本缺口不阻塞 Lucky Egg（其数值/选择/附魔口径全部有权威），仅登记为横切引擎口径差异: 若未来建模"战吼变形追加召唤阶段"，需决定追加阶段触发哪些 SUMMON 监听（"Whenever"/"After" 两类是否都触发）及是否只战吼来源。 |

## B3. 剩余 40 张饰品的阻塞映射（batch_trinkets31 复评，2026-09-02）

| 组 | 阻塞性质 | 卡数 | 卡 id | 主线动作 |
|----|----------|------|-------|----------|
| A | 载荷已注册、但"家族 give/also"读取点缺失 | 11→**0（全组闭环）** | — | 2026-09-19 剩余 5 张全部闭环（owner 权威序: wiki 卡页 `?action=raw` 全文仅 Card template、**无 Notes/正文** → 取卡面天然语言; 逐卡 URL/revid 与推导见 `batch_trinkets31` 各类 docstring）：**868 Rewinder**（"also gain Attack" 增量 = 同句 "give this +1 Health"（金色 +2）; 第二关联卡 `BGS_004` Wrath Weaver 由卡面点名 + 数据核实; 读取点 §7.4.16 `FLAG_REWINDER_ALSO_ATTACK`）。**987 Balladist**（"also give Attack" 增量 = 同句 Health 额 `num(1)+GOLD_SPENT_THIS_TURN`——载荷 @ 升级段 `+{0}/+{1}` 两占位符同处 "(Improved by each Gold…)" 子句; `FLAG_BALLADIST_ALSO_ATTACK` + `start_of_turn` 每回合再得 1 张）。**283 Czarina**（"also give Health" 增量 = 同句 `num(0)` Attack 额，基础 4 / 金色 8; `FLAG_CZARINA_ALSO_HEALTH`）。**824 Implicator**（"Your Demons always consume the highest-Health minion in the Tavern" = 种族范围吞噬策略——新增 `hero.consume_policies` + `Game.add_consume_policy` / `consume_policy` / `pick_consume_victim` 读取点; "Get 2" = 交付 2 份）。**869 Felblood**（两载荷 `BG29_873`/`BG29_877`（+金色）由 `batch_payload_minions` 注册; "give Attack and Health" = 两家族各在自身印面额上补齐另一属性 `FLAG_FELBLOOD_ALSO`）。此前闭环: **828 / 944**（`hero.giver_bonus`，batch_trinkets33）、**274**（§7.4.16 行为开关，batch_trinkets34）、**804**（RULES §7.4.17，batch_trinkets35）、**803 Macaw**（batch_trinkets36）、**803(BG30 Kaboom) / 820 Impulsive**（batch_trinkets39） |
| B | 载荷本体未注册（效果依赖其行为） | 5→**3** | 402 / 431 / 806 | 先迁载荷卡（402 依赖弃牌系统）。**274 Bristlebach Portrait 已闭环并注册**（batch_trinkets34，2026-09-13：§7.4.16 家族行为开关通道 + 载荷 `BristlebachScript.avenge` 消费点；其载荷 `BG26_157` 早已由 batch_payload_minions 注册——原「载荷未注册」记载陈旧）。**777 Goose 已闭环并注册**（batch_goose_lucky_egg，2026-09-17：首载荷 `BG29_801`/`BG29_801_G` 由 batch_remaining2 注册；次生载荷 `BG30_104`/`BG30_104_G` Lucky Egg 由本批注册——"transform into" = 引擎 `Transform`（RULES §6.21）+ `Discover(golden=True)` 池化发现先例（`BG27_Anomaly_572`）+ 附魔不保留（wiki Transform Notes，July 2018）+ 金色单次总额守卫（Bilgewater 先例）；饰品本体同批注册，计数 = `num(0)=3` + Fledgling token 家族） |
| C | ✅ **已完成（2026-09-21，`batch_family_races` 注册 4/4）** 多值种族 `RACES`（2026-09-19 曾记 [NO AUTHORITY FOUND]，**权威已于 2026-09-21 补齐**——wiki `Minion` revid 817925 / `Multi-type minion` revid 855346 / `All` revid 893299 + Patch 30.2.0.205267 revid 814123 Dev Comment） | **0** | — | **逐卡文本核实（4/4）**: 418 “Your Brann Bronzebeards are both Murlocs and Dragons”=2 类; 179 “Your Drakkari Enchanters are both Mechs and Elementals”=2 类; 971 “Your Lightfang Enforcers have all minion types”=全类型; 825 “Your Whelp Smugglers are Dragons”=**单类型**（严格说不是 RACES 模型缺口，而是缺“家族类型改写读取点”+载荷未注册）。**id 前缀订正（数据核实）**: 825 实为 `BG30_MagicItem_825`、179 实为 `BG32_MagicItem_179`（旧记前缀相反）。**载荷状态（2026-09-19 实测）**: `BGS_009`+金色 `TB_BaconUps_082` / `BG26_ICC_901`+金色 / `BG_LOE_077`+金色 **均已注册**; `BG21_013`/`_G`（Whelp Smuggler）**未注册**（旧记“载荷 dbf 72072 在本地数据不解析”**不成立**——dbf 72072 正是 `BG21_013`，缺的是脚本注册而非数据链）。**阻塞事实**: `.race` 为单值 `IntEnum`（`hsrl2/tags.py:41`）+ `Race.ALL`=“匹配一切”的既有语义; 改造面 **286 处 / 69 文件**（引擎 39 处/7 文件 + 脚本 247 处/62 文件，2026-09-19 实测 `grep -rn '\.race\b'`）；`Race.ALL` 现有消费方语义与新语义冲突。完整 `[AUTHORITY FOUND]`/`[NO AUTHORITY FOUND]` 清单与未来原语契约见下节。 |
| D | 子系统缺失 | 6 | 300 Craft / 707 Darkmoon / 994 Wheel / 812 Triple Prize / 820(Secrets) / 823(Timewarp) | M4 子系统排期 |
| E | 语义权威缺失 | 4 | 416 / 711 / 809 / 823(Wax Imprinter) | 查证；查无则维持 DEFERRED。~~933~~ 已解冻（batch_trinkets37, 2026-09-14） |
| F | 引擎原语缺失 | 1 | `BG36_MagicItem_373` Multilayered Shield（动态 `TAVERN_SPELL_EXTRA` 提供者 + "每个不同随从类型"增量口径无权威） | 921 Flagbearer / 923 Elementium Chest 等此前列于本行的卡**均已注册**（2026-09-13 复核）; 本行曾误列 `BG32_MagicItem_921`/`_922`/`_362`（数据不存在）→ 已按 `bg_trinkets.json` 逐 id 核实订正; ~~`BG35_MagicItem_922`~~ 已解冻（batch_trinkets38, 2026-09-17，7d 关闭）; ~~`BG36_MagicItem_362`~~ 已解冻（batch_trinkets31, 2026-09-18，§A11 通道落地） |

> 覆盖（**2026-09-21 实测复核**——`db.trinket_offer_pool()` × `REGISTRY`）:
> 饰品全域 **324/379**、商店可提供集 **316/331（95%）**，未注册可提供项
> **15 张**（418 / 825 / 971 / 179 由 `batch_family_races` 注册后由 19 降为 15）。
> 以下为 2026-09-19 的覆盖记录（保留追溯）: 饰品全域 **320/379**、商店可提供集 **312/331（94%）**，未注册可提供项
> **19 张**（逐 id 与 A–F 映射见下）。batch_trinkets31 作业范围内 41 张 =
> **8 CORRECT + 19 DEFERRED + 14 迁出**（923 Bewitched Ribbon / 362 Cyclist
> Portrait 于 2026-09-18 由该批注册——§A11 通道落地; **868 / 987 / 283 /
> 824 / 869 于 2026-09-19 由该批注册**——owner 权威序: wiki 卡页无 Notes →
> 卡面天然语言 + §7.4.16 `family_flags` / `hero.consume_policies`）;
> 14 迁出 =
> `BG30_MagicItem_440/804/822/821t2/828/944`、`BG32_MagicItem_274/803/804`
> （注意 `BG30_MagicItem_804` 与 `BG32_MagicItem_804` 是两张不同的卡）、
> `BG30_MagicItem_777`（batch_goose_lucky_egg）、`BG32_MagicItem_933`、
> `BG35_MagicItem_922`、`BG30_MagicItem_803`（Kaboom Bot Portrait,
> batch_trinkets39）、`BG32_MagicItem_820`（Impulsive Portrait,
> batch_trinkets39）。
>
> **19 张未注册可提供项的完整映射（2026-09-19 实测; batch_trinkets31
> 注册 A 组 5 张后）**:
> A 组 **0**（868 / 987 / 283 / 824 / 869 已全部闭环）;
> B 组 3 = 402 / 431 / 806（另 921 见 §B 行 7f）;
> C 组 **0**（418 / 825 / 971 / 179 已于 2026-09-21 由 `batch_family_races`
> 注册）; D 组 6 = 300 / 707 / 994 / 812 /
> 820(Safety Patch) / 823(Timeworn Candelabra); E 组 4 = 416 / 711 / 809 /
> 823(Wax Imprinter); F 组 1 = 373。合计 14 + 921 = 15。
>
> **分母口径澄清（2026-09-13 第十七轮实测）**: 379 = **331 张商店可提供项**
> （`db.trinket_offer_pool()`，spell_school 11/12）+ 48 张**非商店项**
> （46 张有同名本体的升级变体 `*t`/`*t2` + `BG30_Trinket_1st/2nd` 两张占位）。
> 非商店项不需要注册（由升级效果/商店占位内部处理），其存在仅使审计仪表的
> 分母偏大——读"320/379"时勿误读为"还剩 59 张"。

### C 组 `RACES` 多类型身份模型 —— 权威核查与未来契约（2026-09-19）

#### 2026-09-21 闭环（`batch_family_races` 注册 4/4）

**[AUTHORITY FOUND] 类型身份（wiki 详细说明，最高权威）**
- `Minion`（`https://hearthstone.wiki.gg/wiki/Minion`，revid **817925**）:
  “Minions in ''Hearthstone'' can have one or two of the following minion
  types”; “Previously, minions could only have one minion type … dual-type
  minions were introduced, allowing a minion to have two types. In any such
  case, these minions **benefit from the effects of both types**.”;
  “Alternatively, minions can either have all minion types listed above at
  once, or no minion types at all: [[All]] … These minions benefit from and
  are affected by every type effect in the game. [[General minion cards|
  General]] … These minions do not benefit from any specific type effects.”
- `Multi-type minion`（revid **855346**）: “Multi-types are always additions,
  never exclusions.”（Furious Felfin: “Murloc Warleader grants it +2 attack,
  and it can be drawn from Sense Demons.”）; “If needed, multi-type minions
  can take on the role of either minion type.”（N'Zoth 例）
- `All`（revid **893299**）: “All minions can be found from random effects and
  Discover options that cover any specific type.”; “All minions can have
  multiple type synergies for various types active at the same time.”;
  “An All minion will always count as a minion type the player hasn't played…”

**[AUTHORITY FOUND] 家族类型改写作用域（wiki 详细说明）**
- `Patch 30.2.0.205267`（revid **814123**，Smuggler Portrait 条目下的官方
  Dev Comment）: “This applies to Whelp Smugglers you see in the **Tavern or
  Discover** as well, not just the ones in your warband.”
- 418 / 179 / 971 与 825 同文本族（“Your X are …”），按同一 owner 作用域落地
  （wiki 仅对 825 有明文 Dev Comment——另三张为同文本族 + 卡面自然语言的
  延伸，逐卡 docstring 已记档）。

**实现（最小原语，沿用既有家族通道先例）**
- 表示: `CardDef.races`（`CARDRACE` ∪ per-race 布尔 tag，生成器新增
  `race_tags` 导出; AC-3）/ `GameTag.RACES`（实例身份集合，写入时展开
  `Race.ALL` → `STANDARD_RACES`，绝不含 ALL/NONE）/ `CardDef.subsets` 仍
  **不是**类型身份（AC-7）。
- 读取点: `Minion.races`（owner 视角: 棋盘/手牌/酒馆）+ `Minion.has_race`
  + `Game.add_family_races` / `family_races` / `effective_races`
  （家族类型改写，生命周期同 `add_family_flag`——source 离场即失效）。
- 改造消费者: 种族光环（`Entity._aura_atk/_aura_health` /
  `ApplyRaceAura`）/ 酒馆与发现候选（`MinionPool.candidates` /
  `_pool_candidates` + `effective_races`）/ 种族保证位
  （`refresh_tavern` 传 `race_of`）/ “of each type”
  （`_each_type_buffs` / Misplaced Tea Set / Motley Phalanx）/
  `_controlled_types` / 免费与生命购买限定 / `bc_race` 战吼配额 /
  元素打出计数 / 磁力宿主 / 吞噬恶魔 / 血宝石野猪人 / 战斗内龙族检查 /
  Whelp Smuggler 的 `stats_gained` 龙过滤。
- 逐卡（4/4 CORRECT）: 418 `{MURLOC, DRAGON}`（家族 `BG_LOE_077` + 金色
  `TB_BaconUps_045`）; 179 `{MECH, ELEMENTAL}`（`BG26_ICC_901`）;
  971 `ALL`（`BGS_009` + `TB_BaconUps_082`）; 825 `{DRAGON}`
  （`BG21_013` + `BG21_013_G`，交付副本 12/12）。测试
  `hsrl2/tests/test_batch_family_races.py`（42 项，含突变探针）。

**N1–N7 逐条裁定（wiki 权威 > 卡面自然语言）**
- N1 部分多类型计数: `|races|`（与标准 10 族取交集; NONE=0; ALL=10）——
  wiki “benefit from the effects of both types” + `All` 页 “every type
  effect”。`_type_association`（T6/T9 饰品关联阈值）**维持旧语义**
  （排除 ALL、按主类型计）——wiki 对 T6/T9 阈值无明文，不在本轮改动。
- N2 “of each type” 重复命中: 逐族资格 = `race in races`（双类型对两族均
  合格，可被两族各命中一次）——依据 wiki “take on the role of either
  minion type” + AC-6 ALL 先例（ALL 每族合格可重复命中）。**否决**“每只
  随从至多占一个类型槽”的读法（N'Zoth 例只说明双类型能填补槽位，未限定
  上限；ALL 先例明确允许多次）。
- N3 饰品类型关联: 无 wiki 明文 → 维持 DEFERRED（见上）。
- N4 酒馆/池可及性: 双类型只需**任一**类型在当局即可入池
  （`MinionPool._race_ok` 集合相交）——wiki “additions, never exclusions”。
  ALL/NONE 仍恒可用（旧语义逐点不变）。
- N5 家族类型光环作用域: **owner 视角**（棋盘/手牌/酒馆 + 发现候选），
  依据 825 官方 Dev Comment; 对手与共享池本体不受影响。**否决**“仅棋盘”
  与“全桌/池全局改写”。
- N6 表示契约: `Race.ALL` 保留为**规范哨兵**，读取时展开为
  `STANDARD_RACES` 集合; 实例身份存 `GameTag.RACES`（`RACE` 保留主类型
  兼容视图，写 `RACE` 同步重置身份集合）。
- N7 `BACON_SUBSET_*` ≠ 类型身份: 已由 `CardDef.races`（只读 `card_race`
  ∪ `race_tags`）与测试 `test_subsets_are_not_type_identity` 钉死。

**残留边界（精确记档，非静默）**
- 脚本层 `_pool_candidates(race=…)` 的约 40 处调用点未逐一改传
  `hero=`（引擎 Tavern / `Discover` / `GetRandomMinion` / Ysera 注入四处
  主路径已改）——这些是脚本自建随机获取，非 Tavern/Discover 正式入口;
  后续批次推进。
- 饰品**可提供性**（Drakkari revid 921179 “only appear in lobbies where
  Mechs or Elementals are present” / Enforcer revid 921181 “currently not
  available in games”）属商店池特性（`BACON_SUBSET_*`），与类型身份改写
  正交，未实现（不改全量饰品报价）。
- `darkgifts.most_common_board_race` 对 ALL 的 `AMBIGUOUS` 处理维持旧语义
  （wiki 对“众数类型”无明文）; 双类型现按 `races` 参与——若未来需要
  统一，须逐点给权威。

**核验方法**: 逐卡读 `data/bg_trinkets.json` / `data/bg_cards.json` 文本与数据 +
`hsdata/CardDefs.xml` 原始 tag（配 `hsdata/RaceTagMap.xml`）+ 全仓 `.race`
读取点（HEAD 实测：引擎 39 处 / 7 文件 + 脚本 247 处 / 62 文件 = **286 处 /
69 文件**，`grep -rn '\.race\b'`）。

**逐卡结论（家族类型数）**
- `BG30_MagicItem_418` Bronzebeard Portrait — “Your Brann Bronzebeards are
  both Murlocs and Dragons” → **2 类**（Murloc + Dragon）。
- `BG32_MagicItem_179` Drakkari Portrait — “Your Drakkari Enchanters are both
  Mechs and Elementals” → **2 类**（Mech + Elemental）。
- `BG30_MagicItem_971` Enforcer Portrait — “Your Lightfang Enforcers have all
  minion types” → **全类型**。
- `BG30_MagicItem_825` Smuggler Portrait — “Your Whelp Smugglers are Dragons”
  → **单类型**（不需要集合，需“家族类型改写读取点”）。**载荷本体亦阻塞**:
  `BG21_013`/`_G` 的效果 “Whenever a friendly Dragon gains Attack, give it
  +1 Health”（金色 +2，`num(0)`=1/2）缺“获得攻击力”观察点（下 N8）——
  故 825 的载荷不是“已可迁移、只差注册”，而是**效果本体无权威观察点**。
- `BG25_041`-class（既有双种族随从）: 成员集合由数据给出（下 AC-3）。

**[AUTHORITY FOUND]**
- **AC-1（家族类型数）**: 四张 Portrait 的家族类型数 = 卡面逐字——源
  `data/bg_trinkets.json`。
- **AC-2（载荷本体无种族）**: `BG_LOE_077` Brann / `BG21_013` Whelp
  Smuggler / `BGS_009` Lightfang Enforcer / `BG26_ICC_901` Drakkari
  Enchanter 四张载荷均**无类型**（无 enumID 200 `CARDRACE`、无 per-race
  布尔 tag）；金色 `TB_BaconUps_045` / `BG21_013_G` / `TB_BaconUps_082` /
  `BG26_ICC_901_G` 同——源 `CardDefs.xml`。
- **AC-3（既有双种族成员集合）**: 多类型身份在数据中由 **`CARDRACE` ∪
  per-race 布尔 tag**（`RaceTagMap.xml` enumID 2522–2556）表达；例
  `BG25_041` Felemental = ELEMENTAL（`CARDRACE=18`）+ DEMON（tag 2537），
  金色 `BG25_041_G` 同——源 `CardDefs.xml` + `RaceTagMap.xml`。当前池 247
  张随从中 **10 张双类型**（`BG27_005`/`BG28_633`/`BG31_330`/`BG32_820`/
  `BG32_821`/`BG34_500`/`BG36_760`/`BG36_763`/`BG36_764`/`BG_DEEP_015`）
  与 **4 张 `Race.ALL`**（`BG27_080`/`BG32_111`/`BG34_320`/`BG36_640`）。
- **AC-4（`Race.ALL` = 视为所有种族·匹配一切）**: 源 RULES §8（“全种族 |
  All | 视为所有种族”）+ §6.19（“光环种族为 ALL 时命中所有随从（含无类型
  `NONE`）”）；引擎 `game._gift_amalgamation` / `_notype_is_all` 同义。
- **AC-5（家族归一）**: 家族 = 基础 + 金色，经 `GameTag.TRIPLE_BASE_CARD_ID`
  回落——源 RULES §7.4.15 / §7.4.16 既有先例。
- **AC-6（“of each type” 下 ALL 型每族合格、可重复命中）**: 源
  `batch_spells3.MisplacedTeaSetScript` Evidence（r/BobsTavern 问句 + 官方
  同款文本族 The Last One Standing 34.6）——**但只覆盖 `Race.ALL` 哨兵，
  不外推部分集合**。
- **AC-7（`BACON_SUBSET_*` 不是类型身份）**: `BG21_013` Whelp Smuggler 有
  `subset_dragon=1` 却无 `CARDRACE`、无 DRAGON tag（2523）→ 它无类型；
  不得用 `CardDef.subsets` 充当 `races`——源 `CardDefs.xml` + RULES §7.4.2
  （subset = 饰品的“关联随从类型”，用途不同）。

**[NO AUTHORITY FOUND]（任一条未定即不得动全仓读取点）**
- **N1 部分多类型计数**: Mech+Elemental 随从在“每个不同随从类型”里算 **1
  类还是 2 类**——无官方源；且仓内三个既有口径**互相冲突**:
  (a) 引擎 `Game._type_association`（`game.py:3928`）**排除** `Race.ALL`
  → 贡献 0 类；
  (b) 脚本 `_controlled_types`（`batch_trinkets3`）/ `_controlled_races`
  （`batch_trinkets5`）令 `Race.ALL` **贡献全部 10 类**（自述“官方 All 型
  规则”，但只援引“同款裁定”，无直接信源）；
  (c) `darkgifts.most_common_board_race`（`darkgifts.py:418-420`）把
  `Race.ALL` 明标 **AMBIGUOUS**（“官方未说明”）而不计。
- **N2 部分多类型在 “of each type” 中的命中次数**: 双类型随从能否被 Mech
  与 Elemental 两次独立选中（双份 buff）——AC-6 的先例不能外推（ALL 是
  哨兵，不是集合语义）。
- **N3 饰品类型关联**（RULES §7.4.2 的 T6/T9/Menagerie）: 双类型 / `ALL`
  型随从对“2 个 / 3 个某类型”的贡献未定（现 `_type_association` 直接
  排除 `ALL`，与 (b) 冲突）。
- **N4 酒馆种族过滤 / 池可及性**: 当局只启用 Mech 时，Mech+Elemental 随从
  是否入池/可抽——无源（现 `MinionPool._race_ok` / `discover._pool_candidates`
  只看单值）。
- **N5 家族类型光环的作用域**: “Your X are Dragons / have all minion types”
  是否覆盖手牌/酒馆/池/生成物（与 §6.19 数值光环的 scope 未决问题同族）。
- **N6 表示契约**: `Race.ALL` 哨兵 vs 满 10 元集合的等价性；`GameTag.RACES`
  是新 tag 还是迁移 `RACE`；`card_race` 是否“主类型”；生成器是否导出
  per-race tag（**当前不导出**，只导出 `BACON_SUBSET_*`）。
- **N7 `BACON_SUBSET_*` ≠ 类型身份**需写入数据契约（AC-7 反例），防止
  未来把 `CardDef.subsets` 误当 `races`。
- **N8 “获得攻击力”观察点（`BG21_013` Whelp Smuggler 效果 / 825 载荷）**:
  ✅ **已闭合（2026-09-20）**。原决策证据包见下 §E（2026-09-19: 权威检索 +
  15 条生产路径盘点 + 一步授权契约）; 触发域按项目所有者权威序（wiki 详细
  说明 > 卡面自然语言解读）钉死于 §E4，原语 `stats_gained` 已落地
  （`hsrl2/events.py::STATS_GAINED`，生产点 `Entity.add_buff`，复制/复原
  经抑制，来源经 `game._action_source`），`BG21_013`/`_G` 已注册
  （`batch_stats_gained`）。825 的残余阻塞**只剩**第 2、3 条（单值家族
  种族覆写读取点 + 作用域 N5）。
  （以下为 2026-09-19 原始记录，保留以追溯）卡面
  “Whenever a friendly Dragon gains Attack, give it +1 Health”（金色
  +2，数据 `num(0)`=1/2）需要一个**逐次“获得攻击力”事件**。引擎现状:
  `hsrl2/events.py` 无 `stats_gained`（旧 `QUEST_DEFERRED_SPEC` #123 / 本表
  #29(d) 曾列为**待新增**，生产点 `Buff.do`; **2026-09-18 订正**: 任务 123
  Find the Murder Weapon 已改用 `buff_applied` + `temporary` 过滤落地，其
  计数边界显式记档于 `docs/agents/QUEST_DEFERRED_SPEC.md` §3.1 第 2 条）;
  唯一相关的
  `buff_applied`（`Entity.add_buff` fire）是实体内部附魔应用钩子——在
  `copy_buffs_to`（复制/三连 `_combine`）与快照重放路径上**同样触发**，
  没有 source/permanence 契约，**不得**当作“获得攻击力”事件顶替。
  另有两类攻击力提升**不经** `add_buff` 且无事件: `BASE_ATK` 覆盖式设定
  （`batch_spells2.SetStats` 家族）与读取时计算的光环
  （`Entity._aura_atk` 的 race/tier/card 光环、脚本 `atk` 钩子）。
  **[NO AUTHORITY FOUND: 触发域]**（2026-09-19 记录，**已被 §E4 取代**）
  哪些路径计入“获得攻击力”、每次事件
  如何计数（每附魔 1 次 / 每来源 1 次 / 按增量）、是否含战斗内临时增益，
  均无卡面/数据/规则权威; 当时全仓 0 张 “gains Attack” 卡已注册（`BG21_013`/
  `BG21_018`/`BG25_027`/`BG26_966`/`BG31_820`/`BG34_Giant_064`/
  `TB_BaconShop_HERO_52_Buddy` 基础+金色全部不在 REGISTRY）→ 无实现先例。
  解除（**已完成 2026-09-20**）: 落地 `stats_gained` 并钉死上述触发域契约后，
  `BG21_013`/`_G` 迁移（连带 825 的载荷面）。

**未来决定必须钉死的原语契约（decision checklist）**
1. **表示**: `CardDef.races` 集合 = `CARDRACE` ∪ per-race tags
   （`RaceTagMap.xml` 2522–2556）；实例 `GameTag.RACES`（位掩码/集合）；
   `Race.ALL` 保留为“全 10 类”的规范表示还是展开为集合。
2. **匹配点**: 所有 `r == want or r == ALL` → `want in races`（语义保持:
   `ALL` ≡ 全标准种族，含旧特例“ALL 命中 `NONE`”）。
3. **计数点**: `|races|` 的精确定义（与标准 10 族取交集；`NONE`=0；`ALL`=10
   或 1）——须统一 `_type_association` / `_controlled_types` /
   `darkgifts.most_common_board_race` 三处，并逐处给出权威或**显式记为
   引擎契约**。
4. **选取点**: “of each type” 的资格与重复命中规则（部分多类型的外推）。
5. **过滤点**: 池 / 酒馆 / discover 的 `races ∩ active_races ≠ ∅` 规则。
6. **光环点**: 家族类型光环（`hero.family_flags` 家族行为通道的候选承载）
   的作用域（棋盘 vs 处处）。
7. **回归**: 既有 `Race.ALL` 消费方（引擎 39 处 + 既有 ALL 卡
   `BG27_080`/`BG32_111`/`BG34_320`/`BG36_640` 等）语义逐点不变。

## D. 第六件验收工具（运行期覆盖率，2026-09-02）

`tools/audit_script_runtime_coverage.py`（报告型 + 批次级 `--strict` 门禁）:
跑 N 局随机对局并追踪 `Entity.call_script`/`Game.play_minion|play_spell`/
`Game.grant_trinket`，报告:
1. **"进入过棋盘/被绑定但钩子零触发"** —— 真·疑似条件永不成立（当前实测 **0**）
2. 从未触发的脚本类（含稀有卡，仅报告）
3. 批次级零触发（有卡被打出但整批零钩子）→ `--strict` 失败条件（当前 **0**）

用途: 五件套全绿仍可能漏"接线存在但实际从不触发"的脚本；本工具是这条
风险面的运行期补充（与 `audit_script_wiring` 静态检查互补）。

## C. 留档待权威（AMBIGUOUS，不得据此改动）

1. **"Get N random（无 different）"是否允许重复**（RULES §7.4.8）：当前全仓按"互异"
   实现（`rng.sample`）。`BG32_MagicItem_282` 显式写 "different" 可能暗示无该词时
   允许重复。涉及 `BG30_MagicItem_942`、`BG28_606`（Spitescale Special）。
2. **"The Tavern always has N cards" = 随从位 vs 总牌数**（RULES §7.4.8）：
   当前实现为 N 个随从位（Glowing Gauntlet / Felbat Portrait / 异变 Seven Cards）。
3. 7 条第六–七轮 AMBIGUOUS（Nozdormu 免费刷新累积、Finley 候选池、Sulfuras
   单体双端、Chenvaala 折扣跨升级、Voone/Rakanishu 周期口径、Young Murk-Eye
   单随从去重、Water Wheel 空池仍消耗额度）见对应 batch docstring。

## E. `stats_gained`（"获得 Attack/Health/stats"）观察点 —— 决策证据包

> **状态（2026-09-20 更新）**: **已落地**。E1–E3 仍为 2026-09-19 的原始
> 证据包（权威检索 + 15 条生产路径盘点 + 16 实体清单）; 触发域阻塞已由
> **项目所有者权威序（wiki 详细说明 > 卡面自然语言解读）** 解除 →
> **E4 给出最终逐路径裁定 + 逐卡结果**（12 注册 / 4 DEFERRED），E5 为本轮
> 验证。原始结论（"[NO AUTHORITY FOUND: 触发域]，16 张卡维持 DEFERRED"）
> 已被 E4 取代，保留于下行以供追溯。
>
> **原结论（2026-09-19，已被取代）**: 冻结权威（`BATTLEGROUNDS_RULES.md`
> / `MECHANICS_REFERENCE.md`）对"何时算获得攻击力/属性"**无任何定义**；
> 现行 `hsrl2` 注册表（REGISTRY）**零**张卡消费该语义。

### E1. 权威检索（逐字引用 / 缺席证据）

**检索方式**: 两份权威文档全文逐行读取 + 关键词计数
（`stats_gained` / `gain Attack` / `gains Attack` / `获得攻击力` / `获得攻击` /
`属性变动` / `属性变化` / `攻击力提高` / `攻击力增加` / `增益事件` 在两文档
**合计出现 0 次**；唯一命中的 `获得属性` 是 RULES §6.16 对 Rally 效果的
泛枚举，非触发域定义）。

**唯一相关且已冻结的条款（覆盖的是别的维度，不覆盖"获得"的触发域）**

| 维度 | 出处 | 原文（逐字） | 对本原语的作用 |
|---|---|---|---|
| 增减的**永久性** | RULES §3.5:197-198 | "**招募阶段Buff**（通过战吼、回合结束效果等获得）是**永久**的" / "**战斗阶段Buff**（如战斗中触发的增益）在战斗结束后**消失**" | 只钉死 `permanent` 字段，不钉死"哪些路径触发" |
| "增益"的**存在形式** | RULES §6.14:538 | "吸附后，两个随从的**攻击力和生命值相加**，效果合并。" | 磁力确实"获得"，但无事件/触发语义 |
| 光环是**读时**机制 | RULES §6.19:572-577 | "`hero.race_auras` … 对**棋盘 + 手牌 + 之后获得的**全部匹配随从**实时**生效 … （`Minion._aura_atk` / `_aura_health`）" | 明确光环=实时计算，**无**"获得时刻"，是否计入仍无权威 |
| "give" ≠ "gain" | RULES §7.4.6c:976-979 | "**裁定（"give" vs "gain"）**: 文本是 "Your Elementals that **give** stats grant an extra +X/+Y" → **自增益**（"gain"）不算给予" | 承认 gain 是独立概念，但只用于元素加成，**不**定义其事件域 |
| 三连**保留**增益 | RULES §10.1:1624 / §10.2:1629 | "金色随从保留所有三个原始随从身上的**增益和状态**。" / "基础**攻击力和生命值翻倍**。" | 三连是"合并/保留"，非"获得"——但无明文排除 |
| 旧引擎事件表 | MECHANICS_REFERENCE §4.2:241 | "\| `BUFF` \| 增益 \| target, atk, health \|" | **旧引擎**（`hsrl/core/`）实现参考，非卡牌规则权威 |

**旧引擎先例（不构成现行权威）**: `hsrl/core/actions.py:294` 的 `Buff.do` 广播
`BUFF(target, atk, health)`；旧卡 `hsrl/cards/minions/scripts.py:5210`
`DefiantShipwrightScript`（= `BG21_018`）与 `:3510` `ScarletSurvivorScript`
消费它。**不能援引**，理由三条: (a) `hsrl/` 最后提交 2026-06-04、已被
`hsrl2/` 取代，权威文档只引用 `hsrl2/`； (b) 旧 `BUFF` 只在 `Buff` Action
触发，旧三连 `hsrl/core/game.py:781/_combine_triple`（`:822 golden.add_buff`）
直调附魔**不广播** → 旧域 = "显式 Buff Action"，不含磁力 / `SetStats` /
光环 / 脚本直调； (c) `DefiantShipwrightScript` 用"当前 atk − 缓存 base"的
差分近似，与卡面定值 `{1}` 不一致，本身即是近似。→ 旧先例**无法**钉死触发域。

### E2. 生产路径盘点（`hsrl2`，attack 增加的全部引擎级入口）

| # | 路径 | 代码位置 | 今日事件 | 代表生产者 | 16 卡是否可能计入 |
|---|---|---|---|---|---|
| 1 | 永久附魔 `Entity.add_buff` | `entity.py:276-300`（fire 在 `:299`） | `buff_applied(target=, buff=)` | 绝大多数 "+X/+Y" 卡 | **可能**（唯一候选生产点） |
| 2 | 附魔 Action `Buff.do` | `actions/stats.py:40-44` | 经 #1 | 脚本队列入队的标准路径 | 可能 |
| 3 | TavernBuff 入馆 | `actions/tavern_buff.py:118` / `game.py:635` | 经 #1 | Defiler Portrait 族 | 可能（属"获得"） |
| 4 | 复制 `copy_buffs_to` | `entity.py:302-315`（`:311` 逐份 `add_buff`） | 经 #1（每份 1 次） | "exact copy" 族 / 三连 | **必须排除**（非获得） |
| 5 | 三连 `_combine` | `game.py:1133-1183`（`:1146` 复制） | 经 #4 → #1 | 三连金色 | **必须排除**（非获得） |
| 6 | 战斗快照恢复/重放 | `game.py:3071 / 3093 / 3106 / 3114-3122`；`minion.py:144`；`game.py:88` | #1（部分）+ **`dmg_deltas` 直插 `_buffs` 无事件** | Tarecgosa / Bewitched Ribbon / Poet | **必须排除**（复原非获得） |
| 7 | 磁力吸附 | `game.py:1325-1329`（BASE_ATK/BASE_HEALTH 相加） | 仅 `magnetized` | Magnetic 族 | 未定（文本"相加"= 无声获得） |
| 8 | `SetStats` 覆盖 | `batch_spells2.py:466-490`（`batch_trinkets14:237` 同构） | 无 | Perfect Vision / Innkeeper's Hearth | 未定（覆盖可增可减） |
| 9 | 脚本直写 `BASE_ATK` | 全仓 `set(GameTag.BASE_ATK` **17 处**（15 处脚本 + `minion.py:20` 初值 + `game.py:1325` 磁力，后者即 #7） | 无 | 召唤 token / 快照复原 / 属性覆盖 | 未定 |
| 10 | `Transform`（buff 整体转移） | `actions/stats.py:109-141`（`:122-123`） | `transform`（非 stats） | Yu'lon / 临时金 | 未定（`_buffs` 未走 `add_buff`） |
| 11 | 计算式光环（读时） | `entity.py:129-152 / 208-212`；`racefx.py:31-57`（`:57`）；`game.py:3551-3577` / `3862-3889` | 无（health 侧直 `set(HEALTH)`） | Feral Talisman / Horde Keychain / 家族光环 | 未定（无写点） |
| 12 | 脚本 `atk`/`health` 动态钩子 | `entity.py:119-127 / 220-227` | 无 | Falling Sky Golem 族 | 未定（读时覆盖） |
| 13 | Dark Gift 附魔 | `game.py:4209-4538` | 经 #1 | 暗月赠礼 | 可能 |
| 14 | 血宝石移转 | `actions/bloodgem.py:286-298`（`:292` 直插） | 无 | Gem Confiscation | 未定（直插 `_buffs`） |
| 15 | 治疗 / HEALTH 直改 | `entity.py:268-272`；`game.py:3577 / 3888` | 无 | 光环同步 / 治疗 | 仅影响 Health 族（另案） |

**关键事实**: 若把 `stats_gained` 放在 #1（`add_buff`），则 #4/#5/#6 会**重复
触发**（副本/三连/战后重放各 1 次 → 结构性推断为 2–4 倍计；**未做变异实测**），
#7–#12 完全不触发
（这些路径不经 `add_buff`）。这正是 `buff_applied` 不能顶替的原因（#4/#5/#6
与 #1 同源）。`ENCHANT_IMMUNE`（Fishbait "This can't gain stats"）已在
`entity.py:287-289` 拒绝正值附魔 → #1 天然不入事件（消费者无须自判）。

### E3. 目标卡表（16 实体 = 8 基础 + 8 金色；全部未注册）

| id（基础 / 金色） | 文本要点 | 数据参数 | 观察者角色 | 今日可达性 |
|---|---|---|---|---|
| `BG21_013`/`_G` Whelp Smuggler | "Whenever a friendly **Dragon** gains Attack, give it +1/2 Health" | `num(0)`=1/2 | 外部（种族） | **经 `BG30_MagicItem_825` 载荷**（825 未注册，另阻塞于家族单值类型改写 N5） |
| `BG21_018`/`_G` Defiant Shipwright | "Whenever this gains Attack **from other sources**, gain +{1} Health"（金"twice"） | `num(1)`=1/1 | 自身（需 source 排除自身） | 非池 / 无饰品链 |
| `BG25_027`/`_G` Hunter of Gatherers | "Whenever this gains Attack, give your minions +2/4 Health" | 文本字面量 | 自身 | 非池 |
| `BG26_966`/`_G` Stormbringer | "After a different friendly Dragon gains Attack, this **also gains it**"（金"twice"） | 无 | 外部 + **数值拷贝** | 非池 |
| `BG31_820`/`_G` Spacefarer | "Whenever **another** friendly Pirate gains Attack, gain +2/4 Health" | 无 | 外部 | 非池 |
| `BG34_Giant_064`/`_G` Timewarped Whelp Smuggler | "Whenever a friendly **minion** gains Attack, give it +{1} Health" | `num(1)`=3/6 | 外部（全种族） | Timewarped（非当前池 / 无饰品链） |
| `TB_BaconShop_HERO_52_Buddy`/`_G` Sinestra | "Whenever a friendly minion gains Attack **during combat**, give it +1/2 Health **permanently**" | 无 | 外部 + 战斗内 + 永久 | Buddy 子系统未实现（#24） |
| `BG34_111`/`_G` Sepulchral Sergeant | "Deathrattle: … **Improves permanently after this gains Attack!**" | `num(0)`=2/4 | 自身计数器（improve） | 非池 |

**当前实际影响面 = 1 条链**: 只有 `BG21_013`/`_G` 有饰品载荷链（825），而 825
本身还被 N5（家族单值类型改写）阻塞 → 本原语当前**不阻塞任何可注册卡**，
但其影响面在解锁 825 后立即出现。

**同原语的更大家族（本契约须前向兼容，非本 16 卡）**: 按"文本观察具名属性"
（正则 `gains\s+(Attack|Health|stats)`，基础卡口径）统计 = **18 张 / 17 张
未注册**（唯一已注册的 `BG31_889` Sharing is Caring 是**生产**增益而非消费）。
其中 "gains **stats**" = `BG21_036` Master of Realities / `BG29_889` 'Loc Prince
（"add +2/+1 **to that amount**"）/ `BG32_335` Murkbrine Expeditioner /
`BG34_Giant_317` Timewarped Expeditioner / `BG34_Giant_801` Timewarped Astrogill /
`TB_BaconShop_HERO_29_Buddy` Tentacle of C'Thun / `TB_BaconShop_HERO_33_Buddy`
Mishmash；"gains **Health**" = `BG33_920` Wrathscale Rogue /
`TB_BaconShop_HERO_39_Buddy` Titanic Guardian。另有更宽的自增益族
（"gain +X/+Y" 类，正则 `gains?\s+(Attack|Health|stats|\+\d)` = 基础卡 81 张）
**不**需要该观察点——它们是增益**生产方**。"can't gain stats" = `BG36_205`
Fishbait（已由 `ENCHANT_IMMUNE` 处理）。

### E4. 最终裁定（2026-09-20 落地轮）—— 触发域 + 逐卡结果

> **前提变更**: 项目所有者权威序（wiki 详细说明 > 卡面自然语言解读）取代了
> 旧的 "NO AUTHORITY FOUND" 阻塞。E1 的检索结论**仍然成立**（冻结规则 +
> 8 张卡页均无 Notes/正文），但按自然语言解读 + 引擎自身语义，触发域可以
> 钉死——**"X gains Attack" = X 的攻击力上升**。

#### D1 计入路径白/黑名单（最终）

| §E2 路径 | 裁定 | 理由 |
|---|---|---|
| #1 `Entity.add_buff` / #2 `Buff` Action / #3 持久酒馆 buff 入馆 / #13 Dark Gift | **计入** | 附魔真正施加于实体 = 属性上升的唯一真实"获得"时刻。唯一生产点（`entity.py::add_buff` 尾广播 `stats_gained`）。ENCHANT_IMMUNE 已在 `add_buff` 提前拒绝 → 天然不入事件（A6）。 |
| #7 磁力相加 | **不计** | "吸附后两个随从的攻击力和生命值**相加**"（RULES §6.14:538）实现为 `host.BASE_ATK += magnetic_minion.atk`（`game.py:1394`）——**不经 `add_buff`**，且是"效果合并/位置并入"而非"获得"（被吸附实体离场）。自然语言读法下不构成"该随从获得攻击力"的独立获得时刻。被否决的替代: 计入（文本"相加"可读作获得）——否决理由: 引擎无附魔、无来源、且磁力随从**离场**，计入会让"获得"同时发生在两个实体上（双计）。 |
| #8 `SetStats` 覆盖 | **不计** | 文本是 "**Set** a minion's stats to X/Y"（覆盖），语义是"变为"而不是"获得"；且覆盖可增可减（`SetStats` 清空附魔后写 BASE）。被否决的替代: 净增才计（`new > old`）——否决理由: 卡面明写 set，把它读成 gain 会让"set 到更高值"成为隐式获得，且引擎无附魔事件可挂。 |
| #9 脚本直写 `BASE_ATK` | **不计** | 与 #8 同类（覆盖/初始化）。全仓 15 处脚本写点均为**建 token 初值**或**快照复原**（`batch_deathrattle.SummonTokenSetStats` / `batch_unlock_final` 复原 / `batch_trinkets15` 覆盖），没有"增量获得"语义。 |
| #10 `Transform`（`_buffs` 整体转移） | **不计** | `keep_buffs=True` 直接 `new._buffs = list(target._buffs)`（`actions/stats.py:122`）——**不经 `add_buff`**、无事件；语义是"同一批附魔换了宿主"（位置搬移），不是新实体"获得"。被否决的替代: 计入（新实体确实数值更高）——否决理由: 数值升高来自身份变更而非获得，且原实体离场。 |
| #11 计算式光环（`race_auras` / `card_auras` / `tier_auras`） | **不计** | 读时计算，无"获得时刻"（RULES §6.19:572-577 明写"实时生效"）。被否决的替代: D6 的"每回合差分快照"（旧引擎 Defiant Shipwright 的近似做法）——否决理由: (a) 差分无法区分光环消失/重现与真实获得，会重复触发；(b) 差分窗口（何时拍快照）无权威；(c) 旧引擎先例本身是近似（E1 末段三条理由），且已注明"不能援引"。 |
| #12 脚本 `atk`/`health` 动态钩子 | **不计** | 同 #11（读时覆盖返回值，`entity.py:119-127`：`atk_fn` 返回 int 直接覆盖）。 |
| #14 血宝石移转（直插 `_buffs`） | **不计** | `actions/bloodgem.py:291-292` 把血宝石 buff 从 victim **移转**给 recipient（直插 `_buffs`，不经 `add_buff`）。移转 = 位置搬移，不是获得。被否决的替代: recipient 计入——否决理由: 同一份 buff 会在移出/移入两侧各产生一次"属性变化"，计入违反唯一真实获得点；victim 的下降也不是"获得"。 |
| #15 治疗 / HEALTH 直改 | **不计** | 治疗只改 `HEALTH`（当前血），不改 `max_health`；"gains Health" 指的是生命值上限增益（add_buff 路径）。且攻击力家族不受影响。 |

#### D2 必须排除的"非获得"路径（最终）—— 已实现抑制

| 路径 | 抑制机制 | 语义 |
|---|---|---|
| #4 `copy_buffs_to`（副本 / 精确复制） | `with suppress_stats_gained():`（`entity.py::copy_buffs_to`） | 复制 = 把已存在的属性复制一份，**不是**"获得" |
| #4b 手动复制循环（快照复原副本 / SirensSong 手牌副本） | 同 #4 的 `suppress_stats_gained()` 窗口（`batch_trinkets32._restore_from_snapshot`、`batch_misc.SirensSongSpellScript.on_play`） | 逐 buff `add_buff` 的手动复制与 #4 同语义（2026-09-20 审计补齐; 此前漏抑制） |
| #5 三连 `_combine`（经 #4） | 同 #4（`game.py:1206` 调 `m.copy_buffs_to(golden)`） | RULES §10.1:1624 "金色随从**保留**所有三个原始随从身上的增益"——"保留"不是"获得" |
| #6 战斗快照复原重放（persist / Poet / dmg_delta 三通道） | `game._restore_no_gain = True`（`run_combat` finally 的 try/finally 包围整段恢复） | 复原 = 把战斗中已"获得过一次"的属性装回实体；`dmg_deltas` 通道本就直插 `_buffs` 不经 `add_buff` |

**实测（2026-09-20 对抗验证复测）**: 未抑制时三连多触发 1 次、战后复原重放多触发 1 次、副本重放（#4b）触发监听器（实测副本 5/5 → 5/8）。
**#6 复原点可达、非等价变异**（旧记"不可达/等价变异"**已撤回**）: 真路径 =
Bewitched Ribbon `BG35_MagicItem_923` 经 `spell_resolving` 给己方随从
`Buff(persist=True)` + Tide Raiser `BG34_920` 亡语**战内**施法 +
`BG34_Giant_064` 监听器 → 抑制时 6 次广播、去抑制 7 次。原因: 战内授予的
persist 附魔**不在战斗起始快照**里，`persist_buffs` 的**对象身份去重**不
跳过它 → 战后经 `m.add_buff(b)` 重放并广播。回归 =
`TestTriggerDomain::test_combat_incombat_persist_replay_does_not_rebroadcast`（M5 探针已杀死）。

#### D3 计数粒度与载荷（最终）

每次**附魔施加** 1 次事件，载荷携带**增量值**（`atk` / `health`）——不是"每次来源 1 次"，也不只给计数。`BG26_966`（"also gains it" = 获得**同样的攻击增量**）与 `'Loc Prince`（"add +2/+1 to that amount"）都要求数值，故载荷必须带 delta。

#### D4 增量正负/零（最终）

只有**正向**才算"获得"（`atk > 0` / `health > 0`）；负向 = 下降、零 = 无事发生。原语**不**替消费者过滤（载荷原样给出 `atk`/`health`，消费者自行只认 `> 0`），因为"gains stats"家族要同时看两轴。

#### D5 临时性（最终）

`permanent = not buff.temporary`（A4 既有裁定）。**临时增益同样触发**：卡面文本是"获得攻击力"，未限定永久；战斗内 `add_buff` 照常广播（`Sinestra` 的 "during combat" 用 `game.in_combat` 自行过滤）。被否决的替代: 只计永久——否决理由: 无权威支持，且会让战斗内"获得攻击力"的明确文本（Sinestra）无法实现。

#### D6 光环与动态钩子（最终）

**完全不计**（见 D1 #11/#12）。理由同上（无获得时刻 = 无事件；差分近似被否决）。

#### D7 `source` 载荷（最终）—— 已实现

`stats_gained.source` = 触发本次附魔的**来源实体**：
1. 动作**显式声明**的 `source`（`Buff(source=...)`）优先；
2. 否则**继承调用方作用域**——`Game.run_script_hook` 把正在执行钩子的实体置为
   `game._action_source`，`ActionQueue.resolve` 在动作未声明 source 时继承；
   **逐动作复位**（2026-09-20 修复）: 循环每次迭代先把 `_action_source`
   复位为 resolve 入口记录的 `prev_source` 再套用本动作的显式 source——
   否则未声明来源的动作会继承**上一个动作**的 source（实测
   `[Buff(dummy, source=ship), Buff(ship)]` 的第二个被误归属给 `ship`）；
3. 两者皆无 → `None`（**来源不明，不臆造**）。

判据: `BG21_018` "from other sources" / `BG31_820` "another friendly Pirate" /
`BG26_966` "a different friendly Dragon" 都要求排除**本体**；`source is None`
时**不排除**（"其他来源"只排除"自身"这一确定情形）。同时保留
`source_id`（附魔携带的来源卡 id，审计/家族标识）。

回归: `TestPrimitiveContract::test_action_source_does_not_leak_between_actions`
（M9 探针已杀死）。

#### D8 战斗边界（最终）

进入/离开战斗时光环消失/恢复**不触发**（#11 不计，且复原被抑制）。战斗内
真实 `add_buff` **触发**（`game.in_combat` 可判）；"permanently" 的跨战斗保留
由消费者用 `Buff(persist=True)` 表达（§3.5 例外 4 通道）。

#### D9 "friendly" 的区界（最终）—— 棋盘限定

`batch_stats_gained._friendly(holder, minion)` = 同一控制者 **且
`minion.zone is Zone.PLAY`**。卡面 "friendly [X]"/"your minions" 在战棋触发
语境下 = 己方**棋盘**随从; **酒馆**（`Zone.TAVERN`）随从属于 Bob、**手牌**
（`Zone.HAND`）不是棋盘随从 → 上游事件来自这两区时不触发本族监听器。
2026-09-20 对抗验证实测旧实现（只查 `controller`）: 一只酒馆龙被
`TavernBuff` 加攻即触发棋盘上的 Whelp Smuggler 并给酒馆随从加生命 = 错误。
回归: `TestTriggerDomain::test_tavern_minion_gain_does_not_trigger`（M6 探针已杀死）。
**边界记录**: `batch_quests._friendly`（同款控制器判定）**未**加
`Zone.PLAY`——其事件域（任务计分事件）的实体已由各事件生产点限定，本轮
不改动以避免超范围行为变更（共享助手分歧在此显式记录）。

#### E4b 逐卡结果（16 实体）

| id（基础/金色） | 文本要点 | 数值（本轮实测 `num()`） | 权威 | 结果 |
|---|---|---|---|---|
| `BG21_013`/`_G` Whelp Smuggler | friendly **Dragon** gains Attack → give **it** +N Health | `num(0)`=1/2 | 卡页 revid=907222（无 Notes）+ 自然语言 | **REGISTERED** |
| `BG21_018`/`_G` Defiant Shipwright | this gains Attack **from other sources** → gain +N Health（金 twice） | `num(1)`=1/1（金靠 "twice"） | 卡页 revid=800837（无 Notes）+ 自然语言; 金 "twice" = Patch 34.6.0.235290 revid=904455 Dev Note | **REGISTERED** |
| `BG25_027`/`_G` Hunter of Gatherers | this gains Attack → give your minions +N Health（**含自身**） | 字面量 2/4（num 全 None） | **官方 Blizzard 31.4.2 patch notes + 卡页 revid=884903 + 本地 CardDefs 36.2.2（13 语言）一致 = "your minions"（无 "other"）**; 见下"权威复核" | **REGISTERED**（**2026-09-20 纠错：此前误按 "other" 实现**） |
| `BG26_966`/`_G` Stormbringer | **a different** friendly Dragon gains Attack → this **also gains it**（金 twice） | 数值 = 事件增量 | 卡页 revid=804846（无 Notes）+ 自然语言; 金 twice = Patch 26.2.0.174258 | **REGISTERED** |
| `BG31_820`/`_G` Spacefarer | **another** friendly Pirate gains Attack → gain +N Health | 字面量 2/4 | 卡页 revid=830430（无 Notes）+ 自然语言 | **REGISTERED** |
| `BG34_Giant_064`/`_G` Timewarped Whelp Smuggler | friendly **minion** gains Attack → give it +N Health | `num(1)`=3/6 | 卡页 revid=883775（无 Notes）+ Patch 34.4.2.234747 revid=901476（"+2 → +3"） | **REGISTERED** |
| `BG34_111`/`_G` Sepulchral Sergeant | Deathrattle: give your other minions +N Health（**Improves permanently after this gains Attack!**） | `num(0)`=2/4; **提升量无参数** | 卡页 revid=883820（无 Notes）; 提升增量无权威 | **DEFERRED**（"提升多少"无权威 → 禁近似） |
| `TB_BaconShop_HERO_52_Buddy`/`_G` Sinestra | friendly minion gains Attack **during combat** → +N Health **permanently** | 字面量 1/2 | 卡页 revid=907187（无 Notes）+ Patch 29.6.0.201108 | **DEFERRED**（Buddy 子系统未实现 → 实体不可达） |

**BG25_027 权威复核（2026-09-20 对抗验证纠错——取代旧"数据陈旧"结论）**:
上一轮（`f0426d5`）把本卡实现为 "your **other** minions"（排除自身），
理由"本地数据陈旧"**不成立**。四条权威证据:
1. **官方 Blizzard 31.4.2 patch notes**（
   https://hearthstone.blizzard.com/en-us/news/24173976/31-4-2-patch-notes）
   逐字: "Hunter of Gatherers * Old: [Tier 4] 3/6. Whenever this gains
   Attack, give your minions +1 Health. * **New: [Tier 5] 3/5. Whenever
   this gains Attack, give your minions +2 Health.**"（**无 "other"**）。
2. **wiki 卡页 `Battlegrounds/Hunter of Gatherers` revid=884903**
   （pageid=80454; wikitext 仅 `{{Card template v2}}`，正文由 dbfId=95293
   拉取）渲染: Regular "…give your minions +2 Health." / Golden
   "…give your minions +4 Health."; Patch changes 段同引 31.4.2.216149
   "give your minions +2 Health"（无 "other"）。
3. **本地 `hsdata/CardDefs.xml`**（build **249896 = 36.2.2，晚于 31.4.2**）
   enUS "…give your minions +2 Health."; **13 语言全无 "other"**。
4. **唯一反证**: wiki patch 文章 `Patch 31.4.2.216149` **revid=892585** 写
   "give your **other** minions +2 Health" —— 与官方原文 + 卡页 + 全部数据
   矛盾，判定为**该 wiki 文章的孤立笔误（outlier）**。旧实现 "other" 即源自
   此孤立行；已纠正为 "your minions"（**含自身**）。数值不变（2/4）。
   回归: `TestHunterOfGatherers::test_gain_buffs_all_minions_including_self`
   （旧用例 `test_gain_buffs_other_minions_not_self` 固化错误行为，已改写;
   M7 探针已杀死）。

**wiki 金色文本 vs 本地数据（实现一律取数据——显式记录）**:
- `BG21_018_G` Defiant Shipwright: wiki 金色 "Whenever this gains Attack,
  gain +2 Health."（**丢 "from other sources"**、写作一次 +2）vs 本地数据
  "…**from other sources**, gain +{1} Health **twice**."（`num(1)`=1）→
  实现取数据（保留排除 + 两次独立 +1）。
- `BG34_Giant_064_G` Timewarped Whelp Smuggler: wiki 金色 "give it **+2**
  Health." vs 本地数据模板 `{1}` + `script_data_num_2`=**6**（卡页 fullTags
  亦为 6）→ 实现取数据（一次 +6）。
- `BG34_111_G` Sepulchral Sergeant: wiki 金色 "Give your **minions** +4
  Health."（旧文残留）vs 本地数据 "Give your **other** minions +{0}
  Health."（`num(0)`=4）→ 本卡 DEFERRED; 若解冻取数据（"other"）。

#### E4c 覆盖变化

- **卡牌覆盖率**: `stats_gained` 家族 16 实体中 **12 注册 / 4 DEFERRED**
  （`batch_stats_gained.py`，2026-09-20）。
- **原语**: `hsrl2/events.py::STATS_GAINED` + `Entity.add_buff` 广播 +
  `suppress_stats_gained()`（复制，含 #4b 手动复制循环）+
  `Game._restore_no_gain`（复原）+ `game._action_source`（来源，**逐动作
  复位**）+ `_friendly` 的 `Zone.PLAY` 区界（D9）。
- **2026-09-20 对抗验证纠错 6 项**: (1) `BG25_027` 文本 "your minions"
  （含自身）; (2) `_restore_no_gain` 真路径可达 → 新增 M5 回归;
  (3) `_restore_from_snapshot` / SirensSong 复制循环补抑制 + 负对照;
  (4) `ActionQueue.resolve` 逐动作复位来源; (5) `_friendly` 限定
  `Zone.PLAY`; (6) 文档/计数与 wiki 金色文本差异显式记录。
- **连带解冻**: `BG30_MagicItem_825` Smuggler Portrait 的载荷
  （`BG21_013`/`_G`）注册 → 825 的残余阻塞**只剩**单值家族种族覆写
  读取点 + 作用域 N5（`batch_trinkets29/31/27` 台账已同步）。
- **同原语的更大家族（前向兼容，非本 16 卡）**: 按正则
  `gains\s+(Attack|Health|stats)` 统计的 18 张基础卡（17 张此前未注册）
  现在**都有**可用观察点；逐张仍需按自身语义（"add to that amount" /
  "twice" / 类型过滤）实现，X 批不在本轮范围。

### E5. 本轮验证（2026-09-20，对抗验证纠错轮）

与 E5 旧版（`f0426d5` 落地轮）不同：本轮为**对抗验证缺陷修复轮**
（6 项: `BG25_027` 文本纠错 + 5 项引擎/边界/文档修复）。

- `hsrl2/tests/`: `4108 passed, 2 skipped, 14 subtests passed`（上一轮
  记账 `4096 passed` 与 `test_batch_stats_gained.py` 47 项**均与实况不符**，
  本轮据实修正——本轮**起点**实测 `4103 passed, 2 skipped, 14 subtests`，
  `test_batch_stats_gained.py` 48 项; 本轮新增 5 项 →
  `4108` / 该文件 **52** 项）。
- 六道严格门禁全 PASS; smoke `--games 150 --seed 606061`（行见批次报告）。
- 变异探针 **10 项**（生产点静默 / 复制不抑制 / delta 恒定 / 类型过滤删除 /
  战后复原不抑制 / `_friendly` 去 Zone / Hunter 排除自身 / 快照副本不抑制 /
  ActionQueue 来源泄漏 / SirensSong 复制不抑制）→ **10/10 全杀**。
  **旧记"第 5 项（复原抑制）为等价变异"已撤回**——见 D2 与
  `tools/_mutation_probe_stats_gained.py`。
- **纠错披露（行为变更，非"文档同步"）**: (a) `BG25_027` 由"排除自身"改为
  "含自身"（旧测试 `test_gain_buffs_other_minions_not_self` 固化错误行为，
  已改写）; (b) 酒馆/手牌随从加攻不再触发本族监听器; (c) 未声明 source 的
  动作不再继承上一个动作的 source; (d) 快照副本 / SirensSong 副本的附魔
  重放不再广播 `stats_gained`。

**战斗中"获得攻击力"监听器的效果边界（实测记录）**: 战内 `add_buff` 照常
广播（`stats_gained`）→ 监听器在战内**立刻生效**（例: Whelp Smuggler 战内
给龙 +1 Health），但其附魔随快照回滚（非 `persist`）→ 战后消失（RULES §3.5;
"战斗阶段 buff 战后消失"）。战斗快照只回滚属性，战内排队的 ActionQueue
在 `events_snapshot`/棋盘恢复中一并丢弃——本族没有战斗内监听器（`Sinestra`
的 "during combat" 仍 DEFERRED），故当前无行为影响; 记录以备未来实现时
按此边界处理。
