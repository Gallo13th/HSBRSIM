# 引擎修改记录（ENGINE_NOTES）

> 规则：修改 `hsrl2/` 必须先有失败测试，改后 `pytest hsrl2/tests -q` 全绿，
> 并在此登记动机、规则依据、影响面。仅 Lead 批准后可动核心文件。

## F-01 战斗快照 deepcopy 实体引用（D-1，2026-10-18）

**文件**：`hsrl2/minion.py::Minion.snapshot_state`

**问题**：`snapshot_state()` 使用 `copy.deepcopy(self.tags)`。`GameTag.KILLER`
（tag 1037）在 `Minion.take_damage` 中写入**击杀者 Entity**（`combat.py`
双向伤害互指），于是每次 `Game.run_combat` 的战前快照都会深拷贝击杀者
实体 → 顺着 `Entity.game/controller/events` 引用拉出**整张 Game 对象图**。

**实测影响**（engine-analyst 基准，20 局 × 8 人）：
- 整局 p50 257ms → 3564ms（约 7.2×）
- `end_recruit_phase` p50 10.7ms → 315ms（约 11×）
- 峰值内存 0.6MB → 58.7MB（约 98×）
- 20 局中 14/871 场战斗出现结果污染（KILLER 深拷贝副本被读取）

**修复**：快照 tags 时跳过实体引用类值（与 `game._frozen_clone` 同口径），
其余值仍逐值深拷贝；`_buffs` 复制为独立列表。KILLER 是战斗内瞬态，
快照复原后不应保留。

**规则依据**：KILLER 为引擎内部引用（`tags.py` 注释"不序列化"），
不属于需要复生的持久状态；RULES §3.5 战斗快照只应回滚属性/关键词/buff。

**影响面**：`Game.run_combat` 的战前快照与复原、复生/分裂的状态副本。
行为上：战斗结束时 KILLER 现在被正确清除，而不是指向克隆实体。
所有既有测试（4164 项）保持全绿；新增回归测试见
`tests/test_engine_fixes.py::TestSnapshotNoEntityDeepcopy`。

**验证命令**：
```powershell
python -m pytest hsrl2/tests -q
python -m pytest tests/test_engine_fixes.py -q
python tools/probe_speed.py --games 20
```

## F-02 Ozumat 战斗开始召唤数量（2026-10-18）

**文件**：`hsrl2/scripts/batches/batch_hero_combat3.py`（Ozumat 脚本）
**测试**：`hsrl2/tests/test_batch_hero_combat3.py`

**问题**：`OzumatScript` 的战斗开始（SoC）效果用
`while not hero.board_full(): summon Tentacle`，在有 1 个随从时召唤 **6 只**
2/2 Taunt Tentacle；官方卡面 "Summon **a** Tentacle"（每场 1 只；
BobsBuddy `_tokenSummoned` 同口径）。

**证据**：官方真实战斗轨迹 `f5d1c647b2f449d1`（HDT BobsBuddy 会话日志）
显示官方 100% loss，引擎 100% win；monkey-patch 为 1 只后引擎 loss 8/8 = 官方。
独立复核：`reversed/rea/behavior_mismatch_analysis.md`（BobsBuddy 反编译
`BB:32185-32219`）。

**修复**：每场战斗只召唤 1 只（token 已召唤守卫）。

**影响面**：Ozumat 英雄技能相关战斗；差分 harness 679 场中
`behavior_mismatch` 1 → 0，干净子集匹配率 92.31% → 100%。

**规则依据**：`data/bg_cards.json`/CardDefs 文本 "summon a Tentacle" +
HDT BobsBuddy 官方日志结果。

## F-03 动态 SCRIPT_DATA_NUM 命名空间（2026-10-18）

**文件**：`hsrl2/tags.py`、`hsrl2/entity.py`、`hsrl2/game.py`、
`hsrl2/scripts/batches/batch_counters.py`；测试 `hsrl2/tests/test_script_data_num.py`

**问题**：动态属性（Eternal Knight 等"本局死亡计数"）需要 `TAG_SCRIPT_DATA_NUM_1..5`
通道，但引擎内部自定义 tag 1068/1069/1070 与官方枚举值无关（官方真实值经
`CardDefs.Bacon.xml` + 客户端 GAME_TAG 双源核对为 **2/3/2889/2919/2920**），
此前差分中表现为 `unmodeled_dynamic_state`。

**修复**：新增 `ScriptDataNum` 独立命名空间 + 官方值映射表 + `Entity._script_data`
独立存储（不进 `Entity.tags`），`Entity.set/get_script_data`、创建时从 CardDef
初始化默认值、`Game.set_entity_script_data`/`inject_script_data_from_trace` 注入
API。Eternal Knight 迁移为"簿记 + 注入计数"（注入 `{3:4}` 复现官方 20/10），
**未注入时行为逐位不变**。其余 12 个动态属性脚本家族留台账，后续逐卡迁移。

**影响面**：默认行为不变；GameTag 1068/1069/1070 零改动；新增防误判回流测试。

## F-04 伤害上限外部注入 API（2026-10-18）

**文件**：`hsrl2/game.py`；测试 `hsrl2/tests/test_damage_cap_injection.py`

**背景**：官方伤害上限不是本地公式，而是服务端 GameEntity tag
`BACON_COMBAT_DAMAGE_CAP`(2089) 由 `_ENABLED`(3403) 门控、动态下发；引擎现有
turn 表（5/10/15，alive≤4 解除）是**近似**（解除阈值/上限 15/伤害公式均有官方
证据吻合，逐档 5/10 无本地样本）。

**修复**：`Game(..., damage_cap_override=N)`（keyword-only，默认 None）、
`set_damage_cap(value, enabled=True)`、`clear_damage_cap()`；
`run_combat` 优先级：`_ENABLED=0` → 无上限；override → 官方值；否则原 turn 表。
**默认 None 时逐位不变**。差分 harness 解析 trace 中 2089/3403，有 tag 才注入。

**后续**：采集真实 Power.log 后验证 5/10 档位并替换默认表。

## F-05 剧毒/烈毒与顺劈的"攻击者存活"门槛（2026-10-18）

**文件**：`hsrl2/combat.py`；测试 `hsrl2/tests/test_combat_semantics_p1.py`

**问题**：引擎要求 `not attacker.dead` 才触发剧毒/烈毒的毁灭、才结算顺劈相邻伤害。
官方关键词文本（`GLOBAL.txt:1021/1231`）"Destroy any minion damaged by this
minion"（无来源存活条件）；顺劈卡面 "Also damages the minions next to whomever
it attacks." 属同时伤害（攻击者被反击致死不应取消）。BobsBuddy 同口径。

**修复**：去掉两处 `not attacker.dead` 门槛；毒杀标记前移到统一死亡结算之前
（互杀同归于尽时毒杀仍生效、同一攻击的死亡同一次结算）。

**影响面**：引擎全量测试 4,265 绿（隔离）；679 官方轨迹差分聚合 ±1（中性，
42 条变化轨迹全部含毒/顺劈语义来源，19 更近/21 更远/2 不变；因缺脚本与单样本
噪声，以官方文本 + 规则级测试为准）。明确未改：死亡波次/复生时序、复生体
buff 保留语义（官方 NO EVIDENCE，等真实 Power.log）。

## F-06 本回合元素打出计数（ELEMENTALS_PLAYED_THIS_TURN，2026-10-18）

**文件**：`hsrl2/hero.py`、`hsrl2/game.py`；测试
`hsrl2/tests/test_turn_elemental_counter.py`、`hsrl2/tests/test_batch_37x_firelands.py`

**问题**：37.0 卡牌 "Improved by each Elemental you played this turn"
（BG35_910 Conflagration / 宿主 BG35_882 Firelands Fugitive）需要**本回合**
元素打出数。引擎此前只有游戏长计数 `GameTag.COUNTER_ELEMENTALS_PLAYED`
（tags 1092，供 BG26_537 Flourishing Frostling "this game" 动态属性使用），
无本回合计数/清零点；用游戏长计数会高估历史回合元素数（SOP 二态铁律禁止近似）。

**修复**（默认行为不变，无既有卡读取该新状态）：
- `Hero.__init__`: 新增公开属性 `elementals_played_this_turn: int = 0`；
- `Game._begin_recruit_for`: 每回合开始清零（与 `CARDS_PLAYED_THIS_TURN`
  同点位）；
- `Game.play_minion` 普通打出路径（元素随从、战吼结算后）: +1（与既有
  `COUNTER_ELEMENTALS_PLAYED` 同一写入点）；
- 公开读取点: `Game.elementals_played_this_turn(hero)`；
- 由 `batch_37x_firelands` 消费：Conflagration 倍率 = `1 + 本回合元素数`
  （每次 +印面值 4/4），并注册 Firelands Fugitive。

**边界（有意，证据不足处不猜）**：
- 只统计 **played**（不统计召唤）；普通 `play_minion` 路径。
- **磁力吸附**路径不计（与既有 `COUNTER_ELEMENTALS_PLAYED` 同口径；
  37.0 当前池无 Elemental+Magnetic，实际不可达；非池 BG31_859 Technical
  Element 若未来入池/被生成需重评）。
- **不改写**游戏长 `COUNTER_ELEMENTALS_PLAYED`（避免改变 Flourishing
  Frostling 等既有卡行为）。

**影响面**：默认行为逐位不变（新属性无既有读取点）；新增 7 条原语测试 +
14 条卡牌测试。全量回归 4,819 passed（Firelands 批后；Deity/Discard 批另行
更新）；`audit_script_wiring --strict` / `audit_vacuous_tests --strict` PASS。

## F-07 Deity（旧神隐藏目标）子系统（2026-10-18）

**文件**：`hsrl2/deity.py`（新）、`hsrl2/hero.py`、`hsrl2/game.py`；
卡牌/令牌脚本 `hsrl2/scripts/batches/batch_37x_deity.py`；
测试 `hsrl2/tests/test_deity_system.py`、`hsrl2/tests/test_batch_37x_deity.py`

**问题**：37.0 Aberration 种族引入 Deity（隐藏旧神目标）机制：每名玩家
开局隐藏随机获得 C'Thun 或 Y'Shaarj；每只友方 Aberration 死亡推进进度；
达到阈值后 Deity 加入战斗；多张池内卡 "Give your **Deity** +X/+Y" 需要
写入点。引擎此前无 Deity 状态/进度/awaken/属性累加。

**证据**：
- 官方 CardDefs 37.0.0.255130 `BG_OldGod`（Secret Deity [DNT]，
  OBJECTIVE/START_OF_COMBAT，QUEST_PROGRESS_TOTAL=4）：
  "After 4 friendly Aberrations die each combat, awaken a {1}/{2} {5}
  ({0} left!)"；NUM_1=4、NUM_2=1、NUM_3=1、NUM_6=130610
  （`BGFYM_000` C'Thun，`BACON_EVOLUTION_CARD_ID` 同值）、
  `BACON_DEITY_SIGIL=1`、`BACON_OLD_GOD` ReferencedTag。
- 官方公告（Patch 36.6.1 上线；36.6.3 阈值 3→4）：每名玩家开局隐藏随机
  C'Thun/Y'Shaarj；友方 Aberration 死亡推进进度；达标后 Deity
  "joins the fight"。
- 两张 Deity token CardDef 文本（C'Thun 的 awaken 特效 / Y'Shaarj 的
  亡语"first {0} Aberrations that died this combat with their maximum
  stats (except Deities)"，NUM_1=2/金 4）。

**修复（默认行为不变——仅当 Aberration 死亡/Deity 卡触发时生效）**：
- `hsrl2/deity.py`: `DeityState`（隐藏状态：card_id/golden/atk/health/
  progress/awakened）+ 阈值从 `BG_OldGod` NUM_1 读取；
- `Hero.deity = None`（惰性状态）；`Game.deity(hero)` /
  `Game.select_deity` / `Game.give_deity_stats`（唯一写入点）/
  `Game.deity_threshold` / `Game.deity_combat_deaths`；
- `Game.run_combat` 开始: `_reset_deity_combat()`（每场重置进度与死亡记录）；
- `_process_death_inner`: death 事件后记录战斗内友方 Aberration 死亡
  （死亡瞬间 base_id/攻/最大生命），推进进度；死亡结算尾部
  `_maybe_awaken_deity` 达标时以当前状态召唤 Deity token（`Game.summon`
  默认最右空位；满场不召唤、后续死亡重试）；广播 `deity_awakened`。
- 随机选择：官方隐藏随机（开局 C'Thun/Y'Shaarj 二选一）。为保持
  `game.rng` 流逐位不变（env 确定性/差分可复现），选择从
  `GameRNG.seed_value` + 英雄序号确定性派生，**不消耗 rng**——
  deviation 记档（隐藏信息，不影响可观测分布）。
- 卡牌脚本（`batch_37x_deity`）：7 张池内 Deity 卡 + Energizing Chamber +
  Y'Shaarj token 基础/金色（`BGFYM_011`/`_G`）按卡面实现。

**边界（证据不足处不猜）**：
- **C'Thun awaken 特效已实现（F-16）**：真实 Power.log 给出
  `floor(atk/N)/floor(health/N)`、余数丢弃；`BGFYM_000/_G` 不单独注册
  脚本（awaken 本体召唤+split 在 `_maybe_awaken_deity`）；N=0 边界
  仍不猜。历史 F-07 DEFERRED 已解除。
- Deity 召唤位置：官方未公布（引擎取 `Game.summon` 默认最右空位）。
- 每场战斗进度重置按卡面 "each combat"；`BG_OldGod` 本地化另一变体
  "Done!"（一次性完成）与公告"总牺牲数"存在措辞冲突 → 采用 CardDefs
  卡面文本（数据权威）并记档。
- 金色 Deity（Mask of Ancient Ones）/Reborn（Evil Experiment）等饰品
  交互留待饰品批次（`DeityState.golden` 已预留，本批未接饰品）。

**影响面**：仅 Aberration 死亡/Deity 卡相关局面行为改变（池内 Aberration
卡在 37.0 大量存在 → env/diff 轨迹会位移；全量回归按最终批更新）。
引擎语义未改既有路径；新增 14 条原语测试 + 48 条卡牌测试。

## F-08 Discard（弃牌）子系统 + Activate cost=0 修正（2026-10-18）

**文件**：`hsrl2/game.py`、`hsrl2/hero.py`、`tools/audit_script_wiring.py`；
卡牌脚本 `hsrl2/scripts/batches/batch_37x_discard.py`；测试
`hsrl2/tests/test_discard_system.py`、`hsrl2/tests/test_batch_37x_discard.py`

**问题**：37.0 Aberration 族以弃牌为核心资源（"Discard a card…"、
"Whenever you discard a card…"、"If you discard this…"、
"each card you've discarded this game"）；引擎此前无弃牌 action/事件/
计数，9 张池内 discard 族 + 3 张 Deity-discard 卡全部 DEFERRED。
另发现数据导出在 **Activate 费用为 0 时省略 `activate_cost`**，引擎
`create_minion` 以 `is not None` 判定 → Mangled Bandit / Brain Rotter /
Abyssal Envoy / Mindbending Recruiter / N'raqi Frostcaller 等
**整卡不可 Activate**（`use_activate` 永远 False）。

**修复**：
- `Game.discard_card(hero, card, *, source=None)`：手牌 → GRAVEYARD；
  `hero.cards_discarded_this_game += 1`；广播
  `card_discarded(hero=, card=, source=)`；分发 `on_discard` 钩子。
  弃置 ≠ 打出/出售（不触发 on_play/on_sell、不回池——池副本视为消耗，
  证据不足记档）。
- `Hero.cards_discarded_this_game`（本局弃牌数，Improve 家族读取点）。
- `on_discard` 钩子加入 `tools/audit_script_wiring.py` 的引擎接线
  白名单（minion/spell 均可分发）。
- Activate 标记修正：以 XML 关键词 `activate` 为权威，
  `d.activate_cost` 缺省按 **0** 标记（`ACTIVATE`+`ACTIVATE_COST`），
  修复 cost=0 卡的不可用问题。
- 卡牌侧（`batch_37x_discard`，24 id）：Discard 选择交互
  `PendingChoice(kind="discard_card")`；"Whenever you discard" 监听
  `card_discarded`；成对弃置（Willbreaker/Operative）监听
  `card_played`；"If you discard this, cast it twice" 由
  Sludge Corrosion / Energizing Chamber 的 `on_discard` 实现
  （两批各自回补 + 测试归属调到对应批次测试文件）。

**证据**：CardDefs 37.0 卡面文本（12 张 + 2 张载荷）；官方公告
"Aberrations… built around discard synergies"；数据 `activate: true`
但 cost 字段缺失 = 0（卡面 "Activate ({2})" 显示 0，官方公告同步）。

**边界（证据不足处不猜）**：
- 弃置的池副本不回池（弃置=消耗；官方无盘面证据）。
- "or Pass"（Duos 语义）不实现（本引擎无 Pass）。
- 成对弃置测试以 `card_played` 事件分发验证监听器（随机法术真实
  play 的目标要求会使单测不稳定；真实 play 路径在引擎层同一事件）。
- 弃牌选择 = 手牌任意一张（官方 UI 同）；空手牌 → Activate 消耗但
  效果落空。

**影响面**：新增 Discard 原语；**Activate cost=0 修正让 5 张卡从
"不可用"变为可用**（含本批池卡与既有金卡定义）——属数据/引擎契约
修正，已加测试。默认其它路径不变。全量回归 4,991 passed；新增
7 条原语测试 + 40 条卡牌测试。

## F-09 Sneed's New Shredder 亡语"from hand"语义（无限重召修复，2026-10-18）

**文件**：`hsrl2/scripts/batches/batch_hero_combat3.py::SneedsNewShredderScript`；
测试 `hsrl2/tests/test_batch_hero_combat3.py::TestSneed`

**问题**：官方卡面 `BG21_HERO_030t/_G`："Deathrattle: Summon the
highest-Health minion **from your hand** and give it Divine Shield for
this combat." 旧实现从手牌复制一只（原件留手）→ 手牌里的高血随从会被
每次 Shredder 死亡重复召唤，形成无限重召；最终压测 8 人 seed=6180
在战斗内触发 `CombatLoopError: combat exceeded max attack rounds`
（2000 回合互召，实测轨迹全为 `BG21_HERO_030t`）。

**修复**：从手牌**移出**该随从（`hero.hand.remove`）再 `Game.summon`，
给圣盾；金色依次移出 2 只不同最高血。测试同步改为断言"原件移出手牌"。

**证据**：CardDefs 37.0 卡面 "from your hand"（HS 标准语义：从手牌
召唤 = 移入战场，非复制）；无限重召的实测轨迹反证旧复制语义不可服务。

**影响面**：仅 Sneed 英雄技能 token 的亡语路径；修复后 8 人 200 局
压测 crashes=0（见 `runs/final_engine_stress.json`）。全量回归绿。

## F-10 动态属性脚本家族迁移到 `script_data_or_card(3)`（2026-10-18）

**文件**：`hsrl2/scripts/batches/batch_counters.py`（7 族）、
`hsrl2/scripts/batches/batch_unlock_final.py`（EternalPortrait）；
测试 `hsrl2/tests/test_dynamic_script_data_migration.py`（26 例）

**背景**：F-03 建立了官方 `TAG_SCRIPT_DATA_NUM_3` 独立通道并只迁移
Eternal Knight。差分仍显示 `context_gap=59`（`unmodeled_dynamic_state=54`）；
FIX_REPORT2 §2.3 台账列出 12 个待迁移"动态属性脚本家族"。

**迁移（默认行为逐位不变；无注入 = 旧公式）**：
- 计数 = 引擎计数/簿记 **+** `script_data_or_card(3)` 注入基线；
  无注入时基数为 0（这些卡 CardDef NUM_3 均 None）；
- 迁移族：
  1. `AbyssalBruiserScript`（TAVERN_SPELLS_CAST_THIS_GAME）
  2. `AncestralAutomatonScript`（已召唤家族簿记）
  3. `FallingSkyGolemScript`（COUNTER_DEATHRATTLES）
  4. `FlourishingFrostlingScript`（COUNTER_ELEMENTALS_PLAYED）
  5. `MaritimeExtortionistScript`（GOLDEN_MINIONS_PLAYED）
  6. `RotHideGnollScript`/`Golden`（本场友方死亡数）
  7. `EternalKnightScript`（F-03 回归，改用统一 helper）
  8. `EternalPortraitScript`（饰品：友方 Undead 死亡累计卡家族光环）
- 金色数值仍由各自 CardDef 体现；owner 隔离（每实体/每英雄独立通道）。

**差分（受控同 harness；before = 临时引擎副本回退迁移调用）**：
- MATCH **394 → 399（+5）**、engine_divergence **182 → 177**；
- `context_gap` **62 → 62**、`unmodeled_dynamic_state` **57 → 57**
  （未降，原因见边界）；deterministic **286/342 → 290/342**；
  干净子集 **13/13 不变**；behavior_mismatch=0、DATA_GAP=0。
- **harness 侧待办**（本批未改 harness）：官方 trace 对这些实体多数只
  携带 `ScriptDataNum1/2`（打印属性值）而非 `NUM_3`；需把这批卡加入
  `DYNAMIC_STAT_SCRIPT_IDS` 让适配器从 printed 反推 count 并注入 NUM_3，
  同时在 `CONSUMED_SCRIPT_DATA` 登记消费位。临时估算（runs 下副本）：
  MATCH 再 +1（399→400），context_gap 仍 62（其余动态缺口卡主导）。

**边界 / DEFERRED（证据不足，未猜）**：
- 4 个台账条目**不是动态属性脚本**（无 atk/health 钩子 / 无计数读取）:
  `EternalTycoonScript`、`HeroicBroodmotherScript`/`Golden`、
  `InsurrectionistsBladeScript`、`WarbandWhistleScript`（后两者为
  DEFERRED stub/内容刷新，不消费 ScriptDataNum）。
- `batch_econ_misc2.py::FallingSkyGolemScript` 是历史 DEFERRED stub
  （未注册）；实际注册类在 `batch_counters.py` 已迁移。
- Volumizer 家族（F-07）动态属性读 hero 级"首次触发"计数，非官方
  ScriptDataNum3 通道；官方语义未证实，未迁移。
- `context_gap` 主导项是**其它已注册卡**（Forest Rover `BG31_801`、
  Wrath Weaver `BGS_004`、Patient Scout `BG24_715`、Gluttonous Trogg
  `BG35_801`、Scarlet Survivor `BG35_814`、Sky Admiral Rogers
  `BG33_823`、Upbeat Frontdrake/Duo、Groundbreaker、Soul Rewinder、
  Brazen Buccaneer、Fire-forged Evoker、Devout Hellcaller、Buzzing
  Vermin、Catacomb Crasher、Zesty Shaker、Felemental 等）与缺失脚本
  （Moonsteel Juggernaut `BG31_171`、Dastardly Drust `BG32_234` 等）——
  不在 FIX_REPORT2 §2.3 清单，官方 ScriptDataNum 语义未逐卡证实，
  需下一批专门排查（禁止按"存在 tag 就注入"近似）。

**影响面**：仅动态属性公式的**注入优先**路径；默认无注入行为不变
（默认回归 5,032 passed / 3 skipped）。

## F-11 B 类动态状态迁移（进度/计时/标记，2026-10-18）

**背景**：`reversed/rea/dynamic_gap_audit.md` 对 TOP 动态缺口卡逐卡
审计：A 类（动态 atk/health 钩子）为 0，B 类 11 张为进度/计时/标记，
C 类 6 张证据不足。本批只落地 B 类中语义明确的 **7 张**（招募期效果）。

**文件**：
`batch_avenge_misc.py`（Patient Scout NUM_1 tier）、
`batch_37x_missing1.py`（Gluttonous Trogg NUM_1 购买进度）、
`batch_misc.py`（Sky Admiral Rogers NUM_1 "Gold left"）、
`batch_diff_driven2.py`（Upbeat Frontdrake NUM_1 剩余回合）、
`batch_diff_driven1.py`（Upbeat Duo NUM_1 剩余回合）、
`batch_econ_misc.py`（Zesty Shaker NUM_1 已用标记）、
`batch_unfreeze.py`（Scarlet Survivor NUM_2 Done 标记）。

**基础设施**：`Entity.is_script_data_injected(num)` —— 区分 CardDef
静态初始化与官方轨迹注入（`set_script_data`/`Game.set_entity_script_data`
标记，`init_script_data_from_carddef` 不标记）。B 类脚本仅在**真实
注入**时用官方值作回放窗口前基线；无注入逐位不变。

**测试**：`hsrl2/tests/test_dynamic_state_migration.py` 13 例（每卡
默认 vs 注入、标记语义）。

**差分（受控同 harness；pre-B11 用临时引擎副本回退注入读取）**：
B 脚本本身 **0 翻转 / 0 胜率变化**（招募期效果不在战斗回放路径；
Scarlet 的 Done/DS 与 trace 关键词一致）。当前基线（harness 已登记
F-10 卡）：MATCH 401、context_gap 80（unmodeled 73）、干净子集
19/19；临时 harness 全量登记本批卡：context 80→75、unmodeled 73→68、
干净子集 19→33/38，但暴露 5 条**既有** behavior_mismatch（非本批
脚本引入；登记前需处理）。安全子集（Patient/Rogers/Upbeat Duo/
Zesty）登记：干净子集 19→24、behavior_mismatch=0。
**待 diff-harness 登记**（卡 id → 槽位）：`BG24_715/_G→{1}`、
`BG35_801/_G→{1}`、`BG33_823/_G→{1}`、`BG26_529/_G→{1}`、
`BG26_199/_G→{1}`、`BG26_505/_G→{1}`、`BG35_814/_G→{2}`。

**边界**：Forest Rover/Buzzing Vermin/Felemental/Catacomb Crasher 的
官方值属引擎可复算的派生值（token 最终属性/酒馆 Buff 累计/CardDef
静态值），**不接脚本消费**；C 类（Wrath Weaver/Groundbreaker/
Soul Rewinder/Brazen Buccaneer/Fire-forged Evoker/Devout Hellcaller）
维持 DEFERRED，缺 Power.log/Notes。

## F-12 引擎原语：minion_gained + 战斗内法术额外施放（2026-10-18）

**文件**：`hsrl2/game.py`、`hsrl2/hero.py`；
测试 `hsrl2/tests/test_engine_primitives_f12.py`（11 例）。

1. **`Game.minion_gained(hero, minion)`**：统一"获得一个随从"入手
   事件，在 `Hero.add_to_hand` 真正进手后**单点广播一次**（购买/
   Discover/生成/满手排队后入手全路径经此；排队期间不广播）。与
   `card_gained`（含法术）区分，避免"购买 + 获得"双事件重复计数；
   供 `BG32_234 Dastardly Drust` 等按 Pirate 过滤的监听器使用。
2. **`Game.combat_spell_extra_casts(hero) -> int`**：默认 0；读取
   hero 级 `_combat_spell_extra_casts`（卡脚本写入），
   `cast_spell_effect` 在 `game.in_combat` 时按 `1+extra` 重复结算
   （每次独立 `spell_resolving`/`spell_resolved`，`cast_no` 递增；
   目标失效则停止额外施放）。默认 0 时原单次路径逐位不变；当前无
   卡脚本设置该值（`BG34_922 Maelstrom Emergent` 卡脚本仍未实现）。

**影响面**：`minion_gained` 只在 `add_to_hand` 增一次事件广播；
`cast_spell_effect` 默认 0 走一次循环（等价原逻辑）。全量回归
5,090 passed / 3 skipped；审计 PASS；smoke 8 局 crashes=0。

## F-13 最后两张 missing_script 收口（Drust / Maelstrom，2026-10-18）

**文件**：`hsrl2/scripts/batches/batch_37x_gapfill.py`；
测试 `hsrl2/tests/test_batch_37x_gapfill.py`（13 例）。

1. **BG32_234/_G Dastardly Drust**：监听 F-12 `minion_gained`（单点，
   防重复）；获得 Pirate（含 ALL）→ 对本人棋盘全体存活随从
   `Buff(num(0),num(1))`；获得**金色** Pirate → 改用 `num(2),num(3)`
   （金色 Drust CardDef 数值自然翻倍：4/4/12/12）。满手排队期间不触发；
   对手获得不触发；非 Pirate 不触发。
2. **BG34_922/_G Maelstrom Emergent**：SoC 时按存活 Maelstrom 重算
   `hero._combat_spell_extra_casts`（普通 num(0)=1；金色文本
   "2 extra times" 字面量=2——金色 CardDef num(0)=1 未随文本更新，
   以文本为准）；死亡/出售时重算清除；仅 `cast_spell_effect` 在
   `in_combat` 消费（招募期不生效）。多个 Maelstrom 叠加。

**影响面**：两张均为非池历史轨迹卡（新增注册，不改变池 279/280）；
默认无卡脚本设置时原路径不变。全量回归 5,103 passed / 3 skipped；
审计三件套 PASS；smoke 8 局 crashes=0。差分：MATCH 400
（71.9%→72.3% 口径变化由其它 agent harness 登记/轨迹集导致）、
context_gap 85、behavior_mismatch 0。

## F-14 Reborn 复生体恢复卡面基础关键词（青铜守卫 C round6，2026-10-18）

**文件**：`hsrl2/game.py::_process_death_inner`（Reborn 分支）；
测试 `hsrl2/tests/test_reborn_keyword_restore.py`（2 例）。

**证据**：真实 `Power.log`（C 局 round6，trace `a07dc079cf3bd8d9`）：
`BGS_034 青铜守卫`（Divine Shield + Reborn）第一次死亡时 DS 已被消耗；
官方 Reborn 新实体 `eid=1487` 的 `FULL_ENTITY` 创建 tag 明确：
`DIVINE_SHIELD=1`、`REBORN=1`（随后 `REBORN=0`）、`CREATOR=1248`、
`HAS_BEEN_REBORN=1`。即 Reborn 是**卡面基础关键词的新副本**，不是仅
保留死亡瞬间 tag 的同一实体。

**Bug**：旧实现 Reborn 只保留死亡瞬间的 tag；BGS_034 的 DS 在死亡前
已破 → 复生体无圣盾，1 血立即被 4 攻随从再次击杀，战斗被判 tie
（64 seeds tie 98.4%，官方 win）。修复：Reborn 原位回归时按 `CardDef`
基础 `keywords` 恢复缺失标签（跳过 `reborn` 本身；DS/taunt 等卡面
基础关键词恢复），其余 buff/临时状态照旧保留/清除。

**验证**：
- 失败测试先红（复生体无 DS）→ 修复后绿；
- C round6 `a07dc...` 引擎 64 seeds：win **90.6%** / tie 9.4%（官方
  win；之前 tie 98.4%）→ `runs/diff_powerlog3_after_f14.json`
  `behavior_mismatch` **0**、MATCH 6/10（修前 5/10）；
- 全量回归 **5,158 passed / 3 skipped / 14 subtests**；F-01..F-13 全绿。

**边界**：只恢复 `CardDef` 基础关键词；不恢复被驱散/消耗的临时关键词
（如被沉默后的关键词），也不改变 Reborn 的一次性/1 血规则。`_G` 卡
的 CardDef 基础关键词同样适用。

## F-15 Deity 边界快照 / sigil / board token 注入（2026-10-18）

**文件**：`hsrl2/deity.py`（`DeitySigilState`）、`hsrl2/game.py`、
`hsrl2/hero.py`；测试 `hsrl2/tests/test_deity_injection.py`（9 例）。

**背景**：state_corpus 已含每英雄 Deity 六字段（bridges），diff-harness
需要把这些官方战斗边界状态注入引擎；旧 F-07 只有
`select_deity/give_deity_stats`，无法精确设置 progress/awakened、sigil
对象，也没有 board Deity token 入口；`run_combat` 开场的
`_reset_deity_combat` 会把 progress/awakened 清零。

**新增 API（默认未调用时逐位不变）**：
1. `Game.inject_deity_state(hero, *, card_id, atk=1, health=1,
   progress=0, awakened=False, sigil_card_id=None, golden=False,
   board_tokens=None)`：一次性精确注入六字段；标记 `DeityState.injected=True`，
   `_reset_deity_combat` 不再覆盖该英雄的 progress/awakened；若带
   `board_tokens`，逐项调用 `inject_deity_board_token`。
2. `Game.inject_deity_sigil(hero, card_id="BG_OldGod", *, progress=0,
   awakened=False)`：建立 `Hero.deity_sigil: DeitySigilState`（Friendly
   Deity Sigil 的引擎侧记录；战斗本身只消费 Deity 状态）。
3. `Game.inject_deity_board_token(hero, *, card_id=None, atk=None,
   health=None, golden=False, position=None, keywords=None)`：召唤
   BGFYM_000/011 token，精确设置属性/站位/关键词；满场/创建失败抛
   `GameStateError`（不静默）。
4. `Game.set_deity_progress` / `set_deity_sigil` 保留为细粒度辅助。

**验证**：
- 默认行为：`Hero.deity/deity_sigil=None`；未调用新 API 的 F-07 路径
  逐位不变；
- 注入 33/33、87/86、progress/awakened、BG_OldGod sigil、board token
  属性/站位/关键词均断言通过；
- state23 经 harness 接入 `inject_deity_state` 后 TVD **0.9844→0.8438**
  （engine win .922→.453 / tie .391 / loss .156，BB 仍 loss 1.0）；
  state268 已收敛 TVD 0（engine loss 1.0 = BB loss 1.0）。该 .8438
  样本的剩余差异随后由 **F-16 C'Thun split** 处理（见下）；F-19 后
  bulk 复跑 state23 TVD **0.7344**。全量回归见收尾。

**边界**：Deity token 的**官方多次 summon 站位/数量**仍以 state 六字段
之外数据为准；本 API 只按调用方给的位置/属性创建，不猜。C'Thun 的
awaken split 已由 **F-16**（真实 Power.log 证据）实现，见下。

**已知 gap 分类（2026-10-19，历史口径，已被 F-16 取代）**：F-15 当时
state23/268 的剩余 TVD 曾归因 C'Thun split DEFERRED；该规则现已有
真实 Power.log 证据并实现（F-16），**diff-harness 不再把 state23/268
标 `unsupported:deity_split_c_thun`**，应重新复跑。BobsBuddy 仍仅第三方
参照，不用 BB 反推官方。`BG34_320`（Rally + ALL 多次选取）仍待更多
官方证据，维持观察、不猜。

## F-16 C'Thun awaken split（真实 Power.log，解除 F-07 DEFERRED）

**文件**：`hsrl2/game.py::_maybe_awaken_deity`；测试
`hsrl2/tests/test_deity_cthun_split.py`（4 例，先红后绿）。

**证据**：`runs/powerlog_2214/Power.log`
- 172605：C'Thun 191/138，N=2 个其它友方 → 每个 +95/+69
  （floor(191/2)/floor(138/2)，余数丢弃）；
- 174028：C'Thun 33/33，N=3 → 每个 +11/+11；
- 108099：C'Thun 1/1，N=1 → 目标 +1/+1。

**实现**：C'Thun（`BGFYM_000`）awaken 召唤 token 后，对**其它**存活
友方随从各加 `floor(state.atk/N)` / `floor(state.health/N)`；
N=0 不施加（边界 DEFERRED，不猜）。Y'Shaarj 亡语不变；卡脚本无改动。

**影响面**：C'Thun awaken 的分配从“无效果”变为有官方证据的均分；
默认未触发 awaken/未选 C'Thun 的路径逐位不变。全量回归与 diff 见收尾。

## F-17 Bristleback Bully（BG35_432/_G）缺脚本

**文件**：`hsrl2/scripts/batches/batch_card_audit2.py`；测试
`hsrl2/tests/test_batch_card_audit2.py`（4 例）。

官方 CardDefs 37.0：`Taunt. Deathrattle: Get a Blood Gem that also
gives a Quilboar Taunt.` 金色 `Get 2 Blood Gems ...`。补亡语：走
`game.grant_card_copy_to_hand` 给 `BG20_GEM_Taunt` 1/2 张；Taunt 与
“野猪人目标也给 Taunt”由既有 `BloodGemTauntScript` 负责。旧状态
REGISTRY 无 `BG35_432/_G`，亡语不触发；修复后测试通过。
BB 是第三方参照，不据此调参。

## F-18 Moonsteel Juggernaut（BG31_171/_G）EoT 卫星

**文件**：`hsrl2/scripts/batches/batch_card_audit3.py`；测试
`hsrl2/tests/test_batch_card_audit3.py`（3 例）。

官方文本：`At the end of your turn, get two {1}/{1} Magnetic Satellites
and improve this.` 普通 NUM_2=6、金色 12。bridge `evidence_round2`
HDT 配对：普通 SCN1=当前卫星、SCN2=+6；金色 +12；手牌 6/12/18 档位
一致。实现：EoT 发两张当前档 `BG31_171t/_Gt`（属性覆盖 + 满手队列），
之后未来档 +6/+12；不改本体属性（证据未观察本体变化）。不读 HDT
`ScriptDataNum` 槽位；Power.log 无 raw EoT 序列，故仅实现该直接证据。

## F-19 Fire-forged Evoker（BG32_822/_G）SoC 公式

**文件**：`hsrl2/scripts/batches/batch_soc.py`；测试
`hsrl2/tests/test_batch_card_audit4.py`（2 例公式）+
`test_batch_soc.py`（旧期望同步更新）。

**证据**：bridge `evidence_round2.json` 20/20 HDT trace 关系：
`SCN3=本局酒馆法术数`；base `SCN1=2*SCN3+2`、`SCN2=SCN3+1`；
golden 基值 +4/+2。CardDef 初始 +2/+2（金 +4/+4）在 c=0 对齐。
raw Power.log 仍无该卡逐次施法样本，故属“trace 关系 + CardDef 初值”
级证据；HDT `ScriptDataNum` 槽位不直接当官方输入。

**Bug**：旧实现 `num0*(1+c)/num1*(1+c)`（普通 c=1：+4/+4，金 +8/+8）；
与 trace 关系冲突。修复为 `atk=num0+2c`、`health=num1+c`
（普通 c=1：+4/+3；金 +6/+5）。新增/更新测试锁定公式（旧公式在
c=1 会给 health +4，与期望 +3 不符）；`test_batch_soc.py` 相关期望
同步更新。

**影响面**：仅 Fire-forged Evoker SoC Buff；默认无该卡/未施法路径
不变；不影响其它 SoC 卡。

## F-20 Trinket offer 过滤 + Choose One/目标两阶段（2026-10-22 8h 审计）

**文件**：`hsrl2/game.py`；测试 `hsrl2/tests/test_engine_choose_target.py`（18 例）。

**动机**：审计发现 41/357 无脚本饰品仍可被 offer/购买（扣金空转）；
`choose_options` 与 `needs_target` 互斥，抉择+定向卡永远到不了目标分支；
法术实体 `CHOOSE_BOTH` 未读。

**改动**：
1. `_gate_trinket_picks`：trinket offer 采样后按 `REGISTRY` 确定性替换无脚本项，
   不消耗 RNG；`grant_random_trinket` 暂未覆盖（记为 P1 gap）。
2. `play_minion`/`play_spell`：先解析 choose，再解析 target，最后
   `_run_play_effects`；`both` 跳过选择但仍走目标阶段。
3. `play_spell` 双效判定增加 `spell.has(GameTag.CHOOSE_BOTH)`。

**测试**：`pytest hsrl2/tests/test_engine_choose_target.py -q` 18 passed；
引擎相关套件 0 failed（2 skipped）。

**影响面**：饰品 offer 池变小（有脚本子集）；Choose One+目标卡行为改变；
无脚本饰品不再能被购买（符合“宁缺勿错”）。RNG 行为保持：过滤在采样后替换。

## F-21 grant_random_trinket 过滤 + PendingChoice 幂等/回滚（2026-10-22 8h P1）

**文件**：`hsrl2/game.py`；测试 `hsrl2/tests/test_engine_pending_choice.py`（12 例）+
`test_engine_choose_target.py`（+4）。

**改动**：
1. `grant_random_trinket` 随机授予路径复用 `_gate_trinket_picks`：
   采样口径保持旧 RNG 消耗，命中无脚本项确定性替换为已注册项；
   无替补返回 None。测试覆盖替换/仅无脚本/真实池/kind 档位。
2. `PendingChoice` 一次性：新增 `resolved/failed/resolution_error/is_settled/_settling`；
   重复 `choose` 抛 `GameStateError`，重入拒绝，越界不消费；
   resolve 抛错 → `failed=True` 终态（不可重试，防半应用重复），异常上抛。
   新增 `Game.take_choice(index, owner=)` 原子 pop+choose API。
3. 3 个既有“越契约二次结算”测试收紧；修复 test_engine_gaps PROBE 删除真实
   REGISTRY 项的污染。

**测试**：`pytest hsrl2/tests` 4816 passed / 6 skipped；`pytest tests` 642 passed /
2 skipped；verify_all --fast 4/4；smoke 8 局 crashes=0。

**影响面**：二次 choose 由静默 no-op 改为显式异常；resolve 失败不再可重试；
env 应优先改用 `Game.take_choice` 并记录 `resolution_error`。

## F-22 `sell_minion` 类型校验（D-9，2026-10-26）

**文件**：`hsrl2/game.py::Game.sell_minion`；测试
`hsrl2/tests/test_engine_api_hardening.py::TestSellMinionTypeCheck`（4 例）。

**问题**（READINESS D-9 / probe A9 实测）：旧实现只检查"实体在棋盘或手牌"，
随后 `minion_pool.release_minion_entity(minion)` 假定 Minion。把 `Spell`
传入 → `AttributeError: 'Spell' object has no attribute 'is_golden'`，
且**崩溃前已加金币 / 已从手牌移除**（状态污染）→ 训练进程崩溃 + 局面损坏。

**修复**：函数入口 `if not isinstance(minion, Minion): return False`（含
`None` / 通用 `Entity`）。非法输入返回 False、零状态改动（金币/手牌/zone/
`MINIONS_SOLD_THIS_TURN` 均不变）。

**规则依据**：出售只对 Minion 有定义（RULES §2.6 / ENGINE_API §3.2 动作表
本就要求"仅 Minion"）；引擎契约「bool = 是否发生」。

**影响面**：仅改变**非法输入**路径（旧行为是崩溃 + 状态污染）；合法出售路径
逐位不变（全量回归 + 既有卖卡脚本/测试全绿）。

## F-23 解冻 API + 冻结事件（D-2，2026-10-26）

**文件**：`hsrl2/game.py::Game.unfreeze_tavern` / `freeze_tavern`；测试
`hsrl2/tests/test_engine_api_hardening.py::TestUnfreezeTavern`（4 例）。

**问题**（READINESS D-2）：旧引擎只有 `freeze_tavern`（置 hero `FROZEN`），
唯一 `clear(FROZEN)` 在 `refresh_tavern` 内部（一次性冻结）。真实游戏可点掉
冻结；环境层只能直接改 tag（破坏封装、无事件）。

**修复**：
- 新增 `Game.unfreeze_tavern(hero) -> bool`：原为冻结态 → 清整馆 `FROZEN`
  + fire `tavern_unfrozen`，返回 True；本来未冻结 → False（无状态变化、无
  事件），与动作 API「bool = 是否发生」同口径；
- `freeze_tavern` 在"未冻结 → 冻结"状态变化时 fire `tavern_frozen`
  （已冻结重复调用不重复广播）；
- 边界：本 API **只清整馆冻结 tag**（`freeze_tavern` 设置的）；单卡冻结
  （效果给的实体级 `FROZEN`）仍由下一次刷新的冻结窗口消费，不在本 API
  语义内（真实 UI 逐卡解冻在引擎中无对应原语）。

**规则依据**：`docs/reference_old/BATTLEGROUNDS_RULES.md` 冻结/刷新章节 +
ENGINE_API §3.7（"引擎没有 unfreeze" 为已登记限制）；READINESS D-2 最小
修复方案。

**影响面**：默认路径不变——全库无 `tavern_frozen`/`tavern_unfrozen` 监听器，
事件新增对既有对局零影响；`freeze_tavern` 返回值仍为 None（签名不变）。
新增 4 条契约测试。

## F-24 名次 API：elimination_order / rank_of / final_ranking（D-5，2026-10-26）

**文件**：`hsrl2/game.py::Game.__init__` / `_process_eliminations` /
`rank_of` / `final_ranking`；测试
`hsrl2/tests/test_engine_api_hardening.py::TestRankApi`（6 例，含真实
`end_recruit_phase` 淘汰路径）。

**问题**（READINESS D-5）：引擎不提供名次，环境层必须监听 `hero_eliminated`
自建 RankTracker；淘汰顺序只存在于事件流里，同一个"第 N 名"逻辑被多处复制。

**修复**：
- `game.elimination_order: List[Hero]`：`_process_eliminations` 内、fire
  `hero_eliminated` **之前**追加（监听器内即可读到最新账本；事件顺序 ==
  淘汰顺序，既有 RankTracker 口径不变）；
- `game.rank_of(hero) -> int`：已被淘汰 → `开局人数 − 淘汰序号`（第一个死
  的 = 第 N 名）；仍存活 → 1；不属于本局 → `ValueError`；
- `game.final_ranking() -> List[Hero]`：仅 `finished` 后可用（否则
  `GameStateError`），第 1 名 → 第 N 名 = 存活者（终局恰 1 名）+ 淘汰顺序
  反序；
- 边界：同回合多人淘汰按 `_process_eliminations` 处理顺序（= 事件顺序）
  编号；引擎不推断并列名次（官方排序证据不足，不猜）。

**规则依据**：ENGINE_API §6.6（标准 RankTracker 口径：第一个被淘汰 =
第 N 名、最后存活 = 第 1 名）；RULES §2.3。

**影响面**：默认行为不变（仅新增记账 + 只读 API；`hero_eliminated` 事件
载荷/顺序不变）。新增 6 条测试。

## F-25 只读查询 API：买价/可买性/技能/下一档/磁力/刷新（D-3，2026-10-26）

**文件**：`hsrl2/game.py`（`quote_buy_cost` / `can_buy` / `can_use_hero_power`
/ `next_tavern_tier` / `magnetic_targets` / `can_refresh` +
`_quote_buy_cost` / `_health_buy_kind` / `_free_minion_buy_hit` /
`_hero_power_check`）；测试
`hsrl2/tests/test_engine_api_hardening.py::TestQuoteBuyCost` /
`TestCanUseHeroPower` / `TestMagneticTargets` / `TestCanRefresh` /
`TestNextTavernTier`（共 24 例，全部含「镜像 == 真实动作」对拍）。

**问题**（READINESS D-3）：合法动作枚举需要的判定都内联在动作函数或私有方法
里，环境层必须复制：
- 买价内联在 `buy_from_tavern`（约 100 行）且 `_take_free_minion_buy` **会消费**
  免费额度（不能预检）；
- 英雄技能可用性内联在 `use_hero_power`；
- `_next_existing_tier` / `_magnetic_valid` 私有；
- 刷新是否可支付内联在 `refresh_tavern`（不可支付会抛异常）。

**修复**（全部纯查询：不扣费、不计数、不消费额度/折扣、不改 tag）：
1. `quote_buy_cost(hero, entity) -> int`：金币口径报价。**与成交路径同源**
   ——`buy_from_tavern` 与报价共用 `_quote_buy_cost`（随从: 基础价 →
   等级价 → 英雄覆盖价 → 条件化规则 → 免费额度；法术: 持久折扣 →
   本回合免费 → 下一个法术折扣）。免费额度改为「只读 peek
   （`_free_minion_buy_hit`）/ 成交消费（`_take_free_minion_buy`）」两步，
   消费时机（定价后、支付前）与旧实现一致；`_take_free_minion_buy` 内部
   改用同一 peek，保证不漂移。
2. `can_buy(hero, entity) -> bool`：镜像成交拒绝条件（在馆/手牌未满/
   未跳回合/金币足够；强制生命支付时要求 `health + armor > cost`）。
3. `can_use_hero_power(hero, power_id=None) -> bool`：`use_hero_power` 前置
   判定抽成 `_hero_power_check`（成交路径与查询同源），等价于
   "`use_hero_power` 现在会不会返回 True"（定向技能 target=None 口径）。
4. `next_tavern_tier(hero) -> Optional[int]`：`_next_existing_tier` 的公开
   别名（含异变 101/102 阶梯）。
5. `magnetic_targets(hero, minion) -> List[Minion]`：与 `play_minion(...,
   magnetic_target=)` 接受条件同源（友方/存活/PLAY/`_magnetic_valid`，
   含 Prosthetic Hand 等数据例外）；非磁力 → `[]`。
6. `can_refresh(hero) -> bool`：镜像 `refresh_tavern(hero)` 付费判定
   （跳回合/封锁 → False；免费额度 → True；健康刷新可支付 → True；否则
   `gold >= REFRESH_COST_OVERRIDE`）。False 时真实调用会抛 `GameStateError`。

**规则依据**：ENGINE_API §4.2/§4.3/§4.5/§4.6/§4.7（既有镜像实现）+ RULES
§7.4.4/§7.4.7/§9.2；READINESS D-3 最小修复方案。

**影响面**：`buy_from_tavern` / `use_hero_power` 行为逐位不变（同源重构，
全量回归绿）；新增 API 默认零调用。对拍测试覆盖：报价==实际扣款（基础/
覆盖价/条件规则/法术折扣/免费额度/生命支付）、peek 不消费且不影响后续
成交、技能可用性==实调用返回值、磁力查询结果被真实吸附接受、刷新
can==真实调用是否抛异常/扣费。

**集成建议（Lead 排期）**：`hsbg/env/driver.py` 当前仍用镜像实现
（`_minion_buy_cost` / `hero_power_usable` / `next_existing_tier` /
`_magnetic_valid` / 刷新前置过滤），建议后续迁移到 F-25 的只读 API；
迁移要求 env 全量测试前后一致（尤其 `test_env_actions` /
`test_env_choice_contract` / `test_env_public_contract`），本轮不做。

## F-26 `Game.phase` 阶段属性（D-14，2026-10-26）

**文件**：`hsrl2/game.py::Game.phase`（property）；测试
`hsrl2/tests/test_engine_api_hardening.py::TestGamePhase`（3 例，含真实
`run_combat` 内 `before_attack` 回调断言）。

**问题**（READINESS D-14）：引擎没有阶段字段，环境必须自建状态机
（ENGINE_API §2.1）；状态机写错会出现"choice 阶段发动作"错位。

**修复**：`phase` 取值 `recruit` / `combat` / `choice` / `game_over`，
优先级与 `hsbg/env/game_env.py::_observe` 同口径：
`finished`（→game_over）> `in_combat`（→combat，仅 `run_combat` 内部可见，
事件回调可读）> `pending_choices`（→choice）> 其余 `recruit`（含
`start_game` 前构造态）。

**规则依据**：ENGINE_API §2.1 状态机 + READINESS D-14 最小修复方案。

**影响面**：纯只读属性（无既有 `phase` 属性/字段冲突），默认行为不变。

## F-27 `CardDB` 公开迭代器（D-8，2026-10-26）

**文件**：`hsrl2/db.py`（`defs()` / `iter_defs()` / `hero_defs()`）；测试
`hsrl2/tests/test_engine_api_hardening.py::TestCardDBIterators`（4 例）。

**问题**（READINESS D-8）：`CardDB` 只有按 id/pool 的查询，全卡遍历与
英雄枚举只能读私有 `_by_id`（引擎重构即破坏；环境层已依赖）。

**修复**：`defs()` 返回全部 `CardDef` 的**新列表**（调用方修改不影响 DB）；
`iter_defs()` 返回只读迭代器（不复制列表）；`hero_defs()` 返回
`CardType.HERO` 子集。顺序 = 注册顺序（`data/` 文件顺序）。

**规则依据**：D-8 最小修复方案 + READINESS §5 G1（合法动作枚举需要英雄池）。

**影响面**：纯新增只读 API；既有 `pool_minions()/pool_spells()/…` 不变。

## F-28 `GameRNG` 审计开关与清理（D-6，2026-10-26）

**文件**：`hsrl2/rng.py`（`audit` 关键字 / `clear_decisions()`）；测试
`hsrl2/tests/test_engine_api_hardening.py::TestGameRNGAudit`（4 例）。

**问题**（READINESS D-6）：`decisions` 无上限（每局 mean 1367 条、max 1771，
<0.2 MB），长期持有 Game / 大量重放时需要开关或清理；无开关只能改私有字段。

**修复**：`GameRNG(seed, *, audit=True)`——**默认 True = 既有审计行为逐位
不变**（tools/probe_*、`hsbg/planning/rng.py` 依赖）；`audit=False` 时随机流
完全不变、不再追加条目。新增 `clear_decisions()`（清日志、不动随机流）。
所有写入点收敛到 `_record()`。

**规则依据**：D-6 最小修复方案；RULES §8 确定性（审计日志不得影响随机流）。

**影响面**：默认路径不变；planning 的 `get_state/set_state/fork` 直接把
`decisions` 当列表读写，兼容。

## F-29 `stats_gained` 抑制深度改 contextvars（D-15，2026-10-26）

**文件**：`hsrl2/entity.py`（`_stats_gained_suppress_depth` / `suppress_stats_gained`
/ `_stats_gained_suppressed`）；测试
`hsrl2/tests/test_engine_api_hardening.py::TestStatsSuppressedContextLocal`（4 例，
含线程隔离：worker 线程抑制窗口内主线程 `stats_gained` 仍广播）。

**问题**（READINESS D-15）：抑制深度是**模块级 int**；同进程两个线程各跑
一局时，A 局的抑制窗口会静默 B 局的 `stats_gained` 广播（脚本被动失效/
数值不一致）→ 排除线程池向量化。

**修复**：改为 `ContextVar[int]`（`default=0`），进入 +1 / 退出 reset
（支持嵌套、异常复原）。单线程/单上下文语义与旧实现逐位相同；不同线程
持有独立深度（新线程从 default=0 开始）。调用方 API 不变
（`with suppress_stats_gained():` / `copy_buffs_to` 内部窗口）。

**规则依据**：READINESS D-15 最小修复方案（contextvars/per-Game）；RULES §3.5
"复制/复原不等于获得"的抑制窗口语义不变。

**影响面**：默认（单线程）行为逐位不变——全量引擎回归 4873 passed / 6 skipped；
额外证据：smoke 8 局 seed 2000 `crashes=0`；确定性 20 seeds 双跑指纹一致
（`tools/final_engine_stress.py --det-cases 20`，digest
`1db23354326a6f0ea86b0e91671214a011b2e17431f8c6998a7c0f45b4fbbf53`）；
`grep -rn "import random" hsrl2/` 仍只有 `hsrl2/rng.py` 本体（随机源单点，
无新增）。

## F-30 本批不改行为项：D-4 / D-7 / D-10 / D-13 现状（2026-10-26）

按任务裁决"无失败测试/无证据不硬改"，以下四项**不改引擎行为**，只回填
现状与后续动作：

1. **D-4 错误风格不一致**（`refresh_tavern` 金币不足抛 `GameStateError`，
   其它动作返回 False）：**DEFERRED（保持现状）**。ENGINE_API §3.0/§3.5
   已把它写成公开契约（"全引擎唯一一个合法但付不起会抛异常的常用动作"），
   环境层 `hsbg/env/driver.py` 已统一 `try/except` 并前置过滤；任一方向
   "统一"都会改变现有行为或破坏既有契约测试 → 不硬改。新增的
   `can_refresh`（F-25）提供了**不抛异常**的预检入口，作为环境层推荐用法。
2. **D-7 `game.choice_policy` 死字段**（`game.py` 赋 "first"，全库无读取
   点）：**DEFERRED**。删除字段可能影响外部读取（含测试/诊断脚本），收益
   低；语义上引擎从不自动结算选择（PendingChoice 契约清晰）。环境层按
   ENGINE_API §5.5 FIFO 自行结算，不依赖该字段。
3. **D-10 `Game` 不可 pickle / 无 clone**：**已由外部模块解决，引擎不改**。
   `hsbg/planning/model.py::clone`（结构化深拷贝 + 闭包重绑）+
   `hsbg/planning/checkpoint.py`（push/pop）已提供可独立推进的快照；
   `hsbg/planning/rng.py` 提供 RNG get_state/set_state/fork。引擎侧不新增
   clone（避免与 planning 的 rebind 语义重复/冲突）。
4. **D-13 `Hero` 构造不校验 card_id**：**环境层已防护，引擎不改**。
   `hsbg/env/game_env.py::_hero_pool` 只取 `card_type == CardType.HERO` 的
   英雄卡，且 `config.hero_id` 不在池内即 `ValueError`。引擎侧校验需要给
   `Hero.__init__` 传 db（签名变更、影响所有脚本/测试构造点），收益不足以
   抵影响面；`Game.hero_power_ids() == []` + `use_hero_power() == False`
   的既有"诚实缺省"保留。

**另（probe_api 同步）**：`tools/probe_api.py::A3` 的
`not hasattr(game, "unfreeze_tavern")` 旧限制断言在 F-23 后过期，已按
Lead 追加授权**最小修正**为正向断言（存在 `unfreeze_tavern` + 解冻成功/
清 FROZEN/fire `tavern_unfrozen`；未冻结时返回 False），实跑
`python3 tools/probe_api.py` → A3 两条 unfreeze 检查 PASS。同文件
**A9** 的 `已知缺陷: sell_minion(Spell) 抛 AttributeError 且状态污染`
断言因 F-22 修复而过期，已按 Lead 追加授权做同类最小修正（改为
`sell_minion(spell) is False` + 零状态污染断言）；实跑
**175/177**，仅剩 A5（F-21 PendingChoice 一次性语义导致的既有 probe
崩溃）与 A7（金色本体既有数据期值）两项**本轮之前既有**过期，
不在本任务范围。`scripts/verify_all.py` 不跑 probe_api，不影响门禁。

**本批验证汇总（2026-10-26，macOS / python3）**：
- `python3 -m pytest hsrl2/tests -q`：**4873 passed / 6 skipped / 0 failed**
  （基线 4816 passed / 6 skipped + 新增 57 条契约测试；无 skip/xfail 新增）；
- `python3 tools/smoke_random_games.py --games 8 --seed 2000`：
  `games=8 completed=8 incomplete=0 crashes=0`；
- 确定性：`python3 tools/final_engine_stress.py --deity-cases 0
  --discard-cases 0 --det-cases 20` → `determinism.identical=20/20`，
  digest `1db23354326a6f0ea86b0e91671214a011b2e17431f8c6998a7c0f45b4fbbf53`；
- 关联根测试：`python3 -m pytest tests/test_engine_fixes.py
  tests/test_planning.py tests/test_env_move.py tests/test_env_observation.py -q`
  → 63 passed。











## F-31 Volumizer 光环下 health ≤ max_health 不变量（Red health 钩子缺失）

**文件**：`hsrl2/scripts/batches/batch_37x_payloadgap1.py::RedVolumizerScript`；
测试 `hsrl2/tests/test_volumizer_health_f31.py`（6 例，先红后绿）。

**问题（env-upgrader 实测，2026-10-26）**：2 人局先 summon Red
Volumizer（`BG34_170t` 3/1）再 summon Blue（`BG34_170t2` 1/3，
"your Volumizers have +3 Health this game"）→ Red `health=4 /
max_health=1`，违反「health ≤ max_health」结构性不变量
（`hsbg/env/invariants.py` 可检出）；真实对局 seed=4212 turn 6 也命中。

**根因**：`_grant_volumizer_aura` 对 hero 级 `volumizer_aura_health`
增量后**同步抬升当前在场 Volumizer 的当前 HEALTH**（与 ApplyRaceAura
可观测行为一致）；`BlueVolumizerScript` / `GreenVolumizerScript` 的
`health` 动态钩子读取该计数使最大血同步；`RedVolumizerScript` 只有
`atk` 钩子、**没有 health 钩子** → 最大血不叠加，当前血被抬高后超上限。
"your Volumizers have +X Health" 是**全体** Volumizer 的光环，Red 必须
吃 Blue/Green 授予的 health 光环。

**修复**：`RedVolumizerScript` 补与 atk 对称的
`health(source) -> _static_total_health(source) + gain`（gain =
`hero.volumizer_aura_health`；计数 0 → None 回落引擎默认）。
Red 自身仍不授予 Health（`health_num_index` 保持 None）。

**规则依据**：CardDefs 37.0 `BG34_170t2/_G` 文本 "your **Volumizers**
have +{1} Health this game (wherever they are)"（全体，非单变体）；
`BG34_170t` 文本只授予 Attack，但"Volumizers"包含 Red。

**影响面**：默认无 Volumizer / 无 health 光环时逐位不变（计数 0 →
返回 None，走引擎默认 max_health）；仅 Red 在 Blue/Green 光环下行为
修正（最大血正确叠加）。新增 6 条不变量测试；既有
`test_batch_37x_payloadgap1.py` 74 例全绿。

## F-32 AC-02：T1 随从池份数 16 → 15（跨引擎一致性）

**文件**：`hsrl2/constants.py::POOL_COPIES_BY_TIER`；测试
`hsrl2/tests/test_rules_constants_ac02_ac03.py`（6 例）。

**问题**（`docs/CONFORMANCE_AUTOTAVERN.md` AC-02，ENGINE_BUG）：旧值
`{1:16, 2:15, 3:13, 4:11, 5:9, 6:7, 7:5}` 的 T1=16 来自
`docs/reference_old/BATTLEGROUNDS_RULES.md`（Patch 35.x 遗留文档，已过时）。

**证据（官方 + 参照双源，E3）**：
- 官方 wiki.gg `/wiki/Battlegrounds` 随从池副本表（2026-10-26 抓取）：
  T1=15, T2=15, T3=13, T4=11, T5=9, T6=7, T7=5；
- AutoTavern `crates/taverngym/src/config.rs:245`
  `pool_copies_by_tier: [15, 15, 13, 11, 9, 7, 5]`（注释 "36.6.0 wiki data"）。

**修复**：`POOL_COPIES_BY_TIER = {1: 15, 2: 15, 3: 13, 4: 11, 5: 9,
6: 7, 7: 5}`（其它档位不变）。`python3 -m tools.ac_conformance.repro
AC-02` 修复后两侧均 `[15, 15, 13, 11, 9, 7, 5]` → verdict MATCH。

**受影响测试（RNG 流位移，非行为退化）**：
- `hsrl2/tests/test_batch_trinkets8.py::TestMinionBait`：原测试用
  `CardDef.race` **主类型单值**判断纳迦，池份数改变后刷新抽取流位移，
  MinionBait 抽到双类型随从 Firescale Hoarder（`BG32_820` =
  Dragon/**Naga**，类型身份集合含 NAGA）→ 旧 `_nagas`/`race_in` 漏计
  而失败。修复 = 测试辅助改为**类型身份集合**语义（`Race.NAGA in
  d.races`，引擎 AC-3 口径），断言语义不变（注入 2 个纳迦/占用 2 份池）。
  不是脚本 bug：MinionBait 经 `_pool_candidates(g, race)` 选族正确。
- `hsrl2/tests/test_consume_tavern.py::test_refresh_tavern_applies_
  persistent_buffs_engine_gap`：固定 seed=34 的刷新内容改变后不再含野兽
  → 改为跨 seed 寻找匹配实体（断言语义不变）。
- 无任何测试断言字面 16（既有用例均引用常量符号）——已在测试注释写明。

**影响面**：T1 每卡池份数 -1（池总量 -37）；刷新抽取权重/三连/残局
守恒分布改变（训练/评估分布向官方对齐）。全量引擎回归见 F-34 汇总结论。

## F-33 AC-03：升级费 T5/T6 9/10 → 11/11（跨引擎一致性）

**文件**：`hsrl2/constants.py::BASE_UPGRADE_COSTS`；测试
`hsrl2/tests/test_rules_constants_ac02_ac03.py`（6 例，含真实动作扣费）。

**问题**（`docs/CONFORMANCE_AUTOTAVERN.md` AC-03，ENGINE_BUG）：旧值
`{2:5,3:7,4:8,5:9,6:10,7:11}`；官方/参照为 T5=11、T6=11。

**键语义核对（不盲改）**：`UPGRADE_COST = BASE_UPGRADE_COSTS[目标档位]`
（`Hero.__init__` 取 `[2]`=5；`_upgrade_cost_after(new_tier)` 写
`BASE[new_tier]` = 下一次升到 new_tier 的基价）→ 键 **k = 升到 k 档的
Base Cost**；T7=10 为特殊档（参照 `upgrade_costs[5]`，索引=目标-2）。
新值 `{2:5, 3:7, 4:8, 5:11, 6:11, 7:10}`。

**证据（官方 + 参照双源，E3）**：
- 官方 wiki.gg `/wiki/Battlegrounds` 升级费表（2026-10-26 抓取）：
  T2=5, T3=7, T4=8, **T5=11, T6=11**；
- AutoTavern `crates/taverngym/src/config.rs:237`
  `upgrade_costs: [5, 7, 8, 11, 11, 10]` + `recruit.rs::base_upgrade_cost`
  （index = to_tier-2 → 行为级确认）。

**修复 + 行为对拍**：`python3 -m tools.ac_conformance.repro AC-03`
修复后两侧常量与**真实 upgrade 动作扣费**逐档一致
（T2..T6：5/7/8/11/11，gold_after/tier_after 相同）→ verdict MATCH。
新增测试含「真实 `upgrade_tavern` 扣费 == 官方常量和」与
「升级后下一次基价键语义」断言。

**影响面**：中后期节奏改变（T5/T6 更贵），策略/BC 数据分布向官方对齐；
既有测试均引用常量符号（无字面 9/10 断言，已核对）。

## F-34 AC-01 先攻平局裁定：证据冲突 → CONVENTION_DIFF（不改行为）

**文件**：无行为改动（`hsrl2/combat.py` 保持原样，`git diff` 为空）；
记录见 `docs/CONFORMANCE_AUTOTAVERN.md` AC-01（auditor 已改判）。

**问题**（参照侧）：AutoTavern `combat.rs:316` 首攻判定为
「数量多者 → 酒馆等级高者 → 随机」，hsrl2 `_determine_first` 平局直接
随机 → 同数量不同等级时约 50% 概率反向。

**证据冲突（不能判 bug）**：
- 支持等级优先：AutoTavern 实现 + 其 `mechanics.rs` 专门测试；中文 2020
  攻略（gamedog，二手来源）；
- 支持随机：**官方 wiki.gg `/wiki/Battlegrounds` Combat Phase 现行原文**
  （2026-10-26 抓取）"If the number of minions is equal for both players,
  one of the players is randomly selected to attack first."；HSBRSIM 旧规则
  文档亦写随机。
- → 二源冲突 + 参照实现单方，Lead 裁定 **CONVENTION_DIFF，不改引擎行为**。

**本地真实语料决定性证据检索（2026-10-26，engine-fixer 执行）**：
- `data/trajectories/`（1100 个引擎自对弈轨迹）、`data/trajectories_{cli,
  hybrid,real}/`：字段仅 = 己方 `turn/health/armor/tavern_tier/gold/board/
  trinkets/hero_power_used`，**无对手战团、无攻击顺序、无先手字段**
  （`grep "combat\|attack\|opp"` 命中 0）→ 不可用于裁定；
- 真实 BG 语料 `runs/official_traces/`（679 条 BobsBuddy/HDT 轨迹）与
  `reversed/`（反编译/证据材料）在本 macOS checkout **不存在**
  （`runs/` gitignore；`find . -name Power.log` 无结果）→ 不可用；
- `hsbg/bridge` 有 Power.log 解析器（`powerlog.py` / `tools/
  diff_extract_replays.py`）但本机无原始日志。
- → 未找到「同数量、不同等级、可判定先手」样本，维持 CONVENTION_DIFF。

**后续（若拿到决定性证据）**：在 `_determine_first` 平局分支比较
`self.a.tavern_tier`/`self.b.tavern_tier`，仍相同才随机；是否加可选开关
（与 AutoTavern 逐位对齐用）由 Lead 决策。当前**不改**。

## F-35 AC-04 BG34_405 Relentless Deflector：可达伤害集合差异 → DEFERRED（非 hsrl2 归因）

**文件**：无行为改动（`hsrl2/**` 不动）；记录 `docs/CONFORMANCE_AUTOTAVERN.md`
AC-04（auditor 台账，candidate）。

**调查（2026-10-26，engine-fixer，45 分钟时间盒）**：
1. 复现 `python3 -m tools.ac_conformance.repro AC-04`：同胜负（A 400/400 胜），
   胜方伤害集合 AT {2:76, 3:172, 5:152} vs HS {3:73, 4:100, 5:69, 6:158}。
2. **排除「Avenge/动态嘲讽」假设**：400 局逐帧扫描 —— AT 侧 BG34_405 的
   `shield_hits` 恒 0、无 DIVINE_SHIELD/TAUNT 关键词帧；HS 侧监听
   `keyword_gained` 统计 **0 次** 405 获得圣盾（Avenge 需 3 次友方死亡且
   405 存活，400 局内一次都未达成；两侧都未触发复仇）。→ 与卡脚本无关。
3. **控制实验定位在 AT 侧脚本卡**：把 BG34_405 换成**同属性无脚本白板**
   （5/4 tier3 + 3×1/3 vs 3×2/2）后：
   - HS 伤害集合 {3,4,5,6}（与带卡时相同）；
   - AT 伤害集合 {3,4,5,6}（与 HS 一致！）——**带 405 脚本时 AT 变为
     {2,3,5}**。
   即：HS 侧带卡/不带卡分布一致（无异常）；**AT 侧使用 BG34_405 脚本时
   分布改变**，而其 Avenge/TAUNT_WHILE_SHIELDED 在观测帧中从未生效。
4. 胜方存活组合（405, dummies）：AT {(0,1),(0,2),(1,1)}；HS {(0,2),(0,3),
   (1,1),(1,2)}；AT 每局恒 6 次攻击事件，HS 4–5 次（同初始 board）——差异
   在基础战斗循环/AT 脚本卡状态表达，而非 hsrl2 卡脚本。

**结论**：AC-04 **DEFERRED，且从「hsrl2 ENGINE_BUG candidate」改判为
「AT 侧脚本卡行为差异候选（CONVENTION/AT bug待查）」**；不修改 hsrl2
行为。若需最终裁定，建议 auditor 用 AT 调试命令逐帧对比 405 与无脚本
白板的 `has_taunt`/`shield` 内部状态（Rust 侧），或补一张真实 Power.log。

**复现命令**：
```bash
python3 -m tools.ac_conformance.repro AC-04
# 控制实验（本批临时脚本，未入库）：同属性无脚本白板 vs 带卡 400 seeds
```

## F-36 KNOWN-DET-1 跨进程确定性：frozenset 迭代顺序进入 RNG 候选（已修复）

**文件**：`hsrl2/scripts/batches/batch_rally2.py::BrambleTunnelerScript`、
`hsrl2/scripts/batches/batch_unfreeze.py::FandralsFortuneScript`；测试
`hsrl2/tests/test_hashseed_determinism.py`（2 例，子进程 + 不同
PYTHONHASHSEED 比输出）。

**问题（env-upgrader 实测，2026-10-26）**：同 seed + 同动作序列的完整
rollout 在 `PYTHONHASHSEED=0` vs `=1` 两进程中分裂（seed=4001：前 129 步
一致，之后 reward/存活数不同；同进程两次 rollout 逐位一致，故现有确定性
测试测不到）。本轮通过逐步 dump 规范化 `game.rng.decisions` 定位：首个
真实分歧 = step24 的两条随机决策 `choose_one_pick`（BG32_237 vs
BG36_332）与随后的 `tavern_draw`（BG36_200 vs BG36_116）。

**根因**：`hsrl2/scripts/choose_one_authority.py` 的
`pool_choose_one_{minion,spell}_ids()` 返回 **`frozenset[str]`**；其迭代
顺序随 str 哈希种子（PYTHONHASHSEED）变化。两个脚本把该迭代结果直接作为
`game.rng.choice/sample` 的候选列表 → 同一 RNG index 在不同进程映射到
不同卡（同进程/同哈希种子下不可见）。`MinionPool/SpellPool` 本身顺序是
`db` 注册顺序（确定性），排除池实现。

**修复（最小，均匀随机语义不变）**：两处候选列表在喂 RNG 前
`sorted()`（minion 侧本就按 `_pool_candidates` 的 db 顺序构造，无需改）：
- `BrambleTunnelerScript.rally`: `sorted(choose_minions)` /
  `sorted(choose_spells)`；
- `FandralsFortuneScript.on_play`: `sorted(choose_spells)`。

**验证**：
- 引擎级子进程探针（Bramble rally + Fandral options，HS=0/1/2/3）输出
  逐位一致；
- env-upgrader 复现脚本 `runs/env_snapshot/hashseed_repro.py`：
  seed 4001–4006 在两 PYTHONHASHSEED 下 **trace_sha256_16 完全一致**
  （4001 `e1024d42d647e456`；4002 `1dd2c80d619e0bb3`；4003
  `90590472f2475fb9`；4004 `dd8ad5227f3b5ed6`；4005 `ef21175e099264d6`；
  4006 `5dab6c669ce29f38`）；
- 新增回归测试用**子进程 + 不同 PYTHONHASHSEED** 比引擎输出（同进程测试
  原理上覆盖不到该缺陷）；`test_batch_rally2` / `test_batch_unfreeze` /
  `test_batch_trinkets20` 等消费方全绿。

**边界/后续**：其它脚本若把 `frozenset`/`set` 迭代结果直接喂 RNG 仍有
同类风险；本批只修实测命中的两处，并以「多 seed 双哈希进程跑完整
rollout」作为验收手段（env-upgrader 脚本可复用作 CI 慢检）。

### F-36 补丁（第 3 处）：`BOUNTY_SPELL_IDS` frozenset → Rogers Bounty RNG（2026-10-26）

**文件**：`hsrl2/scripts/batches/batch_misc.py::SkyAdmiralRogersScript.on_gold_spent`；
测试 `hsrl2/tests/test_hashseed_determinism.py`（探针新增 Rogers 路径）。

**发现**（WS7 taverngym-integrator 环境级 sweep，seeds 0..29+4001/4002 ×
random/heuristic × `PYTHONHASHSEED=0/1`）：F-36 两处修复后仍有 2 例稳定
分裂——seed=2 / seed=3 + `opponent=random`（heuristic 全部一致，故只在
随机对手能走到的路径）。无扰动 RNG 日志定位：首个分歧调用
`label="rogers_bounty"`（HS0 pick=BG33_813 vs HS1=BG33_814，n=5 且 RNG
状态相同）。

**根因（F-36 同类第 3 处）**：`hsrl2/constants.py::BOUNTY_SPELL_IDS` 是
`frozenset({BG33_811..815})`；Rogers 用
`[b for b in BOUNTY_SPELL_IDS if spell_pool.available(b) > 0]` 构造候选后
直接 `game.rng.choice(cands, label="rogers_bounty")` → 同一 rng index 在
不同进程落到不同 Bounty 法术。

**修复**：候选列表改 `sorted(BOUNTY_SPELL_IDS)`（与
`batch_trinkets7.py:271` 既有写法一致；均匀随机语义不变，只固定 index→
card 映射）。

**验证**：
- `PYTHONHASHSEED=0/1/4 python3 -m pytest
  hsrl2/tests/test_hashseed_determinism.py -q` → 2 passed（Rogers 子进程
  探针：花 9 金发 1 个 Bounty，三 hashseed 输出逐位一致）；
- WS7 环境级回归 `tests/test_env_determinism_hashseed.py` seed=2/3 转绿
  （由 taverngym-integrator 复跑确认）；
- 引擎级整局 sweep（`/tmp` 脚本，8 人随机驱动 + 全状态指纹）seeds
  2000–2007/4001/4002 在 HS=0 vs 1 下**10/10 指纹一致**；
- 静态扫描（AST：set 字面量/frozenset 名 → 未 `sorted` 直接进
  `rng.choice/sample/shuffle`）在 hsrl2 引擎代码内**无其它命中**（3 处
  疑似均为 list/tuple 字面量误报，已人工复核）。

## F-37 Reborn 插入棋盘缺 7 上限检查 → board=8（不变量门禁捕获，2026-10-26）

**文件**：`hsrl2/game.py::_process_death_inner`（Reborn 分支）；测试
`hsrl2/tests/test_reborn_board_cap_f37.py`（3 例，先红后绿）。

**现象**（升级新增的 env 不变量门禁捕获）：
`python3 scripts/validate_env.py --games 20 --check-invariants` →
`structural invariant violations: 1`、`ok=false`；样本
`seed=5019: hero[P6]: board=8 > 上限 7`（turn 14、agent `end_turn` 后
稳定状态，P6 存活 7 血、棋盘 8 只）。

**最小栈（Lead monkeypatch 抓取）**：
```
batch_activate.py:748 activate -> game.destroy_minion(target)
game.py destroy_minion -> check_deaths -> _process_single_death
  -> _process_death_inner -> hero.board.insert(pos, m)   # Reborn 直插，无 board_full
```
机制：Activate 摧毁己方带 Reborn 的随从 → 死亡结算中亡语（/其它召唤）
把空位重新填满（7）→ Reborn 分支仍 `board.insert` → 8。

**参照证据（AutoTavern 36.6.3）**：
- `crates/taverngym/src/engine.rs::reborn` 用
  `if let Some(e) = self.summon(side, pos, m) { emit(Event::Reborn) }`——
  复生体走 **summon**，棋盘满则 `summon` 返回 None（**不 emit Reborn**
  = 复生体不返回）；`summon` 满盘分支在非战斗时把池副本回池
  （`if !self.combat { self.g.pool.return_minion(&m) }`）。
- `invariants.rs` 硬约束 `board <= 7`；官方 Reborn 语义为
  "summon it again with 1 Health"（hearthstone.wiki.gg/wiki/Reborn）。

**修复**：`_process_death_inner` Reborn 分支在插入前检查
`hero is not None and hero.board_full()`；满则不返回复生体——
- 不 fire `reborn`（没有复生体，与 AT summon 失败一致）；
- 按普通死亡收尾：`REBORN` tag 清除（已消耗）、进 `hero.graveyard`、
  注销监听器；非战斗（招募期）按普通死亡回池
  （`minion_pool.release_minion_entity`，与 AT 的
  `summon`→`return_minion` 同口径）；
- `_reborn_full_uuids`（Persisting Horror 满血复生标记）一并作废；
- 未满局面逐位不变（正常复生/战斗快照路径不受影响）。

**测试**（`test_reborn_board_cap_f37.py`）：
1. 7 满场 + 复生随从死亡 + 亡语召唤填满 → `board<=7`、复生体未入场、
   无 `reborn` 事件（修复前实测 **8**）；
2. 未满对照（5 只）→ 复生照常入场、事件触发、位置正确；
3. 7 满场但死亡让出空位（无额外召唤）→ 复生照常回归（不误判满场）。

**影响面**：仅在「复生体本应入场但棋盘已被死亡结算中的召唤填满」时改变
行为（旧行为 = 违反 7 上限）；其余 Reborn 路径（战斗/招募、Persisting
Horror、F-14 关键词恢复）逐位不变。引擎全量 4890 passed / 6 skipped；
`validate_env --games 20 --check-invariants` 复跑 **ok=true / violations 0**。
