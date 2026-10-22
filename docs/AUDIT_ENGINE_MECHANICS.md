# 引擎机制审计：抉择 / 发动 / 目标 / 黑暗之赐 / 英雄技能 / 三连·发现·饰品

> 审计对象：`hsrl2/`（vendored 引擎）+ `data/`（官方 **37.0.0.255130** 基线）
> 审计方式：**只读**——`CardDB.load()` + `REGISTRY` 导入 + 静态源码/数据/测试检索；
> 未运行真实游戏、未修改代码以外的任何文件（本文件除外）。
> 基线口径（`data/bg_summary.json`）：BG 卡 3,534；池内随从 273；池内法术 76；
> 英雄 118；英雄技能 165；饰品 409（商店可提供 357）；Dark Gift 47；
> `REGISTRY` 1,460 条脚本；`hsrl2/tests` 140 文件 / 约 4,720 个 test 函数。
>
> 结论先行：**英雄技能/三连/发现（随从）/饰品商店流程/ACTIVATE 基础结算/Dark Gift
> 引擎购买链路均已实现且有较厚测试；真正的缺口集中在「跨机制组合协议」**
> （Choose One × 目标 × 双效）、**「37.0 数据升级的脚本覆盖」**
> （饰品 41 张、英雄技能 17 个）、**「数据层机制元数据」**
> （choose_one 失真、target 不可表达、Dark Gift 窗口/数值硬编码）。

---

## 0. TL;DR 与优先级

| 优先级 | 缺口 | 类别 | 编号 |
|---|---|---|---|
| **P0** | 饰品商店 offer 池**未按 `REGISTRY` 过滤**：41/357 张无脚本饰品仍可被提供并购买（37.0 新增 27 张），扣金后 `on_bind` 缺失 = 空转动作 | 引擎缺失 | G-R1 |
| **P0** | **17/118 英雄的主技能无脚本**（含 37.0 新英雄 Drest'agath / Kith'ix / Jim Raynor / Kerrigan / Loh / Murozond / Morchie / Genn），env 英雄池却全量抽取 → 可选英雄技能恒不可用（死技能） | 脚本缺失 | G-H1 |
| **P0** | **Choose One 组合协议缺口**：`choose_options` 与 `needs_target` 互斥（引擎提前 return）、法术实体 `CHOOSE_BOTH` 不读、旧脚本 `choose="both"` 静默零效果 | 引擎缺失 + 脚本缺失 | G-C1/G-C2/G-C3 |
| **P1** | Dark Gift 5 张 37.0 新 gift 处于 DEFERRED：`EFFICIENCY` 需引擎 Activate 双触发钩子；`DESECRATION`/`WORSHIP`/`DOPPELGANGER`/`POLARIZATION` 所需引擎原语**已存在**，属脚本缺失/理由过时 | 引擎缺失 + 脚本缺失 | G-D1~G-D5 |
| **P1** | `choose_one` 数据字段由**文本兜底**生成：44 个标记中 9 个误报、3 个漏报；脚本被迫硬编码 Choose One 卡集合（两处重复） | 数据缺失 | G-C5 |
| **P1** | `PendingChoice.choose()` **只结算不出队、无幂等标记**：双调用重复结算；resolve 抛错时（env 已 pop）选择永久丢失，无回滚 | 引擎缺失 | G-P1 |
| **P1** | 「选择一个随从」**目标元数据不在数据层**（数据 JSON 无 `needs_target`/目标域字段）；99 个 `needs_target` 脚本中 53 个无 `target_candidates`（默认友方棋盘域） | 数据缺失 | G-T1 |
| **P1** | ACTIVATE 无 `Activate triggers twice`（EFFICIENCY）引擎钩子 | 引擎缺失 | G-A1 |
| **P1** | 法术/卡牌通用 Discover 缺口：`Discover` Action 只造随从，脚本层出现 4 个自定义 Discover Action | 引擎缺失 | G-F1 |
| **P2** | target 校验不对称、`target_count` 仅英雄技能、`use_activate` 无 `TURN_SKIPPED`/目标协议、Gilding 用 `activate_cost` 判定 0 费 Activate、Dark Gift 窗口/数值/队列配对硬编码、kind 无枚举、ENGINE_API 行号锚点过期等（见 §4） | 混合 | G-T2…G-X4 |

**最严重 3 个缺口**：G-R1（饰品空转，直击 RL 动作/奖励有效性）、G-H1（英雄技能死技能，含新赛季英雄）、G-C1/C2/C3（Choose One 组合与双效静默丢效果）。

---

## 1. 机制总表（live 需求 → 引擎 → 数据 → 测试 → 缺口）

> 「live 需求」依据：`docs/reference_old/S14_DIFF_REPORT.md`（37.0 卡面逐条）、
> `docs/reference_old/REFACTOR_PLAN.md` §6.1–6.2（Activate/Dark Gift 官方说明）、
> `docs/reference_old/MECHANICS_REFERENCE.md` §18.3/§26/§31（饰品/三连/英雄技能）、
> `docs/LIVE_TO_SIM_GAP.md`（真实对局观测：choose_one 38 次、target 34 次、
> choice/confirm 62 次、三连奖励/英雄技能仍空白）。
> 引擎行为依据见 §2 逐条 file:line。

| 机制 | live 需求（官方/真实对局） | 引擎实现 | 数据字段 | 测试 | 结论 / 缺口 |
|---|---|---|---|---|---|
| **抉择 Choose One** | 打出时二选一；金色双倍；`CHOOSE_BOTH`（棋盘光环 / 英雄 tag / 实体 tag / 308 饰品）双效合并；部分抉择卡同时需要目标；法术亦有抉择 | `PendingChoice(kind="choose_one")`：`game.py:1120-1135`（随从）、`1513-1530`（法术）；`choose` 经 `ctx["choose"]` 进钩子 `1156-1165` | `choose_one` 字段存在但**文本兜底**（真 23 base / 标 25 base，9 误报 3 漏报）；无「抉择+目标」组合字段 | `test_engine_gaps.py:225`（基础）；`test_batch_choose_one.py`（7 池卡+金色+308 光环）；`test_gem_day.py:59`；`test_batch_unfreeze.py:397-470`（Fandral） | **部分实现**：池内 12 个真实 Choose One 实体（7 随从 + 5 法术）均有选择结算；但协议三分裂（引擎 14 / 自建 5 / 缺失 10 base），组合与双效有 P0/P1 缺口（G-C1~G-C7） |
| **发动 ACTIVATE** | 点击棋盘随从、花 `activate_cost` 金、每回合 1 次、招募阶段结算；部分发动需选目标；37.0 新增「Activate triggers twice」gift | `game.py:1908-1922`：`ACTIVATE`/`ACTIVATE_USED_THIS_TURN`/`ACTIVATE_COST` 判定 → 扣费 → `run_script_hook("activate")`；tag 自举 `3750-3758`；回合重置 `369-371` | `activate` / `activate_cost`（cost=0 按设计省略，引擎用 keyword 兜底） | `test_batch_activate.py`（10 卡/金色全路径）；`test_cards_batch1.py:390-445`（Kelp 定向）；`test_batch_37x_payloadgap1.py:905-925`（activate_target）；`test_batch_37x_discard.py`（0 费） | **基础完备**：池内 **23/23** 有脚本且含 `activate` 钩子；缺口集中在「双触发钩子」（G-A1）、目标协议不属引擎（G-A3）、0 费/Gilding 判定（G-A4） |
| **选择一个随从（target）** | 战吼/法术/英雄技能/Activate/发现等选择合法目标；目标域含友方棋盘、酒馆、手牌、对手；部分效果 2 目标 | `play_minion` 定向战吼 `game.py:1137-1154`（**引擎校验候选**）；`play_spell` `1531-1544`（**不校验显式 target**）；`cast_spell_effect` 随机目标 `1638-1656`；英雄技能多目标链 `2137-2171` + 结算前复核 `2189-2191`/`2241-2257`；Activate 无引擎目标协议（脚本自建） | **无任何 target 元数据**（`defs.py`/数据 JSON 均无）→ 全靠脚本类属性 `needs_target` / `target_candidates` / `target_count` | `test_engine_gaps.py:163-224`（定向战吼/落空）；`test_engine_primitives.py:1601-1638`（双目标链）；大量批测；无「非法显式 target」「目标域数据」测试 | **可用但契约分裂**：REGISTRY 99 个 `needs_target` / 46 个 `target_candidates`；数据层无法表达（G-T1），法术不校验（G-T2），多目标仅技能（G-T3） |
| **黑暗之赐 Dark Gift** | 第 3 回合起 3 金、每回合 1 次、每局 3 次，从 3 个「随从+绑定 gift」中选 1，随从入手；gift 池按回合窗口/tier 曲线/随从资格过滤；部分卡牌/英雄技能/饰品也能以 Dark Gift 授予 | 引擎主链路完备：`use_dark_gift` `game.py:2261-2315`、trio `2317-2346`（T6 最常见种族保底）、配对 `2348-2394`、效果分派 `2400-2419` + 42 个 handler `5156-5623`；DEFERRED 集 `darkgifts.py:159-160` | `dark_gift` 布尔标志（47/47 在 `data/bg_dark_gifts.json`）；**窗口、数值、资格限制均不在数据里**（硬编码） | `test_s14_mechanics.py:58-97`（窗口全量）、`99-148`（tier 曲线/过滤）、`149-284`（gating/三选一）、`285-440`（配对资格）、`441-615`（42 handler 效果） | **引擎通用实现强**（47/47 windows + 42 handler + 5 显式 DEFERRED、分派表缺项即 assert）；缺口 = 5 张 DEFERRED（G-D1~D5）+ 窗口/数值数据化（G-D6）+ 脚本重复配对（G-D7） |
| **英雄技能** | 多技能槽（主 + 第二槽/替换/变体）、费用动态覆写、可用性门槛、每回合/每局次数、定向/双目标、被动技能、挂起期配额复核、回滚 | 完备：`use_hero_power` `game.py:2079-2172`、`_finish_hero_power` `2174-2239`、`hero_power_cost` `2070-2077`、第二槽 `1988-2031`、替换 `2056-2068`、回滚 `2033-2054`、on_bind 接线 `1965-1986`；被动/无脚本诚实拒绝 `2111-2115` | `hero_power_dbf`(Tag380) → `hero_power_id`（`db.py:44-50`、生成器 `generate_bg_data.py:279-282`）；cost/tier 等字段完整 | 极厚：`use_hero_power` 出现 243 次/18 文件；`test_engine_primitives.py:1397-1638`（接线/可用性/费用覆写/替换/每局次数/双目标）；`test_engine_gaps.py:821-925`（双槽/回滚） | **引擎契约完备**；**覆盖缺口在脚本**：129/165 power def 有脚本、101/118 英雄可用；**17 英雄主技能无脚本**（G-H1，P0） |
| **三连奖励 / 发现** | 3 张同名自动合金；棋盘合成立即弹奖励、手牌合成打出时弹；奖励 = 发现 tier+1（部分异变=本档）；发现受池约束、三选一、金色发现只占 1 池 | `check_for_triple` `game.py:1247-1364`（含 Elemental of Surprise 替代、按种族阈值、监听注销）；`_grant_triple_reward` `1378-1401`（`Discover(kind="triple_reward")`）；`actions/discover.py:118-207`（池预留/释放/满手排队） | `triple_upgrade_id`/`triple_base_id`/`tech_level` 完整 | `test_engine_gaps.py:62-160`（三连 6 例）；`test_engine_primitives.py:1650-1686`（金色发现池平衡）、`1064`（种族三连阈值）；40 处 triple_reward 断言/13 文件 | **机制完备**（三连+随从发现）；唯一缺口：`Discover` 只支持随从，法术/卡牌发现由 4 个脚本自定义 Action 顶替（G-F1，P2） |
| **饰品选择** | T6 Lesser / T9 Greater 各一次，4 选 1 + 放弃；花金币；档位由 spell_school；跨局不重复；类型关联保底；第二技能槽可被饰品副本占用 | `_begin_recruit_for` 触发 `game.py:419-431`；`_offer_trinkets` `4997-5052`（4+None、`PendingChoice(kind="trinket_offer")`、购买扣费/事件）；授予/复制/替换/第二槽 `4903-4995` | `trinket` 布尔 + `spell_school`(11/12) + `evolution_card_id` 关联卡；`db.trinket_offer_pool()` `db.py:108-136` 排除 token/升级变体 | 109 处 `trinket_offer`/37 文件；`test_engine_primitives.py:1873-1998`（T6/T9/提前 Greater/放弃）、`2120`（档位池）；`test_engine_gaps.py:925-1127`（授予/复制/第二槽） | **流程完备但 offer 池未过注册闸**：41/357 无脚本仍可被提供（G-R1 P0、G-R2 P1） |
| **PendingChoice（横切契约）** | 引擎把「发现/三选一/目标/任务/饰品」挂起给外部策略结算；FIFO；只处理队首；pop 后 choose | `PendingChoice` `game.py:138-171`；引擎自产 kinds：`choose_one`/`battlecry_target`/`spell_target`/`hero_power_target`/`dark_gift`/`discover_*`/`triple_reward`/`quest_offer`/`trinket_offer`；`choose()` **不出队** | 无（kind 无白名单，脚本可自定义 ≥54 种） | 552 处 `pending_choices`/73 文件，但**无**「双 choose 重复结算」「resolve 抛错丢选择」契约测试 | **契约清晰但无防护**（G-P1 P1）；kind 无枚举 + 文档漂移（G-P2 P2） |
| **卡牌数据字段** | 机制参数应可由数据驱动（窗口/数值/目标/关键字） | 读 `defs.py` 字段 | 见 §3 | `test_dynamic_script_data_migration.py` / `test_script_data_num.py` 等 | **choose_one 失真、target 缺失、Dark Gift 窗口/数值缺失**（G-C5/G-T1/G-D6） |

---

## 2. 逐机制证据与缺口

### 2.1 抉择 Choose One

**引擎实现（契约）**
- `PendingChoice` 定义：`hsrl2/game.py:138-171`；`choose()` 只结算不出队（`148-153`），
  回调后广播 `card_discovered`（`154-171`，`discover_hero_power` 显式排除，`game.py:47`）。
- 随从：`play_minion` 先入场（`1118`），再分流——`CHOOSE_BOTH` 判定 `1123-1125`
  （hero tag / 棋盘任意 `CHOOSE_BOTH` 随从 / **随从实体 tag**）；`choose_options`
  存在时入队 `kind="choose_one"`，`resolve_callback` 调
  `_run_play_effects(..., choose=key)`（`1126-1135`）；`both=True` 时直接传
  `choose="both"`（`1127-1129`）。
- 法术：`play_spell` 同构分支 `1513-1530`；`both` 判定 `1517-1518`
  （hero tag / 棋盘随从光环，**不读法术实体 tag**）。
- 效果入口：`_run_play_effects` 把 `target`/`choose` 注入 `ctx`
  （`1156-1165`），金色 ×2 + Brann/额外战吼配额（`1166-1203`）；
  `_finish_play_spell` 同理（`1702-1704`）。
- `CHOOSE_BOTH` tag 定义：`hsrl2/tags.py:222`；`CHOOSE_ONE`（引擎内部）`tags.py:214`。

**数据**
- 生成器把 `choose_one` 当作**文本兜底关键词**：`tools/generate_bg_data.py:387-389`
  （`if "Choose One" in text`），`XML_KEYWORD_MAP`（`tools/generate_bg_data.py:116-122`）
  **不含** CHOOSE_ONE → 数据字段不是权威标签。
- 实测（本审计脚本）：`choose_one` 标记 **44** def（含金色），文本标题正则命中
  **38** def / 23 base；**9 个误报**（BG31_323/_G、BG31_327/_G、BG31_329/_G、
  BG31_892、BG36_331/_G——均为「提及型」触发/光环/获取卡）；**3 个漏报**
  （BG30_117t、BG30_117_Gt、BG31_893）。
- 脚本因此硬编码 Choose One 池卡集合，且**两处重复**：
  `hsrl2/scripts/batches/batch_rally2.py:64-78`（7 随从 + 4 法术，
  供 Glass of Perspective / Bramble Tunneler 用）与
  `hsrl2/scripts/batches/batch_unfreeze.py:50-63`；漂移守护测试见
  `hsrl2/tests/test_batch_choose_one.py:82-130`。
- 池内实况：7 张 Choose One 随从 + 5 张 Choose One 池法术；**14/44 标记 def
  走引擎 `choose_options` 协议**（= 7 随从 + 7 金色；另有 BG31_893 令牌 1 张），
  其余 30 个标记 def：9 误报、5 张池法术走脚本自建协议、10 个 base 卡无脚本
  （非池/旧赛季：BG26_355、BG30_110、BG30_117(+t/_Gt)、BG30_128、BG31_144、
  BG31_325、BG31_329、BG31_825、BG31_842、BG31_884）。

**测试**
- 引擎基础：`hsrl2/tests/test_engine_gaps.py:225-248`（Choose One 挂起+key 传递）。
- 批级：`test_batch_choose_one.py`（Crater Miner / Sly Infiltrator / Snare Trapper /
  Veteran Brigand / Turbo Hogrider / Thorned Trailblazer / Intrepid Botanist 等，
  `131-635`）；`test_gem_day.py:59`（CHOOSE_BOTH 光环双效）、
  `test_engine_primitives.py:802-827`（hero 级 CHOOSE_BOTH）、
  `test_batch_unfreeze.py:397-470`（Fandral 实体 tag/双效代理）。
- **缺失**：`choose_options` × `needs_target` 组合、旧脚本 `choose="both"`、
  法术实体 `CHOOSE_BOTH` 的引擎回归；Sprightly Scarab / Fearless Foodie 无单测
  （`batch_misc.py` docstring 引用 `test_batch_misc.py`，该文件**不存在**，
  仅有 `test_batch_misc_final.py` 且不覆盖这两张）。

**缺口**

#### G-C1（P0，引擎缺失）`choose_options` 与 `needs_target` 互斥
- 证据：`game.py:1126-1135` 命中 `choose_options` 后**直接 `return True`**，
  永远到不了 `1137-1154` 的定向战吼分支；两个分支无组合逻辑。
  脚本层被迫在 `battlecry` 内自建目标选择：`batch_misc.py:1116-1121`（docstring
  明示「缺口 #4」）、`batch_misc.py:1152-1174`（`SprightlyScarabScript` 自 append
  `kind="battlecry_target"`）；同批报告 `batch_misc.py:52-54`。
- 影响：金色触发两次时目标选择链顺序由脚本偶然实现；目标候选校验、落空语义、
  观测/动作映射均无引擎背书；类似卡若脚本作者漏写则**无目标提示、效果静默落空**。
- 最小修复：`play_minion`/`play_spell` 改为「先解析目标挂起 → choose 挂起 →
  两者就绪后 `_run_play_effects`」，或提供统一的 `_pending_play_intent`
  状态机；`PendingChoice.resolve_callback` 支持「继续解析下一步」。
- 验收：新增引擎测试：带 `choose_options + needs_target` 的脚本打出后依次产生
  2 个 PendingChoice，选择顺序与 `ctx["target"]/ctx["choose"]` 同时到达钩子；
  Sprightly Scarab 显式 target + choose 双参数路径。

#### G-C2（P0，脚本缺失）旧 Choose One 脚本不处理 `choose="both"`（静默零效果）
- 证据：`batch_misc.py:1142-1150`（`_apply` 只匹配 `"reborn"`/`"windfury"`，
  `"both"` 返回 `None`）与 `batch_misc.py:1216-1220`（Fearless Foodie 只匹配
  `"improve"`/`"gems"`，`"both"` 返回 `None`）。缺口清单自身在
  `batch_choose_one.py:58-64` 已登记。对照正确实现：
  `batch_choose_one.py:135`（`_both` 辅助）与 `batch_choose_one.py:587-592`。
- 影响：Thorned Trailblazer（`BG31_327` 光环）/ Trailblazer Sticker（`BG36_MagicItem_308`）
  / Fandral's Fortune 发现路径下，BG27_084、BG30_123 两张「有双效」时不产生任何效果。
- 最小修复：两张脚本改用与 batch_choose_one 相同的 `_both(key, branch)` 分派；
  加 `choose="both"` 单测（含金色总值为双分支之和）。
- 验收：`game.heroes[0].set(CHOOSE_BOTH)`/棋盘放 Trailblazer 后打 BG27_084、
  BG30_123，断言两分支效果都生效且金色总额正确。

#### G-C3（P1，引擎缺失）法术实体级 `CHOOSE_BOTH` 未读取
- 证据：`game.py:1517-1518`（法术分支只查 hero tag 与棋盘随从，**无** `spell.has(CHOOSE_BOTH)`）
  vs `game.py:1123-1125`（随从分支查实体 tag）。脚本层以代理绕过：
  `batch_unfreeze.py:370-378`（`_CombinedChooseOneProxy` 注释直指引擎缺口）、
  `batch_unfreeze.py:403-459`（`_mark_combined_effects` 手动抽干队列实现双效）。
- 影响：Fandral's Fortune「Discover a Choose One card. It has both effects
  combined」必须依赖脚本代理；任何未来「实体置 tag」路径（发现/变形/复制）
  在法术侧都会失效。
- 最小修复：`game.py:1517` 增加 `or spell.has(GameTag.CHOOSE_BOTH)`；
  更新 `batch_unfreeze` 代理退化为可选；补引擎测试。
- 验收：构造带 `CHOOSE_BOTH` tag 的 Choose One 法术实体 → `play_spell` 直接
  以 `choose="both"` 结算、不产生选择窗。

#### G-C4（P2，脚本缺失）5 张池法术仍用自建 Choose One 协议
- 证据：`batch_spells4.py:61-69`（`_queue_choose_one` 手动 append
  `kind="choose_one"`）；调用点 `198/254/370`；滞后 docstring
  `batch_spells4.py:13-16` 与 `39-40` 仍称「play_spell 无 choose_options」。
  5 张卡：BG31_880/881/886/890（+ BG31_892 由 batch_unfreeze 专门处理）。
- 影响：引擎的 `CHOOSE_BOTH` 分流、golden 语义、目标组合协议对它们**完全无效**
  （自建脚本不看 hero tag —— `batch_choose_one.py:62-63` 明示「不受光环影响」）；
  同一机制三套写法，维护/审计成本高。
- 最小修复：迁移 5 张到引擎 `choose_options` + `battlecry/on_play` 的
  `ctx["choose"]` 协议（引擎分支已就绪），删除 `_queue_choose_one`；同时补
  Spell 侧 `choose="both"` 测试。
- 验收：5 张卡在 CHOOSE_BOTH 光环下不弹选择、两分支并联；原二选一测试不变。

#### G-C5（P1，数据缺失）`choose_one` 字段不是权威标签
- 证据：生成器 `tools/generate_bg_data.py:387-389`（文本兜底）；缺失严重性见 §2.1 数据段
  （9 误报 / 3 漏报）；两处硬编码集合 `batch_rally2.py:60-78`、
  `batch_unfreeze.py:50-63`；漂移风险由 `test_batch_choose_one.py:82-130` 手动守护。
- 影响：任何「按 CardDef.choose_one 判定」的引擎/工具/审计（含
  `batch_unfreeze._mark_combined_effects`，`batch_unfreeze.py:423-425`）都会把
  「提及型」卡当 Choose One 卡；官方若调整文本（如本地化/换行）会漂移。
- 最小修复（二选一）：
  (a) 生成器导出权威字段（若 CardDefs 有 CHOOSE_ONE tag）或标题正则导出
  `choose_one_title=true`（排除 `spellcraft_id` 宿主，规则同
  `batch_choose_one._is_choose_one_card`，`batch_choose_one.py:102-130`）；
  (b) 引擎提供唯一判定函数 `is_choose_one_card(db, card)`，替换两处硬编码集合，
  数据字段仅作提示。
- 验收：数据全库「标题正则 ∩ 非 Spellcraft 宿主」= 引擎判定函数输出；
  现有漂移守护测试保留并指向同一实现。

#### G-C6（P2，脚本缺失）10 个 base Choose One 卡无脚本（非池/令牌）
- 证据：`BG26_355` Disco Shuffler、`BG30_110` Mirage Conjurer、`BG30_117t/_Gt`
  （Volcanic Visitor 的 Spellcraft 令牌）、`BG30_128` Sleeping Sea Glass、
  `BG31_144` Adaptive Ancestor、`BG31_325` Crystal Infuser、`BG31_329` Boar Gamer、
  `BG31_825` Grace Farsail、`BG31_842` Nether Construct、`BG31_884`
  The Road Less Traveled——`REGISTRY` 均无脚本，`is_pool_minion/is_pool_spell` 均为 False。
- 影响：当前「随机获得 Choose One 卡」候选是硬编码 7+4 池卡集合，故不会命中；
  但若未来效果改为「全库 Choose One」或这些卡回归池，则拿到即空效果。
- 最小修复：对「可达性」做一次性判定——确认不可达则在数据/注册审计里标
  `not_reachable`；可回归的卡补脚本。
- 验收：audit 工具输出「choose_one 卡 × 脚本/可达性」三方矩阵，0 未知项。

#### G-C7（P1，引擎缺失）`PendingChoice.choose()` 无出队/无幂等 → 双结算风险
- 详见 G-P1（横切契约），此处只记「抉择是高频触发点」。
- 证据：`game.py:148-153`；`docs/ENGINE_API.md:1109-1126` 用示例说明
  「再次 choose 会重复结算」；env 侧正确（`hsbg/env/driver.py:948-958`：
  `pop(0)` 后 `choose`；`1092-1133` FIFO 结算）。

---

### 2.2 发动 ACTIVATE

**引擎实现**
- 标签：`hsrl2/tags.py:174-176`（`ACTIVATE=4089`、`ACTIVATE_COST=4090`、
  内部 `ACTIVATE_USED_THIS_TURN=1022`）。
- 结算：`game.py:1908-1922`——校验 `ACTIVATE`、未用过、控制者/在场、
  `ACTIVATE_COST`（默认 1），扣金 → 置已用 → `run_script_hook(minion, "activate")`
  → 广播 `activate_used`。
- tag 自举：`game.py:3750-3758`——数据在 cost=0 时省略 `activate_cost`（falsy），
  故以关键词 `activate` 为权威、缺省 cost=0（F-08 修复，`docs/ENGINE_NOTES.md` F-08）。
- 回合重置：`game.py:369-371`（每回合清 `ACTIVATE_USED_THIS_TURN`）。
- 效果本体全部在脚本 `activate` 钩子；定向/多段由脚本自建 PendingChoice。

**数据与覆盖**
- `data/bg_summary.json`：池内 `with_activate: 23`；审计实测池内 23 张
  **全部**有 `REGISTRY` 脚本且含 `activate` 钩子（23/23）。
- 数据字段：`activate`（52 def 含金色，`generate_bg_data.py:315-320`）、
  `activate_cost`（41 def；cost=0 省略为设计口径）。
- 5 张 0 费 Activate（`activate_cost=None`，靠 keyword）：BG28_582、BG36_099、
  BG36_300、BG36_311、BG36_312。
- `batch_activate.py:36-41` 明示协议：金币/每回合一次由引擎保证，脚本只写效果；
  `[Targeted]`/Choose 类经 PendingChoice 建模（kind 约定 `activate_target`/
  `tavern_pick`）。
- 实测脚本中 `kind="activate_target"` 14 处，例 `batch_activate.py`（Lionfish/
  Kelp 等）、`test_cards_batch1.py:390-445`（Kelp Keeper 定向触发战吼）、
  `test_batch_37x_payloadgap1.py:905-925`、`test_batch_rally2.py:671-690`。

**测试**：`hsrl2/tests/test_batch_activate.py`（10 卡：Living Prison / Lionfish /
Hired Mount / Castaway / Fruit Vendor / Decoy Conjurer / Jailer / Drone /
Breakout / Bellringer，含金色/空馆/池耗尽）；`test_batch_37x_discard.py`
（cost=0 的 F-08 回归）；`test_cards_batch1.py:390`（Kelp）；`test_batch_rally2.py:673`。
**缺失**：引擎级契约测试（TURN_SKIPPED 守卫、0 费默认、双触发）不存在。

**缺口**

#### G-A1（P1，引擎缺失）无「Activate triggers twice」钩子（Dark Gift EFFICIENCY）
- 证据：`game.py:1908-1922` 只执行一次 `run_script_hook(minion,"activate")`；
  `rg 'activate_times|ACTIVATE_TIMES|activate twice' hsrl2` 仅命中
  `darkgifts.py:77/115/159` 与测试（无引擎实现）；EFFICIENCY 在
  `darkgifts.py:159-160` DEFERRED。
- 影响：37.0 新 gift `BG36_MidGameEffect_000t78` 完全无效果（当前 DEFERRED 静默不生效）。
- 最小修复：`use_activate` 增加倍率读取（仿 `hp_times`，`game.py:2228`），
  例如 `times = 1 + (1 if minion.get(GameTag.DARK_GIFT) == DG.EFFICIENCY else 0)`
  或脚本可声明的 `activate_times`；循环执行钩子并保证「扣费一次」。
- 验收：挂 EFFICIENCY 的 Activate 随从一次激活触发两次钩子、费用只扣一次；
  `darkgifts.DEFERRED_GIFTS` 移除 EFFICIENCY 且 tests/s14 更新。

#### G-A2（P2，引擎缺失）`use_activate` 缺 `TURN_SKIPPED` 守卫
- 证据：`game.py:1908-1912` 无 `hero.get(GameTag.TURN_SKIPPED)` 检查；
  对照 `play_minion` `game.py:1072-1073`、`play_spell` `1493-1494`、
  `use_hero_power` `2081-2082`、`use_dark_gift` `2262-2263` 均有。
- 影响：被冻结/跳过回合的玩家仍可 Activate（与其它动作口径不一致），
  env 镜像需单独特判。
- 最小修复：`use_activate` 首行加同一守卫；补一条引擎回归测试。
- 验收：`TURN_SKIPPED=True` 时 `use_activate` 返回 False 且金币不变。

#### G-A3（P2，引擎缺失）Activate 目标协议非引擎级
- 证据：`use_activate` 不读 `needs_target`/`target_candidates`（对比
  `play_minion:1137-1154`、`play_spell:1531-1544`、`use_hero_power:2137-2171`）；
  脚本各自 append（`batch_activate.py` 多处、`test_batch_37x_payloadgap1.py:905`）。
- 影响：目标合法性无引擎复核、`PendingChoice` kind 命名单靠批约定、
  env 无法从统一协议生成 activate 目标候选（`hsbg/env/driver.py` 需特判）。
- 最小修复：把 `use_activate` 改为与英雄技能同构（`needs_target`/`target_count`
  协议，挂起期复核目标仍在候选域）；或至少在 `docs/ENGINE_API.md` 声明
  「activates 目标永远由脚本自建」并加 lint。
- 验收：新增带 `needs_target` 的假 Activate 脚本单测，验证引擎产生
  `PendingChoice` 并在选择后结算；现有 Kelp 测试语义不变。

#### G-A4（P2，数据/脚本一致性）Gilding 资格用 `activate_cost is not None` → 0 费 Activate 漏判
- 证据：`hsrl2/darkgifts.py:208-209`（`is_activate_minion` 判 `activate_cost`）
  + `darkgifts.py:353-357`（Gilding 不给 Activate 随从）；但数据 cost=0 时
  省略字段（`generate_bg_data.py:318-320`），5 张 0 费 Activate 会 `None`。
- 影响：Gilding 可被配给 5 张 0 费 Activate 随从（dev post 明示不可）。
- 最小修复：谓词改 `d.activate_cost is not None or "activate" in d.keywords`
  （与 `game.py:3756` 同口径）。
- 验收：对 5 张 0 费 Activate 卡，`DG.eligible_gifts(..., GILDING)` 返回不含
  Gilding；新增参数化测试。

---

### 2.3 「选择一个随从」目标

**引擎实现（四条路径的域/校验语义）**
- 战吼：`game.py:1137-1154`——未给 target 且候选非空 → `PendingChoice(kind="battlecry_target")`；
  target 不在候选 → **战吼落空但随从照常入场**；无候选 → 落空。
- 法术：`game.py:1531-1544`——只处理 `target is None` 的挂起；**显式传入的
  target 不校验**（文档亦承认：`docs/ENGINE_API.md:510-513`「引擎不校验其是否在候选内」）。
- 效果施法：`cast_spell_effect` `game.py:1638-1656`——`target=None` 时从候选
  **随机**取一个（不是玩家选择），无候选落空。
- 英雄技能：`game.py:2137-2171` 多目标链（`target_count`）、`2189-2191` 结算前
  用脚本候选域复核、`2241-2257` `_hero_power_target_ok`。
- Activate：无引擎目标协议（见 G-A3）。
- 候选域来源只有脚本约定属性（`docs/ENGINE_API.md:848-...`「目标需求识别」：
  `needs_target`、`target_candidates(minion|spell|hero, game)`、`target_count`）。

**数据**
- `defs.py:16-79` 无任何 target 字段；数据 JSON（minions/spells/hero_powers/trinkets/cards）
  键集合中 target 相关字段**为空**（本审计以 `json.load` 全键扫描确认）。
- 实测 `REGISTRY`（1,460 脚本）：`needs_target=99`、`target_candidates=46`、
  `target_count!=1` 仅 2 个（`BG28_309_G`、`BG20_HERO_201p`）。
- 文本启发式扫描（`choose a|give a|give another|target|set another|cast .* on`）
  发现 **39 个池内 minion/spell 文本暗示目标但脚本未声明 `needs_target`**；
  人工抽样其中大多数是「give a friendly/random」类非定向文本（如
  Spellcraft 宿主随从、被动触发、随机目标），真实缺口集中在
  Choose One 组合（BG27_084 走脚本自建，见 G-C1）与 Activate 目标（G-A3）。

**测试**
- `test_engine_gaps.py:163-224`（定向战吼挂起/落空/显式 target）；
  `test_engine_primitives.py:1507-1638`（英雄技能费用覆写/双目标链）；
  `test_engine_primitives.py:2958-3005`（挂起期每回合配额复核）；
  各批 `needs_target` 卡单测（18 处/12 文件）。
- **缺失**：显式非法 target 的法术路径、目标域数据/镜像、Activate 目标引擎协议。

**缺口**

#### G-T1（P1，数据缺失）目标元数据无法由数据表达
- 证据：`hsrl2/defs.py:16-79`（无 target 字段）；`tools/generate_bg_data.py` 无
  target 导出；`docs/ENGINE_API.md:850-851` 明言「引擎用脚本类的约定属性声明，
  而不是数据字段」。
- 影响：99 个 `needs_target` 中 **53 个没有 `target_candidates`** → 走默认
  「友方存活棋盘随从」域；真实对局中酒馆/手牌/对手目标（Xyrella/Maiev/Baz'hial/
  Cookie 等）只能靠各脚本自觉覆盖。数据审计工具、live 目标候选枚举
  （`docs/LIVE_TO_SIM_GAP.md` L06 `select/target/dragcast` 多次 no_effect）与
  观测都无法从数据侧校验。
- 最小修复：(a) 生成器/维护表导出 `needs_target` + `target_domain`
  （BOARD_FRIENDLY/BOARD_ANY/TAVERN/HAND/OPPONENT/…，可由脚本注册表反填，
  fail-loud：`needs_target` 但无域 → 报错）；(b) `tools/audit_script_wiring.py`
  增加「文本目标子句 × needs_target」lint 清单，人工复核 39 条可疑项。
- 验收：所有 `needs_target` 脚本有显式目标域（默认域需显式声明 `DEFAULT_BOARD`）；
  audit 输出 0 未知。

#### G-T2（P2，引擎缺失）法术显式 target 不校验（与战吼不对称）
- 证据：`game.py:1531-1544`（仅 `target is None` 时查候选；显式 target 直奔
  `_finish_play_spell`，见 `1544`）；对照 `game.py:1143-1146`（战吼校验后落空）。
- 影响：env/自动化传入过期实体（已离场/非法域）时，脚本收到非法 target，
  可能 `GameStateError`（如对非友方随从加 buff 的操作）或静默错加；
  与战吼、英雄技能的「结算前复核」口径不一致。
- 最小修复：`play_spell` 显式 target 时按脚本候选域复核，不合法则按
  「效果落空、法术照常消耗」处理（与无候选语义一致）；补测试。
- 验收：对定向法术传非候选实体 → 返回 True、法术消耗、无效果、不抛错。

#### G-T3（P2，引擎缺失）`target_count` 多目标链未通用化
- 证据：仅英雄技能实现（`game.py:2137-2171`）；`_finish_play_spell`
  （`1682-1769`）与战吼路径（`1137-1154`）均无 `target_count`；
  脚本侧已记录该缺口：`batch_trinkets27.py:614`、`batch_trinkets29.py:859`
  （「`target_count=2` 对 `_finish_play_spell` 零命中」）。
- 影响：「Choose 2 / give 2 minions」类法术/战吼只能脚本自建链；目标候选
  去重与死亡重估逻辑在 4 条路径各写一遍。
- 最小修复：抽出 `Game._collect_targets(hero, script, n, owner_entity)` 通用链，
  战吼/法术/技能/Activate 共用；`n_targets>1` 时依次挂起并重估候选。
- 验收：新脚本声明 `needs_target + target_count=2` 的法术单测；既有
  `BG20_HERO_201p` 双目标测试不回归。

#### G-T4（P2，文档/契约）目标候选函数签名三分裂
- 证据：脚本 `target_candidates(minion/spell/hero, game)` 三种首参
  （`docs/ENGINE_API.md:855-865`；引擎调用点 `game.py:1139-1142`（minion）、
  `1533-1536`（spell）、`2142-2145`/`2251-2254`（hero））。
- 影响：脚本迁移/复用易错；审计工具无法静态校验。
- 最小修复：文档明确签名 + 提供基类/mixin `TargetProvider`（可选）；audit 工具
  按实体类型校验首参。
- 验收：wiring audit 覆盖全部 `needs_target` 脚本签名。

---

### 2.4 黑暗之赐 Dark Gift

**引擎实现（通用链路，非卡牌脚本）**
- 购买/三选一：`game.py:2261-2315`——第 3 回合起、3 金、每回合 1 次、每局 3 次
  （`constants.py:73-76`）；候选 = `DG.eligible_minions`；抽 3 个不同随从
  （`_draw_gift_trio` `2317-2346`，T6+ 常见种族保底）；每个随从配一个互不相同
  合法 gift（`_pair_gifts` `2348-2394`）；预 `acquire` 池 → 入队
  `PendingChoice(kind="dark_gift")`，选项为 `(minion_card_id, gift_card_id)` 二元组；
  resolve 释放未选项 → `create_minion` + `apply_dark_gift` + `pending_hand_add`。
- 门控/过滤：`hsrl2/darkgifts.py`——窗口表（`92-140`）、tier 曲线（`constants.py:78-82`）、
  随从资格（`249-285`）、gift 配对资格（`290-426`）、最常见种族（`429-450`）、
  加权（`453-463`）；`_DARK_GIFT_EFFECTS` 42 handler + `assert` 缺项 fail-loud
  （`game.py:5624-5627`）。
- 授予路径（其他卡）：英雄技能/饰品复用 `_pair_gift_options`
  （`batch_hero_combat3.py:177`，被 `batch_trinkets20.py:140/250`、
  `batch_trinkets22.py:314-321` 跨批复用），最终均走 `game.apply_dark_gift`
  （`batch_trinkets20.py:292`、`batch_hero_combat3.py:1221`）。
- 异常池耗尽：合法但无候选 → 消耗金币/次数、返回 True 无 PendingChoice
  （`2271-2273/2287-2288/2296-2297`，官方效果落空）。
- 基线口径：Dark Gift 按钮是 S14 赛季基线机制（官方 36.2 公告原文见
  `batch_anomalies.py:562-574`），异变 `BG36_Anomaly_002` 无叠加效果——与引擎一致。

**数据与覆盖**
- `data/bg_dark_gifts.json`：47/47 带 `dark_gift=true`，但**只有**
  `card_set/card_type/dark_gift/dbf_id/id/name/text` 七个字段。
- 窗口：注释声称权威 = 官方 37.0 CardDefs tag 4853/4854（`darkgifts.py:83-91`），
  但生成器 **未导出** 4853/4854（`tools/generate_bg_data.py:99-113` 的 TAG 表），
  窗口表是手写常量（`darkgifts.py:92-140`），测试对表值做断言
  （`test_s14_mechanics.py:58-97`）。
- 数值：`bg_cards.json` 的 47 个 gift 实体**无任何 `script_data_num_*`**；数值
  硬编码在引擎 handler（如 Fortitude +5/+5 `game.py:5186-5189`、Titanic
  Strength +1000 `5236-5238`、计数类 `5587-5598`、Dexterity `5608-5609`）
  并注释「XML 文本即权威」。
- 覆盖：42 handler APPLIED + 5 DEFERRED（`darkgifts.py:159-160`：
  POLARIZATION / EFFICIENCY / DESECRATION / WORSHIP / DOPPELGANGER）；
  `_missing` 断言保证窗口表非 DEFERRED 项 100% 有 handler（`game.py:5624-5627`）。

**测试**：`test_s14_mechanics.py` 六组（窗口/曲线/门控/三选一/配对/效果），
另有 `test_batch_anomalies.py`（grant 路径）与 `test_batch_hero_actives.py:
apply_dark_gift`（Mal ygos 交互）；**DEFERRED 只有 Polarization 一条测试**
（`570-582`）。

**缺口**

#### G-D1（P1，引擎缺失）EFFICIENCY（Activate 触发两次）→ 依赖 G-A1
- 证据：`darkgifts.py:77/115/159-160`（DEFERRED）；引擎无 Activate 倍率
  （见 G-A1 证据）；`apply_dark_gift` 对 DEFERRED 仅记审计日志
  （`game.py:2410-2413`）。
- 影响：37.0 新 gift 无效果（静默、但有 `dark_gift_audit_log` 可查）。
- 最小修复：实现 G-A1 后移除 DEFERRED，handler 改为在随从上置 Activate 倍率；
  补测试（激活一次触发两次、扣费一次）。

#### G-D2（P1，脚本缺失）DESECRATION（每弃一张牌 +3/+3）原语已具备
- 证据：`darkgifts.py:78/159`（DEFERRED）称依赖 discard 子系统；但
  `game.py:1044-1067` 已有 `discard_card`：`hero.cards_discarded_this_game += 1`、
  广播 `card_discarded`、分发 `on_discard`（F-08，`docs/ENGINE_NOTES.md`）。
- 影响：gift 空转。
- 最小修复：仿 `_make_counter_gift`（`game.py:5393-5415`）写计数型 handler，
  计数源 = `hero.cards_discarded_this_game`；从 DEFERRED 移除。
- 验收：弃牌 N 次后该随从 +3N/+3N；首回合施加时按既有计数补齐。

#### G-D3（P2，脚本缺失）WORSHIP（SoC 获得 Deity 属性）原语已具备
- 证据：`darkgifts.py:79/159`；Deity 子系统已有
  `game.py:4508` `give_deity_stats(hero, atk, health)` 与 `_soc_listener`
  （`game.py:5156`，gift 通用 SoC 接线器）。
- 最小修复：SoC 时调用 `give_deity_stats`（数值取 handler 参数/数据化后）；
  移除 DEFERRED；补测试（Deity 未选时行为按官方 AMBIGUOUS 记录）。
- 验收：SoC 后 Deity atk/health 增加预期值。

#### G-D4（P2，脚本缺失）DOPPELGANGER（SoC 召唤自身副本）原语已具备
- 证据：`darkgifts.py:80/159`；`hsrl2/actions/summon.py:34` `SummonPlainCopy`
  与 `game.py:5156` `_soc_listener` 均已存在（Battlecry/死亡召唤族广泛使用）。
- 最小修复：SoC 用 `SummonPlainCopy` 召唤自身（满场按官方落空/溢出规则）；
  移除 DEFERRED；补测试。

#### G-D5（P2，脚本缺失/理由过时）POLARIZATION（EoT 磁力吸附随机机械）
- 证据：`darkgifts.py:154-156` 注释称「引擎缺 Magnetic 合并子系统」；但
  `game.py:1463` `attach_magnetic` + `_magnetic_valid`（`1437-1461`）已实现
  磁力吸附（含数据例外）。DEFERRED 见 `darkgifts.py:159-160`。
- 最小修复：EoT 从池/手牌随机取 Magnetic 机械 → `create_minion` +
  `attach_magnetic`（需处理「吸附目标随从必须合法机械宿主」与满场语义）；
  更新过时注释；补测试。
- 验收：EoT 后宿主获得该机械属性/关键词、吸附实体离场。

#### G-D6（P1，数据缺失）窗口/数值/资格限制未数据化
- 证据：窗口硬编码 `darkgifts.py:92-140`；数值硬编码
  `game.py:5186-5239/5587-5622`；数据文件无 4853/4854/`script_data_num_*`；
  生成器 TAG 表 `tools/generate_bg_data.py:99-113` 无 4853/4854。
- 影响：37.0 已发生过 43→47 与数值/窗口变化；任何下次平衡更新都需改引擎 +
  手改常量 + 手改测试，且与「数据是权威」的仓库原则冲突；RL 侧无法从数据感知窗口。
- 最小修复：生成器导出 gift 实体 tag 4853/4854 与模板参数（若官方有）→
  `CardDef.dark_gift_min_turn/max_turn/params`；`GIFT_WINDOWS` 优先读数据、
  常量仅 fallback；数值 handler 改读 `CardDef.num()`（无参时保留文本常量并注释）。
- 验收：`data/bg_dark_gifts.json` 含窗口字段；删除常量后测试仍绿（用数据）；
  新增「窗口表 = 数据」一致性测试。

#### G-D7（P2，脚本/架构）脚本重复实现 trio 配对
- 证据：`batch_hero_combat3.py:177` `_pair_gift_options`（引擎 `_pair_gifts`
  的脚本镜像），被 `batch_trinkets20.py:140/250-258`、`batch_trinkets22.py:
  314-321` 跨批 import 复用；另有多个「Discover 一个带 Dark Gift 的随从」
  的饰品/英雄技能各自抽 trio。
- 影响：与引擎 `use_dark_gift` 的窗口/重抽/池预占语义可能漂移（如无重抽的
  简化路径 `batch_trinkets20.py:258`）；新增授予路径还得再复制。
- 最小修复：引擎暴露 `Game.offer_dark_gift_discover(hero, candidates=None,
  kind="dark_gift") -> bool`（内部复用 `_draw_gift_trio/_pair_gifts`），脚本统一调用。
- 验收：4 处调用点改为引擎 API；既有赠礼测试不回归。

#### G-D8（P2，测试缺失）DEFERRED 覆盖面
- 证据：`test_s14_mechanics.py:570-582` 只断言 Polarization DEFERRED；
  `DEFERRED_GIFTS` 5 项无「全部有审计日志」「窗口表全量」以外的守护。
- 最小修复：参数化测试遍历 `DEFERRED_GIFTS`：apply 后必在
  `game.dark_gift_audit_log` 记 `DEFERRED` 且不崩、不施加任何效果；移出
  DEFERRED 时该测试自动缩小集合。

---

### 2.5 英雄技能

**引擎实现（完整度最高的一组）**
- 使用：`game.py:2079-2172`——身份解析（主技能/第二槽 `hero_power_ids` `2012-2031`）、
  脚本缺失 `2111-2115`（诚实拒绝）、被动 `2113-2114`、`available(hero,game)`
  `2116-2119`、每回合次数 + `hp_uses` `2120-2126`、每局次数 `2127-2132`、
  费用 `hero_power_cost`（`2070-2077`，支持 `cost_override`）、
  目标链 `2137-2171`。
- 结算：`_finish_hero_power` `2174-2239`——挂起期金币/目标/次数/每局配额
  四重复核（`2177-2205`）、扣费计次（`2206-2219`）、`hp_times` 多次结算
  （`2228-2236`）、广播 `hero_power_used`（`2237-2238`）。
- 辅助：第二技能槽 `set_second_hero_power` `1988-2002`、替换 `replace_hero_power`
  `2056-2068`、回滚 `refund_hero_power_use` `2033-2054`、on_bind 幂等接线
  `wire_hero_power_on_bind` `1965-1986`。
- 数据：英雄→技能映射 `db.py:44-50`（`hero_power_dbf` Tag380 → `hero_power_id`），
  生成器 `tools/generate_bg_data.py:279-282`；技能费在 `cost` 字段。

**覆盖与测试**
- 165 个 HERO_POWER 定义中 **129 个有脚本**（62 active / 65 passive / 76 on_bind）；
  118 英雄中 **101 个主技能有脚本**。
- 测试极厚：`use_hero_power` 243 处/18 文件；引擎契约测试
  `test_engine_primitives.py:1397-1638`（接线 / available 门控 / cost_override /
  替换重置 / uses_per_game / 双目标链 / next_opponent），
  `test_engine_primitives.py:2958-3005`（挂起期配额超发防护），
  `test_engine_gaps.py:821-925`（双槽独立计数 / 未知技能拒绝），
  `test_engine_gaps.py:1203-1226`（回滚可用性）。
- 目标/pending：`hero_power_target`（`game.py:2166-2169`）；`discover_hero_power`
  三选一脚本自建且 `card_discovered` 事件显式排除（`game.py:47/159-160`，
  有专项测试 `test_engine_primitives.py:2527-2552`）。

**缺口**

#### G-H1（P0，脚本缺失）17 个英雄主技能无脚本 + env 全英雄池
- 证据：`data/bg_summary.json` 118 英雄；实测 `hero.hero_power_id` 全部有值，
  但以下 17 个主技能 `REGISTRY.get(power_id) is None`：
  BG20_HERO_202 Power of the Storm、BG20_HERO_242 Natural Balance、
  BG20_HERO_283 Dungar's Gryphon、BG21_HERO_000 Conviction、
  BG24_HERO_100 Whodunit?、BG25_HERO_100 Build-An-Undead、
  BG31_HERO_801 Lift Off、BG31_HERO_811 Spawning Pool、
  BG33_HERO_001 Heroic Inspiration、BG34_HERO_000 Alternate Timeline、
  BG34_HERO_004 Warped Conflux、BG35_HERO_001 King of Duality、
  **BG36_HERO_000 Incubate（37.0 新）**、**BG36_HERO_002 Dark Ritual（37.0 新）**、
  TB_BaconShop_HERO_21 Prestidigitation、TB_BaconShop_HERO_90 Come One, Come All!、
  TB_BaconShop_HERO_94 Prize Wall。
  引擎侧诚实拒绝：`game.py:2110-2115`（`script is None → return False`）。
  env 英雄池 = 全部 `BG*/TB_BaconShop_HERO*`（`hsbg/env/game_env.py:264-282`），
  118 个全可被抽中。
- 影响：约 **14.4%（17/118）** 的对局英雄技能恒不可用；live 对局中英雄技能本就
  未被 bot 实现（`docs/LIVE_TO_SIM_GAP.md` L02，`legal.powers` 未用），
  引擎侧这个缺口会让「技能可用性」观测与真实对局不一致；训练时这些英雄
  等于无技能，污染策略/评估。
- 最小修复（分两步）：
  1. **立即**（P0 止血）：env 英雄池过滤为「主技能有脚本」的 101 个（或对
     无脚本技能提供显式占位脚本 `available=False` 并在观测中标注），避免
     静默死技能进训练；
  2. **补齐**：按 37.0 新英雄优先（Drest'agath/Kith'ix/Jim Raynor/Kerrigan/
     Loh/Murozond/Morchie/Genn），旧英雄按当前赛季可选择性排序；每个技能需要
     规则证据（卡面文本 + wiki/官方公告），走 `docs/agents/EFFECT_SCRIPT_SOP.md`。
- 验收：`audit` 输出「英雄 × 主技能脚本」= 118/118；env 抽样 100 局
  `hero_power_usable` 对每个出现英雄至少一次 True（被动技能除外按被动口径）。

#### G-H2（P2，数据/脚本）36 个 power 定义无脚本（含替换变体）
- 证据：165-129 = 36 个 HERO_POWER def 无 `REGISTRY` 脚本，例如
  BG20_HERO_201p2 Spirit Swap、BG20_HERO_283p_t1/t2/t3、BG22_HERO_000p_t1-t4、
  BG22_HERO_001p_t1-t4、BG26_HERO_102p2 Minor Hymn、BG28_HERO_400p2 Lucky Roll、
  BG31_HERO_811p2/p3 等（`replace_hero_power` 可指向的变体技能若缺脚本 →
  `use_hero_power` 拒绝）。
- 影响：依赖「替换为变体技能」的英雄（如 Galewing/Deadeye/Finley 族）链路
  在变体缺失时不可用；部分变体可能是不可达遗留。
- 最小修复：逐卡判定可达性——可达补脚本，不可达在数据/注册审计标记
  `not_reachable`；audit 工具输出 36 个变体的引用点（`replace_hero_power`/
  `_active_power_id`/异变奖励）。
- 验收：每个变体有「被引用的脚本/效果」或 `not_reachable` 标记，0 未知。

#### G-H3（P2，引擎 API）无公开「技能可用性」查询
- 证据：`use_hero_power` 内联全部判定（`2079-2172`），失败原因不暴露；
  `docs/ENGINE_API.md:928-929` 明确「引擎没有公开的 `can_use_hero_power`；
  这是必须镜像的私有判定之一（READINESS D-3）」；env 已手工镜像
  （`hsbg/env/driver.py`）。
- 影响：候选动作枚举/审计/训练都依赖镜像，规则一变就漂移（与
  `quote_buy_cost` 同类风险，`docs/ENGINE_API.md:777-782`）。
- 最小修复：抽 `Game.hero_power_usable(hero, power_id) -> (bool, reason, cost,
  targets)`（返回原因枚举），`use_hero_power` 复用同一判定；文档/`probe_api.py`
  同步。
- 验收：env 镜像删除，改用引擎 API；同 seed 观测/动作序列不变。

---

### 2.6 三连奖励 / 发现

**实现**
- 三连：`check_for_triple` `game.py:1247-1364`——区域规则（棋盘合成立即奖励/
  手牌合成 `TRIPLE_REWARD_PENDING` 打出时奖励）、buff 合并、监听注销、
  Elemental of Surprise 替代合成、按种族阈值（`TRIPLE_THRESHOLD` /
  `triple_threshold_race`）、Clocksworth 硬币替代（`TRIPLE_REWARD_COINS`）、
  异变「无三连奖励」（`TRIPLE_NO_REWARD`）。
- 奖励：`_grant_triple_reward` `game.py:1378-1401` → `Discover(hero, count=3,
  min_tier=max_tier=reward_tier, kind="triple_reward")`；异变 101/102
  「Discover a minion of your Tier」由 `_triple_reward_of_own_tier` 覆盖
  （`game.py:1381-1397`）。
- 发现：`actions/discover.py:118-207`——选项生成即按池预留（acquire），
  resolve 释放未选项、`create_minion`、`pending_hand_add`、金色发现只占 1 份池
  （`GILDED_NOT_TRIPLED`）；无候选落空；满手排队。
- 数据：`triple_upgrade_id`/`triple_base_id`/`tech_level`（`defs.py:39-41`）。

**测试**：`test_engine_gaps.py:62-160`（手牌/棋盘/奖励 tier+1/buff 保留/
金色打出释放奖励/不足 3 张）；`test_engine_primitives.py:1650-1686`
（金色发现池平衡）、`1064`（种族阈值）、`1833`（双三连/硬币奖励；
`_grant_tavern_coins` `game.py:1366-1376`）；40 处 `triple_reward` 断言/13 文件。
异变相关：`test_batch_anomalies3.py`。

**缺口**

#### G-F1（P1，引擎缺失）通用 Discover 只支持随从
- 证据：`actions/discover.py:186-202` resolve 固定 `create_minion`；无「发现法术/
  卡牌」原语。脚本层已出现 4 个自定义 Action：
  `batch_spells4.py:98` `DiscoverTavernSpellOfTier`、
  `batch_spells_final.py:112` `DiscoverOwnTierLocked`、`163`
  `DiscoverUndeadDiesIfPlayed`、`batch_trinkets19.py:281` `DiscoverTier7Locked`。
- 影响：`docs/ENGINE_API.md:728` 宣称存在 `discover_spell` /
  `discover_tavern_spell` kind，但引擎无统一实现；每张「发现法术/卡」卡要自己
  重写池预留/释放/满手排队/事件，易漏池记账；env 观测也需识别多种自定义 Action
  产生的选择（好在统一走 PendingChoice）。
- 最小修复：`Discover` 增加 `card_type`/`factory` 参数（minion/spell/tavern_spell/
  entity），resolve 统一走 `minion_pool` 或 `spell_pool` 的 acquire/release；
  4 个自定义 Action 迁移；事件 `card_discovered` 携带 golden 语义已有。
- 验收：新增「Discover a Tavern spell」引擎测试（池 -1、选项预留、未选释放、
  满手排队）；4 张卡行为不回归。

#### G-F2（P2，测试/doc）三连奖励无「无候选/池耗尽」测试
- 证据：`_grant_triple_reward` 直接 `run_actions(Discover(...))`（`1398-1401`）；
  `Discover.do` 无候选直接 return（`discover.py:175-176`）→ 奖励静默消失。
- 影响：官方池耗尽时三连奖励发放策略（延后/落空）无证据、无测试；极端局可能
  静默少奖励。
- 最小修复：补池耗尽测试并记录 AMBIGUOUS 口径；若官方有「奖励保留到下次」，
  加 `pending_triple_reward` 队列。
- 验收：池耗尽卷测不崩溃、奖励计数可审计。

---

### 2.7 饰品选择（Trinkets）

**引擎实现**
- 触发：`_begin_recruit_for` `game.py:419-431`——第 6/9 回合（`constants.py:106`），
  每英雄每档一次（`_trinket_offered` 按 `(hero, kind)` 记账），支持提前档
  （`_trinket_early`）、「下个饰品为 Lesser」覆写（`_next_trinket_kind`）。
- 商店：`_offer_trinkets` `game.py:4997-5052`——候选 = `db.trinket_offer_pool()`
  × 未获得 × 档位（`spell_school` 11/12）；`TRINKET_CHOICES=4`（`constants.py:113`）；
  保底：≥1 无关联类型 + ≥1 费 ≤2（`5020-5031`）；入队
  `PendingChoice(kind="trinket_offer")`，选项 = `CardDef ×4 + [None]`（放弃）；
  resolve 内复查金币、扣费、建实体、`trinkets_granted` 去重、`run_on_bind`、
  广播 `trinket_bought`（`5033-5048`）。
- 授予/复制（非商店路径）：`grant_trinket` `4903-4933`、
  `copy_trinket` `4935-4951`、`set_second_slot_trinket`（Crystal Ball 族）`4953-4975`、
  `grant_random_trinket` `4977-4988`、`replace_trinket` `4990-4995`、
  关联卡数据链 `trinket_related_card` `4832-4843`。
- 数据：`trinket` 布尔（生成器 `tools/generate_bg_data.py:486-488`）、
  `spell_school` 档位、`evolution_card_id` 关联卡、`subset_*` 类型关联；
  池过滤 `db.py:108-136`（排除 `BG30_Trinket_*` 内部 token 与升级变体）。

**测试**：109 处 `trinket_offer`/37 文件；`test_engine_primitives.py:1873-1998`
（T6 lesser / T9 greater / 提前 Greater / 放弃 / 异常），`2120`（档位池过滤）；
`test_engine_gaps.py:925-1035`（授予协议/去重/替换/购买事件）、`1035-1127`
（复制/第二槽）；`test_batch_trinkets*.py` 38 个批测文件。

**缺口**

#### G-R1（P0，引擎缺失）商店 offer 池未与 `REGISTRY` 交叉过滤
- 证据：`game.py:5015-5017`（`pool = [d for d in self.db.trinket_offer_pool()
  if d.id not in hero.trinkets_granted and (school is None or ...)]`——**只过滤
  已获得与档位，不看脚本是否注册**）；`game.py:5050-5052`（无脑入队）。
  对照任务 offer 的闸门：`game.py:3912-3917` 注释「任务候选 = quest_offer_pool()
  （全部**已注册**任务卡）」+ `quest_offer_pool` `3826-3843`。
  实测（本审计）：`db.trinket_offer_pool()` 357 张中 **41 张无 `REGISTRY` 脚本**
  （BG36 27 张、BG30 6、BG32 4、BG35 4，完整清单见 §5）。
- 影响：玩家/策略可在 T6/T9 买到无任何效果的饰品——**金币被扣、动作有效、
  收益为零**；RL 动作空间包含 41 个「空动作」且分布不低（41/357 ≈ 11.5%，
  每次 offer 4 张期望命中 ≈0.46 张），直接污染训练数据与 live/sim 差异；
  env 的 `CHOOSE` 动作/奖励也因此偏差。
- 最小修复（引擎一行级）：`_offer_trinkets` 候选池改为
  `[d for d in self.db.trinket_offer_pool() if REGISTRY.get(d.id) is not None and ...]`
  （`REGISTRY` 从 `hsrl2.scripts` 延迟导入，模块内已有先例）；同时在
  `tools/audit_*` 输出缺失清单，防回潮。
- 验收：新增测试断言 `offer kind 的 options ⊂ REGISTRY 键`；构造场景（排除池中
  已注册项）验证仍能给出 4 张；41 张缺失数在 audit 输出可见。

#### G-R2（P1，脚本缺失）41 张可提供饰品无脚本（37.0 数据升级遗留）
- 证据：同 G-R1 实测清单（§5）；`data/bg_summary.json` 409 饰品 / 357 商店可提供；
  当前 `REGISTRY` 覆盖 316/357。参考权威台账
  `docs/agents/TRINKET_LEDGER.md` 与 `batch_trinkets31..39`（36.2 基线收口后
  37.0 新增 27 张 BG36 未跟进）。
- 影响：即使 G-R1 过滤落地，这些饰品在真实对局中「应有」而模拟「不提供」，
  属 live/sim 差异；不过滤则训练被污染——两害相权必须先过滤（G-R1），
  再按 37.0 优先级补脚本。
- 最小修复：按 `TRINKET_LEDGER` 分批实现（优先商店常见/高费）；每卡需
  `on_bind`/事件/`evolution_card_id` 数据链验证；`test_batch_trinkets*` 对应
  批测试 + registry 覆盖仪表（`tools/audit_card_registry_v2.py`）保持同步。
- 验收：offer 池覆盖 357/357；audit 覆盖仪表 trinket 行为分母 = 357。

#### G-R3（P2，引擎/测试）购买金币在挂起期被花掉的结算语义
- 证据：`_offer_trinkets.resolve` 在 resolve 时复查 `hero.gold < d.cost`
  （`5036-5037`）→ 静默「放弃购买」但 **PendingChoice 已消费**；
  与 `_finish_hero_power` 的「作废不扣费」类似，但无审计日志/事件。
- 影响：8 人局挂起窗口内花金（官方 UI 即时购买，理论不可达）——训练中若
  观测/动作异步则可能发生；静默丢弃难排查。
- 最小修复：金币不足时记 `trinket_offer_expired` 事件/审计日志（或按
  `GameStateError` 抛错由 env 转 invalid，二选一需统一口径）；补测试。
- 验收：构造「挂起中花光金币」→ resolve 后无购买、有可观测原因。

---

### 2.8 PendingChoice 横切契约

**契约现状**
- 结构/队列：`game.py:138-171`（`owner/options/kind/resolve_callback`），
  队列 `self.pending_choices`（`208`）；`choose(index)` 校验下标（`149-150`），
  执行回调（`152-153`），发现类广播 `card_discovered`（`154-171`）。
- 文档：`docs/ENGINE_API.md:1089-1200`——§5.2 明确「只结算不出队，不 pop 就
  继续 choose = 同一效果重复施加」；§5.3 options 五种类型；§5.4 kind 清单
  （13 项，注明引擎不维护白名单）。
- env 正确用法：`hsbg/env/driver.py:948-958`（`pop(0)` → `choose`）、
  `1092-1133`（FIFO `resolve_pending_choices`）、`ChoiceQueue` 替身 `1141-1190`。
- 引擎自产 kind：`choose_one`、`battlecry_target`、`spell_target`、
  `hero_power_target`、`dark_gift`、`discover_*`、`triple_reward`、
  `quest_offer`、`trinket_offer`；脚本自定义 kind ≥54 种（审计 grep：
  `*_target`/`*_pick`/`*_choice` 词表去重）。

**缺口**

#### G-P1（P1，引擎缺失）无幂等/无出队保护；resolve 异常后选择丢失
- 证据：`game.py:148-153` 无 `_resolved` 标记、不自动出队；
  docs `1109-1126` 用示例演示双结算；回调抛错路径：env 先 `pop(0)` 再
  `choice.choose()`（`hsbg/env/driver.py:956-958`）→ 若脚本回调抛
  `GameStateError`（多脚本显式抛，如 `discover.py:186-189`、`game.py:2301-2303`、
  `game.py:2407-2408`），选择已出队、效果未完成、队列无法重试。
- 影响：RL 训练中「动作非法 → invalid 捕获」框架（AGENTS §3）依赖异常可控，
  但这里会发生**状态半应用 + 选择丢失**；8 人局多选择并发时难以定位。
- 最小修复：
  1. `PendingChoice` 增加 `resolved: bool`，`choose` 二次调用抛
     `GameStateError("already resolved")`；
  2. 提供 `Game.take_choice(index)` 原子 API（`pop(0)` + `choose`，带 owner/
     队首断言），env 改用它；保留 `choose()` 兼容；
  3. 文档 §5.2 改写为「推荐 `take_choice`」。
- 验收：新增契约测试：双 choose 第二次抛错且效果只结算一次；
  非队首/非本人选择被拒绝；异常路径有明确语义（选择不丢或状态回滚）。

#### G-P2（P2，文档/引擎）kind 无枚举、文档清单与实现漂移
- 证据：docs §5.4 列 13 种（`ENGINE_API.md:1138-1158`），实际引擎自产 13 类 + 脚本
  自定义 ≥54 种；`kind` 是自由字符串（`game.py:141-145`）。
- 影响：env/观测/审计需要字符串匹配维护（`hsbg/env/driver.py:1056` 有
  `kind.startswith("choose_")` 之类的启发式），新 kind 易漏；live 对局侧
  `choice` 处理也按字符串（`docs/LIVE_TO_SIM_GAP.md` L04）。
- 最小修复：提供 `PendingChoiceKind` 常量表（引擎自产部分）+ 文档自动同步
  脚本；脚本自定义 kind 规范前缀（如 `card:<card_id>:<purpose>`）或至少注册表。
- 验收：`grep PendingChoice(` 的字符串全部在常量表或注册表；文档由脚本生成。

#### G-P3（P2，文档）ENGINE_API 行号锚点过期
- 证据：`docs/ENGINE_API.md:319/346/367/404/493/519/542` 等函数签名锚点与当前
  `game.py` 差 30~90 行（如 `use_dark_gift` 文档写 `game.py:2172`，实际 2261；
  `use_activate` 写 1819，实际 1908；`play_minion` 写 1015，实际 1068）；
  §3.4 play_spell（`496-527`）未提「法术 Choose One 分流已实现」（实际
  `game.py:1513-1530`），与 `batch_spells4.py` 等脚本的既有假设不一致。
- 影响：审计/开发按文档定位会找错行；文档与实现漂移削弱「权威参考」价值。
- 最小修复：`tools/probe_api.py` 已有断言 → 增加「文档行号锚点」自动生成/
  校验；补 play_spell Choose One 小节。
- 验收：文档锚点由脚本生成并在 CI 校验。

---

## 3. 卡牌数据字段支撑审计

| 机制 | 应有字段 | 现状（`hsrl2/defs.py` / `data/*.json`） | 结论 |
|---|---|---|---|
| Choose One | 权威 `choose_one`（或标签）+ 双效/目标组合信息 | `choose_one: bool` 存在但由**文本兜底**生成（`generate_bg_data.py:387-389`）；9 误报/3 漏报；无「抉择×目标」字段 | **数据缺失（权威性）** G-C5 |
| Choose One 双效 | 308/实体/光环标记 | 数据无 `choose_both` 字段；引擎靠运行时 `CHOOSE_BOTH` tag/脚本 | 可接受（运行时状态，非卡牌静态） |
| ACTIVATE | `activate` + `activate_cost` | 两者均导出（`generate_bg_data.py:315-320`）；cost=0 按设计省略，引擎 keyword 兜底（`game.py:3750-3758`） | **支撑**（0 费需按关键字读取，勿只看 cost，G-A4） |
| Dark Gift | `dark_gift` + 窗口(`min_turn`/`max_turn`) + 数值参数 + 资格标志 | `dark_gift` 布尔（47/47）；**窗口/数值/资格限制完全缺失**（硬编码 `darkgifts.py:92-140`、`game.py:5186-5622`）；生成器 TAG 无 4853/4854 | **数据缺失** G-D6 |
| 英雄技能 | 英雄→技能映射、费用、类型 | `hero_power_dbf`→`hero_power_id`（`db.py:44-50`）、`cost`、`card_type` 完整 | **支撑** |
| 目标选择 | `needs_target` / `target_domain` / `target_count` | **无任何字段**（`defs.py` 与数据 JSON 均无）；纯脚本约定 | **数据缺失** G-T1 |
| 三连 | `triple_upgrade_id`/`triple_base_id`/`tech_level` | 完整导出（`defs.py:39-41`） | **支撑** |
| 发现 | 池标志 `is_pool_minion`/`is_pool_spell`、`tech_level`、`card_type` | 完整 | **支撑**（引擎 Action 只造随从见 G-F1） |
| 饰品 | `trinket`、档位 `spell_school`、关联卡 `evolution_card_id`、类型 `subset_*` | 完整（`generate_bg_data.py:486-488` 等）；`db.trinket_offer_pool()` 派生 | **支撑**（脚本覆盖是缺口，G-R2） |
| 数值参数 | `script_data_num_1..5` | 完整；但 Dark Gift 实体无参数 | **部分缺失**（gift 数值） |
| PendingChoice | ——（运行时） | 无数据字段需求；kind 自由字符串 | 文档/枚举缺口 G-P2 |

---

## 4. 缺口总表（编号 / 优先级 / 类别 / 证据 / 最小修复 / 验收）

| 编号 | P | 类别 | 缺口 | 关键证据 | 最小修复 | 验收 |
|---|---|---|---|---|---|---|
| **G-R1** | **P0** | 引擎 | 饰品 offer 未过脚本注册闸 | `game.py:5015-5017`；对照 `game.py:3912-3917`/`3826-3843` | offer 池加 `REGISTRY.get(d.id)` 过滤 | 单测：options ⊆ REGISTRY；audit 可见 41 缺失 |
| **G-H1** | **P0** | 脚本 | 17/118 英雄主技能无脚本（含 37.0 新英雄） | `game.py:2110-2115`（拒绝）；`hsbg/env/game_env.py:264-282`（全英雄池） | 先 env 过滤/标注，后按 37.0 顺序补脚本 | 英雄×技能覆盖 118/118 |
| **G-C1** | **P0** | 引擎 | choose_options 与 needs_target 互斥 | `game.py:1126-1135` vs `1137-1154`；`batch_misc.py:52-54/1116-1121/1152-1174` | 目标→抉择两阶段状态机 | 组合单测：先 target 后 choose 都到达 ctx |
| **G-C2** | **P0** | 脚本 | 旧 Choose One 脚本 `both` 静默零效果 | `batch_misc.py:1142-1150/1216-1220`；清单 `batch_choose_one.py:58-64` | 两脚本加 `_both` 分派 | 光环下打 BG27_084/BG30_123 双效生效 |
| **G-C3** | P1 | 引擎 | 法术实体 CHOOSE_BOTH 未读 | `game.py:1517-1518` vs `1123-1125`；`batch_unfreeze.py:370-378` | 加 `spell.has(CHOOSE_BOTH)` | 实体 tag 法术直接双效、无选择窗 |
| **G-C4** | P2 | 脚本 | 5 张池法术用自建选择协议 | `batch_spells4.py:61-69/198/254/370` | 迁移到引擎 choose_options | 5 张卡支持光环双效 |
| **G-C5** | P1 | 数据 | choose_one 文本兜底、误报/漏报 | `generate_bg_data.py:387-389`；两处硬编码 `batch_rally2.py:60-78`/`batch_unfreeze.py:50-63` | 导出权威字段或引擎判定函数统一 | 数据判定 = 标题正则∩非 Spellcraft；漂移测试指向实现 |
| **G-C6** | P2 | 脚本 | 10 base Choose One 卡无脚本（非池） | REGISTRY 缺失清单（§2.1） | 判定可达性：补脚本或标 not_reachable | audit 矩阵 0 未知 |
| **G-C7/G-P1** | P1 | 引擎 | PendingChoice 双结算/异常丢选择 | `game.py:138-171`；`docs/ENGINE_API.md:1109-1126`；env `driver.py:948-958` | `resolved` 标记 + `take_choice` 原子 API | 双 choose 第二次抛错；异常路径测试 |
| **G-A1/G-D1** | P1 | 引擎 | Activate 无「触发两次」钩子（EFFICIENCY） | `game.py:1908-1922`（单次）；`darkgifts.py:77/159-160` | `use_activate` 倍率（仿 `hp_times`） | 激活一次触发两次、扣费一次；EFFICIENCY 出 DEFERRED |
| **G-D2** | P1 | 脚本 | DESECRATION 原语已具备却 DEFERRED | `game.py:1044-1067`（discard 计数）；`darkgifts.py:78/159` | 计数型 gift handler（仿 `5393-5415`） | 弃 N 张 +3N/+3N |
| **G-D3** | P2 | 脚本 | WORSHIP 原语已具备却 DEFERRED | `game.py:4508`（deity stats）、`5156`（SoC 接线） | SoC handler | SoC 后 Deity 属性增加 |
| **G-D4** | P2 | 脚本 | DOPPELGANGER 原语已具备却 DEFERRED | `actions/summon.py:34`、`game.py:5156` | SoC SummonPlainCopy | SoC 召唤自身副本 |
| **G-D5** | P2 | 脚本 | POLARIZATION 备注过时 | `game.py:1437-1461/1463`（磁力已实现）；`darkgifts.py:154-160` | EoT 随机机械 → attach_magnetic | EoT 吸附生效 |
| **G-D6** | P1 | 数据 | Dark Gift 窗口/数值/资格硬编码 | `darkgifts.py:92-140`；`game.py:5186-5622`；生成器 `generate_bg_data.py:99-113` | 导出 4853/4854 与参数；表改读数据 | 窗口=数据一致测试；删常量仍绿 |
| **G-D7** | P2 | 架构 | 脚本复制 trio 配对逻辑 | `batch_hero_combat3.py:177`；`batch_trinkets20.py:140/250-258`；`batch_trinkets22.py:314-321` | 引擎 `offer_dark_gift_discover` API | 4 调用点迁移、旧测绿 |
| **G-D8** | P2 | 测试 | DEFERRED 仅 1/5 有测试 | `test_s14_mechanics.py:570-582` | 参数化 DEFERRED 断言 | 5/5 有审计日志/不崩 |
| **G-A2** | P2 | 引擎 | use_activate 无 TURN_SKIPPED 守卫 | `game.py:1908-1912` vs `1072-1073` | 加同一守卫 | 跳过回合不可 Activate |
| **G-A3** | P2 | 引擎 | Activate 目标协议非引擎级 | `game.py:1908-1922` 无 needs_target；14 处脚本自建 | 同构化或文档化+lint | 带 needs_target 的 Activate 单测 |
| **G-A4** | P2 | 数据/脚本 | Gilding 用 activate_cost 漏判 0 费 | `darkgifts.py:208-209/353-357`；5 张 0 费卡 | 谓词加 keyword 兜底 | 5 张卡不被配 Gilding |
| **G-T1** | P1 | 数据 | 目标元数据不可数据化 | `defs.py:16-79`；99/53 无 target_candidates | 导出 needs_target+domain 或注册表反填+lint | 全部 needs_target 有显式域；audit 0 未知 |
| **G-T2** | P2 | 引擎 | 法术显式 target 不校验 | `game.py:1531-1544`；docs `510-513` | 结算前候选复核（落空语义） | 非法 target 不崩、法术消耗 |
| **G-T3** | P2 | 引擎 | target_count 仅技能 | `game.py:2137-2171` vs `1682-1769`；`batch_trinkets27.py:614/29.py:859` | 抽通用多目标链 | 法术 target_count=2 单测 |
| **G-T4** | P2 | 文档 | 候选函数签名三分裂 | `docs/ENGINE_API.md:855-865`；`game.py:1139/1533/2142/2251` | 文档+基类+audit 校验 | wiring audit 覆盖 |
| **G-F1** | P1 | 引擎 | 通用 Discover 只支持随从 | `actions/discover.py:186-202`；4 个脚本自定义 Action | Discover 支持 spell/entity | 发现酒馆法术引擎测试 |
| **G-F2** | P2 | 测试 | 三连奖励池耗尽无测试/口径 | `game.py:1398-1401`；`discover.py:175-176` | 补测试 + AMBIGUOUS 记录 | 池耗尽不崩、可审计 |
| **G-H2** | P2 | 数据/脚本 | 36 个 power 变体无脚本 | 165-129；`replace_hero_power` 可达性未审 | 逐卡可达性判定 | 0 未知 |
| **G-H3** | P2 | 引擎 API | 无公开技能可用性查询 | `game.py:2079-2172`；docs `928-929` | `hero_power_usable()` | env 镜像删除、行为不变 |
| **G-P2** | P2 | 文档/引擎 | kind 无枚举、清单漂移（13 vs ≥54） | `game.py:141-145`；docs `1138-1158` | Kind 常量表 + 前缀规范 | grep 字符串均在表内 |
| **G-P3** | P2 | 文档 | ENGINE_API 行号锚点过期 / play_spell 抉择未记 | `docs/ENGINE_API.md:496-527/686/519/542` | 锚点自动生成校验 + 补小节 | CI 校验锚点 |

---

## 5. 附录

### 5.1 饰品商店可提供但无脚本的 41 张（G-R1/G-R2 清单，按前缀）

- **BG36（37.0 新增，27）**：BG36_MagicItem_373/400/402/403/404/406/407/408/409/410/
  411/412/414/416/417/418/423/424/430/450/600/602/606/609/610/611/852
- **BG30（6）**：BG30_MagicItem_402 Conductor Portrait、416 Token of the Old Gods、
  431 Azerite Portrait、707 Tickatus Sticker、711 Marine Signet、994 Yogg-Tastic Pastry
- **BG32（4）**：BG32_MagicItem_300 Putricide Sticker、806 Battlecruiser Portrait、
  809 Gem Donation、823 Wax Imprinter
- **BG35（4）**：BG35_MagicItem_812 Corrupted Tome、820 Safety Patch、
  823 Timeworn Candelabra、921 Cowrie Necklace

### 5.2 英雄主技能无脚本的 17 位（G-H1 清单）

`BG20_HERO_202` Master Nguyen / `BG20_HERO_242` Guff Runetotem /
`BG20_HERO_283` Galewing / `BG21_HERO_000` Cariel Roame /
`BG24_HERO_100` Sire Denathrius / `BG25_HERO_100` Professor Putricide /
`BG31_HERO_801` Jim Raynor / `BG31_HERO_811` Kerrigan /
`BG33_HERO_001` Loh / `BG34_HERO_000` Murozond /
`BG34_HERO_004` Morchie / `BG35_HERO_001` Genn /
**`BG36_HERO_000` Drest'agath** / **`BG36_HERO_002` Kith'ix** /
`TB_BaconShop_HERO_21` Akazamzarak / `TB_BaconShop_HERO_90` Silas Darkmoon /
`TB_BaconShop_HERO_94` Tickatus。

### 5.3 关键统计（本审计实测，只读脚本口径）

| 项 | 值 |
|---|---|
| 引擎脚本总数 `REGISTRY` | 1,460 |
| 池内随从 / 法术 / 英雄 / 技能绑定 | 273 / 76 / 118 / 118（主技能全有 hero_power_id） |
| Choose One 标记 def / 标题 def / base id | 44 / 38 / 23 |
| 引擎 `choose_options` 脚本 | 15（14 个标记 def + BG31_893） |
| 池内真实 Choose One 实体 | 7 随从（+7 金色）+ 5 法术 |
| 池内 Activate 随从 | 23（**23/23** 有脚本 + activate 钩子） |
| Dark Gift 定义 / 窗口 / handler / DEFERRED | 47 / 47 / 42 / 5 |
| 英雄技能 def 有脚本 / 英雄主技能有脚本 | 129/165 / 101/118 |
| `needs_target` / `target_candidates` 脚本 | 99 / 46（53 个走默认友方棋盘域） |
| 饰品 def / 商店可提供 / 有脚本（商店可提供） | 409 / 357 / 316（**41 缺失**） |
| 三连/发现/饰品测试引用量 | `triple_reward` 40/13 文件；`discover_minion` 65/21；`trinket_offer` 109/37 |
| PendingChoice 引用量 | `pending_choices` 552/73 文件；脚本自定义 kind ≥54 种 |

### 5.4 审计方法与复现（只读）

```powershell
# 1) 数据/注册表统计（不跑对局）
python -c "from hsrl2.db import CardDB; from hsrl2.scripts import REGISTRY; ..."
# 2) 静态检索（grep/ripgrep）：机制关键字 → file:line
# 3) 测试覆盖：grep 'def test_' / 机制 API 调用点
python -m pytest hsrl2/tests -q   # 本轮未执行（任务要求只读审计；测试基线见文档）
```

局限：缺口优先级按「RL/live 机制有效性」排序，未做真实对局差分验证；
`docs/reference_old/` 为历史权威参考（引擎行为以 `hsrl2` 实测为准）；
部分 AMBIGUOUS 项（Dark Gift 权重/窗口并列规则、靶向目标域、多目标选择顺序）
沿用脚本既有裁定，本审计未重新裁决。

---

## 8. 8h 实施状态（2026-10-23 00:10）

- **G-R1 已修**：`_gate_trinket_picks` 在 offer 采样后按 REGISTRY 确定性替换无脚本项（`hsrl2/game.py`）；测试 `test_engine_choose_target.py`。
- **G-C1 已修**：play_minion/play_spell 两阶段（choose→target→结算）；实卡 Sprightly/Foodie 测试通过。
- **G-C3 已修**：play_spell 读取法术实体 `CHOOSE_BOTH` tag。
- **G-C5 已修**：`hsrl2/scripts/choose_one_authority.py` 统一判定；audit choose_one 36 卡/36 脚本 missing=[]。
- **G-H1 部分**：6 个主技能落地（Drest'agath/Kith'ix/Loh/Guff/Genn/Denathrius）；11 个保持未注册，blocker 见 `docs/ENGINE_SUBSYSTEM_GAPS.md`。
- 最终门禁（card builder 收尾后）：hsrl2/tests 4800 passed/6 skipped；tests 622 passed/2 skipped；verify_all --fast 4/4；smoke 8 局 crashes=0。
