"""批次 trinkets31 — 全部剩余未注册饰品复评批（作业单 2026-09-15，41 张）。

台账来源: `docs/agents/TRINKET_LEDGER.md` 未注册明细 41 张（片 1 = 20 /
片 2 = 13 / 片 3 = 6 / 片 4 = 2）。41/41 在 `CardDB` 存在、41/41 在
`CardDB.trinket_offer_pool()` 中，且在本批之前 41/41 全部**不在** `REGISTRY`
（运行核验——与既有 batch_trinkets1..30 / batch_unlock_final 注册集合互不
相交）。本批评审总量 41 张; 截至 2026-09-19 状态 = **8 张 CORRECT
（本批注册）+ 19 张 DEFERRED + 14 张迁出**（SOP §6b 二态铁律;
禁止第三态; 宁可 DEFERRED 不要近似）。

数值一律 `CardDef.num(i)`（缺失 → fail-loud，禁止硬编码; 文本无占位符的
字面量按 SOP §3 在各类 `Params:` 行显式声明并给出数据核实）; 关联卡一律走
数据链 `CardDef.evolution_card_id` → `CardDB.by_dbf`（RULES §7.4.6，零硬编码
卡 id）; 随机一律 `game.rng`（本批 CORRECT 卡无随机）; 状态写在 hero 级
tag / source 实体属性（无 game 级 flag——SOP §12 item 9）。

**新引擎原语逐条核对（2026-09-15，RULES §6.19/§6.20/§7.4.3/§7.4.6/§7.4.9）**
═══════════════════════════════════════════════════════════════════════
  | 原语（生产点） | 本批复评结论 |
  |----------------|-------------|
  | `add_card_aura(source, card_ids, atk, health)`（家族"**have** +X/+Y"光环） | 语义是"家族**自身**获得属性"，与本批家族卡（"give/also give"）不同 → 不适用于 A 组; A 组的"also give"最终经 §7.4.16 `family_flags`（数值增量并入载荷自身 `Buff`）与 `hero.consume_policies`（吞噬策略）落地（868/987/283/824/869 于 2026-09-19 本批注册; 944/828 由 batch_trinkets33 `hero.giver_bonus`; 274 由 batch_trinkets34） |
  | `BONUS_KEYWORD_TAGS` / `grant_bonus_keyword` / `random_bonus_keyword` / `PERSIST_BONUS_ONLY` | 本批 41 张无一涉及 Bonus Keyword（417/891/892/801 已迁移） → 不适用 |
  | `hero.triple_threshold_race`（per-race 三连阈值） | 本批 41 张无三连阈值卡（439 已迁移） → 不适用 |
  | `minion_triggered(minion=, hook=, ctx=)` / `minion_consumed(...)` | 本批 41 张无直接消费卡（156/902 已迁移） → 不适用 |
  | `combat_restored(...)` / `last_minion_died(hero=)` / `hero._combat_dead_snaps` | **440 仅解锁"首只死亡 Mech 快照"一半**; "when you have space" 战斗腾位触发协议仍缺（`combat_summon_log` 只写不读） → 440/822 仍 DEFERRED |
  | `refresh_tavern(copies_of_warband=, keywords=, consume_free=)` + `_tavern_extra_keyword` / `_tavern_cost_rules` | 本批 41 张无关键词限定刷新/展示位（743/755 已迁移）; 921 需的是**法术**子集折扣（"give stats" 类别）→ 不适用 |
  | `CardDef.num(0..4)`（NUM_5 已导出） | 944/373 数值可读; **923 已解锁**（2026-09-18：数值通道 + `Buff(persist=True)` 原语; 权威 = 卡面**同句** "permanently"，补丁史仅旁证） |
  | `_next_trinket_kind` / hero 级 `CHOOSE_BOTH` / `trigger_friendly_rallies` | 本批 41 张无一消费 → 不适用 |
  | **载荷随从注册推进**（`batch_payload_minions`） | **解锁 830**：BG25_041 Felemental 从"未注册"变为"已注册"; **解锁 869**：BG29_873/BG29_877 Felblood 由本批在 `batch_payload_minions` 注册; **解锁 824**：`hero.consume_policies` + `Game.pick_consume_victim` 读取点落地（2026-09-19; 820 已由 batch_trinkets39 注册，2026-09-18） |
  | `GameTag.MINIONS_SOLD_THIS_TURN`（hero 级每回合清零） | 809 的"首个出售"观察点已就绪，但"plays its Blood Gems"的枚数/来源读法无权威 → 仍 DEFERRED |

**CORRECT 8 项（注册 8 个 id；2026-09-18 解冻 2 张——`Buff(persist=True)`
按来源跨战斗持久化原语 + `Game.add_persist_source` / `persist_source_id`
来源规则读取点，RULES §3.5 例外 4；2026-09-19 解冻 A 组 5 张——
owner 权威序: wiki 页无 Notes → 卡面天然语言 + §7.4.16 `family_flags`
/ `hero.consume_policies`）**
═══════════════════════════════════════════════════════════════════════
  BG30_MagicItem_868 Rewinder Portrait (Lesser, school=11, cost 3) —
      交付 BG26_174 Soul Rewinder（数据链）+ BGS_004 Wrath Weaver
      （卡面点名）; `FLAG_REWINDER_ALSO_ATTACK` → 载荷受伤回退时
      `+1/+1`（金色 +2/+2）。
  BG30_MagicItem_987 Balladist Portrait (Greater, school=12) —
      交付 BG26_814; `start_of_turn` 每回合再得 1 张;
      `FLAG_BALLADIST_ALSO_ATTACK` → 战吼 `+N/+N`
      （N = num(1)+GOLD_SPENT_THIS_TURN）。
  BG32_MagicItem_283 Czarina Portrait (Greater, school=12, cost 3) —
      交付 BG28_741; `FLAG_CZARINA_ALSO_HEALTH` → 施放酒馆法术时圣盾
      选择集 `+4/+4`（金色 +8/+8）。
  BG32_MagicItem_824 Implicator Portrait (Lesser, school=11, cost 1) —
      交付**2** 张 BG29_140; `hero.consume_policies` +
      `Game.pick_consume_victim` → 本人恶魔吞噬恒取馆内最高 max_health。
  BG30_MagicItem_869 Felblood Portrait (Lesser, school=11, cost 4) —
      交付 BG29_873; `FLAG_FELBLOOD_ALSO` 登记于 `BG29_873` 与
      `BG29_877` **两个家族** → 各自在印面额上补齐另一属性。
  BG32_MagicItem_830 Felemental Portrait (Lesser, school=11) —
      on_bind: (a) 数据链交付 `BG25_041` Felemental（`grant_trinket_
      related_card`，RULES §7.4.6）; (b) 注册 `battlecry_trigger` 持久监听
      （owner=饰品）——载荷 `FelementalScript` 的战吼经引擎
      `_finish_play_minion`/`TriggerBattlecry` 两路各广播一次（金色 ×2 /
      Brann 加倍各计一次）。
      回调条件: `minion.controller is 本人`（owner 隔离）**且** 家族身份命中
      （`TRIPLE_BASE_CARD_ID` 回落基础 id == `BG25_041`，含金色
      `BG25_041_G`）。命中后施加**同一持久面**的第二份 `TavernBuff`
      （`ApplyTavernBuff` + `BuffCurrentTavern`，`atk=num(0)=2` /
      `health=num(1)=2`）——载荷的 give 是**酒馆全域持久 Buff**（当前 +
      未来入馆），第二份同构 Buff 与"把 give 额提高 +2/+2"数学等价 →
      精确（非近似; 与 Vinespeaker Portrait `BG35_MagicItem_433` 经
      `ImproveBloodGems` 镜像血宝石 give 的既有先例同构）。
      数值通道: `num(0)=2`/`num(1)=2`（缺失 → fail-loud）。

  BG35_MagicItem_923 Bewitched Ribbon (Greater, school=12, cost 4) —
      on_bind 注册持久 `spell_resolving` 监听（owner=饰品; "Whenever you
      cast a spell" 的既有口径——SOP §16c item 36）: `spell.controller
      is 本人` → 对本人棋盘全部存活随从 `Buff(persist=True, source_id=本
      饰品 id)`，数值 = 战斗中（`game.in_combat`）`num(2)/num(4)`（=2/2）
      / 否则 `num(0)/num(1)`（=1/1）。`persist=True` 精确表达
      "permanently" 的战斗内份量（RULES §3.5 例外 4——`run_combat`
      恢复阶段按来源重放; 与 `PERSIST_COMBAT_CHANGES` 的单实体全量通道
      正交）。数值缺失 → fail-loud。

  BG36_MagicItem_362 Cyclist Portrait (Greater, school=12, cost 4) —
      on_bind: (a) 数据链交付 `BG31_925` Showy Cyclist（`grant_trinket_
      related_card`，非池 → 零池操作）; (b) `game.add_persist_source(
      本人, 本饰品, {BG31_925})` —— 载荷 `ShowyCyclistScript.deathrattle`
      授予时经 `game.persist_source_id(hero, source)` 读取，命中即把该次
      `Buff` 标 `persist=True`（战斗内亡语增量跨战斗保留; 对照无饰品 =
      §3.5 常规回滚）。规则挂 **hero** 级（覆盖召唤/Transform/直接换板
      等全部入板路径，SOP §16b item 32）; 家族按 `TRIPLE_BASE_CARD_ID`
      回落匹配（金色同族）; 饰品离场即失效。无模板参数（`num(0..4)`
      全 None——数值由载荷 CardDef 提供）。

**DEFERRED 19 张（状态 / 依赖 / 实现路径；2026-09-02 原始范围 34 张，
828/944/274/803/804/933/777/922/923/362 + 803(Kaboom Bot)/820(Impulsive)
+ 868/987/283/824/869（A 组 5 张，2026-09-19）已相继迁出）**
═══════════════════════════════════════════════════════════════════════
  A. 载荷已注册但"家族 give/also"读取点缺失 —— **0 张（全组闭环）**
    （原 11 张; 828/944 → batch_trinkets33 `hero.giver_bonus`;
      274 → batch_trinkets34; 803 Macaw → batch_trinkets36;
      804 Selfless → batch_trinkets35; 820 Impulsive → batch_trinkets39;
      **868/987/283/824/869 → 本批 2026-09-19**）
    2026-09-19 闭环依据（owner 权威序: wiki 页均**无 Notes/正文** →
    卡面天然语言; 逐条 URL/revid 与推导见各类 docstring）:
      - BG30_MagicItem_868 Rewinder Portrait — "also gain Attack" 增量 =
        同句 "give this +1 Health"（金色 +2）; 第二关联卡 `BGS_004`
        Wrath Weaver（卡面点名 + 数据核实）。
      - BG30_MagicItem_987 Balladist Portrait — "also give Attack" 增量 =
        同句 Health 额 `num(1)+GOLD_SPENT_THIS_TURN`（载荷 @ 升级段
        `+{0}/+{1}` 同处 improvement 子句）; + `start_of_turn` 再得 1 张。
      - BG32_MagicItem_283 Czarina Portrait — "also give Health" 增量 =
        同句 `num(0)` Attack 额（基础 4 / 金色 8）。
      - BG32_MagicItem_824 Implicator Portrait — "Your Demons always
        consume the highest-Health minion in the Tavern" = 种族范围
        吞噬目标策略（新增 `hero.consume_policies` +
        `Game.pick_consume_victim` 读取点）; "Get 2" = 交付 2 份。
      - BG30_MagicItem_869 Felblood Portrait — 两载荷已注册
        （batch_payload_minions）; "give Attack and Health" = 两家族各在
        自身印面额上补齐另一属性。

  B. 载荷未注册（效果依赖其行为，RULES §7.4.6 例外条）（4 张）
    BG30_MagicItem_402 Conductor Portrait — BG28_585 未注册 + 弃牌系统缺失。
    BG30_MagicItem_431 Azerite Portrait — BG28_707 未注册 + Elemental give 通道。
    BG30_MagicItem_777 Goose Portrait — ✅ 已迁出（2026-09-17，
      batch_goose_lucky_egg）: BG29_801 已注册（batch_remaining2,
      2026-09-16，Fledglings 有生产点）; 次生载荷 BG30_104/`_G` Lucky Egg
      由 batch_goose_lucky_egg 注册（"transform into" = 引擎 `Transform`
      + 金色 T3/T4 池化发现）→ 饰品本体同批注册。
    BG30_MagicItem_803 Kaboom Bot Portrait — ✅ **已迁出 batch_trinkets39**
      （2026-09-18）。载荷 BG_BOT_606（+金色）已注册（batch_remaining2,
      2026-09-16）; 家族亡语伤害改写通道 = RULES §7.4.16
      `hero.family_flags`（载荷 `FLAG_KABOOM_DR_BONUS`）; 金色 "twice"
      下 +10 的口径按 owner 权威序裁定为**逐实例**（14+14）——
      Battlegrounds/Kaboom_Bot_Portrait（oldid=921183）**无 Notes 段** →
      卡面天然语言; 否决"总额 +10 一次"（18 无法在两条独立伤害实例间
      分配）。
    BG32_MagicItem_806 Battlecruiser Portrait — token BG31_HERO_801pt 未注册
      + Battlecruiser Upgrade 子系统（无卡池/升级链）。

  C. ✅ **已闭环（2026-09-21，`batch_family_races` 注册 4/4）** 多值/全种族
     身份 `RACES`（原 2026-09-19 记 [NO AUTHORITY FOUND: 多类型消费者的
     解释口径]；权威已于 2026-09-21 由 wiki `Minion` revid 817925 /
     `Multi-type minion` revid 855346 / `All` revid 893299 + Patch
     30.2.0.205267 revid 814123 Dev Comment 补齐——完整裁定见
     `ENGINE_BACKLOG`「C 组 RACES 权威核查」2026-09-21 闭环节）。
     以下为当时的阻塞记录（保留追溯）：
    BG30_MagicItem_418 Bronzebeard Portrait（Brann = Murloc **且** Dragon，
      2 类; 载荷 BG_LOE_077 + 金色 TB_BaconUps_045 均**已注册**）
    BG30_MagicItem_825 Smuggler Portrait（Whelp Smugglers are Dragons，
      **单类型**，严格说非 RACES 模型缺口; 载荷 BG21_013/`_G` **未注册**——
      旧记 "dbf 72072 在本地数据不解析" **不成立**，72072 正是 BG21_013）
    BG30_MagicItem_971 Enforcer Portrait（Lightfang Enforcers have all
      minion types; 载荷 BGS_009 + 金色 TB_BaconUps_082 **已注册**）
    BG32_MagicItem_179 Drakkari Portrait（Drakkari = Mech **且** Elemental，
      2 类; 载荷 BG26_ICC_901 + 金色 **已注册**）
    ——**id 前缀订正**: 825 是 `BG30_…`、179 是 `BG32_…`（下划线上文旧记
    前缀相反）。
    `GameTag.RACE` 单值、`Race.ALL` 是"匹配一切"而非"同时是这两个"
    → 需集合/位掩码 tag + 全部 race 读取点改造（ENGINE_BACKLOG §A1）。
    **成员集合有权威**（卡面 + `CardDefs.xml` 的 `CARDRACE` ∪ per-race
    tag，`RaceTagMap.xml` 2522–2556; 自前池 10 张双类型随从）; **但
    N1–N7 无权威**: 部分多类型计数（1 vs 2 类，且仓内
    `_type_association` 排除 ALL / `_controlled_types` 令 ALL=10 类 /
    `darkgifts` 标 AMBIGUOUS 三口径互相冲突）、"of each type" 重复命中、
    饰品类型关联、入池过滤、家族光环作用域、`RACES` 表示契约、
    `BACON_SUBSET_*`≠类型身份的数据契约 —— 任一条未定即不得动读取点。

  D. 子系统缺失（6 张）
    BG32_MagicItem_300 Putricide Sticker — Craft 多步部件合成链。
    BG30_MagicItem_707 Tickatus Sticker — Darkmoon Prize 候选表（RULES §11.4
      已退役系统，数据无 tier→prize 映射）; num(0)=3。
    BG30_MagicItem_994 Yogg-Tastic Pastry — Wheel of Yogg-Saron（无结果表）。
    BG35_MagicItem_812 Corrupted Tome — 三连奖励**替换**钩子 + Triple Prize
      候选表。
    BG35_MagicItem_820 Safety Patch — Secrets 子系统（挂奥秘 + 致命伤害
      预防钩子）; num(0)=5。
    BG35_MagicItem_823 Timeworn Candelabra — Minor Timewarp 卡表/发现域。

  E. 语义权威缺失（5 张）
    BG30_MagicItem_416 Token of the Old Gods — 两段定向选择链可脚本化，
      但**候选域无权威**（第二段"from a Tier higher": 池 vs 酒馆 /
      恰好 +1 级 vs 任意更高 / 全候选 vs 3 选 Discover——30.6.2 由
      "Discover"改为"choose"、ruRU 独有"из таверны"; 第一段目标域亦未
      明确）→ 不近似。
    BG30_MagicItem_711 Marine Signet — "improve this" 的**档位递增**无数据
      字段（既有 improve 卡全部递增属性值）; num(0)=4 num(1)=1。
    BG32_MagicItem_809 Gem Donation — "plays its Blood Gems" 枚数/来源三种
      读法无权威（3×N / N 轮转 / 每目标 1 颗）。
    BG32_MagicItem_823 Wax Imprinter — "(if possible)" 限定对象（金币上限 /
      生命不足 / 仅未阵亡）无权威（wiki 无 Notes、12 语种同义）。
    ~~BG32_MagicItem_933 Weary Portrait~~ — **已注册**（batch_trinkets37,
      2026-09-14）; 原记"通道语义分歧"已裁定: 通用通道只翻转 temporary
      buff，Reborn 关键词由载荷脚本读 `permanent_spellcraft` 后跳过过期
      监听（34.0.1 官方 hotfix 权威）。

  F. 引擎原语缺失（9 张）
    BG30_MagicItem_440 Boom Controller — **已解冻**: `combat_slot_freed`
      腾位广播 + `_combat_dead_snaps` exact copy → batch_trinkets32 注册。
    BG30_MagicItem_804 Ancient Wishbone — **已解冻**: `hp_times` 技能效果
      结算翻倍配额 → batch_trinkets32 注册。
    BG30_MagicItem_821t2 Fishy Sticker — 金色定义 `TB_BaconUps_307` 无脚本
      且引擎无"金色定义 → 基础脚本回落"协议（ENGINE_BACKLOG §B15）。
    BG30_MagicItem_822 Twin Sky Lanterns — **已解冻**: 同 440 的腾位广播
      + 首召唤物入场态快照 → batch_trinkets32 注册。
    BG35_MagicItem_921 Cowrie Necklace — "Tavern spells that **give stats**"
      的子集折扣读取点（`TAVERN_SPELL_COST_MOD` 是无条件静态 tag）。
    ~~BG35_MagicItem_922 Tide Raiser Portrait~~ — **已解冻（2026-09-17，
      `batch_trinkets38` 注册）**: 原陈述"`spell_resolving` 仅在招募期
      路径广播"错误——`cast_spell_effect` 无条件广播
      `spell_resolving`/`spell_resolved`，战斗上下文经 `game.in_combat`。
    ~~BG35_MagicItem_923 Bewitched Ribbon~~ — **已解冻（2026-09-18，本批
      注册）**: 原陈述"无细粒度跨战斗持久化通道"已由新引擎原语
      `Buff(persist=True)`（RULES §3.5 例外 4，`run_combat` 恢复阶段按
      来源重放）解决; 数值通道 num(0/1/2/4)=1/1/2/**None**/2（`{4}`=2）。
      **权威**: 卡面**同一句**的 "…permanently"（wiki.gg
      `Battlegrounds/Bewitched_Ribbon` 逐字 + 标签表 NUM_1/2/3/5;
      zhCN/JA/KO 把括号渲染为替换语义 "战斗中改为+{2}/+{4}"）⇒ 括号 =
      同一次"permanently"授予的相位数值，非第二次临时效果; 该页 Patch
      changes（只改括号数字、基础 +1/+1 与 "permanently" 从未移动）
      **仅作旁证**，不是排除性证明; 另 + 官方 S14 表（仅可获得性）
      + RULES §3.5 + `game.in_combat` 先例。
    ~~BG36_MagicItem_362 Cyclist Portrait~~ — **已解冻（2026-09-18，本批
      注册）**: 同一原语 + 来源规则读取点 `Game.add_persist_source` /
      `Game.persist_source_id`（载荷 `ShowyCyclistScript.deathrattle`
      命中即标 `persist=True`）。
      **权威**: 官方 S14 饰品全表（Blizzard 论坛 163710, Greater
      "Cyclist Portrait | 4 | Get a Showy Cyclist. Your Showy Cyclists'
      Deathrattles give permanent stats."——与卡面逐字一致）+ RULES §3.5
      + wiki.gg `Battlegrounds/Showy_Cyclist` 32.2.0 亡语复制 bugfix
      Notes。
    BG36_MagicItem_373 Multilayered Shield — 动态 `TAVERN_SPELL_EXTRA_*`
      提供者 + "每个类型"增量口径权威（num0*(1+T) vs num0*T）; num=1/2。

**接线审计读取点（W1/W2/W3 核对）**
═══════════════════════════════════════════════════════════════════════
  - W1: `FelementalPortraitScript` / `BewitchedRibbonScript` /
    `CyclistPortraitScript` 各定义且已注册 `on_bind` → 无死钩子;
    19 个 DEFERRED 类**不定义任何钩子方法**（无"注册但 no-op"第三态）。
  - W2: 注册的事件名均有生产点——`battlecry_trigger`
    （`_finish_play_minion`/`TriggerBattlecry`）、`spell_resolving`
    （`_finish_play_spell`/`cast_spell_effect`）; owner=饰品实体，随
    `grant_trinket` 接线 / `replace` 注销 → 非死监听。
  - W3: 写入的 `TavernBuff` 经 `hero.tavern_buffs` 由引擎
    `add_tavern_entity`（`game.py` L597）真实消费; `hero.persist_sources`
    由 `Game._persist_source_entry` 真实读取（`persist_source_id` /
    `minion_persist_source`）→ 非空转标记。

**测试（`hsrl2/tests/test_batch_trinkets31.py`）**
═══════════════════════════════════════════════════════════════════════
  全部断言走真实引擎路径: 授予 `game.grant_trinket`（on_bind 接线）、真实
  `game.play_minion` 战吼路径、真实 `game.refresh_tavern`（持久面）、真实
  `game.add_tavern_entity`。每方法含正效果 + 同 setup 负/正对照; 双英雄
  owner 隔离; 绑定前/后（一次性语义）; 金色 ×2 触发; 空酒馆落空不报错;
  同 seed 确定性; 结构性 DEFERRED 台账守卫按 TEST_SOP 标 `@engine-only`。
"""

from __future__ import annotations

from typing import List

from hsrl2.actions.consume import CONSUME_POLICY_HIGHEST_HEALTH
from hsrl2.actions.stats import Buff
from hsrl2.actions.tavern_buff import (ApplyTavernBuff, BuffCurrentTavern,
                                       TavernBuff)
from hsrl2.events import BATTLECRY_TRIGGER, Listener
from hsrl2.game import GameStateError
from hsrl2.scripts.batches.batch_battlecry import FLAG_BALLADIST_ALSO_ATTACK
from hsrl2.scripts.batches.batch_econ_misc import (
    FLAG_CZARINA_ALSO_HEALTH, FLAG_REWINDER_ALSO_ATTACK)
from hsrl2.scripts.batches.batch_payload_minions import (
    FIERY_FELBLOOD, FLAG_FELBLOOD_ALSO)
from hsrl2.tags import GameTag

# ── 本批卡 id（CardDB 按名核实，禁止凭记忆写） ──
FELEMENTAL_PORTRAIT = "BG32_MagicItem_830"
FELEMENTAL = "BG25_041"              # 关联卡（evolution_card_id=97553）
FELEMENTAL_GOLDEN = "BG25_041_G"     # 金色独立卡定义
SHOWY_CYCLIST = "BG31_925"           # 362 关联卡（evolution_card_id=115565）
SHOWY_CYCLIST_GOLDEN = "BG31_925_G"  # 金色独立卡定义

# ── 2026-09-19 解冻的 5 张（A 组）载荷 id（CardDB 按名核实） ──
CHARGING_CZARINA = "BG28_741"        # 283 关联卡（evolution_card_id=110321）
LOVESICK_BALLADIST = "BG26_814"      # 987 关联卡（evolution_card_id=99011）
SOUL_REWINDER = "BG26_174"           # 868 关联卡（evolution_card_id=100949）
WRATH_WEAVER = "BGS_004"             # 868 第二关联卡（卡面点名; dbf 59670）
FALSE_IMPLICATOR = "BG29_140"        # 824 关联卡（evolution_card_id=108115）
SLIMY_FELBLOOD = "BG29_873"          # 869 关联卡（evolution_card_id=109418）

# ── A. 载荷已注册但"家族 give/also"读取点缺失 ──
SHAKER_PORTRAIT = "BG30_MagicItem_828"
REWINDER_PORTRAIT = "BG30_MagicItem_868"
REDEEMER_PORTRAIT = "BG30_MagicItem_944"
BALLADIST_PORTRAIT = "BG30_MagicItem_987"
BRISTLEBACH_PORTRAIT = "BG32_MagicItem_274"
CZARINA_PORTRAIT = "BG32_MagicItem_283"
IMPULSIVE_PORTRAIT = "BG32_MagicItem_820"
IMPLICATOR_PORTRAIT = "BG32_MagicItem_824"
FELBLOOD_PORTRAIT = "BG30_MagicItem_869"
MACAW_PORTRAIT = "BG32_MagicItem_803"
SELFLESS_PORTRAIT = "BG32_MagicItem_804"

# ── B. 载荷未注册 ──
CONDUCTOR_PORTRAIT = "BG30_MagicItem_402"
AZERITE_PORTRAIT = "BG30_MagicItem_431"
GOOSE_PORTRAIT = "BG30_MagicItem_777"
KABOOM_BOT_PORTRAIT = "BG30_MagicItem_803"
BATTLECRUISER_PORTRAIT = "BG32_MagicItem_806"

# ── C. 多值种族 RACES ──
BRONZEBEARD_PORTRAIT = "BG30_MagicItem_418"
SMUGGLER_PORTRAIT = "BG30_MagicItem_825"
ENFORCER_PORTRAIT = "BG30_MagicItem_971"
DRAKKARI_PORTRAIT = "BG32_MagicItem_179"

# ── D. 子系统缺失 ──
PUTRICIDE_STICKER = "BG32_MagicItem_300"
TICKATUS_STICKER = "BG30_MagicItem_707"
YOGG_PASTRY = "BG30_MagicItem_994"
CORRUPTED_TOME = "BG35_MagicItem_812"
SAFETY_PATCH = "BG35_MagicItem_820"
TIMEWORN_CANDELABRA = "BG35_MagicItem_823"

# ── E. 语义权威缺失 ──
TOKEN_OF_THE_OLD_GODS = "BG30_MagicItem_416"
MARINE_SIGNET = "BG30_MagicItem_711"
GEM_DONATION = "BG32_MagicItem_809"
WAX_IMPRINTER = "BG32_MagicItem_823"
WEARY_PORTRAIT = "BG32_MagicItem_933"

# ── F. 引擎原语缺失 ──
BOOM_CONTROLLER = "BG30_MagicItem_440"
ANCIENT_WISHBONE = "BG30_MagicItem_804"
FISHY_STICKER = "BG30_MagicItem_821t2"
TWIN_SKY_LANTERNS = "BG30_MagicItem_822"
COWRIE_NECKLACE = "BG35_MagicItem_921"
TIDE_RAISER_PORTRAIT = "BG35_MagicItem_922"
BEWITCHED_RIBBON = "BG35_MagicItem_923"
CYCLIST_PORTRAIT = "BG36_MagicItem_362"
MULTILAYERED_SHIELD = "BG36_MagicItem_373"


# ══════════════════ 共用小工具 ══════════════════


def _hero(ctx):
    """on_bind ctx → 饰品持有英雄（引擎 grant_trinket 传 ctx={"hero": h}）。"""
    return (ctx or {}).get("hero")


def _family_base_id(entity) -> str:
    """实体的家族基础卡 id（金色按 `TRIPLE_BASE_CARD_ID` 回落——RULES §2.3）。"""
    return (entity.get(GameTag.TRIPLE_BASE_CARD_ID, None)
            or getattr(entity, "card_id", None))


def _grant_related(game, hero, tid: str):
    """数据链授予关联卡（RULES §7.4.6）——链条断裂 fail-loud。

    解析失败 → `GameStateError`（SOP §6b，与 `batch_trinkets33
    ._grant_related` / `batch_trinkets34` 同口径）; `grant_trinket_
    related_card` 返回 False（池空落空）不是错误，按 RULES §2.4 整卡
    落空。返回解析出的 `CardDef`（"Get 2"/"and a <卡>" 族复用它交付
    第二份，零硬编码）。
    """
    rel = game.trinket_related_card(tid)
    if rel is None:
        raise GameStateError(f"{tid}: evolution_card_id broken data chain")
    game.grant_trinket_related_card(hero, tid)
    return rel


# ══════════════ BG32_MagicItem_830 Felemental Portrait（CORRECT） ══════════════


class FelementalPortraitScript:
    """
    Natural language: [x]Get a Felemental.
    Your Felementals give
    an extra +{0}/+{1}.

    Formal spec:
      1. on_bind:
         a) `game.grant_trinket_related_card(hero, 本饰品 id)` —— 数据链
            `evolution_card_id=97553` → `db.by_dbf` → `BG25_041`
            Felemental（非池载荷，`is_pool_minion=False` → 零池操作;
            满手排队 RULES §3.3）。
         b) 注册持久监听器 `Listener(BATTLECRY_TRIGGER, owner=source)`——
            载荷 `FelementalScript` 的战吼由引擎 `_finish_play_minion`
            与 `TriggerBattlecry` 两路各广播一次（金色 ×2 / Brann 加倍
            各计一次）。
      2. 回调条件（缺一不触发）:
         a) `minion.controller is 本人`（"your Felementals"——owner 隔离;
            对手战吼不触发）;
         b) 家族身份命中: `_family_base_id(minion) == BG25_041`
            （含金色 `BG25_041_G`——金色是独立卡定义）。
      3. 命中后施加**第二份持久酒馆 Buff**: `ApplyTavernBuff` +
         `BuffCurrentTavern`，`atk=num(0)` / `health=num(1)`，
         `source_id=本饰品 id`。载荷的 give 是**酒馆全域持久面**
         （当前 + 未来入馆随从），第二份同构 Buff 与"把 give 额提高
         +num(0)/+num(1)"数学等价 → 精确表达"give an **extra**"。
         等价性依据: 载荷 `FelementalScript` = `ApplyTavernBuff` +
         `BuffCurrentTavern`（本仓已注册实现），加性与目标域（全酒馆）
         均相同，无随机、无目标选择歧义。
      4. 绑定前已打出的 Felemental 不被追溯（监听器只在 on_bind 后存在
         ——"give an extra" 是持续修饰，官方无追溯语义）; 绑定后新入馆
         随从经 `add_tavern_entity` 应用 `hero.tavern_buffs` 持久面
         （RULES §7.4.9），两份 Buff 同时生效。
      5. 数值: `num(0)` / `num(1)` 缺失 → GameStateError（fail-loud，
         禁止硬编码）。

    Test: test_batch_trinkets31.py — 绑定交付恰好 1 只 BG25_041（手牌）/
      战吼后酒馆既有随从恰 +4/+3（对照无饰品 +2/+1）; 棋盘随从不受影响
      （正 + 负同方法）; 绑定前打出不追溯、绑定后打出生效; 金色
      Felemental 每触发各计一次（+8/+6）; 对手打出不计入本人酒馆 /
      本人饰品不影响对手; 空酒馆落空不报错; 非 Felemental 战吼不触发;
      刷新后持久面仍为两份; 同 seed 确定性。

    Params: {0}=num(0)=2 {1}=num(1)=2（BG32_MagicItem_830;
            载荷 BG25_041 give 基准 = num(0)/num(1) = 2/1）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        # (a) 数据链交付关联卡（"Get a Felemental"）
        game.grant_trinket_related_card(h, source.card_id)
        # (b) 家族 give 的额外增量（数值缺失 fail-loud）
        d = game.db.get(source.card_id)
        extra_atk = d.num(0) if d is not None else None
        extra_health = d.num(1) if d is not None else None
        if extra_atk is None or extra_health is None:
            raise GameStateError(
                f"{source.card_id}: missing num(0)/num(1) template param")
        extra = TavernBuff(atk=extra_atk, health=extra_health,
                           source_id=source.card_id)

        def on_battlecry(g, minion=None, _h=h, _buff=extra, **kw):
            if minion is None or minion.controller is not _h:
                return
            if _family_base_id(minion) != FELEMENTAL:
                return
            g.run_actions([ApplyTavernBuff(_h, _buff),
                           BuffCurrentTavern(_h, _buff)])

        game.events.register(Listener(event=BATTLECRY_TRIGGER, owner=source,
                                      callback=on_battlecry))
        return None


# ══════════════ A. 载荷已注册但"家族 give/also"读取点缺失 ══════════════


class ShakerPortraitScript:
    """
    Natural language: [x]Get a Zesty Shaker. Your Zesty Shakers give an
    extra copy of the spell.

    Status: 已解冻（2026-09-13）——由 `batch_trinkets33` 注册
    （`hero.giver_bonus` 家族给予者加成通道 + `ZestyShakerScript` 消费点）。

    Dependency: 载荷 `BG26_505` ZestyShakerScript 的副本数写死为私有分支
      `copies = 2 if source.is_golden else 1`，无 hero 级
      `shaker_extra_copies` 读取点; 本批不可改他批脚本（SOP §12 item 2/14）。
    Implementation path: 载荷读 hero 级标记（本饰品 on_bind 写入）→
      副本数 +num(0); 之后本卡 on_bind = 数据链交付 + 写标记。

    Params: 无模板参数（BG30_MagicItem_828 num(0..4) 全 None）
    """


class RewinderPortraitScript:
    """
    Natural language: [x]Get a Soul Rewinder and a Wrath Weaver. Your Soul
    Rewinders also gain Attack.

    Status: **CORRECT**（2026-09-19 按 owner 权威序解冻）。

    Authority（逐条）:
      [SILENT] wiki.gg `Battlegrounds/Rewinder_Portrait`（revid=921145，
        2026-09-03; `?action=raw` 全文 = Card template + dbfId/refTags，
        **无 Notes/正文段落**）——wiki 未给数额解释。
      [SILENT] 载荷 `BG26_174` 页（revid 见下）同样只有 Card template。
      [LOCAL DATA] `BG30_MagicItem_868` `num(0..4)` 全 None = 无模板参数;
        载荷 `BG26_174` 基础 "+1 Health" / 金色 `BG26_174_G` "+2 Health"
        为文本字面量。
      ⇒ 按 owner 权威序第 2 条，取**卡面天然语言**读法。

    Natural-language derivation（"also gain Attack" 的增量 = ?）:
      卡面全句 "Get a Soul Rewinder and a Wrath Weaver. Your Soul
      Rewinders **also gain Attack**.";载荷全句 "After your hero takes
      damage, rewind it and give this **+1 Health**."（金色 "+2 Health"）。
      "also gain Attack" 的受词 = 同句中唯一的既有效果 "give this +1
      Health" —— **also** 只新增**属性面**（Attack），不新增数量词;
      文本未给出新数字 ⇒ 增量 = **同句既有的那个量**（基础 +1 / 金色
      +2，与 Health 同额）。这也让金色文本的自洽性成立: 金色把 "+1"
      改成 "+2"（同一处字面量），"also gain Attack" 自然随之为 +2。
      Rejected alternatives:
        (a) **固定 +1 Attack**（不随金色变）: 金色卡面把唯一的数量词
            改成 2，若 Attack 恒为 1，则 "also" 不再镜像同句效果——
            需要凭空发明"金色只加成 Health"的例外，文本无据。
        (b) **Attack = 本体当前 Attack** / **= 本回合受伤额**: 引入
            文本中不存在的量纲，纯发明。
        (c) **另一个隐藏模板参数**: 三个 CardDef（基础/金色/饰品）
            `num(0..4)` 全 None，数据不存在该参数 ⇒ 不可选。
      边界: "also" 只在**同一触发**（同一次 hero_damage_taken）上追加，
      不产生额外触发、不改 rewind 语义; 多张 Rewinder 各自 +1/+1
      （每实例监听各触发一次，既有语义不变）。

    Formal spec:
      1. on_bind:
         a) `_grant_related(game, hero, BG30_MagicItem_868)` —— 数据链
            `evolution_card_id=100949` → `BG26_174` Soul Rewinder
            （池 T2; 池记账/满手排队由引擎负责）。
         b) **第二关联卡** "and a Wrath Weaver": 数据链只给出单卡
            （`evolution_card_id` 单值）; 第二 id 由**卡面点名** +
            `bg_cards.json` 逐卡核实确定 = `BGS_004` Wrath Weaver
            （dbf 59670; 全库唯一 "Wrath Weaver"; wiki
            `Battlegrounds/Rewinder_Portrait` `derived_relatedCardDbfIds`
            = `100949&&59670` 印证）→ `game.grant_card_copy_to_hand`
            （池记账; 池空落空非错误）。
         c) `game.add_family_flag(hero, BG26_174,
            FLAG_REWINDER_ALSO_ATTACK, source=source)`——载荷
            `SoulRewinderScript` 触发时经 `game.family_flag` 读取，
            同一次 `Buff` 追加 Attack（金色按基础卡 id 归一命中）。
      2. owner 隔离: 开关只写本英雄; 对手 Soul Rewinder 不受影响。
      3. 数值零硬编码: 增量由载荷按 `is_golden` 分支取同额 Health（1/2），
         本饰品只提供开关（无 `num` → 无 fail-loud 分支）。
      4. 绑定前已生成的伤害不追溯（监听器只在 on_bind 后存在）。

    Test: test_batch_trinkets31.py — 真实 `grant_trinket` 后手牌出现
      BG26_174 + BGS_004 各 1 张; 真实 `hero.take_damage` → 本体 +1 攻且
      +1 血（对照无饰品 +0 攻/+1 血）; 金色 +2/+2; 对手持有饰品不影响
      我方 / 我方饰品不影响对手; 饰品离场后开关失效。

    Params: 无模板参数（BG30_MagicItem_868 num(0..4) 全 None;
            第二关联卡 id 为身份标识非数值）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        rel = _grant_related(game, h, REWINDER_PORTRAIT)
        ww = game.db.get(WRATH_WEAVER)
        if ww is None:
            raise GameStateError(f"{WRATH_WEAVER}: unknown card id")
        game.grant_card_copy_to_hand(h, ww)
        game.add_family_flag(h, rel.id, FLAG_REWINDER_ALSO_ATTACK,
                             source=source)
        return None


class RedeemerPortraitScript:
    """
    Natural language: [x]Get a Nalaa the Redeemer. Your Nalaa the Redeemers
    give an extra +{0}/+{1}.

    Status: 已解冻（2026-09-13）——由 `batch_trinkets33` 注册
    （`hero.giver_bonus` 通道；按本类 Implementation path 的裁定：extra
    追加在**同次** `_each_type_buffs` 的 Buff 上——同一目标 +8/+7，
    而非二次独立选取）。

    Dependency: 载荷 `BG28_551` 每次施放给"每类型一个**随机**友方"+4/+3;
      本饰品 num(0/1)=4/4，但 "extra +4/+4" 是**同一目标 +8/+7** 还是
      **二次独立选取**（可能落到同类型另一只）无权威——载荷无读取点，
      镜像重抽会改变属性分布（非等价，SOP §6b 禁止近似）。
    Implementation path: 载荷读 hero 级 `nalaa_extra_atk/health`，在同次
      `_each_type_buffs` 的 Buff 上追加同额（保持目标一致）。

    Params: {0}=num(0)=4 {1}=num(1)=4（BG30_MagicItem_944）
    """


class BalladistPortraitScript:
    """
    Natural language: [x]Get a Lovesick Balladist. At the start of each
    turn, get another. Your Lovesick __Balladists also give Attack.

    Status: **CORRECT**（2026-09-19 按 owner 权威序解冻）。

    Authority（逐条）:
      [SILENT] wiki.gg `Battlegrounds/Balladist_Portrait`（revid=921177，
        2026-09-03; `?action=raw` 全文 = Card template + dbfId/refTags
        "Attack-related"，**无 Notes/正文段落**）——wiki 未给数额解释。
      [SILENT] 载荷 `Battlegrounds/Lovesick_Balladist` 页同样只有 Card
        template（mechanicTags=Increment health）。
      [LOCAL DATA] `BG30_MagicItem_987` `num(0..4)` 全 None;
        载荷 `BG26_814`/`BG26_814_G` 仅 `num(1)=1`（Health 基值）,
        `num(0)`（Attack 基值）为 None。
      ⇒ 按 owner 权威序第 2 条，取**卡面天然语言**读法。

    Natural-language derivation（"also give Attack" 的增量 = ?）:
      载荷卡面是**双段文本**（`@` 分隔基础/升级显示态）:
        基础: "Battlecry: Give a Pirate **+{1} Health**. (Improved by each
               Gold you spent this turn!)"
        升级: "Battlecry: Give a Pirate **+{0}/+{1}**. (Improved by each
               Gold you spent this turn!)"
      `data/bg_cards.json` 逐字核实升级段就是**本饰品版本**（batch_battlecry
      `LovesickBalladistScript` docstring 既有裁定）。升级段把同一目标
      从"+{1} Health"改成"+{0}/+{1}"——&#123;0&#125; 是 Attack、&#123;1&#125; 是
      Health，**两个占位符同处 "(Improved by each Gold you spent this
      turn!)" 子句之内** ⇒ Attack 与 Health 是**同一次、同量、同缩放**
      的授予（Attack = Health = 基础 num(1) + 本回合已花金币）。
      文本未引入任何独立数字（数据 `num(0)` 亦为 None）⇒ 增量只能是
      **同句 Health 额**。
      Rejected alternatives:
        (a) **固定 +1 Attack（不随金币缩放）**: 与升级段把两占位符放进
            **同一个** "(Improved by each Gold...)" 子句直接矛盾——若
            Attack 不缩放，文本应把 improvement 只挂在 Health 后; 且
            "also give" 的镜像读法要求同量。
        (b) **Attack = 仅已花金币（基础 0）**: 文本 "+{0}/+{1}" 的 {0}
            在 0 支出时显示为 0 攻，而 Health 显示为 +1——同一"also"
            却让两属性基数不同，无文本依据; "Improved **by** each Gold"
            的既有实现（batch_battlecry 裁定）是**叠加在基值之上**。
        (c) **另一个隐藏模板参数**: 本饰品与两版载荷 `num(0)` 均 None
            ⇒ 数据不存在。
      边界: "also" 只改**同一次战吼**的授予（同一目标、同次 PendingChoice
      选择、同额缩放），**不**产生第二次目标选择; 金色 "twice" 由引擎
      触发 2 次体现（每次 +N/+N），不在此追加。

    Formal spec:
      1. on_bind:
         a) `_grant_related(game, hero, BG30_MagicItem_987)` —— 数据链
            `evolution_card_id=99011` → `BG26_814` Lovesick Balladist
            （池 T4）。
         b) `game.add_family_flag(hero, BG26_814,
            FLAG_BALLADIST_ALSO_ATTACK, source=source)`——载荷
            `LovesickBalladistScript.battlecry` 经 `game.family_flag`
            读取，同一次 `Buff` 追加 `atk = num(1) + GOLD_SPENT_THIS_TURN`
            （= 同句 Health 额; 金色按基础卡 id 归一）。
      2. `start_of_turn`（饰品 SoT 钩子）: "At the start of each turn, get
         another." → `_grant_related` 再交付 1 张（绑定当回合由 on_bind
         交付，之后每回合开始各 1 张; BoomsMonsterPortraitScript 同口径）。
      3. owner 隔离: 开关与交付只作用于本英雄; 对手 Balladist 不受影响。
      4. 数值零硬编码（本饰品无 `num` → 无 fail-loud 分支）。

    Test: test_batch_trinkets31.py — 真实 `grant_trinket` 后手牌出现
      BG26_814; 真实战吼（PendingChoice 选 Pirate）→ +1/+1（对照无饰品
      +0/+1）; 本回合花 3 金 → +4/+4（两属性同缩放）; 金色两次各
      +N/+N; 非 Pirate 不在候选; 真实 `end_recruit_phase` 后再得 1 张;
      对手手牌不变。

    Params: 无模板参数（BG30_MagicItem_987 num(0..4) 全 None; 增量 =
             载荷 num(1) + 金币支出）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        rel = _grant_related(game, h, BALLADIST_PORTRAIT)
        game.add_family_flag(h, rel.id, FLAG_BALLADIST_ALSO_ATTACK,
                             source=source)
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        _grant_related(game, h, source.card_id)
        return None


class BristlebachPortraitScript:
    """
    Natural language: [x]Get a Bristlebach. Your Bristlebachs play Blood
    Gems on all friendly minions.

    Status: 已迁出 → batch_trinkets34（2026-09-13，RULES §7.4.16 家族行为开关通道 `hero.family_flags`）; 原阻塞: 载荷目标集改写读取点缺失

    Dependency: 载荷 `BG26_157` 的 Avenge(2) 对**全部 Quilboar** 施放
      2 颗宝石; "on **all friendly minions**" 是目标集**替换**（Quilboar
      不得因此翻倍）——载荷无读取点，饰品侧镜像会把 Quilboar 变成 4 颗
      （非等价）。
    Implementation path: 载荷读 hero 级 `bristlebach_all_friendly` 切换
      目标集为全部友方随从。

    Params: 无模板参数（count=2 在载荷脚本内，BG32_MagicItem_274 num 全 None）
    """


class CzarinaPortraitScript:
    """
    Natural language: Get a Charging Czarina. Your Charging Czarinas also
    give Health.

    Status: **CORRECT**（2026-09-19 按 owner 权威序解冻; 实现设计见
    ENGINE_BACKLOG #27 第二十七轮记录，本轮完成台账迁移）。

    Authority（逐条）:
      [SILENT] wiki.gg `Battlegrounds/Czarina_Portrait`（revid=921161，
        2026-09-03; `?action=raw` 全文 = Card template + dbfId/refTags
        "Health-related"，**无 Notes/正文段落**）——wiki 未给数额解释。
      [SILENT] 载荷 `Battlegrounds/Charging_Czarina` 页（article_trivia
        只有来历，无机制 Notes）。
      [LOCAL DATA] `BG32_MagicItem_283` `num(0..4)` 全 None; 载荷
        `BG28_741` `num(0)=4`（金色 `BG28_741_G` `num(0)=8`）是该句
        **唯一**数字（"+{0} Attack"）。
      ⇒ 按 owner 权威序第 2 条，取**卡面天然语言**读法。

    Natural-language derivation（"also give Health" 的增量 = ?）:
      载荷全句 "Whenever you cast a Tavern spell, give your minions with
      Divine Shield **+{0} Attack**."; 饰品全句 "Your Charging Czarinas
      **also give Health**."。
      (i) 目标集: "also" 的受词是**同一效果** ⇒ 目标集不变 = 本人棋盘
          当前持有 DIVINE_SHIELD 的存活随从（含 Czarina 自身）。
      (ii) 属性面: "also" 只把 **Attack → Attack and Health**（新增
           Health），不新增数量词。
      (iii) 数额: 句中唯一数字是 `num(0)`; 文本未引入第二个数字 ⇒
           Health 增量 = **同句 Attack 额**（基础 4 / 金色 8）。
      Rejected alternatives:
        (a) **固定 +1 Health**: 文本无 "+1" 字面量、数据无第二参数
            ⇒ 纯发明。
        (b) **按目标自身 Health / 已受损量**: 引入文本不存在的量纲。
        (c) **另一个隐藏模板参数（{1}）**: 两版载荷与本饰品 `num(0..4)`
            全 None ⇒ 数据不存在。
      边界: 只在**同一施法实例、同一选择集**追加，不产生第二次监听
      触发; 多张 Czarina 各自触发（per-instance，监听器 owner=各自实体），
      饰品的 Health 追加随每张 Czarina 的触发各追加一次（与 Attack 严格
      同构）。绑定前已施放的法术不追溯。

    Formal spec:
      1. on_bind:
         a) `_grant_related(game, hero, BG32_MagicItem_283)` —— 数据链
            `evolution_card_id=110321` → `BG28_741` Charging Czarina
            （池 T5，非 token）。
         b) `game.add_family_flag(hero, BG28_741,
            FLAG_CZARINA_ALSO_HEALTH, source=source)`——载荷
            `ChargingCzarinaScript.on_tavern_spell` 经 `game.family_flag`
            读取，同一次 `Buff` 追加 `health = num(0)`（金色按基础卡 id
            归一 → 金色 Czarina 的 `num(0)=8` 同时用于两属性）。
      2. owner 隔离: 开关只写本英雄; 对手的 Czarina 施法不追加、本人
         饰品不影响对手棋盘。
      3. 数值零硬编码（本饰品无 `num` → 无 fail-loud 分支; 增量全部由
         载荷 CardDef `num(0)` 决定）。
      4. 饰品离场（被替换）→ `family_flag` 的 source 存活校验使其及时失效。

    Test: test_batch_trinkets31.py — 真实 `grant_trinket` 后手牌出现
      BG28_741; 真实 `play_spell`（酒馆法术）→ 圣盾随从 +4/+4（对照无
      饰品 +4/+0）; 非圣盾随从两属性皆不变（负对照）; 金色 +8/+8;
      对手施法不触发; 对手持有饰品不影响我方; 绑定前已打出不追溯。

    Params: 无模板参数（BG32_MagicItem_283 num(0..4) 全 None; 增量 =
             载荷 num(0)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        rel = _grant_related(game, h, CZARINA_PORTRAIT)
        game.add_family_flag(h, rel.id, FLAG_CZARINA_ALSO_HEALTH,
                             source=source)
        return None


class ImpulsivePortraitScript:
    """
    Natural language: [x]Get a 6/6 Impulsive Trickster. Your Impulsive
    Tricksters' Deathrattles target adjacent minions.

    Status: ✅ **已迁出 → batch_trinkets39**（2026-09-18）。

    迁移依据（owner 权威序）: 原唯一阻塞 = "target adjacent minions" 的
      数额口径无权威。复核 wiki
      `Battlegrounds/Impulsive_Portrait`（oldid=907061）**无 Notes 段**
      → 卡面天然语言 = **全额逐目标**（饰品的 "target" 替换载荷目标短语
      "another friendly minion" → 复数集合; "give X to <集合>" 每个成员各
      得 X，文本无 "split"/"divided"）。实现: 载荷
      `ImpulsiveTricksterScript.deathrattle` 读
      `FLAG_IMPULSIVE_ADJACENT`（RULES §7.4.16）把目标改为
      `_adjacent_minions`; 饰品 on_bind 交付 6/6 覆盖体
      （`create_minion` + BASE_ATK/HEALTH/HEALTH=6，CuratorSticker 先例）。
      完整推导与边界见 `batch_payload_minions.ImpulsiveTricksterScript`
      docstring §4–6。

    Params: 无模板参数（BG32_MagicItem_820 num(0..4) 全 None;
            6/6 为文本字面量，声明在 batch_trinkets39 `IMPULSIVE_STAT`）
    """


class ImplicatorPortraitScript:
    """
    Natural language: Get 2 False Implicators. Your Demons always consume
    the highest-Health minion in the Tavern.

    Status: **CORRECT**（2026-09-19 按 owner 权威序解冻 + 引擎策略读取点
    落地）。

    Authority（逐条）:
      [SILENT] wiki.gg `Battlegrounds/Implicator_Portrait`（revid=921195，
        2026-09-03; `?action=raw` 全文 = Card template + dbfId/refTags
        "Demon-generating&&Demon-related&&Health-related"，**无
        Notes/正文段落**）——wiki 未给机制解释。
      [SILENT] 载荷 `Battlegrounds/False_Implicator` 页（tags 含 [Random]）
        只有 Card template。
      [LOCAL DATA] `BG32_MagicItem_824` `num(0..4)` 全 None; 载荷
        `BG29_140` 无模板参数（"consume a minion ... to gain its stats"）。
      ⇒ 按 owner 权威序第 2 条，取**卡面天然语言**读法。

    Natural-language derivation（策略与边界）:
      饰品全句 "Get 2 False Implicators. Your **Demons** always consume
      the **highest-Health** minion in the Tavern."。
      (i) 范围 = **"Your Demons"**（本人控制、race 为 DEMON 的随从; 引擎
          惯例 `Race.ALL` 视为具备一切类型 → 命中; 对手恶魔不在域内）。
      (ii) 目标 = **Tavern** 内随从（不扩展到手牌/棋盘; 载荷原文即
           "a minion in the Tavern"）。
      (iii) 选择 = **max_health 最大者**（"highest-Health" 逐字 = 属性值
           `max_health`，与 ConsumeMinion 的 atk/max_health 快照口径一致;
           非当前 health、非攻击、非总属性）。
      (iv) 并列极大: 文本未定义同值次序 ⇒ 在**并列集**内走 `game.rng`
           （保留引擎"全部随机走 game.rng"的确定性协议; 不发明 First/
           Last/Attack 次序等身份 tie-break）。
      Rejected alternatives:
        (a) **最高攻击 / 最高总属性 / 最低生命**: 卡面逐字写 "highest-
            **Health**"，替换为其它量纲无据。
        (b) **仅改 False Implicator 家族**: 卡面写 "Your **Demons**"
            （不是 "Your False Implicators"）——限定到单卡家族会把
            Ur'zul / Mind Muck / Methodical Madness 等其它恶魔吞噬路径
            漏掉 = 卡面明文处的简化实现（SOP §6b 禁止）。
        (c) **并列时取第一只（身份序）**: 需要发明排序规则; 引擎既有
            口径是所有随机选择走 `game.rng`（seed 确定性），取 rng 更弱
            假设。
      边界: 策略只改**目标选择**，不改吞噬的属性获取（仍 atk/max_health）
      与回池语义; 非恶魔吞噬者不受影响; 非酒馆来源（棋盘/手牌）的
      `ConsumeMinion` 目标由各效果显式指定，不经此策略。

    Formal spec:
      1. on_bind:
         a) `_grant_related(game, hero, BG32_MagicItem_824)` —— 数据链
            `evolution_card_id=108115` → `BG29_140` False Implicator
            （非池 token → 零池操作）。
         b) "Get **2** False Implicators"（文本字面量 "2"，数据无参数）:
            再 `game.grant_card_copy_to_hand(hero, rel)` 交付第二份白板
            副本（同卡; 满手排队由引擎负责）。
         c) `game.add_consume_policy(hero, CONSUME_POLICY_HIGHEST_HEALTH,
            source=source)`（RULES §7.4.16 扩展; hero 级种族范围策略）。
      2. 读取点 = `Game.pick_consume_victim(consumer, candidates, ...)`
         （SOP §12 公开 API）; **全部**本人恶魔的酒馆目标选择站点:
         (a) 载荷 `FalseImplicatorScript.end_of_turn`;
         (b) 通用 `ConsumeRandomTavernMinion`（Ur'zul / Mind Muck /
             Activate 基础版等）;
         (c) `batch_activate.SoulkeepingJailerGoldenScript.activate`
             （金色分支原自实现 `rng.choice`，2026-09-19 统一走读取点）;
         (d) `batch_spells_final.ConsumeRandomTavernWithKeywords`
             （Methodical Madness 的 2 次独立吞噬）;
         (e) `batch_quest_rewards.R309`（左右端随从吞噬——消费者为恶魔时
             命中; 非恶魔仍随机）。
         **不改**的边界: 由效果**显式指定**受害者的路径（如
         `BG36_…` Cleaver 类"选择馆内某随从让友方吞噬"、棋盘/手牌来源的
         `ConsumeMinion`）不属"选择**哪只**馆内随从"的随机口径，策略不介入。
      3. owner 隔离: 策略只写本英雄; 对手恶魔不受影响。
      4. 数值零硬编码（"2" 为卡面字面量，无 `num` 模板参数）。
      5. 饰品离场 → `consume_policy` 的 source 存活校验使其及时失效。

    Test: test_batch_trinkets31.py — 真实 `grant_trinket` 后手牌出现
      **恰好 2** 张 BG29_140; 真实 EoT 下馆内高/低生命两只 → 恰吞最高
      生命者（对照无饰品随机，用多 seed 证明非固定）; 并列时走 rng 且
      同 seed 确定; 真实 `ConsumeRandomTavernMinion`（Ur'zul 路径）同样
      命中最高生命（证明是种族范围而非单卡）; 对手恶魔/饰品不影响我方。

    Params: 无模板参数（"Get 2" 为卡面字面量; BG32_MagicItem_824 num
             全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        rel = _grant_related(game, h, IMPLICATOR_PORTRAIT)
        # "Get 2 False Implicators"（第二份白板副本）
        game.grant_card_copy_to_hand(h, rel)
        game.add_consume_policy(h, CONSUME_POLICY_HIGHEST_HEALTH,
                                source=source)
        return None


class FelbloodPortraitScript:
    """
    Natural language: Get a Slimy Felblood. Your Fiery and Slimy Felbloods
    give Attack and Health.

    Status: **CORRECT**（2026-09-19 按 owner 权威序解冻; 两个载荷已注册）。

    Authority（逐条）:
      [SILENT] wiki.gg `Battlegrounds/Felblood_Portrait`（revid=921218，
        2026-09-03; `?action=raw` 全文 = Card template + dbfId/refTags，
        **无 Notes/正文段落**）——wiki 未给机制解释。
      [SILENT] 载荷 `Battlegrounds/Slimy_Felblood`（revid 见 API）/
        `Battlegrounds/Fiery_Felblood` 两页均只有 Card template
        （mechanicTags 分别为 Increment health / Increment attack）。
      [LOCAL DATA] `BG30_MagicItem_869` `num(0..4)` 全 None; 载荷
        `BG29_873` Slimy "+2 Health this game"（金色 `_G` "+4"）/
        `BG29_877` Fiery "+2 Attack this game"（金色 `_G` "+4"）为文本
        字面量（CardDef 无模板参数）。
      ⇒ 按 owner 权威序第 2 条，取**卡面天然语言**读法。

    Natural-language derivation（"give Attack and Health" 的增量 = ?）:
      卡面全句 "Get a Slimy Felblood. Your **Fiery and Slimy Felbloods
      give Attack *and* Health**."; 两载荷分别是**单属性 give**:
        Fiery: "Deathrattle: Minions in the Tavern have +2 Attack this game."
        Slimy: "Battlecry: Minions in the Tavern have +2 Health this game."
      句子结构 "Your [Fiery and Slimy Felbloods] give [Attack and Health]"
      = 对该**两个家族**把 give 的属性面扩为**两属性**; 每个家族仍用
      **自己的印面额**（2 基础 / 4 金色）——文本没有引入任何新数字，
      也没有说"给对方卡的数额"。
      Rejected alternatives:
        (a) **各自只新增对方的属性、数额取对方卡**: 文本唯一数字来自
            各卡自身（+2），"give Attack and Health" 不含"用另一张卡的
            数额"语义; 且两卡同步改动后若取对方额会得到 +2/+2 的巧合
            结果——但当两卡数额不同（如某版金色化不同步）会分叉，
            无文本支持。
        (b) **新增一个合并数额（如 4）**: 数据 `num(0..4)` 全 None
            ⇒ 无参数来源。
        (c) **只在 battlecry（Slimy）侧生效**: "Fiery **and** Slimy" 逐字
            点名两个家族; 只改一个 = 文本明文处的简化（禁止）。
      边界: 增量为**持久酒馆面**（"this game"），与原生 give 同通道
      （`TavernBuff` 当前 + 未来入馆）; 金色数额由各自卡面字面量给出
      （Slimy 金色 = 引擎金色战吼 2 次 × 2 = 4; Fiery 金色 = 独立类
      `_AMOUNT=4`——引擎不自动翻倍金色亡语）。

    Formal spec:
      1. on_bind:
         a) `_grant_related(game, hero, BG30_MagicItem_869)` —— 数据链
            `evolution_card_id=109418` → `BG29_873` Slimy Felblood
            （非池 → 零池操作）。
         b) `game.add_family_flag(hero, BG29_873, FLAG_FELBLOOD_ALSO, ...)`
            与 `game.add_family_flag(hero, BG29_877, FLAG_FELBLOOD_ALSO,
            ...)`——**两个家族**各登记一次（第二家族 id 由卡面点名 +
            数据逐卡核实，见 batch_payload_minions `FIERY_FELBLOOD`）。
         c) 载荷 `SlimyFelbloodScript.battlecry` /
            `FieryFelbloodScript.deathrattle` 经 `game.family_flag` 读取
            → 同一次 `TavernBuff` 追加另一属性（数值 = 自身印面额）。
      2. owner 隔离: 开关只写本英雄; 对手 Felblood 不受影响。
      3. 数值零硬编码（本饰品无 `num`; 增量由载荷 `_AMOUNT` 给出）。
      4. 饰品离场 → `family_flag` 的 source 存活校验使其及时失效。

    Test: test_batch_trinkets31.py — 真实 `grant_trinket` 后手牌出现
      BG29_873; 真实战吼 → 馆内 +2/+2（对照无饰品 +0/+2）; 真实死亡路径
      的 Fiery Felblood 亡语 → +2/+2（对照 +2/+0）; 金色 Slimy 总额
      +4/+4 / 金色 Fiery +4/+4; 对手酒馆不受影响。

    Params: 无模板参数（BG30_MagicItem_869 num(0..4) 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        rel = _grant_related(game, h, FELBLOOD_PORTRAIT)
        game.add_family_flag(h, rel.id, FLAG_FELBLOOD_ALSO, source=source)
        game.add_family_flag(h, FIERY_FELBLOOD, FLAG_FELBLOOD_ALSO,
                             source=source)
        return None


class MacawPortraitScript:
    """
    Natural language: Get a Monstrous Macaw. Your Monstrous Macaws also
    trigger your left-most Battlecry.

    Status: 已迁出 → batch_trinkets36（2026-09-13，RULES §7.4.17 条件化
    战吼第二消费者）; 原阻塞: 载荷"also trigger"分支读取点缺失 +
    "最左战吼"资格集权威

    Dependency: 载荷 `BGS_078` 本体 Rally 触发最左亡语; "also trigger
      your **left-most** Battlecry" 的资格集 = 最左**带战吼**者（32.2
      论坛复现串 `M G x B y z` 裁定），由载荷 `rally` 读
      `FLAG_MACAW_EXTRA_BATTLECRY` 追加（RULES §7.4.17）。
    Implementation path: 载荷读家族开关，额外触发最左战吼（已落地，
      见 batch_trinkets36）。

    Params: 无模板参数（BG32_MagicItem_803 num(0..4) 全 None）
    """


class SelflessPortraitScript:
    """
    Natural language: [x]Get a Selfless Hero. Your Selfless Heroes also
    trigger on Battlecry.

    Status: 已迁出 → batch_trinkets35（2026-09-13，RULES §7.4.17
    条件化战吼协议; 读法由 32.4 补丁说明裁定）; 原阻塞: 结算时点无权威 +
    载荷分支读取点缺失

    Dependency: 载荷 `BG_OG_221` 仅在死亡时给随机友方圣盾; "also trigger
      on Battlecry" 的结算时点（战吼**结算时**还是**结算后**）与是否
      与原亡语叠加（"also" 暗示叠加）无权威（wiki 仅列 BATTLECRY tag，
      无 Notes）; 载荷无 battlecry 分支。
    Implementation path: 载荷增 `battlecry` 出口读 hero 级标记。

    Params: 无模板参数（BG32_MagicItem_804 num(0..4) 全 None）
    """


# ══════════════ B. 载荷未注册（效果依赖其行为） ══════════════


class ConductorPortraitScript:
    """
    Natural language: [x]Get a Snarling Conductor. Whenever you discard a
    card, this plays a Blood Gem on all your minions.

    Status: DEFERRED — 弃牌系统缺失 + 载荷未注册

    Dependency: 引擎无 `CARD_DISCARDED` 事件 / `Game.discard_card`（无弃牌
      路径）; 载荷 `BG28_585` Snarling Conductor 未注册（其"discard → play
      Blood Gem"行为不存在），本饰品效果依赖该行为（RULES §7.4.6 例外条）。
    Implementation path: 引擎弃牌系统 + 载荷迁移 + 饰品侧 on_bind 交付。

    Params: 无模板参数（BG30_MagicItem_402 num(0..4) 全 None）
    """


class AzeritePortraitScript:
    """
    Natural language: [x]Get a Living Azerite. Your Living Azerites also
    give stats to friendly Elementals.

    Status: DEFERRED — 载荷未注册 + Elemental give 通道缺失

    Dependency: 载荷 `BG28_707` Living Azerite 未注册（REGISTRY 运行核验），
      "also give stats to friendly Elementals" 依赖其原生 give 行为;
      `racefx.elemental_give_bonus` 是元素**给**加成的消费点，但本卡的
      语义是 Azerite 的给效果扩展，需载荷读取点。
    Implementation path: 迁移载荷 + 增加"also Elementals"目标/通道读取点。

    Params: 无模板参数（BG30_MagicItem_431 num(0..4) 全 None）
    """


# 777 Goose Portrait 已由 batch_goose_lucky_egg 注册（2026-09-17）→
# 占位 DEFERRED 类删除（迁移轨迹见本模块 docstring B 类清单）。


class KaboomBotPortraitScript:
    """
    Natural language: [x]Get a Kaboom Bot. Your Kaboom Bots' Deathrattles
    deal 10 extra damage.

    Status: ✅ **已迁出 → batch_trinkets39**（2026-09-18）。

    迁移依据（owner 权威序）: 载荷 `BG_BOT_606`/`TB_BaconUps_028` 已于
      2026-09-16 由 batch_remaining2 注册; 家族亡语伤害改写通道 = RULES
      §7.4.16 `hero.family_flags`（Bristlebach 先例），载荷
      `KaboomBotScript.deathrattle` 读 `FLAG_KABOOM_DR_BONUS` 并把
      `KABOOM_EXTRA_DAMAGE`(=10) 逐实例并入同一次 `Hit`。金色 "twice"
      下 +10 的口径: wiki `Battlegrounds/Kaboom_Bot_Portrait`
      （oldid=921183）**无 Notes 段** → 卡面天然语言裁定 = 逐实例
      （14+14）; 否决"总额 +10 一次"（18 无法在两条独立伤害实例间分配）。
      完整推导与边界见 `batch_remaining2.KaboomBotScript` docstring §6–8。

    Params: 无模板参数（"10 extra damage" 文本字面量 = 载荷侧
            `KABOOM_EXTRA_DAMAGE`; BG30_MagicItem_803 num(0..4) 全 None）
    """


class BattlecruiserPortraitScript:
    """
    Natural language: [x]Get an 12/12 Battlecruiser. Whenever the Tavern is
    Refreshed, add a Battlecruiser Upgrade to it.

    Status: DEFERRED — 载荷 token 未注册 + Battlecruiser Upgrade 子系统缺失

    Dependency: 关联 token `BG31_HERO_801pt` 未注册; "Battlecruiser
      Upgrade" 是独立卡池/升级链子系统（数据无 tier→upgrade 映射、
      无战斗巡洋舰升级协议）——刷新入馆的 token 无法定义。
    Implementation path: Battlecruiser Upgrade 子系统（卡表 + `add_tavern_
      entity` 协议）落地后，on_bind 交付 12/12 覆盖体 + 注册
      `tavern_refresh_complete` 注入 Upgrade。

    Params: 无模板参数（"12/12" 为文本字面量;
            BG32_MagicItem_806 num(0..4) 全 None）
    """


# ══════════════ C. 多值/全种族身份 RACES ══════════════


class BronzebeardPortraitScript:
    """
    Natural language: [x]Get a Brann Bronzebeard and a random Battlecry
    minion. Your Brann Bronzebeards are both Murlocs and Dragons.

    Status: DEFERRED — requires 多值种族 `RACES`

    Dependency: "both Murlocs and Dragons" = **同时**属于两个类型;
      `GameTag.RACE` 单值，`Race.ALL` 是"匹配一切"（会错误地让 Brann
      属于全部类型）。交付与"random Battlecry minion"侧可就绪，但身份
      条款无法精确表达（半实现 = 第三态）。
      **[NO AUTHORITY FOUND: 多类型消费者解释]** 成员集合有权威（卡面 =
      2 类; 载荷 `BG_LOE_077` 无类型），但"每个不同类型"计数、`of each
      type` 选取、饰品类型关联、入池过滤、家族光环作用域均无权威，且
      计数侧三口径互相冲突（`ENGINE_BACKLOG`「C 组 RACES 权威核查」
      N1–N7）→ 维持 DEFERRED。
    Implementation path: `RACES` 集合/位掩码 tag + `Minion.race` 集合视图
      + 全部 race 读取点改造（ENGINE_BACKLOG §A1）; **先钉死 N1–N7 与
      原语契约**。

    Params: 无模板参数（BG30_MagicItem_418 num(0..4) 全 None）
    """


class SmugglerPortraitScript:
    """
    Natural language: [x]Get a Whelp Smuggler. Set its stats to 12/12.
    Your Whelp Smugglers are Dragons.

    Status: DEFERRED — requires owner 级家族类型改写读取点
      （**单类型**，严格说不是 `RACES` 集合缺口）;
      载荷注册阻塞已于 2026-09-20 闭合

    Dependency: 载荷 `BG21_013`/`_G` Whelp Smuggler **已注册**
      （2026-09-20 `batch_stats_gained`; 本地数据 dbf 72072 可解析
      = `BG21_013`——旧记"载荷 dbf 72072 不解析"**不成立**）。
      其效果 "Whenever a friendly Dragon gains Attack, give it +1 Health"
      （金色 +2，`num(0)`=1/2）的观察点已由引擎 `stats_gained` 原语
      落地（`hsrl2/events.py::STATS_GAINED`，生产点 `Entity.add_buff`，
      复制/复原经抑制; 触发域逐路径裁定见 ENGINE_BACKLOG §E 与
      `Entity.add_buff` docstring）→ ~~触发域开放~~ **已闭合**。
      "are Dragons" = NONE → DRAGON 的**单值**家族改写（同
      batch_trinkets27 记载: 需 owner 级家族种族覆写读取点，`RACES`
      集合对其过宽）; 作用域 **[NO AUTHORITY FOUND]**（ENGINE_BACKLOG
      §C N5: 棋盘 vs 手牌/酒馆/池/未来副本）。"Set its stats to 12/12"
      **非阻塞项**（`batch_spells2.SetStats` / `batch_trinkets14`
      先例——旧记"另需 set-stats 读取点"不成立）。
    Implementation path: (a) ~~引擎落地 `stats_gained` 观察点 → 迁移
      载荷~~ **已完成 2026-09-20**（`batch_stats_gained`，
      `test_batch_stats_gained.py`）; (b) 家族类型改写读取点（非 RACES）
      并钉死作用域（N5）; 数值 `12/12` 为文本字面量。残余阻塞只剩 (b)。

    Params: 无模板参数（"12/12" 文本字面量;
            BG30_MagicItem_825 num(0..4) 全 None）
    """


class EnforcerPortraitScript:
    """
    Natural language: [x]Get a Lightfang Enforcer. Your Lightfang
    Enforcers have all minion types.

    Status: DEFERRED — requires 运行时追加全类型身份协议（`RACES`）

    Dependency: 载荷 `BGS_009` Lightfang Enforcer **已注册**（交付侧就绪，
      金色 `TB_BaconUps_082` 亦已注册）;
      但"have all minion types"需给家族（含新副本/Transform 入板）追加
      全类型身份——`GameTag.RACE` 单值且无"家族身份光环"读取点（入场即
      打标漏非 summon 路径，SOP §16b item 32 禁止）。
      **[NO AUTHORITY FOUND: 消费者口径]** 匹配侧"全类型"可用 `Race.ALL`
      表达（RULES §8），但计数侧三口径互相冲突——`_type_association`
      排除 `ALL`（贡献 0 类）、`_controlled_types` 令 `ALL` = 10 类、
      `darkgifts.most_common_board_race` 明标 AMBIGUOUS 不计
      （ENGINE_BACKLOG「C 组 RACES 权威核查」N1）→ 维持 DEFERRED。
    Implementation path: `RACES` 集合 tag 或家族身份读取点 + 先钉死
      计数契约（N1）。

    Params: 无模板参数（BG30_MagicItem_971 num(0..4) 全 None）
    """


class DrakkariPortraitScript:
    """
    Natural language: [x]Get a Drakkari Enchanter. Your Drakkari
    Enchanters are both Mechs and Elementals.

    Status: DEFERRED — requires 多值种族 `RACES`

    Dependency: 载荷 `BG26_ICC_901` + 金色 `BG26_ICC_901_G` **已注册**
      （EoT 翻倍由引擎内建）;
      "both Mechs and Elementals"无法用单值 RACE 表达（`Race.ALL` 过宽）。
      **[NO AUTHORITY FOUND: 消费者口径]** 成员集合有权威（卡面 = 2 类;
      载荷无类型），但部分多类型计数（算 1 类还是 2 类）、`of each type`
      的重复命中、饰品类型关联、入池过滤均无权威（ENGINE_BACKLOG
      「C 组 RACES 权威核查」N1–N4）→ 维持 DEFERRED。
    Implementation path: `RACES` 集合 tag + race 读取点改造 + 先钉死
      N1–N4 与原语契约。

    Params: 无模板参数（BG32_MagicItem_179 num(0..4) 全 None）
    """


# ══════════════ D. 子系统缺失 ══════════════


class PutricideStickerScript:
    """
    Natural language: [x]Craft a custom Undead. At the start of every
    2 turns, repeat this. <i>({0} |4(turn, turns) left!)</i>

    Status: DEFERRED — Craft 多步部件合成链缺失

    Dependency: 引擎无 `Game.craft`（部件选择 → 组装 → 产出）、无部件
      候选表与组装规则数据; 复刻会绕过引擎协议（SOP §6b 禁止）。
    Implementation path: Craft 子系统落地后 on_bind + 周期 `start_of_turn`
      触发 Craft 选择链。

    Params: 无模板参数（周期 2 为文本字面量; BG32_MagicItem_300 num 全 None）
    """


class TickatusStickerScript:
    """
    Natural language: [x]Discover a Tier 3 Darkmoon Prize. At the start of
    every three turns, repeat this. <i>({0} |4(turn, turns) left!)</i>

    Status: DEFERRED — Darkmoon Prize 候选表缺失

    Dependency: Darkmoon Prize 是已退役子系统（RULES §11.4），`data/` 无
      tier→prize 映射、无卡池定义; 无法构造 Discover 候选（num(0)=3 已可读）。
    Implementation path: 数据层恢复 Darkmoon Prize 表 + `Discover` 接入 →
      on_bind + 每三回合 `start_of_turn` 重放。

    Params: {0}=num(0)=3（三回合周期）
    """


class YoggTasticPastryScript:
    """
    Natural language: Spin the Wheel of Yogg-Saron. At the start of each
    turn, spin it again.

    Status: DEFERRED — Wheel of Yogg-Saron 结果表/协议缺失

    Dependency: 引擎无 `spin_wheel` 与结果表（数据无 wheel 段）;
      "spin again each turn" 侧可交付但半实现 = 第三态。
    Implementation path: Wheel 结果表 + `Game.spin_wheel` 协议。

    Params: 无模板参数（BG30_MagicItem_994 num(0..4) 全 None）
    """


class CorruptedTomeScript:
    """
    Natural language: Get a Triple Prize. Whenever you would get a Triple
    Reward, get a Triple Prize instead.

    Status: DEFERRED — 三连奖励替换钩子 + Triple Prize 候选表缺失

    Dependency: `game._grant_triple_reward` 内联发放，无替换/覆写协议;
      Triple Prize 候选表未在 36.2.2 数据中提供; 文本 "instead" 是替换
      （近似为"额外给一张"会改变总量，SOP §6b 禁止）。
    Implementation path: 三连奖励替换读取点 + Triple Prize 候选表。

    Params: 无模板参数（BG35_MagicItem_812 num(0..4) 全 None）
    """


class SafetyPatchScript:
    """
    Natural language: Cast Ice Block. Gain {0} Gold.

    Status: DEFERRED — Secrets 子系统缺失

    Dependency: "Cast Ice Block" = 奥秘 `TB_Bacon_Secrets_12`（数据核实
      `evolution_card_id=58512`）; 引擎无 `hero.secrets` 容器、无"致命
      伤害预防"触发窗口。`GainGold` 侧就绪（num(0)=5）但半实现 = 第三态。
    Implementation path: Secrets 子系统（挂载 + 致命伤害前钩子 + 触发/消耗）。

    Params: {0}=num(0)=5（Gain Gold 侧）
    """


class TimewornCandelabraScript:
    """
    Natural language: <b>Discover</b> a 2-Cost minion from the Minor
    Timewarp.

    Status: DEFERRED — Minor Timewarp 卡表/发现域缺失

    Dependency: "Minor Timewarp" 是独立机制卡池（数据无对应 subset/
      发现域字段），无法构造 `Discover` 候选集。
    Implementation path: 数据层导出 Minor Timewarp 卡表 + 发现域接入。

    Params: 无模板参数（"2-Cost" 为发现域约束，文本字面量;
            BG35_MagicItem_823 num(0..4) 全 None）
    """


# ══════════════ E. 语义权威缺失 ══════════════


class TokenOfTheOldGodsScript:
    """
    Natural language: [x]<b>Spellcraft:</b> Choose a minion. Then choose a
    minion from a Tier higher to transform it into.

    Status: DEFERRED — 第二段候选域无权威（引擎已具备 PendingChoice /
      Transform / 池记账，两段链可脚本化）

    Dependency: 两段定向选择链本身可用脚本级 `PendingChoice` 链 +
      `Transform` 表达; 但**候选域**无权威:
        (a) 第二段"from a Tier higher"的来源 = 随从池 vs 酒馆?
        (b) tier 关系 = 恰好 +1 级 vs 任意更高?
        (c) 选项 = 全候选 vs 3 选 Discover（30.6.2 文本由
            "Discover"改为"choose"、ruRU 独有"из таверны"、wiki 仍列
            Discover 类别——三者互相矛盾）;
        (d) 第一段目标域 = 本人棋盘 vs 任意随从?
      无官方 Notes/实测证据（SOP §6b 第 4 步: 宁可 DEFERRED 不近似）。
      另: 饰品 Spellcraft 生成协议**已就绪**（trinkets30 Vibrant Bubble
      先例），不再是阻塞项。
    Implementation path: 候选域权威裁定后，`BG30_MagicItem_416t` 脚本:
      `needs_target` 第一段 + `on_play` 内按第一段 tier 计算第二段候选
      （池占返或酒馆按裁定）→ 第二段 `PendingChoice` → `Transform`。

    Params: 无模板参数（BG30_MagicItem_416 / 416t num(0..4) 全 None）
    """


class MarineSignetScript:
    """
    Natural language: [x]After you play 4 minions, get a random Tier {1}
    Tavern spell and improve this. <i>({0} left!)</i>@[x]After you play
    4 minions, get a random Tier {1} Tavern spell.

    Status: DEFERRED — "improve this" 的档位递增无数据字段

    Dependency: `triple_upgrade_id` 为空、无升级变体 CardDef; 既有
      "improve this" 卡全部递增**属性值**（非档位）; 官方无权威
      （wiki 无 Notes）。num(0)=4（触发阈值）num(1)=1（tier）均已可读。
    Implementation path: 升级变体数据/协议（或官方澄清递增语义）后实现。

    Params: {0}=num(0)=4 {1}=num(1)=1（BG30_MagicItem_711）
    """


class GemDonationScript:
    """
    Natural language: [x]The first minion you sell each turn plays its
    Blood Gems on the 3 highest-Tier minions in the Tavern.

    Status: DEFERRED — "plays its Blood Gems" 枚数/来源无权威读法

    Dependency: `minion_sold` 事件、`MINIONS_SOLD_THIS_TURN` 观察点、
      `GEMS_PLAYED_ON` 记账、`PlayBloodGems` 均已就绪; 阻塞项是读法:
        (a) 按 GEMS_PLAYED_ON 枚数、每颗对 3 目标各施放（3×N）;
        (b) 共 N 颗轮转分配到 3 目标;
        (c) 每目标固定 1 颗。
      三种读法在野猪人高宝石局面数值差异巨大，无官方 Notes/实测。
    Implementation path: 裁定后监听 `minion_sold` + 每回合首个出售记账 →
      取本人酒馆 `tech_level` 最高 3 只按读法施放。

    Params: 无模板参数（"3 highest-Tier" 为文本字面量;
            BG32_MagicItem_809 num(0..4) 全 None）
    """


class WaxImprinterScript:
    """
    Natural language: [x]Gain 2 Gold and take 2 damage. At the start of
    each turn, repeat this <i>(if possible)</i>.

    Status: DEFERRED — "(if possible)" 的限定对象无权威读法

    Dependency: `GainGold` / `hero.take_damage` 均已就绪（2 为文本
      字面量，CardDef 无模板参数）; 但 "(if possible)" 指金币上限 /
      生命不足以承受 2 点伤害 / 仅未阵亡，三者无权威。已查:
      wiki 无 Notes、12 语种同义、32.4.2/33.0.0 补丁历史均未澄清
      （SOP §6b 第 4 步）。
    Implementation path: 裁定后 on_bind + 每回合 `start_of_turn` 执行
      `GainGold(h, 2)` + `h.take_damage(2)` 并按裁定加守卫。

    Params: 无模板参数（"2 Gold"/"2 damage" 文本字面量;
            BG32_MagicItem_823 num(0..4) 全 None）
    """


class WearyPortraitScript:
    """
    Natural language: [x]Get a Weary Mage. Your Weary Mages' Spellcrafts
    are permanent.

    Status: **已迁出** — 历史 DEFERRED 骨架，**不再引用**；实现见
      `batch_trinkets37.WearyPortraitScript`（2026-09-14）。原记:
      DEFERRED — "Spellcrafts are permanent" 通道语义分歧

    Dependency: 载荷 `BG31_830` Weary Mage **已注册**（交付侧就绪）;
      全库"Spellcrafts are permanent"有两条实现:
        (a) 同名 Dark Gift 走 `_permanent_spellcraft_uuids`（法术卡不
            随回合结束丢弃，无公开 API）;
        (b) `add_permanent_spellcraft_rule` 走 RULES §7.4.7a（临时 buff
            永久化）。
      两条语义不同，本卡适用哪条无权威（SOP §6b 第 4 步）。
    Implementation path: 裁定后 on_bind = 数据链交付 + 按正确通道注册规则。

    Params: 无模板参数（BG32_MagicItem_933 num(0..4) 全 None）
    """


# ══════════════ F. 引擎原语缺失 ══════════════


class BoomControllerScript:
    """
    Natural language: [x]When you have space, summon an exact copy of your
    first Mech that died each combat.

    Status: DEFERRED — 战斗内"腾位"有界触发协议缺失（快照半就绪）
    （**已被 batch_trinkets32 取代注册** 2026-09-15——本类仅存台账）

    Dependency: `hero._combat_dead_snaps`（按死亡顺序的轻量快照）**已就绪**
      → "首只死亡 Mech 快照"可读; 阻塞项是 "when you have space" 的
      **触发时点/上界**: XML 无触发 tag、wiki 无 Notes、引擎
      `combat_summon_log` 只写不读且无"棋盘腾位"事件; 直译为 AFTER_ATTACK
      补位正是 SOP §13 item 3 明令禁止的无限补位形态（历史实测 2001 轮
      CombatLoopError）——必须由主线给出有界协议与终止性证明。
    Implementation path: 战斗内腾位事件（有界）+ 首个死亡 Mech 快照
      （已有）→ `start_of_combat` 快照 + 腾位时 `create_minion(card_id,
      golden=snapshot)` + `summon`。

    Params: 无模板参数（BG30_MagicItem_440 num(0..4) 全 None;
            script_data_num_2=99 为内部参数不参与文本）
    """


class AncientWishboneScript:
    """
    Natural language: Your Hero Power triggers twice.

    Status: DEFERRED — 技能**效果结算**翻倍配额缺失
    （**已被 batch_trinkets32 取代注册** 2026-09-15——本类仅存台账）

    Dependency: `hero.extra_triggers` 现有 `hp_uses` = 每回合**使用次数**
      +N，无"单次使用效果结算两次"的读取点（`_finish_hero_power` 只调用
      `script.hero_power` 一次）。用 `hero_power_used` 监听在饰品侧重放
      被 SOP §15 禁止（载荷无 target、passive 技能无钩子、会绕过计次）。
      是否翻倍被动技能亦无权威。
    Implementation path: 引擎新增独立配额 `hp_times`，在 `_finish_hero_power`
      的脚本调用处形如 `for _ in range(1 + extra_trigger("hp_times"))`。

    Params: 无模板参数（BG30_MagicItem_804 num(0..4) 全 None）
    """


class FishyStickerScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Summon a Golden Fish of
    N'Zoth that copies <b>Deathrattles</b>.

    Status: DEFERRED — 金色定义 → 基础脚本回落协议缺失

    Dependency: 关联卡 `evolution_card_id=67216` → `TB_BaconUps_307`
      **金色** Fish of N'Zoth 无脚本（REGISTRY 运行核验）; 基础版
      `TB_BaconShop_HP_105t` 已注册（batch_hero_econ3）但
      `create_minion(card_id, golden=True)` 解析金色独立定义后按金色 id
      绑脚本 → 白板（效果整体落空）。引擎无"金色定义存在但无脚本 →
      显式回落到基础脚本"的审计协议（ENGINE_BACKLOG §B15）。
    Implementation path: 引擎在脚本绑定处增加**显式审计**的金色回落 +
      金色 Fish of N'Zoth 的"gain its Deathrattle twice"分支。

    Params: 无模板参数（BG30_MagicItem_821t2 num(0..4) 全 None）
    """


class TwinSkyLanternsScript:
    """
    Natural language: [x]When you have space, summon a copy of the first
    minion you summon each combat.

    Status: DEFERRED — 战斗内"腾位"触发协议 + 首召唤快照语义缺失
    （**已被 batch_trinkets32 取代注册** 2026-09-15——本类仅存台账）

    Dependency: 同 440; 另需"战斗内首个召唤物"的快照（card_id + 属性 +
      buff?）以及 "a copy" 是白板副本还是精确副本的权威（XML 只有
      TRIGGER_VISUAL + script_data_num_2=1，wiki 无 Notes）。
    Implementation path: 有界腾位协议 + 首召唤快照 + copy 语义裁定。

    Params: 无模板参数（BG30_MagicItem_822 num(0..4) 全 None）
    """


class CowrieNecklaceScript:
    """
    Natural language: Tavern spells that give stats cost (2) less.

    Status: DEFERRED — "give stats" 酒馆法术子集折扣读取点缺失

    Dependency: `TAVERN_SPELL_COST_MOD` 是**无条件**的 hero 级静态 tag
      （`buy_from_tavern` 直接相减），无"法术类别/效果类型"谓词读取点;
      "give stats" 子集的类别标记在数据/引擎均不存在。
    Implementation path: 引擎增按类别/谓词的法术折扣规则（形如
      `hero._tavern_spell_cost_rules`），并在数据层导出 give-stats 类别。

    Params: 无模板参数（"cost (2) less" 文本字面量;
            BG35_MagicItem_921 num(0..4) 全 None）
    """


# BG35_MagicItem_922 Tide Raiser Portrait 已由 batch_trinkets38 注册
# （2026-09-17: `cast_spell_effect` 广播 `spell_resolved`，战斗上下文经
#  `game.in_combat`；载荷 BG34_920 已注册）→ 占位 DEFERRED 台账删除。


class BewitchedRibbonScript:
    """
    Natural language: [x]Whenever you cast a spell, give your minions
    +{0}/+{1} permanently. <i>(+{2}/+{4} while in combat!)</i>

    Evidence: [AUTHORITY FOUND: `data/bg_trinkets.json BG35_MagicItem_923`]
      （Greater, `spell_school=12`, cost 4; `script_data_num_1=1`,
      `_2=1`, `_3=2`, `_5=2` → `num(0/1/2/4)`）;
      [AUTHORITY FOUND: wiki.gg `Battlegrounds/Bewitched_Ribbon`（2026-
      09-18 取，oldid=904582）] 卡面逐字 "Whenever you cast a spell, give
      your minions +1/+1 permanently. (+2/+2 while in combat!)" + 标签表
      `TAG_SCRIPT_DATA_NUM_1=1 / _2=1 / _3=2 / _5=2`; **决定性的权威是
      卡面同一句里的 "…permanently" 本身**: 授予与 "permanently" 写在同一
      次 "give … +{0}/+{1} permanently" 子句中，括号只是该次授予在战斗内
      的数值档（`NUM_3`=战内攻击 / `NUM_5`=战内生命）——zhCN/JA/KO 把括号
      渲染为**替换**语义（"战斗中改为+{2}/+{4}"），即括号不引入第二次独立
      授予; **Patch changes（35.2.2/35.6.2）仅作旁证**: 历次补丁只改括号
      里的数（35.2.2: `(+3/+3 …)` → `(+3/+2 …)`; 35.6.2: → `(+2/+2 …)`），
      基础 +1/+1 与 "…permanently" 从未移动——这与"括号是同一次永久授予的
      战内数值档"一致，但它**不是排除性证明**（补丁史只能佐证，不能单独
      证伪另一读法）;
      [AUTHORITY FOUND: 官方 S14 饰品全表（Blizzard 论坛 163710）] 本卡
      列于 Greater "Staying"（**仅证实可获得性**，该段不给效果文本——
      勿引用为效果权威）;
      [AUTHORITY FOUND: RULES §3.5]（战斗期 buff 战后消失 = 招募期 buff
      永久）→ "permanently" 的战斗内份量**必须跨战斗保留**，即
      `Buff(persist=True)`（RULES §3.5 例外 4）;
      [AUTHORITY FOUND: batch_trinkets15.BloodboundEarringsScript /
      batch_trinkets13.SurveyorPortraitScript 先例] "Whenever you cast a
      spell" 的时点 = `spell_resolving`（每次施放一次，含效果施法/
      双施; 不用 `card_played`——SOP §16c item 36）;
      [AUTHORITY FOUND: `batch_deathrattle2.PlaguerunnerScript` /
      `batch_misc.StalwartKodoScript` 先例] "while in combat" 的战斗
      上下文 = `game.in_combat`。

    Formal spec:
      1. on_bind: 注册持久监听器 `Listener(event="spell_resolving",
         owner=source)`（owner=饰品 → 离场自动注销）。
      2. 回调条件: `spell.controller is 本人`（"you cast"——对手施放不
         触发; 闭包默认参数防晚绑定 SOP §12 item 1）。无其它限定 →
         全法术域（酒馆法术 / Spellcraft / 手牌血宝石 / 效果施法）。
      3. 数值: 战斗中（`game.in_combat` 为真）用 `num(2)/num(4)`
         （=2/2——"while in combat!"）; 否则 `num(0)/num(1)`（=1/1）。
         两者皆写入同一句 "give ... permanently" → `persist=True`。
      4. 目标 = 本人棋盘全部**存活**随从（`Buff` Action 逐只，`atk`/
         `health` 同额; `source_id=本饰品 id` 供审计）。空板落空。
         不指定 `temporary`（文本无 "this turn"）；`persist=True` 是
         "permanently" 的唯一表达（非战斗授予本就在招募期永久，标记
         只在战斗内生效，语义等价）。
      5. 数值缺失 → `GameStateError`（fail-loud，禁止硬编码）。

    Test: test_batch_trinkets31.py — 真实 `game.grant_trinket` + 真实
      `game.play_spell`: 招募期施放后全部己方存活随从 +num(0)/+num(1)
      （对照无饰品只 +1/+1）/ 招募期该批 `Buff` 的 `persist`/`source_id`
      身份 / 真实 `run_combat` 内 `cast_spell_effect`（Tide Raiser 亡语）
      后该次授予**跨战斗保留** +num(2)/+num(4)（对照无饰品 = 回滚）/
      同一场战斗内非持久战内增益仍被回滚（负对照——证明只重放 persist
      附魔）/ 对手施放不触发（owner 隔离）/ 空板落空不报错 /
      num(0..4) 双向钉死。

    Params: {0}=num(0)=1 {1}=num(1)=1 {2}=num(2)=2 {4}=num(4)=2
            （BG35_MagicItem_923）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        d = game.db.get(source.card_id)
        values = tuple(d.num(i) if d is not None else None
                       for i in (0, 1, 2, 4))
        if any(v is None for v in values):
            raise GameStateError(
                f"{source.card_id}: missing num(0/1/2/4) template param")
        out_atk, out_health, in_atk, in_health = values

        def on_resolving(g, spell=None, _h=h, **kw):
            if spell is None or getattr(spell, "controller", None) is not _h:
                return
            atk = in_atk if g.in_combat else out_atk
            health = in_health if g.in_combat else out_health
            targets = [m for m in _h.board if not m.dead]
            if not targets:
                return
            g.run_actions([
                Buff(m, atk=atk, health=health, persist=True,
                     source_id=source.card_id) for m in targets])

        game.events.register(Listener(event="spell_resolving", owner=source,
                                      callback=on_resolving))
        return None


class CyclistPortraitScript:
    """
    Natural language: [x]Get a Showy Cyclist. Your Showy Cyclists'
    <b>Deathrattles</b> give permanent stats.

    Evidence: [AUTHORITY FOUND: `data/bg_trinkets.json BG36_MagicItem_362`]
      （Greater, `spell_school=12`, cost 4, `evolution_card_id=115565` →
      `BG31_925` Showy Cyclist; `num(0..4)` 全 None = 无模板参数，数值
      全部来自载荷卡）;
      [AUTHORITY FOUND: 官方 S14 表同帖 Greater "Cyclist Portrait | 4 |
      Get a Showy Cyclist. Your Showy Cyclists' Deathrattles give
      permanent stats."] —— 与卡面逐字一致;
      [AUTHORITY FOUND: RULES §3.5 + wiki.gg `Battlegrounds/Showy_Cyclist`
      Notes（"Fixed a bug where Showy Cyclist's Deathrattle effect wasn't
      copied by cards that inherited Deathrattles"，32.2.0）] 载荷亡语在
      **战斗中**触发的 `+num(1)/+num(3)` 按 §3.5 本应回滚 →
      "give **permanent** stats" 的精确内容 = 该次授予**跨战斗保留**
      （`Buff(persist=True)`，RULES §3.5 例外 4）;
      [AUTHORITY FOUND: batch_trinkets22 台账] 载荷 `BG31_925`/`BG31_925_G`
      已由 batch_deathrattle 注册（`ShowyCyclistScript.deathrattle`）;
      [AUTHORITY FOUND: `hsrl2/game.py::Game.grant_trinket_related_card` +
      `batch_trinkets37/38` 先例] "Get a Showy Cyclist" = 数据链交付 1 张
      （非池卡 → 零池操作; 满手 `pending_hand_add` 排队）。

    Formal spec:
      1. on_bind:
         a) `game.grant_trinket_related_card(hero, source.card_id)` ——
            数据链 `evolution_card_id=115565` → `db.by_dbf` → `BG31_925`。
         b) 在 `hero` 上登记**家族持久化规则**（引擎
            `Game.add_persist_source(hero, source, {SHOWY_CYCLIST})`，
            RULES §3.5 例外 4）: 命中集 = 家族基础卡 id 集
            （`TRIPLE_BASE_CARD_ID` 回落覆盖金色）。载荷
            `ShowyCyclistScript.deathrattle` 在授予时读
            `game.persist_source_id(hero, source)`，非空即把该次
            `Buff` 标为 `persist=True, source_id=<来源饰品>` → 战斗内
            触发的亡语增量跨战斗保留（战斗中不改数值; 对照无饰品 =
            回滚）。
      2. 家族身份: `TRIPLE_BASE_CARD_ID` 回落（金色 `BG31_925_G` →
            `BG31_925`）——RULES §2.3; 无独立金色饰品定义。家族/复制
            语义**由卡面直接支持**: "**Your** Showy Cyclists'
            Deathrattles give permanent stats" 是该**卡家族**的属性
            （"Your Showy Cyclists'" 限定的是家族身份，不是增益接受者）。
            **范围注记**: 同一亡语被复制到**非家族**随从上时，它已不再是
            "Your Showy Cyclists' Deathrattle" ⇒ 该次授予不持久化
            （已由负对照断言，非静默近似）。
      3. 只作用于**持有者**的 Showy Cyclist（"Your"——对手亡语不保留;
           规则挂在 hero 上，`battlecry` 之外的召唤路径同样覆盖）。
      4. 来源=饰品实体: 生命周期在**读取时**判定
           （`Game._persist_source_entry`: source 必须仍在
           `hero.trinkets`/`quest_rewards`/`board`）——饰品离场/替换即
           规则失效，无需显式注销（与 `add_giver_bonus` /
           `add_family_flag` 同构）。
      5. 数值: 全部来自载荷 `BG31_925` 的 `num(1)`/`num(3)`（亡语脚本
           自读，饰品不重复读取; 无模板参数 → 无 fail-loud 分支）。

    Test: test_batch_trinkets31.py — 真实 `game.grant_trinket` 后入手
      1 张 BG31_925（数据链核实）/ 规则命中集含基础+金色、排除非家族
      与对手（`minion_persist_source`/`persist_source_id`）/ 真实
      `run_combat` 中 Showy Cyclist 死亡 → 己方 Naga 的亡语增量跨战斗
      保留 +2/+1（对照无饰品 = 回滚）/ 复制到**非家族**随从的同一亡语
      增量仍回滚（负对照——证明按来源过滤而非实体全量）/ 非家族亡语
      回滚 / 饰品离场后规则失效 / 战斗外同一亡语照常永久（正对照）/
      `add_persist_source` 的 W3 参数校验（None hero/None source/空集）
      与重复登记合并。

    Params: 无模板参数（BG36_MagicItem_362 num(0..4) 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        if game.trinket_related_card(source.card_id) is None:
            raise GameStateError(
                f"{source.card_id}: evolution_card_id broken data chain")
        game.grant_trinket_related_card(h, source.card_id)
        game.add_persist_source(h, source, {SHOWY_CYCLIST})
        return None


class MultilayeredShieldScript:
    """
    Natural language: [x]Your Tavern spells give an extra +{0}/+{1}.
    <i>(Improved by each different friendly minion type!)</i>

    Status: DEFERRED — 动态 `TAVERN_SPELL_EXTRA_*` 提供者 + 增量口径无权威

    Dependency: (a) `TAVERN_SPELL_EXTRA_ATK/HEALTH` 是静态 hero tag，
      唯一读取点 `racefx.tavern_spell_buff` 在法术结算时一次性读取;
      本卡的额外值随**棋盘不同随从类型数**实时变化（入场/死亡/出售/
      金色化/Transform/战斗复原/换入），静态写入无法表达，且脚本侧
      覆盖式写入会吞掉他源贡献（SOP §16b item 32; 空转标记禁止）;
      (b) "每个类型"增量口径（`num0*(1+T)` vs `num0*T`）无权威
      （印面值 +1/+2 是基准还是 1 类型时的值不可辨）。
    Implementation path: `racefx.tavern_spell_buff` 增加动态提供者
      `hero.tavern_spell_extra_providers`（读取时校验 source 仍在场，
      与 `race_auras`/`add_tier_aura` 同构）+ 增量口径权威。

    Params: {0}=num(0)=1 {1}=num(1)=2（BG36_MagicItem_373）
    """


# ══════════════════════════════ 注册 ══════════════════════════════


# DEFERRED 35 张**不注册**——逐张台账见各类 docstring（SOP §6b 二态铁律）。
# 440 Boom Controller / 804 Ancient Wishbone / 822 Twin Sky Lanterns 已由
# batch_trinkets32 注册（2026-09-15）→ 移出本台账。
# 828 Shaker Portrait / 944 Redeemer Portrait 已由 batch_trinkets33 注册
# （`hero.giver_bonus` 家族给予者加成通道，2026-09-13）→ 移出本台账。
# 804 Selfless Portrait 已由 batch_trinkets35 注册（RULES §7.4.17
# 条件化战吼协议，2026-09-13）→ 移出本台账。
# 803 Macaw Portrait 已由 batch_trinkets36 注册（RULES §7.4.17 条件化
# 战吼第二消费者，2026-09-13）→ 移出本台账。
# 803 Kaboom Bot Portrait / 820 Impulsive Portrait 已由 batch_trinkets39
# 注册（2026-09-18: RULES §7.4.16 家族行为开关通道——家族亡语伤害加成
# `FLAG_KABOOM_DR_BONUS` 逐实例 +10 / 亡语目标集合 `FLAG_IMPULSIVE_ADJACENT`
# 改为相邻 + 6/6 覆盖式交付）→ 移出本台账。
_DEFERRED_IDS = (
    # REWINDER / BALLADIST / CZARINA / IMPLICATOR / FELBLOOD 已由本批注册
    # （2026-09-19，owner 权威序解冻——wiki 页均无 Notes 段 → 卡面天然语言:
    # "also give X" 增量 = 同句既有量; 见各类 docstring）→ 移出本台账
    CONDUCTOR_PORTRAIT, AZERITE_PORTRAIT,
    # GOOSE_PORTRAIT 已由 batch_goose_lucky_egg 注册（2026-09-17: 次生载荷
    # BG30_104/_G + 饰品本体）→ 移出本 DEFERRED 台账
    BATTLECRUISER_PORTRAIT,
    # BRONZEBEARD / SMUGGLER / ENFORCER / DRAKKARI PORTRAIT 已由
    # batch_family_races 注册（2026-09-21，RACES 家族类型身份改写 +
    # owner 作用域）→ 移出本 DEFERRED 台账（仍计入本批 41 张作业范围）
    PUTRICIDE_STICKER, TICKATUS_STICKER, YOGG_PASTRY, CORRUPTED_TOME,
    SAFETY_PATCH, TIMEWORN_CANDELABRA,
    TOKEN_OF_THE_OLD_GODS, MARINE_SIGNET, GEM_DONATION, WAX_IMPRINTER,
    # WEARY_PORTRAIT 已由 batch_trinkets37 注册（2026-09-14: 载荷已在 +
    # Reinvigoration 加 permanent_spellcraft 分支 → Reborn 永久保留）
    # → 移出本 DEFERRED 台账（仍计入本批 41 张作业范围）
    # FISHY_STICKER 已由 batch_misc_final 注册（2026-09-02：金色→基础卡
    # 脚本回落 `Game._script_for` 落地）→ 迁出本 DEFERRED 台账
    # BEWITCHED_RIBBON / CYCLIST_PORTRAIT 已由本批注册（2026-09-18:
    # `Buff(persist=True)` 按来源跨战斗持久化原语 + 来源规则读取点
    # `Game.add_persist_source` / `Game.persist_source_id`）
    # → 移出本 DEFERRED 台账（仍计入本批 41 张作业范围）
    COWRIE_NECKLACE,
    MULTILAYERED_SHIELD,
)


def register() -> List[str]:
    """注册饰品第 31 批复评批 8 张（Felemental / Bewitched Ribbon /
    Cyclist Portrait + 2026-09-19 解冻的 A 组 5 张: Rewinder / Balladist /
    Czarina / Implicator / Felblood Portrait）。

    DEFERRED 19 张（2026-09-02 原始 34 张；821t2/828/944/274/803/804/933/
    777/922/923/362/803(BG30 Kaboom)/820(Impulsive) 及 2026-09-19 的
    A 组 5 张已相继迁出）**不注册**——逐张台账见各类 docstring
    （SOP §6b 二态铁律）。
    """
    from hsrl2.scripts.registry import register as reg

    reg(FELEMENTAL_PORTRAIT, FelementalPortraitScript)
    reg(BEWITCHED_RIBBON, BewitchedRibbonScript)
    reg(CYCLIST_PORTRAIT, CyclistPortraitScript)
    reg(REWINDER_PORTRAIT, RewinderPortraitScript)
    reg(BALLADIST_PORTRAIT, BalladistPortraitScript)
    reg(CZARINA_PORTRAIT, CzarinaPortraitScript)
    reg(IMPLICATOR_PORTRAIT, ImplicatorPortraitScript)
    reg(FELBLOOD_PORTRAIT, FelbloodPortraitScript)
    return [FELEMENTAL_PORTRAIT, BEWITCHED_RIBBON, CYCLIST_PORTRAIT,
            REWINDER_PORTRAIT, BALLADIST_PORTRAIT, CZARINA_PORTRAIT,
            IMPLICATOR_PORTRAIT, FELBLOOD_PORTRAIT]
