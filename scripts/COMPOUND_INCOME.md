# 复利收入：机制清单 + 三档探针 + 沙盒收入模式 + growth 重跑（三段式）

> 上一阶段（`docs/COMP_LINES_TINY.md`）的诊断：24 个脚本组合的 t15 Σ 上限只有 **1,400**，
> 金币 30 与 99 一样、动作上限 40 与 120 一样 → **瓶颈不是钱、不是动作额度，而是「收入不
> 随身材增长」**；实测 Σ/金币 = **2.9**，真实 10k+ 是 **9.9**（3.4 倍）。
>
> 本文件把这一条**当成唯一的瓶颈**来验证与修补，做四件事：
> **A** 从卡表里把「金币生成 / 法术生成 / 法术放大 / 酒馆永久 buff / 三连奖励」全部挖出来，
> 给每张卡一个**预估每回合额外收入**（`scripts/income_probe.py --inventory-only` →
> `runs/comp_lines/income_probe.json` 的 `inventory` 段）；
> **B** 三档探针（I0/I1/I2 + 对照 I0e/I0u）量化「引擎自带的收入机制」到底值多少；
> **C** 给沙盒加 `--gold-mode {fixed,add,growth}` + `--sandbox-income-scale`（默认关、
> 逐位等价），并加 growth 上界臂（I3/I4/I5）测「钱管够时脚本能到多少」；
> **D** 用 growth 模式 + s14-BC 热启动重跑 0.667M 模型 3M 决策，判据改成**形状**
> （`Σ15/Σ12 ≥ 3` 且 `t15 Σ ≥ 4,000`）。

## 0. 结论先行

1. **机制清单：103 张相关卡**（引擎 `implemented & reachable`），其中
   **金币生成 35 张、法术生成 25 张、法术放大 28 张、酒馆永久 buff 15 张**；
   另有 2 条机制级条目（三连奖励 → 金色 + 高 1 级 Discover；酒馆永久 buff × 买入次数）。
   **真正能「每回合重复」产生金币的只有 6 件饰品 + 1 个随从**（Accord-o-Tron）：
   Glowing Crystal（3 金/回合）、Azeroth Model Globe / Goblin Wallet / Rascal Sticker
   （各 1 金/回合）、Wand of Divination（1 金/回合，限 3 次）、Trickster's Sleeve（触发一次）。
   其余 29 张金币卡是**一次性**（Gain 2 Gold / 升到 tier6 给 12 金 / 12 金饰品…），
   摊到 15 回合后都 < 1 金/回合。
2. **三档探针（每档 200 局，脚本策略，纯 CPU）**：Σ/金币 **1.82–1.98**，**三档都到不了 4**
   （判据 ≥6，基线 2.9，真实 9.9）。**引擎自带的金币机制只把整局总金币从 450 提到
   466–470（+4%）**，t15 Σ 从 909 到 962–996（噪声内）。
   ⇒ 按任务给的判据，**引擎的经济上限与线上不一致**（缺口见 §5）。
3. **钱管够时的天花板也很低**：把收入改成 growth（`I3`：15%/回合 + 每载体 2 金，总金币
   2.59×）后 t15 Σ 只从 909/996 涨到 **1,236**（+36%），**Σ/金币反而掉到 0.93**；
   无金币上限（`I4`：总金币 **17.4×**）时 t15 Σ = **1,459**、Σ/金币 **0.19**；
   再翻倍到 39×（`I5`）时 t15 Σ = **1,274**、Σ/金币 **0.07**。
   ⇒ **多给钱不产生复利，只产生「每金币价值递减」**：转换被 7 个站位、40/120 次动作、
   每回合 7 张酒馆牌、每次施法固定 +X/+Y 钉死成**线性**。
   ⇒ **但引擎能表达人类量级**：I4 的单局 max **58,418 > 真实 p50 26,516**，只是
   **≥10,000 的局只占 3.0%**（p50 1,459）——「偶然能凑出来」≠「策略能稳定 farm」（§3.3）。
4. **沙盒侧的 `--gold-mode` 已落地**（`fixed`/`add`/`growth` + `--gold-add`
   `--gold-growth-rate` `--gold-per-carrier` `--sandbox-income-scale` `--gold-cap`）：
   默认 `fixed` 与改动前**逐位一致**（5 个策略 × 2 种奖励 × 6 个 seed 的动作流 sha256 /
   奖励 / Σ 轨迹全等）；`tests/test_sandbox_gold_modes.py` 17 项契约。
5. **growth 重跑 1M 小模型（0.667M，s14-BC 300k → PPO 3M）**：
   - **G15（任务指定**：growth 0.15 + 2/载体、cap 99、动作 40）：**best 在 1M**，
     192 局复核 **t15 Σ p50 = 1,608、Σ15/Σ12 = 1.22、Σ/金币 1.15**；3M 收尾**退化**到 586
     （p50 崩、rollout 均值没崩 → 变成重尾策略）。
   - **G35u（上界**：growth 0.35 + cap 0 + 动作 120）：192 局 **t15 Σ p50 = 2,770
     （t15 p90 4,975 / max 15,985）、Σ15/Σ12 = 1.14**，比固定 30 金的 tiny_C（1,600）**高 73%**、
     比同收入口径的脚本上限（1,459）**高 90%**。
   - ⇒ **判据 ✗**（4,000 的 69%、3× 的 38%）。**复利收入抬高了绝对 Σ，但没有抬高「每金币价值」**：
     `Σ15/Σ12` 全程 1.14–1.22（人类 5.95），`goldens_p50` 0–1、`tavern_buff_p50` 0 —— 乘性通道没打开。
6. **结论（§5）**：引擎**不是**「没有复利机制」，而是**这些机制在这个沙盒口径下无法被
   放大**——缺的不是「每回合多几金币」（39 倍金币也只把 Σ 推到 1.3–1.5k），而是
   **① 每金币价值随战团规模增长**（酒馆永久 buff 的乘性利用 / 金色卡占比 62.1%）、
   **② 动作额度 ∝ 收入**（40 动作最多花 120 金，growth 后 ~60% 金币是废的）、
   **③ 三连/金色的吞吐**（`goldens_p50`=1 vs 真实 62.1% 身材来源）。
   §5.2 给了 5 条可落地的引擎侧/沙盒侧改动与各自的**先行验证**方式。


---

## 1. 任务 A：收入机制清单（卡表）

脚本：`python scripts/income_probe.py --inventory-only`（数据源
`hsbg_engine.catalog_json()` = `rust/crates/hsbg-engine/data/cards.json` 37.0.0.255790）。
只保留 `implemented & reachable` 的卡，分类正则与估值口径写在
`scripts/income_probe.py` 的 `classify()` / `_multiplier()` 里，JSON 的
`inventory.method` 段是机器可读版本。

### 1.1 规模

| 类别 | 张数 | 说明 |
|---|---|---|
| 金币生成 `gold` | **35** | 文本里出现 `gain N Gold` / `increase your maximum Gold` / `Gold for each ...` |
| 法术生成 `spell_gen` | **25** | `get/discover/add ... Tavern spell`、`teach it that spell`、`cast a random Tavern spell` |
| 法术放大 `spell_amp` | **28** | `Your Tavern spells give an extra +X/+Y`、`cast a spell on a friendly minion` 复制类 |
| 酒馆永久 buff `tavern_buff` | **15** | `give minions in the Tavern +X/+Y this game` |
| 按卡种 | | minion 50 / trinket 34（lesser 19 + greater 15）/ tavern_spell 10 / hero_power 9 |
| 机制级 | 2 | `_triple_reward`（三连）、`_tavern_buff`（酒馆永久 buff 的乘性解释） |

> 估值口径：`est_gold_per_turn = 单次金币数 × 每回合触发次数`；触发次数用经验表
> （回合开始/结束 = 1、每两回合 = 0.5、每次买牌 = 8、每花 7 金 = 4、每 3 次施法 = 1、
> `(N left!)` → `min(rate, N/15)`、一次性 → 1/15）。**这是粗估**，真实值由 §2 的探针实测。

### 1.2 每回合可重复的金币来源（全部 7 条）

| 卡 id | 种 | 每回合 +金 | 口径 | 效果 |
|---|---|---|---|---|
| `BG36_MagicItem_220` | lesser trinket | **3.0** | 回合开始 | Glowing Crystal：每个不同友方种族 +1 金 |
| `BG26_147_G` | minion t3 | 2.0 | 回合开始 | Accord-o-Tron（金色）：+2 金 |
| `BG26_147` | minion t3 | 1.0 | 回合开始 | Accord-o-Tron：+1 金 |
| `BG30_MagicItem_425` | lesser trinket | 1.0 | 每两回合 | Azeroth Model Globe：+2 金 + Discover tier6（限 2 次） |
| `BG30_MagicItem_847` | lesser trinket | 1.0 | 回合结束 | Goblin Wallet：铸币上限 +1（**永久叠加**） |
| `BG36_MagicItem_424` | lesser trinket | 1.0 | 回合开始 | Rascal Sticker：每个金色随从 +1 金 |
| `BG36_MagicItem_307` | lesser trinket | 1.0 | 每 3 次施法 | Wand of Divination：+1 金（限 3 次） |

一次性金币（摘录，全部 29 张见 JSON）：`BG30_MagicItem_996` Bob's Tip Jar（+4 金、上限 +4）、
`BG35_MagicItem_818` Mysterious Orb（+10 金）、`BG35_MagicItem_814` Stuffed Coin Purse（到 tier6
+12 金）、`BG32_MagicItem_428` Worn Treasure Map（2 回合后 +10 金）、
`BG32_MagicItem_823` Wax Imprinter（+2 金/回合但只能 1 次）、7 张金币酒馆法术
（`BG28_810` Tavern Coin +1、`BG28_805` Strike Oil 上限 +1、`BG36_303` Corrupted Coin +2、
`BG28_800` Careful Investment +2、`BG33_815` Wealthy Bounty +2、`BG28_884` Overconfidence +3 胜）、
`TB_BaconShop_HP_076` Piggy Bank（+2 金/每局一次，随回合 +1）。

> **关键事实 1**：金币饰品的单张上限就是 **3 金/回合**（Glowing Crystal），一次性饰品摊薄后
> < 1 金/回合。相对 30 金/回合的基线，**全部金币机制加起来也只有 ~10% 的量级**。

### 1.3 法术生成（把「法术」当成一种收入）

| 卡 id | 种 | 每回合法术 | 效果 |
|---|---|---|---|
| `BG36_MagicItem_852` | lesser trinket | **2** | Willbreaker Sticker：2 张随机酒馆法术，回合开始重复 |
| `BG30_MagicItem_420t` | greater trinket | **2** | Book of Medivh（大）：回合开始 Discover 2 张酒馆法术 |
| `BG35_MagicItem_851` | lesser trinket | 2 | Water Wheel：每个元素 +1 张（每回合 2 次） |
| `BG35_MagicItem_750` | greater trinket | 2 | Magicfin Sticker：每买 1 张酒馆法术 → 1/1 鱼人并教会它 |
| `BG36_MagicItem_372` | greater trinket | 1（×3 份） | Sphere of Memory：回合结束给上一张法术的 3 份复制 |
| `BG30_MagicItem_420` | lesser trinket | 1 | Book of Medivh：回合开始 Discover 1 张 |
| `BG36_764` / `_G` | minion t4 | 1（2/4 张） | Gearfin：回合结束给 2（金色 4）张 1 费酒馆法术 |
| `BG35_123` / `_G` | minion t5 | 1（1/2 份） | Cataclysmic Harbinger：回合结束给上一张法术的复制 |
| `BG33_891_G` | minion t6 | 2 | Magicfin Mycologist：每买酒馆法术 → 1/1 鱼人（每回合 2 次） |
| `BG32_821` / `_G` | minion t5 | 1 | Felfire Conjurer：回合结束「你的酒馆法术额外 +1/+1」 |

法术放大（28 张）里对「每金币价值」最关键的 7 张饰品：`BG36_MagicItem_373`
Multilayered Shield（+1/+2，按种族数增强）、`BG36_MagicItem_371` Honeycomb Ring、
`BG32_MagicItem_801t` Heart of the Forest、`BG32_MagicItem_270t` Wicked Tome、
`BG36_MagicItem_418` Tome of the Ancients、`BG36_MagicItem_211` Lovely Locket
（**一次施法变两次**）、`BG36_MagicItem_831` Felsteel Cleaver（法术被随从吸收成身材）。

> **关键事实 2**：法术生成是**真实的收入机制**（Willbreaker / Book of Medivh 每回合 1–2 张），
> 但每张法术的收益是**固定 +X/+Y**，所以它把 Σ 拉成 `O(金币)` 而不是 `O(金币^2)`；
> 唯一能把它变成乘性的是 `Lovely Locket`（施法翻倍）与 `Multilayered Shield`（每种族 +1/+2）。

### 1.4 三连奖励与酒馆永久 buff（乘性来源）

- **三连奖励**（`content::triple_reward_item`）：3 张同名 → **金色**（身材 ×2、金色效果）
  **+ Discover 一张高 1 级的随从**。真实高强度战团 **62.1% 身材来自 `_G`**
  （`docs/COMP_LINES_TINY.md` §1），是「买牌数 × 池子宽度」的线性函数，但**金色效果
  本身常常是乘性**（金色 Accord-o-Tron +2 金、金色 Gearfin 4 张法术…）。
- **酒馆永久 buff**（`stats.tavern_atk/tavern_hp`，15 张卡）：`BG28_707` Living Azerite
  （每次施法给酒馆元素 +4/+3）、`BG36_762` Devilish Distractor（每次对它施法给酒馆 +1/+2）、
  `BG27_016` Champion of Sargeras（+8/+8）、`BG28_886` Staff of Enrichment（+2/+2）、
  `BG30_MagicItem_544t` Nomi Sticker（每元素 +5/+5）。
  乘性在于 **「每回合买 N 张被永久 buff 过的酒馆随从 = N 份 buff 进战团」**，而 N ∝ 金币。

> 探针里 `tavern_buff_p50` 只有 **4–8**、`goldens_p50` = **1**（15 回合）——**脚本完全没吃到
> 这两条乘性来源**。这正是「引擎机制在、但沙盒口径下无法被放大」的直接证据（§5）。

---

## 2. 任务 B：沙盒加「会复利的收入」（默认关、逐位等价）

### 2.1 用法

```bash
# 现状（默认）：每回合把金币重置为 30，逐位等价旧的 --gold-mode set
python -m hsbg.az.train.economy_sandbox --gold-mode fixed --gold-per-turn 30

# 线性收入：引擎自然补币 + 30 + 5×(turn−1)（模拟「每回合多 k 金」的金币饰品）
python -m hsbg.az.train.economy_sandbox --gold-mode add --gold-per-turn 30 --gold-add 5

# 几何收入 + 载体正反馈：引擎自然补币 + 30×1.15^(turn−1) + 2×上回合载体数
python -m hsbg.az.train.economy_sandbox --gold-mode growth --gold-per-turn 30 \
    --gold-growth-rate 0.15 --gold-per-carrier 2

# 上界探针：金币不封顶（引擎自己的 (base+max_gold_bonus).min(99) 仍只作用于自然补币）
python -m hsbg.az.train.economy_sandbox --gold-mode growth --gold-growth-rate 0.35 --gold-cap 0
```

| 参数 | 默认 | 语义 |
|---|---|---|
| `--gold-mode` | `fixed` | `fixed`（=旧 `set`，**重置**为 `gold_per_turn`）/ `add`（引擎收入 + `base+k×(t−1)`）/ `growth`（引擎收入 + `scale×(base×(1+r)^(t−1) + per_carrier×载体数)`） |
| `--gold-per-turn` | 10（训练脚本）/30（探针） | base 收入 |
| `--gold-add` | 0 | `add` 的线性斜率（每回合 +k） |
| `--gold-growth-rate` | 0.0 | `growth` 的复利率（0.15 = 每回合 ×1.15） |
| `--gold-per-carrier` | 0 | `growth` 的「每个上回合在场载体 +N 金」（滚雪球项） |
| `--sandbox-income-scale` | 1.0 | 注入项整体缩放（**上界探针**） |
| `--gold-cap` | 99 | 注入后的金币上限（0 = 不封顶）；99 与引擎 `(base+max_gold_bonus).min(99)` 一致 |

**语义要点**：`fixed` **覆写**回合开始的金币（所以饰品的「回合开始 +金」会被抹掉）；
`add`/`growth` **不覆写**，在引擎本回合给出的金币上**叠加**，所以引擎的金币生成
（饰品 / max-gold / `gold_next_turn`）全部保留。引擎自然补币仍是
`min(start_gold + gold_increment×(t−1), gold_refill_cap)` = **3→10**。

### 2.2 逐位等价（默认关）

- 反向补丁验证：把改动后的模块反向还原成改动前的版本，**5 个脚本策略**（`end` / `spell` /
  `teacher` / `carrier_teacher` / `greedy`）× **2 种奖励**（`log_strength` / `exp_growth`）
  × **6 个 seed**：动作流 **sha256 完全相同**、整局奖励逐位相同、`sigma_by_turn` 完全相同
  （`/tmp/inc_probe/equiv.py`；默认 `gold_mode=fixed` 走的就是旧 `set` 分支）。
- 单测 `tests/test_sandbox_gold_modes.py`：
  - 三档 `income_for_turn(t)` 与实测 `gold_income_hist` / `gold_start_hist` 逐项正确
    （含自然补币 3→10、`gold_cap`、`income_scale`、`gold_per_carrier`、第 1 回合 0 载体）；
  - `fixed` ≡ 旧 `set`；`growth(r=0, per_carrier=0)` ≡ `add(gold_add=0)`；
  - 三档 × `--sandbox-trinkets {None,1,0}` 都能跑、饰品报价次数与金币口径互不影响；
  - `summarize()` 新增 `gold_total_income_p50` / `sigma12_per_gold_p50` / `sigma15_per_gold_p50`。

### 2.3 新增度量

`measure()` 现在记录 `gold_income`（本回合注入项）、`gold_start`（回合开始实际金币）、
`goldens`（金色卡数）；`episode_summary()` 增加 `gold_start_hist` / `gold_income_hist` /
`gold_total_income`（整局拿到的金币 = **Σ/金币 的分母**）/ `goldens_t15`；`summarize()`
给出 `sigma12_per_gold_p50`（与文档的 2.9 / 9.9 同口径）与 `goldens_p50`。

---

## 3. 任务 C：三档探针（+ 两个对照与三个上界）

`python scripts/income_probe.py --games 200 --workers 12`（纯 CPU，~390 s；每档 200 局，
`--turns 15 --action-cap 40 --sandbox-trinkets 1`，策略 = `spell` 基线脚本 + 收入偏好）。

| 档 | 收入口径 | 饰品选择 | Σ/金币（t12） | t12 p50 | **t15 p50** | t15/Σ12 | 金色 p50 | 施法 p50 | 金币饰品命中 |
|---|---|---|---|---|---|---|---|---|---|
| **I0** | `fixed` 30/回合（**现状**） | 第一个买得起的 | **1.86** | 838 | **909** | 1.04 | 1 | 68 | 0.19 |
| I0u | `fixed` 30（解除脚本刷新上限） | 同 I0 | 1.98 | 890 | 992 | 1.08 | 1 | 74 | 0.19 |
| I0e | 引擎收入 30/回合（**不覆写**） | 同 I0 | 1.88 | 878 | 996 | 1.08 | 1 | 78 | 0.13 |
| **I1** | I0e | **优先金币生成饰品** | **1.82** | 878 | **962** | 1.10 | 1 | 78 | **0.47** |
| **I2** | I0e | 金币 > 法术生成 > 法术放大 + 优先买收入牌 | **1.91** | 890 | **941** | 1.06 | 1 | 78 | 0.47 |
| I3 | `growth` 0.15 + 2/载体（cap 99） | 同 I2 | 0.93 | 1084 | 1236 | 1.02 | 1 | 96 | 0.46 |
| I4 | `growth` 0.35、**无上限**、动作 120 | 金币/法术饰品（不买收入牌） | 0.19 | 1459 | 1459 | 1.00 | 1 | 101 | 0.41 |
| I5 | `growth` 0.45、无上限、动作 120 | 同 I4 | 0.07 | 1222 | 1274 | 1.00 | 1 | 94 | 0.48 |

补充数字：

| 档 | 总金币（p50） | 相对 450 | 每回合金币 p50 | 载体率 | 酒馆 buff p50 | 金币饰品出现在报价里 | 法术饰品命中 |
|---|---|---|---|---|---|---|---|
| I0 | 450 | 1.00× | 30 | 0.28 | 4 | 0.47 | 0.08 |
| I0e | 466 | 1.04× | 31 | 0.31 | 4 | 0.47 | 0.07 |
| I1 | 470 | 1.04× | 31 | 0.31 | 4.5 | 0.47 | 0.08 |
| I2 | 470 | 1.04× | 31 | 0.32 | 4 | 0.48 | 0.30 |
| I3 | 1166 | **2.59×** | 78 | 0.33 | 8 | 0.46 | 0.34 |
| I4 | 7804 | **17.4×** | 520 | 0.37 | 8 | 0.43 | 0.32 |
| I5 | 17652 | **39.2×** | 1177 | 0.37 | 8 | 0.49 | 0.25 |

### 3.1 判据逐条

| 判据 | 门槛 | 最好的一档 | 判定 |
|---|---|---|---|
| Σ/金币（t12 口径） | **≥ 6**（真实 9.9 的 60%） | **1.98**（I0u）/ 1.91（I2） | **✗**（差 3.0×） |
| Σ/金币 下限 | ≥ 4 | 全部 ≤ 1.98 | **✗** |
| 引擎金币机制价值 | 显著 > 0 | +4%（450→466/470） | **✗**（噪声量级） |
| t15 Σ | ≥ 4,000（§4 判据） | 1459（I4，钱 17 倍） | **✗**（差 2.7×） |
| t12→t15 形状 | ≥ 3× | 1.10（I1） | **✗** |

**⇒ 三档都到不了 4 ⇒ 按任务给的判据：引擎的经济上限与线上不一致**，需要报告缺口（§5）。

> **口径对齐**：文档里的 **2.9** 是 `docs/COMP_LINES_TINY.md` §4.1 那 24 个组合里**最好**的一个
> （gold 99 + 免费 tier6，t12 = 1,312 → 1,312/450 = 2.9）。同口径的「spell / cap40 / gold30 /
> 无免费 tier6」在 ceiling probe 里是 t12 988 → **2.20**；本探针 I0（同策略、200 局 p50）是
> **1.86**。差异来自样本量（6 局 vs 200 局，t15 是重尾）与 `free_tier6`。
> **结论不受影响**：无论 1.86 还是 2.9，都离 6 差 2–3 倍。

### 3.2 三条对机制的直接读数

1. **金币机制是「真的、但很小」**：金币饰品命中率从 0.13 提到 **0.47**（I1），总金币只从
   466 涨到 470（**+0.9%**）——因为每件饰品顶多 +3 金/回合，而它还要占掉一个饰品位
   （本该给「法术放大」）。I1 的 t15 Σ **没有**超过 I0e（962 vs 996）。
2. **法术生成比金币生成值钱**：I2 的法术饰品命中率 0.08→**0.30**，Σ/金币 1.88→1.91、
   t15 941（与 I1 同量级）。原因同上：法术收益是**固定 +X/+Y**，多一张法术 = 多一次线性项。
3. **钱越多、每金币越不值钱**：总金币 2.6×→17×→39×，t15 Σ 1,236→1,459→1,274，
   Σ/金币 0.93→**0.19**→**0.07**。**没有任何「收入↑ → 身材↑ 更快」的迹象**；
   多出来的钱被 7 个站位、动作额度、每回合 7 张酒馆牌、固定 buff 量吃掉。

### 3.3 重尾：引擎**能**表达人类量级，但只有 ~3% 的局摸到

| 档 | t15 p50 | p90 | p99 | max | ≥4,000 占比 | ≥10,000 占比 |
|---|---|---|---|---|---|---|
| I0（现状） | 909 | 2,121 | 7,616 | 9,453 | 2.5% | 0.0% |
| I1 | 962 | 2,250 | 3,629 | 10,129 | 1.0% | 0.5% |
| I3（growth 0.15） | 1,236 | 3,271 | 5,664 | 7,284 | 7.0% | 0.0% |
| I4（growth 0.35、无上限、动作 120） | 1,459 | 4,494 | 23,053 | **58,418** | 13.0% | **3.0%** |
| I5（growth 0.45、无上限、动作 120） | 1,274 | 5,552 | 18,672 | 22,830 | 15.5% | **3.5%** |

**读法（很重要）**：I4 的单局 max **58,418 已经超过真实 10k+ 的 p50（26,516）** ⇒
**引擎不是表达不了人类量级的战团**；但它的 **p50 只有 1,459**、只有 **3%** 的局能过 10k。
即：缺口不是「机制不存在」，而是「**稳定地**把乘性链条凑齐」——
脚本的 `tavern_buff_p50` 只有 8、`goldens_p50` = 1，说明这些局是**偶然**凑出来的，
不是被策略**瞄准**的。这正是 §5.2 要补的东西（让乘性链条可被策略稳定地 farm）。

---

## 4. 任务 D：growth 模式重跑 1M 小模型（BC 热启动）

配方 = `docs/COMP_LINES_TINY.md` §4/§5 的 C 臂（0.667M，`entity d_model=128 layers=2 heads=4`，
`s14-BC 300k → PPO`，`exp_growth` 奖励 w1=1.0 / w2=0.2 / base 0.35 / from 10 / w3=0.3，
`--sandbox-trinkets 1 --turns 15 --gold-per-turn 30`），**只改收入口径**：

| 臂 | 收入口径 | 动作额度 | 输出 |
|---|---|---|---|
| **G15** | `growth` 0.15 + 2/载体，`--gold-cap 99`（**任务指定**） | 40 | `runs/comp_lines/tiny_G15_growth` |
| G35u（上界） | `growth` 0.35 + 2/载体，`--gold-cap 0` | 120 | `runs/comp_lines/tiny_G35u_growth` |

```bash
python scripts/train_economy_sandbox.py \
  --from-scratch --arch entity --d-model 128 --n-layers 2 --n-heads 4 --device cuda:7 \
  --decisions 3000000 --envs 64 --batch-decisions 16384 --minibatch 1024 --grad-accum 8 \
  --epochs 2 --sandbox-reward exp_growth --sandbox-growth-w-final 1.0 \
  --sandbox-growth-w-super 0.2 --sandbox-growth-slope-base 0.35 --sandbox-growth-from 10 \
  --sandbox-growth-w-ratio 0.3 --sandbox-trinkets 1 \
  --gold-mode growth --gold-per-turn 30 --gold-growth-rate 0.15 --gold-per-carrier 2 \
  --turns 15 --action-cap 40 --eval-every 1000000 --eval-games 48 \
  --core-from-comps 1 --trinket-target-from-comps 1 --lr 1e-5 --entropy-coef 0.01 \
  --bc-teacher-from runs/az_entity_s14/model.pt --bc-decisions 300000 --bc-epochs 3 \
  --bc-lr 3e-4 --out runs/comp_lines/tiny_G15_growth
```

### 4.1 结果

两臂都是 `0.667M`、`BC 300k`（s14 教师，CE 1.18/1.11、top1 0.53/0.49）→ PPO 3M，**各 ~48 分钟**
（`cuda:7`，~1,000–1,350 dec/s）。判据数字用**同口径 192 局复核**（`scripts/eval_income_sandbox.py`，
复用训练脚本的 `evaluate()`，`sample=True` T=1），括号里是训练里每 1M 的 48 局评价值。

| 臂 | 收入口径 | 决策 | t12 p50 | **t15 p50** | t15 p90 / max | **Σ15/Σ12** | Σ/金币 | 金色 p50 | 施法 p50 | 核心牌 | 饰品命中 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **G15**（任务指定；**best = 1M**） | growth 0.15 + 2/载体，cap 99，动作 40 | 1.0M(+BC) | 1,334 | **1,608** | 2,897 / 9,275 | **1.22** | **1.15** | 0 | 31 | 1 | 0.18 |
| G15（3M 收尾，**退化**） | 同上 | 3.0M | 430 | 586 | 1,018 / 4,107 | 1.38 | — | 0 | 36 | 1 | 0.06 |
| **G35u**（上界：钱不封顶 + 动作 120） | growth 0.35 + 2/载体，cap 0，动作 120 | 3.0M(+BC) | 2,470 | **2,770** | 4,975 / 15,985 | **1.14** | 0.32² | 1 | 54 | 1 | 0.20 |
| （参照）I3 **脚本** | 同 G15 收入 | — | 1,084 | 1,236 | 3,271 / 7,284 | 1.02 | 0.93 | 1 | 96 | — | — |
| （参照）I4 **脚本** | 同 G35u 收入 | — | 1,459 | 1,459 | 4,494 / 58,418 | 1.00 | 0.19 | 1 | 101 | — | — |
| （参照）tiny_C（fixed 30，上一阶段 C 臂） | fixed 30 | 3.0M(+BC) | 1,038–1,334 | 1,293–1,600 | 3,133 / 8,628 | 1.16–1.32 | 2.9¹ | 1 | 52 | 100% | 0.23 |

¹ tiny_C 的 Σ/金币 = t12 1,312 / 450（`docs/COMP_LINES_TINY.md` §4.3）。
² G35u 的金币 p50 = **7,796**（无上限），其中能花掉的只有 `120 动作 × 3 金 × 15 回合 ≈ 5,400`，
所以它的 Σ/金币 被「花不出去的金币」压低了 —— **这一档只能看绝对 Σ，不能看 Σ/金币**。

**判据逐条**：

| 判据 | 门槛 | G15（best） | G35u（上界） | 判定 |
|---|---|---|---|---|
| t15 Σ p50 | **≥ 4,000** | 1,608（40%） | 2,770（69%） | **✗** |
| Σ15/Σ12 | **≥ 3** | 1.22 | 1.14 | **✗**（人类的 1/4） |
| Σ/金币 | ≥ 6 | 1.15 | 0.32² | **✗** |

### 4.2 四条读数

1. **复利收入确实抬高了绝对 Σ，而且模型比脚本更会用钱**：
   B 臂（growth 0.35 + 动作 120）t15 p50 **2,770**，比同收入口径的脚本上限 I4（1,459）**高 90%**，
   比固定 30 金的 tiny_C（1,600）**高 73%**。⇒「收入 → 价值」的管道没有断，训练也确实吃到了它。
2. **但形状不动**：三档的 `Σ15/Σ12` = **1.14–1.22**（tiny_C 1.16–1.32、人类 **5.95**）。
   `exp_segment_rate`（Σ15/Σ12 ≥ 3 的局占比）= **0–0.06**（G15 收尾那版 0.10 是唯一亮点，
   但它的绝对 Σ 只有 586）。⇒ **没有出现「指数段」**。
3. **乘性通道一次都没打开**：`goldens_p50` = **0–1**（真实 62.1% 身材来自金色）、
   训练 eval 的 `tav`（酒馆永久 buff）= **0–4**（脚本 I3/I4 也只有 8）。即：模型学会的是
   「用金币换更多线性项（法术/身材）」，**没学会**「用触发次数/金色/酒馆 buff 把线性项变乘性项」。
4. **G15 训练不稳定（负结果）**：48 局 p50 从 BC 起点 1,418 → 1M **1,512** → 2M 1,120 → 3M **586**；
   同一时间 rollouts 的 `ep_LT_mean` 还在 0.68→0.75（Σ≈2.3k），`value_loss` 0.24→0.05 ——
   即 **p50 崩了、均值没崩**：策略变成了「少数局爆大、多数局摆烂」的重尾分布，
   而 p50 判据正好惩罚这个。上界臂 G35u 则是单调上升（1,534→1,817→2,344→2,672）。
   结论：`growth 0.15 + 动作 40 + cap 99` 这个组合下，3M PPO **不足以稳定收敛**；
   要复现这一档必须留 1M 的 `model_step_1000000.pt`（本文的所有 G15 数字都用它）。

---

## 5. 结论

### 5.1 引擎经济够不够？——「机制齐全，但在这个沙盒口径下无法放大」

| 问题 | 答案 | 证据 |
|---|---|---|
| 引擎有没有「金币生成」机制？ | **有，但很小** | 35 张金币卡（§1.2），每回合可重复的只有 7 条，单张上限 +3 金/回合；实测金币饰品命中率 0.13→0.47 只把总金币从 466 提到 470（**+0.9%**） |
| 引擎有没有「法术生成」？ | **有，比金币值钱** | 25 张法术生成卡；I2 的法术饰品命中率 0.08→0.30，Σ/金币 1.88→1.91 |
| 引擎有没有「乘性」机制？ | **有，但一次都没被用上** | 三连/金色（`goldens_p50` 0–1）、酒馆永久 buff（`tavern_buff_p50` 0–8）、触发放大器（Brann/Titus/Drakkari 在池子里） |
| 「多给钱」能不能补上 3.4×？ | **不能，且会掉效率** | 总金币 2.59×→17.4×→39.2×，t15 Σ 1,236→1,459→1,274，**Σ/金币 0.93→0.19→0.07** |
| 「多给动作」能不能补上？ | **不能单独补** | I4（动作 120 + 钱 17 倍）t15 Σ 1,459，与 I3（动作 40、钱 2.6 倍）1,236 同量级 |
| 引擎能不能**表达**人类量级？ | **能，但只有 ~3% 的局** | I4 的单局 max **58,418 > 真实 p50 26,516**，但 p50 只有 1,459、≥10k 占 3.0%（§3.3） |

**⇒ 按任务判据：三档 Σ/金币 = 1.82 / 1.91（I1/I2）都到不了 4，引擎的经济上限与线上不一致。**
但把原因归到「收入不够」是**错的**：真正缺的是**每金币价值**。用同一个「每金币产出」尺子：

- 沙盒（固定 30 金/回合，脚本）：Σ12/金币 = **1.86**（本探针 200 局）/ **2.9**（文档的最好组合）；
- 真实 10k+（用**沙盒**分母 450）：**9.9**（t12），即 3.4–5.3 倍缺口；
- 真实 10k+（用**真实收入**：t12 ≈ 92 金、t15 ≈ 150 金）：t12 **≈ 48**、t15 **≈ 177**
  ⇒ 缺口 **17–26 倍（t12）/ 60–90 倍（t15）**。

后一个口径才是机制层面的真相：真实战团不是「钱多」（真实 15 回合只有 ~150 金），而是
**每 1 金在后期能换到 10–50 点身材**（永久酒馆 buff × 买入次数、金色 ×2、触发放大 ×2 叠出来的）。
沙盒里这个数从头到尾是 **~2**。**所以「3.4×」是被同一个 450 分母掩盖过的低估**。

### 5.2 需要补的机制/数值（引擎侧/沙盒侧改动的依据）

按性价比排序（每条都给了「怎么先验证」）：

1. **动作额度 ∝ 收入**（最硬的结构性限制）。现在 `max_actions_per_turn=40` → 每回合最多花
   ~120 金；growth 到 200+ 金/回合后 **~60% 的金币是废的**（I3：金币 2.59× 只换 Σ +36%）。
   落地：沙盒加 `--action-cap-per-gold N`（每 N 金 +1 动作）或直接用已有的
   `--sandbox-action-cap-ramp` 跟着金币档位升。**先验证**：I3 配置 + 动作 80/120，看 Σ 是否
   从 1,236 抬到 2.5k+（I4 的 1,459 说明「只加动作、不加乘性」仍不够，所以这条必须与 2/3 一起做）。
2. **让「酒馆永久 buff」成为可 farm 的乘性项**。引擎 15 张卡 + `stats.tavern_*` 都在，但沙盒里
   15 回合只攒到 0–8 点；真实是「每回合 5–10 次施法 × 每次 +1~+5 × 再被触发/金色翻倍」。
   落地：① 沙盒加 `--tavern-buff-scale K`（上界验证：K=3–5 时脚本 t15 能否到 5k）；
   ② 引擎侧提高这批卡的权重/出现率，或让「施法 → 酒馆 buff」的转换率随 tier 上升。
3. **三连/金色的吞吐**。`goldens_p50` = **1**，而真实 62.1% 身材来自 `_G`。三连需要同名牌 ×3，
   沙盒每回合只有 7 张牌 + 40 动作。落地：① 提高刷新上限/池子宽度（`--action-cap` 已有，
   但需要配 1）；② 把「金色/三连」加进奖励混合（现在 `--sandbox-reward-mix` 只有
   `tier/carrier/tavern/spells/gold/sigma`，缺 `golden:` 项）。
4. **触发放大器进 BC 教师**。Brann（战吼两次）/Titus（亡语两次）/Drakkari（回合结束两次）
   是真实 CORE 出现频率最高的三张（7/4/3 次，`docs/COMP_LINES_TINY.md` §1），
   但在 0.667M + 3M 决策里完全没被用上。落地：用 §3 的 `IncomePolicy`（I2/I3 的
   「收入偏好」脚本）或专门的「放大器教师」做 BC —— 比从零探索便宜一个量级。
5. **（数值）收入 ∝ 规模**。`--gold-per-carrier` 已支持，但 7 站位让载体饱和在 7
   （最多 +14 金/回合）。要真正滚雪球，需要把「载体数」从站位里解耦（例如按
   「本局买过的载体总数」或「战团 Σ 的幂」计收入）——这是**引擎侧规则**，不是沙盒曲线。

### 5.3 对判据本身的建议

- **10,000 这个绝对量级在当前沙盒口径下不可达**：脚本 ~1.5k、模型 ~2.8k（最好），
  10k 是模型上限的 3.6 倍。它不是「再训久一点」的问题 —— 收入 39 倍时 Σ 也只有 1.3k。
- **建议主判据改成形状 + 相对量**：`Σ15/Σ12 ≥ 2`（先）→ `≥ 3`（人类 5.95 的一半），
  绝对 Σ 的门槛按「收入口径」定义（例如 growth 0.35 + 动作 120 下 t15 ≥ 4,000）。
- **一个可用的中间目标**：把 `tavern_buff_p50` 从 0–8 抬到 100+、`goldens_p50` 从 1 抬到 3+。
  这两个数一旦动，形状才可能动；它们比 `t15 Σ` 更早给出信号（也已经在
  `episode_summary()` 里，每局都记）。

---

## 6. 复现

```bash
# A：机制清单（纯 CPU，秒级）→ runs/comp_lines/income_probe.json 的 inventory 段
python scripts/income_probe.py --inventory-only --json-out runs/comp_lines/income_probe.json

# B：三档探针 + 对照/上界（200 局/档，12 进程，纯 CPU，~6.5 分钟）
python scripts/income_probe.py --games 200 --workers 12 \
    --json-out runs/comp_lines/income_probe.json

# C：收入模式契约（17 项）+ 沙盒/饰品旧契约（20 项）
python -m pytest tests/test_sandbox_gold_modes.py tests/test_economy_sandbox.py \
    tests/test_sandbox_trinkets.py -q

# D：growth 重跑（cuda:7；BC 300k + PPO 3M，~50 分钟/臂）
#    G15：见 §4 命令；上界臂加 --gold-growth-rate 0.35 --gold-cap 0 --action-cap 120

# E：同口径 192 局复核（复用训练脚本的 evaluate()；sample + greedy 各一遍）
python scripts/eval_income_sandbox.py \
    --checkpoint runs/comp_lines/tiny_G15_growth/model_step_1000000.pt \
    --games 192 --device cuda:7 --gold-mode growth --gold-growth-rate 0.15 \
    --gold-per-carrier 2 --gold-cap 99 --action-cap 40 \
    --json-out runs/comp_lines/tiny_G15_eval192.json
python scripts/eval_income_sandbox.py \
    --checkpoint runs/comp_lines/tiny_G35u_growth/model.pt \
    --games 192 --device cuda:7 --gold-mode growth --gold-growth-rate 0.35 \
    --gold-per-carrier 2 --gold-cap 0 --action-cap 120 \
    --json-out runs/comp_lines/tiny_G35u_eval192.json

# F：沙盒 CLI 直看三档金币轨迹（每回合一行）
python -m hsbg.az.train.economy_sandbox --policy spell --games 4 --gold-mode growth \
    --gold-per-turn 30 --gold-growth-rate 0.15 --gold-per-carrier 2 --sandbox-trinkets 1
```

> **验证**：`python -m pytest tests -q` 全库 **762 passed / 8 skipped / 0 failed**（进度 100%；本机 load ~190 时有两次 pytest 在收尾 flush 阶段被资源压力终止，进度条仍是全绿、无 FAILED）。触及 `economy_sandbox` 的 6 个测试文件（54 项）单独跑也全绿；`--gold-mode` 的 17 项契约在 `tests/test_sandbox_gold_modes.py`。

机器可读入口：

| 内容 | 路径 |
|---|---|
| 机制清单 + 三档/上界探针结果 | `runs/comp_lines/income_probe.json`（`inventory` / `arms` / `verdict`） |
| 探针日志 | `runs/comp_lines/income_probe.log` |
| growth 训练历史 | `runs/comp_lines/tiny_G15_growth/history.jsonl`、`runs/comp_lines/tiny_G35u_growth/history.jsonl` |
| 训练日志 | `runs/comp_lines/tiny_G15.log`、`runs/comp_lines/tiny_G35u.log` |
| 192 局复核 | `runs/comp_lines/tiny_G15_eval192.json`、`runs/comp_lines/tiny_G35u_eval192.json` |

---

## 7. 边界与未做

- **探针的「脚本策略」是下界**：I4/I5 里脚本在有 17–39 倍金币时反而更差（Σ/金币 0.19/0.07），
  一部分是策略问题（它会把金币换成不缩放的身材/收入牌，且 `spell` 脚本的刷新上限、手牌 10 张
  上限会浪费动作）。**「引擎经济上限」的严格说法是「在 7 站位 / 40–120 动作 / 每回合 7 张
  酒馆牌的约束下，手写脚本只能把金币线性换成 Σ」**；模型是否能用酒馆永久 buff 与金色卡
  把这条线掰成曲线，由 §4 的 growth 重跑来回答。
- **估值是粗估**：`est_gold_per_turn` 假设触发都命中；`(N left!)`/`Once per game`/`Then swap`
  按 15 回合摊。清单用于**排序与找机制**，不是精确经济模型。
- **未改 Rust**：`--gold-mode` 全部落在 Python 沙盒（`debug set_player gold`），
  引擎机制/数值一个字节没动；`cargo test` 无需重跑。
- **未做**：`--gold-mode add` 下的「收入 ∝ 上回合战团 Σ 的幂」（`Σ^α`）——如果 §5 的结论是
  要「每金币价值随规模上升」，那是一个**引擎侧**改动（buff 乘性），不是沙盒的收入曲线能模拟的。
