# 流派（archetype）软偏置人类操作

> 状态：**已实现、默认关闭（`--archetype-bias-coef 0`）、完成 A/B（见 §7）**。
> 一句话：用 Firestone 人类对局离线学出「流派 → 该流派人类在该回合怎么打」的偏好表，
> 训练时在**合法动作的 logit** 上给这些偏好动作加一个**非负**小量，让策略「按该流派的
> 人类范式打」，但**不屏蔽**任何动作 —— 是引导，不是硬约束。

## 1. 动机（用户诉求）

用户诉求：「遇到固定流派时，强制/引导模型按该流派的人类范式操作（先软后硬）」。

硬约束（改写 mask / 强制动作）问题很大：一旦识别错，PPO 就再也学不到「识别错时该怎么
补救」，而且会让 on-policy 数据分布与策略脱钩（记录的动作不是策略会选的动作）。所以
**第一步只做软偏置**：

- 只加不减：`logits[a] += bias[a]`，`bias >= 0`；
- 不屏蔽：mask 一位都不动，PPO 仍可偏离（`old_logprob` 仍是真实采样分布）；
- 低置信不动手：检测概率 `< --archetype-min-prob=0.6` 时 bias 恒 0；
- 默认关闭：`coef=0` 不构造对象、不新增 meta 键、不传额外 kwargs → **与旧路径逐位等价**
  （单测 `test_coef_zero_is_legacy_and_bitwise` 直接用同 seed 两实例比动作序列）。

## 2. 数据与两段式分类器

### 2.1 数据

| 数据 | 规模 | 用途 |
|---|---|---|
| `data/firestone_replays/firestone_recent_actions.jsonl.gz` | 132,425 条逐动作（有标签对局） | 局级特征 + 动作偏好表 |
| `data/real_library/library_firestone_recent.jsonl` | 500 局（**427 局有 archetype 标签**） | 流派标签 / 英雄 / 大厅种族 |
| `rust/crates/hsbg-engine/data/cards.json` | 3,983 张卡 | 卡 id → 种族 / 是否随从 |

标签分布（427 局，27 种流派）：`beast_lobster 64 / neutral_tea_set 40 / dragon_shield 31 /
quilboar_gem_spam 31 / demon_boost_shop 26 / mech_apm 25 / mech_volumizer 23 /
elemental_azerite 20 / pirate_discover 19 / aberration_discard 17 / undead_butcher 17 …`
长尾 11 类各 ≤ 7 局。**头部 17 类**（`--min-games 8`）+ `other` 共 18 类；种族族 11 类。

### 2.2 特征（132 维，**全部线上可得**）

特征由 `hsbg/az/train/archetype_bias.py` 的 `ArchetypeHistory` + `build_vector` 生成，
**训练脚本与线上推理共用同一份代码**（`scripts/build_archetype_table.py` 也在用它），
不存在「两套特征实现各写一遍」的漂移风险。

| 块 | 宽度 | 内容 | 线上来源 |
|---|---:|---|---|
| `n_actions` | 1 | `log1p(己方人类口径动作数)` | 己方决策历史 |
| `turn` / `tempo` | 2 | 当前 turn、每回合动作数 | `global.turn` + 历史 |
| `type_share` | 11 | 动作类型占比（买随从/买法术/打随从/打法术/卖/刷新/冻结/升级/技能/黑暗赠礼/结束回合） | 己方历史 |
| `rhythm` | 36 | 6 类节奏动作 × 6 个 turn 桶的**每回合次数** | 己方历史 |
| `flow_tribe` | 11 | 买/打进来的种族占比 | 己方历史 + 酒馆/手牌种族位 |
| `flow_recent` | 11 | 最近买/打的种族占比（0.8/turn 指数衰减） | 同上 |
| `board_tribe` | 11 | 己方战团种族占比 | `board` 块 |
| `shop_tribe` | 11 | 当前酒馆随从种族占比 | `shop` 块 |
| `tier_curve` | 6 | 每个 turn 桶内达到的最高 tier | `global.tier` |
| `tier_now` / `max_tier` | 2 | 当前 / 历史最高 tier | 同上 |
| `gold_mean` / `gold_now` | 2 | 平均 / 当前金币 | `global.gold` |
| `lobby` | 11 | 本局可用种族（公共信息，开局即知） | `global[42:53]` |
| `hero` | 17 | 英雄 one-hot（16 词表 + other）。**默认全 0**（见消融） | `cards[0]` |

`Move/Cancel/Choose/Activate` 这些 AutoTavern 机械动作**不计入**（人类日志里没有对应行，
计进去会让训练/推理两侧口径不一致）；`Magnetize` 归到 `play_minion`。
训练侧对每个对局在**每个 turn 起点**取一个前缀样本（该回合之前的己方动作 + 当回合可见
观测），共 **5,851** 个样本 / 427 局（平均 13.7 个/局）。交叉验证**按 game_id 分组**，
同一局的前缀样本绝不跨折。

### 2.3 指标（5 折分组 CV，`data/archetype/archetype_metrics.json`）

| 任务 | 类别 | 样本 | top-1 | top-3 | macro-F1 | 多数类基线 |
|---|---:|---:|---:|---:|---:|---:|
| 段 1：种族族 | 11 | 5,851 | **64.5%** | **83.3%** | 0.620 | 16.3% |
| 段 2：头部流派 + other | 18 | 5,851 | **45.3%** | **73.5%** | 0.382 | 14.8% |

温度校准后的可靠性（ECE）分别为 0.018 / 0.015（校准温度 0.90 / 0.95）。

**为什么不是探针的 85.7/97.2、66.4/91.5？** `scripts/archetype_probe.py` 用的是**整局
结束后的全量特征**（整局买牌直方图、tier 里程碑），只能在赛后算，**线上不可用**；这里
必须在「第 t 回合开始时」就给判断，信息量差一个量级。两者不是同一任务：

| 口径 | 种族族 top1/top3 | 头部流派 top1/top3 | 可否线上使用 |
|---|---|---|---|
| 探针（整局全量特征） | 85.7 / 97.2 | 66.4 / 91.5（16 类） | ✗ 赛后 |
| 本文（turn 起点前缀，线上同口径） | 64.5 / 83.3 | 45.3 / 73.5（18 类） | ✓ |

前缀口径的**实际工作点**（`--archetype-min-prob 0.6` 门控，按 turn 桶）：

| turn | 流派段 coverage | 流派段 precision | 种族段 coverage | 种族段 precision |
|---|---:|---:|---:|---:|
| 1–4 | 19.3% | 50.5% | 40.5% | 55.1% |
| 5–6 | 18.9% | 78.3% | 47.0% | 81.8% |
| 7–8 | 23.3% | 78.9% | 54.0% | 90.2% |
| 9–10 | 31.7% | 82.2% | 64.2% | 95.3% |
| 11–12 | 37.9% | 80.6% | 71.3% | 97.7% |
| 13–15 | 41.7% | 84.1% | 74.4% | 97.6% |

即：**前 4 回合基本不该偏置**（precision ~50%，靠 0.6 门槛自然压住），**第 5 回合起
命中精度 78–84%**，第 9 回合起种族族判断 95%+。这决定了 §8 的启用建议。

### 2.4 分类器消融（都做在 CV 上，可复现）

| 变体 | 流派 top1 | 说明 |
|---|---:|---|
| 默认（无英雄、`class_weight=0`、l2=0.03、800 epoch） | **45.3%** | 本文采用 |
| 英雄 one-hot K=8 / 16 / 64 | 38.8% / 36.7% / 36.7% | **过拟合**：153 个英雄 / 427 局，单英雄样本 ~2.8 局 |
| `class_weight=1`（类别平衡） | 40.8% | 稀有类概率被抬高，gate 精度掉 20pp+ |
| l2=1e-2 | 38.8% | 欠正则 |

结论：**不要用英雄 one-hot**（线上也确实用不到它来判定「该怎么打」），类别权重关掉，
让概率直接对准 top-1 精度 —— 这才是门控需要的量。

## 3. 动作偏好表（`data/archetype/archetype_table.json`）

对 `流派 / 种族族 / 全局基线` 三个层级，按 6 个 turn 桶（+ `all`）统计：

```json
"mech_apm": {
  "support": 25, "tribe_family": "mech", "head": true,
  "pref": {
    "7-8": {
      "n": 783, "turns": 50,
      "per_turn": {"upgrade": 0.603, "reroll": 1.66, "hero_power": 0.348, ...},
      "rates":    {"buy_minion": 0.084, "play_minion": 0.309, ...},
      "buy_tribe": {"MECHANICAL": 0.417, "PIRATE": 0.221, "UNDEAD": 0.082, ...},
      "board_tribe": {"MECHANICAL": 0.462, "PIRATE": 0.227, ...},
      "top_cards": {"BG34_170": 0.076, "BG26_147": 0.061, ...}
    }, ... , "all": {...}
  }
}
```

- `per_turn` 是**每回合**频率（`--` 每次决策的 `rates` 也保留，仅用于分析）：
  「何时升 tier / 何时 reroll」用逐决策口径会被「一回合 40 个动作」稀释 10 倍以上，
  实测相对增益从 ~3% 抬到 ~25%，才有可用的信号；
- 小样本平滑：`rate = (k + α·baseline)/(n + α)`，`α=8`（逐回合）/`α=5`（种族分布）；
- `top_cards` 只留 share `>= 1%` 的前 10 张；
- **归一化**：`buy_tribe`/`board_tribe` 在**有样本的桶内和恒为 1**；完全没有样本的桶
  返回 `{}`（宁可不给偏好也不编造）→ 偏置项自然为 0。单测覆盖（`test_archetype_table.py`）。

## 4. 偏置规则（`hsbg/az/train/archetype_bias.py`）

检测（每决策一次，纯 numpy，~10 µs 量级）：

1. `x = build_vector(己方历史, 当前观测)`；
2. 两段式：`p_arch = softmax(段2)`、`p_tribe = softmax(段1)`；
3. 若 `argmax(p_arch) != "other"` 且 `max(p_arch) >= min_prob` → **流派级**偏好表；
4. 否则若 `max(p_tribe) >= min_prob` → 退回**种族族级**偏好表（粗粒度、覆盖全）；
5. 都不满足 → 不偏置（`archetype_level_none`）。

打分（全部 `>= 0`，当前 turn 的桶）：

| 分项 | 公式 | 作用动作 |
|---|---|---|
| 升级节奏 | `clip((per_turn_arch[upgrade]-per_turn_base[upgrade])/max(base,1e-3), 0, 2.0)` | `Upgrade`(3) |
| 刷新节奏 | 同上（`reroll`） | `Refresh`(1) |
| 技能节奏 | 同上（`hero_power`） | `HeroPower`(4,5) |
| 买牌种族 | `clip((buy_tribe_arch[t]-buy_tribe_base[t])/0.12, 0, 1.0)` | 酒馆随从位 `Buy`(8..15) |
| 买牌单卡 | `min(1, share/0.05)`，只对 `share>=1%` 的 `top_cards` | 同上 |
| 打出种族 | 同「买牌种族」× 0.5 | 手牌随从的 `Play`(46..125) |

合成：`bias = clip(coef · Σ分项, 0, coef·2.0)`，再 `bias[非法位] = 0`。所以
`coef=0.5` 时单动作最多 +1.0 logit，`coef=1.5` 最多 +3.0 —— 都在「引导」而非「决定」的量级。

温度口径：worker 侧在 masked softmax **之前**把 bias 加到 logits 上（`/τ` 之后再 softmax），
主进程 `_net_predict` 路径同样 `logits + bias`，两条路径数学等价（`betas` 单测覆盖
fast 路径传参 + slow 路径相加）。

统计写进 collect meta：`archetype_detected`、`archetype_name`（命中最多的类）、
`archetype_names`（逐类计数）、`bias_applied`（= `archetype_bias_applied` 的短名）、
`archetype_bias_applied`、`archetype_decisions`、
`archetype_level_{archetype,tribe,none}`、`archetype_mean_prob`、`archetype_bias_actions`、
`archetype_bias_sum`、`archetype_bias_coef/min_prob/table`。默认关闭时**一个键都不加**。

## 5. 泄漏边界（硬约束）

识别与偏置**只用**：

1. `Game.observe(seat)` 里的本座位可见信息（turn/tier/gold/lobby 种族位、己方战团/手牌/
   酒馆的种族位、英雄与酒馆卡的下标）；
2. 己方**历史动作**（采集时只有 learner 的决策经过 policy）；
3. 离线统计出来的流派→动作偏好表（不含任何本局对手私有信息、不含结局）。

**没有**用到：对手手牌/战团/隐藏 counter、本局 seed 的终局名次、评测面板、人类库的
`placement`、训练集里的对局结果。实现上 `parse_obs` 只接受 `(features, cards)` 两个数组，
拿不到 `game` 对象 → 结构上就堵住了「顺手读引擎内部状态」的路。

已知的**分布偏移**（不是泄漏，但要如实写）：分类器在**人类轨迹**上训练，线上跑在
**learner 自己的轨迹**上。learner 的打法分布与人类不同，所以线上命中率低于 CV 覆盖率
（§7 实测：检出率 24–25%、真正加 bias 的只有 14–15%，而 CV 覆盖率 27%）。这也是为什么 `--archetype-min-prob 0.6` 的门控必须保留。

## 6. 接线与 CLI

| 位置 | 改动 |
|---|---|
| `hsbg/az/train/archetype_bias.py` | 新模块：特征/两段式/偏好表/偏置/统计/汇总 |
| `hsbg/az/train/ppo.py` | `CollectConfig.archetype_bias_coef/min_prob/table/model`；`PPOSelfPlayPolicy._abias`；`decide`/`decide_batch` 计算 bias（fast 路径作为 kwargs 传 worker，slow 路径加在 logits 上）；`_finish` 记己方动作；`archetype_bias_meta()`；`collect_ppo_batch` 写 meta |
| `hsbg/az/train/batch_eval.py` | `LeafRequest.bias`；`submit/act/act_batch` 透传；worker 在 logits 上逐行加 bias（只加、不改 mask） |
| `hsbg/az/train/parallel_collect.py` | lockstep / 串行路径的 meta（`archetype_bias_meta`、`aggregate_archetype_bias`） |
| `hsbg/az/train/process_pool.py` | 多 worker 汇总 `aggregate_archetype_bias(metas)` |
| `scripts/train_entity_sync.py` | `--archetype-bias-coef`（默认 0）、`--archetype-min-prob`（0.6）、`--archetype-table`、`--archetype-model`；history header 自动记录 `vars(args)` |
| `scripts/build_archetype_table.py` | 构建 `archetype_model.npz` + `archetype_table.json` + `archetype_metrics.json` |
| `scripts/archetype_ab_summary.py` | A/B 汇总（只读，出 JSON + markdown 表） |
| `tests/test_archetype_bias.py` / `tests/test_archetype_table.py` | 31 个单测（无引擎/无 torch 依赖；全部通过） |

构建制品：

```bash
python scripts/build_archetype_table.py        # ~25 s（4,000 张卡的种族表 + 5,851 前缀样本）
# -> data/archetype/{archetype_model.npz, archetype_table.json, archetype_metrics.json}
```

## 7. A/B（同超参，cuda:7，从 `runs/az_entity_s13/model.pt` 起，各 40 iters）

三臂只差偏置系数（seed / 数据 / 引擎 / 人类战团注入完全相同）：

| 臂 | 参数 | 说明 |
|---|---|---|
| A | `--archetype-bias-coef 0` | 现状（关闭） |
| B | `--archetype-bias-coef 0.5 --archetype-min-prob 0.6` | 弱引导 |
| C | `--archetype-bias-coef 1.5 --archetype-min-prob 0.6` | 强引导 |

训练配置 = s13 同款（`--games 192 --sims 0 --lr 1.2e-6 --clip 0.2 --target-kl 0.02
--entropy-coef 0.001 --pi-coef 0 --anchor-beta 0.1 --seq-coef 0.05 --bc-coef 0.004
--dpo-coef 0.02 --move-guard 1 --mirror-p 0.2 --human-board-p 0.9
--human-board-fidelity full --pipeline 1 --lockstep 1`），
只有 `--processes 8 --gpus 7 --device cuda:7 --iterations 40` 不同（单卡跑）。

### 7.1 训练侧（同超参，各 40 iters ≈ 1.1M decisions）

| 指标 | A（coef=0） | B（coef=0.5） | C（coef=1.5） |
|---|---:|---:|---:|
| learner decisions | 1,094,865 | 1,116,716 | 1,104,286 |
| 训练秒（含 actor，单卡 cuda:7） | 397 | 410 | 439 |
| 检测命中数（`archetype_detected`） | — | 269,803 | 278,478 |
| 命中率（检出/决策） | — | **24.2%** | **25.2%** |
| 实际加 bias 的决策数 | — | 164,267 | 169,692 |
| 偏置应用率（应用/决策） | — | **14.7%** | **15.4%** |
| 其中流派级 / 种族族级（占全部决策） | — | 22,548 / 247,255（2.0% / 22.1%） | 23,580 / 254,898（2.1% / 23.1%） |
| 命中类平均概率 | — | 0.733 | 0.737 |
| 命中最多的流派 | — | murloc 85.9k、dragon 74.9k、mech 63.7k | murloc 80.6k、mech 78.1k、dragon 71.1k |

- **流派级只占 2%**：learner 自己的轨迹（还没学会人类那种「专精一个流派」的打法）在
  「头部流派」分类器上几乎都落在 `other`，绝大多数命中来自**种族族级回退**。这说明
  段 2 的上线价值取决于「learner 是否已经打得像人」，也解释了为什么 §10 要求先补数据。
- coef=0 臂的 collect meta 里**没有任何 `archetype_*` 键**（默认关闭 = 零键、零开销）。

### 7.2 三个固定量具（A/B 完全相同口径；评测时**关闭**偏置）

| 指标 | A（coef=0） | B（coef=0.5） | C（coef=1.5） |
|---|---:|---:|---:|
| **人类战团面板 144 局**（配对 bot 基线） | | | |
| model mean_rank（越低越好） | 6.257 | **6.194** | 6.347 |
| Δ mean_rank（model−bot） | −1.451 | **−1.514** | −1.361 |
| 95% CI | [−1.667, −1.222] | [−1.729, −1.291] | [−1.576, −1.153] |
| model top4 | 10.4% | **11.1%** | 6.2% |
| model win | 0% | 0% | 0% |
| **C0 gate 128 局 vs 引擎 bot** | | | |
| model mean_rank | 1.953 | **1.852** | 1.977 |
| Δ mean_rank（model−bot） | −2.492 | **−2.594** | −2.469 |
| model top4 / win | 96.1% / 40.6% | **98.4%** / 40.6% | 96.1% / 39.1% |
| **质量监控 64 局** | | | |
| mean_rank | 1.812 | 1.984 | **1.734** |
| top4 / win | 96.9% / 46.9% | 93.8% / 46.9% | **98.4%** / 46.9% |
| strength_ratio_t12 / t15 | 0.143 / 0.031 | 0.142 / 0.035 | **0.161 / 0.037** |
| tier≥5 占比 t12 / t15 | 6.2% / 25.0% | 12.9% / 23.3% | **17.2% / 44.2%** |
| moves/turn 均值 / p90 | 4.54 / 25.7 | 5.18 / 31.0 | **6.12 / 34.0** |
| 净盘面不变回合比 | 23.0% | 22.9% | 24.4% |

**统计口径说明**：三臂评测的 seed/面板完全相同（配对），但每个面板只有 144/128/64 局，
mean_rank 的单臂标准误约 0.19（144 局）→ 两臂均值差的 SE ≳ 0.27，本表里 A/B/C 的
mean_rank 差（≤0.15）**远未达到显著**。三个量具都只能说明「**没有观测到退化**」，
不能说明「变强了」。

### 7.3 机制验证（偏置到底改了什么？）

同一 checkpoint（C 臂）、同 seed、同一批对局做两次确定性探针：

**(a) 动作类型/节奏（8 局 vs bot，每局开/关偏置）**

| coef | upgrade 次数 | reroll 次数 | 买随从次数 | 买随从种族 Top2 |
|---|---:|---:|---:|---|
| 0 | 24 | 252 | 101 | MECH 46.5% / PIRATE 14.9% |
| 0.5 | 26 | 231 | 104 | MECH 47.1% / PIRATE 14.4% |
| 1.5 | 25 | 259 | 113 | MECH 38.9% / **ELEMENTAL 15.0%** |

**(b) 概率质量迁移（确定性，不采样）**：对每个「实际加了 bias」的决策，比较
`softmax(logp)` 与 `softmax(logp+bias)`：

| coef | 偏置动作上的质量增量 | 全分布 TV 距离 | **greedy argmax 翻转率** | 翻转落在偏置动作上 |
|---|---:|---:|---:|---:|
| 0.5 | +0.41pp | 0.0042 | **6.1%** | 100% |
| 1.5 | +3.46pp | 0.0351 | **12.7%** | 100% |

结论：偏置是**温和但正确方向**的引导（coef=0.5 只在 6% 的被偏置决策上改变 greedy 选择），
这与 40 iters / 1.1M 决策下「评测差异不显著」完全一致；同时也说明 coef=1.5 已经足以
在训练中把策略推向另一种范式（tier 进度明显更快、动作数更多），只是**迁移到人类面板
需要更长的训练**才能验证。

### 7.4 结论

1. **不退化**：三臂在人类面板 / C0 gate / 质量监控上都在噪声内；B（0.5）在两个
   「对手强度」量具上都略好（human top4 10.4→11.1%、c0_gate 1.95→1.85），C（1.5）在
   质量监控的时间线（tier/强度）上最好但人类面板 top4 掉到 6.2%（−4pp ≈ 1.6σ）。
2. **机制有效**：命中率 24–25%、应用率 15% 左右；概率质量按设计只往偏好动作上搬，
   greedy 翻转率 6%（coef 0.5）/13%（coef 1.5）。
3. **建议**：默认**继续关闭**；需要「按流派人类范式打」的软引导时用
   **`--archetype-bias-coef 0.5 --archetype-min-prob 0.6`**（保守、与其他 shaping 项
   正交、可随时关掉）；**不建议**现在就用 1.5 做主线（top4 有掉的风险，需 ≥300 iters
   的 A/B 才能判）。若要「只在中后期生效、避免早期误偏置」，实践上等价于用
   `--archetype-min-prob 0.7`（turn≥7 的 gate 精度 79–84%，覆盖率降到 ~20%）。

## 8. 结论与建议（TL;DR）

- 分类器指标（线上同口径前缀特征）：种族族 **top1 64.5% / top3 83.3%**，头部流派+other
  **top1 45.3% / top3 73.5%**；门控 `min_prob=0.6` 下 turn 5–8 精度 **78–90%**、
  turn 9+ 精度 82–98%（探针的 85.7/97.2 与 66.4/91.5 是**赛后全量特征**，不可线上使用）。
- 软偏置按设计工作：命中率 24–25%、应用率 15%、只加不减、不屏蔽、coef=0 逐位等价。
- A/B（各 40 iters ≈ 1.1M decisions）：**三项量具均无显著差异**，B 略正、C 的范式迁移
  最明显但人类面板 top4 有 −4pp 的（不显著）风险。
- **推荐**：默认关闭；要用就 `--archetype-bias-coef 0.5 --archetype-min-prob 0.6`。
  需要更「硬」的引导前，先满足 §10 的 5 条判据。

## 9. 复现

```bash
# 1) 分类器 + 偏好表
python scripts/build_archetype_table.py

# 2) 单测
python -m pytest tests/test_archetype_bias.py tests/test_archetype_table.py -q

# 3) 训练（最小闭环，1 iter）
python scripts/train_entity_sync.py --checkpoint runs/az_entity_s13/model.pt \
  --arch entity --device cuda:7 --processes 2 --gpus 7 --games 8 --sims 0 \
  --lockstep 1 --fast-act 1 --iterations 1 --gpu-free-check 0 \
  --archetype-bias-coef 0.5 --out /tmp/archetype_smoke

# 4) A/B 汇总
python scripts/archetype_ab_summary.py --arms A,B,C \
  --out runs/az_arch_ab/summary.json
```

## 10. 后续：什么时候可以上硬护栏

软偏置的下一步才是「硬」（把偏好动作之外的概率压到 0 / 强制 EndTurn 时机），上线门槛
必须**同时**满足下面几条，缺一不可：

1. **检测精度**：≥ 8 万局人类对局（现在 427 局标签订单太薄），把段 2 的
   gate precision 在 turn 5–8 从 ~79% 提到 **≥ 92%**，且 top1 ≥ 65%；
2. **分布对齐**：在「learner 自己的轨迹」上做一次闭环验证（用 A/B 产出的 checkpoint
   回放，检查检测器的命中分布与人类面板一致），消除 §5 说的轨迹分布偏移；
3. **软偏置先证明不亏**：连续 ≥ 3 个 A/B 里，B/C 臂的 human/bot/quality 三项**没有**
   ≥ 2σ 的退化（本目录的 A/B 是第 1 次，见 §7）；同时 `bias_applied` 要能被
   `--archetype-min-prob` 稳定控制在 10–30%；
4. **回滚开关**：硬护栏必须能按「流派级/种族级/动作类别」三种粒度单独关掉，且默认关；
   要有「护栏触发率」与「护栏导致 forced=True」的独立计数（照 `MoveGuard` 的口径），
   并且 PPO 损失要能把被护栏强制的样本排除（否则会伪造 on-policy ratio）；
5. **最坏情况兜底**：护栏生效时若清空后只剩 EndTurn，必须回退原 mask（同 `MoveGuard`
   的 `forced` 语义），且不允许改变可行动作集合为空的状态。
