# BOARD_PROBLEMS — 场面题（自对弈关键局面 + 人类参考解 + 强度辅助头）

> 方向 A 的开发与 A/B 报告（[RESEARCH_PLAN_V2](RESEARCH_PLAN_V2.md) §4.1）。
> 状态：**开关默认关闭**，已实现 + 单测 + 40–60 iter 四臂 A/B；结论见 §10。
> **§12** = 两个「后期强度」开关（`--problem-turn-weight` /
> `--problem-min-strength-delta`）+ 题池后期覆盖 + 三臂 A/B（结论：都没过门禁，不进 s15/s16）。
> **§13** = 后期题池扩容（t14 380 / t15 136，672 局）+ 重放质量审计（52/52，偏差 0.0%）
> + B 臂预注册复测（t14 −7.1% / t15 −3.7% ⇒ 仍不进 s15；瓶颈换成后期参考解 reroll）。
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
| `--problem-turn-weight` | `""` | 按 turn 给 soft-CE 加权（`"10:2,12:3,14:4,15:4"`；空 = 不加权、`weight=None` 走原 `mean` 路径）；权重 0 = 剔除该 turn。见 §12 |
| `--problem-min-strength-delta` | `0.0` | 只留 `label.strength_delta >= 阈值` 的题（0 = 不过滤、不读该字段）；过滤计数进 history。见 §12 |

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

## 12. 后期强度开关（t12–t15）：`--problem-turn-weight` / `--problem-min-strength-delta`

> 状态：**两个开关都默认关闭、空权重 + 阈值 0 时与 §1–§11 的实现逐位等价**（下表和 sha
> 都来自 2026-10-31 的 s14 冻结起点）；A/B/C 三臂已完成，**按预注册门禁两个都没过，
> 因此不进 s15/s16 默认配方**（判定见 §12.9）。

### 12.1 动机（为什么加这两个开关）

`runs/plots/strength_stages.md`（阶段强度表）给出的事实：

| 阶段 | t10 | t12 | t13 | t14 | t15 |
|---|---:|---:|---:|---:|---:|
| 真实 10k+ p50 | 1,128 | 4,458 | 9,666 | 21,136 | **26,516** |
| s8 比值 | 0.344 | 0.151 | 0.092 | 0.041 | 0.038 |
| s14@70M 比值 | 0.301 | 0.127 | 0.069 | 0.035 | **0.031** |

s8→s14 **t12 之后几乎不动**（t12 0.13–0.15、t13 0.07–0.09、t15 0.03–0.04），
真实 t15 p50 = 26,516 而我们 ~821（**差 32 倍**）。而我们的题目池（§8）参考解 **52% 是
`upgrade`**，集中在 t6–t12 的升本——**没有一道题直接监督「后期把随从做大」**
（买高 tier 随从 / 三连 / buff / 经济滚雪球）。两个开关就是把有限的 soft-CE 梯度
**按回合和结果增量重新分配**，而不是加大系数（§10.4 已证明加大系数只抬 tier 不抬强度）。

### 12.2 开关 1：`--problem-turn-weight "10:2,12:3,14:4,15:4"`（默认空）

| 项 | 语义 |
|---|---|
| 语法 | `turn:weight` 逗号分隔；未列出的 turn 权重 **1.0** |
| 生效位置 | `problem_bc_soft_ce`：`loss = Σ_{i∈bc_valid} w_i·CE_i / Σ w_i`（只在有效行上加权，分母同步加权） |
| `weight = 0` | **该 turn 的题从池里剔除**（记入 `problem_pool_dropped_by_turn`），因此也支持「不要某些 turn」 |
| 解析健壮性 | 缺 `:`、turn 非整数/为负、weight 负/非有限/`nan`/`inf`、空项（`10:2,,12:3`）、重复且不一致 → **`ValueError` 报错退出**（`PPOConfig` 构造期 + CLI 启动期双重校验）；`10:2,10:2.0` 允许（等价去重） |
| 默认逐位等价 | 空串 -> `pool.turn_weight is None` -> `problem_obs_batch` 的 `weight=None` -> 走**原来的** `ce[valid].mean()`（不是「全 1 加权」，避免浮点顺序差异） |

### 12.3 开关 2：`--problem-min-strength-delta <float>`（默认 0）

只保留 `label.strength_delta >= 阈值` 的题。`strength_delta` 就是 §2.3 的
**t+3 归一化强度增量** `log1p(after) - log1p(before)`（存活题 mean **1.231** / std **0.734**；
老池子只有 `label.delta_log1p` 时自动退化读它，**不混用**量纲差 3 个数量级的原始 `delta`）。
阈值 > 0 而题缺字段时**报错**（不静默保留/丢弃）；默认 0 时完全不读该字段。

两个开关的过滤结果都写进 **history**（`history.jsonl` 每行 `problems` 段 + `ppo` 段同源）：

```jsonc
"problems": {"problem_pool_size": 1581, "problem_pool_used": 1132,
             "problem_pool_dropped_by_delta": 449, "problem_pool_dropped_by_turn": 0,
             "problem_pool_min_strength_delta": 0.5,
             "problem_pool_turn_weights": {},
             "problem_pool_path": "data/board_problems/problems_s14_s15.jsonl"}
```

### 12.4 题目构造增强（`scripts/build_board_problems.py`）

| 新参数/字段 | 语义 |
|---|---|
| `--focus-turns "10-15"`（或 `"10-15,8"`） | 只在指定 turn 段出题；区间合并、越界/逆序报错；`skipped.focus_turn` 计数 |
| `--min-delta <float>` | **出题时**就用 rollout 的强度增量过滤（`label.strength_delta`），`skipped.min_delta` 计数 |
| 每题 `strength_delta` | t+3 归一化增量（= `label.delta_log1p`，同时写进 `label.strength_delta`） |
| 每题 `turn` / `is_late_turn` | `is_late_turn = turn >= LATE_TURN_MIN=10`（§12.1 的「后期」口径，与阶段强度表对齐） |
| `problems.meta.json` | 新增 `late_turn_problems` / `late_turn_by_turn` / `strength_delta_{p50,p90,mean}` / `late_turn_min` |

### 12.5 题池变化（实测，2026-10-31 17:0x，cuda:7）

**先看一个关键事实：s14 训练分布出不出后期题。** 用 §9 的 s14 分布（人类战团 5 席 × p0.9 +
镜像 2 席 × p0.2）出 64 局（seed 20200），题池 **1,163 题、turn 只到 t13，t14/t15 = 0 题**；
64/64 局的 learner 都在 t13 前出局（`per_game.turns` 到 t18，但那是别的座位还在打）。
**所以「turn 权重的 14/15 项」在 s14 分布池上必然空转**——想监督 t14/t15，先要有 t14/t15 的题，
而这需要**更弱对手的分布**（否则我们的 learner 根本活不到那里，这本身就是强度缺口的证据）。

因此本次重建了三份池子：

| 池 | 构造 | 题数 | turn 覆盖 | `Δlog1p` mean/p50 | 存活 | t12/t13/t14/t15 |
|---|---|---:|---|---:|---:|---|
| `problems_s14_late.jsonl` | s14 分布 64 局，seed 20200 | 1,163 | t1–t13 | 1.187 / 1.134 | 95.4% | 26 / 8 / **0 / 0** |
| `problems_late_turns.jsonl` | **弱对手** 64 局（human p0.5×3 席、无镜像）+ `--focus-turns 10-15`，seed 30200 | 418 | t10–t15 | 0.499 / 0.415 | 56.5% | 92 / 60 / **22 / 12** |
| `problems_s14_s15.jsonl`（A/B/C 用） | 上面两份合并 | **1,581** | t1–t15 | 1.005 / 0.932 | 85.1% | 118 / 68 / 22 / 12 |

合并池上两个开关的实际作用：

| 臂 | 生效池 | 权重和 / 后期占比 | 去掉的题 |
|---|---:|---|---|
| A（原样） | 1,581 | 1,581 / t≥10 = 38.7% | 0 |
| B（turn 权重） | 1,581 | **2,147（+36%）** / t≥10 = **54.9%** | 0 |
| C（delta ≥ 0.5） | **1,132** | 1,132 / t≥10 = 20.2% | **449（28.4%）** |

**C 的副作用必须记下**：`--min-delta 0.5` 会**优先删掉后期题**（t12 118→23、t13 68→10、
t14 22→6、t15 12→4，t9 120→86），因为后期增量天然更小（后期题 Δ mean 0.499 vs 前期 1.187）。
「按结果增量留题」和「重点监督后期」在这一步是**互相冲突**的，这就是 §12.8 里 C 在
t12–t15 全面不动的原因之一。

### 12.6 单测（`tests/test_board_problem_switches.py`，**31 个**）

| 组 | 覆盖 |
|---|---|
| turn 权重解析 | 合法语法/字典/空白/权重 0/等价重复；**13 个非法输入**必须 `ValueError`（缺 `:`、非整数、负 turn、负/nan/inf weight、空项、尾随逗号、重复不一致、非字符串） |
| 加权生效 | 同一批题目上 `problem_bc_soft_ce` 的加权损失 **= 纯 numpy 手算值**（`ΣwCE/Σw`，行 2 `bc_valid=False` 不进分母、`weight_sum` 核对）；`weight=None` 时 = 原来的 `ce[valid].mean()`；无有效行返回 0 |
| delta 过滤 | 池子变小、保留题 `strength_delta` 全 ≥ 阈值、`dropped_by_delta` 计数正确；只有 `delta_log1p` 的老池子仍可过滤；缺字段 + 阈值>0 **报错**；负阈值报错 |
| turn 权重剔除 | `{"6": 0}` 的 turn 被剔除、其余权重 1、`turn_weight`/`problem_pool_dropped_by_turn` 正确；默认池 `turn_weight is None` → `batch.weight is None` |
| **默认逐位等价** | 同 seed **训练 2 iter**：空权重+delta=0 与「不传新开关」的权重 **sha256 完全相同**；同 seed 复跑 sha 仍相同；换成真加权 `10:2,12:3,14:4,15:4` 后 sha **必须变化**（否则开关空转） |
| 默认不写新键 | `coef=0` 时新开关不进 `stats`/`config` 回显（与旧版结构一致）；`coef>0` 时才出现 |
| `--focus-turns` | `focus_allows` 只看目标区间；真实 rollout（需引擎）里 focus 区间的题**全部落在区间内**、区间外题被裁掉、`skipped.focus_turn > 0`、区间内题与全量池的 `obs.sha256` 一致（只裁不重算） |
| 入口 | 两个脚本都暴露新参数；非法值/负阈值以**退出码 2** 报错 |

**改动前后逐位等价（跨版本）证据**：改动前（HEAD `c84fd48`）用同一脚本（`trainer.update`
×2、同 seed、固定 batch、`--problem-bc-coef 0.05`）跑出
`sha256 = 20f9188f…fdb04e`；改动后「不传新开关」与「显式空权重 + delta=0」**都是同一个 sha**
（`runs/ab_turnweight/bitwise_{baseline_head,default_after,default_after_explicit}.json`）。
全仓 `pytest tests`：**590 个测试、0 failed**。

### 12.7 A/B 设计（单因素三臂）

- **起点**：`runs/ab_turnweight/start_model.pt` = `runs/az_entity_s14/model.pt` 的冻结副本
  （`trainer_updates=3501`，sha256 `59bd5e08…cbe9`）。三臂**同一份权重**。
- **配方**：s14 逐字配方（192 局/iter、`lr 1.2e-6`、anchor 0.1/200、bc 0.004、dpo 0.02、
  seq 0.05、5 席人类战团 p0.9、镜像 2 席 p0.2、archetype 0.5、`--processes 8 --gpus 7`），
  三臂都带 `--problem-bc-coef 0.05`；各 40 iter（≈1.12M decisions）。
- **题池**：三臂都用 `data/board_problems/problems_s14_s15.jsonl`（1,581 题，t1–t15）——
  §12.5：s14 分布池没有 t14/t15，不重建就没有可测的东西。
- **臂**：A = 原样；B = A + `--problem-turn-weight "10:2,12:3,14:4,15:4"`；
  C = A + `--problem-min-strength-delta 0.5`。
- **评测**：`quality_monitor --games 96 --seed-base 740000`（主看 t12–t15 强度比）、
  `human_panel_eval --games 256 --seats 8 --seed-base 420000 --smoke`（同 seed 逐局配对）。
- **产物**：`runs/ab_turnweight/{run_ab.sh,eval_ab.sh,armA|armB|armC,SUMMARY.json,
  strength_by_turn.py}`。

### 12.8 结果（2026-10-31，40 iter/臂，同一冻结起点）

**质量面板（96 局，seed 740000）逐 turn 强度比 = ours_p50 / real_p50**：

| turn | 真实 p50 | A（对照） | B（turn 权重） | C（delta 过滤） |
|---|---:|---:|---:|---:|
| t9 | 546 | 0.4154 | 0.4227 (+1.8%) | 0.3962 (−4.6%) |
| t10 | 1,128 | 0.3270 | 0.3155 (−3.5%) | 0.3008 (−8.0%) |
| t11 | 2,203 | 0.2227 | 0.2281 (+2.4%) | 0.2215 (−0.5%) |
| t12 | 4,458 | 0.1463 | 0.1403 (**−4.1%**) | 0.1434 (−1.9%) |
| t13 | 9,666 | 0.0816 | 0.0777 (**−4.8%**) | 0.0803 (−1.6%) |
| t14 | 21,136 | 0.0426 | 0.0442 (**+3.7%**) | 0.0416 (−2.4%) |
| t15 | 26,516 | 0.0357 | 0.0392 (**+9.9%**) | 0.0353 (−0.9%) |

**主表**（human 256 配对 + 质量门）：

| 臂 | human mean | Δ vs A [95% CI] | top4 | 强度比 t12 | t13 | t14 | t15 | tier≥5@t12 | tier≥5@t15 | 出局强度 p50 | moves/turn | 硬错 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| A | 6.422 | — | 8.20% | 0.1463 | 0.0816 | 0.0426 | 0.0357 | 13.7% | 40.0% | 866 | 0.65 | 0 |
| B | **6.340** | **−0.082** [−0.223, +0.051] | **10.55%** (+2.34pp) | 0.1403 (−4.1%) | 0.0777 (−4.8%) | 0.0442 (+3.7%) | 0.0392 (+9.9%) | 8.3% (−39%) | 36.2% (−9.5%) | 866 (+0.1%) | 0.64 | 0 |
| C | **6.266** | **−0.156** [−0.293, −0.027] | 10.16% (+1.95pp) | 0.1434 (−1.9%) | 0.0803 (−1.6%) | 0.0416 (−2.4%) | 0.0353 (−0.9%) | 13.5% (−1%) | **43.6% (+9.1%)** | **761 (−12.1%)** | 0.72 | 0 |

- **软 CE 确实在学、方向按预期偏移**（40 iter 在 128 题/iter 上的均值）：`problem_bc_top1_acc`
  A 0.166 → B **0.171**（+0.5pp，把权重压到 t10/t12/t14/t15 后「argmax 命中人类参考」略升），
  C **0.140**（−2.6pp：留下的都是「高增量」难题，本身更难命中参考 top-1）。
  `pbc` 损失值三臂不可直接比（B 是加权均值、C 的池子小 28%）。
- **collect 吞吐这一列 CI 无效**：三臂的 collect 分别在 s14 的异步评测/A-B 评测并发时跑的
  （B −19%、C −24.8%），与 §10.2 的 D 臂同类**环境干扰**，不作为结论依据；三臂 `illegal=0、
  truncated=0`，Move 安全无回归（0.64–0.72 moves/turn）。
- **n 很小**：质量面板 t14/t15 只有 78–82 / 50–58 局，human 256 局配对 CI 半宽 ≈0.14；
  B 的 t15 +9.9% 与门禁的 +10% **在噪声内不可区分**。

### 12.9 门禁判定与结论

| 门禁（预注册） | 阈值 | B | C |
|---|---|---|---|
| t14/t15 强度比 vs A | ≥ **+10%** | ✗ (+3.7% / **+9.9%**) | ✗ (−2.4% / −0.9%) |
| human 不劣化 | Δ ≤ +0.05 | ✓ (−0.082) | ✓ (−0.156) |
| 出局强度 p50 | 不低于 A | ✓ (+0.1%) | ✗ (−12.1%) |
| tier≥5 @t12 | 不低于 A | ✗ (−39%) | ✓ (−1%) |
| 硬错 | 0 | ✓ | ✓ |
| **整臂结论** | 全过 | **FAIL**（未过 +10%） | **FAIL** |

**结论：两个开关都不进 s15/s16 默认配方**（保持空权重 / 0）。但结果不是「机制无效」，而是
**三个具体边界**：

1. **B 是唯一在 t14/t15 上正向的臂**（+3.7% / +9.9%），且 human 不劣化（−0.082，CI 含 0）、
   出局强度不降、`pbc_top1` +1.6pp。它离门禁只差 0.1pp，而 t15 只有 50–58 局 ⇒ **这条门禁在这套
   样本量下没有分辨力**。建议 s15/s16 若再测，按**预注册**做：同 pool、同 ckpt、`quality 384 局 +
   human 256 局`，B 单独比 A（不要三臂同时跑），先算功效再判。
2. **「按 delta 留题」与「重点后期」互相冲突**（§12.5）：C 删掉的 449 题里后期题占比最高，
   结果 t12–t15 全面不动、出局强度 −12.1%。**不建议**把 `--problem-min-strength-delta` 用于
   后期目标；它更适合「只学能长大的局面」的**效率/方差**实验（C 的 human 反而显著更好
   −0.156 [−0.293,−0.027]，但代价是后期更弱，属于另一条 trade-off，需单独预注册）。
3. **题池覆盖是硬瓶颈**：s14 分布下 64/64 局都在 t13 前出局，**t14/t15 的题必须用更弱对手的
   分布出题**（本次 human p0.5×3 席、无镜像 + `--focus-turns 10-15`，64 局得到 t14 22 / t15 12 题）。
   真要让 turn 权重作用于 t14/t15，下一步应该先把**后期题覆盖率**做上去（`--focus-turns` +
   `--games 256` 级），否则池子里 14/15 的权重只是空转。

### 12.10 回退

| 场景 | 操作 |
|---|---|
| 不想用加权 | `--problem-turn-weight ""`（默认）：`turn_weight=None`，走原 `mean` 路径，逐位等价 |
| 不想过滤 | `--problem-min-strength-delta 0`（默认）：不读 `strength_delta` |
| 池子建错 | 三份池都是独立文件，`--problem-pool` 指回 `data/board_problems/problems.jsonl` 即可 |
| trainer.pt 兼容 | 新开关只存在 `PPOConfig`（默认值），旧 `trainer.pt` 加载时取默认值；`state_dict` 里多两个键也不影响旧代码读其它键 |


## 13. 后期题池扩容（t10–t15）：规模、质量审计、B 臂复测（预注册）

> 状态：**题池扩到 4,871 题（t14 380 / t15 136，672 局）**；质量审计 52 题**全部 0 偏差**；
> 预注册的 B 臂复测（120M 冻结起点 + 新池）**未过 t14/t15 强度比 +10% 门禁**
> （t14 **−7.1%**、t15 **−3.7%**）⇒ **不进 s15**（`--problem-bc-coef` 保持 0）。
> 产物：`data/board_problems/problems_late_big.jsonl`（4,871 题）、
> `problems_all.jsonl`（6,452 题）、`runs/ab_late_big/{prereg.json,SUMMARY.json,audit_*.json}`。
> 代码：`scripts/build_board_problems.py --audit-games`、
> `scripts/audit_board_problems.py`、`scripts/merge_board_problems.py`。

### 13.1 动机与预注册（先写判据，再看结果）

§12.9 留下三个具体边界，本次只做三件事：

1. **扩池**：§12.5 的弱对手池（64 局）只有 t14 22 / t15 12 题，t14/t15 的强度比门禁在
   n=78–82 / 50–58 局下没有分辨力（B 的 +9.9% 差 0.1pp）；
2. **审计**：题池是「obs（3227+124+掩码）+ 人类参考解 + t+3 真实强度」的混合物，
   任何一环错位都会让训练静默跑偏，必须能从局面**重放**核对；
3. **只复测 B**：§12.8 里 B 是唯一在 t14/t15 正向的臂（+3.7% / +9.9%），
   本次同池、同起点、同 seed、同评测，**单因素**再测一次，并把 t14/t15 样本量提到 ≥150 局。

预注册写在**跑臂之前**（`runs/ab_late_big/prereg.json`，2026-10-31T17:46:21）：
起点 sha、池构造、两臂开关、评测规模、门禁与决策规则全部钉死。

- **起点**：`runs/ab_late_big/start_model.pt` = **s14 收尾权重**
  （s14 `history` 4,242 iter ≈ 120M decisions，`trainer_updates=4241`，
  sha256 `fffc395c…b58f500c`）。**题池与 A/B 用同一份权重**（on-policy 状态，§8.1 的要求）。
- **门禁**（与 §12.9 同口径）：t14/t15 强度比各 **≥ +10%**、human 配对 Δ **≤ +0.05**、
  出局强度 p50 **不降**、**零硬错**。

### 13.2 题池扩容（`--focus-turns 10-15` + 弱对手分布）

构造命令（每块 96 局；**块间 gseed 不重叠**，seed 步长 100）：

```bash
# 7 个 seed 块 × 96 局 = 672 局（python = hiermolgen 环境；cuda:7）
PYTHONPATH=rust/python:. python scripts/build_board_problems.py \
  --checkpoint runs/ab_late_big/start_model.pt --device cuda:7 \
  --games 96 --seed 20201 --focus-turns 10-15 --horizon 3 \
  --human-boards data/real_library/library_real_quasi_full.jsonl \
  --human-board-p 0.4 --human-board-seats 3 --human-board-fidelity full \
  --mirror-p 0 --move-guard 1 --obs-dtype f32 \
  --out runs/ab_late_big/parts/problems_late_big_s20201.jsonl
# 其余块：20301 20401 20501 20601 20701 20801（同一命令，只换 --seed）
```

**为什么 human p 是 0.4 而不是 §12.5 的 0.5**：s14 训练分布（human 5 席 p0.9 + 镜像 2 席）
下 64/64 局都在 t13 前出局（§12.5），题池**根部没有** t14/t15；p=0.5×3 席 24 局的试跑
只产出 t14 16 / t15 8（且 t15 波动大）。**p=0.4 让 learner 多活 1–2 回合**，24 局
→ t14 16 / t15 8（0.67/0.33 题/局），据此把局数放大到 672 局。

| 池 | 构造 | 题数 | t10 | t11 | t12 | t13 | **t14** | **t15** | Δ p50 | 存活率 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `problems_late_turns.jsonl`（§12.5） | 弱对手 64 局，seed 30200 | 418 | 126 | 106 | 92 | 60 | **22** | **12** | 0.415 | 56.5% |
| **`problems_late_big.jsonl`（本次）** | 弱对手 **672 局**，7 块 × 96 | **4,871** | 1,314 | 1,241 | 1,056 | 744 | **380** | **136** | 0.393 | 52.9% |
| **`problems_all.jsonl`（合并）** | 上面 + `problems_s14_s15.jsonl`，按 obs sha 去重 | **6,452** | 1,542 | 1,405 | 1,174 | 812 | **402** | **148** | 0.461 | 60.8% |

- **目标达成**：t14 380 ≥ 120、t15 136 ≥ 100、局数 672 ≥ 384（每块明细：
  t14 56/68/54/42/62/44/54、t15 24/18/22/12/20/16/24）；合并去重只丢 1 题
  （同 obs sha 的重复局面），0 个 label 冲突。
- 每题保留 `turn` / `strength_delta` / `is_late_turn`；`merge_board_problems.py` 只按
  `obs.sha256` 去重（冲突会计数报出），并重编 `problem_id`（原 id 存 `origin_problem_id`）。

**每个 turn 的 Δ 与存活率（`problems_all.jsonl`，Δ = t+3 的 `log1p` 增量）**：

| turn | 题数 | 存活率 | Δ p50 | Δ p90 |
|---|---:|---:|---:|---:|
| 6 / 7 / 8 / 9 | 128 / 128 / 128 / 120 | 100% | 1.196 / 1.091 / 0.951 / 0.715 | 1.668 / 1.591 / 1.436 / 1.178 |
| 10 | 1,542 | 94.6% | 0.665 | 1.122 |
| 11 | 1,405 | 70.1% | 0.470 | 0.878 |
| 12 | 1,174 | 33.4% | 0.286 | 0.613 |
| 13 | 812 | 11.3% | 0.159 | 0.527 |
| **14** | 402 | **4.5%** | 0.066 | 0.354 |
| **15** | 148 | **6.8%** | 0.000 | 0.332 |

**这条统计比题数更重要**：t+3 视界在 t14/t15 上要求游戏跑到 t17/t18，而弱对手局大多
在 t16 前结束（learner 或对手被淘汰），所以 **t14/t15 的强度标签 95% 是 `terminal=1`
（最后可见值，Δ→0）**。也就是说，扩容池给的是 **t14/t15 的「状态」**（turn 加权 CE
需要的正是状态），**不是 t14/t15 的「强度标签」**：`--strength-aux-coef` 在 t14/t15 上
只能用到 18+8 道存活题（`aux_valid`），**不能用这批题训练强度头**（误差会被 mask 掉，
剩下的前中期题会主导归一化）。这是 §13.3 审计只覆盖 `survived` 题的原因。

**参考解质量（决定 §13.4 结果的机理）**：匹配率 **100%**、`mass_legal` p50 **0.596**、
策略 top-1 命中参考 top-1 **18.8%**；层级 `tier` 3,135 / `turn_tier` 620 /
`turn_tier_gold` 2,697。t≥13 的题 **61%** 落在最具体的 `turn_tier_gold` 层（不是退化层），
但**参考 top-1 被 `reroll` 主导**：

| turn | 参考 top-1 = reroll | 参考 top-1 = buy | 参考质量里 reroll | buy |
|---|---:|---:|---:|---:|
| t6–t9 | 2–61% | 0–6% | 0.16–0.34 | 0.15–0.27 |
| t12 | 40.9% | 0.1% | 0.33 | 0.10 |
| t13 | **77.1%** | 0% | 0.41 | 0.06 |
| t14 | **69.2%** | 0% | 0.46 | 0.05 |
| t15 | **64.9%** | 0% | 0.44 | 0.08 |

即：10k+ 人类在后期 `(turn, tier, gold, 酒馆有牌)` 格子里的主动作是**刷酒馆**，
`buy` 的质量不到 8%。**加权 = 把 soft-CE 梯度按 turn 压到「reroll」这条动作上**——
这能解释为什么 B 的 t14/t15 强度比反而略降（§13.4），也说明**下一个瓶颈不是覆盖，
而是后期参考解本身**（reroll 不直接长大战团）。

**B 臂的加权后有效池**（`problems_all.jsonl` + `"10:2,12:3,14:4,15:4"`）：
权重和 **11,992**（+85.9% vs 6,452）；t≥10 的质量占比 **91.9%**（A 是 85.0%）；
t14 **13.4%**、t15 **4.9%**（A 是 6.2% / 2.3%）⇒ 每 iter 128 题里 t14 从 ~8 题变 ~17 题。

### 13.3 题池质量审计（重放 3 回合）

**为什么必须审计**：`obs`（features+cards+合法掩码）与 `label.strength_before/after_t3`
来自同一局 rollout 的不同时刻，任何错位（错题面对错标签、注入没重放、pass 位置错）
都会让 soft-CE/强度头静默学错东西，而指标上看不出来。

**工具**：`build_board_problems.py --audit-games` 记录被审局号的**每回合起始（注入后）
`state_json`** + `turn_pos`（回合在哪个 seat 开始，因为回合可能在 pass 中间推进）+
**learner 全部动作** `[turn, decision_idx, action]`；`scripts/audit_board_problems.py`
从局面按**与出题循环完全相同的调度**重放（同 `for seat in range(8)` + `bot_play` + 记录
动作），并做三件事：

1. 重放到题目决策点：重新编码观测，`obs.sha256` 必须**逐位相同**；`features` 解出的
   `Σ(atk+hp)` 必须等于 `label.strength_before`（观测与标签同口径的直接断言）；
2. 继续重放到 `turn+3` 回合起始（中途每个回合边界用记录状态替换**对手注入**；
   替换前后 learner 的 `player_json` 必须相同，否则说明重放已漂移）；
3. 比较重放得到的 `strength_after` 与 `label.strength_after_t3`：
   `Δ = log1p(after)-log1p(before)` 的相对偏差必须 < 10%。

**结果（全部 0 偏差）**：

| 审计集 | 采样 | 通过 | obs sha | strength_before 错 | Δ 相对偏差 p50/p90/max | 边界检查 |
|---|---:|---:|---:|---:|---:|---:|
| 主池 32 局分层抽样（t10 12 / t11 10 / t12 6 / t13 2） | 30 | **30** | 100% | 0 | **0.0 / 0.0 / 0.0** | 90/90 一致 |
| **补审 t14/t15**（7 局，全部 survived t≥14 的源局，逐局重跑捕获） | 22（t14 14 / t15 8） | **22** | 100% | 0 | **0.0 / 0.0 / 0.0** | 66/66 一致 |
| **合计** | **52** | **52** | 100% | 0 | **0.0 / 0.0 / 0.0**（门限 10%） | **156/156** |

- **确定性**：补审的 7 局按同 seed 重跑，82 行题目与合并池按 `obs.sha256` 一一对应，
  `strength_before/after`、`turn` **0 处不一致** ⇒ 出题是逐位可复现的。
- **全池廉价检查**（不需要重放）：`problems_late_big.jsonl` 全部 **4,871** 题解码 obs，
  `turn` 与 `strength_before` 对 `label` **0 处不一致**（`scripts/audit_board_problems.py
  --pool`，每次重建池都应跑一遍）。
- **已知边界（必须写明）**：审计只覆盖 `survived=1` 的题；t14/t15 的 `terminal=1` 题
  （占 95%）的「最后可见值」语义**没有**做重放验证——它的标签本来就不是 t+3 增量，
  训练侧也只在 `available & survived` 上使用（`aux_valid`）。52/52 的 0 偏差说明
  **重放链路（状态 ↔ obs ↔ 强度）是对的**，不说明 terminal 标签有物理意义。

### 13.4 A/B（B 臂复测，预注册单因素）

- **两臂**：同池 `problems_all.jsonl`、同起点（120M 冻结）、同 seed 20100、s14 逐字配方、
  `--problem-bc-coef 0.05`、各 **40 iter ≈ 1.12M decisions**（实测 A 1,121,170 / B 1,122,901）；
  A = 不加权，B = `--problem-turn-weight "10:2,12:3,14:4,15:4"`。
- **评测**：`human_panel_eval --games 256 --seats 8 --seed-base 420000 --smoke`（逐局配对）；
  `quality_monitor --games 320 --seed-base 740000`（t14 280/277 局、t15 209/206 局，
  达到 ≥150 局的目标，是 §12.8 的 3.4 倍样本）。

**逐 turn 强度比（ours p50 / real p50，quality 320 局）**：

| turn | 真实 p50 | A | B | B vs A | n（A/B） |
|---|---:|---:|---:|---:|---:|
| t9 | 546.5 | 0.3898 | 0.3898 | +0.0% | 320/320 |
| t10 | 1,128.5 | 0.2955 | 0.3053 | +3.3% | 318/318 |
| t11 | 2,203 | 0.2145 | 0.2081 | −3.0% | 316/318 |
| t12 | 4,458 | 0.1362 | 0.1332 | −2.1% | 316/315 |
| t13 | 9,666.5 | 0.0729 | 0.0717 | −1.6% | 311/314 |
| **t14** | 21,136 | 0.0398 | 0.0370 | **−7.1%** | **280/277** |
| **t15** | 26,516 | 0.0341 | 0.0328 | **−3.7%** | **209/206** |

**主表（human 256 配对 + quality 320）**：

| 臂 | human mean | Δ vs A [95% CI] | top4 Δ | t12 | t13 | **t14** | **t15** | tier≥5@t12 | tier≥5@t15 | 出局强度 p50 | moves/turn | 硬错 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A（对照） | 6.316 | — | 10.94% | 0.1362 | 0.0729 | 0.0398 | 0.0341 | 8.9% | 32.5% | 804 | 0.49 | 0 |
| **B（turn 加权）** | **6.176** | **−0.141 [−0.293, +0.016]** | **13.67% (+2.73pp)** | 0.1332 | 0.0717 | 0.0370 | 0.0328 | 9.2% | 31.6% | 816 (+1.5%) | 0.50 | 0 |

- 训练侧：A 的 `problem_bc_loss` 均值 8.23、`pbc_top1` 0.222；B 8.50 / 0.223
  （**加权后损失值不可直接比**：B 是 `Σw·CE/Σw`，池子质量分布也不同）；
  B 的 history 里 `problem_pool_turn_weights={'10':2,'12':3,'14':4,'15':4}`、
  `problem_pool_used=6452`，说明开关真的生效、没有空转。
- **功率**（这次必须报）：`ratio_p50` 是 280/206 局的样本中位数，按 `p90-p50≈1.28σ`
  估计 `se(median)≈4–5%`，两臂相对差的 95% CI 约
  **t14 [−17.4%, +3.3%]、t15 [−16.5%, +9.2%]**。也就是说：**这套样本量能排除 +10%
  以上的提升，但不能分辨 ±5%**；不过 B 的**点估计是负的**，不是「差一点没到 +10%」。

**门禁判定（预注册）**：

| 门禁 | 阈值 | B | |
|---|---|---|---|
| t14 强度比 vs A | ≥ +10% | **−7.1%** | ✗ |
| t15 强度比 vs A | ≥ +10% | **−3.7%** | ✗ |
| human 配对 Δ | ≤ +0.05 | −0.141 [−0.293, +0.016] | ✓ |
| 出局强度 p50 | 不低于 A | +1.5% | ✓ |
| 硬错 | 0 | illegal/truncated/truncated_combats 全 0 | ✓ |
| **整臂** | 全过 | **FAIL** | |

### 13.5 结论：不进 s15；瓶颈已从「覆盖」换成「后期参考解」

1. **题池覆盖不再是瓶颈**：t14/t15 从 22/12 题扩到 **380/136**（合并后 402/148），
   42% 的题在 t≥12，`--problem-turn-weight` 的 14/15 项**不再空转**（§12.9 的边界 3 已消除）。
   审计 52/52、偏差 0.0%，题池可以作为后续任何后期实验的数据底座。
2. **但 B 臂复测失败**：t14 −7.1%、t15 −3.7%（n=277/206），**与 §12.8 的 +3.7%/+9.9%
   方向相反**。两次的起点（s14 3501 vs 4241）和池子（1,581 vs 6,452 题）都不同，
   §12.8 那个「差 0.1pp」的 +9.9% 更可能是**噪声**；本次样本量足够排除 +10%。
   ⇒ `--problem-bc-coef` / `--problem-turn-weight` **保持默认 0 / 空串，不进 s15**。
3. **human 反而更好（−0.141，CI 上界 +0.016）且 top4 +2.73pp**：
   这与 §10.4「加大系数只抬 tier 不抬强度」一致——加权把梯度压到「后期刷酒馆/升本」
   这些**人类节奏**动作上，主面板（对 8 席人类风格对手）更舒服，但**战团强度不涨**。
   这不是收益（预注册门禁是强度），也不建议据此开开关。
4. **新的具体缺口 = 后期参考解**：t13–t15 的参考 top-1 有 **65–77% 是 `reroll`**、
   `buy` 质量 < 8%。加权等于教策略「后期刷酒馆」，它不直接长大战团。
   下一步要动的是**参考解构造**，而不是继续加题：例如后期只保留最具体的
   `turn_tier_gold` 层、对 `reroll` 做上限/下采样、或按「牌面质量/三连概率」重加权。
5. **强度头在后期上不可用（本次新增的证据）**：t14/t15 的 `survived` 只占 3.7%/5.9%，
   `aux_valid` 只有 18+8 题；`--strength-aux-coef` 在 t14/t15 上只能当噪声。
   要用结果标签监督后期，得把 horizon 缩到 **+2**（t14→t16 的存活率会高一个量级）
   或换更弱对手继续扩池——都需要单独预注册。

### 13.6 回退与产物

| 场景 | 操作 |
|---|---|
| 不想用新池 | `--problem-pool data/board_problems/problems_s14_s15.jsonl`（旧池，1,581 题）即可；新池只是文件，不影响默认路径 |
| 池子建错/重跑 | §13.2 的命令逐块可复现（同 seed 逐位一致；块间 seed 步长 100 避免 gseed 重叠） |
| 审计失败 | `scripts/audit_board_problems.py --audit <pool>.audit.jsonl --pool <pool>.jsonl`：obs sha / 强度偏差任一不通过即非 0 退出 |
| 训练侧回退 | 两个开关本来就默认关闭；`--problem-bc-coef 0` 时新池不被读取 |
| 产物 | `data/board_problems/problems_late_big.jsonl` + `.meta.json`、`problems_all.jsonl` + `.meta.json`、`runs/ab_late_big/parts/problems_late_big_s*.audit.jsonl`（32 局审计状态，123 MB）、`runs/ab_late_big/{prereg.json,SUMMARY.json,SUMMARY.json.md,audit_late_big.json,audit_late1415.json}` |
