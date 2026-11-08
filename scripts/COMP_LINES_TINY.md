# 复利阵容 · 1M 小模型 · 无对战沙盒：第一阶段（Firestone comps / 饰品 / 指数成长奖励）

> 目标（用户的核心判断）：**当前所有方案都只是在弱局部最优上发力**。核心是学会
> **复利阵容的几何级数乃至指数成长**；先用**足够小的模型（~1M）**、**足够高的吞吐**、
> **没有对战的环境**，逼它学会「前 9–10 回合选对饰品与核心牌 → 后续回合指数成长」。
>
> 本文件是第一阶段的三件事 + 判据：
> **A** 拿到 Firestone 的阵容（comps）数据 → `data/scaling/comps_top.json`；
> **B** 确认沙盒支持「饰品选择」并把它做成可开关 + 可度量；
> **C** 用 **0.667M** 的 entity 模型 + **超线性（加速度）奖励** 在无对战沙盒里训练 ≥5M 决策；
> **D** 按判据（t15 Σ p50 ≥ 10,000、t12→t15 ≥ 3×、核心牌/饰品命中率 ≥60%）判定并给出下一步。

## 0. 结论先行

1. **A 成功**：Firestone comps 页的数据源不是 ``firestoneapp.com``，而是
   ``static.zerotoheroes.com`` 上的静态 JSON（URL 从 ``main.*.js`` bundle 里 grep 出来的，
   见 §1.1）。拿到 **27 套阵容**（含 top-10% MMR 排序）、**62 张核心牌**（61 张在引擎卡库）、
   **每套 4 张关键饰品**（由三条可核验证据合成，证据逐条写进 ``why``）。
   与仓库既有资产的交集：核心牌 ∩ ``data/scaling/carriers.json`` = **7 张**、
   ∩ ``data/scaling/compound_cards.json`` 的复利核心集 = **21 张（33.9%）**。
2. **B 之前就能用、这次补上「可开关 + 可度量 + 契约测试」**：引擎默认
   ``lesser_trinket_turn=6 / greater_trinket_turn=9 / trinket_choices=4``，
   沙盒**本来**每局就有 2 次饰品选择（第 6、9 回合各 4 选 1），编码是
   **``Choose(0..3)`` = 动作 30..33**（``Pending::Trinket``）。新增
   ``--sandbox-trinkets {1,0,-1}``（默认 -1 = 引擎默认 → **与改动前逐位一致**，
   已验证：动作流 / ``sigma_by_turn`` / 奖励 / 全部旧度量键都相同）与
   ``trinket_offers`` / ``trinket_ids`` 度量；`tests/test_sandbox_trinkets.py` 8 项契约。
3. **C 做成，但「10,000 / 3×」判据没达到**。三条臂的实测（0.667M，全部开饰品、exp_growth）：

   | 臂 | 决策 | t15 Σ p50 | Σ15/Σ12 | 核心牌命中 | 饰品命中 |
   |---|---|---|---|---|---|
   | A 从零，lr 3e-5 | 5.0M | **18** | 1.00 | 41% | 10% |
   | B 从零，lr 1e-4 | 5.0M | **111** | 1.17 | 56% | 12% |
   | C s14-BC 300k → PPO | 3.0M(+BC) | **1,293–1,600** | 1.16–1.32 | **100%** | 23% |

   ⇒ **判据 ✗**（绝对强度差 6.3×、指数段差 2.3×）。但两个前提被证实：
   **容量够**（C 的 1,600 超过 24 个脚本组合的最好值 1,400）、
   **核心牌选择能学会**（C 100%）。**从零训练在 5M 决策内基本没学会经济**（18–111）。
4. **为什么不可达：沙盒的「每金币价值产出」本身是线性的**（这是最有用的结论）。
   24 个脚本组合 × {动作上限 40/120} × {金币 30/99} × {免费 tier6} 的 t15 Σ p50 **最高 1,400**，
   而判据要 10,000（脚本上限的 7.2 倍）。金币 99 与 30 一样、动作上限 120 与 40 一样 ⇒
   瓶颈不是钱也不是动作额度，而是**收入不随身材增长**：固定 30 金币/回合 × 15 回合 = 450 金币
   ÷ ~3 金币/张 ≈ **150 次价值事件**，实测 ≈ **2.9 Σ/金币**；真实 10k+ 是 **9.9 Σ/金币**（3.4 倍），
   差额正是复利循环（金币生成饰品/法术、三连金色、酒馆永久 buff × 场上 N）。
   ⇒ **下一步不是加大训练量，而是先给沙盒一个会复利的收入**（§4.4 第 1 条）。
5. 顺手的负结果：**奖励口径的改动没有救回指标**——``exp_growth`` 的超线性项在 t10..t15
   对「线性铺场」一分不给、对「每回合 ×1.55 复利」每回合给满，但沙盒里所有臂的
   ``growth_dlog_late_p50`` 只有 **0.00–0.10**（基线 0.35）⇒ 该项在大多数轨迹上是 0、**没有梯度**。
   这证明的是「**判据不可达**」，不是「奖励设计错了」（§4.3）。

---

## 1. 任务 A：Firestone 阵容数据 → `data/scaling/comps_top.json`

### 1.1 数据源：SPA 的 API 怎么找到的

页面 ``https://www.firestoneapp.com/battlegrounds/comps?rank=10`` 是 Angular SPA，
HTML 里只有三个 bundle（``main.f30184659a410109.js``，6.5 MB）。在 bundle 里 grep
``comp``/``trinket`` 拿到全部数据端点（**不是** ``static.firestoneapp.com``，而是
ZeroToHeroes 的 CDN）：

| 用途 | 端点 |
|---|---|
| 阵容定义（27 套，含 CORE/ADDON/CYCLE + 专家 tip + 强度/难度） | ``static.zerotoheroes.com/hearthstone/data/battlegrounds-strategies/bgs-comps-strategies.gz.json?v=37.0`` |
| 阵容战绩（按 MMR 分桶的平均名次） | ``static.zerotoheroes.com/api/bgs/comp-stats/last-patch/overview-v3.gz.json`` |
| 阵容示例终局面板（真实高 MMR 玩家战团） | ``static.zerotoheroes.com/api/bgs/comp-stats/last-patch/boards/<archetype>.json`` |
| 饰品专家点评（141 张饰品有建议） | ``static.zerotoheroes.com/hearthstone/data/battlegrounds-strategies/bgs-trinket-strategies.gz.json`` |
| 饰品战绩（按 MMR 分桶的选取率/名次，243 张有数据） | ``static.zerotoheroes.com/api/bgs/trinket-stats/last-patch/overview-from-hourly.gz.json`` |

数据抓取脚本：``scripts/comp_lines_fetch.py``（原始 JSON 缓存到 ``runs/comp_lines/raw/``，
可离线重跑；``--no-boards`` 跳过 35 次面板请求）。**``?rank=10`` 的口径** = overview 里的
``mmr=10`` 分桶（100/50/25/10/1 百分位；1 = 最强 1%），排序与判据都用它。

### 1.2 27 套阵容（按 top-10% MMR 平均名次排序）

`data/scaling/comps_top.json` 的每条记录字段：
``archetype / name / tribe / power_level / difficulty / core_cards / addon_cards /
cycle_cards / trinkets / growth_text / when_to_commit / growth_mechanism / stats /
example_boards``。``stats.is_top`` 标记前 10（``--top-n``，默认 10）。

| # | 阵容 | 种族 | 强度 | rank=10 名次 | 核心牌 | 关键饰品（证据） | 示例终局面板 Σ p50/max |
|---|---|---|---|---|---|---|---|
| 1 | Neutral Tea Set | QUILBOAR | S | 3.40 | 3: Gatekeeper Amalgam, Balinda Stonehearth, Brann Bronzebeard | Wand of Divination, Felsteel Cleaver | 44259/383984 |
| 2 | Undead APM | UNDEAD | S | 3.46 | 4: Sky Admiral Rogers, Proud Privateer, Forsaken Weaver, Snazzy Phantom | Eternal Portrait, Baleful Incense | 44419/374128 |
| 3 | Murloc Scam | MURLOC | A | 3.47 | 3: Expert Aviator, Sewer Escapee, Bile Spitter | Nerglish Phrasebook, Hackerfin Portrait | 11032/675236 |
| 4 | Aberration Discard | ABERRATION | C | 3.53 | 2: Harbinger Aph'lass, Mysterious K'Thir | Sludge Portrait, Tome of the Ancients | 40458/194854 |
| 5 | Dragon Shield | DRAGON | A | 3.53 | 4: Persistent Poet, Hopebringer, Heroic Broodmother, Nadina the Red | Holy Mallet, Bronze Timepiece | 11514/163632 |
| 6 | Demon Boost Shop | DEMON | A | 3.54 | 4: Devilish Distractor, Balinda Stonehearth, Felboar, Imp-lusionist | Felsteel Cleaver, Pilgrimp Sticker | 75434/993598 |
| 7 | Murloc Handbuff | MURLOC | C | 3.58 | 5: Choral Mrrrglr, Twilight Tidehunter, Flighty Scout, Diremuck Forager | Nerglish Phrasebook, Fungalmancer Sticker | 4463/116916 |
| 8 | Mech APM | MECHANICAL | S | 3.63 | 2: Auto Reveille, Spark Snapper | Mecha-Jaraxxus Sticker, Beatboxer Portrait | 110728/2043810 |
| 9 | Undead Butcher | UNDEAD | A | 3.70 | 2: Drustfallen Butcher, Snazzy Phantom | Goldenizer Supply, Eternal Portrait | 71206/450077 |
| 10 | Quilboar Choose One | QUILBOAR | C | 3.72 | 2: Turbo Hogrider, Bramble Tunneler | Trailblazer Sticker, Blood Golem Sticker | 63314/288959 |
| 11 | Murloc End Of Turn | MURLOC | A | 3.73 | 4: Brann Bronzebeard, Young Murk-Eye, Drakkari Enchanter, Magicfin Mycologist | Hackerfin Portrait, Vibrant Bubble | 46655/177494 |
| 12 | Quilboar Felboar Spam | QUILBOAR | S | 3.81 | 3: Felboar, Balinda Stonehearth, Brann Bronzebeard | Bloodbound Earrings, Bloodbound Earrings | 74515/293886 |
| 13 | Elemental Azerite | ELEMENTAL | S | 3.81 | 4: Living Azerite, Leyline Surfacer, Balinda Stonehearth, Brann Bronzebeard | Azerite Portrait, Baller Portrait | 106303/419747 |
| 14 | Beast Lobster | BEAST | S | 3.82 | 4: Tasty Lobster, Titus Rivendare, Deathstrider, Headhunter Gryphon | Goldenizer Supply, Snarky Portrait | 86637/1355625 |
| 15 | Mech Volumizer | MECHANICAL | C | 3.92 | 3: Resourceful Robot, Utility Drone, Drakkari Enchanter | Mecha-Jaraxxus Sticker, Goldenizer Supply | 48916/652203 |
| 16 | Aberration Deathrattle | ABERRATION | B | 3.93 | 2: Faceless Converter, Titus Rivendare | Goldenizer Supply, Sludge Portrait | 12436/90569 |
| 17 | Pirate Discover | PIRATE | B | 4.02 | 2: Hooktusk Master Marauder, Enterprising Escapee | Designer Eyepatch, Heart of the Forest | 64883/127486 |
| 18 | Demon Self Damage | DEMON | A | 4.04 | 6: Wrath Weaver, Ashen Corruptor, Soul Rewinder, Eredar Escapist | Rewinder Portrait, Bob-blehead | 71919/231770 |
| 19 | Elemental Tempest | ELEMENTAL | C | 4.06 | 3: Brann Bronzebeard, Unbound Tempest, Air Revenant | Upstart Embers, Frigid Blossom | 59110/199585 |
| 20 | Beast Beetle | BEAST | A | 4.09 | 4: Ravaging Scorpid, Turquoise Skitterer, Headhunter Gryphon, Banana Slamma | Summoning Sphere, Goldenizer Supply | 989/476886 |
| 21 | Beast Leviathan | BEAST | A | 4.19 | 4: Lurking Leviathan, Banana Slamma, Sewer Lord, Headhunter Gryphon | Goldenizer Supply, Beetle Band | 1482/34204 |
| 22 | Undead Eternal Knight | UNDEAD | C | 4.21 | 3: Eternal Knight, Eternal Summoner | Eternal Portrait, Summoning Sphere | 56698/341759 |
| 23 | Dragon Kalecgos | DRAGON | C | 4.28 | 2: Kalecgos Arcane Aspect, Brann Bronzebeard | Bronze Timepiece, Emerald Dreamcatcher | 16062/192788 |
| 24 | Dragon Spell Power | DRAGON | B | 4.29 | 4: Crimson Vindicator, Persistent Poet, Runic Arcanist, Brann Bronzebeard | Bronze Timepiece, Holy Mallet | 14117/83747 |
| 25 | Mech Glambot | MECHANICAL | A | 4.34 | 4: Glambot, Balinda Stonehearth, Utility Drone, Drakkari Enchanter | Mecha-Jaraxxus Sticker, Beatboxer Portrait | 54872/371253 |
| 26 | Quilboar Gem Spam | QUILBOAR | A | 4.45 | 4: Hot-Air Surveyor, Geomagus Roogug, Bramble Tunneler, Balinda Stonehearth | Blood Golem Sticker, Bloodbound Earrings | 44380/358062 |
| 27 | Pirate Bounty | PIRATE | B | 4.89 | 2: Sky Admiral Rogers, Proud Privateer | Heart of the Forest, Miniature Ship | 23760/429199 |

**关键观察 1（对训练的直接含义）**：这些阵容的**真实终局面板 Σ p50 是 4.5k–110k**
（max 到 204 万），而**沙盒脚本能打到的 t15 Σ p50 只有 1.4k**（§4.1）。
即：真实阵容的成长量级与沙盒脚本量级差 **5–80 倍**，不在一个数量级上。

**关键观察 2**：列表里反复出现的「核心」是**复利/触发链放大器**而不是纯身材卡——
``Brann Bronzebeard``（战吼触发两次，出现 7 次）、``Balinda Stonehearth``（5 次）、
``Drakkari Enchanter``（结束回合触发两次，3 次）、``Titus Rivendare``（亡语触发两次，4 次）、
``Goldenizer Supply``（饰品：把一张牌变金色）。这正是「几何级数」的机制来源：
**触发次数 ×N 是乘性放大**，配合三连/金色（真实高强度战团 62.1% 身材来自 ``_G``）。

### 1.3 统计与交集（`comps_top.json["stats"]`）

| 指标 | 值 |
|---|---|
| 阵容数 / 有战绩的 / 标记 top-10 的 | **27 / 27 / 10** |
| 核心牌并集（CORE） | **62 张**，其中在引擎卡库 **61 张** |
| 核心牌+附加牌并集 | 126 张（引擎在库 125） |
| 全部牌（CORE+ADDON+CYCLE）并集 | 152 张（引擎在库 151） |
| ∩ ``data/scaling/carriers.json``（22 个载体 id） | **7 张**：`BG28_633` Felboar、`BG28_707` Living Azerite、`BG34_692` Forsaken Weaver、`BG36_640` Gatekeeper Amalgam、`BG36_703` Twilight Tidehunter、`BG36_762` Devilish Distractor、`BG36_853` Glambot |
| ∩ ``data/scaling/compound_cards.json`` 的复利核心集（64 个 id） | **21 张（33.9%）**；核心+附加 = 37 张（29.4%） |
| ``compound_cards.json`` 里已有同 archetype 键 | 27/27（两个数据源用同一套 archetype id，可直接对齐） |
| 饰品：引擎卡库 trinket 卡 / 有专家点评 / 有战绩 | 420 / 141 / 243；**27 套阵容共引用 57 张不同的关键饰品** |
| 示例面板缺失 | 0 套 |

**交集偏低的解释**：``carriers.json`` 只收录「把施法转成永久身材」的载体（11 张 + 金色），
而 Firestone 的 CORE 更偏向「触发链放大器」（Brann/Titus/Drakkari/Balinda），
两者机制不同、只在 Felboar / Devilish Distractor / Living Azerite 这类「施法系阵容」上重叠。
``compound_cards.json`` 的核心集是**从引擎卡表挖的**（169 张复利候选 → 64 张 core），
与人类 CORE 有 1/3 重合——**重合的那 1/3 就是「两边都认可」的核心**，是最该先教会模型的东西。

### 1.4 饰品（trinkets）是怎么定出来的（重要：没有官方 comp→trinket 映射）

Firestone 的 comps 数据里**没有** trinket 字段（饰品是另一套页面/另一份 JSON），
所以 ``trinkets`` 是**合成的**，每条都带 ``why`` 证据，不做无据推断：

| 证据 | 含义 | 权重 |
|---|---|---|
| ``mention:<card>`` | 饰品专家点评里用 ``[[卡名]]`` 明确提到本阵容的核心/附加牌 | 3.0/张 |
| ``text:<card>`` | 点评正文里以普通文字点名（名字 ≥7 字符才认，避免噪声） | 1.5/张 |
| ``assoc:<TRIBE>`` | 引擎 ``cards.json`` 里该饰品的 ``assoc`` 命中本阵容主种族（主种族 = CORE 权重 2、ADDON 权重 1 的**多数票**） | 2.0 |
| ``mechanic:<kw>`` | 饰品 ``text`` 与本阵容成长机制词重合（复生/亡语/战吼/酒馆…） | 0.6/个 |
| 战绩 | top-10% MMR 平均名次（``4.6 − place`` 越大越好）与选取率 | 1.2 / 0.8 |

每套取 top-4（``--top``）。记录里同时给出 ``kind``（lesser/greater）、``cost``、
``assoc``、``place10``、``pick10``、``data_points``，可直接核验。

---

## 2. 任务 B：沙盒里的饰品（Trinket）支持

### 2.1 结论：引擎/沙盒**本来就有**饰品，缺的是「可开关 + 可度量 + 契约」

- 引擎 ``RulesConfig::default()``：``lesser_trinket_turn=6``、``greater_trinket_turn=9``、
  ``trinket_choices=4``（``rust/crates/hsbg-engine/src/config.rs``）；
  ``flow.rs::start_turn`` 在 ``turn == lesser`` 与 ``turn >= greater && !greater_offered``
  时调 ``offer_trinkets``，把 4 张候选推成 **阻塞式** ``Pending::Trinket``
  （``recruit.rs::drop_unaffordable_trinket_offers`` 会跳过「一张都买不起」的报价）。
- 沙盒没有动 Rust：它走的是引擎原生 ``start_turn`` → 所以**默认就有**饰品选择。
  实测（``tests/test_sandbox_trinkets.py``）：每局 **恰好 2 次**饰品选择，出现在
  **turn 6 / turn 9**，每次 **4 个候选**。
- **动作编码**：``Pending::Trinket`` 与 Discover/ChooseOne 共用「选择段」
  ``Choose(0..16)`` = 动作 **30..46**；饰品的 4 个选项就是 **30..33**。
  这一段在 245 动作空间的前 245 内（冻结契约不变），观测里对应
  ``cards[SLICE_CARD_CHOICES]``（见 `docs/COMPOUND_CHAINS.md` §动作表）。
- 购买价随回合/减价效果变化（``trinket_price``），**跳过也会推进**（不能拒绝，只能选）。

### 2.2 这次的改动

`hsbg/az/train/economy_sandbox.py`：

| 改动 | 语义 |
|---|---|
| ``SandboxConfig.trinkets: Optional[bool] = None`` | **None = 引擎默认**（不写任何 trinket 键 → 与改动前**逐位一致**）；``True`` = 把 6/9/4 显式钉死（值等于默认，行为不变）；``False`` = 阈值推到 999（真正的关） |
| ``engine_config()`` | 只有 ``trinkets is not None`` 时才写 ``lesser_trinket_turn / greater_trinket_turn / trinket_choices`` |
| ``measure()`` | ``trinkets is not None`` 时新增 ``trinkets``（本回合拥有的 id 列表）与 ``trinket_count`` |
| ``_pending_kind()`` | 只在「饰品计量开启 + 这一步是 Choose」时查一次 ``view``（≈0.45 ms），且**每回合最多 8 次**（不加这个门，随机策略下每次 Discover 都查 view，实测占采样时间 25%） |
| ``episode_summary()`` | 新增 ``trinket_offers``（本局饰品选择次数）/ ``trinket_ids``（曾拥有的饰品并集）/ ``trinket_count`` |
| CLI ``--sandbox-trinkets {1,0,-1}`` | 默认 **-1 = 引擎默认**；1 = 显式开启；0 = 关闭 |

`scripts/train_economy_sandbox.py`：``--sandbox-trinkets``、``--trinket-target-from-comps``
（用 ``comps_top.json`` 的 57 张关键饰品做**命中率**）、``--core-from-comps``
（用 62 张 Fireman... Firestone 核心牌做**命中率**）；评测行新增
``trk=<拥有数>/<命中率>``。

### 2.3 「默认关时的逐位等价」

验证方式是**把 HEAD 版本的模块读进来和新版本逐位对跑**
（``git show HEAD:hsbg/az/train/economy_sandbox.py`` → /tmp，同一 seed 同一动作选择规则，
比较动作流 / ``sigma_by_turn`` / 整局奖励 / 全部旧度量键）：**6 个 seed 全部相同**。

- 默认（``trinkets=None``）：``engine_config()`` 里**没有** trinket 键 → 引擎行为与改动前逐位一致；
  ``measure()``/``episode_summary()`` 只是**新增**键（``growth_*``、没有 trinket 键），
  旧键的值不变。
- ``trinkets=True``：与默认的 ``sigma_by_turn`` **逐位相同**（因为 6/9/4 就是默认值），
  测试 ``test_default_equals_explicit_trinkets_on`` 盯着这件事。
- 只在 ``trinkets=True`` 时才有饰品键，所以想省 CPU 可以继续用默认路径。

---

## 3. 任务 C：1M 小模型 + 指数成长奖励

### 3.1 模型规模（实测参数）

| 配置 | 参数量 | 说明 |
|---|---|---|
| ``--arch entity --d-model 128 --n-layers 2 --n-heads 4`` | **0.667M** | 本次主臂（用户指定尺寸；≤1M，不需要再缩） |
| ``--d-model 128 --n-layers 4`` | 1.064M | 「严格 ~1M」的备选（未用，只为对照） |
| （历史）``d-model 256 --n-layers 4`` | 3.57M | `docs/ECONOMY_SANDBOX.md` 的旧「小模型」 |

观测/动作头与 14.8M 的 s14 **逐项一致**（3227 floats + 124 cards / 245 动作 / scalar value，
value 头是 ``tanh``），所以 checkpoint 仍可直接回完整游戏。

> **value 头的量纲约束**：``value = tanh(...)`` ∈ [-1,1] → 整局回报必须留在 ~[-2,2]。
> 这也是下面奖励权重的取值依据（w1=1.0 + w2=0.2 + w3=0.3，见 §3.2）。

### 3.2 奖励设计：惩罚线性、奖励加速

沙盒原有的 ``log_strength`` 是**望远镜** ``r_t = L_t − L_{t−1}``（整局和 = ``L_T``），
``L_t = log1p(Σ_t)/log1p(30000)``。它对「早强/晚强」中立，**完全不区分线性与复利**。
新增 ``--sandbox-reward exp_growth``（默认参数即下表）：

```
r_t = w1·(L_t − L_{t−1})                                   # 终局强度（望远镜 → w1·L_T）
    + w2·max(0, ΔlnΣ_t − slope_base)      (t ≥ growth_from)  # 超线性：超过基线斜率才给分
    + w3·max(0, ln(Σ_T/Σ_12) − ln 3)      (只在 t = T)       # 指数段：t12→t15 ≥3× 的额外加成
ΔlnΣ_t = ln(1+Σ_t) − ln(1+Σ_{t−1})     # 本回合的「对数斜率」
```

| 参数 | 默认 | 含义 |
|---|---|---|
| ``--sandbox-growth-w-final`` (w1) | 1.0 | 终局强度权重（``L_T ≤ 0.89``） |
| ``--sandbox-growth-w-super`` (w2) | 0.2 | 超线性权重（≤0.1/回合 × 6 回合） |
| ``--sandbox-growth-slope-base`` | 0.35 | **基线对数斜率**：ΔlnΣ 低于它不加分 |
| ``--sandbox-growth-from`` | 10 | 从第 10 回合开始给超线性分（用户口径 t10..t15） |
| ``--sandbox-growth-w-ratio`` (w3) | 0.3 | 指数段（Σ15/Σ12 ≥ 3×）加成 |

**为什么这条公式区分「线性 vs 复利」**（`runs/plots/comp_lines_reward.png`）：

- 线性铺场 ``Σ_t = 1000t`` → t10..t15 的 ΔlnΣ = ln(15/14) = **0.069** < 0.35 → **w2 项恒为 0**；
- 复利 ``Σ_t = 1000·1.55^t`` → ΔlnΣ = ln 1.55 = **0.438** > 0.35 → 每回合拿满 ``w2·0.088``；
- 单测 ``test_exp_growth_rewards_acceleration_not_linearity`` 钉死这两点
  （线性 = 0.0，复利 = 6×0.088 = 0.53）；
- ``test_exp_growth_telescopes_without_extra_terms``：``w2=w3=0`` 时整局和 == ``L_T``（与旧口径同源）。

### 3.3 环境与配方

```
economy sandbox（无对手 / 无战斗 / 无血量 / 无排名，docs/ECONOMY_SANDBOX.md）
--turns 15 --gold-per-turn 30（set 模式）--action-cap 40 --num-players 8
--sandbox-trinkets 1        # 第 6/9 回合 4 选 1，动作 30..33
--sandbox-reward exp_growth # §3.2
PPO: epochs 2, minibatch 1024 × grad_accum 8（有效 8192）, batch_decisions 16384, gamma 1.0, lam 0.95
```

两条臂（只有 lr / entropy 不同，用来回答「0.667M 从零能不能学」）：

| 臂 | 起点 | lr | entropy | 决策预算 |
|---|---|---|---|---|
| **A** `tiny_A_lr3e-5` | from scratch | 3e-5 | 0.01 | 5,000,000 |
| **B** `tiny_B_lr1e-4` | from scratch | 1e-4 | 0.02 | 5,000,000 |

评测：每 1M 决策评一次（``--eval-every 1M --eval-games 48``），greedy + sample(T=1) 两种；
评测里同时记 ``core_rate``（62 张 Firestone 核心牌在场率）与 ``trinket_hit_rate``
（57 张关键饰品命中率）、成长曲线形状。

### 3.4 吞吐

| 阶段 | 实测 |
|---|---|
| 单环境 ``EconomySandbox.step``（含观测/掩码） | ~0.26 ms（15 回合 ≈ 22 ms/局，与 `docs/ECONOMY_SANDBOX.md` 一致） |
| 一局决策数（0.667M 策略，15 回合 / 40 动作上限） | **~560–615 个决策**（→ 5M 决策 ≈ 8.5k 局） |
| 优化前 → 优化后（饰品 pending 探测：每次 Choose 都 ``view`` → 每回合最多 8 次） | **709 → 1,415 dec/s** |
| 128 个 lockstep 环境 + 0.667M 模型（``cuda:7``，fp32） | **A 1,963 dec/s / B 2,104 dec/s**（两条臂并行，机器另有他人在跑 60 worker） |
| 5.0M 决策的实际耗时 | A **42 分钟**、B **40 分钟**；C（BC 300k + PPO 3.0M）**48 分钟** |
| 评测开销 | 48 局 × 2 模式（greedy/sample）≈ 8–15 s（占训练 <1%） |

> 说明：本机 128 核但同时有别人的 60 worker 在跑，实测波动 ±2×；
> ``--envs`` 从 96 加到 192/256 在争用下**没有收益**（前向不是瓶颈，引擎步进是）。


---

## 4. 任务 D：判据与结论

判据（用户给定）：**t15 Σ p50 ≥ 10,000**（真实 26,516 的 38%）、**t12→t15 ≥ 3×**、
**核心牌/饰品命中率 ≥ 60%**。

### 4.1 先量「沙盒能表达多少」：脚本策略的可表达上限

在解读模型之前必须先知道环境的天花板，否则「模型没学会」和「环境表达不了」分不开。
`scripts/sandbox_ceiling_probe.py` 扫了 **3 个脚本策略 × 动作上限 {40,120} × 金币 {30,99} ×
免费 tier6 {0,1} = 24 个组合**（每个 6 局，全部开启饰品）：

| 策略 | 最好的组合 | t12 Σ p50 | t15 Σ p50 | t15 单局最大 | 施法数 p50 | ``r12_15`` |
|---|---|---|---|---|---|---|
| ``spell``（专门做施法缩放的脚本） | cap 40 / gold 99 / free tier6 | **1,312** | 1,291 | 2,305 | 78 | 1.08 |
| ``spell`` | cap 40 / gold 30 / free tier6 | 988 | **1,175** | 3,728 | 90 | 1.10 |
| ``teacher``（载体教师） | cap 40 / gold 30 / free tier6 | 756 | 866 | 1,877 | 56 | 1.13 |
| ``carrier_teacher`` | 同上 | 756 | 866 | 1,877 | 56 | 1.13 |

- **24 个组合里 t15 Σ p50 的最高值 = 1,400**（``runs/comp_lines/ceiling.json``）。
- **金币几乎不起作用**（gold 99 ≈ gold 30）、**动作上限几乎不起作用**（cap 120 ≈ cap 40），
  两者都指向同一个瓶颈：**每回合能买到的「价值事件」数量被经济结构钉死了**（见 §4.3）。
- 所有脚本组合的 ``r12_15`` 都在 **1.0–1.15**，**没有一个出现指数段**。
- 与历史结论一致：`docs/ECONOMY_SANDBOX.md` §3 记录的「∞金币 + 施法缩放脚本 t12 = 1170」、
  `runs/ceiling_probe/REPORT.md` 的「免费 tier6 + 120 动作 t12 = 1843」。

> ⇒ **判据 10,000 是脚本上限（1.4k）的 7.2 倍**。这不是「再训久一点」能补的差距。

### 4.2 1M 模型（0.667M）的实测

原始数据 ``runs/comp_lines/tiny_*/history.jsonl``，图 ``runs/plots/comp_lines_training.png``
与 ``runs/plots/comp_lines_growth.png``；判据由 ``scripts/comp_lines_report.py``
自动算进 ``runs/comp_lines/summary.json``。

| 臂 | 起点 | lr | 决策 | t12 Σ p50 | **t15 Σ p50** | t15 p90 / 单局 max | **Σ15/Σ12** | slope_late | curv | exp 段率 | 核心牌命中 | 饰品命中 | 施法 p50 | 载体率 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **A** `tiny_A_lr3e-5` | 从零 | 3e-5 | 5.0M | 18.0 | **18.0** | 116 / 4,107 | 1.00 | 0.000 | −0.0135 | 4.2% | 40.6% | 10.4% | 0 | 4.2% |
| **B** `tiny_B_lr1e-4` | 从零 | 1e-4 | 5.0M | 88.5 | **111.0** | 487 / 7,398 | 1.17 | 0.067 | −0.0137 | 5.2% | 56.3% | 11.5% | 1.5 | 20.8% |
| **C** `tiny_C_bc_s14` | **s14-BC 300k** → PPO | 1e-5 | 3.0M（+BC） | 1,038–1,334 | **1,293–1,600** | 3,133 / 8,628 | 1.16–1.32 | 0.091–0.098 | −0.0131 | 4.2% | **100%** | 22.9% | 52 | 58.3% |
| （参照）脚本上限 | teacher/spell | — | — | 1,312 | 1,400 | — / 3,728 | 1.08–1.15 | 0.03–0.09 | — | 0% | — | — | 78–90 | 17–100% |
| （参照）真实 10k+ | 人类 | — | — | 4,458 | 26,516 | — | **5.95** | ≈0.59 | — | — | — | — | ~200+ | — |

说明：
- A/B 的"5M 拍点（48 局）"是 t12/t15 = **22.0/22.5** 与 **100.0/118.5**；表里用的是收尾的
  96 局复核值（更稳）。C 的曲线是 **1M: 1354/1508 → 2M: 1334/1600（最好）→ 3M: 1038/1293**，
  评测只有 48 局而 t15 是重尾分布，±20% 是噪声量级。
- **C 的 1,600 已经超过 24 个脚本组合的最好值（1,400，+14%）**：容量不是瓶颈（§4.3）。
- **``Σ15/Σ12`` 全都在 1.2 左右，人类是 5.95**：这就是"指数段"缺失的定量表达。
- **饰品命中率 10–38%**（判据 60%）：0.667M 模型学会了"选一个饰品"（每局 2.06–2.33 次报价
  都能选到），但没学会"选对这张"。核心牌命中率 C 到了 **100%**（B 56%）。
- ``growth_dlog_late_p50``（t≥10 的每回合对数斜率中位数）= **0.00–0.10**，全部低于
  ``exp_growth`` 的基线 **0.35** ⇒ **超线性奖励项在大多数轨迹上是 0**（§4.3 第 3 层）。

### 4.2.1 判据逐条

| 判据 | 门槛 | A | B | C（最好） | 判定 |
|---|---|---|---|---|---|
| t15 Σ p50 | ≥ 10,000 | 18 | 111 | 1,600 | **✗**（C 只到 16%） |
| t12→t15 增长 | ≥ 3× | 1.00 | 1.17 | 1.32 | **✗**（人类 5.95） |
| 核心牌命中率 | ≥ 60% | 40.6% | 56.3% | **100%** | ✓（仅 C） |
| 饰品命中率 | ≥ 60% | 10.4% | 11.5% | 22.9% | **✗** |

**⇒ 判据未达成。** 三项里只有"核心牌命中率"在 BC 热启动臂上过线；绝对强度差
**6.3 倍**、指数段差 **2.3 倍**（1.32 vs 3.0）。
"1M 模型在无对战沙盒里学会复利阵容"这个命题，**在本阶段得不到支持**；
但支持了它的两个前提：**容量够**（C 打平/超过脚本上限）、**核心牌选择可以学会**（C 100%）。

### 4.3 为什么没到判据：三层诊断（每层都有数字）

**第 1 层——容量不是瓶颈。** 0.667M 的模型 **BC 300k 决策**（从 s14 蒸馏，CE 1.22、top1 0.523）
就能到 **t12 1,152 / t15 1,363**，是脚本上限的 96%，核心牌命中率 **97.9%**。
即：**这个尺寸足够表达沙盒里目前所有可表达的策略**——"模型太小所以学不会"不成立。

**第 2 层——从零学在这个预算里学不动。** 两条 from-scratch 臂（5M 决策、lr 3e-5 / 1e-4）：

- ``t12 Σ p50`` 只从 10（随机）走到 **13.5–22**（脚本 1,300 → 差 60–100×）；
- ``entropy`` 一直 0.67–0.70（≈ 合法动作上的均匀分布），``approx_kl`` 1e-5–3e-3（策略几乎不动）；
- 唯一在动的是 **``ep_len_mean`` 615 → 553**：模型学会了「少按按钮、早点结束回合」，
  而不是「买对牌」。``ep_LT_mean`` 在 0.28–0.53 之间横盘（Σ ≈ 30–90）；
- 施法数 p50 = **0**：一次酒馆法术都没学会放。

⇒ 15 回合 × 40 动作的**长程稀疏**问题（买 → 施法 → 载体 → 复利，链条 5+ 步）在 5M 决策里
没有被探索到；纯 on-policy 采样 + 均匀初始化 → 绝大部分轨迹是「把动作额度烧完」。

**第 3 层——环境的**「每金币价值产出」**本身就是线性的。**
这是判据不可达的根本原因（也是最有用的结论）：

- 沙盒金币 = ``gold_mode=set``，每回合固定 30 → 15 回合总金币 **450**；
  单张牌 ≈3 金币 ⇒ 整局**最多 ~150 次「价值事件」**（买/施法/触发）。
- 实测脚本上限 t12 Σ ≈ 1,312 ⇒ **≈ 2.9 Σ / 金币**。
- 真实 10k+ t12 Σ = 4,458 ⇒ **≈ 9.9 Σ / 金币**（同一分母下 3.4 倍）。
- 真实玩家的「每金币价值」之所以更高，正是**复利循环**：金币生成类饰品/法术（Bob's Tip Jar
  之类）、三连/金色（真实高强度战团 **62.1%** 身材来自 ``_G``）、以及「酒馆永久 buff ×
  场上 N 只」的**乘性放大**。沙盒里这些机制**都在**（引擎 100% 实现），但**固定收入 +
  每回合 40 动作**把「循环」压成了「线性」：收入不随身材增长，动作额度也不随回合增长。
- 佐证：``gold 99`` 与 ``gold 30`` 的脚本上限一样（§4.1）——不是钱不够，是**钱不能生钱**。

**结论**：判据（10,000 / 3×）在**当前沙盒口径下不可达**，与模型大小、训练时长无关。
用户的核心判断（**要学复利/几何成长**）**方向是对的**，但第一阶段的沙盒还**没有把复利写进经济**：
它只在「单回合内用金币把身材堆高」上是复利的（触发链 ×N），在**跨回合**上是线性的。

### 4.4 下一步（按性价比排序）

1. **给沙盒一个会复利的收入**（最高优先级，不改 Rust 机制、只改配置/规则）：
   - ``--gold-mode add`` + 「金币生成类」牌（引擎已有 trinket/spell 的 gold 效果）；
   - 把 ``gold_per_turn`` 做成**随身材/载体数增长**的课程（例如 ``gold = 10 + 2×carriers``），
     这样「买载体 → 收入↑ → 买更多载体」才形成正反馈；
   - 提供 ``--sandbox-income-scale``（收入 ∝ 上回合战团 Σ 的幂）作为**上界探针**，
     先测「有复利收入时脚本能到多少」，再决定要不要训。
2. **把「3× 指数段」当主判据、把绝对 Σ 当次要判据**：绝对 10k 依赖经济口径，
   ``Σ15/Σ12 ≥ 3`` 是**形状**判据，跨环境可比。建议在复利收入到位后，先要求
   ``exp_segment_rate ≥ 0.5``。
3. **1M 模型路线照旧、但必须有 BC 热启动**：本实验已证明 0.667M + 300k BC 就能打平脚本上限，
   ```--bc-teacher-from``（从 s14 或从「复利收入沙盒」里的强脚本）是最省的一步；
   从零 on-policy 训练在这个动作空间上不现实（§4.3 第 2 层）。
4. **把饰品做成「有后果的决策」**：现在 2 次饰品选择里命中率只有 0.17–0.38，
   因为训练信号里饰品的影响被 7 回合后的终局稀释。建议在奖励里加
   ``reward_mix`` 的 trinket 项（本次已具备 ``trinket_hits`` 度量）或做「饰品→中局」
   的分段价值。
5. **蒸馏进大模型之前先定「什么算学会」**：本文件给出的
   ``growth_slope_late / growth_curv / growth_ratio_12_15 / exp_segment_rate``
   四个指标已经落在 ``episode_summary`` 里（每局都记），可以直接当门禁。

---

## 5. 复现

```bash
# A：抓 Firestone comps（缓存到 runs/comp_lines/raw，--no-boards 可跳过 35 次请求）
python scripts/comp_lines_fetch.py                      # → data/scaling/comps_top.json

# B：饰品契约 + 指数成长奖励契约（20 项）
python -m pytest tests/test_sandbox_trinkets.py tests/test_economy_sandbox.py -q

# 沙盒脚本 CLI（单环境，看每回合 Σ / tier / 载体 / 施法 / 饰品）
python -m hsbg.az.train.economy_sandbox --policy spell --games 8 \
    --gold-per-turn 30 --turns 15 --sandbox-trinkets 1 --sandbox-reward exp_growth

# 可表达上限（脚本策略 × 24 组合，纯 CPU）
python scripts/sandbox_ceiling_probe.py --games 6 --json-out runs/comp_lines/ceiling.json

# C：1M 小模型（0.667M）+ 指数成长奖励 + 饰品
python scripts/train_economy_sandbox.py --from-scratch \
    --arch entity --d-model 128 --n-layers 2 --n-heads 4 --device cuda:7 \
    --decisions 5000000 --envs 128 --batch-decisions 16384 --minibatch 1024 --grad-accum 8 \
    --epochs 2 --sandbox-reward exp_growth --sandbox-growth-w-final 1.0 \
    --sandbox-growth-w-super 0.2 --sandbox-growth-slope-base 0.35 --sandbox-growth-from 10 \
    --sandbox-growth-w-ratio 0.3 --sandbox-trinkets 1 --gold-per-turn 30 --turns 15 \
    --action-cap 40 --eval-every 1000000 --eval-games 48 --core-from-comps 1 \
    --trinket-target-from-comps 1 --lr 3e-5 --entropy-coef 0.01 \
    --out runs/comp_lines/tiny_A_lr3e-5
# （BC 热启动臂：同上去掉 --from-scratch，加
#   --bc-teacher-from runs/az_entity_s14/model.pt --bc-decisions 300000 --bc-epochs 3 --bc-lr 3e-4 --lr 1e-5）

# D：图 + 判据汇总
python scripts/comp_lines_report.py --arms A,B,C \
    --out-dir runs/plots --json-out runs/comp_lines/summary.json
```

关键数字的机器可读入口：

| 内容 | 路径 |
|---|---|
| 阵容数据（含交集统计） | `data/scaling/comps_top.json`（``stats`` 段） |
| 可表达上限（24 组合） | `runs/comp_lines/ceiling.json` |
| 训练历史（逐 update / 逐 eval） | `runs/comp_lines/tiny_*/history.jsonl` |
| 判据汇总 | `runs/comp_lines/summary.json` |
| 图 | `runs/plots/comp_lines_{growth,training,comps,reward}.png` |

---

## 6. 边界与未做

- **判据的绝对量级**（10,000）本身可疑：真实 26,516 是「10k+ MMR、完整 8 人对战」的 t15，
  而沙盒无对手/无战斗/固定收入。要求沙盒复现 38% 的真实 Σ，等价于要求沙盒经济
  ≈ 真实经济，**这需要先修沙盒口径**（§4.4 第 1 条），而不是加训练量。
- **饰品的来源**：Firestone 没有 comp→trinket 官方映射，本文件的 ``trinkets`` 是三条证据
  合成（§1.4），已逐条给出 ``why``；如果要用作硬标签，需要人工复核 top-10 阵容的 40 张。
- **只测了 0.667M**：1.06M（d128×4 层）与 3.57M 没有跑（时间给到了 3 条臂的 lr/BC 对照）。
- **两条 from-scratch 臂在 5M 决策内没有学会经济**（§4.3 第 2 层），所以「1M 模型能否学复利」
  这个问题在本阶段**没有得到肯定答案**——目前能说的只有：**容量足够**（§4.3 第 1 层），
  **缺的是环境里的复利收入与热启动**。
- 未动 Rust（无机制改动）；未 kill / 未重启任何在跑的训练（全程 ``cuda:7`` 或 CPU，
  GPU 显存只多用 ~1 GB）。
