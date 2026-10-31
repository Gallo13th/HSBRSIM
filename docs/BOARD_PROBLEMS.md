# BOARD_PROBLEMS — 场面题（自对弈关键局面 + 人类参考解 + 强度辅助头）

> 方向 A 的开发与 A/B 报告（[RESEARCH_PLAN_V2](RESEARCH_PLAN_V2.md) §4.1）。
> 状态：**开关默认关闭**，已实现 + 单测 + 40–60 iter 四臂 A/B；结论见 §10。
> 日期：2026-10-31。代码：`hsbg/az/train/board_problems.py`、
> `scripts/build_board_problems.py`、`scripts/board_ab_summary.py`。

## 0. 一句话

**不把人类轨迹直接当 BC 的输入**（那是 [BC_PRETRAIN](BC_PRETRAIN.md) §9.4 全败的根因：
人类回放状态分布 ≠ 自对弈状态分布）；而是**在自对弈轨迹自己的关键局面上出题**，
人类数据只提供「同一决策阶段人类会怎么做」的**参考分布**，配一个从状态预测
**t+3 战团强度**的辅助头。三个开关全部默认关闭、`coef=0` 逐位等价。

## 1. 为什么这样做（失败机理与对策）

| 事实 | 对策 |
|---|---|
| BC 预训练 8 组门禁全败；Move 概率压得住但强度回不来（[BC_PRETRAIN](BC_PRETRAIN.md) §9.3–§9.4） | **不在人类轨迹上做 CE**：题目状态来自当前策略的 rollout（on-policy 状态），人类数据只做「动作分布参考」 |
| 人类数据没有 gold/shop/池差量，硬 label 会引入不可见信息 | 参考解是**分布**不是 label：按 `(酒馆有牌?, turn, tier, gold)` 匹配，且只保留**当前局面合法掩码内**的动作；无支撑时逐级退化并记录 |
| 单靠 CE 可能重复 BC 的强度崩塌 | 同时监督**结果**：强度辅助头预测 t+3 战团总身材（log1p）与 tier+1，提供与动作选择正交的信号 |
| Move 连按（[MOVE_GUARD](MOVE_GUARD.md)） | 出题 rollout 与参考解候选**都**过 `move_guard`；`reposition` 默认不进参考解 |

## 2. 题目构造（`scripts/build_board_problems.py`）

### 2.1 关键局面（在自对弈轨迹上出题）

用 **A/B 的冻结起点权重**（`runs/ab_board/start_model.pt` = s14 step_1601）按**训练分布** rollout（人类战团 5 席 × p0.9 + `fidelity=full`、
镜像快照 2 席 × p0.2 × p75、`--move-guard 1`、温度 1.0），记录两类关键局面：

| 标签 | 判据 | 动机 |
|---|---|---|
| `turn_start` | 本回合 learner 的第一个决策 | 经济/升本/购买的起点，t9–t12 强度缺口的源头 |
| `upgrade_ready` | 引擎判定当前可升本（`mask[3]` 合法，已含金币约束） | 「该升不升」（[DPO_UPGRADE](DPO_UPGRADE.md)）是已证实的缺口 |
| `triple_ready` | 手牌+棋盘里某张牌已 ≥2 张且酒馆能买到最后一张 | 三连是中期强度的主要跃迁 |
| `core_card` | 棋盘上有 `tier >= 3`（`--core-min-tier`）的核心随从 | 阵地/核心随从的取舍 |

采样策略：`turn_start` 必留；其余分叉点每回合最多 `--max-fork-per-turn 2` 个（按出现顺序）；
`turn 0`（选英雄）与「只剩 choose/activate/magnetize/move 合法」的决策点**不出题**
（参考解 9 类动作覆盖不到，出了也是噪声）。

### 2.2 每道题存什么（`problems.jsonl`，一行一题）

```jsonc
{
  "problem_id": "bp-000123", "schema": "board_problem_v1",
  "source_group": "rollout:seed=20200:game=7",   // 整局为源组，禁止逐帧泄漏切分
  "game_seed": 20207, "turn": 9, "seat": 0, "decision_idx": 2,
  "tags": ["upgrade_ready", "core_card"],
  "obs": {"dtype": "f32", "features_b64": "...", "cards": [...],   // 3227 floats + 124
          "legal": [0, 1, 3, 8, ...], "sha256": "..."},             // 合法动作下标
  "state": {"gold": 8, "tier": 3, "strength": 412, "board_len": 5, "hand_len": 3, "shop_len": 5},
  "policy_action": 3, "policy_prob": 0.41,          // 出题时策略实际选的动作
  "ref": {"actions": [3, 9, 16], "weights": [0.55, 0.30, 0.15],
          "matched": true, "level": "turn_tier_gold", "floor": 10000,
          "support": 96, "mass_legal": 0.62},        // 人类参考动作 top-k（软标签）
  "label": {"strength_before": 412, "strength_after_t3": 1290, "delta": 878,
            "delta_log1p": 1.06, "tier_before": 3, "tier_after": 4,
            "tier_up": 1, "survived": 1, "terminal": 0,
            "available": 1, "horizon": 3, "target_turn": 12},
  "move": {"last": -1, "n": 1, "counts": [[203, 1]]}   // 出题时刻的回合内换位历史
}
```

**观测为什么不用 `state_json`**：题目状态只需要「训练输入同口径」的
features(3227)+cards(124)+合法掩码(245)；`f32` 存储可逐位复现（`obs.sha256` 是复现断言），
体积约 17 KB/题（`--obs-dtype f16` 可减半）。`state_json` 会绑定引擎版本且大 10 倍以上，
单测里也没有额外收益。

### 2.3 结果标注（短程真实值，不是仿真奖励）

rollout **结束后**回填（`horizon=t+3`）：

- `strength_after_t3` = learner 在 `turn+3` 回合**开始时**的战团 `Σ(atk+hp)`（与
  `quality_monitor` 同口径）；`strength_before` = 出题时刻的值；
  `delta = after - before`，`delta_log1p = log1p(after) - log1p(before)`；
- `tier_up = [tier(t+3) >= tier(t)+1]`；
- `available=1` 恒成立（**缺失不伪造成 0**）：learner 在 t+3 前出局的题用**最后可见值**
  并标 `terminal=1, survived=0`，训练侧仍可用（它表达「这个局面最后没能长大」）。

## 3. 参考解来源与匹配（`ReferenceTable` / `match_reference_actions`）

**数据**：`data/firestone_bc/bc_samples.jsonl.gz`（308,944 条逐动作样本，MMR 字段可用）。
只用 9 类白名单动作（= BC 的 `sell/reroll/buy_minion/buy_spell/play_spell/play_minion/
upgrade/hero_power/end_turn`）；`reposition/triple/freeze/dark_gift/choose` 不进参考解。

**分层键**（每层都先按 `shop_phase` 切分）：

```text
level 顺序（越靠前越具体）：turn_tier_gold → turn_tier → tier → turn → all
MMR 阶梯（同一 level 内优先高分段）：10000 → 8000 → 6000
支撑不足（< --min-support 40）就退化到下一个组合；全都不足 → ref.matched=false
```

`shop_phase`（酒馆是否还有牌）是**必须**的维度：Firestone 的 `end_turn` 行大量出现在
酒馆刷空/进入战斗之后（`shop_cards=[]`，`gold` 字段也陈旧）。只用 `(turn,tier,gold)` 匹配时，
实测 **58% 的题 top-1 变成 EndTurn**；加上 `shop_phase` 后降到合理水平（见 §8）。

**映射到 245 个动作**（不是硬 label）：

1. 类型分布 `p(type) = Σ_card p(type,card)`；
2. 卡牌型动作（buy/play/sell）**同卡优先**落到对应槽位（用观测的 card id → 槽位），
   同卡质量之外的余量在该类型的所有合法槽位上均分（人类买了别的牌时不给错槽位硬标签）；
3. `play_*` 的落位在合法落位上均分；
4. 过合法掩码 + **Move 守卫**（`apply_move_guard`），剩下质量重新归一 → top-k（默认 8）。

## 4. 强度辅助头（`--strength-aux-coef`，默认 0）

entity 模型上的 `strength_head = Linear(d_model, 2)`：

| 输出 | 目标 | 损失 |
|---|---|---|
| `[0]` | `z = (Δ − mean) / std`，`Δ = log1p(strength_t3) − log1p(strength_t0)`（**增量**，t+3） | masked MSE |
| `[1]` | `tier_up ∈ {0,1}` | masked BCEWithLogits（`--strength-tier-pos-weight`） |

**为什么是增量而不是绝对强度**（两条实测，都是 `board_problem_probe` 量出来的）：

| 目标 | trunk global token 上的 5 折 CV MSE（z 化后 var=1） | 解读 |
|---|---:|---|
| 绝对 `log1p(strength_t3)` | **0.093**（R²≈0.91） | 几乎被「当前回合/当前场面」完全决定 ⇒ 辅助任务退化成恒等式，残差≈0 ⇒ `dL/dg≈0` |
| 增量 `Δ` | **0.313**（R²≈0.69） | 残差大 3 倍，是**动作能改变**的部分，也是 §4.1 定义的结果标注口径 |

绝对强度仍然保存（`label.strength_after_t3`），供报告与校准；头预测的是增量。

**三个工程决定（每个都对应一个实测坑）**：

1. **离线拟合而不是随机初始化**：s14 配方 `lr=1.2e-6`，一次 Adam 步最多动权重 ~1e-6，
   随机头在 200 步内不可能校准。全池实测（`board_problem_probe`，同架构随机头 seed 0）：
   **MSE 0.509 / pearson(Δ) 0.709**，而 CV 拟合后是 **MSE 0.174 / pearson(Δ) 0.911**
   —— 随机头误差是拟合头的 3 倍，它给 trunk 的梯度基本是噪声方向。
   `fit_strength_head()` 用 **CV 选 λ 的闭式 ridge** 拟合强度、L2-logistic 拟合 tier。
2. **默认冻结**：不冻结的线性头会继续拟合这 293 道题（d=384，弱正则时 in-sample MSE
   可到 **0.044**），残差 → 0 ⇒ `dL/dg → 0`，辅助损失对 trunk 同样没有信号。冻结后语义是
   「**让 trunk 的表示保持对 t+3 强度增量的可预测性**」，辅助梯度只进 trunk。
   CV 选 λ=1.0 的冻结头实测：in-sample MSE **0.174**、CV MSE **0.312**、tier_acc 1.000、
   pearson(Δ) 0.911。
3. **只在存活题上算 + 不伪造标签**：`aux_valid = available & survived`（305/321）。
   t+3 前出局的题用最后可见值，尺度不可比，**masked 掉而不是填 0**（§2.3 要求）。
   归一化参数 `strength_norm={mean 1.330, std 0.707, target: delta_log1p}` 只由存活题估。

**checkpoint 兼容**：旧 ckpt 没有 `strength_head.*` → `load_checkpoint` 不建头、
`forward` 逐位一致；`--strength-aux-coef>0` 时 `attach_strength_head()` 追加头（其余权重
逐位不变），`save_checkpoint` 写 `strength_head=true` + `strength_norm`；之后
`load_checkpoint` 自动重建。单测覆盖两个方向（`test_attach_strength_head_*`）。

## 5. 场面题监督（`--problem-bc-coef`，默认 0）

在题目状态上做 **soft-label 交叉熵**：`-Σ_k q_k log π_θ(a_k|s)`，`q` = 参考解 top-k
（行和 1），只在合法动作上取 log-prob；`policy_top1_in_ref` / `top1_acc` 作为诊断。

- 每个 iteration 抽 `--problem-batch 128` 道题，**与强度辅助头共用同一批 + 同一次
  `forward_problem`**（B/C/D 三臂的题目状态完全一致，只有系数不同）；
- `--problem-bc-every` / `--strength-aux-every` 各自按 iteration 周期门控（跳过步完全不前向）；
- 与 BC/DPO **正交**：BC 仍是回放分层 CE（`--bc-coef`），DPO 仍只处理 upgrade 子集；
  三者共享同一次 backward，但 RNG（`bc_rng` / `dpo_rng` / `problem_rng`）各自独立，
  所以 `coef=0` 时 PPO 的 permutation/采样序列逐位不变。

## 6. Move 安全（生成 + 监督两侧）

- **出题**：rollout 的 learner 由 `PPOSelfPlayPolicy` 的 `MoveGuard` 采样（cap=3、
  repeat=2、逆换位屏蔽）；题目里的 `move` 字段记录该时刻的回合内换位历史；
- **监督**：参考解候选过同一套 `apply_move_guard`（`--exclude-move` 默认直接把 Move 族
  排除在标准解之外，作为第二道保险）；
- 实测：321 道题里 `move.n` p50 = 0、max = 1（守卫生效，标准解不含连按换位）。

## 7. 接口与默认关闭（逐位等价）

| 开关 | 默认 | 行为 |
|---|---|---|
| `--problem-pool` | `data/board_problems/problems.jsonl` | 两个系数都为 0 时**不读**该文件 |
| `--problem-bc-coef` / `--problem-bc-every` | `0.0` / `1` | 0 = 不加载池、不采样、不前向、stats 无 `problem_*` 键 |
| `--strength-aux-coef` / `--strength-aux-every` | `0.0` / `1` | 0 = 不建头、不算 loss、checkpoint 与旧版逐位一致 |
| `--problem-batch` | 128 | 题目 CE 与强度头共用的批大小 |
| `--strength-tier-pos-weight` | 1.0 | tier+1 BCE 的正样本权重 |

`PPOConfig` 里同名字段默认也是 0；`train_ppo` / `ppo_losses` 在 `coef=0` 时**不导入**
`board_problems`、不产生新 stats 键、连 `config` 回显里的新键都去掉（与旧版结构一致）。
单测 `tests/test_strength_aux.py::test_coef_zero_bitwise_*` 断言 `total` 与权重逐位相同。

## 8. 题目统计（实测，`data/board_problems/problems.meta.json`）

构造命令（2026-10-31 13:13，cuda:7）：

```bash
PYTHONPATH=rust/python:. python scripts/build_board_problems.py \
  --checkpoint runs/ab_board/start_model.pt --device cuda:7 \
  --games 16 --seed 20200 --out data/board_problems/problems.jsonl
```

**必须用与 A/B 相同的冻结 ckpt 出题**：s14 的 `model.pt` 每 100 iter 被覆盖一次，
用「当时最新的 s14」出题会让题目状态与训练起点差出几百万决策（off-policy）。
`start_model.pt` 的 sha256 = `fc35c7e3d710487ccc9693b2a45452192fab6f4da6e7472bfcf520449d6a5f6f`
（`trainer_updates=1601`）。

| 指标 | 值 |
|---|---|
| 题目数 | **321**（2,563 个 learner 决策 / 16 局 / 16 s，`--seed 20200`） |
| 覆盖 turn | **t1–t13**（t9 32 题、t10 28、t11 24、t12 16、t13 6；t1 16 / t2 18 …） |
| 标签覆盖 | `turn_start` 146、`upgrade_ready` 276、`core_card` 220、`triple_ready` 15 |
| 参考解 | 匹配率 **100%**（321/321）、缺失 0；层级 `turn_tier_gold` 118 / `turn_tier` 68 / `tier` 135 |
| MMR 分段 | 10k+ **151（47%）**、8k+ 39、6k+ 131 |
| 参考解合法质量占比 | p50 **0.611**（人类动作质量里能落到本题合法动作上的比例） |
| 策略 top-1 命中参考解 | **19.3%**；`policy_action ∈ ref top-k` **59.2%**（正是要监督的地方） |
| 强度标签 | `available` 321（**无缺失**）；`survived` **305（95.0%）**，16 题 t+3 前出局 → `terminal=1` |
| 强度 p50 | 出题时 **97** → t+3 **267**（存活题）；`tier_up` 率 **52.6%** |
| 增量归一化 | `Δlog1p` 的 mean **1.231** / std **0.734**（随 ckpt 存为 `strength_norm`），p50 **1.197** |
| Move | `move.n` p50 0 / max 1（守卫生效） |
| 注入（同训练分布） | 人类战团 applied **625/1082 = 57.8%**（拒绝：`not_alive` 213 / `pending_choice` 171 / `not_recruit` 73）；镜像 applied 49/94 |
| 跳过 | `fork_cap` 1581（每回合上限）、`no_supervisable` 455（只剩 choose 等）、`min_turn` 16 |
| rollout 名次 | mean **4.94**（16 局；训练分布含 5 席人类战团，不是主面板口径） |

### 8.1 「状态分布对齐」的证据（本方案的关键验证）

1. **题目状态是 on-policy 的**：321 道题全部来自**同一冻结起点 ckpt** 的 rollout（同训练分布的注入），
   不是人类回放帧。因此不存在 BC 预训练的「训练/推理状态错配」。
2. **但状态仍与人类不同分布**：135/321（42%）的题只能退化到 `tier` 层匹配，因为我们的
   `(turn, tier)` 格子（例如 t9 还在 tier 2）在人类数据里几乎不存在。这条统计本身是
   「我们弱在哪」的直接证据：**t6 以后 tier 明显落后于人类**，与 [DPO_UPGRADE](DPO_UPGRADE.md)
   的 tier 缺口结论一致。
3. **人类参考解可用但不等同于最优**：`ref.mass_legal` p50 0.587 说明约 41% 的人类动作质量
   在本局面根本不可执行（手牌/酒馆结构不同）——这正是「只把它当参考分布、不当 label」的理由。
4. **策略与参考解差多远**：`policy_action ∈ ref top-k` 仅 **59.2%**、`policy == ref top-1`
   仅 **19.3%**（见 `problems.meta.json` 的 `policy_top1_in_ref`）；差距集中在「回合起点
   先买还是先升」。
5. **参考解 top-1 的结构性偏差（必须写明）**：321 题里 **167 题（52%）** 的参考 top-1 是
   `upgrade`、74 题（23%）是 `reroll`（回合起点题里 upgrade 占多数）。原因有二：① 我们的题大多处在**tier 落后**的状态
   （t6–t12 仍 tier 1–2），人类在同一 `(酒馆有牌, tier, gold)` 条件下的主动作确实是升本
   （与 [DPO_UPGRADE](DPO_UPGRADE.md) 的「该升不升」一致）；② 类型质量按槽位均分时，
   单动作类型（upgrade/reroll/end_turn）不会被稀释，所以相对权重偏高。这是**已知偏差**，
   也是「只给 0.05 小系数 + 同时看强度头，不做纯 CE」的理由。

## 9. A/B 设计（四臂、同起点、单因素）

- **起点**：`runs/ab_board/start_model.pt`（s14 `trainer_updates=1601` 的冻结快照，
  sha256 `fc35c7e3…a5f6f`）。**四臂必须同一份权重**：s14 每 100 iter 覆盖 `model.pt`，
  用「当时最新」的会引入 2–5M 决策的漂移（第一次尝试就踩了这个坑，已作废重跑）。
- **配方**：s14 逐字配方（`docs/PROJECT_MEMORY.md` §2.1），只改被检验的开关：
  `--seed 20100 --games 192 --processes 8 --gpus 7`、`lr 1.2e-6`、`anchor 0.1/200`、
  `bc 0.004`、`dpo 0.02`、`seq 0.05`、`move-guard 1`、5 席人类战团 p0.9、
  镜像 2 席 p0.2、`archetype 0.5`。
- **四臂**（各 40 iter ≈ 1.12M decisions）：

| 臂 | 新增开关 |
|---|---|
| A | 无（现状对照） |
| B | `--strength-aux-coef 0.05`（只强度辅助头） |
| C | `--problem-bc-coef 0.05`（只场面题 CE） |
| D | 两者都开 |

- **评测**（只 human + 质量面板，不跑 bot 晋级）：
  `human_panel_eval --games 256 --seats 8 --seed-base 420000 --quantile auto`
  （`--smoke` 开发面板，512 局正式面板留给 exam）；
  `quality_monitor --games 96 --seed-base 740000 --move-guard 1 --move-cap 3 --move-repeat-limit 2`。
  四臂同 seed ⇒ 逐局 rank 严格配对。
- **离线探针**（`scripts/board_problem_probe.py`）：在**完整题目池**上测 soft CE /
  top-1 / 参考 top-k 命中 / 强度头 MSE·相关（每步只抽 128 题，训练日志噪声太大）。
- **记账**：`collect_s` / `decisions_per_s` 与评测耗时分开（[RESEARCH_PLAN_V2](RESEARCH_PLAN_V2.md) §5.4）；
  本实验只报 collect，不把评测算进采集门。

## 10. A/B 结果与门禁

### 10.1 离线探针：辅助信号「学到没」（全池 321 题、无采样噪声）

`scripts/board_problem_probe.py`（`runs/ab_board/probe_ABCD.json`）：

| 臂 | 题目 soft CE | top-1 命中 | argmax ∈ ref top-k | 强度头 MSE | pearson(Δ) |
|---|---:|---:|---:|---:|---:|
| A（对照，40 iter） | 7.034 | 20.9% | 60.4% | — | — |
| start（未训练） | 7.025 | 20.3% | 58.6% | — | — |
| B（只强度头） | 7.023 | 20.6% | 59.5% | **0.130** | **0.934** |
| C（只题目 CE） | **5.867** | 21.8% | 61.4% | — | — |
| D（两者） | **5.884** | **22.1%** | **62.0%** | 0.145 | **0.936** |

读法：

1. **题目 CE 真的在学**：C/D 把全池 soft CE 从 7.03 降到 5.87（**−1.17 = −16.6%**），
   argmax 落在人类参考 top-k 内的比例 60.4% → 61.4/62.0%。方向正确、幅度不大——因为
   soft 标签主要在**重分配概率质量**，不是翻转 argmax。
2. **强度头对策略几乎无影响**：B 的 soft CE 与 A 只差 0.011（噪声级）。原因见 §4：
   强度/增量在 trunk 表示里**已经线性可解码**（CV-R² 0.69–0.91），冻结探针只能当
   「表示锚」，不能告诉策略「该做什么」。但它确实改变了表示：同一个冻结头在全池上的
   MSE 从 0.174 降到 0.130（pearson 0.911→0.934）。
3. 因此**唯一会改行为的是 `--problem-bc-coef`**；`--strength-aux-coef` 是表示层正则，
   40–60 iter 内不可能改变主指标。

### 10.2 四臂主结果（human 256 配对 + 质量 96；同 seed/seat）

`runs/ab_board/SUMMARY.json` / `SUMMARY.json.md`：

| 臂 | human mean | Δ vs A [95% CI] | top4 Δ | 强度比 t12 | 强度比 t15 | tier≥5@t12 | tier≥5@t15 | 出局强度 p50 | moves/turn | collect Δ |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A（对照） | 6.270 | — | — | 0.134 | 0.035 | 10.4% (10/96) | 42.4% (28/66) | 801 | 0.71 | — |
| B 强度头 | 6.289 | **+0.020** [−0.109,+0.145] | −1.95pp | 0.133 (−0.8%) | 0.035 (−0.3%) | 15.6% (15/96) | 46.9% (30/64) | 768 (−4.1%) | 0.69 | −1.8% |
| C 题目 CE | 6.309 | **+0.039** [−0.137,+0.211] | −1.56pp | 0.137 (+2.0%) | 0.037 (+6.4%) | **21.9% (21/96)** | **60.7% (37/61)** | 805 (+0.5%) | 0.71 | −0.4% |
| D 两者 | 6.320 | **+0.051** [−0.141,+0.231] | −1.56pp | 0.136 (+1.3%) | 0.032 (−10.0%) | 20.0% (19/95) | 49.2% (30/61) | 871 (+8.7%) | 0.69 | −30.0%\* |

\* D 的 collect 慢 30% 是**环境干扰**：同一时段外部任务把 GPU 0/1/2 打到 100%，
且 D 的 `ppo_s` 也同步 +36%（方法本身只多一次 128 行前向/iteration，B 的实测是 +5%、
C 是 −2%）。这一项记为 **inconclusive**，不作为 D 的失败依据（§11 的回退条件仍按其它门）。

**硬错**：四臂 human 面板全部 **0 illegal / 0 truncated / 0 truncated_combats**；
注入 `applied/attempt` ≈ 79–80%（拒绝全是 `pending_choice`），与 s14 同口径。

### 10.3 门禁判定（[RESEARCH_PLAN_V2](RESEARCH_PLAN_V2.md) §2.3）

| 门禁 | 阈值 | B | C | D |
|---|---|---|---|---|
| human Δ（配对 95% CI） | ≤−0.10 且 CI 上界 <+0.05 | ✗ (+0.020) | ✗ (+0.039) | ✗ (+0.051) |
| human top4 | ≥ 基线 −2pp | ✓ (−1.95pp) | ✓ (−1.56pp) | ✓ (−1.56pp) |
| 强度比 t12 | ≥ +10% | ✗ (−0.8%) | ✗ (+2.0%) | ✗ (+1.3%) |
| 强度比 t15 | ≥ +10% | ✗ (−0.3%) | ✗ (+6.4%) | ✗ (−10.0%) |
| tier≥5 @t12/t15 | 不低于基线 | ✓ | ✓ | ✓ |
| 出局强度 p50 | 不低于基线 | ✗ (−4.1%) | ✓ (+0.5%) | ✓ (+8.7%) |
| collect | < +15% | ✓ (−1.8%) | ✓ (−0.4%) | inconclusive |
| 硬错 | 0 | ✓ | ✓ | ✓ |
| **整臂结论** | 全过 | **FAIL** | **FAIL** | **FAIL** |

### 10.4 结论：哪个开关进 s15

**两个都不进。** 按 §2.3，四臂全部未过（human 无改善、t12/t15 强度比远未到 +10%），
因此 `--problem-bc-coef` 与 `--strength-aux-coef` **保持默认 0**，s15 配方不变。

但要区分「机制无效」与「预算不够」，证据是：

1. **题目 CE 确实在改行为**（§10.1）：全池 soft CE −16.6%，argmax∈ref top-k +1.0~1.6pp；
   并且 C 的 **tier≥5@t12 从 10.4% 升到 21.9%（+10/96 局）、@t15 42.4%→60.7%**——
   方向与参考解 top-1（52% 是 upgrade）一致，是「把 40–60 iter 的有限梯度花在升/买节奏上」
   的合理结果。但 n=96/61、单 seed，且没有同步的强度比提升，**不能当收益**。
2. **强度头不改变行为**：B 的 soft CE 与 A 差 0.011（噪声），human Δ +0.020（CI 含 0）。
   机制上也不该有：强度/增量在 trunk 里已经线性可解码（CV-R² 0.91/0.69）。
3. **预算分辨率不足**：40 iter = **1.12M decisions**（每 iter 28.1k），而 s14 自己的
   human 曲线在 10M decisions 尺度上就来回 ±0.07（10M 6.328 → 20M 6.246 → 50M 6.3125 →
   60M 6.332）。1.12M 的偏移量级 ≈0.01，**主面板在这套预算下没有分辨 −0.10 的功效**
   （256 局配对 CI 半宽 ≈0.17）。
4. **Move 安全无回归**：moves/turn 0.69–0.71（与 A 同），标准解不含连按换位。

**建议的下一步（未执行，需 Lead 批准与预注册）**：只把 C（`--problem-bc-coef 0.05`）
作为单因素跑到 **20–40M decisions**（同冻结起点/同配方，预注册 checkpoint 与面板），
用 §2.3 同一套门禁判定；`--strength-aux-coef` 只保留离线探针用途（它已经是很好的
「表示里有没有强度信息」的读数），不再进训练。

**为什么不是加大系数**：C 的 soft CE 已经降了 16.6%，说明信号被吃进去了；再加大系数只会
把「升/买节奏」推得更猛（tier 上升但强度比不动），这与 DPO 只抬 tier 不抬强度比的历史
一致（[DPO_UPGRADE](DPO_UPGRADE.md) §6.5）。



## 11. 回退方式

| 场景 | 操作 |
|---|---|
| 任一臂门禁未过 | 只把该臂的开关置 0（`--problem-bc-coef 0` / `--strength-aux-coef 0`），其余配方不动；旧 ckpt 无需转换 |
| 题目池数据问题 | `--problem-pool` 指向空/坏文件时训练入口自动 warn 并把两个系数置 0（不中断） |
| 强度头不收敛/校准差 | `strength_aux_coef=0` 后头不参与前向；或直接用 `runs/ab_board/start_model.pt` 这类无头 ckpt |
| 旧 ckpt 兼容 | 无头 ckpt 直接加载（`load_checkpoint` 自动不建头）；带头 ckpt 也能被旧代码忽略未知键？**不能** —— 带 `strength_head.*` 的 ckpt 需要本版本的 `load_checkpoint` |
| 重新出题 | 重跑 §8 的命令（同 seed 逐位可复现；`--seed`/`--games` 可换） |
