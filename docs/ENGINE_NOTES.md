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







