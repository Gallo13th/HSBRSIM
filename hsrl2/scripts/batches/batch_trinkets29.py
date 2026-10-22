"""批次 trinkets29 — 饰品第二十九批（2026-09-14，30 张合并复评批）。

台账来源: 派发作业单给定的 30 个 id。这 30 张恰是
`batch_trinkets27` 的 15 张 DEFERRED（402/416/418/431/439/440/707/711/
777/803/804/821t2/822/825/828）∪ `batch_trinkets28` 的 15 张 DEFERRED
（868/869/944/971/987/994/179/274/283/300/417/803/804/806/809）——
两批（同日 2026-09-14）各自的"未解冻"并集。本批按引擎**当前状态**逐张
重新核验（SOP §6b 二态铁律），不引用旧批结论作为终点。
（274 / 803 / 804 后已分别由 batch_trinkets34 / batch_trinkets36 /
batch_trinkets35 注册、777 由 batch_goose_lucky_egg 注册（2026-09-17）→
迁出本批 DEFERRED 台账; 上列 30 张仅为本批 **原始作业范围**。）

运行核验（`CardDB` 实读，2026-09-14）:
  - 30/30 在 `CardDB` 存在; 30/30 在 `CardDB.trinket_offer_pool()` 中
    （含 `BG30_MagicItem_821t2` Fishy Sticker——其 `t2` 后缀**无同名
    本体**，是独立商店本体，非升级变体）;
  - 30/30 在本批之前**全部不在** `REGISTRY`（与 batch_trinkets1..28 注册
    集合互不相交）;
  - 数值一律 `CardDef.num(i)` 直读（本批 7 张有模板参数: 440 num(1)=99、
    707 num(0)=3、711 num(0)=4/num(1)=1、777 num(0)=3、822 num(1)=1、
    944 num(0)=4/num(1)=4、300 num(0)=2; 其余 23 张 num(0..4) 全 None）;
  - 关联卡一律数据链 `CardDef.evolution_card_id` → `CardDB.by_dbf`
    （RULES §7.4.6），零硬编码卡 id（见文末台账）;
  - 本批**无随机、无状态写入**（0 张注册）——不存在 `game.rng` /
    game 级 flag / 私有标记的接线风险（SOP §12 item 9）。

**本批结论: CORRECT 0 张 / DEFERRED 17 张 → 13 张**（原始作业范围 30 张;
13 张已由后续批次注册迁出，含 777 / 803（BG30）——见上; **2026-09-21
再迁出 4 张**: 418 / 825 / 971 / 179 由 `batch_family_races` 注册
（RACES 家族类型身份改写 + owner 作用域））。
═══════════════════════════════════════════════════════════════════════
  余下 17 张逐张复评后，**没有任何一张**能用现有原语表达为语义精确的实现；
  没有任何一张因"新原语"而解冻。逐张的 Status / Dependency /
  Implementation path 见各脚本类 docstring（本批不注册，故各类**不带
  任何钩子方法**——避免"注册但 no-op"的第三态，也避免 W1 死钩子）。

**作业单"已就绪原语"清单逐条核对（本批无消费点）**
═══════════════════════════════════════════════════════════════════════
  | 原语 | 本批候选卡 | 核验结论（为何仍不解锁） |
  |------|-----------|------------------------|
  | `TRIPLE_THRESHOLD` | 439 Designer Eyepatch | **hero 级全域单值**（`game.py::check_for_triple` L1074 `hero.get(GameTag.TRIPLE_THRESHOLD, 3)`），文本是 **Pirate 限定**（数据 `subset_pirate=1`）。写入 2 会让**所有**随从 2 份成金 = 过度适用（近似实现，SOP §6b 禁止）。缺 per-race 阈值读取点。 |
  | `trigger_deathrattle` | 804（BG32）Selfless Portrait（**已迁出 batch_trinkets35**） | 统一入口就绪; 归属读取点已由**条件化战吼**协议补齐（RULES §7.4.17）: 载荷 `SelflessHeroScript` 声明 `battlecry_flag` 并复用同一结算函数，饰品侧只写家族开关。2026-09-13 由 batch_trinkets35 注册。 |
  | `destroy_minion`+`minion_destroyed` | — | 本批无 Destroy 条款卡。 |
  | `spell_resolved` / `spell_resolving` | — | 本批无施法被动卡（416 是 Spellcraft **法术本体**缺两段选择链，见下）。 |
  | `gold_gained` | — | 本批无金币观察卡（402 的 "gain 4 Gold" 属未注册载荷 `BG28_585`）。 |
  | `MINIONS_SOLD_THIS_TURN` | 809 Gem Donation | 事件/计数就绪，但 "plays its Blood Gems" 的**宝石枚数读法无权威**（三种候选，SOP §6b 第 4 步）——原语就绪 ≠ 语义确定。 |
  | `TAVERN_OFFER_TIER_EXACT`+`TAVERN_EXTRA_TIER_SLOTS` | — | 本批无展示位卡。 |
  | `TAVERN_MINION_COST_OVERRIDE` | — | 本批无费用覆写卡。 |
  | `on_transform`+战斗内 Transform 持久化 | — | 本批无金色化/变身卡（821t2 是"召唤金色 token"，非 Transform）。 |
  | `_next_trinket_kind` | — | 本批无"下个饰品档位"卡。 |
  | hero 级 `CHOOSE_BOTH` | — | 本批无 Choose One 卡。 |
  | `trigger_friendly_rallies` | 803（BG32）Macaw Portrait（**已迁出 batch_trinkets36**） | 该原语是"触发**己方全部 Rally**"（EoT 用），而本卡要求"Macaw 自己的 Rally **额外**触发最左战吼"——语义不同，故未采用; 803 的追加项改由 RULES §7.4.17 条件化战吼（§7.4.16 家族开关 + 载荷 `rally` 消费 `FLAG_MACAW_EXTRA_BATTLECRY`）实现，"left-most Battlecry"资格集口径由 32.2 论坛复现串裁定（2026-09-13）。 |
  | `minion_consumed` 载荷 | — | 本批无吞噬卡。 |
  | `racefx.elemental_give_bonus` | 431 Azerite Portrait | 该原语是"己方元素 give-stats 的额外值"唯一消费点（RULES §7.4.6c），而本卡改写的对象是**未注册**的 `BG28_707` Living Azerite（"给**馆内**元素 +{0}/+{1}"）→ 无行为可改写。 |
  | `grant_card_copy_to_hand(golden=)` | 987 Balladist Portrait（"每回合再得一张"） | 交付侧就绪，但同卡第二条款 "also give Attack" 的**增量无数据字段**（`BG26_814` base/golden/饰品 num 均 None）→ 整卡不可 CORRECT。 |
  | `grant_trinket(duplicate=)` | — | 本批无副本条款卡。 |
  | `add_tavern_entity`+`tavern_entity_added`+`tavern_refresh_complete` | — | 本批无入馆/刷新窗口卡（806 的 "add an Upgrade **to it**" 是逐实体附着，`add_tavern_entity` 只能放入新实体）。 |
  | `cast_spell_effect` | — | 本批无效果施法卡。 |
  | `add_permanent_spellcraft_rule` | — | 本批无 Spellcraft 永久化卡。 |
  | `add_tier_aura` | — | 本批无档位光环卡。 |
  | `CardDef.num(0..4)`（NUM_5） | 711 / 300 / 707 / 440 / 777 / 822 / 944 | 本批 7 张有参数的卡**全部**能取到 num（逐张见 `Params:`）；NUM_5 导出对本批**零影响**（无卡缺 {4}/{5} 通道）。 |
  | `batch_payload_minions` 14 张载荷 | 803/804/944/971/274/283（+868 的 Soul Rewinder） | 载荷**本体**已注册; "also/extra/改写目标集"的**读取通道**多数缺失（该批模块 docstring L107-112 自述"Nalaa 另缺 extra 通道 / Lightfang 另缺 RACES"）——274 已由 batch_trinkets34、803 已由 batch_trinkets36、804 已由 batch_trinkets35 补齐读取点并迁出; 其余逐张见下 A 类。 |

**A. 载荷/家族改写通道缺失（15 张）——载荷脚本须先加读取点**
═══════════════════════════════════════════════════════════════════════
  - 402 Conductor Portrait — 弃牌系统（无 `CARD_DISCARDED`/`discard_card`）
    + 载荷 `BG28_585` 未注册。
  - 431 Azerite Portrait — 载荷 `BG28_707` Living Azerite 未注册。
  - 777 Goose Portrait — ✅ 已迁出（2026-09-17，batch_goose_lucky_egg）:
    载荷 `BG29_801` 已由 batch_remaining2 注册; 次生载荷
    `BG30_104`/`BG30_104_G` Lucky Egg 由 batch_goose_lucky_egg 注册
    （战吼 Discover 金色 T3/T4 后变形自身）→ 饰品本体同批注册
    （计数条款 = `num(0)=3` + Fledgling token 家族）。
  - 803（BG30）Kaboom Bot Portrait — ✅ **已迁出 batch_trinkets39**
    （2026-09-18）。载荷面（`BG_BOT_606`/`TB_BaconUps_028`，batch_remaining2
    2026-09-16）本就关闭; 两条残余阻塞均已消除: (a) 家族亡语伤害加成读取点
    = RULES §7.4.16 `family_flags`（Bristlebach 先例）; (b) 金色 "twice" 下
    +10 的口径按 owner 权威序裁定为**逐实例**（每实例 4+10=14; 金色
    14+14）——wiki `Battlegrounds/Kaboom_Bot_Portrait`（oldid=921183）
    **无 Notes 段**（2026-09-16 复核）→ 卡面天然语言; 否决"总额 +10 一次"
    （18 无法在两条各自独立选取目标的伤害实例间分配）。
  - 825 Smuggler Portrait — 载荷 `BG21_013` Whelp Smuggler 未注册
    （其"获得攻击力"触发缺 `stats_gained` 观察点——见类 docstring）+
    "are Dragons" **单值**家族类型改写（无写-读点；非 `RACES` 集合缺口）。
  - 828 Shaker Portrait — 载荷 `BG26_505` 已注册，但 "give an **extra**
    copy" 须改 `ZestyShakerScript` 私有记账（其"每回合一次"闸在载荷内）。
  - 868 Rewinder Portrait — `BG26_174` Soul Rewinder 已注册，但
    "also gain Attack" **增量无权威** + 第二关联卡（Wrath Weaver）无数据链。
  - 869 Felblood Portrait — 载荷 `BG29_873`/`BG29_877` 均未注册。
  - 944 Redeemer Portrait — `BG28_551` Nalaa 已注册，无 "extra +{0}/+{1}"
    通道（增量**有**权威 num(0)=num(1)=4）。
  - 987 Balladist Portrait — `BG26_814` 已注册，无 "also give Attack" 通道
    + 增量无数据字段。
  - 274（BG32）Bristlebach Portrait — `BG26_157` 已注册，无 target-scope
    改写通道（本体写死 `race in (QUILBOAR, ALL)`）。
  - 283（BG32）Czarina Portrait — `BG28_741` 已注册，无 "also give Health"
    通道 + Health 增量无数据字段。
  - 803（BG32）Macaw Portrait — `BGS_078` 已注册; "left-most Battlecry"
    资格集由 32.2 论坛复现串 `M G x B y z`（跳过非战吼 x）裁定为最左
    **带战吼**者，配合条件化战吼协议（RULES §7.4.17）→ **已迁出
    batch_trinkets36**（2026-09-13）。
  - 804（BG32）Selfless Portrait — `BG_OG_221` 已注册; "also trigger on
    Battlecry" 读法由 32.4 补丁说明（Snicker Snacks 条目）裁定为"打出本体
    即触发其亡语"，配合条件化战吼协议（RULES §7.4.17）→ **已迁出
    batch_trinkets35**（2026-09-13）。
  - 806 Battlecruiser Portrait — `BG31_HERO_801pt` 未注册 + "12/12" 交付体
    + Battlecruiser Upgrade **附着**子系统（`BG31_HERO_801pta..j`）。

**B. 多值种族身份 `RACES`（4 张，ENGINE_BACKLOG §A1/§B2-4 与「C 组 RACES
权威核查」（2026-09-19 复核）；825 与 A 类重叠 = 双重阻塞）**
═══════════════════════════════════════════════════════════════════════
  `BG30_MagicItem_418` Bronzebeard Portrait（"both Murlocs and Dragons" = 2
  类）/ `BG30_MagicItem_825` Smuggler Portrait 的种族条款（"are Dragons" =
  **单类型**，非集合） / `BG30_MagicItem_971` Enforcer Portrait（"have all
  minion types"）/ `BG32_MagicItem_179` Drakkari Portrait（"both Mechs and
  Elementals" = 2 类）。**id 前缀订正**: 825 是 `BG30_…`、179 是 `BG32_…`
  （旧记相反）。**载荷状态**: `BGS_009`+`TB_BaconUps_082` /
  `BG26_ICC_901`+金色 / `BG_LOE_077`+金色 均已注册; `BG21_013`/`_G`（825
  载荷）**未注册**（旧记"dbf 72072 不解析"不成立——72072 正是
  `BG21_013`）。
  `GameTag.RACE` 单值，`Race.ALL` 语义是"匹配一切类型"而非"同时属于这
  两个"——写入 `Race.ALL` 会让 Drakkari 同时成为野兽/龙/野猪人…（超出
  文本给出的两个），是近似实现。缺 `RACES` 集合 tag + 全部 race 读取点
  改造。**成员集合有权威**（卡面 + `CardDefs.xml` 的 `CARDRACE` ∪
  per-race tag，`RaceTagMap.xml` 2522–2556）；**消费者口径无权威**（部分
  多类型计数 1 vs 2 类、`of each type` 重复命中、饰品类型关联、入池过滤、
  家族光环作用域、`RACES` 表示契约——`ENGINE_BACKLOG` 上节 N1–N7），
  且仓内三个计数口径冲突 → 不得动读取点。

**C. 子系统 / 引擎原语缺失（12 张）**
═══════════════════════════════════════════════════════════════════════
  - 416 Token of the Old Gods — 饰品 Spellcraft（`spellcraft_id=112813`
    → `BG30_MagicItem_416t`）+ **两段定向选择链**（"Choose a minion. Then
    choose a minion from a Tier higher"）。`Game.play_spell` 目标路径只有
    **单段**（`target_count` 链只存在于 `use_hero_power`，
    `inspect.getsource(Game.play_spell)` 复核零命中）。
  - 439 Designer Eyepatch — per-race 三连阈值（见上表 `TRIPLE_THRESHOLD`）。
  - 440 Boom Controller — 战斗内**有界**"腾位补召"协议（SOP §13 item 3
    明令禁止 AFTER_ATTACK 无限补位；XML 无触发 tag）。
  - 707 Tickatus Sticker — Darkmoon Prize 候选卡表（RULES §11.4 已退役
    系统；数据无 tier→prize 映射）。
  - 711 Marine Signet — "improve this" 的**档位递增**无数据字段、无官方
    权威（wiki 无 Notes；既有 "improve this" 卡全部递增**属性值**）。
  - 804（BG30）Ancient Wishbone — 英雄技能**效果结算翻倍**钩子
    （`extra_triggers` 只有 `hp_uses` = 每回合多次**使用**；
    `_finish_hero_power` 源码无 `hp_times`）。
  - 821t2 Fishy Sticker — 金色 Fish of N'Zoth `TB_BaconUps_307` 无脚本，
    引擎无"金色定义 → 基础脚本回落"（`create_minion` 直查 `REGISTRY`，
    `game.py` L2886-2888；ENGINE_BACKLOG §B15）。
  - 822 Twin Sky Lanterns — 同 440（"when you have space"）。
  - 809 Gem Donation — "plays its Blood Gems" 三种读法无权威。
  - 994 Yogg-Tastic Pastry — Wheel of Yogg-Saron（无 `spin_wheel`、无结果表）。
  - 300 Putricide Sticker — Craft 多步部件合成链（无 `Game.craft`）。
  - 417 Tarecgosa Sticker — Bonus Keyword 定义域（RULES §9.6）+ 位置/种族
    PERSIST 光环原语（双重阻塞）。

**工程缺口 → 阻塞卡映射（供主线排期；本批上报）**
═══════════════════════════════════════════════════════════════════════
  | # | 缺口（最小改造） | 阻塞卡 | 改造规模 |
  |---|-----------------|--------|---------|
  | G1 | 载荷脚本加"extra/also"读取点：`NalaaTheRedeemerScript` 读 hero 级 `nalaa_extra_atk/health`；`BristlebachScript` 读 `bristlebach_all_friendly`；`MonstrousMacawScript` 读 `macaw_extra_battlecry`；`SelflessHeroScript` 增 `battlecry` 分支；`ZestyShakerScript` 读 `shaker_extra_copies` | 944 / 274 / 828（803(32)/804(32) 已于 2026-09-13 分别由 batch_trinkets36/35 迁出） | 每个 ~3 行 + 1 测试 |
  | G2 | `RACES` 集合 tag + race 读取点集合视图（**前置: [NO AUTHORITY FOUND: 消费者解释口径] N1–N7 须先钉死**，见 ENGINE_BACKLOG「C 组 RACES 权威核查」） | `BG30_MagicItem_418` / `BG30_MagicItem_825`（单类型，或仅需家族类型改写读取点） / `BG30_MagicItem_971` / `BG32_MagicItem_179` | 引擎级（中） |
  | G3 | per-race 三连阈值（`hero.triple_threshold_by_race`，与全局取小） | 439 | 引擎级（小） |
  | G4 | 法术路径 `target_count` 链（同 `use_hero_power._chain`）+ 动态第二段候选 | 416 | 引擎级（小-中） |
  | G5 | `hp_times` 配额（`_finish_hero_power` 脚本调用处 `for _ in range(1+extra_trigger("hp_times"))`） | 804(30) | 引擎级（小） |
  | G6 | 金色定义 → 基础脚本回落（显式审计，不静默） | 821t2 | 引擎级（小） |
  | G7 | 战斗内"腾位"有界触发协议（`combat_summon_log` 读取点 + 上限） | 440 / 822 | 引擎级（中） |
  | G8 | 弃牌系统 `CARD_DISCARDED` + `Game.discard_card` | 402 | 引擎级（中） |
  | G9 | Craft 合成链 / Wheel of Yogg / Darkmoon Prize 表 | 300 / 994 / 707 | 子系统（大） |
  | G10 | 家族级伤害改写通道（Kaboom Bot "+10 damage"） | ~~803(30)~~ ✅ **已迁出 batch_trinkets39**（2026-09-18） | 读取点 = RULES §7.4.16 `family_flags`（`FLAG_KABOOM_DR_BONUS`，载荷 `KaboomBotScript` 消费）; 金色口径按 wiki 无 Notes → 卡面天然语言裁定 = **逐实例 +10**（14+14） |
  | G11 | 语义权威（非引擎）：868/987/283 增量、711 递增口径、809 宝石枚数 | 868/987/283/711/809（803/804(32) 选定口径已分别由 32.2 复现串 / 32.4 补丁说明裁定并迁出） | 查证/实测 |

**关联卡台账（RULES §7.4.6——本批 30 张中 15 张有数据链）**
═══════════════════════════════════════════════════════════════════════
  | 饰品 | `evolution_card_id` → `db.by_dbf` | 载荷脚本状态 |
  |------|-----------------------------------|-------------|
  | BG30_MagicItem_402 | 104770 → BG28_585 Snarling Conductor | 未注册 |
  | BG30_MagicItem_418 | 96786 → BG_LOE_077 Brann Bronzebeard | 已注册（池卡） |
  | BG30_MagicItem_431 | 107939 → BG28_707 Living Azerite | 未注册 |
  | BG30_MagicItem_777 | 107865 → BG29_801 Silver Goose | 已注册（remaining2; 饰品本体 + 次生载荷 BG30_104/_G 由 batch_goose_lucky_egg 于 2026-09-17 注册） |
  | BG30_MagicItem_803 | 96766 → BG_BOT_606 Kaboom Bot | 已注册（remaining2） |
  | BG30_MagicItem_821t2 | 67216 → TB_BaconUps_307 Fish of N'Zoth（金） | 未注册 |
  | BG30_MagicItem_825 | 72072 → BG21_013 Whelp Smuggler | 未注册 |
  | BG30_MagicItem_828 | 99054 → BG26_505 Zesty Shaker | 已注册 |
  | BG30_MagicItem_868 | 100949 → BG26_174 Soul Rewinder | 已注册 |
  | BG30_MagicItem_869 | 109418 → BG29_873 Slimy Felblood | 未注册 |
  | BG30_MagicItem_944 | 104468 → BG28_551 Nalaa the Redeemer | 已注册（并行批） |
  | BG30_MagicItem_971 | 59707 → BGS_009 Lightfang Enforcer | 已注册（并行批） |
  | BG30_MagicItem_987 | 99011 → BG26_814 Lovesick Balladist | 已注册 |
  | BG32_MagicItem_179 | 101314 → BG26_ICC_901 Drakkari Enchanter | 已注册 |
  | BG32_MagicItem_274 | 100997 → BG26_157 Bristlebach | 已注册（batch_trinkets34 迁本卡） |
  | BG32_MagicItem_283 | 110321 → BG28_741 Charging Czarina | 已注册 |
  | BG32_MagicItem_803 | 62230 → BGS_078 Monstrous Macaw | 已注册（batch_trinkets36） |
  | BG32_MagicItem_804 | 96769 → BG_OG_221 Selfless Hero | 已注册（batch_trinkets35） |
  | BG32_MagicItem_806 | 118684 → BG31_HERO_801pt Battlecruiser | 未注册（token） |
  无数据链（效果自含）: 416 / 439 / 440 / 707 / 711 / 804(30) / 822 /
  994 / 300 / 417 / 809（11 张，36.2.2 逐条核实 `evolution_card_id` 为空）。
  说明: 载荷本体**未注册**时按 RULES §7.4.6 只登记、不阻塞"交付类"饰品；
  但本批依赖载荷**行为**的卡（A 类）正是被该行为阻塞，故一并 DEFERRED。

**接线审计读取点（W1/W2/W3 核对）**
═══════════════════════════════════════════════════════════════════════
  - W1: 本批各类**不定义任何钩子方法**（`on_bind` / `start_of_turn` /
    `end_of_turn` / `start_of_combat` / `avenge` 全无）——不产生死钩子，
    也不存在"注册但 no-op"的第三态。
  - W2: 无 `Listener(...)` 注册 → 无死监听。
  - W3: 不写 `game._x` / `hero._x` 私有标记 → 无空转标记。
  - `register()` 返回**空列表**（0 张 CORRECT）; 台账守卫见
    `hsrl2/tests/test_batch_trinkets29.py::TestBatch29Ledger`，引擎缺口
    守卫见 `TestBatch29EngineGaps`（缺口闭合时守卫转红 → 提示解冻）。
"""

from __future__ import annotations

from typing import List

# ── 本批卡 id（CardDB 按名核实，禁止凭记忆写） ──
# A. 载荷/家族改写通道缺失
CONDUCTOR_PORTRAIT = "BG30_MagicItem_402"       # Snarling Conductor
AZERITE_PORTRAIT = "BG30_MagicItem_431"         # Living Azerite
GOOSE_PORTRAIT = "BG30_MagicItem_777"           # Silver Goose
KABOOM_BOT_PORTRAIT = "BG30_MagicItem_803"      # Kaboom Bot
SMUGGLER_PORTRAIT = "BG30_MagicItem_825"        # Whelp Smuggler
SHAKER_PORTRAIT = "BG30_MagicItem_828"          # Zesty Shaker
REWINDER_PORTRAIT = "BG30_MagicItem_868"        # Soul Rewinder
FELBLOOD_PORTRAIT = "BG30_MagicItem_869"        # Slimy/Fiery Felblood
REDEEMER_PORTRAIT = "BG30_MagicItem_944"        # Nalaa the Redeemer
BALLADIST_PORTRAIT = "BG30_MagicItem_987"       # Lovesick Balladist
BRISTLEBACH_PORTRAIT = "BG32_MagicItem_274"     # Bristlebach
CZARINA_PORTRAIT = "BG32_MagicItem_283"         # Charging Czarina
MACAW_PORTRAIT = "BG32_MagicItem_803"           # Monstrous Macaw
SELFLESS_PORTRAIT = "BG32_MagicItem_804"        # Selfless Hero
BATTLECRUISER_PORTRAIT = "BG32_MagicItem_806"   # Battlecruiser

# B. 多值种族身份
BRONZEBEARD_PORTRAIT = "BG30_MagicItem_418"     # Brann Bronzebeard
ENFORCER_PORTRAIT = "BG30_MagicItem_971"        # Lightfang Enforcer
DRAKKARI_PORTRAIT = "BG32_MagicItem_179"        # Drakkari Enchanter

# C. 子系统 / 引擎原语缺失
TOKEN_OF_THE_OLD_GODS = "BG30_MagicItem_416"    # Spellcraft 法术
DESIGNER_EYEPATCH = "BG30_MagicItem_439"        # 三连阈值
BOOM_CONTROLLER = "BG30_MagicItem_440"          # 战斗内腾位
TICKATUS_STICKER = "BG30_MagicItem_707"         # Darkmoon Prize
MARINE_SIGNET = "BG30_MagicItem_711"            # improve 档位
ANCIENT_WISHBONE = "BG30_MagicItem_804"         # 技能效果翻倍
FISHY_STICKER = "BG30_MagicItem_821t2"          # 金色 token 脚本
TWIN_SKY_LANTERNS = "BG30_MagicItem_822"        # 战斗内腾位
GEM_DONATION = "BG32_MagicItem_809"             # 血宝石枚数读法
YOGG_TASTIC_PASTRY = "BG30_MagicItem_994"       # Wheel of Yogg
PUTRICIDE_STICKER = "BG32_MagicItem_300"        # Craft
TARECGOSA_STICKER = "BG32_MagicItem_417"        # Bonus Keyword

# ⚠️ 历史台账快照（2026-09-02）已删除: 该元组列出的多数 id 此后已陆续注册
# （如 274 Bristlebach → batch_trinkets34、804 Selfless → batch_trinkets35、
# 828/944 → batch_trinkets33 …），继续保留会误导。**live 状态**见
# `hsrl2/tests/test_batch_trinkets29.py::DEFERRED_IDS`（活断言）与
# `docs/agents/TRINKET_LEDGER.md`（生成自注册表）。

# ── 载荷 / 关联卡 id（数据链 `evolution_card_id` → `CardDB.by_dbf`；
#    仅用于 docstring 台账与测试断言，运行时无脚本读取） ──
SNARLING_CONDUCTOR = "BG28_585"          # 402 载荷（未注册）
LIVING_AZERITE = "BG28_707"              # 431 载荷（未注册）
SILVER_GOOSE = "BG29_801"                # 777 载荷（已注册: remaining2）
LUCKY_EGG = "BG30_104"                   # 777 次生载荷（已注册:
                                         # goose_lucky_egg, 2026-09-17）
KABOOM_BOT = "BG_BOT_606"                # 803 载荷（已注册: remaining2）
KABOOM_BOT_G = "TB_BaconUps_028"         # 803 金色载荷（已注册: remaining2）
WHELP_SMUGGLER = "BG21_013"              # 825 载荷（未注册）
ZESTY_SHAKER = "BG26_505"                # 828 载荷（已注册）
SOUL_REWINDER = "BG26_174"               # 868 载荷（已注册）
SLIMY_FELBLOOD = "BG29_873"              # 869 载荷（未注册）
FIERY_FELBLOOD = "BG29_877"              # 869 载荷（未注册）
NALAA = "BG28_551"                       # 944 载荷（已注册）
LOVESICK_BALLADIST = "BG26_814"          # 987 载荷（已注册）
BRISTLEBACH = "BG26_157"                 # 274 载荷（已注册）
CHARGING_CZARINA = "BG28_741"            # 283 载荷（已注册）
MONSTROUS_MACAW = "BGS_078"              # 803(32) 载荷（已注册）
SELFLESS_HERO = "BG_OG_221"              # 804(32) 载荷（已注册）
BATTLECRUISER_TOKEN = "BG31_HERO_801pt"  # 806 载荷（未注册）
TOKEN_SPELL = "BG30_MagicItem_416t"      # 416 的 Spellcraft 法术（未注册）
FISH_OF_NZOTH_G = "TB_BaconUps_307"      # 821t2 金色载荷（未注册）


# ══════════════ A. 载荷 / 家族改写通道缺失 ══════════════


class ConductorPortraitScript:
    """
    Natural language: [x]Get a Snarling Conductor. Whenever you discard a
    card, this plays a <b>Blood Gem</b> on all your minions.

    Status: DEFERRED — requires 弃牌子系统 + 载荷脚本（双重阻塞）

    Dependency:
      1. 全仓零弃牌机制: `grep -rni "discard" hsrl2/` 只命中他批 DEFERRED
        docstring；无 `Game.discard_card`、无 `events.CARD_DISCARDED`
        （运行核验 hasattr 均为 False）→ "Whenever you **discard** a card"
        的触发点不存在。
      2. 载荷 `BG28_585` Snarling Conductor（数据链 104770）在 REGISTRY
        **无脚本** → "this plays a Blood Gem" 的"this"（该随从的行为）不存在。
    Implementation path: (a) 引擎实现弃牌协议（`game.discard_card(hero,
      card)` + `CARD_DISCARDED` 广播 + 手牌弃置的回池/Spellcraft 交互）;
      (b) 迁 `BG28_585`（亡语/被动"弃牌时对全体友方 `PlayBloodGems`"）;
      (c) 饰品 on_bind 走数据链交付。阻塞卡: BG30_MagicItem_402 +
      BG28_585（ENGINE_BACKLOG §B12）。
    Reference: batch_trinkets27 模块 docstring（同卡台账，本批复核维持）。

    Test: 不注册（DEFERRED）——台账守卫见
      test_batch_trinkets29.py::TestBatch29Ledger。

    Params: 无模板参数（BG30_MagicItem_402 num(0..4) 全 None）
    """


class AzeritePortraitScript:
    """
    Natural language: [x]Get a Living Azerite. Your Living Azerites also
    give stats to friendly Elementals.

    Status: DEFERRED — requires 载荷脚本（RULES §7.4.6 例外条款）

    Dependency:
      1. 载荷 `BG28_707` Living Azerite（"Whenever you cast a Tavern spell,
        give Elementals in the Tavern +{0}/+{1} this game"，num 3/2）在
        REGISTRY **无脚本** → 无"给馆内元素"的行为可供改写。
      2. "also give stats to **friendly** Elementals" 的读取点是该载荷的
        `tavern_spell_cast` 出口（须读 hero 级标记），本批不可写他批次
        脚本（SOP §12 item 2/14）。注意与 `racefx.elemental_give_bonus`
        **无关**: 后者是"己方元素 give-stats 额外值"的消费点，本卡改写的
        是**馆内元素**目标集（RULES §7.4.6c）。
    Implementation path: 先迁 `BG28_707`（战吼/被动 + 持久酒馆 Buff 面），
      再让其 `on_cast` 读 hero 级 `azerite_extra_friendly`（本饰品 on_bind
      写入 + 数据链交付）把棋盘元素并入目标集。阻塞卡:
      BG30_MagicItem_431 + BG28_707。
    Reference: batch_trinkets27 模块 docstring（同卡台账）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG30_MagicItem_431 num(0..4) 全 None）
    """


# 777 Goose Portrait 已由 batch_goose_lucky_egg 注册（2026-09-17）→
# 占位 DEFERRED 类删除（迁移轨迹见本模块 docstring A 类清单与
# test_batch_trinkets29 的 `_REGISTERED_PAYLOADS`）。


class KaboomBotPortraitScript:
    """
    Natural language: [x]Get a Kaboom Bot. Your Kaboom Bots'
    <b>Deathrattles</b> deal 10 extra damage.

    Status: ✅ **已迁出 → batch_trinkets39**（2026-09-18）。

    迁移依据（owner 权威序）: 两条原阻塞均消除。
      (a) 家族级亡语伤害改写读取点 = RULES §7.4.16 `hero.family_flags`
          + `Game.add_family_flag` / `family_flag`（Bristlebach 先例）;
          载荷 `batch_remaining2.KaboomBotScript.deathrattle` 读
          `FLAG_KABOOM_DR_BONUS` 并把 `KABOOM_EXTRA_DAMAGE`(=10) 逐实例
          并入同一次 `Hit`（`num(0) + bonus`）——不在饰品侧另算伤害
          （避免 SOP §6b / §12 item 14 的"复刻他卡伤害逻辑"近似）。
      (b) 金色 "twice" 下 +10 的口径: 复核 wiki
          `Battlegrounds/Kaboom_Bot_Portrait`（oldid=921183）**无 Notes
          段** → 按卡面天然语言**逐实例 +10**（每实例 4+10=14; 金色
          14+14=28）; 否决"总额 +10 一次"（18 无法在两条各自独立选取目标
          的伤害实例间分配，文本无 "split" 字样）。
    Reference: batch_trinkets27 模块 docstring（同卡台账）。

    Test: 已实现——见 `hsrl2/tests/test_batch_trinkets39.py`。

    Params: 无模板参数（BG30_MagicItem_803 num(0..4) 全 None;
            文本字面量 "10 extra damage" = 载荷侧 `KABOOM_EXTRA_DAMAGE`）
    """


class SmugglerPortraitScript:
    """
    Natural language: [x]Get a Whelp Smuggler. Set its stats to 12/12.
    Your Whelp Smugglers are Dragons.

    Status: **已迁出 → batch_family_races（2026-09-21）**——注册于
      `batch_family_races.SmugglerPortraitScript`（owner 级家族类型改写
      读取点 `Game.add_family_races` / `Minion.races` + Tavern/Discover
      作用域; 载荷 `BG21_013`/`_G` 已于 2026-09-20 注册）。以下保留原始
      阻塞记录。

    Dependency:
      1. ~~载荷 `BG21_013`/`_G` 未注册~~ **已闭合（2026-09-20，
        `batch_stats_gained`）**: 引擎 `stats_gained` 原语落地
        （`hsrl2/events.py::STATS_GAINED`，生产点 `Entity.add_buff`，
        复制/复原经 `suppress_stats_gained()`/`_restore_no_gain` 抑制;
        触发域逐路径裁定见 `Entity.add_buff` docstring 与
        ENGINE_BACKLOG §E），`BG21_013`/`_G` 本体已注册并带真实路径测试
        （`test_batch_stats_gained.py::TestWhelpSmuggler`）。本卡残余阻塞
        **只剩**第 2/3 条（家族类型改写读取点 + 作用域）。
      2. "are Dragons" 是**单值**家族类型改写（`NONE → DRAGON`）——
        与 418/971/179 的多值 `RACES` 集合**不同族**（825 卡面无
        "both"/"all"，单类型无需集合模型，故 `RACES` 缺口不是本卡的
        阻塞）。阻塞 = 引擎无"owner 级家族种族覆写"读取点:
        `GameTag.RACE` 单值，写点仅 `Minion.__init__` +
        `create_minion`（异变 `_notype_is_all`）; `hero.race_auras` /
        `card_auras` / `tier_auras` 是数值光环不是身份改写; 入场即打标
        会漏 Transform / 直接 `board[idx]=` 入板路径（SOP §16b item 32
        禁止）。
      3. 作用域 **[NO AUTHORITY FOUND]**（ENGINE_BACKLOG「C 组 RACES
        权威核查」N5）: "Your Whelp Smugglers are Dragons" 是否覆盖
        手牌/酒馆/池/生成物与未来副本——XML 无 scope tag、仓内无家族
        类型光环先例。
      4. "Set its stats to 12/12" 有先例（`batch_spells2.SetStats` /
        `batch_trinkets14.InnkeepersHearthScript`），非阻塞项。
    Implementation path: (a) ~~引擎落地 `stats_gained` 观察点~~ **已完成
      2026-09-20**; (b) 引擎新增 owner 级家族种族覆写读取点并钉死作用域
      （N5）; (c) on_bind 交付关联卡 + `SetStats 12/12`（文本字面量）。
      残余阻塞卡: BG30_MagicItem_825 + `BG21_013`/`_G` 的**类型改写**。
    Reference: batch_trinkets31 同卡台账（2026-09-19 复核）;
      ENGINE_BACKLOG「C 组 RACES 权威核查」AC-2/AC-7/N5;
      `batch_stats_gained`（2026-09-20 载荷解冻）。

    Test: 不注册（DEFERRED）——同上台账守卫; 载荷侧行为测试见
      `test_batch_stats_gained.py`。

    Params: 无模板参数（BG30_MagicItem_825 num(0..4) 全 None;
            文本字面量 "12/12" 未实现前不入代码）
    """


class ShakerPortraitScript:
    """
    Natural language: [x]Get a Zesty Shaker. Your Zesty Shakers give an
    extra copy of the spell.

    Status: DEFERRED — requires 载荷脚本的 extra-copy 读取通道
      （RULES §7.4.6 例外条款 + SOP §12 item 2/14）

    Dependency:
      1. 载荷 `BG26_505` Zesty Shaker **已注册**
        （`batch_econ_misc.ZestyShakerScript`）——本体可交付、行为就绪。
      2. 但其 `on_played` 回调的份数由 `copies = 2 if source.is_golden
        else 1` **写死**，不读任何 hero 级标记 → "an **extra** copy"
        无消费点。在饰品侧再注册一次 `card_played` 监听会复刻其
        "每回合一次"闸（`source._shaker_turn` 私有记账）与 SPELLCRAFT
        副本构造，属近似实现（SOP §6b/§12 item 14 禁止）。
    Implementation path: `ZestyShakerScript.on_played` 增读 hero 级
      `shaker_extra_copies`（本饰品 on_bind 写入 + 数据链交付）并把
      `copies += 该值`（金色同样叠加）。阻塞卡: BG30_MagicItem_828（G1）。
    Reference: batch_trinkets27 模块 docstring（同卡台账）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG30_MagicItem_828 num(0..4) 全 None）
    """


class RewinderPortraitScript:
    """
    Natural language: [x]Get a Soul Rewinder and a Wrath Weaver.
    Your Soul Rewinders also gain Attack.

    Status: ✅ **已迁出 → batch_trinkets31**（2026-09-19，owner 权威序: wiki 页无 Notes → 卡面天然语言）; 原阻塞 — requires 多关联卡数据链 + Attack 增量权威 +
      载荷脚本读取点

    Dependency:
      1. "Get a Soul Rewinder **and** a Wrath Weaver": 数据链
        `evolution_card_id`(100949) 只指向 `BG26_174` Soul Rewinder
        （池 T2，已注册）; Wrath Weaver **无第二条数据链**（XML
        `TAG_SCRIPT_DATA_NUM_1`(4185)=2 的语义是"生成卡数"，非第二卡 dbid）。
      2. "also gain Attack": 增量**数值无权威**——`BG26_174`/`BG26_174_G`
        CardDef num 全 None（既有脚本的 "+1 Health"/"金色 +2" 是文本
        字面量），本饰品 CardDef 亦无任何模板参数; wiki 卡页无 Notes。
      3. 读取点必须在 `SoulRewinderScript` 内（hero 级标记消费），本批
        不可写他批次脚本（SOP §12 item 2）。
    Implementation path: (a) 数据层补第二关联卡（生成器导出第二个
      `BACON_EVOLUTION_CARD_ID`）或主线裁定命名回退; (b) 增量权威落地;
      (c) `SoulRewinderScript` 读 hero 级 `soul_rewinder_bonus_atk`。
      阻塞卡: BG30_MagicItem_868（G1 + G11）。
    Reference: batch_trinkets28 模块 docstring（同卡台账）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG30_MagicItem_868 num(0..4) 全 None）
    """


class FelbloodPortraitScript:
    """
    Natural language: Get a Slimy Felblood. Your Fiery and Slimy Felbloods
    give Attack <i>and</i> Health.

    Status: ✅ **已迁出 → batch_trinkets31**（2026-09-19，owner 权威序: wiki 页无 Notes → 卡面天然语言）; 原阻塞 — requires 载荷脚本（RULES §7.4.6 例外条款）

    Dependency:
      1. 关联卡 `BG29_873` Slimy Felblood（战吼: 馆内随从 +2 生命 this
        game）与 `BG29_877` Fiery Felblood（亡语: 馆内随从 +2 攻击 this
        game）在 REGISTRY **均无脚本**（36.2.2 数据核实）→ 交付的
        Felblood 永不产生"给予"行为，"give Attack **and** Health" 的
        改写对象不存在。
      2. 读取点是这两个脚本的 `TavernBuff` 出口（须读 hero 级双属性
        标记），本批不可写他批次脚本（SOP §12 item 2）。
    Implementation path: 先迁 `BG29_873` / `BG29_877`（含金色 `_G`）;
      随后由它们读 hero 级 `felblood_extra_health` / `felblood_extra_atk`
      （本饰品 on_bind 写入 + 数据链交付）把缺失的一侧补上。阻塞卡:
      BG30_MagicItem_869（G1）。
    Reference: batch_trinkets28 模块 docstring（同卡台账）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG30_MagicItem_869 num(0..4) 全 None）
    """


class RedeemerPortraitScript:
    """
    Natural language: [x]Get a Nalaa the Redeemer. Your Nalaa the
    Redeemers give an extra +{0}/+{1}.

    Status: DEFERRED — requires 载荷脚本的 "extra" 消费通道
      （RULES §7.4.6 例外条款 + SOP §12 item 2/14）

    Dependency:
      1. 载荷 `BG28_551` Nalaa the Redeemer 已由并行批
        `batch_payload_minions` 注册——本体可交付、`tavern_spell_cast`
        行为就绪; 增量数值**本身有权威**（本饰品 num(0)=num(1)=4）。
      2. 但其 `on_cast` 直接以 `_each_type_buffs(d.num(0), d.num(1))`
        结算，**不读**任何 hero 级 "extra" 标记（该批模块 docstring
        L107-108 自述"另缺: give an extra +{0}/+{1} 家族增量通道"）。
        在饰品侧重放 `tavern_spell_cast` 会复刻 Nalaa 的"每族随机一只"
        选取与 rng 消耗，且在没有 Nalaa 时也触发 = 近似实现（SOP §6b）。
    Implementation path: `NalaaTheRedeemerScript.on_cast` 增读 hero 级
      `nalaa_extra_atk` / `nalaa_extra_health`（本饰品 on_bind 写入 +
      数据链交付）并把额外值并入**同一次** `_each_type_buffs`。阻塞卡:
      BG30_MagicItem_944（G1）。
    Reference: batch_trinkets28 模块 docstring（同卡台账）;
      `batch_payload_minions.NalaaTheRedeemerScript`。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: {0}=num(0)=4 {1}=num(1)=4（BG30_MagicItem_944）
    """


class BalladistPortraitScript:
    """
    Natural language: [x]Get a Lovesick Balladist. At the start of each
    turn, get another. Your Lovesick __Balladists also give Attack.

    Status: ✅ **已迁出 → batch_trinkets31**（2026-09-19，owner 权威序: wiki 页无 Notes → 卡面天然语言）; 原阻塞 — requires "also give Attack" 的增量权威 +
      载荷脚本读取点

    Dependency:
      1. 交付侧就绪: 数据链 `BG26_814` Lovesick Balladist（池 T4）**已注册**
        （`batch_battlecry`），"At the start of each turn, get another"
        本身可表达（`grant_card_copy_to_hand` + 池占返、满手入队）。
      2. 但 "also give Attack" 的**增量无数据字段**: `BG26_814` 的 base 与
        golden CardDef 只有 num(1)=1（"Give a Pirate +{1} Health"），
        本饰品 CardDef 无任何模板参数（num(0..4) 全 None）→ Attack 数值
        无权威（SOP §6b 第 4 步）。wiki 卡页无 Notes。
      3. 读取点必须在 `LovesickBalladistScript`（他批次）内，本批不可写。
    Implementation path: 权威落地后——(i) on_bind 注册 `start_of_turn`
      监听 → `grant_card_copy_to_hand(hero, db.get("BG26_814"))`;
      (ii) `LovesickBalladistScript` 读 hero 级 `balladist_extra_atk`
      并在 battlecry 的 Buff 上补同额 Attack。阻塞卡:
      BG30_MagicItem_987（G1 + G11）。
    Reference: batch_trinkets28 模块 docstring（同卡台账）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG30_MagicItem_987 num(0..4) 全 None）
    """


class BristlebachPortraitScript:
    """
    Natural language: [x]Get a Bristlebach. Your Bristlebachs play
    <b>Blood Gems</b> on all friendly minions.

    Status: 已迁出 → batch_trinkets34（2026-09-13，RULES §7.4.16 家族行为开关通道 `hero.family_flags`）; 原阻塞: requires 载荷脚本的 target-scope 消费通道
      （RULES §7.4.6 例外条款 + SOP §12 item 2/14）

    Dependency:
      1. 载荷 `BG26_157` Bristlebach（"Avenge (2): This plays 2 Blood Gems
        on all your Quilboar"）已由并行批 `batch_payload_minions` 注册
        ——Avenge 行为就绪（`avenge_target=2` 数据驱动）。
      2. 但其 `avenge` 把目标集**写死**为 `race in (QUILBOAR, ALL)`，不读
        任何 hero 级 target-scope 标记（该批 docstring L109-110 自述
        "另缺: play Blood Gems on all friendly minions 改写通道"）。
        在饰品侧再注册 Avenge/重放会让野猪人**双倍**吃宝石且复刻他卡
        逻辑（近似实现，SOP §6b/§12 item 14 禁止）。
    Implementation path: `BristlebachScript.avenge` 读 hero 级
      `bristlebach_all_friendly`（本饰品 on_bind 写入 + 数据链交付）决定
      目标集为全体友方。阻塞卡: BG32_MagicItem_274（G1）。
    Reference: batch_trinkets28 模块 docstring（同卡台账）;
      `batch_payload_minions.BristlebachScript`。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG32_MagicItem_274 num(0..4) 全 None）
    """


class CzarinaPortraitScript:
    """
    Natural language: Get a Charging Czarina. Your Charging Czarinas also
    give Health.

    Status: ✅ **已迁出 → batch_trinkets31**（2026-09-19，owner 权威序: wiki 页无 Notes → 卡面天然语言）; 原阻塞 — requires Health 增量权威 + 载荷脚本读取点

    Dependency:
      1. 载荷 `BG28_741` Charging Czarina（"Whenever you cast a Tavern
        spell, give your minions with Divine Shield +{0} Attack"，
        num(0)=4）**已注册**。
      2. "also give Health" 的**增量无数据字段**: `BG28_741` 只有
        num(0)=4，饰品 CardDef num(0..4) 全 None; wiki 卡页无 Notes →
        候选读法（等于 Attack 增量 / 固定 +1 / 隐藏常量）无证据可裁
        （SOP §6b 第 4 步）。
      3. `batch_econ_misc.ChargingCzarinaScript` 只给 Attack、不读任何加成
        通道; 在饰品侧另注册 `spell_resolved` 重放 = 归属错误（Czarina
        被出售后仍生效）+ 复刻他卡数值权威（近似，SOP §6b 禁止）。
    Implementation path: 权威落地后 `ChargingCzarinaScript` 读 hero 级
      `czarina_extra_health`（本饰品 on_bind 写入 + 数据链交付）并在同一
      次 Buff 上补 Health。阻塞卡: BG32_MagicItem_283（G1 + G11）。
    Reference: batch_trinkets28 模块 docstring（同卡台账）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG32_MagicItem_283 num(0..4) 全 None）
    """


class MacawPortraitScript:
    """
    Natural language: Get a Monstrous Macaw. Your Monstrous Macaws also
    trigger your left-most <b>Battlecry</b>.

    Status: 已迁出 → batch_trinkets36（2026-09-13，RULES §7.4.17 条件化
      战吼第二消费者）; 原阻塞: requires 载荷脚本的 extra-battlecry 消费
      通道 + "最左战吼"选定口径权威（口径已由 32.2 论坛复现串裁定）

    Dependency:
      1. 载荷 `BGS_078` Monstrous Macaw（"Rally: Trigger your left-most
         Deathrattle (except this minion's)"）与金色 `TB_BaconUps_135`
         已由并行批 `batch_payload_minions` 注册——Rally/亡语侧就绪。
      2. 原阻塞（2026-09-13 消除）: 其 `rally` 只触发最左**亡语**，不读
         hero 级 extra-battlecry 标记。现由 RULES §7.4.17 条件化战吼
         协议补齐（§7.4.16 家族开关 + 载荷消费
         `FLAG_MACAW_EXTRA_BATTLECRY`）。
      3. 原阻塞（2026-09-13 消除）: "left-most **Battlecry**" 资格集口径
         由 32.2 官方论坛复现串 "[32.2] Macaw Portrait + Glowgullet
         Warlord"（2025-05-15）棋盘 `M G x B y z` 裁定 = 最左**带战吼**
         者（跳过中间的非战吼 x）。引擎 `trigger_friendly_rallies` 是
         "触发己方全部 Rally"（EoT 用），语义不同，未采用。
    Implementation path: `MonstrousMacawScript.rally` 读
      `FLAG_MACAW_EXTRA_BATTLECRY` 在 Rally 时对最左带战吼随从执行
      `TriggerBattlecry`（已落地，见 batch_trinkets36）。
    Reference: batch_trinkets28 模块 docstring（同卡台账）;
      `batch_payload_minions.MonstrousMacawScript`。

    Test: 已迁出（batch_trinkets36 于 2026-09-13 注册该饰品）——原台账
      守卫见 `test_batch_trinkets29.py`。

    Params: 无模板参数（BG32_MagicItem_803 num(0..4) 全 None）
    """


class SelflessPortraitScript:
    """
    Natural language: [x]Get a Selfless Hero. Your Selfless Heroes also
    trigger on <b>Battlecry</b>.

    Status: 已迁出 → batch_trinkets35（2026-09-13，RULES §7.4.17
      条件化战吼协议; 读法由 32.4 补丁说明裁定）; 原阻塞: requires
      载荷脚本的 battlecry 附加消费通道 + "on Battlecry" 读法权威

    Dependency:
      1. 载荷 `BG_OG_221` Selfless Hero（"Deathrattle: Give a random
        friendly minion Divine Shield"）与金色 `TB_BaconUps_014` 已由并行
        批 `batch_payload_minions` 注册——亡语侧就绪（`_targets` 1/2）。
      2. 其脚本只有 `deathrattle`，**不读** hero 级标记、也没有
        `battlecry` 分支（该批 L102-104 自述"另缺 … 附加通道"）。
      3. "also trigger on Battlecry" 的读法无权威: wiki 卡页（2026-09-14
        实读）仅有 `BATTLECRY` / `3407=0` / `BACON_EVOLUTION_CARD_ID`
        Wiki tags 与 "Deathrattle-generating / Ongoing effect" 分类，
        **无 Notes 段**——"打出本体时触发其亡语"与"每次你触发战吼时触发
        己方 Selfless Heroes"两读法均未被官方文本排除（SOP §6b 第 4 步）。
        引擎 `BATTLECRY_TRIGGER` 事件与 `game.trigger_deathrattle` 入口
        就绪，但读法未定前不得实现。
      4. **补充（2026-09-13 实读 + 运行探针）**: 即便按读法 1
        （"打出本体即触发"）实现，直增 `battlecry` 钩子也会让**无饰品时**
        的 Selfless Hero 被静态门禁 `_has_battlecry_hook` 判为战吼随从
        （实测 `extra_trigger_used['bc_first']` 由 0 → 1）→ 误消费 War Drum
        `BG32_MagicItem_416` 配额、误计入 `BG30_MagicItem_982`（"买 2 个战吼
        随从"）、并成为 Young Murk-Eye Sticker `BG35_MagicItem_752` 最左/
        最右战吼目标（脚本侧另有一份 `_has_battlecry_hook` 副本）。
        需引擎协议: 脚本声明**条件化战吼**（flag 名），全部
        `_has_battlecry_hook` 门禁按 `game.family_flag` 判定。
    Implementation path: 主线裁定读法后——若为"打出本体即触发"，由
      `SelflessHeroScript` 增 `battlecry` 分支（复用同一结算函数）;
      若为"每次战吼触发家族"，由 on_bind 监听 `battlecry_trigger` 并调
      `game.trigger_deathrattle`（Titus/`dr_extra` 同源，RULES §6.20）。
      阻塞卡（已消除）: BG32_MagicItem_804（G1 + G11）——2026-09-13 由
      batch_trinkets35 注册。
    Reference: batch_trinkets28 模块 docstring（同卡台账）;
      `batch_payload_minions.SelflessHeroScript`。

    Test: 已迁出（batch_trinkets35 注册）——原台账守卫见
      test_batch_trinkets29.py。

    Params: 无模板参数（BG32_MagicItem_804 num(0..4) 全 None）
    """


class BattlecruiserPortraitScript:
    """
    Natural language: [x]Get an 12/12 Battlecruiser. Whenever the Tavern is
    <b>Refreshed</b>, add a Battlecruiser Upgrade to it.

    Status: DEFERRED — requires Battlecruiser Upgrade 附着子系统（三重阻塞）

    Dependency:
      1. 关联卡 `BG31_HERO_801pt` Battlecruiser（token，数据 2/2）在
        REGISTRY **无脚本**，且本卡要求交付时属性为 **12/12**（文本字面量
        覆盖）——需"SetStats 语义"的交付体。
      2. "Battlecruiser Upgrade" 是独立子系统（`BG31_HERO_801pta..j`
        card_type=42 存在，但 Jim Raynor `BG31_HERO_801p` 整条技能链
        DEFERRED——batch_hero_combat3 台账）; db 无 Upgrade 的数据链
        （`evolution_card_id` 只指向 Battlecruiser 本体）。
      3. "add … **to it**" 是逐实体**附着**协议——`inject_tavern_minion` /
        `add_tavern_entity` 只能放入新实体，无法表达"给同一实体挂载
        升级件"（ENGINE_BACKLOG §B2-13）。
    Implementation path: 先实现 Jim Raynor 的 Upgrade 商店/附着协议
      （部件卡池 + 逐实体 upgrade 列表 + 刷新时追加），再交付 12/12
      Battlecruiser。阻塞卡: BG32_MagicItem_806 + `BG31_HERO_801p`。
    Reference: docs/agents/ENGINE_BACKLOG.md §B2-13; batch_trinkets28
      模块 docstring。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG32_MagicItem_806 num(0..4) 全 None;
            文本字面量 "12/12" 未实现前不入代码）
    """


# ══════════════ B. 多值种族身份 RACES ══════════════


class BronzebeardPortraitScript:
    """
    Natural language: [x]Get a Brann Bronzebeard and a random
    <b>Battlecry</b> minion. Your Brann Bronzebeards are both Murlocs
    and Dragons.

    Status: **已迁出 → batch_family_races（2026-09-21）**——注册于
      `batch_family_races.BronzebeardPortraitScript`（`GameTag.RACES`
      类型身份集合 + owner 家族类型改写）。以下保留原始阻塞记录。

    Dependency:
      1. 交付侧就绪: `BG_LOE_077` Brann Bronzebeard 已注册且为池卡
        （数据链 96786）; "a random Battlecry minion" 可用池感知随机挑选。
      2. "are **both** Murlocs and Dragons" 需要**同时属于两个类型**:
        `GameTag.RACE` 单值（数据 `subset_murloc` + `subset_dragon` 是
        饰品自身的展示关联，非随从身份），`Race.ALL` 是"匹配一切"——用它
        会把 Brann 错误地变成野兽/恶魔/野猪人… 全部类型（超出文本给出的
        两个）。
    Implementation path: ENGINE_BACKLOG §A1 的 `RACES` 集合 tag +
      `Minion.race` 集合视图（单值兼容读取点全改造）; 改造后 on_bind =
      数据链交付 + 对本人 Brann **实例**追加 {MURLOC, DRAGON}（未来副本
      经入板钩子），并随机交付一张带战吼的池随从。阻塞卡:
      BG30_MagicItem_418（同族 971/825/179）。
    Reference: docs/agents/ENGINE_BACKLOG.md §A1/§B2-4; batch_trinkets27
      模块 docstring。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG30_MagicItem_418 num(0..4) 全 None）
    """


class EnforcerPortraitScript:
    """
    Natural language: [x]Get a Lightfang Enforcer. Your Lightfang
    Enforcers have all minion types.

    Status: **已迁出 → batch_family_races（2026-09-21）**——注册于
      `batch_family_races.EnforcerPortraitScript`（"have all minion
      types" = `Race.ALL` → `STANDARD_RACES` 展开）。以下保留原始阻塞
      记录。

    Dependency:
      1. 载荷 `BGS_009` Lightfang Enforcer（EoT: 每类型一个随机友方
        +4/+4）已由并行批 `batch_payload_minions` 注册——本体可交付、
        EoT 行为就绪; 但该批 docstring L111-112 自述本饰品"另缺: 多值
        种族 `RACES`"。
      2. "have all minion types" 需要给**家族**（含绑定后新获得的副本）
        追加全类型身份。引擎 `GameTag.RACE` 是单值: 直接
        `m.set(RACE, Race.ALL)` 只在 `create_minion` 的异变通道有生产点，
        **没有**"按卡家族追加身份"的读取点在绑定后持续生效; 入场即打标
        会漏 Transform / 直接入板路径（SOP §16b item 32 禁止）。
      3. 是否等于 `Race.ALL` 语义（"匹配一切类型"）需主线裁定——与
        418/825/179 同族。
    Implementation path: (a) `RACES` 集合/位掩码 tag + race 读取点改造，
      或 (b) 引擎 `game.add_card_aura`（ENGINE_BACKLOG §B2-17）式的家族
      身份读取点; 随后本饰品 on_bind 数据链交付并对家族实例追加全类型
      身份。阻塞卡: BG30_MagicItem_971（同族 _418 / _825 / _179）。
    Reference: docs/agents/ENGINE_BACKLOG.md §A1/§B2-4。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG30_MagicItem_971 num(0..4) 全 None）
    """


class DrakkariPortraitScript:
    """
    Natural language: [x]Get a Drakkari Enchanter. Your Drakkari
    Enchanters are both Mechs and Elementals.

    Status: **已迁出 → batch_family_races（2026-09-21）**——注册于
      `batch_family_races.DrakkariPortraitScript`（`{MECH, ELEMENTAL}`
      双类型身份）。以下保留原始阻塞记录。

    Dependency:
      1. 关联卡 `BG26_ICC_901` Drakkari Enchanter（池 T5，EoT 翻倍为引擎
        内建光环）**已注册** → 交付侧就绪。
      2. "are **both** Mechs and Elementals" 是**同时属于两个类型**:
        `GameTag.RACE` 单值，`Race.ALL` 是"匹配一切"——用它会把 Drakkari
        错误地变成 Beast/Dragon/Quilboar/… 全部类型（超出文本给出的两个）。
    Implementation path: ENGINE_BACKLOG §A1 的 `RACES` 集合 tag +
      `Minion.race` 集合视图; 改造后 on_bind = 数据链交付 + 对本人
      Drakkari Enchanter **实例**追加 {MECH, ELEMENTAL}（未来副本经入板
      钩子）。阻塞卡: BG32_MagicItem_179（同族 _418 / _825 / _971）。
    Reference: docs/agents/ENGINE_BACKLOG.md §A1; batch_trinkets28 模块
      docstring。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG32_MagicItem_179 num(0..4) 全 None）
    """


# ══════════════ C. 子系统 / 引擎原语缺失 ══════════════


class TokenOfTheOldGodsScript:
    """
    Natural language: [x]<b>Spellcraft:</b> Choose a minion. Then choose a
    minion from a Tier higher to transform it into.

    Status: DEFERRED — requires 饰品 Spellcraft 生成协议 + 法术路径两段
      定向选择链（第二段候选域动态）

    Dependency:
      1. 本卡的 Spellcraft 由数据链 `spellcraft_id=112813` →
        `BG30_MagicItem_416t`（法术，未注册）表达; 引擎当前 Spellcraft
        生成/授予协议只覆盖**随从**（`grant_spellcraft_spell` 以随从为
        锚点），无"饰品提供 Spellcraft 法术"的接线点。
      2. 该法术是**两段定向选择链**（"Choose a minion. Then choose a
        minion from a Tier higher"）: `Game.play_spell` 的定向路径只有
        **单段** `needs_target`（`inspect.getsource(Game.play_spell)` /
        `_finish_play_spell` 对 `target_count` 零命中）; `target_count=2`
        链只存在于 `use_hero_power`（`game.py` `_chain`）。
      3. 第二段候选域（"from a Tier **higher**"——相对第一段所选随从的
        tier，含上限封顶口径）无 wiki Notes 权威（patch 30.4.3→30.6.2
        由 Discover 改为 choose）。
    Implementation path: (a) 引擎把 `target_count` 链推广到法术路径并支持
      "第二段候选由第一段结果决定"的回调; (b) 饰品 Spellcraft 生成协议;
      (c) 候选域权威裁定后由 `BG30_MagicItem_416t` 脚本实现 Transform。
      阻塞卡: BG30_MagicItem_416（G4）。
    Reference: batch_trinkets27 模块 docstring（同卡台账）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG30_MagicItem_416 num(0..4) 全 None）
    """


class DesignerEyepatchScript:
    """
    Natural language: You only need 2 copies of a Pirate to make it Golden.

    Status: DEFERRED — requires **按种族**三连阈值读取点
      （`TRIPLE_THRESHOLD` 是 hero 级全域单值）

    Dependency:
      1. 引擎唯一的阈值读取点是 `game.py::check_for_triple` L1074
        `threshold = hero.get(GameTag.TRIPLE_THRESHOLD, 3)`——**hero 级
        全域**（Clocksworth `BG34_HERO_002p` 的"只需 2 份"用同一 tag）。
      2. 本卡文本限定 **Pirate**（数据 `subset_pirate=1`）: 写入
        `TRIPLE_THRESHOLD=2` 会让**所有**随从 2 份成金 = 过度适用，
        是近似实现（SOP §6b 禁止）; 引擎无
        `TRIPLE_THRESHOLD_RACE` / `hero.triple_threshold_by_race`
        （`GameTag.__members__` 运行核验均为 False）。
      3. 在饰品侧自行实现"2 只海盗手动合成"= 复刻 `check_for_triple`
        的池占返 / 金色独立定义 / buff 并集 / 三连奖励发放全链
        （SOP §6b/§16b item 32 禁止）。
    Implementation path: 引擎新增 `hero.triple_threshold_by_race`
      （race → N，与全局 `TRIPLE_THRESHOLD` **取小**）+ `check_for_triple`
      按 `acquired.race`（含 `RACES` 集合成员）查表; 随后本卡 on_bind 写
      `{PIRATE: 2}`（`subset_pirate` 数据驱动，非硬编码种族）。阻塞卡:
      BG30_MagicItem_439（G3）。
    Reference: batch_trinkets11/27 模块 docstring（同卡台账，本批按引擎
      现状复核维持并补齐精确读取点）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG30_MagicItem_439 num(0..4) 全 None;
            文本字面量 "2 copies" / "Pirate" 未实现前不入代码）
    """


class BoomControllerScript:
    """
    Natural language: [x]When you have space, summon an exact copy of your
    first Mech that died each combat.

    Status: DEFERRED — requires 战斗内**有界**"腾位补召"触发协议

    Dependency:
      1. 引擎无"战斗中你有空位时"的触发点: XML 无对应触发 tag
        （CardDefs.xml / wiki 仅见叙事文本），`combat_summon_log` 只写不读
        （ENGINE_BACKLOG §B14/§B2-14）。
      2. SOP §13 item 3 明令禁止用 AFTER_ATTACK"每次攻击后补满"近似
        （Ozumat Tentacular / Drek'Thar 曾造成无限战斗）; 本卡数据
        `script_data_num_2=99` 暗示"上限 99 次"（= 事实上每次有空间即
        触发），无界实现会让双方同类时战斗不终止。
      3. "your first Mech that died each combat" 需要"本场首个死亡机械"
        的快照读取点（`combat_death_log` 可在 death 监听后读，但
        "有界补召"协议未定）。
    Implementation path: 引擎定义"腾位触发"协议（死亡结算后、召唤波之间
      的空位观察点 + 每场次数上限，默认由 `script_data_num_2` 提供）
      → 饰品把"首个死亡机械"的快照存入 source 闭包并在每次腾位时
      `Summon` 精确副本（`Entity.copy_buffs_to` 独立复制，SOP §16b item 20）。
      阻塞卡: BG30_MagicItem_440 + BG30_MagicItem_822（同族，G7）。
    Reference: batch_trinkets27 模块 docstring（同卡台账）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: {1}=num(1)=99（BG30_MagicItem_440; num(0/2..4) 全 None——
            文本无占位符，该参数疑为"每场触发次数上限"，协议未定前不入代码）
    """


class TickatusStickerScript:
    """
    Natural language: [x]<b>Discover</b> a Tier 3 Darkmoon Prize. At the
    start of every three turns, repeat this. <i>({0} |4(turn, turns) left!)</i>

    Status: DEFERRED — requires Darkmoon Prize 候选卡表

    Dependency:
      1. 数据中无"Tier N Darkmoon Prize"的候选集合或 tier→prize 映射
        （`BG27_Anomaly_Prizes2` / `TB_BaconShop_HP_106` Prize Wall 同样
        只有叙事文本）; RULES §11.4 记载该系统**已退役**，官方未公布
        奖池表。
      2. 唯一同族卡 `BG35_MagicItem_812t` Triple Prize（"Discover a Tier 3
        Darkmoon Prize"）亦因此 DEFERRED。
      3. 周期触发（每 `{0}`=3 回合，`num(0)` 就绪）本身可表达，但
        Discover 候选为空 = 注册即空转（第三态）。
    Implementation path: 数据层补 Darkmoon Prize 候选表（官方奖池 +
      tier 归属）→ `Discover(hero, candidates, kind="darkmoon_prize")`
      （预留语义）; 本卡 on_bind 与每 3 回合的 `start_of_turn` 各调用
      一次。阻塞卡: BG30_MagicItem_707 + BG35_MagicItem_812（G9）。
    Reference: docs/agents/ENGINE_BACKLOG.md §B11; RULES §11.4;
      batch_trinkets27 模块 docstring。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: {0}=num(0)=3（BG30_MagicItem_707; num(1..4) 全 None）
    """


class MarineSignetScript:
    """
    Natural language: [x]After you play 4 minions, get a random Tier {1}
    Tavern spell and improve this. <i>({0} left!)</i>@[x]After you play 4
    minions, get a random Tier {1} Tavern spell.

    Status: DEFERRED — requires "improve this" 的**档位递增**权威

    Dependency:
      1. `after you play 4 minions` 的计数与 `get a random Tier {1} Tavern
        spell`（`DrawTavernSpell` / 池感知，`{1}=num(1)=1`）均可用现有
        原语表达; `({0} left!)` = num(0)=4 的进度显示。
      2. 但 "improve this" 的**递增对象与幅度无数据字段、无官方权威**:
        数据只有 `script_data_num_1=4` / `num_2=1`，第二段（`@` 后）文本
        仍写 `{1}` → "每次触发档位 +1" 只是候选读法; 全仓既有 "improve
        this" 卡（`BG30_MagicItem_541/879/879t`、`BG32_MagicItem_801/801t`
        等）**全部递增属性值**，无"递增档位"先例; 越 `max_tavern_tier`
        后的行为亦无定义。wiki 卡页无 Notes（SOP §6b 第 4 步）。
    Implementation path: 权威落地（递增对象 = 档位、幅度 = +1、上限口径）
      后: on_bind 注册 `minion_played`（owner 过滤本人）滚动计数 num(0)
      → 触发时按当前 `{1}` 取池法术入手（满手入队 RULES §3.3）→
      `{1} += 1`。阻塞卡: BG30_MagicItem_711（G11）。
    Reference: batch_trinkets12/27 模块 docstring（同卡台账）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: {0}=num(0)=4 {1}=num(1)=1（BG30_MagicItem_711;
            num(2..4) 全 None——"improve" 幅度无字段，见上）
    """


class AncientWishboneScript:
    """
    Natural language: Your Hero Power triggers twice.

    Status: DEFERRED — requires 英雄技能**效果结算翻倍**钩子

    Dependency:
      1. `Game.use_hero_power` / `_finish_hero_power` 只支持"每回合可用
        **次数**"（`uses_per_turn` + `hero.extra_triggers["hp_uses"]`，
        RULES §6.20——Sous Chef Sticker `BG35_MagicItem_801` 的 "an extra
        time each turn"），**没有**"单次使用效果结算两次"的读取点:
        `script.hero_power(hero, self, ctx)` 只被调用一次
        （`inspect.getsource(Game._finish_hero_power)` 对 `hp_times`
        零命中）。
      2. 用 `hero_power_used` 监听在饰品侧重放被 SOP §15 明令禁止
        （"禁止在卡脚本里自己写计数器重放效果"），且技术上不可行: 事件
        载荷不含本次使用的 `target`、`passive=True` 的技能没有
        `hero_power` 钩子、重放会绕过每回合/每局计数语义。
      3. 是否翻倍**被动**技能与技能费用无权威（多语言文本只写
        "triggers twice"）。
    Implementation path: 引擎新增独立配额（而非复用 `hp_uses`）:
      `hero.extra_triggers["hp_times"] = 1` 在 `_finish_hero_power` 的
      脚本调用处消费——形如 `for _ in range(1 + hero.extra_trigger(
      "hp_times")): script.hero_power(...)`（与 `_finish_play_spell` 的
      spells 循环同构，按 cast 结算、计数只记一次、费用只扣一次）;
      随后本卡 on_bind 写 `hp_times += 1`。阻塞卡: BG30_MagicItem_804
      （G5）。
    Reference: batch_trinkets7/8/12/27 同卡台账（本批复核维持）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG30_MagicItem_804 num(0..4) 全 None）
    """


class FishyStickerScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Summon a Golden Fish of
    N'Zoth that copies <b>Deathrattles</b>.

    Status: DEFERRED — requires 金色定义 → 基础脚本回落（引擎级）

    Dependency:
      1. 关联卡数据链 `evolution_card_id=67216` → `TB_BaconUps_307`
        **金色 Fish of N'Zoth**（"After a different friendly Deathrattle
        minion dies in combat, gain its Deathrattle **twice**"）——该金色
        id **无脚本**（REGISTRY 运行核验无此 id）。
      2. 基础版 `TB_BaconShop_HP_105t` Fish of N'Zoth **已注册**
        （`batch_hero_econ3.FishOfNZothScript`，单倍亡语重放）。但
        `Game.create_minion` 的脚本绑定是**直查** `REGISTRY.get(card_id)`
        （`game.py` L2886-2888），无"金色定义 → 基础卡脚本回落"——
        召唤出的金色鱼是**白板**（on_summon 不跑、亡语不重放），效果
        整体落空（注册即 no-op = 禁止的第三态）。且"twice"语义也超出
        基础脚本（ENGINE_BACKLOG §B15）。
    Implementation path: 引擎实现显式、受审计的"金色定义无脚本 → 回落到
      `TRIPLE_BASE_CARD_ID` 的基础脚本"（不能静默）; 并为金色鱼补
      "twice" 分支（独立金色脚本或 `_per_trigger` 模型）。阻塞卡:
      BG30_MagicItem_821t2（G6）。
    Reference: batch_trinkets27 模块 docstring（同卡台账）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG30_MagicItem_821t2 num(0..4) 全 None）
    """


class TwinSkyLanternsScript:
    """
    Natural language: [x]When you have space, summon a copy of the first
    minion you summon each combat.

    Status: DEFERRED — requires 战斗内**有界**"腾位补召"触发协议

    Dependency:
      1. 同 `BG30_MagicItem_440` Boom Controller: 引擎无"战斗中你有空位
        时"的触发点（XML 无触发 tag、wiki 无 Notes），`combat_summon_log`
        只写不读（ENGINE_BACKLOG §B14/§B2-14）。
      2. `script_data_num_2=1` 暗示"每场触发 1 次"的额度，但触发时机协议
        未定; 用 AFTER_ATTACK 补召会与 440 同族陷入无限战斗
        （SOP §13 item 3 禁止）。
      3. "the first minion you summon each combat" 需要"本场首个召唤物"
        的**快照**读取点（在召唤后被后续召唤/死亡覆盖前采集）。
    Implementation path: 同 440 的"腾位触发"协议（次数上限取
      `script_data_num_2`）→ source 闭包记录本场首个召唤物的卡 id + buff
      快照，腾位时 `Summon` 精确副本（`copy_buffs_to` 独立复制）。
      阻塞卡: BG30_MagicItem_822 + BG30_MagicItem_440（G7）。
    Reference: batch_trinkets27 模块 docstring（同卡台账）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: {1}=num(1)=1（BG30_MagicItem_822; num(0/2..4) 全 None——
            文本无占位符，该参数疑为"每场触发次数上限"，协议未定前不入代码）
    """


class GemDonationScript:
    """
    Natural language: [x]The first minion you sell each turn plays its
    <b>Blood Gems</b> on the 3 highest-Tier minions in the Tavern.

    Status: DEFERRED — "plays its Blood Gems" 的**宝石枚数/来源**无权威
      读法（SOP §6b 第 4 步）

    Dependency:
      1. 三种候选读法在野猪人高宝石局面数值差异巨大:
        (a) 按该随从身上的 `GEMS_PLAYED_ON` 枚数 N、每颗对 3 个目标各施放
            一次（共 3×N 颗）;
        (b) 共 N 颗轮转分配到 3 个目标;
        (c) 每目标固定 1 颗（共 3 颗）。
      2. 已查信源（本批复读，无新证据）: hearthstone.wiki.gg 卡片页
        （仅 refTags "Blood Gem-related / Tavern Tier-related /
        Selling-related" 与 [Targeted]/[Random] 标签，**无 Notes 段**）、
        36.2.2 / 35.6 patch notes、中文卡库镜像——均无裁定。
      3. 引擎侧**已就绪**（非引擎缺口）: `minion_sold` 事件、
        per-minion `GEMS_PLAYED_ON` tag、`PlayBloodGems` action、
        `MINIONS_SOLD_THIS_TURN` hero 级计数（本回合首售判定）——但
        原语就绪 ≠ 语义确定。
    Implementation path: 监听 `minion_sold` + 本回合首售记账（source 级
      闭包）→ 取本人酒馆 `tech_level` 最高的 3 只（并列按位置口径）→
      按裁定读法施放。阻塞卡: BG32_MagicItem_809（G11）。
    Reference: docs/agents/ENGINE_BACKLOG.md §C（AMBIGUOUS 留档）;
      batch_trinkets28 模块 docstring。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG32_MagicItem_809 num(0..4) 全 None;
            文本字面量 "3 highest-Tier minions" 未实现前不入代码）
    """


class YoggTasticPastryScript:
    """
    Natural language: Spin the Wheel of Yogg-Saron. At the start of each
    turn, spin it again.

    Status: DEFERRED — requires Wheel of Yogg-Saron 子系统 + 结果表

    Dependency:
      1. 全库无 Wheel 实现（`grep -rni "spin_wheel" hsrl2/` 只命中他批
        DEFERRED docstring; `Game` 无 `spin_wheel` 属性，运行核验）;
        数据中亦无轮盘结果 token/表（`grep -i "wheel" data/*.json` 只
        命中无关卡名 Dalaran Cheese Wheel / Water Wheel）。
      2. 同缺口已由 batch_quest_rewards3（`BG24_Reward_135` Yogg-tastic
        Tasties）与 batch_anomalies3（`BG27_Anomaly_503` The Yogg-iseum）
        备案; 官方未公布结果概率表。
    Implementation path: 引擎实现 `game.spin_wheel(hero)` + 每个结果的
      card_id/数值数据权威（官方奖池表）→ 本卡 on_bind 调用一次、
      `start_of_turn` 每次回合再调用。阻塞卡: BG30_MagicItem_994（G9）。
    Reference: docs/agents/ENGINE_BACKLOG.md §B11。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG30_MagicItem_994 num(0..4) 全 None）
    """


class PutricideStickerScript:
    """
    Natural language: [x]Craft a custom Undead. At the start of every 2
    turns, repeat this. <i>({0} |4(turn, turns) left!)</i>

    Status: DEFERRED — requires Craft（多步部件合成）选择链

    Dependency:
      1. "Craft a custom Undead" 是 Putricide 多步部件合成链（种族 +
        关键词 + 属性选择 → `BG25_HERO_100pt` Putricide's Creation）;
        全仓无 craft 实现（`Game` 无 `craft` 属性，运行核验）;
        `BG25_HERO_100p` Build-An-Undead 技能亦因此 DEFERRED
        （batch_hero_combat3 台账）。
      2. 数值 `{0}`=num(0)=2 已就绪; 周期触发（每 2 回合）本身可表达，
        但合成链缺失 = 半实现 → 第三态（SOP §6b）。
    Implementation path: 建立多步 `PendingChoice` 合成协议（部件卡片池 +
      参数落点 + token 生成）后，on_bind 与每 `{0}` 回合的
      `start_of_turn` 各调用一次。阻塞卡: BG32_MagicItem_300 +
      `BG25_HERO_100p`（G9）。
    Reference: docs/agents/ENGINE_BACKLOG.md §B10。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: {0}=num(0)=2（BG32_MagicItem_300; num(1..4) 全 None）
    """


class TarecgosaStickerScript:
    """
    Natural language: [x]Your left and right-most Dragons permanently keep
    <b><b>Bonus Keyword</b>s</b> and stats gained in combat.

    Status: DEFERRED — requires Bonus Keyword 定义域 + 位置/种族 PERSIST
      光环原语（双重阻塞）

    Dependency:
      1. "Bonus Keyword" 定义域无任何数据字段（RULES §9.6 主线裁定;
        官方定义域已收为 DS/Reborn/Stealth/Taunt/Venomous/Windfury 6 张
        ——`BG36_MagicItem_801` Consuming Claw 已按该 6 集实现），且需
        **逐实体记录被授予的 bonus 关键词**（"keep" 的对象）。
      2. 引擎 PERSIST 是**单实体全量** tag（`PERSIST_COMBAT_CHANGES`，
        Tarecgosa / Persistent Poet 本体）; 无"按位置（最左/最右）+
        种族（Dragon/ALL）持续授予"的光环原语，`run_combat` 的 Poet
        通道只覆盖"相邻龙"（`ADJACENT_PERSIST_SOURCE`）。用入场即
        buff/逐实例打标的近似被 SOP §16b item 32 禁止（Transform /
        直接入板路径会漏）。
    Implementation path: (a) `BONUS_KEYWORD_SET` 权威落数据字段 + 逐实体
      `BONUS_KEYWORDS_GRANTED` 记录; (b) "位置 + 种族"的 PERSIST 光环读取
      点（与 `hero.race_auras` / `game.add_tier_aura` 同构的"读取时校验
      source 在场"生命周期）。阻塞卡: BG32_MagicItem_417
      （同族 _891 / _892; G2 的延伸）。
    Reference: docs/BATTLEGROUNDS_RULES.md §9.6;
      docs/agents/ENGINE_BACKLOG.md §B9。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG32_MagicItem_417 num(0..4) 全 None）
    """


# ══════════════ 注册 ══════════════


def register() -> List[str]:
    """本批余下 17 张**全部** DEFERRED（SOP §6b 二态铁律）——注册空列表。

    原始作业范围 30 张逐张复评为"无法用现有原语做成语义精确实现"（每张的
    Status / Dependency / Implementation path 见各类 docstring）; 13 张
    已由后续批次注册迁出（含 777，2026-09-17; 含 803（BG30），2026-09-18
    由 batch_trinkets39）。本批不注册任何 id，因此也不存在"注册但 no-op"
    的第三态。
    """
    return []
