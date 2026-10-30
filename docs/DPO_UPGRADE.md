# upgrade 子集 DPO（one-sided self-DPO）

> 目标：修复 learner 的 **tier 进度** —— `scripts/quality_monitor.py` 实测 tier 从 turn 9
> 起长期停在 4，而真实 10k+ MMR 在 t9+ 会到 5–6（`docs/TIER_TARGET.md`）。
> 本文记录：离线诊断 → 最小 DPO 实现 → **接进 PPO 训练循环**（默认关闭、`coef=0`
> 逐位等价）→ 小系数 A/B（cuda:7，60 iter）→ 失败判据与结论。

---

## 1. 离线诊断（已有基础）

真实人类回放（`data/firestone_bc/bc_samples.jsonl.gz`，MMR ≥ 6000）里
`action_type=="upgrade"` 的样本共 **3,050** 条。用干净基线 `runs/az_entity_s8b/model.pt`
在这些状态上做 masked-softmax 诊断（`scripts/dpo_upgrade_probe.py`，
`runs/dpo_upgrade_probe.json`）：

| 指标 | 数值 |
|---|---|
| 样本数 | 3,050（mmr ≥ 6000） |
| 当前策略在这些状态上**选 upgrade** | **67.4%**（2,056 / 3,050） |
| one-sided DPO 初值（β=0.1） | 0.7245（接受率 0.326 = argmax≠upgrade） |
| `tier4 且「应升本」`（turn 9 / 12）时选 upgrade | **25% / 13%** |
| 纯 DPO 30 步后的选择率 | **99.9%**（信号极尖） |

结论：整体选择率不低，但**该升不升**的 headroom 集中在 t9/t12；DPO 方向正确，但
**必须小系数**（纯 DPO 30 步就饱和）。

---

## 2. 已有实现（离线，`hsbg/az/train/dpo_upgrade.py`）

- `load_upgrade_samples(path, mmr_min=6000, limit=None) -> UpgradeSamples`
  只读 `action_type=="upgrade"` 的样本；观测编码**完全复用** `bc_aux`
  （`load_bc_samples` + `bc_obs_batch`），`action_index` 恒为 `3`（`ACT.A_UPGRADE`）；
  编码结果做形状/标签自检。`UpgradeSamples.take(indices)` 供训练期无放回抽样。
- `dpo_pair_loss(model, batch, beta) -> (loss, accept_rate)`：
  one-sided DPO，`chosen` = 人类 upgrade，`rejected` = **当前策略** masked argmax
  （自我对比、无参考模型），`argmax == chosen` 的样本跳过；
  `L = -logsigmoid(β·(logp_chosen − logp_rejected))` 在接受样本上取均值；
  整批被跳过返回 0（保留计算图，不会 NaN）。
- `masked_policy_logprobs(...)`：分块诊断前向（不改变 train/eval 状态）。
- 单测 `tests/test_dpo_upgrade.py`（9 项）覆盖手算对照、跳过、mask、空批、β、加载过滤。

---

## 3. 接进 PPO 训练循环（本次）

### 3.1 配置（`PPOConfig`，`hsbg/az/train/ppo.py`）

| 字段 | 默认 | 含义 |
|---|---|---|
| `dpo_coef` | `0.0` | DPO 系数；**0 = 完全关闭**（不加载池、不采样、不算 loss、stats 无 `dpo_*`） |
| `dpo_beta` | `0.1` | DPO 温度 β（有限正数） |
| `dpo_batch` | `128` | 每个 DPO 步无放回抽样的 upgrade 样本数 |
| `dpo_every` | `4` | DPO 周期，**按 iteration 计**（不是按 PPO 微批） |
| `dpo_samples` | `data/firestone_bc/bc_samples.jsonl.gz` | upgrade 样本来源 |

构造期校验：`dpo_coef >= 0`、`dpo_beta` 有限且 > 0、`dpo_batch > 0`、`dpo_every >= 1`。

### 3.2 训练器（`hsbg/az/train/ppo_trainer.py`）

- `PPOTrainer(..., dpo_pool=...)` / `set_dpo_pool()`：**惰性加载** upgrade 池
  （~3,050 条 / ~4–8 s）；`dpo_coef=0` 时**完全不加载**；加载失败只 warn 一次并自动
  `dpo_coef=0`（与 BC 同一策略，绝不中断训练）；
- 独立 `dpo_rng = default_rng([seed, 0x0D0])`：开/关 DPO、跳过步都**不改变** PPO 的
  permutation/采样序列（`bc_rng` 同理）；
- `update()` 里判定 `updates % dpo_every == 0` 才抽样（第 0 个 iteration 必做），
  抽样 `min(dpo_batch, len(pool))` 条后随 `train_ppo(dpo_batch=...)` 传入；
- `state_dict()/load_state_dict()` 持久化 `dpo_rng`（旧 `trainer.pt` 缺该键时保留新 RNG）。

### 3.3 损失接入（`ppo.py`）

与 BC 项同模式（同一个 `model`、同一次 `backward`）：

```
total = ppo + seq_coef·seq + bc_coef·bc + [dpo_coef·L_dpo]     # 方括号 = 每 dpo_every 个 iteration 一次
```

- 一次 iteration 只加**一次**：在第一个梯度累积组的第 0 个微批上把
  `dpo_coef_eff = dpo_coef × len(slices)` 加进 `total`；随后
  `(total / len(slices)).backward()` 正好抵消，等效梯度就是 `dpo_coef·∇L_dpo`
  （`--grad-accum 8` 下不会 1/8 折损，也不会多算）；
- 其余 iteration 完全不构建 DPO 图（无额外前向/显存）；
- stats（仅当真的算出 DPO 时出现）：
  `dpo_loss / dpo_coef / dpo_accept_rate / dpo_samples / dpo_beta / dpo_every /
  dpo_steps / dpo_batch_size`；`dpo_coef=0` 时这些键与 config 回显一起被剔除，
  **stats 结构与未接 DPO 的旧版本逐字节一致**；
- `dpo_accept_rate = 1 − P(argmax = upgrade)`，因此 **`1 − accept_rate` 就是当前策略在
  upgrade 池上的选择率**（可直接看 DPO 的行为效果）。

### 3.4 CLI（`scripts/train_entity_sync.py`）

```bash
--dpo-coef 0.002 --dpo-beta 0.1 --dpo-batch 128 --dpo-every 4 \
--dpo-samples data/firestone_bc/bc_samples.jsonl.gz
```

启动打印（`coef>0` 时）：

```
[dpo] upgrade 池: samples=3050 mmr>=6000 load=3.8s path=...
[dpo] beta=0.1 coef=0.002 batch=128 every=4 （每 4 个 iteration 加一次 coef*L_dpo）
[dpo] 当前策略 on 池: dpo_loss=0.7245 accept_rate=0.320（n=512） -> 单步项=0.00145，平均/iteration=0.00036
[dpo] 期望梯度占比（loss 标度参考）: 单步 DPO 项 / |PPO total| ≈ 0.19%（参考 total=0.7700）
[dpo] 期望梯度占比（实测 ‖g_dpo‖/‖g_ppo‖，来自 runs/dpo_grad_probe.json）: 单步≈0.04%，平均/iteration≈0.01%
```

（池加载失败 → `[warn] upgrade DPO 样本加载失败，自动关闭 dpo_coef=0（不中断训练）`。）

### 3.5 期望梯度占比（离线探针）

训练循环里没有余量再算一次“无 DPO 的 PPO 梯度”作分母：`--compile-train 1` 的编译反向
使用 donated buffer（`retain_graph=True` 直接报错），且 s9d 同款配置（bf16 + 16 actor）
下多一次 1024 行前向实测 **CUDA OOM**。因此拆成独立探针 `scripts/dpo_grad_probe.py`
（不改权重、不训练）：

1. 用 checkpoint 采集 2 局（bot 对手、与训练同款采集配置，实测 ~3 s / 430 decisions）；
2. 构造训练同款 PPO 损失（policy/value/aux/seq/BC）求 `‖g_ppo‖`；
3. upgrade 池抽 128 条求 `‖g_dpo‖`（**coef=1**）；
4. 写 `runs/dpo_grad_probe.json`：`share_per_coef = ‖g_dpo‖/‖g_ppo‖`。

s8b 实测：`‖g_ppo‖=15.34`（PPO total=0.696，430 decisions）、
`‖g_dpo‖=3.13`（L_dpo=0.727，accept=0.359）→ **`share_per_coef = 0.204`**。
系数线性，所以

| coef | 单步梯度占比 | 平均/iteration（every=4） |
|---|---|---|
| 0.002 | 0.041% | 0.010% |
| 0.005 | 0.102% | 0.026% |

> 这是**梯度范数**占比（含 value/BC/seq 全部 PPO 项），不是“对 upgrade logit 的定向
> 位移占比”。A/B 实测证明它就是有效判据：coef 0.002/0.005（0.01%/0.03% 累计）测不出
> 任何行为变化；**0.02 + every=1（0.41% 累计）才出现 +8.6pp 的 picks_upgrade**
> （§6.5）。原因：Adam 每步参数位移 ≈ lr（1.2e-6），DPO 必须在**累计**意义上和 PPO
> 同量级才推得动策略，见 §4 的预算公式。

### 3.6 逐位等价（默认关闭）

`dpo_coef=0`：不加载池、不建 DPO 图、不动 RNG、stats/config 无 `dpo_*`。
`tests/test_dpo_train.py::test_dpo_coef_zero_is_bitwise_identical` 用同 seed / 同 batch /
同 `rng` 跑两次（一次不传 DPO、一次传池但 `coef=0`），`model.pt` **SHA256 相同**。
另有：手算梯度对照（含 `grad_accum` 补偿）、`coef>0` stats 出现、池空/加载失败自动跳过、
`dpo_every` 按 iteration 计数、独立 RNG 不扰动 PPO 序列。

```bash
pytest tests/test_dpo_train.py tests/test_dpo_upgrade.py -q     # 7 + 9 项
```

---

## 4. 系数选择（被 A/B 修正过的结论）

- 纯 DPO（单独优化、无 PPO 竞争）30 步可把选择率推到 99.9% → 信号很尖，最初据此选了
  **0.002 / 0.005 + every=4**（每 60 iter 只有 15 个 DPO 步）；
- **实测这两个系数没有可测效果**（§6）：DPO 梯度只占同一步 PPO 梯度的 0.04%/0.10%，
  15 步累计仍远小于 PPO 自身的漂移；
- 把累计量写成可预算的形式（§3.5 的 `share_per_coef=0.204`）：

  ```
  累积 DPO 梯度 / 累积 PPO 梯度 ≈ coef × 0.204 × (dpo_steps / ppo_updates)
  ```

  | 配置 | coef | dpo_steps/ppo_updates | 累计占比 |
  |---|---|---|---|
  | B | 0.002 | 15/60 | **0.010%** |
  | C | 0.005 | 15/60 | **0.026%** |
  | D | 0.020 | 60/60 | **0.41%** |

- **D（0.02 + every=1）是第一个有效配置**：池上 picks_upgrade 69.05% → 77.7%
  （+8.6pp），t9/t12 的 should 组 pick率 +15.1/+13.1pp，t15 的 tier p50 4 → 5；
  panels 不劣化。仍未饱和（77.7% ≪ 90%）；
- 推荐：**`--dpo-coef 0.02 --dpo-every 1`**（或等效平均权重的 `0.08 @ every=4`，
  但每步尖峰更大、不推荐）。不要再往 0.002/0.005 调，那一段是噪声平台；
- 若要更快见效（或 s9d 的 lr 更低），可把 DPO 放进**独立参数组/优化器**给更大 lr，
  或先做 30 步纯 DPO 预热再回 PPO（这也是最初 99.9% 那条结论的做法）；
- 饱和/停止条件：`picks_upgrade > 85–90%` 或 `dpo_accept_rate < 10%`（池上已无对比信号）
  时把 coef 降回 0 或改用 ramp。

## 5. A/B 设置

- 起点：`runs/az_entity_s8b/model.pt`（与 s9d 同一 checkpoint）；seed 15100；
- s9d 同款超参（`lr=1.2e-6`、`minibatch=1024`、`grad_accum=8`、`epochs=1`、
  `lam=0.995`、`clip=0.2`、`target_kl=0.02`、`max_grad_norm=1.0`、`amp=bf16`、
  `compile_train=1`、`anchor_beta=0.1/0.02`、`pi_coef=0`、`seq_coef=0.05`、
  `bc_coef=0.008`、`bc_every=4`、`shaping_coef=0.001`、mirror/human-board 注入同 s9d），
  `--move-guard 1`；
- 每臂 **60 iteration**（192 games/iter ≈ 36.7k decisions → 共 ≈ 2.22M decisions）；
- 单一 GPU（cuda:7）：`--processes 12 --gpus 7`（`processes/games` 只影响吞吐，
  不改学习口径）；四臂串行、互不重叠；
- 评测（全部同 seed 面板、同 checkpoint 口径）：
  - `scripts/quality_monitor.py --games 64 --move-guard 1`（tier p50 @ t9/t12/t15、
    tier≥5 比例、战团强度比）；
  - bot 面板 `scripts/c0_gate.py --games 64 --seats 8 --smoke`（model vs 引擎 bot 配对 rank）；
  - human 面板 `scripts/human_panel_eval.py --games 96 --seats 8 --smoke --baseline-bot 1`；
  - 池上 probe `scripts/dpo_upgrade_probe.py --device cpu`（3,050 条 upgrade 的
    `picks_upgrade` 与 t9/t12 should 组 pick率 —— 最敏感的行为指标）。

单臂命令（A 无 DPO；B/C 是 DPO 系数；D 是有效系数下限）：

```bash
COMMON="--checkpoint runs/az_entity_s8b/model.pt --arch entity --device cuda:7 \
  --processes 12 --gpus 7 --threads 8 --games 192 --sims 0 --epochs 1 \
  --minibatch 1024 --grad-accum 8 --amp bf16 --lr 1.2e-6 --lr-min-ratio 0.5 \
  --max-updates 3000 --clip 0.2 --target-kl 0.02 --lam 0.995 --max-grad-norm 1.0 \
  --entropy-coef 0.001 --pi-coef 0.0 --anchor-beta 0.1 --anchor-iterations 200 \
  --anchor-beta-tail 0.02 --compile-train 1 --anchor-amp 1 --pipeline 1 --lockstep 1 \
  --leaf-wait-ms 1.0 --move-guard 1 --move-cap 3 --move-repeat-limit 2 \
  --shaping-coef 0.001 --seq-coef 0.05 --bc-coef 0.008 --bc-batch 128 --bc-every 4 \
  --bc-compile 1 --gpu-free-check 0 --seed 15100 --iterations 60 --minutes 90 \
  --snapshot-every 100 --keep-snapshots 2 --out runs/dpo_ab/A"
python scripts/train_entity_sync.py $COMMON
python scripts/train_entity_sync.py $COMMON --dpo-coef 0.002 --dpo-batch 128 --dpo-every 4 --out runs/dpo_ab/B
python scripts/train_entity_sync.py $COMMON --dpo-coef 0.005 --dpo-batch 128 --dpo-every 4 --out runs/dpo_ab/C
python scripts/train_entity_sync.py $COMMON --dpo-coef 0.02  --dpo-batch 128 --dpo-every 1 --out runs/dpo_ab/D
```

汇总：四臂的 `quality.json / bot_panel.json / human_panel.json / pool_probe.json`
都在 `runs/dpo_ab/{A,B,C,D}/`；`runs/dpo_ab/table.json` 是本文所有数字的来源。

> `quality_monitor.py` 本次新增 `tier_ge5_ratio`（逐 turn）与 `tier_p50_t15 /
> tier_ge5_t9|t12|t15 / strength_ratio_t9|t12|t15` 汇总键（additive，不改旧指标）。

## 6. A/B 结果

（A = 无 DPO；B = coef 0.002；C = coef 0.005；均 60 iter / ≈2.22M decisions，cuda:7，
同 seed / 同 checkpoint / 同超参；`dpo_every=4` → 每臂 15 个 DPO 步。）

### 6.1 quality_monitor（64 局，engine bot；`--move-guard 1`）

| 指标 | A（现状） | B（0.002） | C（0.005） |
|---|---|---|---|
| tier p50 @ t9 / t12 / t15 | 4 / 4 / 4 | 4 / 4 / 4 | 4 / 4 / 4 |
| **tier≥5 比例 @ t9** | 0.125 | 0.109（−1.6pp） | **0.156（+3.1pp）** |
| **tier≥5 比例 @ t12** | 0.270 | 0.266（−0.4pp） | **0.317（+4.8pp）** |
| tier≥5 比例 @ t15 | 0.457 | 0.450 | 0.488（+3.1pp） |
| 战团强度比 @ t9 / t12 / t15 | 0.414 / 0.155 / 0.040 | 0.389 / 0.139 / 0.040 | 0.408 / 0.135 / 0.031 |
| quality 面板 mean_rank / top4 / win | 1.688 / 0.969 / 57.8% | 1.781 / 0.984 / 50.0% | 1.812 / 0.969 / 50.0% |

### 6.2 训练面板（同 seed 面板，配对 rank）

| 指标 | A（现状） | B（0.002） | C（0.005） |
|---|---|---|---|
| bot 面板 64 局 mean_rank | 1.688 | 1.500 | 1.578 |
| bot 面板 Δ vs bot（负=更好） | −3.266 [−3.83, −2.70] | −3.453 [−4.02, −2.88] | −3.375 [−3.98, −2.75] |
| human 面板 96 局 mean_rank | 6.469 | 6.406 | 6.385 |
| human 面板 Δ vs bot（负=更好） | −1.281 [−1.59, −0.99] | −1.344 [−1.65, −1.06] | −1.365 [−1.63, −1.11] |

### 6.3 upgrade 池上 probe（3,050 条静态样本，最敏感的行为指标）

| 指标 | A（现状） | B（0.002） | C（0.005） |
|---|---|---|---|
| picks_upgrade 总体 | 69.05% | 68.13%（−0.9pp） | 69.57%（+0.5pp） |
| t7 should 组 pick率（n=198） | 88.4% | 86.9% | 89.4% |
| t9 should 组 pick率（n=53） | 28.3% | 24.5% | 28.3% |
| t12 should 组 pick率（n=38） | 13.2% | 7.9% | 18.4% |
| DPO loss / accept_rate（池上） | 0.725 / 30.9% | 0.730 / 31.9% | 0.724 / 30.4% |
| 训练期间 1−accept（15 个 DPO 步） | — | 0.648→0.742，mean 0.718 | 0.648→0.727，mean 0.712 |

### 6.4 读法与噪声（重要）

- 64 局 tier≥5 的 1pp = 0.64 局：t9 上 `0.125 → 0.156` 只是 8 → 10 局，**纯噪声**；
  t12 的 `0.270 → 0.317` 是 17 → 20 局，同样在噪声内；
- 池上 probe（3,050 条）总体 picks_upgrade 的 1σ ≈ 0.84pp，t9/t12 子组（n=53/38）1σ ≈ 6pp；
  B 与 C 相对 A 的变化都在 ±1σ 内，**且不单调**（B 略降、C 略升）；
- 训练面板的 95% CI 宽度约 0.5 rank，B/C 与 A 全部重叠；
- 与 §3.5 的梯度占比一致：coef 0.002/0.005 + every=4 → 单步 DPO 梯度只有 PPO 的
  0.04%/0.10%，累计 15 步仍远小于 PPO 的漂移 → **测不出行为变化是预期结果**。

### 6.5 附加臂 D（有效系数下限：0.02 + every=1，60 个 DPO 步）

| 指标 | A（现状） | D（0.02, every=1） | Δ（D−A） |
|---|---|---|---|
| tier p50 @ t9 / t12 / t15 | 4 / 4 / 4 | 4 / 4 / **5** | t15 +1 |
| tier≥5 比例 @ t9 | 0.125 | 0.109 | −1.6pp（1 局噪声） |
| tier≥5 比例 @ t12 | 0.270 | **0.359** | **+8.9pp** |
| tier≥5 比例 @ t15 | 0.457 | **0.649** | **+19.2pp** |
| quality mean_rank / top4 / win | 1.688 / 96.9% / 57.8% | **1.531 / 100% / 60.9%** | 更好 |
| death_strength_p50 | 769 | **902** | +133 |
| bot 面板 Δ vs bot（负=更好） | −3.266 | −3.281 | −0.016（噪声内） |
| human 面板 Δ vs bot（负=更好） | −1.281 | −1.323 | −0.042（噪声内） |
| 池上 picks_upgrade | 69.05% | **77.7%** | **+8.6pp（10σ）** |
| 池上 t9 should 组 pick率（n=53） | 28.3% | **43.4%** | **+15.1pp（2.4σ）** |
| 池上 t12 should 组 pick率（n=38） | 13.2% | **26.3%** | **+13.1pp（1.9σ）** |
| 池上 tier4 / tier5 的 pick率 | 53.5% / 21.0% | 67.9% / 37.4% | 两级都更敢升 |
| DPO loss / accept（池上） | 0.725 / 30.9% | 0.722 / 22.3% | 池上信号被消耗 8.6pp |

**为什么 t9 的 tier≥5 没升**：t9 的 tier 由 **t7/t8 的 upgrade** 决定，而 DPO 的
should 组集中在 t9/t12 —— 效果体现在**下游** t12/t15（t12 +8.9pp、t15 +19.2pp、
t15 的 tier p50 4→5）。池上 t9 should 组 pick率 +15.1pp 才是“该升已升”的直接证据。
换句话说，判据里的 “t9/t12 tier≥5 上升” 应按“**滞后一档的下游 turn**”解读。

## 7. 失败判据与结论

**判据（任务口径）**：t9/t12 的 `tier≥5 比例`上升 **且** human 面板 mean_rank 不劣化
（Δ ≤ +0.15）**且** bot 面板不倒退（Δ ≤ +0.15）。

### 7.1 结论

- **B（0.002）、C（0.005，every=4）不建议并入**：池上 picks_upgrade 变化
  −0.9pp / +0.5pp（1σ≈0.84pp，且不单调），t9/t12 的 tier≥5 变化在 64 局噪声内，
  DPO loss 15 步不动（0.727→0.727）。**这一段系数是噪声平台**；C 的“PASS”是
  2–3 局噪声 + 面板随机波动的假阳性，不能当结论。
- **D（0.02, every=1）建议并入 s9d**：池上 picks_upgrade +8.6pp（10σ）、
  t9/t12 should 组 +15.1/+13.1pp、t15 的 tier p50 4→5、tier≥5@t12 +8.9pp /
  @t15 +19.2pp；human Δ −0.042、bot Δ −0.016（都远在 +0.15 容差内，且方向偏中性）。
  t9 的 tier≥5 −1.6pp（1 局）不作为否决：它是滞后指标（见 §6.5）。
- **并入方式**：`--dpo-coef 0.02 --dpo-beta 0.1 --dpo-batch 128 --dpo-every 1`，
  从 s9d 最新快照续训；建议**先 60–200 iter 观察**（或加 ramp/上限），
  到 `picks_upgrade > 85%` 或 `dpo_accept_rate < 10%` 时衰减/关闭。
  期望收益：t15 的 tier p50 从 4 推到 5、tier≥5@t12/t15 抬升，panels 不下滑。

### 7.2 失败模式（任一即停用 DPO 或降系数）

1. t12/t15 的 tier≥5 比例没有上升（信号太弱 / 被 anchor+BC 抵消）—— B、C 即此；
2. human 面板 mean_rank 劣化 > +0.15（提前升本牺牲经济/血量）；
3. bot 面板 mean_rank 劣化 > +0.15；
4. `picks_upgrade` 冲到 > 90%（饱和，变成无脑升本）—— D 只到 77.7%，安全；
5. 池上 `accept_rate` < 10%（没有可学的对比信号，继续加只会放大噪声）；
6. DPO loss 在 20+ 步内完全不动（当前系数下 DPO 项等于没接）—— B/C 即此，
   此时调系数没有意义，应先看 §4 的累计占比预算。

## 8. 运维注意

- `dpo_coef=0` 是**逐位等价**的默认路径：老 run 续训、A/B 基线都不受影响；
- `dpo_coef>0` 时启动多 ~4–8 s（读 12 MB JSONL 的 upgrade 子集）+ 每 4 个 iteration 一次
  128 行前向（实测 PPO 阶段耗时不变，四舍五入到噪声内）；
- 池是**静态**的人类样本（不随策略刷新），`rejected` 是当前策略 argmax，所以信号会随
  选择率上升而自然衰减（accept_rate ↓）——这是设计使然，不是 bug；
- `--compile-train 1` 下不要再在训练循环里做二次前向诊断（会 OOM）；梯度占比走
  `scripts/dpo_grad_probe.py` 离线测。
