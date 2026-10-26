# AutoTavern × hsrl2 跨引擎一致性审计（WS2 台账）

> **参照**：AutoTavern（刚开源）Python 包 `taverngym 1.0.0`，Rust 引擎 `TavernGym`，
> 客户端 **36.6.3.253932**（server rules 36.6.3，N_ACTIONS=245，`source_hash` 见报告 meta）。
> **被审**：HSBRSIM `hsrl2` 引擎，数据基线 **37.0.0.255130**（`data/bg_summary.json`）。
> 审计日期：2026-10-26。只读审计：未修改 `hsrl2/**`、`hsbg/**`、`data/**`、参照仓库。
> 全部结论由本仓库脚本实测（命令见 §8），产物在 `runs/conformance/`（gitignore）。

## 0. 本次升级最终状态（2026-10-26）

| 项 | 数值/状态 |
|---|---|
| 参照 / 被审版本 | taverngym 1.0.0（36.6.3.253932） / hsrl2 + data 37.0.0.255130 |
| 场景总数 | **58**（战斗 26 + 卡牌 16 + 经济 14 + 流程 2；含 AC-04 白板对照 C26） |
| 修复前（审计初版） | 57 场景：MATCH 52 / **ENGINE_BUG 4（AC-01…AC-04）** / UNSUPPORTED 1 |
| 修复后（当前工作树） | **58 场景：MATCH 55 / CONVENTION_DIFF 2 / ENGINE_BUG 0 / UNSUPPORTED 1** |
| AC 状态 | **AC-01 = CONVENTION_DIFF**（先攻平局约定，证据冲突）；**AC-02 = FIXED**（T1 池份数 16→15）；**AC-03 = FIXED**（升级费 T5/T6→11/11）；**AC-04 = CONVENTION_DIFF**（engine-fixer F-35：参照侧脚本行为异常，**非 hsrl2 bug**；新增 C26 无脚本白板对照 MATCH） |
| 回归命令 | `python3 -m pytest tests/conformance` → **13 passed / 约 3.8s**；`python3 -m tools.ac_conformance.run --seeds 48` → 58 场景约 4.3s（含可选对照）。未安装可选依赖 `taverngym` 时自动 **skip（不是失败）** |
| 最小复现 | `python3 -m tools.ac_conformance.repro`（AC-01…AC-04，约 1s） |
| 数据差异 | 共享卡 3412 / 共享随从 2393（攻/血/tier/种族差异 0）；规则常量 18/18 一致（修复后）；data_diff 0 规则差异 |

> 账本口径：`expected` 是**审计结论快照**（不是“期望引擎正确”），引擎行为变化时
> `pytest tests/conformance` 会失败并提示同步台账。

## 0.1 TL;DR（审计初版结论，已按最终状态标注）

| # | 结论 | 数字/证据 |
|---|------|-----------|
| 1 | **战斗核心与参照高度一致** | 42 个双引擎战斗对照（合成 26 + 卡牌 16）中 **39 个 MATCH 且胜负/伤害精确一致**（含圣盾、嘲讽/潜行、顺劈、剧毒/烈毒、风怒/超级风怒、复生、亡语、伤害上限、平局）；其余 3 项：先攻约定 AC-01（C24）、参照侧脚本异常 AC-04（K15）、参照侧不可构造（C18）。 |
| 2 | **4 条 AC 台账最终裁定**（初版 4 条 ENGINE_BUG） | **AC-01 先攻平局约定 → CONVENTION_DIFF**（AT 等级优先约定 vs 官方 wiki 同数量随机，证据冲突）；**AC-02/AC-03 → 已修复**（engine-fixer F-32/F-33）；**AC-04 BG34_405 → CONVENTION_DIFF**（engine-fixer F-35：400 局逐帧证明复仇/圣盾/嘲讽从未触发 + 无脚本白板对照两侧一致 → 异常在参照侧脚本实现，非 hsrl2 bug）。 |
| 3 | **数据可比性好** | 共享卡 id **3412**/3983；共享随从 **2393** 张：攻/血/酒馆等级/种族 **差异 0**；卡面文本 847 条仅表示差异、37 条待复核；仅 4 张卡缺 `START_OF_COMBAT` 字段（×普通/金色=8）。 |
| 4 | **场景规模** | 58 个场景：**MATCH 55 / CONVENTION_DIFF 2 / ENGINE_BUG 0 / UNSUPPORTED 1 / DATA_GAP 0**（最终状态），覆盖任务书机制清单的全部条目（幽灵等少数条目在 §6 标注不可比原因）。 |
| 5 | **处置结论** | **最终无 ENGINE_BUG**：AC-02/03 已修复；AC-01/AC-04 均为 CONVENTION_DIFF（前者证据冲突、后者参照侧脚本异常），hsrl2 无需改动。若需与参照逐位对齐，可另行评估先攻等级判定；AC-04 可继续在 AutoTavern Rust 侧裁定。 |

## 1. 版本、参照与可比性

| 项 | AutoTavern（参照） | HSBRSIM（被审） |
|---|---|---|
| 引擎/包 | taverngym 1.0.0（Rust `crates/taverngym` + PyO3） | `hsrl2/`（vendored Python 引擎） |
| 客户端版本 | **36.6.3.253932**（server rules 36.6.3） | 数据 **37.0.0.255130** |
| 卡表 | `crates/taverngym/data/cards.json`（3983 卡） | `data/bg_cards.json`（3534 卡）+ `bg_pool_minions.json`（273 池随从） |
| 动作空间 | N_ACTIONS=245 | `hsbg/env/spec.py` 侧契约（本审计不涉及） |
| 测试基线 | `cargo test` mechanics.rs 14k 行 + python 46 passed | `pytest hsrl2/tests` 4816 passed/6 skipped（Lead 提供） |

**可比性口径**：两版本相差一个小版本（36.6.3 → 37.0.0）。为避免把“版本改动”误判为
“引擎 bug”：

1. 机制级场景用**合成白板随从**（不依赖卡牌脚本/数值），两引擎构造同一组攻/血/
   关键词/tier；
2. 卡牌级场景只用**两版本共享且卡面数据一致**的卡（`data_diff` 逐卡校验攻/血/
   tier/种族/关键词；见 §2.2），共 16 个卡牌场景；
3. 36.6.3→37.0.0 新增/改动的卡（只 AT 571 张 / 只 HS 122 张、37 张文本待复核）**不**
   纳入卡牌级对照，只登记为版本数据差异。

> ⚠️ 参照性质：AutoTavern 是**第三方**从客户端数据重建的引擎（其 `docs/ARCHITECTURE.md`
> 明确“cross-source order is a simulator convention”），不是官方服务端。因此
> “与 AutoTavern 不一致”是**疑点/证据等级 E2**，修复前需 Lead/engine-analyst 复核；
> 但 AC-01/02/03 另有官方 wiki（2026-10-26 抓取）交叉证据，等级可到 E3。

## 2. 数据差异（36.6.3 vs 37.0.0）

复现：`python3 -m tools.ac_conformance.data_diff`（产物 `runs/conformance/data_diff.json`）。

### 2.1 id 层

| 指标 | 数值 |
|---|---|
| AutoTavern 卡数 | 3983 |
| HSBRSIM 卡数 | 3534 |
| 共享 id | **3412** |
| 仅 AutoTavern | 571（36.6.3 有、37.0 删除/替换：历史池卡/token 为主） |
| 仅 HSBRSIM | 122（37.0 新卡为主） |

### 2.2 随从层（共享 2393 张）

| 维度 | 差异数 | 说明 |
|---|---|---|
| 攻/血 | **0** | 两版本数值完全一致（可比性强） |
| 酒馆等级 | **0** | 一致 |
| 种族 | **0** | 一致（AT `races` ∪ HS `card_race`+`race_tags` 语义对齐后） |
| 关键词 | **8** | 4 张 × 普通/金色 的 `START_OF_COMBAT` 字段缺口：BG26_963 / BG27_556 / BG34_Giant_042；另 2 条为测试卡（BGMinionAbilityTest*）ACTIVATE 标记差异 |
| 卡面文本 | **37** 条待复核 + **847** 条仅表示差异 | HS 数据含 `_`/`@`/`{n}` 换行与动态参数占位、AT 已代入具体数值；规范化后 847 条等价，37 条需人工复核（多为动态进度文本的两段式表示） |

**文本差异样例**（37 条待复核中的代表）：BG21_018 Defiant Shipwright（`+1` vs `+{1}`）、
BG26_176 The Boogie Monster（Tier 1 vs Tier `{0}`）、BG26_199 Upbeat Duo（进度文本）。
这些不影响战斗数值，但影响“文本→效果”自动审计，登记为观察项。

### 2.3 关键词字段缺口（DATA_GAP 风险）

HSBRSIM `data/bg_cards.json` 的字段集缺少 AutoTavern 卡表里存在的部分关键词标记：

* `START_OF_COMBAT` 布尔字段缺 4 张共享卡（上表；非池卡为主）；
* `data/bg_cards.json` **完全没有** `stealth` / `cleave` / `mega_windfury` /
  `end_of_turn` 字段（`hsrl2/defs.py::CardDef.from_json` 支持这些键，但数据导出未带）；
  AT 的 stealth 卡均为**非池卡**（21 张全部 `pools=[]`），因此当前池内玩法不受影响，
  但“从卡表自动识别关键词”的离线审计/日志回放会漏判。

建议：数据生成器补齐 `stealth/cleave/mega_windfury/end_of_turn` 四字段（只读登记，
不属于本 WS 的写范围）。

### 2.4 池层

| 指标 | AutoTavern | HSBRSIM |
|---|---|---|
| 池内随从 | 245 | 273 |
| 共享池随从 | **240** | — |
| 仅 AT 池 | 5 | — |
| 仅 HS 池 | — | 33 |
| 共享池内卡属性/关键词差异 | 2（= 2.2 的 4 张 SoC 卡） | — |

### 2.5 规则常量（`RulesConfig` vs `hsrl2.constants`）

| 字段 | AutoTavern 36.6.3 | HSBRSIM 37.0.0 | 判定 |
|---|---|---|---|
| start_gold / buy / sell / refresh | 3 / 3 / 1 / 1 | 3 / 3 / 1 / 1 | MATCH |
| gold_increment / cap | +1 / 10 | +1 / 10 | MATCH |
| shop_minion_slots (T1..T6) | 3/4/4/5/5/6 | 3/4/4/5/5/6 | MATCH |
| shop_spell_slots | 1 | 1 | MATCH |
| spell_copies_by_tier | 5/7/9/11/9/7 | 5/7/9/11/9/7 | MATCH |
| triple_copies / board / hand | 3 / 7 / 10 | 3 / 7 / 10 | MATCH |
| damage_caps / until_alive | (1→5, 4→10, 8→15) / 4 | 同 | MATCH |
| **pool_copies_by_tier** | **[15,15,13,11,9,7,5]** | **[16,15,13,11,9,7,5]** | **AC-02 ENGINE_BUG** |
| **upgrade_costs (T2..T6)** | **[5,7,8,11,11]** | **[5,7,8,9,10]** | **AC-03 ENGINE_BUG** |
| upgrade_discount_per_turn | 1 | 1 | MATCH |

## 3. 审计方法与判定口径

### 3.1 等价局面构造

| 侧 | 构造方式 |
|---|---|
| AutoTavern | `taverngym.Game(seed, config_json)`；8 座位英雄选择后统一 pin **Patchwerk**（`TB_BaconShop_HERO_34`，唯一效果=开局 +30 血，纯被动），清空棋盘/手牌；`debug(set_turn/set_player/add_minion/edit_minion/refresh_shop/combat_preview)` 编辑局面。合成随从=白板宿主卡 + `edit_minion(atk,hp,keywords)` 覆写；宿主卡 tier 进入伤害公式，故与 hsrl2 dummy 的 `tech_level` 对齐（T1/T2/T3/T5 四档白板）。 |
| hsrl2 | `Game(heroes, db, seed)`（2 英雄、无英雄技能）；`Minion(...)` 合成随从设 `controller/zone` 直接上棋盘（与 `hsrl2/tests` 的 `dummy()` 同款）；`hero.set(GameTag.TAVERN_TIER)` 设酒馆等级；`game.turn` 设回合；`run_combat(alive_count=)` 跑战斗。 |
| 卡牌场景 | 两侧都用**同一 card_id** 真实创建（AT `add_minion`；HS `create_minion+summon`），不覆写属性（数据差异由 §2 挡住）。 |

**污染控制**（AutoTavern 侧实测）：pin 后玩家 `stats` 全 0、`effects/quests/trinkets`
为空、只有 Patchwerk 被动；两侧血量都置 100、护甲 0，伤害按“扣血差值”观察。

### 3.2 观察指标

* 胜负分布（a 胜 / b 胜 / 平）与**应用伤害上限后的实际扣血**（伤害公式两侧一致：
  胜方酒馆等级 + 存活随从 tier 之和）；
* 首攻方（AT：replay frames 第一条 attack 日志；HS：`CombatResult.attacker_first`）；
* 死亡顺序/数量（HS `combat_death_log`；AT frames 的 dies 日志）用于人工复核；
* 每个分布场景两引擎各 **48 个独立 trial/seed**（固定 seed 0..47 / AT trial i 的
  派生 RNG），拒绝把单样本当证据。

### 3.3 判定规则（`tools/ac_conformance/compare.py`）

| 情形 | 判定 |
|---|---|
| 两侧都只有一个结果类别（确定性） | 要求胜负**且**伤害值集合完全相同 → `exact_match`；否则 mismatch |
| 两侧都可能多结果 | 胜负分布逐类差 ≤0.25 **且** 伤害均值差 ≤1.5 → `dist_match`；否则 mismatch |
| 首攻方 | 两侧都随机 → MATCH（约定）；一侧确定另一侧随机/不同 → mismatch |
| mismatch 且无“约定解释” | → **ENGINE_BUG**（候选）；若为参照侧脚本/实现异常（有控制实验证据）→ **CONVENTION_DIFF**（AC-04 情形） |
| 参照侧 API 无法构造等价局面 | → **UNSUPPORTED**（不硬凑） |
| 卡缺失/卡面数据不一致 | → **DATA_GAP** |

### 3.4 明确容忍的约定差异（不算 bug）

* RNG 流不同（AT xoshiro256** / HS `GameRNG`）与**随机目标/随机平局选择**的具体
  取值（只比较语义不变量与分布）；
* 事件日志文字/顺序、内部实体 id、replay 帧格式；
* 安全上限（AT `max_combat_attacks=400` vs HS 2000/20000）导致的截断保护；
* 整局流程场景中两引擎的 bot 策略不同（只比较规则不变量，不比较名次分布）。

## 4. 场景矩阵（58 个）

> 数据来自 `runs/conformance/report.json`（`python3 -m tools.ac_conformance.run`，
> seeds=48，耗时约 3s）。每个场景的完整两侧输出见报告 `rows[].detail`。

| ID | 场景 | 结果 | 证据摘要 |
|---|---|---|---|
| C01 | 圣盾吸收一次攻击（2/2 DS vs 1/1） | **MATCH** | 胜率 T=1.00/0.00/0.00 H=1.00/0.00/0.00；伤害值 T=[2] H=[2] |
| C02 | 圣盾+嘲讽 vs 大身材（吸收后被击穿） | **MATCH** | 胜率 T=0.00/1.00/0.00 H=0.00/1.00/0.00 |
| C03 | 嘲讽优先于普通随从 | **MATCH** | 胜率 T=0.00/1.00/0.00 H=0.00/1.00/0.00 |
| C04 | 潜行随从不可被选中 | **MATCH** | 胜率 T=0.00/1.00/0.00 H=0.00/1.00/0.00 |
| C05 | 顺劈同时命中相邻随从 | **MATCH** | 胜率 T=0.00/0.00/1.00 H=0.00/0.00/1.00 |
| C06 | 剧毒同归于尽（平局） | **MATCH** | 胜率 T=0.00/0.00/1.00 H=0.00/0.00/1.00 |
| C07 | 烈毒同归于尽（平局） | **MATCH** | 胜率 T=0.00/0.00/1.00 H=0.00/0.00/1.00 |
| C08 | 剧毒 vs 圣盾（圣盾免疫毒杀） | **MATCH** | 胜率 T=0.00/1.00/0.00 H=0.00/1.00/0.00 |
| C09 | 风怒镜像（同归于尽） | **MATCH** | 胜率 T=0.00/0.00/1.00 H=0.00/0.00/1.00 |
| C10 | 超级风怒连续 4 次攻击 | **MATCH** | 胜率 T=1.00/0.00/0.00 H=1.00/0.00/0.00；伤害值 T=[2] H=[2] |
| C11 | 复生随从战后以 1 血重立 | **MATCH** | 胜率 T=0.00/0.00/1.00 H=0.00/0.00/1.00 |
| C12 | 全员 0 攻 —— 平局且无伤害 | **MATCH** | 胜率 T=0.00/0.00/1.00 H=0.00/0.00/1.00 |
| C13 | 0 攻 vs 1 攻（0 攻方被白吃） | **MATCH** | 胜率 T=0.00/1.00/0.00 H=0.00/1.00/0.00 |
| C14 | 嘲讽+潜行混合（嘲讽仍强制） | **MATCH** | 胜率 T=0.00/1.00/0.00 H=0.00/1.00/0.00 |
| C15 | turn1 伤害上限 5（原始 6） | **MATCH** | 胜率 T=1.00/0.00/0.00 H=1.00/0.00/0.00；伤害值 T=[5] H=[5] |
| C16 | turn4 伤害上限 10（原始 11） | **MATCH** | 胜率 T=1.00/0.00/0.00 H=1.00/0.00/0.00；伤害值 T=[10] H=[10] |
| C17 | turn8 伤害上限 15（原始 26） | **MATCH** | 胜率 T=1.00/0.00/0.00 H=1.00/0.00/0.00；伤害值 T=[15] H=[15] |
| C18 | 存活≤4 解除伤害上限（原始 21 全额） | **UNSUPPORTED** | 胜率 T=1.00/0.00/0.00 H=1.00/0.00/0.00；伤害值 T=[15] H=[21]；AutoTavern Python API 无法把 8 人局改成 4 人存活：combat_preview 的伤害上限按真实 lobby 存活人数计算（仍为 8），不能注入 alive=4；hsrl2 侧 alive_c |
| C19 | token tier 计入伤害（tier3 token） | **MATCH** | 胜率 T=1.00/0.00/0.00 H=1.00/0.00/0.00；伤害值 T=[4] H=[4] |
| C20 | 酒馆等级计入伤害（胜方 tier4） | **MATCH** | 胜率 T=1.00/0.00/0.00 H=1.00/0.00/0.00；伤害值 T=[5] H=[5] |
| C21 | 顺劈+嘲讽（顺劈波及后排） | **MATCH** | 胜率 T=0.00/1.00/0.00 H=0.00/1.00/0.00 |
| C22 | 复生+圣盾（复生体恢复圣盾，F-14 回归） | **MATCH** | 胜率 T=0.00/1.00/0.00 H=0.00/1.00/0.00 |
| C23 | 先攻：随从多的一方先攻 | **MATCH** | 胜率 T=0.00/0.00/1.00 H=0.00/0.00/1.00；首攻 T=['a', 'a', 'a', 'a', 'a', 'a'] H={'a': 48, 'b': 0} |
| C24 | 先攻：数量相同 → 参照按酒馆等级高者先攻 [AC-01→CONVENTION_DIFF] | **CONVENTION_DIFF** | 胜率 T=0.00/0.00/1.00 H=0.00/0.00/1.00；首攻 T=['b', 'b', 'b', 'b', 'b', 'b'] H={'a': 25, 'b': 23}；AutoTavern 采用等级优先约定（combat.rs:316）；官方 wiki 现行文本为「同数量随机」；无决定性证据，HSBRSIM 保持随机（ |
| C25 | 先攻：数量/等级都相同 → 随机（约定差异容忍） | **MATCH** | 胜率 T=0.00/0.00/1.00 H=0.00/0.00/1.00；首攻 T=['b', 'a', 'b', 'a', 'b', 'b'] H={'a': 25, 'b': 23} |
| C26 | 对照：同属性无脚本白板（5/4 tier3 + 3×1/3 vs 3×2/2） | **MATCH** | 胜率 T=1.00/0.00/0.00 H=1.00/0.00/0.00；伤害值 T=[3, 4, 5, 6] H=[3, 4, 5, 6] |

| ID | 场景 | 结果 | 证据摘要 |
|---|---|---|---|
| K01 | BG28_300 Harmless Bonehead 亡语召唤 2 只 1/1 | **MATCH** | 胜率 T=1.00/0.00/0.00 H=1.00/0.00/0.00；伤害值 T=[2] H=[2] |
| K02 | BG25_354 Titus 使亡语额外触发（Bonehead 召唤 4 只） | **MATCH** | 胜率 T=1.00/0.00/0.00 H=1.00/0.00/0.00；伤害值 T=[5] H=[5] |
| K03 | BG29_611 Cord Puller 圣盾+亡语召唤 1/1 | **MATCH** | 胜率 T=1.00/0.00/0.00 H=1.00/0.00/0.00；伤害值 T=[2] H=[2] |
| K04 | BG25_010 Handless Forsaken 亡语召唤复生 Hand | **MATCH** | 胜率 T=1.00/0.00/0.00 H=1.00/0.00/0.00；伤害值 T=[4] H=[4] |
| K05 | BGS_034 青铜守卫 (DS+Reborn) vs BGS_119 爆裂飓风 (DS+Windfury) | **MATCH** | 胜率 T=1.00/0.00/0.00 H=1.00/0.00/0.00；伤害值 T=[3] H=[3] |
| K06 | BGS_131 Deadly Spore 烈毒 vs 9/9 | **MATCH** | 胜率 T=1.00/0.00/0.00 H=1.00/0.00/0.00；伤害值 T=[4] H=[4] |
| K07 | BG23_318 Leeroy 亡语灭杀击杀者 | **MATCH** | 胜率 T=1.00/0.00/0.00 H=1.00/0.00/0.00；伤害值 T=[5] H=[5] |
| K08 | BG36_620 Boom-in-a-Box 战斗开始 AoE 3 | **MATCH** | 胜率 T=1.00/0.00/0.00 H=1.00/0.00/0.00；伤害值 T=[5] H=[5] |
| K09 | BG31_803 Buzzing Vermin 嘲讽+亡语召唤甲虫 | **MATCH** | 胜率 T=1.00/0.00/0.00 H=1.00/0.00/0.00；伤害值 T=[2] H=[2] |
| K10 | BG24_500 Amber Guardian 战斗开始给龙圣盾+2/+2 | **MATCH** | 胜率 T=1.00/0.00/0.00 H=1.00/0.00/0.00；伤害值 T=[3] H=[3] |
| K11 | BG25_022 Scarlet Skull 复生+亡语给亡灵+1/+2 | **MATCH** | 胜率 T=1.00/0.00/0.00 H=1.00/0.00/0.00；伤害值 T=[3] H=[3] |
| K12 | BGS_040 Nadina 亡语给 3 条友方龙圣盾 | **MATCH** | 胜率 T=1.00/0.00/0.00 H=1.00/0.00/0.00；伤害值 T=[3, 5] H=[3, 5] |
| K13 | BG25_013 Rot Hide Gnoll 本场死亡计数动态攻击 | **MATCH** | 胜率 T=1.00/0.00/0.00 H=1.00/0.00/0.00；伤害值 T=[2] H=[2] |
| K14 | BG25_016 Sin'dorei Straight Shot 圣盾风怒 Rally 移除关键词 | **MATCH** | 胜率 T=1.00/0.00/0.00 H=1.00/0.00/0.00；伤害值 T=[5] H=[5] |
| K15 | BG34_405 Relentless Deflector 复仇(3)重获圣盾 | **CONVENTION_DIFF** | 胜率 T=1.00/0.00/0.00 H=1.00/0.00/0.00；伤害值 T=[2, 3, 5] H=[3, 4, 5]；AC-04（参照侧脚本行为异常，非 hsrl2 分歧）：同胜负下胜方可达伤害集合不同（AT {2,3,5} vs HS {3,4,5}）。engine-fixer F-35 证据：405 的 Avenge/圣盾 |
| K16 | 亡语连锁死亡结算顺序（Bonehead + Cord Puller 同场） | **MATCH** | 胜率 T=1.00/0.00/0.00 H=1.00/0.00/0.00；伤害值 T=[2, 3] H=[2, 3] |

| ID | 场景 | 结果 | 证据摘要 |
|---|---|---|---|
| E01 | 起始金币 3 | **MATCH** | 一致 |
| E02 | 金币收入曲线 3/4/5/6/7（上限 10） | **MATCH** | 一致 |
| E03 | 购买随从费用与行为扣费 | **MATCH** | 一致 |
| E04 | 出售随从返还 1 金 | **MATCH** | 一致 |
| E05 | 刷新费用 1 金 | **MATCH** | 一致 |
| E06 | 各酒馆等级随从槽位 3/4/4/5/5/6 | **MATCH** | 一致 |
| E07 | 酒馆法术槽位 1 | **MATCH** | 一致 |
| E08 | 基础升级费阶梯 T2..T6 = 5/7/8/11/11 [AC-03 已修复] | **MATCH** | 一致 |
| E09 | 每回合升级费衰减 1 | **MATCH** | 一致 |
| E10 | 各等级随从池份数 15/15/13/11/9/7/5 [AC-02 已修复] | **MATCH** | 一致 |
| E11 | 各等级酒馆法术池份数 5/7/9/11/9/7 | **MATCH** | 一致 |
| E12 | 棋盘/手牌上限 7/10 | **MATCH** | 一致 |
| E13 | 三连所需份数 3 | **MATCH** | 一致 |
| E14 | 伤害上限阶梯 (1,5)/(4,10)/(8,15) 与解除阈值 | **MATCH** | 一致 |

| ID | 场景 | 结果 | 证据摘要 |
|---|---|---|---|
| F01 | AutoTavern 整局 bot 对局：名次唯一/无崩溃/结束 | **MATCH** | 整局不变量 |
| F02 | hsrl2 整局随机对局：50 回合内结束/无崩溃 | **MATCH** | 整局不变量 |

### 4.1 机制清单覆盖对照（任务要求 → 场景）

| 机制 | 覆盖场景 | 结果 |
|---|---|---|
| 先手规则 | C23（数量多者先）、C24（**AC-01→CONVENTION_DIFF** 同数比等级约定）、C25（同数同级随机） | C23/C25 MATCH；C24 CONVENTION_DIFF |
| 嘲讽/潜行目标选择 | C02、C03、C04、C14、C21、K09 | 全 MATCH |
| 圣盾多次吸收 | C01、C02、C08、C22（复生恢复圣盾）、K03、K05 | 全 MATCH |
| 顺劈 | C05、C21 | MATCH |
| 剧毒/烈毒 | C06、C07、C08、K06 | 全 MATCH |
| 风怒/超级风怒 | C09、C10、K05、K14 | 全 MATCH |
| 复生 | C11、C22、K04、K05、K11 | 全 MATCH |
| 亡语与死亡结算顺序 | K01、K02（Titus 双触发）、K03、K04、K11、K12、K16 | 全 MATCH |
| 复仇（Avenge） | **K15（AC-04）**、C26（无脚本白板对照） | K15 = **CONVENTION_DIFF**（参照侧脚本异常，F-35）；C26 对照 MATCH |
| 战斗伤害上限 5/10/15 | C15、C16、C17、C18（解除上限，**UNSUPPORTED**）、E14 | 5/10/15 全 MATCH；解除上限参照侧不可构造 |
| 平局 | C06、C07、C09、C12、C14 | 全 MATCH |
| 幽灵 | 见 §6（两引擎均实现，但参照 Python API 无法构造等价“幽灵战”并比较 → 未纳入） | — |
| 金币与升级费用 | E01、E02、E03、E08（**AC-03 已修复**）、E09 | 全 MATCH（修复后） |
| 刷新/冻结 | E05（刷新费）；冻结行为见 §6 未覆盖说明 | 费用 MATCH |
| 购买/卖出 | E03、E04 | MATCH |
| 三连与池子份数 | E10（**AC-02 已修复**）、E13 | 全 MATCH（修复后） |
| 回合开始/结束 | E02、E09、F02（整局回合推进） | MATCH |
| 配对与淘汰/名次 | F01（AT 整局 bot 名次不变量）、F02（HS 整局不变量） | 不变量 MATCH（bot 策略不同→不比较名次分布） |

## 5. AC 台账（AC-01…AC-04，含最终裁定）

> 每条可用 `python3 -m tools.ac_conformance.repro AC-0x` 复现；固定输入/两引擎输出
> 见脚本输出。**最终裁定（2026-10-26，Lead 确认 + engine-fixer F-35）**：
> AC-01 = CONVENTION_DIFF（证据冲突）；AC-02/AC-03 = FIXED；AC-04 = CONVENTION_DIFF
> （参照侧脚本行为异常，非 hsrl2 分歧，引擎不改）。

### AC-01（已改判 **CONVENTION_DIFF**）先攻平局：参照按酒馆等级、HSBRSIM 随机

* **现象**：双方随从数量相同时，AutoTavern 按**酒馆等级高者先攻**；hsrl2
  `hsrl2/combat.py::CombatScheduler._determine_first` 平局直接随机。
* **最小复现**：A 1×2/2（tier1） vs B 1×2/2（tier5），第 1 回合。
  * AutoTavern：6/6 个 seed 均为 **b（tier5）先攻**（deterministic）；
  * hsrl2：64 seeds 中 a 先攻 34 / b 先攻 30（随机）。
* **证据冲突（为何不判 bug）**：
  * 支持“等级优先”：AutoTavern `combat.rs:316` 实现与注释（客户端 36.6.3 重建，
    且 `tests/mechanics.rs:4578 n1_higher_tier_attacks_first_on_equal_boards` 有
    专门测试）；中文二手攻略（gamedog 2020-09-12）亦写“随从一样多则酒馆等级高者先”；
  * 支持“随机”：**官方 wiki.gg `/wiki/Battlegrounds` 现行文本**（2026-10-26 抓取）：
    “If the number of minions is equal for both players, one of the players is
    randomly selected to attack first.”；HSBRSIM 旧规则文档写随机；
  * **二源冲突 + 参照实现单方，不能判 hsrl2 bug** → Lead 裁定
    **CONVENTION_DIFF**（At 采用等级优先约定；HSBRSIM 保持现状）。
* **影响**：若训练/评估要与 AutoTavern（或共享其语料的 BB 分布）逐位对齐，先手
  约定会改变同数量对局的胜负分布；对“官方等价”无决定性影响。
* **建议**：不改引擎。若后续需要与参照逐位对齐，可在 `_determine_first` 平局分支
  比较 `hero.tavern_tier`，仍相同才随机（可选开关，需 Lead 决策）。
* **决定性证据获取路径**（本批未找到）：
  1. HSBRSIM 真实 `Power.log`/HDT 语料（`docs/DIFF_HARNESS.md` 记录的 679 场
     BobsBuddy 轨迹、`runs/official_traces*/`；原始日志未入库）中筛出
     “同随从数、不同酒馆等级且先手可从事件流判定”的战斗样本；
  2. 客户端战斗中 game entity 的 `BACON_...` 先手 tag / HDT BobsBuddy 首攻字段；
  3. 拿到样本后只需重跑 C24（`python3 -m tools.ac_conformance.repro AC-01`）对比。

### AC-02（**FIXED**，2026-10-26 engine-fixer）T1 随从池份数 16 → 15

* **现象**：`hsrl2/constants.py POOL_COPIES_BY_TIER = {1:16, 2:15, 3:13, ...}`；
  AutoTavern（36.6.3 客户端/wik.gg 数据）为 **15/15/13/11/9/7/5**。
* **最小复现**：`python3 -m tools.ac_conformance.repro AC-02`（打印两侧常量）。
  行为级不可直接读池（调试 API 不暴露副本数），但常量决定抽取权重/三连概率。
* **判定依据**：AutoTavern `config.rs:245`（注释 “15/15/13/11/9/7/5, wiki.gg data
  as of 36.6.0”）；hearthstone.wiki.gg `/wiki/Battlegrounds` 副本表 T1=15
  （2026-10-26 抓取）；HSBRSIM 旧文档 `reference_old/BATTLEGROUNDS_RULES.md`
  写“截至 Patch 35.x T1=16”——已过时。
* **影响**：T1 每卡多 1 份 → 早期三连/刷新概率系统性偏差，池总量 +37 张
  （37 张 T1 卡），影响训练分布与残局守恒。
* **修复状态**：**已修复**（`hsrl2/constants.py POOL_COPIES_BY_TIER[1]=15`，
  2026-10-26 engine-fixer）；E10 复跑由 ENGINE_BUG → **MATCH**。
* **回归**：`pytest hsrl2/tests`（池相关用例）与 `tools/final_engine_stress.py`。

### AC-03（**FIXED**，2026-10-26 engine-fixer）升级费 T5/T6 应为 11/11

* **现象**：hsrl2 `BASE_UPGRADE_COSTS = {2:5,3:7,4:8,5:9,6:10,7:11}》；
  参照为 `[5,7,8,11,11,10]`（目标 T2..T7）。
* **最小复现**：`python3 -m tools.ac_conformance.repro AC-03`：两侧都真实执行
  “升到 T5/T6”的动作并打印扣费：AutoTavern T5 扣 11、T6 扣 11；hsrl2 T5 扣 9、
  T6 扣 10（行为级可观测，非仅常量）。
* **判定依据**：AutoTavern `config.rs:237`；hearthstone.wiki.gg `/wiki/Battlegrounds`
  升级费表（T5=11、T6=11，2026-10-26 抓取）。
* **影响**：中后期节奏与“能否提前上本”决策；影响 RL 策略与 BC 数据分布。
* **修复状态**：**已修复**（`BASE_UPGRADE_COSTS={2:5,3:7,4:8,5:11,6:11,7:10}`，
  2026-10-26 engine-fixer）；E08 复跑由 ENGINE_BUG → **MATCH**。`repro AC-03`
  现在两侧输出一致（修复前后对照见提交 diff）。

### AC-04（**CONVENTION_DIFF**，参照侧脚本行为异常 / engine-fixer F-35）BG34_405 Relentless Deflector

* **现象**：A=[BG34_405, 1/3×3] vs B=[2/2×3]（turn8 避开上限），两引擎 A 都 400/400
  全胜，但胜方可达伤害值集合不同：
  * AutoTavern：{2:76, 3:172, 5:152}（无 4/6）
  * hsrl2：{3:73, 4:100, 5:69, 6:158}（无 2）
* **最小复现**：`python3 -m tools.ac_conformance.repro AC-04`（400 trial/引擎，含
  `control_vanilla` 白板对照段）；场景矩阵 K15（带卡）+ C26（同属性无脚本白板）。
* **证据链（F-35，决定性）**：
  1. **排除“复仇/动态嘲讽时序”假设**：400 局逐帧扫描 AutoTavern 侧 405
     `shield_hits` 恒 0、无 DIVINE_SHIELD/TAUNT 关键词帧；hsrl2 侧 405
     `keyword_gained` 得圣盾 **0 次** → 双方复仇条件（3 友方死亡且 405 存活）
     从未满足，卡面效果根本没有触发。
  2. **控制实验**：把 BG34_405 换成同属性**无脚本白板**（5/4 tier3 + 3×1/3 vs
     3×2/2）→ 两引擎伤害集合都回到 **{3,4,5,6}**（本套件 C26 = MATCH 复验）；
     hsrl2 带卡/不带卡一致，**只有 AutoTavern 带脚本 405 时变成 {2,3,5}**
     （AutoTavern 白板 {3,4,5,6}）。
  3. **结论**：分歧来自**参照引擎侧“带脚本 405”的行为**（观测帧里 flags 未生效
     却改变分布）——属 AutoTavern 脚本/实现候选问题，**hsrl2 与无脚本白板一致**，
     非 hsrl2 卡脚本 bug。按 Lead 裁定登记 **CONVENTION_DIFF**（参照侧实现差异），
     **不改 hsrl2**。
* **影响**：仅影响以 AutoTavern 为参照的 BG34_405 相关战斗对照；hsrl2 训练/评测
  无需改动。若后续用 AutoTavern 做该卡的分布对拍，需先修参照侧。
* **后续裁定路径**（本批未做，非阻塞）：在 AutoTavern Rust 侧用调试命令逐帧对比
  405 与无脚本白板的 `has_taunt`/圣盾内部状态；或补真实 Power.log 的该卡战斗。
  证据等级：E2（参照实现侧），不影响 hsrl2 结论。

## 6. 不可比 / UNSUPPORTED / 未覆盖（如实登记）

| 项 | 状态 | 原因/后续 |
|---|---|---|
| 存活≤4 解除伤害上限（C18） | **UNSUPPORTED** | AT Python API 的 `combat_preview` 伤害上限按真实 8 人 lobby 存活数计算，无法注入 `alive=4`；hsrl2 侧可观察到 21 全额伤害。规则常量本身两侧一致（E14）。后续可用 AT 的 Rust 测试直接构造 4 人局补齐。 |
| 幽灵战（ghost） | 未覆盖 | 两引擎均实现幽灵/亡者战团（AT `ghost_b`/`ghost_player`，HS `end_recruit_phase` 幽灵路径），但“等价幽灵局面”的构造需要先淘汰玩家（AT Python 侧无直接入口），本批时间为 2-3h 未硬凑；建议后续用 AT Rust 测试 + HS 3 人局补齐。 |
| 冻结行为 | 未做跨引擎行为对照 | 仅比较刷新费用（E05）。冻结保留/清除一轮的语义两侧文档一致，但未构造同局面观察（调试 refresh 与真实回合开始刷新路径不同）。 |
| 三连行为 | 仅常量 | E13 比较“需 3 份”；真实三连合并/金色化/发现奖励未做跨引擎对照（需要买 3 张同卡，受随机酒馆限制）。 |
| 英雄技能/饰品/任务/Dark Gift/异变/Deity/Timewarp | 未覆盖 | 两版本子系统差异大（37.0 新增 ABERRATION/Deity/Timewarp 等），且参照 36.6.3 无对应系统；属于 DATA_GAP/版本差异，不属本批“共享机制”。 |
| 整局名次分布 | 不比较 | F01/F02 只验证规则不变量（名次唯一、对局结束、无崩溃）；两引擎 bot 策略不同，名次分布不可比。 |
| 事件日志顺序 | 约定差异 | 不比较日志文字/顺序（参照文档明确 cross-source order 是约定）。 |
| AC-01 先攻平局裁定 | 证据冲突（CONVENTION_DIFF） | 决定性证据=真实 `Power.log`/HDT 语料中“同随从数不同等级且先手可判定”的样本（679 场 BB 轨迹原始日志未入库）；本批未找到，故不判 bug。 |

## 7. 统计

### 7.1 场景分类（58 个，seeds=48）

| 分类 | 数量（最终状态） | 修复前（审计初版，57 场景） |
|---|---|---|
| MATCH | 55 | 52 |
| CONVENTION_DIFF | 2（AC-01 先攻约定 + AC-04 参照侧脚本异常） | 0 |
| ENGINE_BUG | 0 | 4（AC-01…AC-04） |
| UNSUPPORTED | 1（C18） | 1 |
| DATA_GAP | 0 | 0 |
| DEFERRED | 0 | 0 |
| **合计** | **58** | **57** |

* 战斗（合成随从）场景 26 个：**24 MATCH** + 1 CONVENTION_DIFF（AC-01/C24）+
  1 UNSUPPORTED（C18）；新增 C26 = AC-04 的无脚本白板对照（MATCH）。
* 卡牌场景 16 个：**15 MATCH** + 1 CONVENTION_DIFF（AC-04/K15，参照侧脚本异常）。
* 经济/规则常量场景 14 个：**14 MATCH**（AC-02/03 修复后）。
* 流程场景 2 个：2 MATCH。

### 7.2 数据层

* 共享 id 3412；共享随从 2393（攻/血/tier/种族差异 0）；
* 卡面文本：847 条仅表示差异、37 条待复核；
* 关键词字段缺口 8 条（4 卡×2）；池：AT 245 / HS 273 / 共享 240；
* 规则常量：修复后 **18/18 一致**（AC-02/AC-03 修复前为 2 项不一致）；data_diff 规则差异 0。

## 8. 复现命令与产物

```bash
cd /Users/letiangao/HSAgent/HSBRSIM

# 1) 场景套件（pytest，13 个测试 / 约 3s）
python3 -m pytest tests/conformance -q

# 2) 全量重跑（58 场景 × 48 seeds，约 4s，写 runs/conformance/report.json）
python3 -m tools.ac_conformance.run --seeds 48

# 3) ENGINE_BUG 最小复现（AC-01…AC-04）
python3 -m tools.ac_conformance.repro            # 或 -- AC-01 AC-04
python3 -m tools.ac_conformance.repro AC-01

# 4) 数据差异（写 runs/conformance/data_diff.json）
python3 -m tools.ac_conformance.data_diff

# 5) 场景矩阵片段（生成文档表格）
python3 -m tools.ac_conformance.gen_doc
```

> **可选依赖**：本套件依赖 AutoTavern 的 `taverngym` Python 包（参照引擎）。
> 未安装时 `pytest tests/conformance` 会自动 **skip**（三个测试文件模块级
> `pytest.importorskip("taverngym", ...)`），**不是失败**，也不会破坏
> Windows 开发机的默认 `pytest tests` 收集（见 `docs/TAVERNGYM_BACKEND.md`）。
> 需要跑全量对照时按该文档安装 `taverngym`。

| 文件 | 作用 |
|---|---|
| `tests/conformance/test_conformance.py` | 套件回归：58 场景判定 vs 台账基线（行为变化即失败，提示更新台账） |
| `tests/conformance/test_data_diff.py` | 数据差异/规则常量快照（2393/3412/847/37/8 等） |
| `tests/conformance/test_versions.py` | 版本自检（taverngym 36.6.3 / HS data 37.0.0.255130 / 确定性） |
| `tools/ac_conformance/tavern_api.py` | AutoTavern 侧构造/战斗观察/经济探针 |
| `tools/ac_conformance/hsrl2_api.py` | hsrl2 侧构造/战斗观察/经济探针 |
| `tools/ac_conformance/scenarios.py` | 58 场景定义 + 台账基线 `expected` |
| `tools/ac_conformance/compare.py` | 判定口径/分类 |
| `tools/ac_conformance/run.py` | 一键 runner（JSON 报告 + 统计） |
| `tools/ac_conformance/repro.py` | AC-01…AC-04 最小复现 |
| `tools/ac_conformance/data_diff.py` | 卡牌/常量数据差异 |
| `runs/conformance/report.json` | 逐场景两侧观察/证据（gitignore） |
| `runs/conformance/data_diff.json` | 数据差异明细（gitignore） |

环境：系统 `python3`（Anaconda 3.12），`taverngym 1.0.0`（36.6.3.253932）已编译安装；
AutoTavern 仓库只读位于 `repos/AutoTavern`（可用 `AUTOTAVERN_ROOT` 覆盖）。
套件不依赖 torch/网络。

## 9. 结论与建议

1. **可用性结论**：hsrl2 与 AutoTavern 在战斗核心机制上高度一致（42 个战斗对照中
   39 MATCH 且胜负/伤害精确一致），说明 hsrl2 的战斗语义可作为可靠参照；最终
   **无 ENGINE_BUG**。
2. **裁定结果**：AC-02/AC-03 已修复（池份数/升级费，engine-fixer F-32/F-33），
   E08/E10 已转 MATCH；AC-01 证据冲突 → CONVENTION_DIFF；AC-04 经 F-35 逐帧 +
   白板控制实验证明异常在**参照侧脚本**，→ CONVENTION_DIFF（hsrl2 不改）。
   所有 `hsrl2/**` 改动遵循 Lead 批准 + `hsrl2/tests` 回归（engine 4887 passed/6 skipped）。
3. **回归接入**：`tests/conformance` 已把 58 场景判定固化为台账基线；引擎修复后
   跑套件会把对应行从 ENGINE_BUG 变 MATCH → 按提示更新
   `scenarios.expected` 与本文档即可（勿放宽断言）。
4. **扩展方向（按价值）**：
   * 用 AT Rust `mechanics.rs` 的确定性 fixture 语义补 C18（4 人局上限解除）与
     幽灵战；
   * 冻结/三连/发现奖励的真实行为对照（需要更细的调试入口）；
   * 把 AC-01/02/03 的修复做成 A/B 行为回归（修复前后分布对比），确认训练指标
     变化方向；
   * 数据生成器补 `stealth/cleave/mega_windfury/end_of_turn` 字段（DATA_GAP）。
5. **限制**：AutoTavern 是第三方客户端重建参照，不是官方实现；本台账的
   “一致”只证明两实现一致，不证明官方等价；官方等价仍需真实 Power.log/官方
   裁决器（见 `docs/EXACTNESS_STATUS.md` 的既有结论）。

## 10. 修订记录

| 时间 | 变更 | 触发 |
|---|---|---|
| 2026-10-26 初版 | 57 场景；52 MATCH / 4 ENGINE_BUG（AC-01…AC-04）/ 1 UNSUPPORTED | 本次审计 |
| 2026-10-26 最终-1 | AC-01 改判 CONVENTION_DIFF（wiki 现行文本 vs 参照实现二源冲突）；AC-02/03 修复后 E08/E10 → MATCH；新增顶部最终状态表、AC-01 决定性证据路径、修订记录 | Lead 裁定 + engine-fixer 合入 |
| 2026-10-26 最终-2 | AC-04 改判 CONVENTION_DIFF（F-35：400 局逐帧排除复仇/嘲讽假设 + 无脚本白板控制实验 → 参照侧脚本行为异常，非 hsrl2 bug）；新增 C26 白板对照场景；统计 **58 场景：MATCH 55 / CONVENTION_DIFF 2 / ENGINE_BUG 0 / UNSUPPORTED 1**；§5/§7/§0 同步 | engine-fixer F-35 + Lead 裁定 |
