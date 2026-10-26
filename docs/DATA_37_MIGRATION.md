# 37.0.0.255130 → AutoTavern schema 数据迁移报告

> **一句话**：把 HSBRSIM 官方数据 `data/bg_*.json`（patch **37.0.0.255130**）离线、可复现地映射为
> AutoTavern（36.6.3，MIT）Rust 引擎使用的 `cards.json` schema，产物为 `data/p2/cards_37.json`
> （3983 卡 = 3695 映射 + 288 compat），并给出与上游 36.6.3 的定量差分、字段覆盖率、局限与交接事项。
>
> 所有数字均由 `tools/p2_data/gen_carddb_37.py` 实际产出，可用 `--report`/`--check` 复算；
> 本文件中的数字与 `data/p2/MANIFEST.json` 一一对应。

| 项目 | 值 |
|---|---|
| 目标数据版本 | 37.0.0.255130（`data/bg_summary.json` 的 `patch`） |
| 上游参照 | AutoTavern 36.6.3.253932 / 36.6.3，`crates/taverngym/data/cards.json`（3983 卡） |
| 生成器 | `tools/p2_data/gen_carddb_37.py` v1.1.0（纯标准库、无网络） |
| 产物 | `data/p2/cards_37.json`、`data/p2/MANIFEST.json`、`data/p2/new_cards_37.json`、`data/p2/at_scripted_ids.json` |
| 映射卡 / compat / 合计 | **3695 / 288 / 3983** |
| 37 独有但不入 schema | 122（108 异变 + 14 UI 按钮），见 `new_cards_37.json` |
| 自检 | 27 项 pytest 全绿；生成器两次运行 byte-identical；`--check` OK |
| P2-C 审计修复（P2-B2） | ① 单人池剔除 3 张 Duos-only 法术（spell 76→**73**）；② 全卡库 `text/text_alt/text_zh/text_alt_zh` 无 `@` 残留，见 §2.4 |
| P2-B3 Rust 集成修复 | ① T3 继承 AT 机制元数据（`pool_tag` 原值 0/1/2、`lobby_req`、`assoc` 顺序等）；② Dark Paradox：base `BG36_360` 不入池 + 5 形态入池（minion 273→**277**），见 §2.5 |

---

## 1. 目标与设计原则

第二阶段主路线是 fork AutoTavern 的 Rust 引擎（`hsbg_engine`）。上游把
`crates/taverngym/data/cards.json` 用 `include_str!` 编译进二进制（`cards.rs`），并用
`CardKind::parse` 解析 10 种 kind。本迁移把 HSBRSIM 的 37.0.0 官方数据映射到**同一 schema**，
使 Rust fork 可以“只换数据文件、不改引擎结构”地升级到最新数值。

三条原则：

1. **能映射的映射，映射不了的分层处理，禁止编造。**
   - **T1**：37 官方数据直接映射（绝大多数字段）；
   - **T2**：37 数据没有等价来源、但 36.6.3 上游有同一卡片 id 的来源 → 继承并在
     `MANIFEST.field_provenance` / `MANIFEST.t2_inherited` 显式登记（中文对齐/链接补齐，见 §4.7/§4.8）；
   - **T3**：AutoTavern 机制实现依赖的**客户端元数据**（`pool_tag`/`lobby_req`/`assoc` 顺序等）
     37 没有权威来源 → 从 36.6.3 精确继承，登记 `MANIFEST.t3_inherited_meta`（见 §4.10，P2-B3）；
   - **T4**：两版都没有 → 省略字段（Rust serde `#[serde(default)]` 兜底默认值），列入 §10 局限。
2. **并集策略**：上游 Rust 引擎启动时 `script.rs::registry()` 会对每个 content 脚本执行
   `db().id(id)`，`CardDb::id` 对缺失 id **直接 panic**（`cards.rs:397-406`
   `"card id not in database: {id}"`）。因此 36.6.3 有、37.0.0 官方数据里没有的卡以 **compat 条目**
   保留（字段沿用上游，`pools=[]`、`pool_tag=0`、`reachable=false`），保证所有脚本 id 可解析，
   同时不进入任何池子、不改变对局内容（见 §8）。
3. **确定性**：输出不含时间戳，卡按 id 排序、一行一卡（上游 `render()` 同款格式）；同一输入
   两次运行 byte-identical。

---

## 2. 输入数据（只读）

全部来自 HSBRSIM `data/`（patch **37.0.0.255130**）：

| 文件 | 行数 | 用途 |
|---|---:|---|
| `data/bg_cards.json` | 3534 | BG 全卡（含金卡/衍生/法术/饰品/任务奖励/异变/按钮），核心输入 |
| `data/bg_pool_minions.json` | 273 | 当前池内随从（`is_pool_minion=true`） |
| `data/bg_pool_spells.json` | 76 | 池内酒馆法术（`is_pool_spell=true`）；**单人池有效 73**（剔除 3 张 Duos-only，见 §2.4） |
| `data/bg_heroes.json` | 118 | 英雄（hp/armor/`hero_power_dbf`/`companion_id`/`hero_draftable`） |
| `data/bg_hero_powers.json` | 165 | 英雄技能（cost/text） |
| `data/bg_trinkets.json` | 409 | 饰品（`spell_school` 11=小饰品、12=大饰品） |
| `data/bg_quest_rewards.json` | 73 | 任务奖励（5 张带 `reward_dbf_id`） |
| `data/bg_dark_gifts.json` | 47 | 黑暗赠礼（37 新机制，文本无 flag） |
| `data/bg_tavern_spells.json` | 205 | 酒馆法术全集（含池外/衍生） |
| `data/bg_anomalies.json` | 108 | 异变（AutoTavern schema **无**对应 kind，不入库） |
| `data/card_zhcn.json` | 34607 | 中文名/文本（**实测为 36.2 时代快照**，见 §4.8） |
| `data/bg_summary.json` | — | 版本/统计（patch 字段用于 MANIFEST 核对） |

上游只读参照：`/Users/letiangao/HSAgent/repos/AutoTavern`（可用 `--at-root` 或
`HSBRSIM_AT_ROOT` 覆盖）：`crates/taverngym/data/cards.json`（3983 卡）、
`crates/taverngym/src/content/*.rs`（脚本注册表）。

### 2.4 修复记录（P2-C 交叉审计 → P2-B2）

P2-C 在 P2-B 产物里发现 2 个数据层问题，已在生成器修复并重新生成（本次即修复后产物）：

| # | 问题 | 根因 | 修复 | 证据/校验 |
|---|---|---|---|---|
| 1 | `BG31_242/243/244` 3 张 Duos-only 法术 `pools=['spell']`、`reachable=true`，混入单人池（应为 73 而非 76） | 37 `bg_pool_spells.json` 的 `is_pool_spell` 标记含 Duos 卡；单人/双人池共用同一标记 | 生成器新增 `is_duos_only()`：文本拆分后**无第二段（无单人变体）**且匹配 `\bteammate\b|\bpass (?:a|an|one)\b` → 强制 `pools=[]`、`pool_tag=0`、`reachable=false`（T2 继承后仍强制覆盖）；MANIFEST 新增 `pool_scope.excluded_duos_only`（ids/规则/证据） | P2-C `docs/PORTING_37_PLAN.md` §2.4/§4.5；36.6.3 上游同 id 均 `pools=[]`/`reachable=false`；3 张无金卡形式（37 与 36.6.3 均无 `_G`）。影响：`spell` 池 76→**73**，`reachable` 真值 −3 |
| 2 | `JAIL_800hp2.text` 残留 `@` 分隔符 | 该卡是 **compat 条目**（36.6.3 独有，上游 `cards.json` 文本自带 `@` 变体分隔符，36.6.3 仅此 1 处），P2-B 的 compat 路径原样拷贝未拆 | `make_compat_entry()` 对 compat 的 `text/text_zh` 只拆 `@` 分隔符（不替换占位符、不清洗其余内容）：`text="…twice."`、`text_alt="({0} left!)"`；自检新增“全卡库 4 个文本字段无 `@`”断言 | 全库残留 `@` = **0**；compat 其余字段仍与上游逐字一致 |

> 说明：这 2 项均为**池口径/文本格式**问题，不改变 3983 总数、3695 映射 / 288 compat、上游脚本 id
> 1290 个 0 missing 等既有结论。

### 2.5 修复记录（P2-B3：AT 机制元数据 + Dark Paradox）

Rust 主引擎替换 37 数据后 `cargo test --release -p hsbg-engine` 出现 3 个失败
（`mechanics.rs::pool_tag_rule_excludes_rot_hide_gnoll_by_default`、
`mechanics.rs::lobby_without_forced_aberrations`、
`mechanics.rs::aberration_subset_needs_aberrations_in_the_lobby`），根因是
**AutoTavern 机制实现依赖的客户端元数据在 37 官方数据里没有权威来源**。修复如下：

| # | 问题 | 修复 | 证据/影响 |
|---|---|---|---|
| 1 | AT 用 `pool_tag`（客户端 `IS_BACON_POOL_MINION` 原值：3681 张 0、301 张 1、1 张 2）做 strict 池过滤；37 源只有布尔 `is_pool_minion`，`BG25_013`（AT=2）被当成 1 → 进入 universe | **T3 继承**：对两版本共享 id，从 36.6.3 上游 `cards.json` **精确继承 `pool_tag`**（含 0 值）；叠加其余机制字段（见 §4.10） | Rust `flow.rs` `strict_pool_tag` 默认 true（`pool_tag<=1` 才进 universe）；`BG25_013` 恢复 2 → 默认被过滤；`pools.minion && pool_tag<=1` = **276**（277−1） |
| 2 | Dark Paradox：AT `flow.rs::PARADOX_VARIANTS` 用 5 个 token 作为每局形态；37 源把 base `BG36_360` 标池内、5 形态不标 → universe 里 paradox 形态数 0，测试断言 `forms==1` 失败 | **特例对齐 AT 机制**：base `BG36_360` → `pools=[]`/`reachable=false`；`BG36_360t3/t4/t5/t6/t9` → `pools=['minion']`/`reachable=true`（tier/数值保持 37 值，与 AT 的 2/5/4/3/6 一致） | 依据 AT `flow.rs::PARADOX_VARIANTS` 注释（每局随机 1 形态进池）；MANIFEST `pool_scope.dark_paradox` 逐项记录。单一池 minion 273→**277** |
| 3 | `lobby_req`（饰品/酒馆法术的种族 lobby 条件，如 Aberration 子集）37 映射缺失 → 无 Aberration 大厅仍出 Aberration 子集饰品 | 同 T3：从 36.6.3 精确继承 `lobby_req`（59 张：43 酒馆法术 + 15 饰品 + 1 英雄） | `BG36_371`/`BG36_301t`/`BG36_303`（酒馆法术）与 15 张 Aberration 饰品恢复门控；回归 PASS |

> 这 3 项均为**机制元数据/池语义**修复，不改变 37 的数值/文本/原名、不改变 3983/3695/288 与脚本 id
> 1290 个 0 missing；同时新增 MANIFEST `t3_inherited_meta`（字段/来源/id 数/覆盖率）与
> `mechanism_meta`（Rust 断言所需的派生计数）。

---

## 3. 产物

| 文件 | 大小 | sha256（前 16） | 内容 |
|---|---:|---|---|
| `data/p2/cards_37.json` | 1.66 MiB（1700 KiB） | `c482612727c2618e` | AutoTavern schema 卡库（3983 卡，meta+cards） |
| `data/p2/MANIFEST.json` | 42 KiB | `0776acad169d3435` | 源版本/计数/字段来源与覆盖率/T3 机制元数据/差分/自检/脚本 id 摘要/产物哈希 |
| `data/p2/new_cards_37.json` | 18 KiB | `eb1297242b4302d4` | 37 独有、schema 不收录的 122 个 id（异变/按钮）清单 |
| `data/p2/at_scripted_ids.json` | 65 KiB | `b0b534084b79e851` | AutoTavern 源码引用的全部卡 id（分类 + 解析结果） |

`cards.json` 的 `meta`（Rust `RawMeta` 只读前两个字段，其余供人/工具追溯）：

```json
{"client_version":"37.0.0.255130","server_patch":"37.0.0",
 "source":"HSBRSIM 官方数据 37.0.0.255130 + AutoTavern 36.6.3 compat 条目",
 "count":3983,"mapped_count":3695,"compat_count":288,
 "generator":"HSBRSIM tools/p2_data/gen_carddb_37.py v1.1.0",
 "at_baseline":"36.6.3.253932 (36.6.3)"}
```

---

## 4. 映射表（37 数据 → AutoTavern schema）

来源等级：**T1**=37 直接映射；**T2**=36.6.3 继承（中文/链接等）；**T3**=AT 机制元数据继承
（P2-B3，见 §4.10）；**T4**=省略/默认。上游字段类型见
`crates/taverngym/src/cards.rs` 的 `RawCard`/`CardDef`。

### 4.1 kind 判定（10 种取值，`CardKind` 同构）

| 37 来源 | 判定 | 卡数（映射） |
|---|---|---:|
| `bg_cards.card_type=4`（MINION） | `minion` | 2393 |
| `bg_cards.card_type=5`（SPELL）+ `dark_gift=true` | `dark_gift` | 47 |
| `bg_cards.card_type=5` + `quest=true`，或 `quest_progress_total` 非空且文本含 `Quest` | `quest` | 22 |
| `bg_cards.card_type=5` 其余 | `spell` | 263 |
| `bg_cards.card_type=40`（BACON_QUEST_REWARD） | `quest_reward` | 73 |
| `bg_cards.card_type=42`（BACON_SPELL） | `tavern_spell` | 205 |
| `bg_cards.card_type=44`（BACON_TRINKET）+ `spell_school=12` | `trinket_greater` | 215 |
| `bg_cards.card_type=44` + `spell_school=11` | `trinket_lesser` | 194 |
| `bg_heroes` | `hero` | 118 |
| `bg_hero_powers` | `hero_power` | 165 |
| `card_type∈{43(异变),12,22,24(按钮/UI)}` | **不入 schema**（T4） | 122 |

- 饰品大小类判定依据：36.6.3 共享 id 上 `spell_school=11` 与 `trinket_lesser` **194/194**
  吻合、`=12` 与 `trinket_greater` **215/215** 吻合（唯一可判据，非猜测）。
- `quest` 文本判定：36.6.3 有 10 张任务卡在 37 数据里没有 `quest` 布尔标记，但都有
  `quest_progress_total` 且文本含 `Quest`；该规则在共享 id 上与上游 kind 只有 **1 张**不同
  （`BG24_Quest_328` “Close the Case”：文本 `Quest: Win the game.`、`quest_progress_total=1`，
  37 数据语义上是任务，上游 bundle 归类为 spell → 本报告按 37 数据判为 `quest`，见 §6.4）。

### 4.2 字段总表

| AutoTavern 字段 | 37 来源 | 等级 | 说明/校准 |
|---|---|---|---|
| `id` | `id` | T1 | 排序输出 |
| `dbf` | `dbf_id` | T1 | 共享卡与上游逐卡一致（0 差异） |
| `kind` | 见 §4.1 | T1 | 10 种取值 |
| `name` | `name` | T1 | 共享卡 3695/3695 与上游一致 |
| `name_zh` | `card_zhcn.n`，缺失补上游 | T1→T2 | 补 388 张（主要为 BG36 前缀） |
| `tier` | `tech_level`（缺省 0） | T1 | 共享卡 3695/3695 一致 |
| `atk` / `hp` | `atk` / `health`（缺省 0） | T1 | 共享卡 3695/3695 一致 |
| `armor` | `bg_heroes.armor`，其余 0 | T1 | 共享卡 3695/3695 一致 |
| `cost` | `cost`（缺省 0） | T1 | 见 §6.4 口径差异（随从 cost 0→3，引擎不消费随从 cost） |
| `races` | `card_race` 数值→名称 ∪ `race_tags`（`MECH`→`MECHANICAL`），保序 | T1 | 验证：共享随从种族集合 3695/3695 精确一致 |
| `assoc` | `subset_*`：随从 = subset − `races`；非随从 = subset | T1→T3 | 共享卡 3695/3695；顺序/缺失项按上游精确继承（§4.10） |
| `lobby_req` | 酒馆法术 = `subset_*`；其余取上游 | T1→T3 | 59 张全部按上游继承（43 酒馆法术 + 15 饰品 + 1 英雄，含 Aberration 门控） |
| `keywords` | 布尔 flag → 名称 + 少量文本规则 | T1 | 见 §4.4 |
| `golden` / `normal` | `triple_upgrade_id` / `triple_base_id`（dbf→id） | T1→T2 | 可解析 1165 条与上游 100% 一致；22/7 条目标缺失时 T2 补齐 |
| `pools` | minion/tier7/spell/hero 来自 37 池子文件；trinket/timewarp 取上游 | T1→T2 | 见 §4.6（含 Duos-only 剔除与 Dark Paradox 特例） |
| `pool_tag` | 36.6.3 客户端 `IS_BACON_POOL_MINION` 原值（0/1/2） | **T3** | 37 只有布尔 `is_pool_minion`，无法表达 `BG25_013=2`；Rust strict 池过滤依赖它（§4.10） |
| `reachable` | 池内为真 ∪ 上游 `reachable` | T1→T2 | 见 §4.6 |
| `text` / `text_alt` | `text` 规范化 + `@` 变体拆分 | T1→T3 | 见 §4.5；共享卡英文 3688/3695 与上游逐字一致；上游有变体且文本对齐时 `text_alt` 取上游（§4.10） |
| `text_zh` / `text_alt_zh` | 上游中文（英文逐字一致时优先），`card_zhcn` 兜底 | T2→T1 | 见 §4.8 |
| `hero_power` | `bg_heroes.hero_power_dbf` → id | T1 | 118 张全解析，跳过自引用 |
| `buddy` | `bg_heroes.companion_id` → id | T1 | 109 张（与上游 109/109 一致） |
| `spellcraft` | `spellcraft_id` → id | T1 | 70 张（与上游 70/70 一致） |
| `spellcraft_spell` | 被任意 `spellcraft_id` 指向的卡 | T1 | 69 张（与上游 69/69 一致） |
| `quest_goal` | `quest_progress_total` | T1 | 42 张，值全部一致 |
| `reward_card` | `reward_dbf_id` → id | T1 | 5 张全一致 |
| `window` | 上游 | T2 | 黑暗赠礼 offer 回合窗（47 张），37 无来源 |
| `prize_tier` | 上游 | T2 | 暗月奖券等级（32 张），37 无来源 |
| `tw_types` / `tw_weight` / `tw_min_minions` | 上游 | T2 | 时间扭曲卡（93/143/3 张），37 无来源 |
| `name`/`text` 之外的空字段 | — | T4 | 省略，Rust serde 默认 |

### 4.3 races / assoc / lobby_req：`subset_*` 的真实语义（实测校准）

37 数据的 `subset_beast/subset_mech/...` 布尔标记**不是**种族字段，而是“池内子集”标记。用
36.6.3 共享卡实测三种语义：

1. **非随从卡（饰品/任务奖励/英雄/英雄技能/法术/黑暗赠礼）**：`subset_*` ≡ 上游 `assoc`
   （关联种族/饰品适配种族）——409 张饰品、73 张任务奖励、118 英雄、165 英雄技能、264 法术
   全部 0 例外；
2. **酒馆法术**：`subset_*` 同时等价于上游 `lobby_req`（仅在该种族酒馆出现）——共享 202/205
   精确吻合，剩余 3 张是 37 新增卡（上游用 ABERRATION 门控，37 数据无对应标记）；
3. **随从卡**：`subset_*` 是“池内子集”（含自身种族与“配合该种族的中立随从”），
   上游 `assoc` = subset − `races` ——2393 张共享随从 0 例外。

因此映射表达式：

```
races      = [card_race 数值→名称] + race_tags（保序、MECH→MECHANICAL）
assoc      = kind==minion ? (subset − races) : subset
lobby_req  = kind==tavern_spell ? subset : (上游非空时 T2 继承)
```

> 注：上游 `assoc` 的**顺序**来自 bundle 字段序，37 数据只有布尔标记，无法还原顺序；
> 输出按字母序（`Races` 是位掩码，顺序无语义，差异统计按集合比较）。

### 4.4 keywords：flag 直映射 + 少量文本规则

flag → 名称（全部由 36.6.3 校准，括号内 tp/fp/fn）：

`battlecry→BATTLECRY(324/0/0)`、`deathrattle→DEATHRATTLE(390/0/0)`、`taunt→TAUNT(174/0/0)`、
`divine_shield→DIVINE_SHIELD(121/1/0)`、`windfury→WINDFURY(33/0/0)`、`reborn→REBORN(55/1/0)`、
`magnetic→MAGNETIC(52/0/1)`、`venomous→VENOMOUS(29/0/0)`、`poisonous→POISONOUS(5/0/0)`、
`avenge→AVENGE(120/0/0)`、`start_of_combat→START_OF_COMBAT`、`rally→BACON_RALLY(144/0/0)`、
`choose_one→CHOOSE_ONE(33/11/3)`、`quest→QUEST`、`spellcraft_id→BACON_SPELLCRAFT_ID(70/0/0)`。

文本补充规则（37 没有对应 flag 的机制）：

| 规则 | 适用范围 | 36.6.3 实测 |
|---|---|---|
| 文本含 `Start of Combat:` → `START_OF_COMBAT` | minion（上游同款规则）+ 饰品/英雄技能/任务奖励 | tp 171 / fp 5 / fn 8 |
| 文本以 `Stealth` 开头 → `STEALTH` | minion | tp 20 / fp 0 / fn 0（纯文本无法区分“给予潜行”，只用“开头”判定） |
| `end of your/each/every [N] turn(s)` → `END_OF_TURN_TRIGGER` | minion | tp 176 / fp 8 / fn 15（行为上仅用于黑暗赠礼 t21 资格） |
| 加粗机制词（`<b>Deathrattle:</b>` 等）→ 对应关键词 | dark_gift（37 无布尔 flag） | 与上游 45/47 一致（t12/t15 多出 REBORN/DIVINE_SHIELD） |

**无法还原的机制词**：`TRIGGER_VISUAL`（1314 张，纯视觉触发标记，引擎不使用）、`AURA`（155）、
`DISCOVER`（29，文本启发式精确率仅 16%，不映射）、`InvisibleDeathrattle/SECRET/SIDE_QUEST/
TWINSPELL` 等旧标签。这些只会影响“按机制筛选卡池”的展示型过滤，不影响脚本行为；与上游的
关键词差异见 §6.4。

### 4.5 文本规范化（只做格式整理，不引入新内容）

1. **变体拆分**：hsdata 用 `@` 粘连多段显示文本（例：`... (2 turns left!)@[x]At the end of...`）。
   判定规则：`@` 前最后一个非空白字符是句末标点（`.!?>)>。！？；：`）或 `@` 后紧跟 `[x]`/`<b>`
   → 视为分隔符，第 1 段 → `text`，第 2 段 → `text_alt`（上游 schema 只有一段 alt；映射集内
   全部是两段，共 154 张，其中 2 张清洗后与主文本相同被去重，实际产出 152 张 `text_alt`）。
   剩余 `@` 是“动态数值占位符”。
2. **占位符**：`{N}` → `script_data_num_{N+1}`（缺失按上游同款渲染为 `0`）；剩余 `@` →
   `script_data_num_1`。例：`Avenge ({2}): Give adjacent minions +{0}/+{1}.` →
   `Avenge (3): Give adjacent minions +2/+2.`（与上游逐字一致）。
3. **复数标记** `|4(singular, plural)`：按同句最近的前置数字判单复数（`1 |4(spell, spells)` →
   `1 spell`；`2 |4(turn, turns)` → `2 turns`），无数字时按复数。
4. **清理**：去 `<b>/<i>/[x]` 标记、`_`→空格（hsdata 的空格标记）、`-\n`→`- `、换行→空格、
   压缩连续空格。与上游 `gen_carddb.clean()` 等价。
5. **compat 条目的文本**：36.6.3 上游 `cards.json` 里偶发残留 `@` 变体分隔符（全库仅
   `JAIL_800hp2` 1 处）。compat 条目要求“字段沿用上游”，因此只拆 `@` 分隔符（第 1 段 →
   `text`、第 2 段 → `text_alt`；不替换占位符、不做其它清洗），保证全库 4 个文本字段
   无 `@` 残留（§2.4 修复 2）。
6. 结果：共享卡英文文本 **3688/3695（99.81%）** 与上游逐字一致；剩余 7 张是已知边界
   （见 §6.4 Top 列表，全部可由“占位符/变体/复数”规范化口径解释），**未观察到真实的卡面
   内容改动**。

### 4.6 pools / pool_tag / reachable

| 池子 | 37 来源（T1） | 张数 | 说明 |
|---|---|---:|---|
| `minion` | `bg_pool_minions` + Dark Paradox 特例 | **277** | 原始池文件 273；base `BG36_360` 移出（−1）、5 个形态入池（+5），见 §4.11；含 13 张 7 级 |
| `tier7` | 池内随从且 `tech_level=7` | 13 | 36.6.3 为 12（多 1 张 `BG27_514`） |
| `spell` | `bg_pool_spells`（剔除 Duos-only） | **73** | 36.6.3 为 70；原始池文件 76，剔除 `BG31_242/243/244`（§2.4） |
| `hero` | `bg_heroes`（全部 `hero_draftable`） | 118 | 36.6.3 为 116（+`BG22_HERO_007`/`BG23_HERO_304`） |
| `trinket` | **T2**：上游 trinket 池成员 | 236 | 37 数据不提供饰品“当前是否可被提供”的信息 |
| `timewarp` | **T2**：上游 timewarp 池成员 | 253 | 37 数据不含轮换/临时禁用视图 |

**Duos-only 剔除规则**（P2-C 审计）：37 数据用 `单人文本@Duos文本` 表示双版本卡（如
`BG36_100`，有第二段 → 单人可用）；只有“文本拆分后无第二段且含 `teammate` / `Pass a…`
标记”的卡才是 Duos-only。当前仅池法术 `BG31_242 Bargain Bundle`、`BG31_243 Portal in a
Fountain`、`BG31_244 Portal in a Crystal` 3 张命中（无金卡形式），`36.6.3` 上游同 id 也是
`pools=[]`/`reachable=false`。MANIFEST `pool_scope.excluded_duos_only` 逐项登记。

**Dark Paradox 特例**（P2-B3，详见 §4.11）：37 源把 base `BG36_360` 标为池内、5 个形态 token
不标；按 AT `flow.rs::PARADOX_VARIANTS` 机制，base 不入池（−1）、5 形态入池（+5），故有效
minion 池 = 273 − 1 + 5 = **277**。

`pool_tag` **不再由 `is_pool_minion` 推导**，而是按 T3 从 36.6.3 上游 `cards.json` **精确继承**
客户端 `IS_BACON_POOL_MINION` 原值（全库 3681 张 0 / 301 张 1 / 1 张 2，37 数据只有布尔值无法
表达 2）。Rust `flow.rs` 在 `strict_pool_tag`（默认 true）下用 `pool_tag <= 1` 过滤，因此
`BG25_013`（tag=2）即便 `pools=['minion']` 也不会进入 universe；`pools.minion && pool_tag<=1`
= **276**。`reachable` = “在任一池子” ∪ 上游 `reachable`（37 无 views 数据，故 token 可达性沿用
上游；该字段在 Rust 引擎中只用于 debug/serialize，无行为影响）。

### 4.7 关系字段与 T2 继承清单

T2（`MANIFEST.t2_inherited` 实际计数）：

| 字段 | 计数 | 原因 |
|---|---:|---|
| `text_zh` 对齐替换 | 110 | 英文与上游逐字一致 → 中文采用上游（见 §4.8） |
| `text_zh` 补齐 | 395 | `card_zhcn` 无该卡中文 |
| `name_zh` 补齐 | 388 | 同上 |
| `text_alt_zh` | 17 | 上游有中文变体 |
| `golden` / `normal` 补齐 | 18 / 6 | 37 的 `triple_*` 目标 dbf 不在 37 卡表（只存在于 compat） |
| `lobby_req`（ABERRATION 门控） | 19 | 37 数据无 `subset_aberration` |
| `window` / `prize_tier` / `tw_*` | 47 / 32 / 93·143·3 | 37 数据无对应来源（`window`/`prize_tier` 已并入 §4.10 的 T3 精确继承） |

### 4.8 中文数据源（重要发现）

**`data/card_zhcn.json` 实测是 36.2 时代的中文快照**，不能直接当“37 最新中文”用：

- 关键证据 1：**没有任何 BG36 前缀的中文**（37 数据里 BG36 卡 360 张，`card_zhcn` 命中 0），
  而 36.6.3 上游 bundle 有 BG36 中文；
- 关键证据 2：大量台词仍是旧机制/旧数值。例 `BG28_582`：37 英文是
  `Activate (0): Discard a card to get 3 Blood Gems.`，上游中文 `发动（0）：弃掉一张牌…`（对齐），
  `card_zhcn` 是 `在你的回合开始时，弃掉一张法术牌…`（旧版）；`BG23_017` 37 英文 `+2/+1`，
  上游中文 `+2/+1`，`card_zhcn` 为 `+1/+1`（旧数值）。

因此中文策略：**当 37 英文文本与 36.6.3 英文逐字一致时，优先采用 36.6.3 中文**
（与英文同源、比旧快照新）；`card_zhcn` 仅作兜底（英文不一致的 7 张边界卡）与 `name_zh` 主源。
结果：`text_zh` 在“双方都非空”的 3515 张卡上与上游 **3515/3515（100%）一致**；覆盖率 3515/3695
（其余 180 张上游中文本身为空，如部分 token）。名字沿用 `card_zhcn`（1 张比上游占位名 `废案`
更好：`BG34_Trinket_2nd_Spell`）。

### 4.10 T3：AutoTavern 机制元数据继承（P2-B3）

37 官方数据（`data/bg_*.json`）只覆盖“卡牌数值/文本/池子标记”，**不包含 AT 机制实现依赖的
客户端 tag 与关系字段**。为让 Rust 主引擎的机制断言成立，生成器对**两版本共享的 3695 个
mapped id** 从 36.6.3 上游 `cards.json` 继承下列字段（`MANIFEST.t3_inherited_meta` 逐字段记录
`at_non_default`/`applied`/`changed`/`already_equal`）：

| 字段 | 继承方式 | 上游有值 id 数 | 实际写入 | 与 37 推导值的变化 | 用途 |
|---|---|---:|---:|---:|---|
| `pool_tag` | **精确覆盖**（含 0） | 274（mapped） | 3695 | 70 | Rust `strict_pool_tag` 池过滤（`BG25_013`=2） |
| `lobby_req` | 上游非默认才继承 | 59 | 59 | 0 | 大厅种族门控（Aberration 子集饰品/法术/英雄） |
| `assoc` | 上游非默认才继承 | 398 | 398 | 7（仅顺序） | 类型关联（trinket 提供条件/英雄 lobby 适配） |
| `hero_power` | 上游非默认才继承 | 118 | 118 | 0 | 英雄→主技能 |
| `buddy` | 上游非默认才继承 | 109 | 109 | 0 | 英雄→伙伴 |
| `spellcraft` | 上游非默认才继承 | 70 | 70 | 0 | 随从/饰品→法术巧手临时法术 |
| `spellcraft_spell` | 上游非默认才继承 | 69 | 69 | 0 | 法术巧手法术标记 |
| `reward_card` | 上游非默认才继承 | 5 | 5 | 0 | 任务奖励→关联卡 |
| `quest_goal` | 上游非默认才继承 | 42 | 42 | 0 | 任务进度目标 |
| `window` | 上游非默认才继承 | 47 | 47 | 0 | 黑暗赠礼提供回合窗 |
| `prize_tier` | 上游非默认才继承 | 32 | 32 | 0 | 暗月奖券等级 |
| `text_alt` | 上游非默认**且英文逐字对齐**才继承 | 9 | 8 | 0 | 多段显示文本（`BG_OldGod` 英文不一致故不继承） |
| `text_alt_zh` | 上游非默认且中文对齐才继承 | 122 | 122 | 1 | 多段中文显示文本 |

> 这些字段**不改变 37 的数值/文本/原名**（`tier/atk/hp/armor/cost/name/text/races` 仍来自 37）；
> 37 独有的卡（本迁移中只有不入库的异变/按钮）无继承值。`pool_tag` 必须精确继承含 0 值：
> AT 用“客户端原始 tag”而非“是否在池”表达特殊隐藏（tag=2）。

### 4.11 Dark Paradox 特例（P2-B3）

AutoTavern 机制（`flow.rs::PARADOX_VARIANTS`）：Dark Paradox 的 base 卡**不进 universe**，
每局从 5 个形态中随机选 1 个进池（`universe` 对 `BG36_360t*` 只保留被选中的形态；
tier5 形态是 `t4`、tier6 形态是 `t9`）。37 源的 `is_pool_minion` 把 base 标为池内、5 个形态
不标，若直接映射会导致 Rust 侧“paradox 形态数 = 0”断言失败。

生成器按 AT 机制约定特例修正（tier/攻血/文本保持 37 数据值，与 AT 的 tier 2/5/4/3/6 一致）：

| 卡 | 37 源 | 产物 | 依据 |
|---|---|---|---|
| `BG36_360`（base） | `is_pool_minion=true` | `pools=[]`、`reachable=false` | AT base 不入池 |
| `BG36_360t3` (tier 2) / `t4` (5) / `t5` (4) / `t6` (3) / `t9` (6) | 无池标记 | `pools=['minion']`、`reachable=true`、`pool_tag<=1` | AT 5 形态每局随机 1 个进池 |

效果：单人池 minion 273 − 1 + 5 = **277**；Rust `pool_tag_rule...`/`lobby_without_forced_aberrations`/
`aberration_subset_needs_aberrations_in_the_lobby` 三条断言所需的 universe 内容恢复。
MANIFEST `pool_scope.dark_paradox` 与 `mechanism_meta.dark_paradox` 逐项记录；P1 内容移植阶段
会改为 37 单卡动态机制（见 `docs/PORTING_37_PLAN.md`）。

---

## 5. 生成与校验命令

```bash
cd /Users/letiangao/HSAgent/HSBRSIM

# 生成（写 data/p2/*，默认 --at-root=/Users/letiangao/HSAgent/repos/AutoTavern）
python3 tools/p2_data/gen_carddb_37.py

# 只打印统计，不写文件（映射/compat 计数、kind 表、差分、脚本 id、耗时）
python3 tools/p2_data/gen_carddb_37.py --report

# 校验：重算并与入库产物逐字节比较；同时校验 meta/计数/脚本 id（0 missing）
python3 tools/p2_data/gen_carddb_37.py --check

# 可复现性测试（22 项：数据自检 + 双跑 byte-identical + --check 正/负路径 + 交叉验证）
python3 -m pytest tests/test_p2_data.py -q
```

可选参数：`--out DIR`（写/校验到其他目录）、`--at-root PATH`（上游只读仓库，亦可用环境变量
`HSBRSIM_AT_ROOT`）。生成器纯标准库、不联网；本机生成耗时 **约 0.5–1.1s**（`--report` 打印实测值）。

---

## 6. 与上游 36.6.3 的定量差分

差分口径：共享 id（3695）上，以 36.6.3 上游 `cards.json` 为参照；列表字段按集合比较（顺序无
语义）；可选字段“缺失”等价 schema 默认值。完整 Top 列表见 `MANIFEST.diff_vs_at_36_6_3`。

### 6.1 总体

| 项 | 数量 |
|---|---:|
| 共享 id（36.6.3 ∩ 37.0.0） | 3695 |
| 上游独有 → **compat 条目** | 288 |
| 37 独有、schema 不收录（异变/按钮） | 122 |
| 产物卡总数（= 上游 3983，id 集合完全相同） | 3983 |

- **新增可玩卡：0 张**（37.0.0 没有新增 AutoTavern schema 内的卡 id；122 张 37 独有 id 全是
  异变 108 + UI 按钮 14，schema 无对应 kind）。
- **移除（退环境/换季）**：288 张，按 kind：minion 203、spell 33、hero 25、hero_power 11、
  trinket_lesser 7、trinket_greater 4、tavern_spell 3、quest 2。主要来源：
  BGDUO* 134（双人模式）、TB_* 40、RLK/EX1/ICC/BOT/CORE/GVG/VAN 等旧系列重印。
  **这 288 张在 36.6.3 中本来就不在任何池子**（`removed_by_pool` 为空）→ compat 条目不影响对局内容。
- **产物 id 集合与顺序与上游完全相同** → Rust `CardDb` 表序不变，`fingerprint`（FNV-1a，只哈希
  id）与 36.6.3 **相同**，已有存档的 `Game::check_loaded` 不会因换数据而判新旧表不兼容。

### 6.2 数值字段：0 变化

共享 3695 张卡上，以下字段与 36.6.3 **逐卡完全一致**（`MANIFEST.cross_validation_vs_at_36_6_3`）：

`name` 3695/3695、`tier` 3695/3695、`atk` 3695/3695、`hp` 3695/3695、`armor` 3695/3695、
`golden` 3695/3695、`normal` 3695/3695、`hero_power` 3695/3695、`buddy` 3695/3695、
`spellcraft` 3695/3695、`quest_goal` 3695/3695、`reward_card` 3695/3695、
**`pool_tag` 3695/3695**（T3 精确继承，§4.10）。

> 结论：**37.0.0.255130 相对 36.6.3 没有 BG 数值/卡面改动**，变化集中在“换了赛季的池子成员、
> 卡表范围（288 张旧卡不再出现在 37 CardDefs 中）、以及 36.6.3 之后的客户端标签/文本微调”。
> 这正是“数值按最新版本记录”的落地结果——不是没做，而是两版数值确实相同。

### 6.3 池子与轮换（37 最新池子 vs 36.6.3 池子）

| 池子 | 36.6.3 | 37.0.0 | 差分（新增/移除，见 `changed_fields.pools.detail`） |
|---|---:|---:|---|
| minion | 245 | **277** | 37 原始池文件 273（+33/−5，其中 12 张为 7 级池成员同时打标），再按 AT Dark Paradox 机制 −1 base +5 形态（§4.11） |
| tier7 | 12 | 13 | +1（`BG27_514`） |
| hero | 116 | 118 | +2（`BG22_HERO_007` Queen Azshara、`BG23_HERO_304` Lady Vashj） |
| spell | 70 | 73 | +3（原始池文件 76；剔除 3 张 Duos-only 后 73，§2.4） |
| trinket | 236 | 236 | 0（T2 继承上游成员） |
| timewarp | 253 | 253 | 0（T2 继承上游成员） |

池内随从判定链（Rust `flow.rs`）：`pools.minion || pools.tier7` → 等级过滤 →
`races/assoc` 大厅过滤 → `strict_pool_tag`（`pool_tag<=1`）。T3 精确继承 `pool_tag` 后，
`pools.minion && pool_tag<=1` = **276**（唯一被 strict 过滤的是 `BG25_013`，AT tag=2）；
`reachable` 变 **26** 张（池内新成员变 true；Dark Paradox base 由 true 变 false）。

### 6.4 字段口径差异（按 kind）

| 字段 | 变化数 | 按 kind | 原因（非数据错误） |
|---|---:|---|---|
| `kind` | 1 | quest 1 | `BG24_Quest_328`：37 数据是任务（Quest 文本+goal），上游归 spell |
| `name_zh` | 1 | tavern_spell 1 | `BG34_Trinket_2nd_Spell`：上游占位名 `废案`，`card_zhcn` 为实名 |
| `cost` | 1989 | minion 1989 | 37 随从 `cost=3`（购买价），上游写 0；Rust 引擎随从价由 `RulesConfig.buy_cost=3` 决定，**不消费该字段** |
| `races` | 1 | trinket_lesser 1 | `BG32_MagicItem_416`：上游 bundle 给了 race=MURLOC，37 饰品数据无 `card_race` |
| `assoc` | 0 | — | 与上游 3695/3695 一致（T3 继承顺序） |
| `lobby_req` | 0 | — | 与上游 3695/3695 一致（59 张 T3 继承，含 Aberration 门控） |
| `keywords` | 1521 | minion 1020、trinket_greater 182、trinket_lesser 160、hero_power 70、quest_reward 49、quest 13、tavern_spell 13、spell 12、dark_gift 2 | 主因：上游 `TRIGGER_VISUAL` 1314、`AURA` 155、`DISCOVER` 29 等 37 无来源标签被省略；另有文本规则新增/AT 标签缺失（`+CHOOSE_ONE 11`/`+END_OF_TURN 14`/`+START_OF_COMBAT 5` 等） |
| `pools` | 37 | minion 32、hero 2、tavern_spell 3 | 37 最新池子（§6.3）；Duos-only 剔除 + Dark Paradox 特例后，仅剩赛季轮换差异 |
| `pool_tag` | **0** | — | T3 精确继承 AT 客户端原值（§4.10）后与上游逐卡一致 |
| `reachable` | 26 | minion 21、hero 2、tavern_spell 3 | 同上；minion +1 = Dark Paradox base（AT=true、产物=false） |
| `text` | 7 | minion 5、spell 1、trinket_greater 1 | 见下表“文本边界 7 张” |
| `text_alt` | 144 | minion 93、hero_power 19、trinket 22、tavern_spell 7、spell 3 | 37 数据用 `@` 显式分隔多段文本，本映射正确拆出，上游旧算法未拆（属**增强**） |
| `text_alt_zh` | 1 | spell 1 | `BG_OldGod` 的 `{5}` 占位符指向卡 id，37 数据无解（上游把 id 嵌进文本） |

**文本边界 7 张（英文）**：

| id | 差异 | 说明 |
|---|---|---|
| `BG25_HERO_100pt` | `0` → `0 0` | 原文是 `{0}\n{1}` 两个占位符 |
| `BG28_597`/`_G` | 多 `(0)` | 37 文本含 `(@)` 进度计数器，上游 bundle 省略了该段 |
| `BG30_Trinket_2nd` | 上游 `...8 The second Trinket Shop...` 粘连 → 本映射拆成 `text`+`text_alt` | 上游拆分算法失效，本映射更正确 |
| `BG34_639_G` | 上游残留 `(2 |4(turn, turns) left!)` → 本映射解析为 `(2 turns left!)` | 本映射更正确 |
| `BG36_523` | `1 turns` → `1 turn` | 复数按数字判定 |
| `BG_OldGod` | 上游 `130610`（bundle 已代入卡 id）→ 本映射 `0` | `{5}` 占位符无 `script_data_num_6` 来源 |

### 6.5 交叉验证质量（映射可信度证据）

| 指标 | 结果 |
|---|---|
| 数值字段（name/tier/atk/hp/armor/golden/normal/hero_power/buddy/spellcraft/quest_goal/reward_card） | 12 项全部 3695/3695 |
| `races` 集合 | 3694/3695（仅上述 trinket 1 张） |
| `assoc` / `lobby_req` / `tw_types` 集合 | 3695/3695 |
| `pool_tag` | 3695/3695（T3 精确继承，§4.10） |
| `pools` 集合 | 3658/3695（37 张赛季轮换 + Dark Paradox 特例，§6.3） |
| 英文 `text` | 3688/3695（99.81%） |
| 中文 `text_zh`（双方非空） | 3515/3515（100%） |
| 行为关键词 flag 映射 | BATTLECRY/DEATHRATTLE/TAUNT/WINDFURY/MAGNETIC/VENOMOUS/POISONOUS/AVENGE/BACON_RALLY/QUEST 全部 **fp=0** |

---

## 7. 字段覆盖率（3695 映射卡中非默认值张数）

| 字段 | 张数 | 字段 | 张数 |
|---|---:|---|---:|
| `races` | 2005 | `assoc` | 398 |
| `keywords` | 1626 | `pools` | 957 |
| `pool_tag`（非 0） | 274 | — | — |
| `golden` | 1183 | `normal` | 1171 |
| `text_zh` | 3515 | `text_alt` | 152 |
| `text_alt_zh` | 121 | `lobby_req` | 59 |
| `hero_power` | 118 | `buddy` | 109 |
| `spellcraft` | 70 | `spellcraft_spell` | 69 |
| `quest_goal` | 42 | `reward_card` | 5 |
| `window` | 47 | `prize_tier` | 32 |
| `tw_types` | 93 | `tw_weight` | 143 |
| `tw_min_minions` | 3 | `pool_tag`（非 0） | 274 |

---

## 8. compat 条目（36.6.3 独有卡）

**为什么必须保留（panic 证据）**：上游 Rust 引擎启动即构建脚本注册表：

- `src/script.rs:413-424`：`registry()` 对 `crate::content::all_scripts()` 的每个 id 执行
  `let c = d.id(id);`；
- `src/cards.rs:397-406`：`pub fn id(&self, id: &str) -> CardId` →
  `self.find(id).unwrap_or_else(|| panic!("card id not in database: {id}"))`。

37 数据没有的 36.6.3 卡若直接消失，脚本注册会在启动时 panic（`cargo run`/测试全部起不来）。
compat 条目按“字段原样、移出池子”保留：

- 条目数 **288**（按 kind 见 §6.1），`pools=[]`、`pool_tag=0`、`reachable=false`；
- 1266 个注册脚本 id + 其它代码引用 id（并集 **1290**，§9）全部可解析，**0 missing**；
- 影响：`registry()` 对 compat 卡也注册脚本，但这些卡不会进入任何池子/酒馆/发现池，因此脚本
  永不触发（它们在上游 36.6.3 里也已经不在池子中，`removed_by_pool` 为空）——**无对局行为影响**，
  只占表空间；`CardId` 表序与上游一致（§6.1）；
- 收敛策略（P1 内容移植）：等 fork 的 content 脚本按 37 卡表清理后，可改为“只保留仍被脚本/测试
  引用的 id”或按 `at_scripted_ids.json` 生成最小 compat 集；在此之前保持全量 288 最安全
  （Rust 测试 `tests/*.rs` 也引用大量旧 id，例如 `minion(&mut g,0,"BG36_360t4")`）。

---

## 9. 上游脚本 id 清单（`data/p2/at_scripted_ids.json`）

从上游 Rust 源码（只读）正则抽取、并全部在 `cards_37.json` 中验证可解析：

| 分类 | 抽取方式 | 唯一 id 数 |
|---|---|---:|
| `registration` | `crates/taverngym/src/content/*.rs` 注册元组首元素 `("ID", Script)` | 1266 |
| `registration_const` | 注册位置用 `&str` 常量（解析常量值） | 19 |
| `cardid` | 任意 `src/**/*.rs` 的 `cardid!("ID")` / `cardid!(CONST)` | 83 |
| `db_id` | 任意 `src/**/*.rs` 的 `.id("ID")`（含 `cards.rs/engine.rs/recruit.rs` 等） | 36 |
| **并集** | — | **1290** |
| 不可解析 | `missing` | **0** |
| `content_literal`（保守超集） | content/*.rs 里所有像卡 id 的字符串字面量 | 1377（全部可解析） |

非卡牌常量（如 `TargetSpec` 的 `ANY`）已排除，`unresolved_const_idents=[]`。
该文件同时供内容任务参考（哪些卡需要脚本）。

---

## 10. 局限与未映射字段（明确不做，不编造）

| 项 | 处理 | 影响 |
|---|---|---|
| Duos-only 卡（3 张池法术） | 生成器强制移出单人池（§2.4），不入 `pools`/`reachable` | 单人模式本就不应出现；双人模式数据管线不在本迁移范围 |
| AT 机制元数据（`pool_tag`/`lobby_req`/`assoc` 顺序/`window` 等） | T3 从 36.6.3 继承（§4.10），非 37 官方数据 | 这些是 AT 机制实现依赖的客户端 tag；37 官方 CardDefs 不提供。若后续拿到 37 hsdata 原始 tag，可替换为 37 值 |
| Dark Paradox base/形态的池归属 | 按 AT `flow.rs::PARADOX_VARIANTS` 机制特例（§4.11） | 37 单卡动态机制实现（P1）后可移除特例 |
| 异变 108 / UI 按钮 14 | 不入 `cards_37.json`，登记 `new_cards_37.json` | AutoTavern `CardKind` 无对应取值；异变属于规则层，若 fork 要实现异变需另行设计数据 |
| `TRIGGER_VISUAL` / `AURA` / `DISCOVER` / 旧标签 | 省略 | 仅影响展示型“按机制筛池”过滤；引擎行为由脚本决定 |
| `lobby_req` 的 ABERRATION 门控 | 19 张共享卡 T2 继承 | 37 数据无 `subset_aberration`；37 新增卡无来源 |
| `pools.trinket` / `pools.timewarp` | T2 继承 36.6.3 成员 | 37 数据没有“饰品当前可提供/时间扭曲轮换视图”；若 37 又调整了轮换，需等 hsdata 视图数据 |
| `window`（黑暗赠礼回合窗）、`prize_tier`、`tw_*` | T2 继承 | 37 数据无对应 tag；36.6.3 之后若有暗改无法感知 |
| 多段变体（>2 段） | 上游 schema 只有一段 `text_alt` | 映射集内没有 >2 段的卡（154 张两段，全部可表达） |
| `{5}` 等指向卡 id 的占位符 | 渲染为 `0` | 37 数据无 `script_data_num_6`；仅 1 张（`BG_OldGod`） |
| 无前置数字的 `|4(...)` | 按复数 | 37 数据无法判定单复数（当前数据全部有前置数字） |
| `name_zh` 的旧快照差异 | 用 `card_zhcn` 主源 + 缺失补上游 | 名字跨版本极少变动；`text_zh` 已按 §4.8 对齐 |
| compat 条目文本 | 除 `@` 变体分隔符外**原样保留上游** | 上游 36.6.3 残留的 `{0}` 占位符/`[x]` 名字（如 `BG_BT_258`、`BGDUO_HERO_100p`）不修，保持逐字一致；仅 `JAIL_800hp2`（36.6.3 唯一带 `@` 的卡）拆成 `text`+`text_alt`（§2.4）；映射卡 0 残留（无 `@`/`{N}`/`|4(`/标记/下划线/换行） |
| 规则/赛季参数（饰品价格、黑暗赠礼槽位、池子权重、伙伴规则等） | **不在本次范围** | 这些在 Rust `RulesConfig`/content，不在 `cards.json`；37 数据不提供 |

---

## 11. 交接事项

### 11.1 给 Rust fork（`rust/`，另一 teammate）

1. 用 `data/p2/cards_37.json` 替换 `crates/taverngym/data/cards.json`（文件名/路径按 fork 的
   重命名调整）；**id 集合与表序不变**，`CardDb.fingerprint` 不变。
2. 需要同步的硬编码（否则 `cargo test` 红，属预期而非数据错误）：
   - `src/lib.rs`：`pub const GAME_VERSION: &str = "36.6.3.253932"` → `"37.0.0.255130"`；
     `SERVER_RULES_VERSION` → `"37.0.0"`；lib.rs `#[cfg(test)]` 内对这两个常量的字面量断言同步改；
   - `src/cards.rs::tests::pool_counts_match_bundle`：池子计数断言从
     `minion 245 / hero 116 / spell 70 / trinket 236` → **`277 / 118 / 73 / 236`**
     （minion=277 含 Dark Paradox 5 形态、不含 base，见 §4.11；spell=73 已剔除 3 张 Duos-only，
     见 §2.4）；
   - `src/cards.rs::tests::loads_and_links_golden`：`client_version == GAME_VERSION` 随之满足；
     该用例其余断言（`BG25_001` tier/atk/hp/taunt/reborn/undead/minion 池/golden atk=4）在 37
     数据下仍成立；`all_races_sentinel`（`BG36_360t3` 为 ALL）也成立。
   - `tests/mechanics.rs::pool_tag_rule_excludes_rot_hide_gnoll_by_default`：`eligible` 断言
     `244`（36.6.3 口径）需改为 **276**（`pools.minion && pool_tag<=1`，即 277−`BG25_013`）；
     `BG25_013` 的 `pool_tag` 已恢复 2（T3 继承），默认被过滤、`strict_pool_tag=false` 时会回到
     Undead 大厅——测试语义不变；
   - `tests/mechanics.rs::lobby_without_forced_aberrations` /
     `aberration_subset_needs_aberrations_in_the_lobby`：Dark Paradox 5 形态入池后
     `forms==1` 成立；`lobby_req`（59 张，T3 继承）保证无 Aberration 大厅不出现
     Aberration 子集饰品/法术（`BG36_371`/`BG36_301t`/`BG36_303` 等）。
3. 37 卡表范围变化（288 张旧卡仅在 compat 中、无池子）不影响启动与对局；若 fork 后续清理
   content 脚本，可按 `at_scripted_ids.json` 收紧 compat 集。
4. `meta.client_version/server_patch` 已是 37.0.0 值，`RawMeta` 直接可用。

### 11.2 给内容任务

- `data/p2/new_cards_37.json`：37 独有、schema 不收录的 **122** 个 id（108 异变 + 14 按钮），
  含 id/dbf/card_type/name/reason——37.0.0 **没有新增可玩卡**，不需要新卡脚本；
- `data/p2/at_scripted_ids.json`：上游 1290 个“被脚本/代码引用”的 id 及分类，可直接当
  “哪些卡需要脚本”的清单；
- 若内容任务要覆盖异变机制，需要新的数据载体（当前 `cards_37.json` 无法表达）。

---

## 12. 复现与验收清单

```text
[x] python3 tools/p2_data/gen_carddb_37.py            # 退出码 0，写出 data/p2/*（本机约 0.5–1.1s）
[x] python3 tools/p2_data/gen_carddb_37.py --check    # "byte-identical / meta/计数/脚本 id 校验通过"
[x] python3 tools/p2_data/gen_carddb_37.py --report   # 打印本文所有计数/差分/脚本 id 数字
[x] python3 -m pytest tests/test_p2_data.py -q        # 27 passed
[x] 两次运行 byte-identical（测试内 subprocess 双跑 + 比对入库产物）
[x] 上游脚本 id 1290 个全部可解析（missing=[]）
[x] 数值字段 vs 36.6.3：12 项全部 3695/3695 一致
[x] 单人池：minion **277**（Dark Paradox 5 形态入池/base 不入池）/ spell 73（3 张 Duos-only 已剔除）/
    hero 118 / trinket 236 / tier7 13
[x] T3 机制元数据：pool_tag 3695/3695、lobby_req 59/59、assoc 3695/3695 与 36.6.3 逐卡一致；
    `pools.minion && pool_tag<=1` = 276（BG25_013 tag=2）
[x] Dark Paradox：base `BG36_360` pools=[]/reachable=false；5 形态 pools=['minion']/tier 2/5/4/3/6
[x] 全卡库文本 0 个 `@` 残留（compat 的 JAIL_800hp2 已拆分修复）
```

数据层结论：**37.0.0.255130 的 AutoTavern schema 数据已就绪（3983 卡，脚本 id 0 缺失）**；
36.6.3→37.0.0 没有数值改动，变化全部是“卡表范围 + 赛季池子 + 文本/标签口径”，且所有变化均
在 `MANIFEST.diff_vs_at_36_6_3` 中可逐卡复算。
