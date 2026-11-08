# 复利链条（compound chains）：文本挖矿 → 流派核心牌集 → 先验 → 沙盒验证

> 状态：**挖矿已实现**（`scripts/mine_compound_cards.py` → `data/scaling/compound_cards.json`）、
> **先验已实现且默认关**（`hsbg/az/train/compound_prior.py`，`--compound-prior-coef 0`、
> `--archetype-background-penalty 0`，`coef=0` 逐位等价旧路径）、**沙盒 A/B/C 三组已跑**
> （§5）。单测 `tests/test_compound_prior.py`（15 条）。
>
> 一句话：酒馆战棋的强度是**复利**的，不是线性的。复利链条只有两类 —— **乘数**
> （`double` / `twice` / `for each` / `each time`）与**几何级数/累加**
> （`permanently` / `this game` / `an extra +1/+1` / `consume` / `improve this`）。
> 从卡牌文本里按这两类挖出核心牌 → 按流派编成核心牌集 → 训练时给「买/选当前流派
> 核心牌」加一个**软先验**（+coef），给「买/选别的部落非公用核心牌」加**背景惩罚**
> （-penalty），让 3.5M 小模型更快找到给定阵容的解法。

## 1. 两类复利链条（用户洞察 → 可判定的文本证据）

| 类 | 机制 | 复利从哪里来 | 代表性文本 |
|---|---|---|---|
| **乘数** `multiplier` | 某个效果「每触发一次就再乘一层」 | 同一次触发被放大 N 倍 / 按数量重复 | `Your end of turn effects trigger twice.` `Has +7/+7 **for each** Golden minion you've played this game.` `**Repeat for each** friendly Golden minion.` |
| **累加/几何级数** `accumulator` | 把某个量**永久**抬高，之后每次触发都从更高基线起步 | 永久增量累加（tier2 的 1 点，到 tier6 变成每回合 10+ 点） | `Whenever you cast a Tavern spell, give Elementals in the Tavern +4/+3 **this game**.` `… give minions in the Tavern +2/+2 **this game**. **Activate (1): Improve this.**` |
| **触发链** `trigger_chain`（引信） | 本身不复利，但决定乘数/累加**触发多少次** | 触发次数 → 乘数/累加的底数 | `Whenever you …` / `After you …` / `Rally:` / `Deathrattle:` / `Battlecry:` / `Avenge (n):` |

关键点：**「this game」+「an extra +X/+X」是最强的复利形态** —— 每一次酒馆法术施放
都永久抬高之后**所有**随从的基线，法术数 × 永久增量的乘积就是 Σ 的几何增长。这也是
`data/scaling/carriers.json` 里 11 张「施法载体」的共同文本骨架（见 §2.4）。

## 2. 文本挖矿（`scripts/mine_compound_cards.py`）

### 2.1 规则表（英文 + 中文双重取证）

规则 = `(name, en_regex, zh_regex, weight, note)`，英文在 `text.lower()` 上、中文在
`text_zh` 上各匹配一次，任一命中即算（与 `scripts/carrier_common.py` 的双重取证同口径）。

| 类 | 规则（权重） |
|---|---|
| 乘数 | `triple`(4.0)、`double`(3.0)、`repeat_for_each`(3.0)、`twice`(2.5)、`for_each`(2.0)、`each_time`(2.0)、`every_time`(2.0)、`for_every`(2.0)、`per_each`(1.0) |
| 累加 | `permanently`(3.0)、`this_game`(3.0)、`an_extra`(2.5)、`improved_by`(2.5)、`consume`(2.5)、`this_gains`(2.5)、`blood_gem_extra`(2.5)、`keeps_gained`(2.0)、`gain_xx`(2.0)、`grow`(2.0)、`golden_keep`(2.0)、`increase`(1.5) |
| 触发链 | `whenever_you`(2.0)、`rally`(2.0)、`avenge`(2.0)、`whenever_friendly`(1.5)、`after_you`(1.5)、`deathrattle`(1.5)、`battlecry`(1.0)、`end_of_turn`(1.0)、`start_of_combat`(1.0)、`activate`(1.0) |
| **噪声**（不打复利分） | `maximum gold` / `costs Health instead of Gold` / `Triple Reward` / `Discover a …` / `Bounties` → 分数 ×0.25 且**不进**核心牌集（它们是经济/奖励机制，不是战斗复利） |

分数：`score = 1.0·乘数分 + 1.0·累加分 + 0.35·触发链分`，其中乘数分含 `+X/+X` 幅度
（`min(3, (X+Y)/10)`）；再乘 **tier 可得性加成** `1 + 0.10·max(0, 6-tier)`（越早成型越强）。
核心牌资格 = `kind=minion` + `tier<=5` + `in_pool` + `implemented` + 非噪声。

数据源：`rust/crates/hsbg-engine/data/cards.json`（文本/种族/tier）+
`hsbg_engine.catalog_json()`（`in_pool` 683 张 / `implemented` / `tier7`）。
`--check` 幂等（重跑逐位一致，`meta.generated_at` 除外）。

### 2.2 统计（`data/scaling/compound_cards.json` 的 `meta.counts`）

| 口径 | 全部卡表 | 池内（`in_pool`） |
|---|---|---|
| 卡表总数 | 3,983 | 683 |
| 命中（任一类） | **2,759** | 429 |
| **乘数** `multiplier` | **628** | **94** |
| **累加** `accumulator` | **1,218** | **185** |
| **触发链** `trigger_chain` | **2,150** | **314** |
| 乘数 ∩ 累加（真·复利） | **240** | 24 |
| 核心牌资格 | — | **169**（13 组种族核心 / 27 个头部流派核心） |
| 公用牌 `common_ids` | — | **20**（空种族/`ALL` 融合怪 + 多族卡） |

按种族分布（池内/全量，取奇数项；完整表在 JSON `meta.tribe_dist`）：

| 种族 | 乘数 | 累加 | 触发链 |
|---|---|---|---|
| NEUTRAL（无种族） | 76 / 275 | 94 / 472 | 138 / 679 |
| ABERRATION | 1 / 6 | 15 / 36 | 20 / 50 |
| BEAST | 2 / 43 | 8 / 99 | 19 / 206 |
| DEMON | 1 / 38 | 16 / 101 | 16 / 136 |
| DRAGON | 1 / 33 | 9 / 74 | 17 / 165 |
| ELEMENTAL | 2 / 57 | 8 / 68 | 15 / 126 |
| MECHANICAL | 2 / 39 | 9 / 73 | 17 / 183 |
| MURLOC | 2 / 34 | 8 / 80 | 19 / 148 |
| PIRATE | 3 / 41 | 6 / 66 | 18 / 142 |
| QUILBOAR | 0 / 19 | 7 / 44 | 16 / 112 |
| UNDEAD | 2 / 32 | 7 / 88 | 17 / 198 |
| NAGA | 0 / 26 | 0 / 50 | 1 / 85 |
| ALL（融合怪） | 2 / 21 | 2 / 22 | 7 / 32 |

读法：**「累加」远比「乘数」多**（1,218 vs 628）—— 因为这一版环境的复利主要靠
「永久增量」（`this game` / `an extra +1/+1`）而不是 `double`；而「乘数 ∩ 累加」的
240 张才是真正一条链上两种机制都占的牌（核心牌集里分数最高的基本都是这批）。
NAGA 在池内只剩 1 张随从（池子被裁过），所以它的核心牌集天然只有 1 张 —— 是**数据
现实**，不是挖矿漏了。

### 2.3 代表卡（按复利分数，池内 + tier≤5，共 16 张）

| id | 名称 | tier | 种族 | 类 | 分数 | 文本片段 |
|---|---|---|---|---|---|---|
| BG30_123 | 无畏的食客 | 3 | QUILBOAR | 累加 | 23.7 | `Choose One - Your Blood Gems give an extra +1/+1 this game` |
| BG33_885 | 鲜血精研者 | 5 | QUILBOAR | 累加+触发 | 20.9 | `Rally: Your Blood Gems give an extra +1/+2 this game.` |
| BG25_008 | 永恒骑士 | 2 | UNDEAD | 乘数+累加 | 19.0 | `Has +4/+2 for each friendly Eternal Knight that died this game` |
| BG33_828 | 舰长尤朵拉 | 5 | PIRATE | 累加+触发 | 17.9 | `Deathrattle: give your minions +6/+6. Golden ones keep it permanently.` |
| BG32_860 | 浅鳍秘法师 | 3 | MURLOC | 累加 | 17.2 | `When you sell this, your Tavern spells give an extra +1/+1 this game.` |
| BG32_337 | 海鲜乱炖 | 3 | — | 乘数+累加 | 15.9 | `Give a minion +1/+1. Repeat for each different Bonus Keyword in your warband.` |
| BG32_237 | 新锐植物学家 | 2 | — | 累加 | 15.4 | `Choose One - Your Tavern spells give an extra +1 Attack this game; or +1 Health.` |
| BG32_821 | 邪火咒龙 | 5 | DRAGON/DEMON | 累加+触发 | 15.3 | `At the end of your turn, your Tavern spells give an extra +1/+1 this game.` |
| BG33_830 | 艾萨拉的刀客 | 3 | PIRATE | 累加+触发 | 15.2 | `Battlecry: Your Tavern spells give an extra +1 Attack this game.` |
| BG33_924 | 蓝色雏龙 | 3 | DRAGON | 累加+触发 | 15.2 | `Rally: Your Tavern spells give an extra +1 Health this game.` |
| BG32_235 | 冲浪的希尔梵 | 2 | PIRATE | 乘数+触发 | 15.0 | `… give adjacent minions +1 Attack. Repeat for each friendly Golden minion.` |
| BG36_300 | 恩拉其唤冰者 | 5 | ABERRATION | 累加+触发 | 14.9 | `Activate (0): Discard a card for your Tavern spells to give an extra +1/+1 this game.` |
| BG36_362 | 牺牲的愤怒卫士 | 4 | DEMON | 累加+触发 | 14.8 | `Deathrattle: Give minions in the Tavern +2/+2 this game. Activate (1): Improve this.` |
| BG32_880 | 友善的恶鬼 | 4 | UNDEAD | 累加+触发 | 14.5 | `Deathrattle: Your Tavern spells give an extra +1 Attack this game.` |
| BG21_015 | 泰蕾苟萨 | 2 | DRAGON | 累加 | 14.0 | `This permanently keeps Bonus Keywords and stats gained in combat.` |
| BG36_114 | 寄生血肉兽幼崽 | 4 | ABERRATION | 累加+触发 | 13.9 | `At the end of your turn, give your left-most minion +2/+2. (Improved by each card you've discarded this game!)` |

纯乘数的最强代表（与上表互补）：
`BG26_ICC_901 达卡莱附魔师 t5「Your end of turn effects trigger twice.」`、
`BG_LOE_077 布莱恩·铜须 t5「Your Battlecries trigger twice.」`、
`BG26_802 香蕉猛猿 t4「After you summon a Beast in combat, double its Attack.」`、
`BG35_883 幻影 t6「Your spells that target friendly minions cast twice.」`。

### 2.4 与 `carriers.json` 的重叠（先验最该抓的那批）

`carriers.json` 的 22 个 primary id（11 张载体 + 金色）**全部**被挖到：

- 命中 **乘数** 的载体 5 个（`BG27_005_G`、`BG28_633_G`、`BG28_707_G`、`BG36_640_G`、`BG36_853_G` —— 金色版文本里的 `twice`）；
- 命中 **累加** 的载体 14 个（`this game` / `permanently` 骨架）；
- 命中 **触发链** 的载体 22 个（全部是 `Whenever/After you cast …`）；
- 进**核心牌集**的载体 6 个：`BG28_633`（Felboar，QUILBOAR/DEMON）、`BG28_707`（Living Azerite，ELEMENTAL）、`BG36_108`（Vicious Mindslasher，ABERRATION）、`BG36_703`/`BG36_704`（MURLOC）、`BG36_762`（Devilish Distractor，DEMON）。

也就是说：**载体清单 ⊂ 复利牌集**，而挖矿额外补上了「没有载体但同样复利」的一批
（血宝石/甲虫/酒馆 buff/金色/弃牌成长），这正是用户「通过文本 brainstorm 玩法核心牌」
想要的覆盖面。

## 3. 流派核心牌集（`core` 段）

`core.by_tribe`（13 组，按分数降序；`id 名称(tier,分数)`）：

| 种族 | 核心牌 |
|---|---|
| ABERRATION | BG36_300 恩拉其唤冰者(t5,15) / BG36_114 寄生血肉兽幼崽(t4,14) / BG36_318 无面转化者(t5,13) / BG36_320 神秘的克熙尔(t5,9) / BG36_106 克熙尔割喉者(t4,5) / BG36_108 残忍的精神鞭笞者(t3,5) |
| ALL | BG36_360t6 黑暗悖论体(t3,12) / BG36_360t3(t2,2) / BG32_111 梦魇茶客(t5,2) / BG36_360t5(t4,1) |
| BEAST | BG31_801 森林游虫(t2,11) / BG35_602 深潜巨兽(t5,11) / BG31_809 绿松石飞掠虫(t5,6) / BG36_202 美味龙虾(t3,4) / BG26_802 香蕉猛猿(t4,4) / BG36_207 狼宝宝(t3,4) |
| DEMON | BG32_821 邪火咒龙(t5,15) / BG36_362 牺牲的愤怒卫士(t4,15) / BG33_155 虔诚的萨特唤魔者(t3,14) / BG36_762 恶魔干扰者(t5,11) / BGS_004 愤怒编织者(t1,7) / BG23_357 心灵泥魔(t2,4) |
| DRAGON | BG32_821 邪火咒龙(t5,15) / BG33_924 蓝色雏龙(t3,15) / BG21_015 泰蕾苟萨(t2,14) / BG29_813 执念诗心龙(t4,12) / BG36_364 希望信使(t5,10) / BG36_245 符文奥术师(t4,7) |
| ELEMENTAL | BG31_815 沙丘土著(t1,13) / BG34_865 爆焰灯神(t4,13) / BG34_856 幼体水波(t3,13) / BG28_707 活化艾泽里特(t5,11) / BG34_500 魔焰执行者(t4,4) / BG36_181 空气投球手(t4,3) |
| MECHANICAL | BG34_170t3 绿色扩音机(t2,9) / BG35_341 附魔哨卫(t4,9) / BG34_170t 红色扩音机(t2,8) / BG34_170t2 蓝色扩音机(t2,8) / BG31_177 机械侏儒解译者(t2,5) / BG36_851 火花破坏机(t5,4) |
| MURLOC | BG32_860 浅鳍秘法师(t3,17) / BG31_148 黑客鱼人(t5,12) / BG26_137 裁脍鱼人(t4,7) / BG36_703 暮光猎潮者(t4,6) / BG36_704 萨满招潮者(t5,4) / BG36_700 下水道逃生鱼人(t5,4) |
| NAGA | BG32_820 火鳞囤积者(t5,2)（池内仅此 1 张） |
| NEUTRAL | BG32_237 新锐植物学家(t2,15) / BG32_341 胡蒙格斯(t4,9) / BG26_ICC_901 达卡莱附魔师(t5,6) / BG_LOE_077 布莱恩·铜须(t5,6) / BG36_345 可疑的监狱守卫(t1,4) / BG23_318 莽神火车王(t5,1) |
| PIRATE | BG33_828 舰长尤朵拉(t5,18) / BG33_830 艾萨拉的刀客(t3,15) / BG32_235 冲浪的希尔梵(t2,15) / BG36_524 海上勒索师(t4,11) / BG26_810 火药运输工(t4,5) / BG26_814 苦情民谣歌手(t4,4) |
| QUILBOAR | BG30_123 无畏的食客(t3,24) / BG33_885 鲜血精研者(t5,21) / BG33_883 剃刀沼泽织藤者(t5,7) / BG28_633 邪能野猪人(t5,3) / BG30_121 热气球测绘员(t4,3) / BG34_682 剃刀沼泽舞扇者(t4,2) |
| UNDEAD | BG25_008 永恒骑士(t2,19) / BG32_880 友善的恶鬼(t4,14) / BG25_013 腐皮豺狼人(t1,10) / BG25_011 死亡群居蛛魔(t2,9) / BG34_690 疫病行尸(t4,8) / BG36_511 丧钟死灵(t4,6) |

**按机制分组**（`core.by_mechanism`，与种族正交）：`deathrattle` / `battlecry` / `rally` /
`avenge` / `choose_one` / `spell_scaling` / `tavern_buff` / `blood_gem` / `consume` /
`discard` / `golden` / `end_of_turn` / `magnetic` / `divine_shield` / `self_damage`。
例如 `spell_scaling` 组前四：BG32_860(17) / BG32_237(15) / BG32_821(15) / BG33_830(15)。

**按头部流派**（`core.by_archetype`，27 个 = `data/archetype/archetype_table.json` 的
全部 archetype，用 `tribe_family` 取种族候选 + 名字 token 对应的机制加成 +1.5 重排）。
例：

- `demon_boost_shop`（DEMON + `tavern_buff`）：BG36_362 / BG32_821 / BG33_155 / BG36_762 / BGS_004 / BG36_621
- `quilboar_gem_spam`（QUILBOAR + `blood_gem`）：BG30_123 / BG33_885 / BG33_883 / BG30_121 / BG34_682 / BG28_633
- `undead_butcher`（UNDEAD + `deathrattle`）：BG25_008 / BG32_880 / BG25_013 / BG34_690 / BG25_011 / BG25_022
- `beast_lobster`（BEAST + `spell_scaling`）：BG31_801 / BG35_602 / BG31_809 / BG36_202 / BG26_802 / BG36_207

`core.common_ids`（20 张「公用牌」，背景惩罚**永不**罚）：无种族 / `ALL` 融合怪（如
BG26_ICC_901、BG_LOE_077、BG36_345、BG36_360t6）+ 多族卡（如 BG32_821 DRAGON/DEMON）。
特别注意：**全流派最强的部落牌也不算公用牌**（BG30_123 仍是 QUILBOAR 专属）——否则
「给定流派后把别的部落压到背景权重」就压不动了。

## 4. 先验机制（`hsbg/az/train/compound_prior.py`，默认关）

### 4.1 偏置落在哪

| 动作段 | 落点 | 值 |
|---|---|---|
| `Buy 8..15` | 酒馆槽位的卡 id（`cards[SLICE_CARD_SHOP]`） | 属于**当前流派核心牌** → `+coef`；属于**其它流派核心牌且非公用** → `-penalty` |
| `Choose 30..45` | 发现/抉择/饰品选项的卡 id（`cards[SLICE_CARD_CHOICES]`） | 同上 |
| 其它（升 tier / roll / 卖 / 换位 / 磁力 / EndTurn） | — | 恒 0（节奏交给 `archetype_bias` 的偏好表） |

硬约束：`coef=0 且 penalty=0` → **不构造对象**、不读卡表、`bias()` 恒 `None` →
与旧路径**逐位等价**；只给**合法**动作写值（`bias[~mask]=0`）；`+coef` 侧**只加不减**；
clip 到 `[-penalty, +coef]`。

### 4.2 流派判定（优先级）

1. `--compound-archetype`（受控实验/评测用；A/B/C 就是 `DEMON`）；
2. 现有两段式分类器 `data/archetype/archetype_model.npz`（**复用**
   `archetype_bias.parse_obs` / `ArchetypeHistory` 的同一套特征，不会两侧漂移）：
   `max(p_arch) >= 0.6` 且非 `other` → 头部流派；否则 `max(p_tribe) >= 0.6` → 种族；
3. 退化：**场上（×2）+ 手牌（×1）最多种族**（只需观测，无模型也能跑）；
4. 都没有 → `core.global`（全流派通用核心，仍能加分）。

### 4.3 与 PPO 的相容性（关键设计）

**有偏采样 / 无偏似然**：采样用 `softmax(logits + bias)`，但记录的 `logprob` 仍是
**无 bias** 的 `log_softmax(logits)` 在所选动作上的值。于是 `ratio = exp(new-old)` 在
第一次更新时严格等于 1 —— 不会被 `approx_kl` 早停打掉（这正是历史 bug 家族），
而梯度会把策略往先验偏好的动作推（等价于用先验做行为整形）。
`bias=None` 时走**完全旧的代码路径**（连 `logp_all.exp()` 都保留），逐位等价。

### 4.4 接口与 CLI

```python
from hsbg.az.train.compound_prior import CompoundPrior, engine_card_id_lookup, core_ids_for
prior = CompoundPrior(coef=1.0, background_penalty=1.0, archetype="DEMON",
                      card_index_of=engine_card_id_lookup())
bias = prior.bias(features, cards, mask, game_id=seed, seat=0)  # f32[245] 或 None
prior.note_action(action, game_id=seed, seat=0)                  # 历史特征
prior.to_meta()   # compound_prior / compound_pos_actions / compound_neg_actions / ...
```

沙盒侧（`scripts/train_economy_sandbox.py`）：

```
python scripts/train_economy_sandbox.py ... \
  --compound-prior-coef 1.0 --archetype-background-penalty 1.0 \
  --compound-archetype DEMON --compound-core-metric 1
```

`--compound-core-metric 1` 打开「目标流派核心牌在场数」度量（`economy_sandbox.measure`
里与 `carriers` 完全平行地统计 `core`），汇总键：`core_t15_p50` / `core_t15_mean` /
`core_rate` / `core_turns_mean`。不配置时**不新增任何键**（旧报告逐位不变）。

### 4.5 单测（`tests/test_compound_prior.py`，15 条全绿）

默认关（不读卡表、不产 bias、meta 不新增键）／正偏置只出现在核心牌的 Buy/Choose
（其它动作整排 0）／`penalty=0` 时他流派核心牌只「不加」不减／背景惩罚只打非公用牌／
非法位清零／mask 维度校验／同一输入重复调用逐位相同（forced 路径 + 分类器路径）／
跨实例确定性／场上最多种族退化／无种族退回 global／`core_ids_for` 便捷函数／meta 聚合。

## 5. 沙盒 A/B/C 三组（256×4 小 entity，无对手，金币 30，2M decisions/组）

设置（三组**完全相同**，只差先验系数）：

| 项 | 值 |
|---|---|
| 模型 | `--arch entity --d-model 256 --n-layers 4`（3.57M 参数，与 s14 同架构同头，可直接回迁） |
| 起点 | 三组共享 `runs/compound_prior/prep_bc/model_bc.pt`（s14 教师 300k 决策 BC，CE 2 epoch）→ **初始化逐位相同** |
| 沙盒 | `damage_caps=[[1,0]]`、无对手决策、`gold_per_turn=30`（set）、`action_cap=40`、15 回合 |
| 目标流派 | `DEMON`（核心 6 张：BG32_821 / BG36_362 / BG33_155 / BG36_762 / BGS_004 / BG23_357；含载体 Distractor + Felboar） |
| 大厅种族 | `DEMON,QUILBOAR,DRAGON,PIRATE,MURLOC`（三组同种子 → 同一批酒馆） |
| PPO | `lr 3e-6`、有效批 8192（`minibatch 512 × grad_accum 16`）、`entropy 0.004`、`target_kl 0.05`、fp32 |
| 评测 | 每 1M 决策 32 局 + 终局 64 局；`--eval-seed-base 900000`；`sample`（T=1）为主口径 |

| 组 | 先验 |
|---|---|
| **A** | 无（`--compound-prior-coef 0`，代码不构造 prior → 旧路径） |
| **B** | `--compound-prior-coef 1.0`（买/选当前流派核心牌 +1） |
| **C** | B + `--archetype-background-penalty 1.0`（买/选别的部落非公用核心牌 -1） |

### 5.1 结果（2M 决策；`sample` 口径，Σ = 战团攻+血之和）

训练期评测（32 局，`--eval-seed-base 900000`；`final` = 收尾 64 局）：

| 组 | decisions | t12 Σ p50 | t12 Σ p90 | t15 Σ p50 | 载体率 | 施法 p50 | 核心牌在场率 | 核心牌在场回合 |
|---|---|---|---|---|---|---|---|---|
| A 无先验 | 0（BC 后） | 1101 | 1400 | 1228 | 0.62 | 45 | 0.44 | 2.09 |
| A 无先验 | 1.0M | 1022 | 1464 | 1112 | 0.62 | 46 | 0.28 | 1.41 |
| A 无先验 | 2.0M | 1149 | 1614 | 1241 | 0.72 | 47 | 0.44 | 2.47 |
| A 无先验 | final(64) | 1113 | 1743 | 1254 | 0.67 | 48 | 0.39 | 2.56 |
| B 先验 +1 | 0（BC 后） | 1054 | 1345 | 1206 | 0.62 | 45 | 0.53 | 2.19 |
| B 先验 +1 | 1.0M | 978 | 1503 | 1253 | 0.59 | 40 | **0.62** | **3.62** |
| B 先验 +1 | 2.0M | 1111 | 1621 | 1230 | 0.62 | 52 | **0.62** | **3.00** |
| B 先验 +1 | final(64) | 1051 | 1531 | 1163 | 0.50 | 49 | 0.47 | **3.20** |
| C 先验+惩罚 | 0（BC 后） | 1032 | 1445 | 1140 | 0.50 | 48 | **0.59** | **2.53** |
| C 先验+惩罚 | 1.0M | 1012 | 1291 | 1046 | 0.66 | 46 | 0.56 | 3.38 |
| C 先验+惩罚 | 2.0M | 1136 | 1616 | 1290 | 0.53 | 52 | 0.44 | 3.03 |
| C 先验+惩罚 | final(64) | 1082 | 1582 | **1390** | 0.70 | 48 | 0.47 | 3.23 |

统一评测（96 局，`scripts/compound_prior_eval.py`，含**载体施法审计**）：

| 组 | 评测时先验 | t12 Σ p50 | t12 Σ p90 | t15 Σ p50 | 载体率 | 施法 p50 | **对载体施法数/局** | 核心牌在场率 |
|---|---|---|---|---|---|---|---|---|
| A | 关 | 1164 | 1836 | 1232 | 0.66 | 43 | **2.99** | 0.35 |
| B | 开（+1） | 1068 | 1685 | 1174 | 0.64 | 45 | 1.52 | **0.49** |
| B | 关 | **1138** | 1546 | 1268 | 0.60 | 48 | 1.84 | 0.32 |
| C | 开（+1/−1） | 1066 | 1644 | 1197 | 0.57 | 49 | 2.27 | 0.43 |
| C | 关 | 1109 | 1678 | 1248 | 0.59 | 50 | 2.56 | 0.33 |

**同一份权重**上的因果隔离（BC 权重 `prep_bc/model_bc.pt`，未经过任何 PPO 更新，192 局）：

| 权重 | 目标流派 | 先验 | t12 Σ p50 | t15 Σ p50 | 载体率 | 对载体施法数 | 核心牌在场率 |
|---|---|---|---|---|---|---|---|
| BC | DEMON | 关 | 1040 | 1137 | 0.52 | 2.01 | 0.48 |
| BC | DEMON | +1 | 1022 | 1141 | 0.58 | 1.69 | **0.58** |
| BC | QUILBOAR | 关 | 1042 | 1196 | 0.57 | 1.91 | 0.34 |
| BC | QUILBOAR | +1 | 1048 | 1150 | 0.49 | 1.80 | 0.42 |

读法（诚实版）：

1. **先验确实改变了行为**：同一权重下「目标流派核心牌在场率」0.48 → **0.58**（+21% 相对），
   在场回合 2.09 → 2.53（C），训练期 B/C 的核心牌在场回合稳定高于 A（3.0–3.6 vs 2.5）。
   这是**因果**的（权重逐位相同，唯一差别是买/选动作的 logit 偏置）。
2. **但 Σ 没有显著提高**：A/B/C 的 t12 p50 差异 1051–1164，而 p90 带宽 1500–1800、
   96 局下中位数的抽样误差约 ±50–60 → 所有组间差异都在噪声带内。3 组点估计里
   **A（无先验）反而最高**（1164 / 1138 / 1109 vs 1068 / 1066）。
3. **对载体施法数变少了**（A 2.99 → B 1.52 / C 2.27）：先验把金币花在核心牌上，
   挤掉了「买法术 → 砸载体」的预算。DEMON 核心集里 3 张（BG32_821 / BG36_362 /
   BG36_762）本身是「每施放法术成长」，但它们要**法术数量**配合，而先验只管买牌、
   不管买法术 —— 这是这套偏置落点的一个结构性缺口。
4. 代价：B/C 采样吞吐 806/809 dec/s vs A 865 dec/s（先验每决策多一次 `parse_obs` +
   分类器前向，约 **6–7%**）。

### 5.2 收敛速度（t12 Σ 首次 ≥ 阈值所需 decisions）

**先说结论：请求的阈值 `t12 Σ≥1000` 在本配方下**没有区分度** —— BC 热身（s14 教师、
300k 决策）把三组的起点直接抬到 1032–1101，`decisions=0` 就已经达标。所以下表同时给出
更高阈值；「所需 decisions」取训练期逐 update 的 `ep_LT_p50` 反解 Σ（
`Σ = expm1(LT·log1p(30000))`，每 16k 决策一个点），再做 **5 窗滑动平均 + 连续 3 窗确认**
（避免单点噪声制造假穿越）。

| 组 | t12≥1000 | t12≥1100 | t12≥1200 | t12≥1400 | 前 25% 决策均值 | 后 25% 决策均值 | 末 10 窗均值 |
|---|---|---|---|---|---|---|---|
| A 无先验 | 70k | 70k | **1200k** | 未达 | 1064 | **1272** | 1259 |
| B 先验 +1 | 70k | 70k | 1806k | 未达 | 1101 | 1188 | 1218 |
| C 先验+惩罚 | 70k | 140k | 1610k | 未达 | 1063 | 1234 | **1283** |

平滑后的曲线（5 窗移动平均，Σ p50）：

| decisions | A | B | C |
|---|---|---|---|
| 200k | 1085 | 1097 | 1117 |
| 400k | 996 | 1036 | 1039 |
| 600k | 1016 | 1054 | 977 |
| 800k | 1101 | 1035 | 1045 |
| 1000k | 1152 | 1040 | 1071 |
| 1200k | **1250** | 1077 | 1054 |
| 1400k | 1200 | 1164 | 1134 |
| 1600k | **1336** | 1167 | 1239 |
| 1800k | 1204 | 1210 | 1286 |

**没有看到先验加速收敛**：高的两个阈值上 A 反而最早穿越（1200k vs 1610k/1806k），
后 25% 的均值 A 最高。三组曲线在整个 2M 内都处在同一个 ±150 的噪声带里。

### 5.3 为什么没有加速（诊断）

1. **这套 PPO 几乎不更新策略**：121 次 update 里 `policy_loss ≈ 1e-4`、`approx_kl ≈ 1e-4`、
   `entropy ≈ 1.0–1.1`（几乎不变）、`clip_frac ≤ 0.005`；只有 value 头在学
   （`value_loss` 0.18 → 0.03–0.05）。也就是说 A/B/C 在 2M 内**基本等于"同一份 BC 策略
   + 三种不同的 acting 先验"**，训练期的差异理应 ≈ 5.1 的固定权重对比（实测一致）。
   BC 起点太强（s14 教师 300k、`ce 1.17→1.01`、`top1 0.58`）+ `lr 3e-6` 是主因。
2. **目标流派的核心牌集与 Σ 传导链不完全对齐**：DEMON 的 6 张核心牌里，BG32_821 /
   BG36_362 / BG36_762 靠「**法术数量** × 永久增量」放大，而先验只偏置**买牌**（Buy/Choose），
   不偏置「买法术」（Buy 位里的 tavern_spell）与「对载体施法」（Choose 目标）。所以它把
   策略推向「买成长牌」却没有同时抬「法术流量」，反而挤压了载体的施法预算
   （§5.1 第 3 点）。
3. **沙盒的经济学**：`gold=30`、15 回合、无战斗 —— 复利要在 t12–t15 兑现，需要
   「早期买成长引擎 + 中期买法术 + 后期买大身材」三段节奏；单点买牌偏置只动第一段。

### 5.4 结论与建议

- **先验机制本身是正确且可控的**：默认关、`coef=0` 逐位等价、只加不减、成本 6–7%、
  同一权重下把目标流派核心牌在场率从 0.48 抬到 0.58（+21% 相对）。15 条单测覆盖
  「偏置只在对应动作上 / 默认关 / 确定性」。
- **但「先验加速 Σ 收敛」在本实验里没有被证实**：三组 t12 Σ p50 差异落在 ±100 噪声带、
  A 甚至略高；高阈值穿越 A 最早。归因是配方（强 BC 起点 + `lr 3e-6`）让策略几乎不更新，
  先验只能当 acting 引导，而 DEMON 核心集又没有同时抬法术流量。
- **接入 s18 小模型专家课程的建议（按优先级）**：
  1. **接在"策略还不会打"的阶段**：`from-scratch` 或弱 BC（10–30k）的前 200–500k 决策，
     并把 `coef` 线性退火到 0（前 200k 1.0 → 1M 时 0.2 → 之后 0）。先验的价值在早期
     探索，而不是在已收敛的 BC 策略上长期施加。
  2. **把先验搬进 BC 教师 / 搜索提议**：比 acting 偏置更划算 —— 用核心牌集扩充
     `archetype_bias` 偏好表的 `top_cards` 分项，或作为 MCTS 的 prior 偏置
     （只在根节点前 N 个 buy 候选上加 bias）。
  3. **补齐动作面**：先验应同时覆盖「买酒馆法术」与「对载体施法/选目标」——否则
     「买成长牌」与「法术流量」脱节（本实验暴露出的最大缺口）。
  4. **换目标流派再验一次**：QUILBOAR（血宝石，BG30_123/BG33_885 是全局分数最高的两张，
     传导链最短）或 PIRATE（金色系）比 DEMON 更适合做「先验 → Σ」的第二个样本；
     本轮的固定权重对比里 QUILBOAR 先验把核心牌在场率 0.34 → 0.42，值得再跑一次 2M。
  5. **不要**把 `--archetype-background-penalty` 当作提高 Σ 的手段：它的作用是「收窄搜索
     空间」（同权重下其它部落核心牌的购买被压掉，C 组 `compound_neg_actions≈2.76M` 次），
     适合「已知阵容、要快速找该阵容解法」的推理期，而不是从头学强度。

## 6. 复现命令

```bash
# 1) 挖矿（幂等自检 + 报告）
python scripts/mine_compound_cards.py --check
python scripts/mine_compound_cards.py --report

# 2) 单测
python -m pytest tests/test_compound_prior.py -q

# 3) A/B/C 沙盒（三组并行，共享同一份 BC 权重；见 runs/compound_prior/launch_abc_par.sh）
bash runs/compound_prior/launch_abc_par.sh
python runs/compound_prior/extract_abc.py     # 抽表 + 阈值 + 曲线

# 4) 统一评测（含「对载体施法数」审计 + 核心牌在场）
python scripts/compound_prior_eval.py \
  --checkpoint runs/compound_prior/A_noprior/model_final.pt \
  --compound-archetype DEMON --games 96 --device cuda:7 \
  --json-out runs/compound_prior/eval_A.json

# 5) 同一权重上做先验 on/off 的因果隔离（BC 权重，192 局）
python scripts/compound_prior_eval.py \
  --checkpoint runs/compound_prior/prep_bc/model_bc.pt \
  --compound-archetype DEMON --compound-prior-coef 1.0 \
  --games 192 --device cuda:7 --json-out runs/compound_prior/eval_bc192_on.json
```

产物：`runs/compound_prior/{prep_bc,A_noprior,B_prior,C_prior_bg}/`（`history.jsonl` /
`summary.json` / `model_*.pt`）、`runs/compound_prior/eval_*.json`。
