# CardDefs 权威证据表（第 2 轮不确定卡审计）

> 生成时间: 2026-10-19T01:13:29+00:00 ｜ 脚本: `tmp_255130/carddefs_authority.py`（只读）
> 官方数据: `reversed/hsdata_255130/`（tag 255130）；项目数据: `data/`（patch `37.0.0.255130`）
> 本表只报告权威证据与差异，**未修改** `data/` 或引擎。

## 0. 方法

1. 解析官方拆分 CardDefs（`CardDefs.xml` + `CardDefs.Bacon.xml`），逐卡提取 enUS/zhCN 文本、全部 tag（含 `BACON_*` / `TAG_SCRIPT_DATA_NUM_*`）、DBF id 与**文件行号**；
2. 用 `tools/generate_bg_data.py` 的同一套函数（`build_card_info` / `detect_xml_keywords` / `detect_text_keywords` / pool 标志）计算**期望 JSON**；
3. 与当前 `data/*.json` 逐字段对比（仅列差异）；`{i}` 占位符 ↔ `TAG_SCRIPT_DATA_NUM_{i+1}` 对齐检查；
4. 审计分类/引擎状态引用 engine-analyst / diff-harness 台账（只读引用，不重判）。

## 1. 覆盖与结论

| 指标 | 值 |
|------|----|
| 覆盖卡数（含金色/对照） | **42** |
| 分组 | direct(2), c_class(6), dynamic_8(15), deity_split(5), hero_power(3), diff_top(11) |
| 当前 `data/` 与 CardDefs 不一致 | **0** |
| 官方未找到实体 | **0** |

**结论：覆盖卡在当前 `data/` 中的字段与官方 CardDefs 一致（0 处差异）** —— 本清单的差异均为**引擎实现/证据**层，不是数据层。

## 2. 逐卡权威证据

### `BG31_171` — Moonsteel Juggernaut / 月铁毁灭战舰

- 来源: `CardDefs.Bacon.xml` 行 98232；DBF **115666**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=17(MECHANICAL)、tech=6、atk/health=8/8、cost=3、rarity=None、armor=None
- 关键词: ∅；种族身份 tag: ∅；subsets: ['subset_mech']
- ScriptDataNum: {2: 6}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{1}` | 2 | `TAG_SCRIPT_DATA_NUM_2` | 6 | 是 | ok |

**英文全文**

```text
[x]At the end of your turn,
get two {1}/{1} <b>Magnetic</b>
Satellites and improve
this.
```

**中文全文（zhCN）**

```text
在你的回合结束时，获取两张{1}/{1}的<b>磁力</b>卫星并提升此效果。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 342 | `ARTISTNAME` | 0 |
 | 3 | `TAG_SCRIPT_DATA_NUM_2` | 6 |
 | 45 | `HEALTH` | 8 |
 | 47 | `ATK` | 8 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 5 |
 | 200 | `CARDRACE` | 17 |
 | 202 | `CARDTYPE` | 4 |
 | 1429 | `BACON_TRIPLE_UPGRADE_MINION_ID` | 115667 |
 | 1440 | `TECH_LEVEL` | 6 |
 | 1595 | `BACON_SUBSET_MECH` | 1 |
 | 1724 | `1` | 1 |
 | 3744 | `END_OF_TURN_TRIGGER` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 14 个全部匹配）。

**官方机制 tag 未进数据层**（生成器白名单外；数据层无对应字段）

 | enumID | tag | 值 |
 |---|---|---|
 | 1724 | `1` | 1 |
 | 3744 | `END_OF_TURN_TRIGGER` | 1 |

**数据层提示**

- 官方机制 tag 未进数据层（生成器白名单外）: `1(1724)=1`, `END_OF_TURN_TRIGGER(3744)=1`

**审计对齐（engine-analyst / diff-harness）**

- 分类: missing_script（DEFERRED P3）
- 引擎状态: 无脚本；'improve this' 语义无权威定义（wiki Notes 缺失）
- 官方文本 vs 引擎实现: 官方文本 vs 引擎实现不符（未实现）
- 依据: reversed/rea/deferred_primitives.md §P3；DIFF_HARNESS §5.3-B（20 条分歧）
- 缺失证据: 真实 BG Power.log 的 EoT 前后实体数值序列（卫星数量/数值/自身改善步长）
- 处理: 维持 DEFERRED；不猜步长/对象

### `BG28_583` — Geomagus Roogug / 地卜大师鲁古格

- 来源: `CardDefs.Bacon.xml` 行 67026；DBF **104766**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=43(QUILBOAR)、tech=4、atk/health=4/6、cost=3、rarity=None、armor=None
- 关键词: ['divine_shield']；种族身份 tag: ∅；subsets: ['subset_quilboar']
- ScriptDataNum: ∅

**英文全文**

```text
[x]<b>Divine Shield</b>. Whenever a
<b>Blood Gem</b> is played on this,
this plays a <b>Blood Gem</b> on a
__different friendly minion.
```

**中文全文（zhCN）**

```text
<b>圣盾</b>。每当一张<b>鲜血宝石</b>被用于本随从时，本随从对一个不同的友方随从使用一张<b>鲜血宝石</b>。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 32 | `TRIGGER_VISUAL` | 1 |
 | 45 | `HEALTH` | 6 |
 | 47 | `ATK` | 4 |
 | 114 | `ELITE` | 1 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 2 |
 | 200 | `CARDRACE` | 43 |
 | 202 | `CARDTYPE` | 4 |
 | 1429 | `BACON_TRIPLE_UPGRADE_MINION_ID` | 104767 |
 | 1440 | `TECH_LEVEL` | 4 |
 | 1456 | `IS_BACON_POOL_MINION` | 1 |
 | 1845 | `BACON_SUBSET_QUILLBOAR` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 15 个全部匹配）。

**数据层提示**

- CardDefs 无 ScriptDataNum（无参数化数值；若卡面含动态数值，只能走文本字面量/机制通道，见 F-10 P5 缺口）

**审计对齐（engine-analyst / diff-harness）**

- 分类: 池内唯一剩余缺口（触发链证据缺口）
- 引擎状态: 无脚本（DEFERRED）：双互触发无界，官方触发链上限无权威
- 官方文本 vs 引擎实现: 官方文本 vs 引擎实现不符（未实现）+ 规则多解
- 依据: docs/EXACTNESS_STATUS.md §52/§118；docs/FINAL_REPORT.md
- 缺失证据: 官方触发链上限/递归配额证据（或引擎触发链配额原语裁定）
- 处理: DEFERRED；不近似

### `BGS_004` — Wrath Weaver / 愤怒编织者

- 来源: `CardDefs.Bacon.xml` 行 240101；DBF **59670**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=15(DEMON)、tech=1、atk/health=1/3、cost=3、rarity=None、armor=None
- 关键词: ∅；种族身份 tag: ∅；subsets: ['subset_demon']
- ScriptDataNum: {1: 2, 2: 2}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{0}` | 1 | `TAG_SCRIPT_DATA_NUM_1` | 2 | 是 | ok |
 | `{1}` | 2 | `TAG_SCRIPT_DATA_NUM_2` | 2 | 是 | ok |

**英文全文**

```text
After you play a Demon, deal 1 damage to your hero and gain +{0}/+{1}.
```

**中文全文（zhCN）**

```text
在你使用一张恶魔牌后，对你的英雄造成1点伤害并获得+{0}/+{1}。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 2 | `TAG_SCRIPT_DATA_NUM_1` | 2 |
 | 3 | `TAG_SCRIPT_DATA_NUM_2` | 2 |
 | 32 | `TRIGGER_VISUAL` | 1 |
 | 45 | `HEALTH` | 3 |
 | 47 | `ATK` | 1 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 9 |
 | 200 | `CARDRACE` | 15 |
 | 201 | `FACTION` | 3 |
 | 202 | `CARDTYPE` | 4 |
 | 1429 | `BACON_TRIPLE_UPGRADE_MINION_ID` | 59679 |
 | 1440 | `TECH_LEVEL` | 1 |
 | 1456 | `IS_BACON_POOL_MINION` | 1 |
 | 1593 | `BACON_SUBSET_DEMON` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 16 个全部匹配）。

**审计对齐（engine-analyst / diff-harness）**

- 分类: C 类（证据不足 → DEFERRED）
- 引擎状态: 有脚本（+2/+2 Buff）；官方 ScriptDataNum 槽位含义未知
- 官方文本 vs 引擎实现: 文本多解/需日志证据（tag 槽位语义）
- 依据: reversed/rea/dynamic_gap_audit.md §4
- 缺失证据: Power.log 该 tag 含义（是否 enchant 字段）/wiki Notes
- 处理: 维持 DEFERRED；不登记消费槽位

### `BG31_035` — Groundbreaker / 碎地者

- 来源: `CardDefs.Bacon.xml` 行 96377；DBF **114816**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=92(NAGA)、tech=6、atk/health=6/4、cost=3、rarity=None、armor=None
- 关键词: ∅；种族身份 tag: ∅；subsets: ['subset_naga']
- ScriptDataNum: {1: 3, 2: 1}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{0}` | 1 | `TAG_SCRIPT_DATA_NUM_1` | 3 | 否 | NUM_WITHOUT_PLACEHOLDER（脚本可能以卡 id 引用） |
 | `{1}` | 2 | `TAG_SCRIPT_DATA_NUM_2` | 1 | 是 | ok |
 | `{2}` | 3 | `TAG_SCRIPT_DATA_NUM_3` | None | 是 | PLACEHOLDER_WITHOUT_NUM（CardDefs 无该槽位或值为 0） |

**英文全文**

```text
[x]After you play a Naga, gain
+{1}/+{1}. <i>(Improved by
every 3 spells you've cast
this game!)</i>@[x]After you play a Naga,
gain +{1}/+{1}.
<i>(Cast {2}/3 spells
to improve!)</i>
```

**中文全文（zhCN）**

```text
在你使用一张纳迦牌后，获得+{1}/+{1}。<i>（在本局对战中，你每施放3个法术都会提升！）</i>@在你使用一张纳迦牌后，获得+{1}/+{1}。<i>（施放{2}/3个法术即可提升！）</i>
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 342 | `ARTISTNAME` | 0 |
 | 2 | `TAG_SCRIPT_DATA_NUM_1` | 3 |
 | 3 | `TAG_SCRIPT_DATA_NUM_2` | 1 |
 | 32 | `TRIGGER_VISUAL` | 1 |
 | 45 | `HEALTH` | 4 |
 | 47 | `ATK` | 6 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 14 |
 | 200 | `CARDRACE` | 92 |
 | 202 | `CARDTYPE` | 4 |
 | 1429 | `BACON_TRIPLE_UPGRADE_MINION_ID` | 114817 |
 | 1440 | `TECH_LEVEL` | 6 |
 | 1456 | `IS_BACON_POOL_MINION` | 1 |
 | 1724 | `1` | 1 |
 | 2272 | `BACON_SUBSET_NAGA` | 1 |
 | 3047 | `BACON_TRIGGER_XY` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 16 个全部匹配）。

**官方机制 tag 未进数据层**（生成器白名单外；数据层无对应字段）

 | enumID | tag | 值 |
 |---|---|---|
 | 1724 | `1` | 1 |
 | 3047 | `BACON_TRIGGER_XY` | 1 |

**数据层提示**

- TAG_SCRIPT_DATA_NUM_1=3 存在但文本无 {0}（可能被卡 id/内部参数引用）
- 文本占位符 {2} 在 CardDefs 无对应 TAG_SCRIPT_DATA_NUM_3（生成器导出为 None；脚本必须走文本字面量）
- 官方机制 tag 未进数据层（生成器白名单外）: `1(1724)=1`, `BACON_TRIGGER_XY(3047)=1`

**审计对齐（engine-analyst / diff-harness）**

- 分类: C 类（证据不足 → DEFERRED）
- 引擎状态: 有脚本（每 3 法术 improve）；官方 NUM 三槽关系不明
- 官方文本 vs 引擎实现: 文本多解/需日志证据（槽位语义 + 触发链）
- 依据: reversed/rea/dynamic_gap_audit.md §4
- 缺失证据: 官方 tag 槽位语义 + 事件级日志
- 处理: 维持 DEFERRED

### `BG26_174` — Soul Rewinder / 灵魂回溯者

- 来源: `CardDefs.Bacon.xml` 行 42990；DBF **100949**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=15(DEMON)、tech=2、atk/health=4/2、cost=3、rarity=None、armor=None
- 关键词: ∅；种族身份 tag: ∅；subsets: ['subset_demon']
- ScriptDataNum: {3: 2}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{2}` | 3 | `TAG_SCRIPT_DATA_NUM_3` | 2 | 是 | ok |

**英文全文**

```text
After your hero takes damage, rewind it and give this +{2} Health.
```

**中文全文（zhCN）**

```text
在你的英雄
受到伤害后，回溯该伤害并使本随从获得
+{2}生命值。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 342 | `ARTISTNAME` | 0 |
 | 32 | `TRIGGER_VISUAL` | 1 |
 | 45 | `HEALTH` | 2 |
 | 47 | `ATK` | 4 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 9 |
 | 200 | `CARDRACE` | 15 |
 | 202 | `CARDTYPE` | 4 |
 | 1429 | `BACON_TRIPLE_UPGRADE_MINION_ID` | 100950 |
 | 1440 | `TECH_LEVEL` | 2 |
 | 1456 | `IS_BACON_POOL_MINION` | 1 |
 | 1593 | `BACON_SUBSET_DEMON` | 1 |
 | 2889 | `TAG_SCRIPT_DATA_NUM_3` | 2 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 15 个全部匹配）。

**审计对齐（engine-analyst / diff-harness）**

- 分类: C 类（证据不足 → DEFERRED）
- 引擎状态: 有脚本（受伤 rewind + NUM_3 Health）；NUM_1/2 含义未知
- 官方文本 vs 引擎实现: 文本多解/需日志证据（rewind 快照/触发计数）
- 依据: reversed/rea/dynamic_gap_audit.md §4；阶段 1 已按官方 NUM_3 修正脚本
- 缺失证据: Power.log + wiki Notes；rewind 快照字段
- 处理: 维持 DEFERRED（NUM_1/2 不消费）

### `BG35_701` — Brazen Buccaneer / 无耻的海盗

- 来源: `CardDefs.Bacon.xml` 行 188571；DBF **130703**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=23(PIRATE)、tech=5、atk/health=5/6、cost=3、rarity=None、armor=None
- 关键词: ∅；种族身份 tag: ∅；subsets: ['subset_pirate']
- ScriptDataNum: {1: 2, 2: 3}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{0}` | 1 | `TAG_SCRIPT_DATA_NUM_1` | 2 | 是 | ok |
 | `{1}` | 2 | `TAG_SCRIPT_DATA_NUM_2` | 3 | 是 | ok |
 | `{2}` | 3 | `TAG_SCRIPT_DATA_NUM_3` | None | 是 | PLACEHOLDER_WITHOUT_NUM（CardDefs 无该槽位或值为 0） |

**英文全文**

```text
[x]At the end of your turn, give
your left-most Pirate +{0}/+{1}.
Repeat for each card you
played this turn. <i>({2})</i>
```

**中文全文（zhCN）**

```text
在你的回合结束时，使你最左边的海盗获得+{0}/+{1}。在本回合中你每使用过一张牌，重复一次。<i>（重复{2}次）</i>
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 2 | `TAG_SCRIPT_DATA_NUM_1` | 2 |
 | 3 | `TAG_SCRIPT_DATA_NUM_2` | 3 |
 | 45 | `HEALTH` | 6 |
 | 47 | `ATK` | 5 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 7 |
 | 200 | `CARDRACE` | 23 |
 | 202 | `CARDTYPE` | 4 |
 | 1429 | `BACON_TRIPLE_UPGRADE_MINION_ID` | 130704 |
 | 1440 | `TECH_LEVEL` | 5 |
 | 1596 | `BACON_SUBSET_PIRATE` | 1 |
 | 1724 | `1` | 1 |
 | 3744 | `END_OF_TURN_TRIGGER` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 15 个全部匹配）。

**官方机制 tag 未进数据层**（生成器白名单外；数据层无对应字段）

 | enumID | tag | 值 |
 |---|---|---|
 | 1724 | `1` | 1 |
 | 3744 | `END_OF_TURN_TRIGGER` | 1 |

**数据层提示**

- 文本占位符 {2} 在 CardDefs 无对应 TAG_SCRIPT_DATA_NUM_3（生成器导出为 None；脚本必须走文本字面量）
- 官方机制 tag 未进数据层（生成器白名单外）: `1(1724)=1`, `END_OF_TURN_TRIGGER(3744)=1`

**审计对齐（engine-analyst / diff-harness）**

- 分类: C 类（证据不足 → DEFERRED）
- 引擎状态: 有脚本（EoT 按出牌数重复）；槽位无法对齐
- 官方文本 vs 引擎实现: 文本多解/需日志证据（重复次数 vs Buff 值）
- 依据: reversed/rea/dynamic_gap_audit.md §4
- 缺失证据: 官方 tag 语义（重复次数 vs Buff 值）
- 处理: 维持 DEFERRED

### `BG32_822` — Fire-forged Evoker / 火铸唤魔师

- 来源: `CardDefs.Bacon.xml` 行 124401；DBF **120301**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=24(DRAGON)、tech=6、atk/health=8/6、cost=3、rarity=None、armor=None
- 关键词: ['start_of_combat']；种族身份 tag: ∅；subsets: ['subset_dragon']
- ScriptDataNum: {1: 2, 2: 2}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{0}` | 1 | `TAG_SCRIPT_DATA_NUM_1` | 2 | 是 | ok |
 | `{1}` | 2 | `TAG_SCRIPT_DATA_NUM_2` | 2 | 是 | ok |

**英文全文**

```text
[x]<b>Start of Combat:</b> Give your
Dragons +{0}/+{1}.
Improves permanently after
____you cast a Tavern spell.
```

**中文全文（zhCN）**

```text
<b>战斗开始时：</b>使你的龙获得+{0}/+{1}。在你施放一个酒馆法术后永久提升此效果。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 2 | `TAG_SCRIPT_DATA_NUM_1` | 2 |
 | 3 | `TAG_SCRIPT_DATA_NUM_2` | 2 |
 | 32 | `TRIGGER_VISUAL` | 1 |
 | 45 | `HEALTH` | 6 |
 | 47 | `ATK` | 8 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 10 |
 | 200 | `CARDRACE` | 24 |
 | 202 | `CARDTYPE` | 4 |
 | 1429 | `BACON_TRIPLE_UPGRADE_MINION_ID` | 120302 |
 | 1440 | `TECH_LEVEL` | 6 |
 | 1591 | `BACON_SUBSET_DRAGON` | 1 |
 | 1724 | `1` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 16 个全部匹配）。

**官方机制 tag 未进数据层**（生成器白名单外；数据层无对应字段）

 | enumID | tag | 值 |
 |---|---|---|
 | 1724 | `1` | 1 |

**数据层提示**

- 官方机制 tag 未进数据层（生成器白名单外）: `1(1724)=1`

**审计对齐（engine-analyst / diff-harness）**

- 分类: C 类（证据不足 → DEFERRED）
- 引擎状态: 有脚本；官方 Improve 计数公式/金色 tag 关系不明
- 官方文本 vs 引擎实现: 文本多解/需日志证据（公式）
- 依据: reversed/rea/dynamic_gap_audit.md §4
- 缺失证据: 官方 Improve 计数公式 + 金色是否用基础 num；Power.log
- 处理: 维持 DEFERRED

### `BG33_155` — Devout Hellcaller / 虔诚的萨特唤魔者

- 来源: `CardDefs.Bacon.xml` 行 136682；DBF **122586**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=15(DEMON)、tech=3、atk/health=4/4、cost=3、rarity=None、armor=None
- 关键词: ∅；种族身份 tag: ∅；subsets: ['subset_demon']
- ScriptDataNum: {1: 2, 2: 2}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{0}` | 1 | `TAG_SCRIPT_DATA_NUM_1` | 2 | 是 | ok |
 | `{1}` | 2 | `TAG_SCRIPT_DATA_NUM_2` | 2 | 是 | ok |

**英文全文**

```text
After another friendly Demon deals damage, gain +{0}/+{1} permanently.
```

**中文全文（zhCN）**

```text
在另一个友方恶魔造成伤害后，永久获得+{0}/+{1}。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 2 | `TAG_SCRIPT_DATA_NUM_1` | 2 |
 | 3 | `TAG_SCRIPT_DATA_NUM_2` | 2 |
 | 32 | `TRIGGER_VISUAL` | 1 |
 | 45 | `HEALTH` | 4 |
 | 47 | `ATK` | 4 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 9 |
 | 200 | `CARDRACE` | 15 |
 | 202 | `CARDTYPE` | 4 |
 | 1429 | `BACON_TRIPLE_UPGRADE_MINION_ID` | 122587 |
 | 1440 | `TECH_LEVEL` | 3 |
 | 1456 | `IS_BACON_POOL_MINION` | 1 |
 | 1593 | `BACON_SUBSET_DEMON` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 16 个全部匹配）。

**审计对齐（engine-analyst / diff-harness）**

- 分类: C 类（证据不足 → DEFERRED）
- 引擎状态: 有脚本（永久 +2/+2 Buff）；官方 trigger 计数 tag 语义不明
- 官方文本 vs 引擎实现: 文本多解/需日志证据（计数语义）
- 依据: reversed/rea/dynamic_gap_audit.md §4
- 缺失证据: 官方 trigger 计数 tag 语义；Power.log
- 处理: 维持 DEFERRED

### `BG35_921` — Abyssal Bruiser / 深渊打手

- 来源: `CardDefs.Bacon.xml` 行 190137；DBF **130658**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=92(NAGA)、tech=4、atk/health=2/1、cost=3、rarity=None、armor=None
- 关键词: ['divine_shield']；种族身份 tag: ∅；subsets: ['subset_naga']
- ScriptDataNum: {1: 2, 2: 1}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{0}` | 1 | `TAG_SCRIPT_DATA_NUM_1` | 2 | 是 | ok |
 | `{1}` | 2 | `TAG_SCRIPT_DATA_NUM_2` | 1 | 是 | ok |

**英文全文**

```text
[x]<b>Divine Shield</b>
Has +{0}/+{1} for each
Tavern spell you've
cast this game.
```

**中文全文（zhCN）**

```text
<b>圣盾</b>。在本局对战中，你每施放一个酒馆法术，便拥有+{0}/+{1}。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 342 | `ARTISTNAME` | 0 |
 | 2 | `TAG_SCRIPT_DATA_NUM_1` | 2 |
 | 3 | `TAG_SCRIPT_DATA_NUM_2` | 1 |
 | 45 | `HEALTH` | 1 |
 | 47 | `ATK` | 2 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 14 |
 | 200 | `CARDRACE` | 92 |
 | 202 | `CARDTYPE` | 4 |
 | 1429 | `BACON_TRIPLE_UPGRADE_MINION_ID` | 130659 |
 | 1440 | `TECH_LEVEL` | 4 |
 | 1456 | `IS_BACON_POOL_MINION` | 1 |
 | 1724 | `1` | 1 |
 | 2272 | `BACON_SUBSET_NAGA` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 17 个全部匹配）。

**官方机制 tag 未进数据层**（生成器白名单外；数据层无对应字段）

 | enumID | tag | 值 |
 |---|---|---|
 | 1724 | `1` | 1 |

**数据层提示**

- 官方机制 tag 未进数据层（生成器白名单外）: `1(1724)=1`

**审计对齐（engine-analyst / diff-harness）**

- 分类: F-10 8 族动态属性（已迁移 script_data_or_card(3)）
- 引擎状态: 有脚本（动态 atk/health 钩子 + NUM_3 通道）；默认行为不变
- 官方文本 vs 引擎实现: 非文本不符（动态状态/测量口径）
- 依据: docs/EXACTNESS_STATUS.md F-10；reversed/rea/deferred_primitives.md P2b/P5
- 缺失证据: P5: CardDef 缺动态步长（num 为空）→ harness 文本回退表；真实 Power.log 逐事件数值可消除回退
- 处理: 保持默认；不硬套 NUM_3（P2b 反推失败时保留缺口）

### `BG35_921_G` — Abyssal Bruiser / 深渊打手

- 来源: `CardDefs.Bacon.xml` 行 190201；DBF **130659**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=92(NAGA)、tech=4、atk/health=4/2、cost=3、rarity=None、armor=None
- 关键词: ['divine_shield']；种族身份 tag: ∅；subsets: ∅
- ScriptDataNum: {1: 4, 2: 2}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{0}` | 1 | `TAG_SCRIPT_DATA_NUM_1` | 4 | 是 | ok |
 | `{1}` | 2 | `TAG_SCRIPT_DATA_NUM_2` | 2 | 是 | ok |

**英文全文**

```text
[x]<b>Divine Shield</b>
Has +{0}/+{1} for each
Tavern spell you've
cast this game.
```

**中文全文（zhCN）**

```text
<b>圣盾</b>。在本局对战中，你每施放一个酒馆法术，便拥有+{0}/+{1}。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 2 | `TAG_SCRIPT_DATA_NUM_1` | 4 |
 | 3 | `TAG_SCRIPT_DATA_NUM_2` | 2 |
 | 45 | `HEALTH` | 2 |
 | 47 | `ATK` | 4 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 14 |
 | 200 | `CARDRACE` | 92 |
 | 202 | `CARDTYPE` | 4 |
 | 1440 | `TECH_LEVEL` | 4 |
 | 1471 | `BACON_TRIPLED_BASE_MINION_ID` | 130658 |
 | 1724 | `1` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 15 个全部匹配）。

**官方机制 tag 未进数据层**（生成器白名单外；数据层无对应字段）

 | enumID | tag | 值 |
 |---|---|---|
 | 1724 | `1` | 1 |

**数据层提示**

- 官方机制 tag 未进数据层（生成器白名单外）: `1(1724)=1`

**审计对齐（engine-analyst / diff-harness）**

- 分类: F-10 8 族动态属性（已迁移 script_data_or_card(3)）
- 引擎状态: 有脚本（动态 atk/health 钩子 + NUM_3 通道）；默认行为不变
- 官方文本 vs 引擎实现: 非文本不符（动态状态/测量口径）
- 依据: docs/EXACTNESS_STATUS.md F-10；reversed/rea/deferred_primitives.md P2b/P5
- 缺失证据: P5: CardDef 缺动态步长（num 为空）→ harness 文本回退表；真实 Power.log 逐事件数值可消除回退
- 处理: 保持默认；不硬套 NUM_3（P2b 反推失败时保留缺口）

### `BG35_342` — Falling Sky Golem / 坠落的飞天魔像

- 来源: `CardDefs.Bacon.xml` 行 187205；DBF **130798**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=17(MECHANICAL)、tech=6、atk/health=4/2、cost=3、rarity=None、armor=None
- 关键词: ['divine_shield']；种族身份 tag: ∅；subsets: ['subset_mech']
- ScriptDataNum: {1: 4, 2: 2}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{0}` | 1 | `TAG_SCRIPT_DATA_NUM_1` | 4 | 是 | ok |
 | `{1}` | 2 | `TAG_SCRIPT_DATA_NUM_2` | 2 | 是 | ok |

**英文全文**

```text
<b>Divine Shield</b>. Has +{0}/+{1} for each <b>Deathrattle</b> you've triggered this game <i>(wherever this is).</i>
```

**中文全文（zhCN）**

```text
<b>圣盾</b>。在本局对战中，你每触发过一次<b>亡语</b>，便拥有+{0}/+{1}<i>（无论本随从在哪）。</i>
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 342 | `ARTISTNAME` | 0 |
 | 2 | `TAG_SCRIPT_DATA_NUM_1` | 4 |
 | 3 | `TAG_SCRIPT_DATA_NUM_2` | 2 |
 | 45 | `HEALTH` | 2 |
 | 47 | `ATK` | 4 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 5 |
 | 200 | `CARDRACE` | 17 |
 | 202 | `CARDTYPE` | 4 |
 | 1429 | `BACON_TRIPLE_UPGRADE_MINION_ID` | 130799 |
 | 1440 | `TECH_LEVEL` | 6 |
 | 1456 | `IS_BACON_POOL_MINION` | 1 |
 | 1595 | `BACON_SUBSET_MECH` | 1 |
 | 1724 | `1` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 17 个全部匹配）。

**官方机制 tag 未进数据层**（生成器白名单外；数据层无对应字段）

 | enumID | tag | 值 |
 |---|---|---|
 | 1724 | `1` | 1 |

**数据层提示**

- 官方机制 tag 未进数据层（生成器白名单外）: `1(1724)=1`

**审计对齐（engine-analyst / diff-harness）**

- 分类: F-10 8 族动态属性（已迁移 script_data_or_card(3)）
- 引擎状态: 有脚本（动态 atk/health 钩子 + NUM_3 通道）；默认行为不变
- 官方文本 vs 引擎实现: 非文本不符（动态状态/测量口径）
- 依据: docs/EXACTNESS_STATUS.md F-10；reversed/rea/deferred_primitives.md P2b/P5
- 缺失证据: P5: CardDef 缺动态步长（num 为空）→ harness 文本回退表；真实 Power.log 逐事件数值可消除回退
- 处理: 保持默认；不硬套 NUM_3（P2b 反推失败时保留缺口）

### `BG35_342_G` — Falling Sky Golem / 坠落的飞天魔像

- 来源: `CardDefs.Bacon.xml` 行 187272；DBF **130799**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=17(MECHANICAL)、tech=6、atk/health=8/4、cost=3、rarity=None、armor=None
- 关键词: ['divine_shield']；种族身份 tag: ∅；subsets: ∅
- ScriptDataNum: {1: 8, 2: 4}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{0}` | 1 | `TAG_SCRIPT_DATA_NUM_1` | 8 | 是 | ok |
 | `{1}` | 2 | `TAG_SCRIPT_DATA_NUM_2` | 4 | 是 | ok |

**英文全文**

```text
<b>Divine Shield</b>. Has +{0}/+{1} for each <b>Deathrattle</b> you've triggered this game <i>(wherever this is).</i>
```

**中文全文（zhCN）**

```text
<b>圣盾</b>。在本局对战中，你每触发过一次<b>亡语</b>，便拥有+{0}/+{1}<i>（无论本随从在哪）。</i>
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 2 | `TAG_SCRIPT_DATA_NUM_1` | 8 |
 | 3 | `TAG_SCRIPT_DATA_NUM_2` | 4 |
 | 45 | `HEALTH` | 4 |
 | 47 | `ATK` | 8 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 5 |
 | 200 | `CARDRACE` | 17 |
 | 202 | `CARDTYPE` | 4 |
 | 1440 | `TECH_LEVEL` | 6 |
 | 1471 | `BACON_TRIPLED_BASE_MINION_ID` | 130798 |
 | 1724 | `1` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 15 个全部匹配）。

**官方机制 tag 未进数据层**（生成器白名单外；数据层无对应字段）

 | enumID | tag | 值 |
 |---|---|---|
 | 1724 | `1` | 1 |

**数据层提示**

- 官方机制 tag 未进数据层（生成器白名单外）: `1(1724)=1`

**审计对齐（engine-analyst / diff-harness）**

- 分类: F-10 8 族动态属性（已迁移 script_data_or_card(3)）
- 引擎状态: 有脚本（动态 atk/health 钩子 + NUM_3 通道）；默认行为不变
- 官方文本 vs 引擎实现: 非文本不符（动态状态/测量口径）
- 依据: docs/EXACTNESS_STATUS.md F-10；reversed/rea/deferred_primitives.md P2b/P5
- 缺失证据: P5: CardDef 缺动态步长（num 为空）→ harness 文本回退表；真实 Power.log 逐事件数值可消除回退
- 处理: 保持默认；不硬套 NUM_3（P2b 反推失败时保留缺口）

### `BG36_524` — Maritime Extortionist / 海上勒索师

- 来源: `CardDefs.Bacon.xml` 行 208823；DBF **132764**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=23(PIRATE)、tech=4、atk/health=7/7、cost=3、rarity=None、armor=None
- 关键词: ∅；种族身份 tag: ∅；subsets: ['subset_pirate']
- ScriptDataNum: {1: 7, 2: 7}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{0}` | 1 | `TAG_SCRIPT_DATA_NUM_1` | 7 | 是 | ok |
 | `{1}` | 2 | `TAG_SCRIPT_DATA_NUM_2` | 7 | 是 | ok |

**英文全文**

```text
[x]Has +{0}/+{1} for each
Golden minion you've
played this game
<i>(wherever this is)</i>.
```

**中文全文（zhCN）**

```text
在本局对战中，你每使用一张金色随从牌，便拥有+{0}/+{1}<i>（无论本随从在哪）</i>。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 342 | `ARTISTNAME` | 0 |
 | 2 | `TAG_SCRIPT_DATA_NUM_1` | 7 |
 | 3 | `TAG_SCRIPT_DATA_NUM_2` | 7 |
 | 45 | `HEALTH` | 7 |
 | 47 | `ATK` | 7 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 7 |
 | 200 | `CARDRACE` | 23 |
 | 202 | `CARDTYPE` | 4 |
 | 1429 | `BACON_TRIPLE_UPGRADE_MINION_ID` | 132765 |
 | 1440 | `TECH_LEVEL` | 4 |
 | 1456 | `IS_BACON_POOL_MINION` | 1 |
 | 1596 | `BACON_SUBSET_PIRATE` | 1 |
 | 1724 | `1` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 16 个全部匹配）。

**官方机制 tag 未进数据层**（生成器白名单外；数据层无对应字段）

 | enumID | tag | 值 |
 |---|---|---|
 | 1724 | `1` | 1 |

**数据层提示**

- 官方机制 tag 未进数据层（生成器白名单外）: `1(1724)=1`

**审计对齐（engine-analyst / diff-harness）**

- 分类: F-10 8 族动态属性（已迁移 script_data_or_card(3)）
- 引擎状态: 有脚本（动态 atk/health 钩子 + NUM_3 通道）；默认行为不变
- 官方文本 vs 引擎实现: 非文本不符（动态状态/测量口径）
- 依据: docs/EXACTNESS_STATUS.md F-10；reversed/rea/deferred_primitives.md P2b/P5
- 缺失证据: P5: CardDef 缺动态步长（num 为空）→ harness 文本回退表；真实 Power.log 逐事件数值可消除回退
- 处理: 保持默认；不硬套 NUM_3（P2b 反推失败时保留缺口）

### `BG36_524_G` — Maritime Extortionist / 海上勒索师

- 来源: `CardDefs.Bacon.xml` 行 208883；DBF **132765**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=23(PIRATE)、tech=4、atk/health=14/14、cost=3、rarity=None、armor=None
- 关键词: ∅；种族身份 tag: ∅；subsets: ∅
- ScriptDataNum: {1: 14, 2: 14}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{0}` | 1 | `TAG_SCRIPT_DATA_NUM_1` | 14 | 是 | ok |
 | `{1}` | 2 | `TAG_SCRIPT_DATA_NUM_2` | 14 | 是 | ok |

**英文全文**

```text
[x]Has +{0}/+{1} for each
Golden minion you've
played this game
<i>(wherever this is)</i>.
```

**中文全文（zhCN）**

```text
在本局对战中，
你每使用一张金色随从牌，便拥有+{0}/+{1}<i>（无论本随从在哪）</i>。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 2 | `TAG_SCRIPT_DATA_NUM_1` | 14 |
 | 3 | `TAG_SCRIPT_DATA_NUM_2` | 14 |
 | 45 | `HEALTH` | 14 |
 | 47 | `ATK` | 14 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 7 |
 | 200 | `CARDRACE` | 23 |
 | 202 | `CARDTYPE` | 4 |
 | 1440 | `TECH_LEVEL` | 4 |
 | 1471 | `BACON_TRIPLED_BASE_MINION_ID` | 132764 |
 | 1724 | `1` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 14 个全部匹配）。

**官方机制 tag 未进数据层**（生成器白名单外；数据层无对应字段）

 | enumID | tag | 值 |
 |---|---|---|
 | 1724 | `1` | 1 |

**数据层提示**

- 官方机制 tag 未进数据层（生成器白名单外）: `1(1724)=1`

**审计对齐（engine-analyst / diff-harness）**

- 分类: F-10 8 族动态属性（已迁移 script_data_or_card(3)）
- 引擎状态: 有脚本（动态 atk/health 钩子 + NUM_3 通道）；默认行为不变
- 官方文本 vs 引擎实现: 非文本不符（动态状态/测量口径）
- 依据: docs/EXACTNESS_STATUS.md F-10；reversed/rea/deferred_primitives.md P2b/P5
- 缺失证据: P5: CardDef 缺动态步长（num 为空）→ harness 文本回退表；真实 Power.log 逐事件数值可消除回退
- 处理: 保持默认；不硬套 NUM_3（P2b 反推失败时保留缺口）

### `BG25_008` — Eternal Knight / 永恒骑士

- 来源: `CardDefs.Bacon.xml` 行 33767；DBF **95261**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=11(UNDEAD)、tech=2、atk/health=4/2、cost=3、rarity=None、armor=None
- 关键词: ∅；种族身份 tag: ∅；subsets: ['subset_undead']
- ScriptDataNum: {1: 4, 2: 2}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{0}` | 1 | `TAG_SCRIPT_DATA_NUM_1` | 4 | 是 | ok |
 | `{1}` | 2 | `TAG_SCRIPT_DATA_NUM_2` | 2 | 是 | ok |

**英文全文**

```text
[x]Has +{0}/+{1} for each friendly
Eternal Knight that died this
__game <i>(wherever this is)</i>.
```

**中文全文（zhCN）**

```text
在本局对战中，每有一个友方永恒骑士死亡，便拥有+{0}/+{1}<i>（无论本随从在哪）</i>。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 2 | `TAG_SCRIPT_DATA_NUM_1` | 4 |
 | 3 | `TAG_SCRIPT_DATA_NUM_2` | 2 |
 | 45 | `HEALTH` | 2 |
 | 47 | `ATK` | 4 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 1 |
 | 200 | `CARDRACE` | 11 |
 | 202 | `CARDTYPE` | 4 |
 | 1429 | `BACON_TRIPLE_UPGRADE_MINION_ID` | 95262 |
 | 1440 | `TECH_LEVEL` | 2 |
 | 1456 | `IS_BACON_POOL_MINION` | 1 |
 | 2347 | `BACON_SUBSET_UNDEAD` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 16 个全部匹配）。

**审计对齐（engine-analyst / diff-harness）**

- 分类: F-10 8 族动态属性（已迁移 script_data_or_card(3)）
- 引擎状态: 有脚本（动态 atk/health 钩子 + NUM_3 通道）；默认行为不变
- 官方文本 vs 引擎实现: 非文本不符（动态状态/测量口径）
- 依据: docs/EXACTNESS_STATUS.md F-10；reversed/rea/deferred_primitives.md P2b/P5
- 缺失证据: P5: CardDef 缺动态步长（num 为空）→ harness 文本回退表；真实 Power.log 逐事件数值可消除回退
- 处理: 保持默认；不硬套 NUM_3（P2b 反推失败时保留缺口）

### `BG25_008_G` — Eternal Knight / 永恒骑士

- 来源: `CardDefs.Bacon.xml` 行 33866；DBF **95262**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=11(UNDEAD)、tech=2、atk/health=8/4、cost=3、rarity=None、armor=None
- 关键词: ∅；种族身份 tag: ∅；subsets: ∅
- ScriptDataNum: {1: 8, 2: 4}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{0}` | 1 | `TAG_SCRIPT_DATA_NUM_1` | 8 | 是 | ok |
 | `{1}` | 2 | `TAG_SCRIPT_DATA_NUM_2` | 4 | 是 | ok |

**英文全文**

```text
[x]Has +{0}/+{1} for each friendly
Eternal Knight that died this
__game <i>(wherever this is)</i>.
```

**中文全文（zhCN）**

```text
在本局对战中，每有一个友方永恒骑士死亡，便拥有+{0}/+{1}<i>（无论本随从在哪）</i>。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 2 | `TAG_SCRIPT_DATA_NUM_1` | 8 |
 | 3 | `TAG_SCRIPT_DATA_NUM_2` | 4 |
 | 45 | `HEALTH` | 4 |
 | 47 | `ATK` | 8 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 1 |
 | 200 | `CARDRACE` | 11 |
 | 202 | `CARDTYPE` | 4 |
 | 1440 | `TECH_LEVEL` | 2 |
 | 1471 | `BACON_TRIPLED_BASE_MINION_ID` | 95261 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 14 个全部匹配）。

**审计对齐（engine-analyst / diff-harness）**

- 分类: F-10 8 族动态属性（已迁移 script_data_or_card(3)）
- 引擎状态: 有脚本（动态 atk/health 钩子 + NUM_3 通道）；默认行为不变
- 官方文本 vs 引擎实现: 非文本不符（动态状态/测量口径）
- 依据: docs/EXACTNESS_STATUS.md F-10；reversed/rea/deferred_primitives.md P2b/P5
- 缺失证据: P5: CardDef 缺动态步长（num 为空）→ harness 文本回退表；真实 Power.log 逐事件数值可消除回退
- 处理: 保持默认；不硬套 NUM_3（P2b 反推失败时保留缺口）

### `BG25_013` — Rot Hide Gnoll / 腐皮豺狼人

- 来源: `CardDefs.Bacon.xml` 行 34481；DBF **95271**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=11(UNDEAD)、tech=1、atk/health=1/4、cost=3、rarity=None、armor=None
- 关键词: ∅；种族身份 tag: ∅；subsets: ['subset_undead']
- ScriptDataNum: ∅

**英文全文**

```text
Has +1 Attack for each friendly minion that died this combat.
```

**中文全文（zhCN）**

```text
在本场战斗中，每有一个友方随从死亡，便拥有+1攻击力。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 45 | `HEALTH` | 4 |
 | 47 | `ATK` | 1 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 1 |
 | 200 | `CARDRACE` | 11 |
 | 202 | `CARDTYPE` | 4 |
 | 1429 | `BACON_TRIPLE_UPGRADE_MINION_ID` | 95272 |
 | 1440 | `TECH_LEVEL` | 1 |
 | 1456 | `IS_BACON_POOL_MINION` | 2 |
 | 2347 | `BACON_SUBSET_UNDEAD` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 14 个全部匹配）。

**数据层提示**

- CardDefs 无 ScriptDataNum（无参数化数值；若卡面含动态数值，只能走文本字面量/机制通道，见 F-10 P5 缺口）

**审计对齐（engine-analyst / diff-harness）**

- 分类: F-10 8 族动态属性（已迁移 script_data_or_card(3)）
- 引擎状态: 有脚本（动态 atk/health 钩子 + NUM_3 通道）；默认行为不变
- 官方文本 vs 引擎实现: 非文本不符（动态状态/测量口径）
- 依据: docs/EXACTNESS_STATUS.md F-10；reversed/rea/deferred_primitives.md P2b/P5
- 缺失证据: P5: CardDef 缺动态步长（num 为空）→ harness 文本回退表；真实 Power.log 逐事件数值可消除回退
- 处理: 保持默认；不硬套 NUM_3（P2b 反推失败时保留缺口）

### `BG25_013_G` — Rot Hide Gnoll / 腐皮豺狼人

- 来源: `CardDefs.Bacon.xml` 行 34535；DBF **95272**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=11(UNDEAD)、tech=1、atk/health=2/8、cost=3、rarity=None、armor=None
- 关键词: ∅；种族身份 tag: ∅；subsets: ∅
- ScriptDataNum: ∅

**英文全文**

```text
Has +2 Attack for each friendly minion that died this combat.
```

**中文全文（zhCN）**

```text
在本场战斗中，每有一个友方随从死亡，便拥有+2攻击力。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 45 | `HEALTH` | 8 |
 | 47 | `ATK` | 2 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 1 |
 | 200 | `CARDRACE` | 11 |
 | 202 | `CARDTYPE` | 4 |
 | 1440 | `TECH_LEVEL` | 1 |
 | 1471 | `BACON_TRIPLED_BASE_MINION_ID` | 95271 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 12 个全部匹配）。

**数据层提示**

- CardDefs 无 ScriptDataNum（无参数化数值；若卡面含动态数值，只能走文本字面量/机制通道，见 F-10 P5 缺口）

**审计对齐（engine-analyst / diff-harness）**

- 分类: F-10 8 族动态属性（已迁移 script_data_or_card(3)）
- 引擎状态: 有脚本（动态 atk/health 钩子 + NUM_3 通道）；默认行为不变
- 官方文本 vs 引擎实现: 非文本不符（动态状态/测量口径）
- 依据: docs/EXACTNESS_STATUS.md F-10；reversed/rea/deferred_primitives.md P2b/P5
- 缺失证据: P5: CardDef 缺动态步长（num 为空）→ harness 文本回退表；真实 Power.log 逐事件数值可消除回退
- 处理: 保持默认；不硬套 NUM_3（P2b 反推失败时保留缺口）

### `BG_TTN_401` — Ancestral Automaton / 星元自动机

- 来源: `CardDefs.Bacon.xml` 行 230198；DBF **108432**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=17(MECHANICAL)、tech=2、atk/health=3/4、cost=3、rarity=None、armor=None
- 关键词: ∅；种族身份 tag: ∅；subsets: ['subset_mech']
- ScriptDataNum: ∅

**英文全文**

```text
[x]Has +3/+2 for each other
Ancestral Automaton you've
summoned this game
<i>(wherever this is)</i>.
```

**中文全文（zhCN）**

```text
在本局对战中，你每召唤过一个其他星元自动机，便拥有+3/+2<i>（无论本随从在哪）</i>。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 342 | `ARTISTNAME` | 0 |
 | 45 | `HEALTH` | 4 |
 | 47 | `ATK` | 3 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 5 |
 | 200 | `CARDRACE` | 17 |
 | 202 | `CARDTYPE` | 4 |
 | 1429 | `BACON_TRIPLE_UPGRADE_MINION_ID` | 108435 |
 | 1440 | `TECH_LEVEL` | 2 |
 | 1595 | `BACON_SUBSET_MECH` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 13 个全部匹配）。

**数据层提示**

- CardDefs 无 ScriptDataNum（无参数化数值；若卡面含动态数值，只能走文本字面量/机制通道，见 F-10 P5 缺口）

**审计对齐（engine-analyst / diff-harness）**

- 分类: F-10 8 族动态属性（已迁移 script_data_or_card(3)）
- 引擎状态: 有脚本（动态 atk/health 钩子 + NUM_3 通道）；默认行为不变
- 官方文本 vs 引擎实现: 非文本不符（动态状态/测量口径）
- 依据: docs/EXACTNESS_STATUS.md F-10；reversed/rea/deferred_primitives.md P2b/P5
- 缺失证据: P5: CardDef 缺动态步长（num 为空）→ harness 文本回退表；真实 Power.log 逐事件数值可消除回退
- 处理: 保持默认；不硬套 NUM_3（P2b 反推失败时保留缺口）

### `BG_TTN_401_G` — Ancestral Automaton / 星元自动机

- 来源: `CardDefs.Bacon.xml` 行 230256；DBF **108435**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=17(MECHANICAL)、tech=2、atk/health=6/8、cost=3、rarity=None、armor=None
- 关键词: ∅；种族身份 tag: ∅；subsets: ∅
- ScriptDataNum: ∅

**英文全文**

```text
[x]Has +6/+4 for each other
Ancestral Automaton you've
summoned this game
<i>(wherever this is)</i>.
```

**中文全文（zhCN）**

```text
在本局对战中，你每召唤过一个其他星元自动机，便拥有+6/+4<i>（无论本随从在哪）</i>。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 342 | `ARTISTNAME` | 0 |
 | 45 | `HEALTH` | 8 |
 | 47 | `ATK` | 6 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 5 |
 | 200 | `CARDRACE` | 17 |
 | 202 | `CARDTYPE` | 4 |
 | 1440 | `TECH_LEVEL` | 2 |
 | 1471 | `BACON_TRIPLED_BASE_MINION_ID` | 108432 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 12 个全部匹配）。

**数据层提示**

- CardDefs 无 ScriptDataNum（无参数化数值；若卡面含动态数值，只能走文本字面量/机制通道，见 F-10 P5 缺口）

**审计对齐（engine-analyst / diff-harness）**

- 分类: F-10 8 族动态属性（已迁移 script_data_or_card(3)）
- 引擎状态: 有脚本（动态 atk/health 钩子 + NUM_3 通道）；默认行为不变
- 官方文本 vs 引擎实现: 非文本不符（动态状态/测量口径）
- 依据: docs/EXACTNESS_STATUS.md F-10；reversed/rea/deferred_primitives.md P2b/P5
- 缺失证据: P5: CardDef 缺动态步长（num 为空）→ harness 文本回退表；真实 Power.log 逐事件数值可消除回退
- 处理: 保持默认；不硬套 NUM_3（P2b 反推失败时保留缺口）

### `BG26_537` — Flourishing Frostling / 缤纷冰灵

- 来源: `CardDefs.Bacon.xml` 行 46357；DBF **101267**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=18(ELEMENTAL)、tech=5、atk/health=2/1、cost=3、rarity=None、armor=None
- 关键词: ∅；种族身份 tag: ∅；subsets: ['subset_elemental']
- ScriptDataNum: {1: 2, 2: 1}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{0}` | 1 | `TAG_SCRIPT_DATA_NUM_1` | 2 | 是 | ok |
 | `{1}` | 2 | `TAG_SCRIPT_DATA_NUM_2` | 1 | 是 | ok |

**英文全文**

```text
[x]Has +{0}/+{1} for each
Elemental you played this
___game <i>(wherever this is)</i>.
```

**中文全文（zhCN）**

```text
在本局对战中，你每使用过一张元素牌，便拥有+{0}/+{1}<i>（无论本随从在哪）</i>。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 2 | `TAG_SCRIPT_DATA_NUM_1` | 2 |
 | 3 | `TAG_SCRIPT_DATA_NUM_2` | 1 |
 | 45 | `HEALTH` | 1 |
 | 47 | `ATK` | 2 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 4 |
 | 200 | `CARDRACE` | 18 |
 | 202 | `CARDTYPE` | 4 |
 | 1429 | `BACON_TRIPLE_UPGRADE_MINION_ID` | 101268 |
 | 1440 | `TECH_LEVEL` | 5 |
 | 1688 | `BACON_SUBSET_ELEMENTALS` | 1 |
 | 1724 | `1` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 15 个全部匹配）。

**官方机制 tag 未进数据层**（生成器白名单外；数据层无对应字段）

 | enumID | tag | 值 |
 |---|---|---|
 | 1724 | `1` | 1 |

**数据层提示**

- 官方机制 tag 未进数据层（生成器白名单外）: `1(1724)=1`

**审计对齐（engine-analyst / diff-harness）**

- 分类: F-10 8 族动态属性（已迁移 script_data_or_card(3)）
- 引擎状态: 有脚本（动态 atk/health 钩子 + NUM_3 通道）；默认行为不变
- 官方文本 vs 引擎实现: 非文本不符（动态状态/测量口径）
- 依据: docs/EXACTNESS_STATUS.md F-10；reversed/rea/deferred_primitives.md P2b/P5
- 缺失证据: P5: CardDef 缺动态步长（num 为空）→ harness 文本回退表；真实 Power.log 逐事件数值可消除回退
- 处理: 保持默认；不硬套 NUM_3（P2b 反推失败时保留缺口）

### `BG26_537_G` — Flourishing Frostling / 缤纷冰灵

- 来源: `CardDefs.Bacon.xml` 行 46415；DBF **101268**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=18(ELEMENTAL)、tech=5、atk/health=4/2、cost=3、rarity=None、armor=None
- 关键词: ∅；种族身份 tag: ∅；subsets: ∅
- ScriptDataNum: {1: 4, 2: 2}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{0}` | 1 | `TAG_SCRIPT_DATA_NUM_1` | 4 | 是 | ok |
 | `{1}` | 2 | `TAG_SCRIPT_DATA_NUM_2` | 2 | 是 | ok |

**英文全文**

```text
[x]Has +{0}/+{1} for each
Elemental you played this
___game <i>(wherever this is)</i>.
```

**中文全文（zhCN）**

```text
在本局对战中，你每使用过一张元素牌，便拥有+{0}/+{1}<i>（无论本随从在哪）</i>。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 2 | `TAG_SCRIPT_DATA_NUM_1` | 4 |
 | 3 | `TAG_SCRIPT_DATA_NUM_2` | 2 |
 | 45 | `HEALTH` | 2 |
 | 47 | `ATK` | 4 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 4 |
 | 200 | `CARDRACE` | 18 |
 | 202 | `CARDTYPE` | 4 |
 | 1440 | `TECH_LEVEL` | 5 |
 | 1471 | `BACON_TRIPLED_BASE_MINION_ID` | 101267 |
 | 1724 | `1` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 14 个全部匹配）。

**官方机制 tag 未进数据层**（生成器白名单外；数据层无对应字段）

 | enumID | tag | 值 |
 |---|---|---|
 | 1724 | `1` | 1 |

**数据层提示**

- 官方机制 tag 未进数据层（生成器白名单外）: `1(1724)=1`

**审计对齐（engine-analyst / diff-harness）**

- 分类: F-10 8 族动态属性（已迁移 script_data_or_card(3)）
- 引擎状态: 有脚本（动态 atk/health 钩子 + NUM_3 通道）；默认行为不变
- 官方文本 vs 引擎实现: 非文本不符（动态状态/测量口径）
- 依据: docs/EXACTNESS_STATUS.md F-10；reversed/rea/deferred_primitives.md P2b/P5
- 缺失证据: P5: CardDef 缺动态步长（num 为空）→ harness 文本回退表；真实 Power.log 逐事件数值可消除回退
- 处理: 保持默认；不硬套 NUM_3（P2b 反推失败时保留缺口）

### `BG36_MagicItem_216` — Eternal Portrait / 永恒肖像

- 来源: `CardDefs.Bacon.xml` 行 213643；DBF **133404**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=44(BATTLEGROUND_TRINKET)、race=None(None)、tech=None、atk/health=None/None、cost=5、rarity=None、armor=None
- 关键词: ∅；种族身份 tag: ∅；subsets: ['subset_undead']
- ScriptDataNum: {1: 4, 2: 2}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{0}` | 1 | `TAG_SCRIPT_DATA_NUM_1` | 4 | 是 | ok |
 | `{1}` | 2 | `TAG_SCRIPT_DATA_NUM_2` | 2 | 是 | ok |

**英文全文**

```text
[x]Get a Golden Eternal Knight.
After a friendly Undead dies,
your Eternal Knights have
+{0}/+{1} this game.
```

**中文全文（zhCN）**

```text
获取一张金色永恒骑士。在一个友方亡灵死亡后，在本局对战中，你的永恒骑士拥有+{0}/+{1}。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 2 | `TAG_SCRIPT_DATA_NUM_1` | 4 |
 | 3 | `TAG_SCRIPT_DATA_NUM_2` | 2 |
 | 32 | `TRIGGER_VISUAL` | 1 |
 | 48 | `COST` | 5 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 12 |
 | 201 | `FACTION` | 3 |
 | 202 | `CARDTYPE` | 44 |
 | 1635 | `SPELL_SCHOOL` | 12 |
 | 2347 | `BACON_SUBSET_UNDEAD` | 1 |
 | 2519 | `BACON_EVOLUTION_CARD_ID` | 95262 |
 | 3407 | `BACON_TRINKET` | 1 |
 | 4701 | `1` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 13 个全部匹配）。

**官方机制 tag 未进数据层**（生成器白名单外；数据层无对应字段）

 | enumID | tag | 值 |
 |---|---|---|
 | 4701 | `1` | 1 |

**数据层提示**

- 官方机制 tag 未进数据层（生成器白名单外）: `1(4701)=1`

**审计对齐（engine-analyst / diff-harness）**

- 分类: F-10 8 族动态属性（饰品侧延伸）
- 引擎状态: 有脚本（NUM_1~NUM_3：Golden Eternal Knight + 友方 Undead 死亡累计）
- 官方文本 vs 引擎实现: 非文本不符（饰品可见性/测量口径）
- 依据: reversed/rea/deferred_primitives.md P4；EXACTNESS_STATUS F-10
- 缺失证据: 真实 Power.log 的饰品实体 tag（traceizer 扩展 trinkets[]）
- 处理: 不判定为引擎 bug

### `BGFYM_000` — C'Thun / 克苏恩

- 来源: `CardDefs.Bacon.xml` 行 239324；DBF **130610**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=126(ABERRATION)、tech=1、atk/health=1/1、cost=3、rarity=None、armor=None
- 关键词: ∅；种族身份 tag: ∅；subsets: ∅
- ScriptDataNum: ∅

**英文全文**

```text
<b>Deity.</b> After this awakens, give this minion's stats split amongst your other minions.
```

**中文全文（zhCN）**

```text
<b>神明</b>。在本随从被唤醒后，使你的其他随从获得属性值，获得的总量为本随从的属性值。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 32 | `TRIGGER_VISUAL` | 1 |
 | 45 | `HEALTH` | 1 |
 | 47 | `ATK` | 1 |
 | 114 | `ELITE` | 1 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 6 |
 | 200 | `CARDRACE` | 126 |
 | 202 | `CARDTYPE` | 4 |
 | 1429 | `BACON_TRIPLE_UPGRADE_MINION_ID` | 134633 |
 | 1440 | `TECH_LEVEL` | 1 |
 | 4744 | `BACON_OLD_GOD` | 1 |
 | 4929 | `19779` | 19779 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 12 个全部匹配）。

**官方机制 tag 未进数据层**（生成器白名单外；数据层无对应字段）

 | enumID | tag | 值 |
 |---|---|---|
 | 4744 | `BACON_OLD_GOD` | 1 |
 | 4929 | `19779` | 19779 |

**数据层提示**

- 官方机制 tag 未进数据层（生成器白名单外）: `BACON_OLD_GOD(4744)=1`, `19779(4929)=19779`
- CardDefs 无 ScriptDataNum（无参数化数值；若卡面含动态数值，只能走文本字面量/机制通道，见 F-10 P5 缺口）

**审计对齐（engine-analyst / diff-harness）**

- 分类: F-07 Deity / C'Thun awaken split（DEFERRED）
- 引擎状态: Deity 子系统已实现（aberration 死亡推进/awaken/Deity 增益）；C'Thun awaken 的 'stats split amongst your other minions' 未实现
- 官方文本 vs 引擎实现: 官方文本多解/需官方证据（split 的整除/余数/顺序/目标数）
- 依据: docs/ENGINE_NOTES.md F-07；EXACTNESS_STATUS §223-255；round6 §2.1
- 缺失证据: 真实 Power.log 的 C'Thun awaken 分配结果 / 官方 Notes（禁止用 BobsBuddy 反推）
- 处理: 标 known_context_gap: deity_split_c_thun，不要求收敛

### `BGFYM_000_G` — C'Thun / 克苏恩

- 来源: `CardDefs.Bacon.xml` 行 239389；DBF **134633**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=126(ABERRATION)、tech=1、atk/health=2/2、cost=3、rarity=None、armor=None
- 关键词: ∅；种族身份 tag: ∅；subsets: ∅
- ScriptDataNum: ∅

**英文全文**

```text
<b>Deity.</b> After this awakens, give double this minion's stats split amongst your other minions.
```

**中文全文（zhCN）**

```text
<b>神明</b>。在本随从被唤醒后，使你的其他随从获得属性值，获得的总量为本随从的双倍属性值。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 32 | `TRIGGER_VISUAL` | 1 |
 | 45 | `HEALTH` | 2 |
 | 47 | `ATK` | 2 |
 | 114 | `ELITE` | 1 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 6 |
 | 200 | `CARDRACE` | 126 |
 | 202 | `CARDTYPE` | 4 |
 | 1440 | `TECH_LEVEL` | 1 |
 | 1471 | `BACON_TRIPLED_BASE_MINION_ID` | 130610 |
 | 4744 | `BACON_OLD_GOD` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 12 个全部匹配）。

**官方机制 tag 未进数据层**（生成器白名单外；数据层无对应字段）

 | enumID | tag | 值 |
 |---|---|---|
 | 4744 | `BACON_OLD_GOD` | 1 |

**数据层提示**

- 官方机制 tag 未进数据层（生成器白名单外）: `BACON_OLD_GOD(4744)=1`
- CardDefs 无 ScriptDataNum（无参数化数值；若卡面含动态数值，只能走文本字面量/机制通道，见 F-10 P5 缺口）

**审计对齐（engine-analyst / diff-harness）**

- 分类: F-07 Deity / C'Thun awaken split（DEFERRED）
- 引擎状态: Deity 子系统已实现（aberration 死亡推进/awaken/Deity 增益）；C'Thun awaken 的 'stats split amongst your other minions' 未实现
- 官方文本 vs 引擎实现: 官方文本多解/需官方证据（split 的整除/余数/顺序/目标数）
- 依据: docs/ENGINE_NOTES.md F-07；EXACTNESS_STATUS §223-255；round6 §2.1
- 缺失证据: 真实 Power.log 的 C'Thun awaken 分配结果 / 官方 Notes（禁止用 BobsBuddy 反推）
- 处理: 标 known_context_gap: deity_split_c_thun，不要求收敛

### `BGFYM_011` — Y'Shaarj / 亚煞极

- 来源: `CardDefs.Bacon.xml` 行 239692；DBF **132532**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=126(ABERRATION)、tech=1、atk/health=1/1、cost=3、rarity=None、armor=None
- 关键词: ['deathrattle']；种族身份 tag: ∅；subsets: ∅
- ScriptDataNum: {1: 2}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{0}` | 1 | `TAG_SCRIPT_DATA_NUM_1` | 2 | 是 | ok |

**英文全文**

```text
[x]<b>Deity.</b> <b>Deathrattle:</b> Summon your
first {0} Aberrations that died this
combat with their maximum
stats <i>(except <b>Deities</b>)</i>.
```

**中文全文（zhCN）**

```text
<b>神明</b>。<b>亡语：</b>召唤你在本场战斗中死亡的前{0}个畸变怪，且其具有其最大属性值<i>（<b>神明</b>除外）</i>。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 2 | `TAG_SCRIPT_DATA_NUM_1` | 2 |
 | 45 | `HEALTH` | 1 |
 | 47 | `ATK` | 1 |
 | 114 | `ELITE` | 1 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 6 |
 | 200 | `CARDRACE` | 126 |
 | 202 | `CARDTYPE` | 4 |
 | 1429 | `BACON_TRIPLE_UPGRADE_MINION_ID` | 134634 |
 | 1440 | `TECH_LEVEL` | 1 |
 | 4744 | `BACON_OLD_GOD` | 1 |
 | 4929 | `19780` | 19780 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 14 个全部匹配）。

**官方机制 tag 未进数据层**（生成器白名单外；数据层无对应字段）

 | enumID | tag | 值 |
 |---|---|---|
 | 4744 | `BACON_OLD_GOD` | 1 |
 | 4929 | `19780` | 19780 |

**数据层提示**

- 官方机制 tag 未进数据层（生成器白名单外）: `BACON_OLD_GOD(4744)=1`, `19780(4929)=19780`

**审计对齐（engine-analyst / diff-harness）**

- 分类: F-07 Deity / C'Thun awaken split（DEFERRED）
- 引擎状态: Deity 子系统已实现（aberration 死亡推进/awaken/Deity 增益）；C'Thun awaken 的 'stats split amongst your other minions' 未实现
- 官方文本 vs 引擎实现: 官方文本多解/需官方证据（split 的整除/余数/顺序/目标数）
- 依据: docs/ENGINE_NOTES.md F-07；EXACTNESS_STATUS §223-255；round6 §2.1
- 缺失证据: 真实 Power.log 的 C'Thun awaken 分配结果 / 官方 Notes（禁止用 BobsBuddy 反推）
- 处理: 标 known_context_gap: deity_split_c_thun，不要求收敛

### `BGFYM_011_G` — Y'Shaarj / 亚煞极

- 来源: `CardDefs.Bacon.xml` 行 239758；DBF **134634**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=126(ABERRATION)、tech=1、atk/health=2/2、cost=3、rarity=None、armor=None
- 关键词: ['deathrattle']；种族身份 tag: ∅；subsets: ∅
- ScriptDataNum: {1: 4}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{0}` | 1 | `TAG_SCRIPT_DATA_NUM_1` | 4 | 是 | ok |

**英文全文**

```text
[x]<b>Deity.</b> <b>Deathrattle:</b> Summon your
first {0} Aberrations that died this
combat with their maximum
stats <i>(except <b>Deities</b>)</i>.
```

**中文全文（zhCN）**

```text
<b>神明</b>。<b>亡语：</b>召唤你在本场战斗中死亡的前{0}个畸变怪，且其具有其最大属性值<i>（<b>神明</b>除外）</i>。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 2 | `TAG_SCRIPT_DATA_NUM_1` | 4 |
 | 45 | `HEALTH` | 2 |
 | 47 | `ATK` | 2 |
 | 114 | `ELITE` | 1 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 6 |
 | 200 | `CARDRACE` | 126 |
 | 202 | `CARDTYPE` | 4 |
 | 1440 | `TECH_LEVEL` | 1 |
 | 1471 | `BACON_TRIPLED_BASE_MINION_ID` | 132532 |
 | 4744 | `BACON_OLD_GOD` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 14 个全部匹配）。

**官方机制 tag 未进数据层**（生成器白名单外；数据层无对应字段）

 | enumID | tag | 值 |
 |---|---|---|
 | 4744 | `BACON_OLD_GOD` | 1 |

**数据层提示**

- 官方机制 tag 未进数据层（生成器白名单外）: `BACON_OLD_GOD(4744)=1`

**审计对齐（engine-analyst / diff-harness）**

- 分类: F-07 Deity / C'Thun awaken split（DEFERRED）
- 引擎状态: Deity 子系统已实现（aberration 死亡推进/awaken/Deity 增益）；C'Thun awaken 的 'stats split amongst your other minions' 未实现
- 官方文本 vs 引擎实现: 官方文本多解/需官方证据（split 的整除/余数/顺序/目标数）
- 依据: docs/ENGINE_NOTES.md F-07；EXACTNESS_STATUS §223-255；round6 §2.1
- 缺失证据: 真实 Power.log 的 C'Thun awaken 分配结果 / 官方 Notes（禁止用 BobsBuddy 反推）
- 处理: 标 known_context_gap: deity_split_c_thun，不要求收敛

### `BG_OldGod` — Secret Deity [DNT] / 秘密神明

- 来源: `CardDefs.Bacon.xml` 行 228692；DBF **132487**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=5(SPELL)、race=None(None)、tech=None、atk/health=None/None、cost=None、rarity=None、armor=None
- 关键词: ∅；种族身份 tag: ∅；subsets: ∅
- ScriptDataNum: {1: 4, 2: 1, 3: 1}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{0}` | 1 | `TAG_SCRIPT_DATA_NUM_1` | 4 | 是 | ok |
 | `{1}` | 2 | `TAG_SCRIPT_DATA_NUM_2` | 1 | 是 | ok |
 | `{2}` | 3 | `TAG_SCRIPT_DATA_NUM_3` | 1 | 是 | ok |

**英文全文**

```text
After 4 friendly Aberrations die each combat, awaken a {1}/{2}
{5}. <i>({0} left!)</i>@After 4 friendly Aberrations die each combat, awaken a {1}/{2}
{5}. <i>(Done!)</i>
```

**中文全文（zhCN）**

```text
每场战斗中，在4个友方畸变怪死亡后，唤醒一个{1}/{2}的{5}。<i>（还剩{0}个！）</i>@每场战斗中，在4个友方畸变怪死亡后，唤醒一个{1}/{2}的{5}。<i>（已完成！）</i>
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 2 | `TAG_SCRIPT_DATA_NUM_1` | 4 |
 | 3 | `TAG_SCRIPT_DATA_NUM_2` | 1 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 12 |
 | 202 | `CARDTYPE` | 5 |
 | 535 | `QUEST_PROGRESS_TOTAL` | 4 |
 | 2519 | `BACON_EVOLUTION_CARD_ID` | 130610 |
 | 2889 | `TAG_SCRIPT_DATA_NUM_3` | 1 |
 | 2921 | `TAG_SCRIPT_DATA_NUM_6` | 130610 |
 | 3047 | `BACON_TRIGGER_XY` | 1 |
 | 4922 | `BACON_DEITY_SIGIL` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 11 个全部匹配）。

**官方机制 tag 未进数据层**（生成器白名单外；数据层无对应字段）

 | enumID | tag | 值 |
 |---|---|---|
 | 3047 | `BACON_TRIGGER_XY` | 1 |
 | 4922 | `BACON_DEITY_SIGIL` | 1 |
 | 4946 | `1` | 1 |

**数据层提示**

- 官方机制 tag 未进数据层（生成器白名单外）: `BACON_TRIGGER_XY(3047)=1`, `BACON_DEITY_SIGIL(4922)=1`, `1(4946)=1`

**审计对齐（engine-analyst / diff-harness）**

- 分类: F-07 Deity / C'Thun awaken split（DEFERRED）
- 引擎状态: Deity 子系统已实现（aberration 死亡推进/awaken/Deity 增益）；C'Thun awaken 的 'stats split amongst your other minions' 未实现
- 官方文本 vs 引擎实现: 官方文本多解/需官方证据（split 的整除/余数/顺序/目标数）
- 依据: docs/ENGINE_NOTES.md F-07；EXACTNESS_STATUS §223-255；round6 §2.1
- 缺失证据: 真实 Power.log 的 C'Thun awaken 分配结果 / 官方 Notes（禁止用 BobsBuddy 反推）
- 处理: 标 known_context_gap: deity_split_c_thun，不要求收敛

### `BG26_HERO_102p2` — Minor Hymn / 小调颂歌

- 来源: `CardDefs.Bacon.xml` 行 50080；DBF **103503**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=10(HERO_POWER)、race=None(None)、tech=None、atk/health=None/None、cost=0、rarity=None、armor=None
- 关键词: ∅；种族身份 tag: ∅；subsets: ∅
- ScriptDataNum: ∅

**英文全文**

```text
[x]Twice per turn, give a
minion Health equal to
your Tier. <i>(Swaps to
Attack next turn!)</i>
```

**中文全文（zhCN）**

```text
每回合两次。使一个随从获得等同于你当前等级的生命值。<i>（下回合切换为攻击力！）</i>
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 12 |
 | 202 | `CARDTYPE` | 10 |
 | 2376 | `BACON_HEROPOWER_BASE_HERO_ID` | 103500 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_hero_powers.json`；期望字段 7 个全部匹配）。

**官方机制 tag 未进数据层**（生成器白名单外；数据层无对应字段）

 | enumID | tag | 值 |
 |---|---|---|
 | 2376 | `BACON_HEROPOWER_BASE_HERO_ID` | 103500 |

**数据层提示**

- 官方机制 tag 未进数据层（生成器白名单外）: `BACON_HEROPOWER_BASE_HERO_ID(2376)=103500`

**审计对齐（engine-analyst / diff-harness）**

- 分类: 英雄技能 missing_script（单列台账）
- 引擎状态: 无技能脚本；CardDef 文本已更新为 37.0 'Twice per turn ...'（36.6.3 为不带 Twice per turn）
- 官方文本 vs 引擎实现: 官方文本 vs 引擎实现不符（未实现）+ 招募期技能（对战斗无直接影响）
- 依据: DIFF_HARNESS §5.3 英雄技能台账；behavior_mismatch_5_rootcause §1.3
- 缺失证据: 英雄技能批次实现（Twice per turn/Attack-Health 交替）；当前 harness 标 unmodeled_context
- 处理: 不判定为战斗 bug

### `BG26_HERO_102p` — Major Hymn / 大调颂歌

- 来源: `CardDefs.Bacon.xml` 行 50031；DBF **103501**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=10(HERO_POWER)、race=None(None)、tech=None、atk/health=None/None、cost=0、rarity=None、armor=None
- 关键词: ∅；种族身份 tag: ∅；subsets: ∅
- ScriptDataNum: ∅

**英文全文**

```text
[x]Twice per turn, give a
minion Attack equal to
your Tier. <i>(Swaps to
Health next turn!)</i>
```

**中文全文（zhCN）**

```text
每回合两次。使一个随从获得等同于你当前等级的攻击力。<i>（下回合切换为生命值！）</i>
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 12 |
 | 202 | `CARDTYPE` | 10 |
 | 2376 | `BACON_HEROPOWER_BASE_HERO_ID` | 103500 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_hero_powers.json`；期望字段 7 个全部匹配）。

**官方机制 tag 未进数据层**（生成器白名单外；数据层无对应字段）

 | enumID | tag | 值 |
 |---|---|---|
 | 2376 | `BACON_HEROPOWER_BASE_HERO_ID` | 103500 |

**数据层提示**

- 官方机制 tag 未进数据层（生成器白名单外）: `BACON_HEROPOWER_BASE_HERO_ID(2376)=103500`

**审计对齐（engine-analyst / diff-harness）**

- 分类: 对照（同英雄另一技能，已实现）
- 引擎状态: 有技能脚本（Major Hymn）
- 官方文本 vs 引擎实现: 无（对照）
- 依据: hsrl2/scripts/batches 英雄技能批次
- 缺失证据: —
- 处理: 对照

### `BG26_HERO_102` — Inge, the Iron Hymn / 因葛，钢铁颂歌

- 来源: `CardDefs.Bacon.xml` 行 49800；DBF **103500**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=3(HERO)、race=None(None)、tech=None、atk/health=None/30、cost=None、rarity=2、armor=10
- 关键词: ∅；种族身份 tag: ∅；subsets: ∅
- ScriptDataNum: ∅

**英文全文**

```text
（无文本）
```

**中文全文（zhCN）**

```text
（无 zhCN）
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 342 | `ARTISTNAME` | 0 |
 | 45 | `HEALTH` | 30 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 12 |
 | 202 | `CARDTYPE` | 3 |
 | 203 | `RARITY` | 2 |
 | 292 | `ARMOR` | 10 |
 | 380 | `HERO_POWER` | 103501 |
 | 1491 | `BACON_HERO_CAN_BE_DRAFTED` | 1 |
 | 2130 | `BACON_COMPANION_ID` | 113627 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_heroes.json`；期望字段 11 个全部匹配）。

**审计对齐（engine-analyst / diff-harness）**

- 分类: 对照（英雄本体/技能绑定链）
- 引擎状态: 英雄本体，HERO_POWER tag 绑定两技能
- 官方文本 vs 引擎实现: 无（对照）
- 依据: CardDefs HERO_POWER(380)
- 缺失证据: —
- 处理: 对照

### `BG34_694` — Wintergrasp Ghoul / 冬拥食尸鬼

- 来源: `CardDefs.Bacon.xml` 行 156230；DBF **126955**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=11(UNDEAD)、tech=5、atk/health=5/3、cost=3、rarity=None、armor=None
- 关键词: ['deathrattle']；种族身份 tag: ∅；subsets: ['subset_undead']
- ScriptDataNum: ∅

**英文全文**

```text
<b>Deathrattle:</b> Get a Tomb Turning.
```

**中文全文（zhCN）**

```text
<b>亡语：</b>获取一张惊扰墓穴。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 45 | `HEALTH` | 3 |
 | 47 | `ATK` | 5 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 1 |
 | 200 | `CARDRACE` | 11 |
 | 202 | `CARDTYPE` | 4 |
 | 1429 | `BACON_TRIPLE_UPGRADE_MINION_ID` | 126956 |
 | 1440 | `TECH_LEVEL` | 5 |
 | 2347 | `BACON_SUBSET_UNDEAD` | 1 |
 | 2519 | `BACON_EVOLUTION_CARD_ID` | 126957 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 15 个全部匹配）。

**数据层提示**

- CardDefs 无 ScriptDataNum（无参数化数值；若卡面含动态数值，只能走文本字面量/机制通道，见 F-10 P5 缺口）

**审计对齐（engine-analyst / diff-harness）**

- 分类: 差分 TOP 卡（TVD 聚类）
- 引擎状态: TVD .499；有脚本（Deathrattle: Get a Tomb Turning）
- 官方文本 vs 引擎实现: 非数据不符；TVD 由 Deity 状态缺口/脚本覆盖/外部附魔主导（EXACTNESS_STATUS §249-256：标 unsupported 后重算，不要求收敛）
- 依据: docs/DIFF_HARNESS.md §TOP；reversed/rea/round6_and_bb_top_analysis.md
- 缺失证据: harness 补 Deity 六字段（deity_card_id/atk/health/progress/awakened/sigil）与 oracle schema；真实 Power.log
- 处理: 不因此改数据/引擎

### `BG35_432` — Bristleback Bully / 刺背恶霸

- 来源: `CardDefs.Bacon.xml` 行 187511；DBF **130145**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=43(QUILBOAR)、tech=2、atk/health=3/2、cost=3、rarity=None、armor=None
- 关键词: ['deathrattle', 'taunt']；种族身份 tag: ∅；subsets: ['subset_quilboar']
- ScriptDataNum: ∅

**英文全文**

```text
[x]<b>Taunt</b>
<b>Deathrattle:</b> Get a
<b>Blood Gem</b> that also gives
a Quilboar <b>Taunt</b>.
```

**中文全文（zhCN）**

```text
<b>嘲讽</b>。<b>亡语：</b>获取一张<b>鲜血宝石</b>。该宝石还能使野猪人获得
<b>嘲讽</b>。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 45 | `HEALTH` | 2 |
 | 47 | `ATK` | 3 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 2 |
 | 200 | `CARDRACE` | 43 |
 | 202 | `CARDTYPE` | 4 |
 | 1429 | `BACON_TRIPLE_UPGRADE_MINION_ID` | 130146 |
 | 1440 | `TECH_LEVEL` | 2 |
 | 1845 | `BACON_SUBSET_QUILLBOAR` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 15 个全部匹配）。

**数据层提示**

- CardDefs 无 ScriptDataNum（无参数化数值；若卡面含动态数值，只能走文本字面量/机制通道，见 F-10 P5 缺口）

**审计对齐（engine-analyst / diff-harness）**

- 分类: 差分 TOP 卡（TVD 聚类）
- 引擎状态: TVD .492；有脚本（Taunt/Deathrattle: Blood Gem+Taunt）
- 官方文本 vs 引擎实现: 非数据不符；TVD 由 Deity 状态缺口/脚本覆盖/外部附魔主导（EXACTNESS_STATUS §249-256：标 unsupported 后重算，不要求收敛）
- 依据: docs/DIFF_HARNESS.md §TOP；reversed/rea/round6_and_bb_top_analysis.md
- 缺失证据: harness 补 Deity 六字段（deity_card_id/atk/health/progress/awakened/sigil）与 oracle schema；真实 Power.log
- 处理: 不因此改数据/引擎

### `BG32_835` — Tranquil Meditative / 宁静的冥想者

- 来源: `CardDefs.Bacon.xml` 行 124924；DBF **119942**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=92(NAGA)、tech=5、atk/health=3/8、cost=3、rarity=None、armor=None
- 关键词: ∅；种族身份 tag: ∅；subsets: ['subset_naga']
- ScriptDataNum: {1: 1, 2: 1}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{0}` | 1 | `TAG_SCRIPT_DATA_NUM_1` | 1 | 是 | ok |
 | `{1}` | 2 | `TAG_SCRIPT_DATA_NUM_2` | 1 | 是 | ok |

**英文全文**

```text
[x]<b>Spellcraft:</b> Your Tavern
spells give an extra
+{0}/+{1} this game.
```

**中文全文（zhCN）**

```text
<b>塑造法术：</b>在本局对战中，你的酒馆法术使随从额外获得+{0}/+{1}。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 342 | `ARTISTNAME` | 0 |
 | 2 | `TAG_SCRIPT_DATA_NUM_1` | 1 |
 | 3 | `TAG_SCRIPT_DATA_NUM_2` | 1 |
 | 32 | `TRIGGER_VISUAL` | 1 |
 | 45 | `HEALTH` | 8 |
 | 47 | `ATK` | 3 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 14 |
 | 200 | `CARDRACE` | 92 |
 | 202 | `CARDTYPE` | 4 |
 | 1429 | `BACON_TRIPLE_UPGRADE_MINION_ID` | 119943 |
 | 1440 | `TECH_LEVEL` | 5 |
 | 1456 | `IS_BACON_POOL_MINION` | 1 |
 | 2272 | `BACON_SUBSET_NAGA` | 1 |
 | 2359 | `BACON_SPELLCRAFT_ID` | 121479 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 17 个全部匹配）。

**审计对齐（engine-analyst / diff-harness）**

- 分类: 差分 TOP 卡（TVD 聚类）
- 引擎状态: TVD .414；有脚本（Tranquil Meditative）
- 官方文本 vs 引擎实现: 非数据不符；TVD 由 Deity 状态缺口/脚本覆盖/外部附魔主导（EXACTNESS_STATUS §249-256：标 unsupported 后重算，不要求收敛）
- 依据: docs/DIFF_HARNESS.md §TOP；reversed/rea/round6_and_bb_top_analysis.md
- 缺失证据: harness 补 Deity 六字段（deity_card_id/atk/health/progress/awakened/sigil）与 oracle schema；真实 Power.log
- 处理: 不因此改数据/引擎

### `BG34_926` — Ruthless Queensguard / 无情的女王护卫

- 来源: `CardDefs.Bacon.xml` 行 158492；DBF **126918**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=92(NAGA)、tech=6、atk/health=3/3、cost=3、rarity=None、armor=None
- 关键词: ['battlecry', 'deathrattle', 'rally']；种族身份 tag: ∅；subsets: ['subset_naga']
- ScriptDataNum: ∅

**英文全文**

```text
<b>Battlecry, Deathrattle, and Rally:</b> Cast Queen's Command.
```

**中文全文（zhCN）**

```text
<b>战吼，亡语，进击：</b>施放女王的命令。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 45 | `HEALTH` | 3 |
 | 47 | `ATK` | 3 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 14 |
 | 200 | `CARDRACE` | 92 |
 | 202 | `CARDTYPE` | 4 |
 | 1429 | `BACON_TRIPLE_UPGRADE_MINION_ID` | 126919 |
 | 1440 | `TECH_LEVEL` | 6 |
 | 2272 | `BACON_SUBSET_NAGA` | 1 |
 | 2519 | `BACON_EVOLUTION_CARD_ID` | 130713 |
 | 4204 | `BACON_RALLY` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 17 个全部匹配）。

**数据层提示**

- CardDefs 无 ScriptDataNum（无参数化数值；若卡面含动态数值，只能走文本字面量/机制通道，见 F-10 P5 缺口）

**审计对齐（engine-analyst / diff-harness）**

- 分类: 差分 TOP 卡（TVD 聚类）
- 引擎状态: TVD .418；有脚本
- 官方文本 vs 引擎实现: 非数据不符；TVD 由 Deity 状态缺口/脚本覆盖/外部附魔主导（EXACTNESS_STATUS §249-256：标 unsupported 后重算，不要求收敛）
- 依据: docs/DIFF_HARNESS.md §TOP；reversed/rea/round6_and_bb_top_analysis.md
- 缺失证据: harness 补 Deity 六字段（deity_card_id/atk/health/progress/awakened/sigil）与 oracle schema；真实 Power.log
- 处理: 不因此改数据/引擎

### `BG34_320` — The Last One Standing / 最后的生物

- 来源: `CardDefs.Bacon.xml` 行 151342；DBF **127109**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=26(ALL)、tech=7、atk/health=15/15、cost=3、rarity=None、armor=None
- 关键词: ['rally']；种族身份 tag: ∅；subsets: ∅
- ScriptDataNum: {1: 15, 2: 15}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{0}` | 1 | `TAG_SCRIPT_DATA_NUM_1` | 15 | 是 | ok |
 | `{1}` | 2 | `TAG_SCRIPT_DATA_NUM_2` | 15 | 是 | ok |

**英文全文**

```text
<b>Rally:</b> Give a friendly minion of each type +{0}/+{1} permanently.
```

**中文全文（zhCN）**

```text
<b>进击：</b>使每个类型的各一个友方随从永久获得+{0}/+{1}。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 342 | `ARTISTNAME` | 0 |
 | 2 | `TAG_SCRIPT_DATA_NUM_1` | 15 |
 | 3 | `TAG_SCRIPT_DATA_NUM_2` | 15 |
 | 45 | `HEALTH` | 15 |
 | 47 | `ATK` | 15 |
 | 114 | `ELITE` | 1 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 12 |
 | 200 | `CARDRACE` | 26 |
 | 202 | `CARDTYPE` | 4 |
 | 1429 | `BACON_TRIPLE_UPGRADE_MINION_ID` | 127110 |
 | 1440 | `TECH_LEVEL` | 7 |
 | 1456 | `IS_BACON_POOL_MINION` | 1 |
 | 1724 | `1` | 1 |
 | 4204 | `BACON_RALLY` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 16 个全部匹配）。

**官方机制 tag 未进数据层**（生成器白名单外；数据层无对应字段）

 | enumID | tag | 值 |
 |---|---|---|
 | 1724 | `1` | 1 |

**数据层提示**

- 官方机制 tag 未进数据层（生成器白名单外）: `1(1724)=1`

**审计对齐（engine-analyst / diff-harness）**

- 分类: 差分 TOP 卡（TVD 聚类）
- 引擎状态: 玩家终局卡；有脚本（Rally + ALL 多重选取），官方多重选取语义待证据（EXACTNESS_STATUS/F-11 观察项）
- 官方文本 vs 引擎实现: 非数据不符；TVD 由 Deity 状态缺口/脚本覆盖/外部附魔主导（EXACTNESS_STATUS §249-256：标 unsupported 后重算，不要求收敛）
- 依据: docs/DIFF_HARNESS.md §TOP；reversed/rea/round6_and_bb_top_analysis.md
- 缺失证据: harness 补 Deity 六字段（deity_card_id/atk/health/progress/awakened/sigil）与 oracle schema；真实 Power.log
- 处理: 不因此改数据/引擎

### `BG36_300` — N'raqi Frostcaller / 恩拉其唤冰者

- 来源: `CardDefs.Bacon.xml` 行 202055；DBF **132136**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=126(ABERRATION)、tech=5、atk/health=6/3、cost=3、rarity=None、armor=None
- 关键词: ['activate']；种族身份 tag: ∅；subsets: ∅
- ScriptDataNum: {1: 1, 2: 1}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{0}` | 1 | `TAG_SCRIPT_DATA_NUM_1` | 1 | 是 | ok |
 | `{1}` | 2 | `TAG_SCRIPT_DATA_NUM_2` | 1 | 是 | ok |
 | `{2}` | 3 | `TAG_SCRIPT_DATA_NUM_3` | None | 是 | PLACEHOLDER_WITHOUT_NUM（CardDefs 无该槽位或值为 0） |

**英文全文**

```text
[x]<b>Activate ({2}):</b> Discard a card
for your Tavern spells to give
_an extra +{0}/+{1} this game.
```

**中文全文（zhCN）**

```text
<b>发动（{2}）：</b>弃一张牌。在本局对战中，你的酒馆法术使随从额外获得+{0}/+{1}。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 2 | `TAG_SCRIPT_DATA_NUM_1` | 1 |
 | 3 | `TAG_SCRIPT_DATA_NUM_2` | 1 |
 | 45 | `HEALTH` | 3 |
 | 47 | `ATK` | 6 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 6 |
 | 200 | `CARDRACE` | 126 |
 | 202 | `CARDTYPE` | 4 |
 | 1429 | `BACON_TRIPLE_UPGRADE_MINION_ID` | 132137 |
 | 1440 | `TECH_LEVEL` | 5 |
 | 1456 | `IS_BACON_POOL_MINION` | 1 |
 | 1724 | `1` | 1 |
 | 4089 | `INTERACTABLE_OBJECT` | 1 |
 | 4757 | `BACON_SUBSET_ABERRATION` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 16 个全部匹配）。

**官方机制 tag 未进数据层**（生成器白名单外；数据层无对应字段）

 | enumID | tag | 值 |
 |---|---|---|
 | 1724 | `1` | 1 |
 | 4757 | `BACON_SUBSET_ABERRATION` | 1 |
 | 4953 | `1` | 1 |

**数据层提示**

- 文本占位符 {2} 在 CardDefs 无对应 TAG_SCRIPT_DATA_NUM_3（生成器导出为 None；脚本必须走文本字面量）
- 官方机制 tag 未进数据层（生成器白名单外）: `1(1724)=1`, `BACON_SUBSET_ABERRATION(4757)=1`, `1(4953)=1`

**审计对齐（engine-analyst / diff-harness）**

- 分类: 差分 TOP 卡（TVD 聚类）
- 引擎状态: Deity 聚类 TOP（TVD .766/0.422）；脚本/数据面待与 Deity 状态缺口区分
- 官方文本 vs 引擎实现: 非数据不符；TVD 由 Deity 状态缺口/脚本覆盖/外部附魔主导（EXACTNESS_STATUS §249-256：标 unsupported 后重算，不要求收敛）
- 依据: docs/DIFF_HARNESS.md §TOP；reversed/rea/round6_and_bb_top_analysis.md
- 缺失证据: harness 补 Deity 六字段（deity_card_id/atk/health/progress/awakened/sigil）与 oracle schema；真实 Power.log
- 处理: 不因此改数据/引擎

### `BG36_318` — Faceless Converter / 无面转化者

- 来源: `CardDefs.Bacon.xml` 行 202897；DBF **132331**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=126(ABERRATION)、tech=5、atk/health=5/5、cost=3、rarity=None、armor=None
- 关键词: ['deathrattle']；种族身份 tag: ∅；subsets: ∅
- ScriptDataNum: {1: 2, 2: 1}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{0}` | 1 | `TAG_SCRIPT_DATA_NUM_1` | 2 | 是 | ok |
 | `{1}` | 2 | `TAG_SCRIPT_DATA_NUM_2` | 1 | 是 | ok |

**英文全文**

```text
[x]<b>Deathrattle:</b> Give your <b>Deity</b>
+{0}/+{1}. <i>(Improved by
each Tavern spell you've
cast this game!)</i>
```

**中文全文（zhCN）**

```text
<b>亡语：</b>使你的<b>神明</b>获得+{0}/+{1}。<i>（在本局对战中你每施放一个酒馆法术都会提升！）</i>
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 2 | `TAG_SCRIPT_DATA_NUM_1` | 2 |
 | 3 | `TAG_SCRIPT_DATA_NUM_2` | 1 |
 | 45 | `HEALTH` | 5 |
 | 47 | `ATK` | 5 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 6 |
 | 200 | `CARDRACE` | 126 |
 | 202 | `CARDTYPE` | 4 |
 | 1429 | `BACON_TRIPLE_UPGRADE_MINION_ID` | 132332 |
 | 1440 | `TECH_LEVEL` | 5 |
 | 1456 | `IS_BACON_POOL_MINION` | 1 |
 | 1724 | `1` | 1 |
 | 4757 | `BACON_SUBSET_ABERRATION` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 16 个全部匹配）。

**官方机制 tag 未进数据层**（生成器白名单外；数据层无对应字段）

 | enumID | tag | 值 |
 |---|---|---|
 | 1724 | `1` | 1 |
 | 4757 | `BACON_SUBSET_ABERRATION` | 1 |

**数据层提示**

- 官方机制 tag 未进数据层（生成器白名单外）: `1(1724)=1`, `BACON_SUBSET_ABERRATION(4757)=1`

**审计对齐（engine-analyst / diff-harness）**

- 分类: 差分 TOP 卡（TVD 聚类）
- 引擎状态: Deity 聚类 TOP；同上
- 官方文本 vs 引擎实现: 非数据不符；TVD 由 Deity 状态缺口/脚本覆盖/外部附魔主导（EXACTNESS_STATUS §249-256：标 unsupported 后重算，不要求收敛）
- 依据: docs/DIFF_HARNESS.md §TOP；reversed/rea/round6_and_bb_top_analysis.md
- 缺失证据: harness 补 Deity 六字段（deity_card_id/atk/health/progress/awakened/sigil）与 oracle schema；真实 Power.log
- 处理: 不因此改数据/引擎

### `BG36_523` — Enterprising Escapee / 上进的逃兵

- 来源: `CardDefs.Bacon.xml` 行 208684；DBF **132762**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=23(PIRATE)、tech=5、atk/health=6/6、cost=3、rarity=None、armor=None
- 关键词: ∅；种族身份 tag: ∅；subsets: ['subset_pirate']
- ScriptDataNum: {1: 6, 3: 6, 4: 1}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{0}` | 1 | `TAG_SCRIPT_DATA_NUM_1` | 6 | 是 | ok |
 | `{2}` | 3 | `TAG_SCRIPT_DATA_NUM_3` | 6 | 是 | ok |
 | `{3}` | 4 | `TAG_SCRIPT_DATA_NUM_4` | 1 | 是 | ok |

**英文全文**

```text
[x]After you spend {2} Gold, get
a Lockbox. If you already have
one, it opens {3} |4(turn, turns) sooner
instead. <i>({0} Gold left!)</i>
```

**中文全文（zhCN）**

```text
在你花掉{2}枚铸币后，获取一张上锁宝箱。如果你已有宝箱，改为使其提前{3}回合打开。<i>（还剩{0}枚！）</i>
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 342 | `ARTISTNAME` | 0 |
 | 2 | `TAG_SCRIPT_DATA_NUM_1` | 6 |
 | 32 | `TRIGGER_VISUAL` | 1 |
 | 45 | `HEALTH` | 6 |
 | 47 | `ATK` | 6 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 7 |
 | 200 | `CARDRACE` | 23 |
 | 202 | `CARDTYPE` | 4 |
 | 1429 | `BACON_TRIPLE_UPGRADE_MINION_ID` | 132763 |
 | 1440 | `TECH_LEVEL` | 5 |
 | 1456 | `IS_BACON_POOL_MINION` | 1 |
 | 1596 | `BACON_SUBSET_PIRATE` | 1 |
 | 2519 | `BACON_EVOLUTION_CARD_ID` | 132766 |
 | 2889 | `TAG_SCRIPT_DATA_NUM_3` | 6 |
 | 2919 | `TAG_SCRIPT_DATA_NUM_4` | 1 |
 | 3047 | `BACON_TRIGGER_XY` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 18 个全部匹配）。

**官方机制 tag 未进数据层**（生成器白名单外；数据层无对应字段）

 | enumID | tag | 值 |
 |---|---|---|
 | 3047 | `BACON_TRIGGER_XY` | 1 |

**数据层提示**

- 官方机制 tag 未进数据层（生成器白名单外）: `BACON_TRIGGER_XY(3047)=1`

**审计对齐（engine-analyst / diff-harness）**

- 分类: 差分 TOP 卡（TVD 聚类）
- 引擎状态: Deity 聚类 TOP；同上
- 官方文本 vs 引擎实现: 非数据不符；TVD 由 Deity 状态缺口/脚本覆盖/外部附魔主导（EXACTNESS_STATUS §249-256：标 unsupported 后重算，不要求收敛）
- 依据: docs/DIFF_HARNESS.md §TOP；reversed/rea/round6_and_bb_top_analysis.md
- 缺失证据: harness 补 Deity 六字段（deity_card_id/atk/health/progress/awakened/sigil）与 oracle schema；真实 Power.log
- 处理: 不因此改数据/引擎

### `BG36_320_G` — Mysterious K'Thir / 神秘的克熙尔

- 来源: `CardDefs.Bacon.xml` 行 203092；DBF **134498**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=126(ABERRATION)、tech=5、atk/health=14/14、cost=3、rarity=None、armor=None
- 关键词: ∅；种族身份 tag: ∅；subsets: ∅
- ScriptDataNum: {1: 7, 2: 7, 3: 6}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{0}` | 1 | `TAG_SCRIPT_DATA_NUM_1` | 7 | 是 | ok |
 | `{1}` | 2 | `TAG_SCRIPT_DATA_NUM_2` | 7 | 是 | ok |
 | `{2}` | 3 | `TAG_SCRIPT_DATA_NUM_3` | 6 | 是 | ok |

**英文全文**

```text
[x]At the end of your turn,
discard your {2} left-most
Tavern spells. Gain +{0}/+{1}
for each discarded.
```

**中文全文（zhCN）**

```text
在你的回合结束时，弃掉你最左边的{2}张酒馆法术牌。每弃掉一张，便获得+{0}/+{1}。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 2 | `TAG_SCRIPT_DATA_NUM_1` | 7 |
 | 3 | `TAG_SCRIPT_DATA_NUM_2` | 7 |
 | 45 | `HEALTH` | 14 |
 | 47 | `ATK` | 14 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 6 |
 | 200 | `CARDRACE` | 126 |
 | 202 | `CARDTYPE` | 4 |
 | 1440 | `TECH_LEVEL` | 5 |
 | 1471 | `BACON_TRIPLED_BASE_MINION_ID` | 134497 |
 | 2889 | `TAG_SCRIPT_DATA_NUM_3` | 6 |
 | 3744 | `END_OF_TURN_TRIGGER` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 15 个全部匹配）。

**官方机制 tag 未进数据层**（生成器白名单外；数据层无对应字段）

 | enumID | tag | 值 |
 |---|---|---|
 | 3744 | `END_OF_TURN_TRIGGER` | 1 |

**数据层提示**

- 官方机制 tag 未进数据层（生成器白名单外）: `END_OF_TURN_TRIGGER(3744)=1`

**审计对齐（engine-analyst / diff-harness）**

- 分类: 差分 TOP 卡（TVD 聚类）
- 引擎状态: Deity 聚类 TOP；同上
- 官方文本 vs 引擎实现: 非数据不符；TVD 由 Deity 状态缺口/脚本覆盖/外部附魔主导（EXACTNESS_STATUS §249-256：标 unsupported 后重算，不要求收敛）
- 依据: docs/DIFF_HARNESS.md §TOP；reversed/rea/round6_and_bb_top_analysis.md
- 缺失证据: harness 补 Deity 六字段（deity_card_id/atk/health/progress/awakened/sigil）与 oracle schema；真实 Power.log
- 处理: 不因此改数据/引擎

### `BG36_106_G` — Cutthroat K'Thir / 克熙尔割喉者

- 来源: `CardDefs.Bacon.xml` 行 198353；DBF **131711**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=126(ABERRATION)、tech=4、atk/health=8/8、cost=3、rarity=None、armor=None
- 关键词: ∅；种族身份 tag: ∅；subsets: ∅
- ScriptDataNum: {1: 8, 2: 8}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{0}` | 1 | `TAG_SCRIPT_DATA_NUM_1` | 8 | 是 | ok |
 | `{1}` | 2 | `TAG_SCRIPT_DATA_NUM_2` | 8 | 是 | ok |

**英文全文**

```text
Whenever you discard a card, give this and your <b>Deity</b> +{0}/+{1}.
```

**中文全文（zhCN）**

```text
每当你弃掉一张牌，使本随从和你的<b>神明</b>获得+{0}/+{1}。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 2 | `TAG_SCRIPT_DATA_NUM_1` | 8 |
 | 3 | `TAG_SCRIPT_DATA_NUM_2` | 8 |
 | 32 | `TRIGGER_VISUAL` | 1 |
 | 45 | `HEALTH` | 8 |
 | 47 | `ATK` | 8 |
 | 183 | `CARD_SET` | 1453 |
 | 199 | `CLASS` | 6 |
 | 200 | `CARDRACE` | 126 |
 | 202 | `CARDTYPE` | 4 |
 | 1440 | `TECH_LEVEL` | 4 |
 | 1471 | `BACON_TRIPLED_BASE_MINION_ID` | 131710 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 14 个全部匹配）。

**审计对齐（engine-analyst / diff-harness）**

- 分类: 差分 TOP 卡（TVD 聚类）
- 引擎状态: Deity 聚类 TOP；同上
- 官方文本 vs 引擎实现: 非数据不符；TVD 由 Deity 状态缺口/脚本覆盖/外部附魔主导（EXACTNESS_STATUS §249-256：标 unsupported 后重算，不要求收敛）
- 依据: docs/DIFF_HARNESS.md §TOP；reversed/rea/round6_and_bb_top_analysis.md
- 缺失证据: harness 补 Deity 六字段（deity_card_id/atk/health/progress/awakened/sigil）与 oracle schema；真实 Power.log
- 处理: 不因此改数据/引擎

### `BG32_821` — Felfire Conjurer / 邪火咒龙

- 来源: `CardDefs.Bacon.xml` 行 124283；DBF **120299**；build 255130 (37.0.0)
- 类型/种族/身材: card_type=4(MINION)、race=24(DRAGON)、tech=5、atk/health=6/5、cost=3、rarity=None、armor=None
- 关键词: ∅；种族身份 tag: ['DEMON']；subsets: ['subset_demon', 'subset_dragon']
- ScriptDataNum: {1: 1, 2: 1}

 | 占位符 | ScriptDataNum | XML tag | 值 | 文本出现 | 状态 |
 |---|---|---|---|---|---|
 | `{0}` | 1 | `TAG_SCRIPT_DATA_NUM_1` | 1 | 是 | ok |
 | `{1}` | 2 | `TAG_SCRIPT_DATA_NUM_2` | 1 | 是 | ok |

**英文全文**

```text
[x]At the end of your turn,
your Tavern spells give
an extra +{0}/+{1}
this game.
```

**中文全文（zhCN）**

```text
在你的回合结束时，你的酒馆法术在本局对战中使随从额外获得+{0}/+{1}。
```

**官方相关 tag**（`enumID` / 名称 / 值；完整列表见 JSON）

 | enumID | tag | 值 |
 |---|---|---|
 | 2 | `TAG_SCRIPT_DATA_NUM_1` | 1 |
 | 3 | `TAG_SCRIPT_DATA_NUM_2` | 1 |
 | 45 | `HEALTH` | 5 |
 | 47 | `ATK` | 6 |
 | 183 | `CARD_SET` | 1453 |
 | 200 | `CARDRACE` | 24 |
 | 202 | `CARDTYPE` | 4 |
 | 1429 | `BACON_TRIPLE_UPGRADE_MINION_ID` | 120300 |
 | 1440 | `TECH_LEVEL` | 5 |
 | 1456 | `IS_BACON_POOL_MINION` | 1 |
 | 1591 | `BACON_SUBSET_DRAGON` | 1 |
 | 1593 | `BACON_SUBSET_DEMON` | 1 |
 | 3744 | `END_OF_TURN_TRIGGER` | 1 |

**当前 `data/` 一致性**

- ✅ 一致（记录来源: `bg_cards.json`；期望字段 18 个全部匹配）。

**官方机制 tag 未进数据层**（生成器白名单外；数据层无对应字段）

 | enumID | tag | 值 |
 |---|---|---|
 | 3744 | `END_OF_TURN_TRIGGER` | 1 |

**数据层提示**

- 官方机制 tag 未进数据层（生成器白名单外）: `END_OF_TURN_TRIGGER(3744)=1`

**审计对齐（engine-analyst / diff-harness）**

- 分类: 差分 TOP 卡（TVD 聚类）
- 引擎状态: Deity 聚类 TOP（+ 玩家侧 BG34_320）；同上
- 官方文本 vs 引擎实现: 非数据不符；TVD 由 Deity 状态缺口/脚本覆盖/外部附魔主导（EXACTNESS_STATUS §249-256：标 unsupported 后重算，不要求收敛）
- 依据: docs/DIFF_HARNESS.md §TOP；reversed/rea/round6_and_bb_top_analysis.md
- 缺失证据: harness 补 Deity 六字段（deity_card_id/atk/health/progress/awakened/sigil）与 oracle schema；真实 Power.log
- 处理: 不因此改数据/引擎

## 3. 差异/错误清单与处置

- **数据层差异 0 处**：本清单所有卡在当前 `data/` 中与官方 255130 CardDefs 一致（文本/数值/参数/关键词/池标志）。
- Moonsteel/Geomagus/C 类/Deity split/Minor Hymn/差分 TOP 的差异均在**引擎实现或证据缺口**层；按任务约定不改数据，由 Lead/engine-analyst 按台账排期。
- 若未来 CardDefs 更新（新 build），用 `tools/version_sync.py --dry-run` 重跑差分；本表可作为逐卡复核基线。

### 3.1 全量巡检发现（候选清单之外的数据层问题）

**A. Activate 卡缺 `INTERACTABLE_OBJECT_COST(4090)`：11 条记录**（官方 255130 CardDefs 只有 4089、无 4090）

| card_id | 名称 | 文本（EN 摘录） | data 现状 | DBF/来源 |
|---|---|---|---|---|
| `BG28_582` | Mangled Bandit | <b>Activate ({1}):</b> Discard a card to get {0} <b><b>Blood Gems</b>.</b> | activate=True, activate_cost=None | 104764 / `CardDefs.Bacon.xml`:CardDefs.Bacon.xml:66875 |
| `BG28_582_G` | Mangled Bandit | <b>Activate ({1}):</b> Discard a card to get {0} <b><b>Blood Gems</b>.</b> | activate=True, activate_cost=None | 104765 / `CardDefs.Bacon.xml`:CardDefs.Bacon.xml:66950 |
| `BG36_099` | Brain Rotter | <b>Activate ({2}):</b> Discard a card to give your <b>Deity</b> +{0}/+{1}. | activate=True, activate_cost=None | 131696 / `CardDefs.Bacon.xml`:CardDefs.Bacon.xml:197568 |
| `BG36_099_G` | Brain Rotter | <b>Activate ({2}):</b> Discard a card to give your <b>Deity</b> +{0}/+{1}. | activate=True, activate_cost=None | 131697 / `CardDefs.Bacon.xml`:CardDefs.Bacon.xml:197647 |
| `BG36_300` | N'raqi Frostcaller | [x]<b>Activate ({2}):</b> Discard a card for your Tavern spells to give _an extra +{0}/+{1 | activate=True, activate_cost=None | 132136 / `CardDefs.Bacon.xml`:CardDefs.Bacon.xml:202055 |
| `BG36_300_G` | N'raqi Frostcaller | [x]<b>Activate ({2}):</b> Discard a card for your Tavern spells to give _an extra +{0}/+{1 | activate=True, activate_cost=None | 132137 / `CardDefs.Bacon.xml`:CardDefs.Bacon.xml:202134 |
| `BG36_311` | Abyssal Envoy | [x]<b>Activate ({0}):</b> Discard a card to get a random Tavern spell. | activate=True, activate_cost=None | 132213 / `CardDefs.Bacon.xml`:CardDefs.Bacon.xml:202577 |
| `BG36_311_G` | Abyssal Envoy | [x]<b>Activate ({0}):</b> Discard a card to get 2 random Tavern spells. | activate=True, activate_cost=None | 132214 / `CardDefs.Bacon.xml`:CardDefs.Bacon.xml:202655 |
| `BG36_312` | Mindbending Recruiter | <b>Activate ({0}):</b> Discard a card to get a random Aberration. | activate=True, activate_cost=None | 132215 / `CardDefs.Bacon.xml`:CardDefs.Bacon.xml:202733 |
| `BG36_312_G` | Mindbending Recruiter | <b>Activate ({0}):</b> Discard a card to get 2 random Aberrations. | activate=True, activate_cost=None | 132216 / `CardDefs.Bacon.xml`:CardDefs.Bacon.xml:202815 |
| `BGMinionAbilityTest` | Test BG minion ability | <b>Activate:</b> Give a minion +1/+1 (one per turn) | activate=True, activate_cost=None | 132120 / `CardDefs.Bacon.xml`:CardDefs.Bacon.xml:239864 |

> 影响：这些卡在当前数据里 `activate=True` 但 `activate_cost=None`；引擎 `CardDef.activate_cost`/`is_activate_minion` 会判为非 Activate（卡面有 `Activate ({N})` 费用占位符却没有静态值）。其中**池内本体 5 张**（`BG28_582`/`BG36_099`/`BG36_300`/`BG36_311`/`BG36_312`，其余为金色变体）；`BGMinionAbilityTest` 为测试 token，可忽略。
> 处置建议（**不改数据**，待 Lead/engine-analyst 裁定）：① 官方 CardDefs 确实缺 4090，生成器不应臆造成本；② 引擎可增加'文本占位符无 tag'的告警/兜底（需规则裁定）；③ 后续客户端/官方数据补 tag 后走 `tools/version_sync.py --check`。

**B. 候选卡占位符无静态 ScriptDataNum：3 张**（文本 `{N}` 在 CardDefs 无对应 NUM 值）

| card_id | 名称 | 占位符 | 状态 | 文本（EN 摘录） |
|---|---|---|---|---|
| `BG31_035` | Groundbreaker | `{0}` | NUM_WITHOUT_PLACEHOLDER（脚本可能以卡 id 引用） | [x]After you play a Naga, gain +{1}/+{1}. <i>(Improved by every 3 spells you've  |
| `BG31_035` | Groundbreaker | `{2}` | PLACEHOLDER_WITHOUT_NUM（CardDefs 无该槽位或值为 0） | [x]After you play a Naga, gain +{1}/+{1}. <i>(Improved by every 3 spells you've  |
| `BG35_701` | Brazen Buccaneer | `{2}` | PLACEHOLDER_WITHOUT_NUM（CardDefs 无该槽位或值为 0） | [x]At the end of your turn, give your left-most Pirate +{0}/+{1}. Repeat for eac |
| `BG36_300` | N'raqi Frostcaller | `{2}` | PLACEHOLDER_WITHOUT_NUM（CardDefs 无该槽位或值为 0） | [x]<b>Activate ({2}):</b> Discard a card for your Tavern spells to give _an extr |

> 这些多为**动态进度/费用显示槽**（如 `({2})` 当前进度、`(repeats {2})`、Activate 费用），官方 CardDefs 只给文本占位符而不给静态 NUM；generator 的导出（None）与 CardDefs 一致，**不应补 0 或猜值**；脚本按事件计数/文本字面量处理。

## 4. 与 engine-analyst 的对齐口径

按每张卡的 `audit.mismatch_class` 归类（逐卡明细见 §2 各卡「审计对齐」；机器可读见 JSON `cards[].audit`）：

| 判定 | 卡 | 需要什么 |
|------|----|----------|
| 官方文本 vs 引擎实现不符（未实现） | `BG31_171` | 官方数值序列/Notes；按批次补脚本/机制 |
| 官方文本 vs 引擎实现不符（未实现）+ 规则多解 | `BG28_583` | 官方触发链上限证据（Geomagus） |
| 文本多解/需日志证据（tag 槽位语义） | `BGS_004` | 真实 BG Power.log 的逐事件 tag |
| 文本多解/需日志证据（槽位语义 + 触发链） | `BG31_035` | 官方 tag 槽位语义 + 事件级日志 |
| 文本多解/需日志证据（rewind 快照/触发计数） | `BG26_174` | Power.log + wiki Notes |
| 文本多解/需日志证据（重复次数 vs Buff 值） | `BG35_701` | 官方 tag 语义 |
| 文本多解/需日志证据（公式） | `BG32_822` | 官方 Improve 公式 + 金色 num 语义 |
| 文本多解/需日志证据（计数语义） | `BG33_155` | 官方 trigger 计数 tag 语义 |
| 非文本不符（动态状态/测量口径） | `BG35_921`, `BG35_921_G`, `BG35_342`, `BG35_342_G`, `BG36_524`, `BG36_524_G`, `BG25_008`, `BG25_008_G`, `BG25_013`, `BG25_013_G`, `BG_TTN_401`, `BG_TTN_401_G`, `BG26_537`, `BG26_537_G` | P2b/P5：真实 Power.log 逐事件数值可消除文本回退表（无需改数据） |
| 非文本不符（饰品可见性/测量口径） | `BG36_MagicItem_216` | P4：traceizer 扩展 trinkets[]（饰品 tag 可见性），非引擎 bug |
| 官方文本多解/需官方证据（split 的整除/余数/顺序/目标数） | `BGFYM_000`, `BGFYM_000_G`, `BGFYM_011`, `BGFYM_011_G`, `BG_OldGod` | 真实 Power.log 的 awaken 分配结果/官方 Notes（禁止用 BB 反推） |
| 官方文本 vs 引擎实现不符（未实现）+ 招募期技能（对战斗无直接影响） | `BG26_HERO_102p2` | 英雄技能批次实现 |
| 无（对照） | `BG26_HERO_102p`, `BG26_HERO_102` | 无需动作（对照组） |
| 非数据不符；TVD 由 Deity 状态缺口/脚本覆盖/外部附魔主导（EXACTNESS_STATUS §249-256：标 unsupported 后重算，不要求收敛） | `BG34_694`, `BG35_432`, `BG32_835`, `BG34_926`, `BG34_320`, `BG36_300`, `BG36_318`, `BG36_523`, `BG36_320_G`, `BG36_106_G`, `BG32_821` | 见 JSON audit.needs |

**补充**：
- `BG34_320`（The Last One Standing）在 `diff_top` 分组，`audit.mismatch_class` 指向 TVD/Deity 状态缺口；同时 `EXACTNESS_STATUS` 将 'Rally + ALL 多重选取' 列为观察项（F-11），如需单独裁定可复用本表文本/参数证据。
- 差分 TOP 卡的 TVD 是**采样指标**：`EXACTNESS_STATUS` 明确 C'Thun split 是已知证据 gap，不应作为收敛目标；Deity 聚类需 harness 补六字段后重算（见 `round6_and_bb_top_analysis.md`）。

## 5. 复现

```powershell
cd C:\HSagent
python tmp_255130\carddefs_authority.py
```

机器可读: `reversed/rea/carddefs_authority_round2.json`
