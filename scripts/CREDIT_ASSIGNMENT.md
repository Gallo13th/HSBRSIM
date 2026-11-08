# 方向 B：信用分配离线诊断（幂率迹 + 动作条件 critic 边界）

> 状态：离线诊断/实现完成；**不接主线**。日期：2026-10-31。
> 规格来源：[RESEARCH_PLAN_V2](RESEARCH_PLAN_V2.md) §B.1（定义/极限）、§B.2（单测）、
> §B.3（baseline 无偏性）、§4.2（开发清单）。本文件只记录 CPU 离线结果，
> 不改变 s14 训练/评测，不占 GPU。

## 0. 结论（TL;DR）

1. **GAE(γ=1, λ=0.995) 的信用并没有被压没**：离线两套轨迹上，早期 t≤8 的终端分量
   占 `|A|` 中位 **15.8%**（audit 620 局）/ **21.8%**（s14 32 局），与
   [PRESSURE_AUDIT](PRESSURE_AUDIT.md) 的 14.6% 同量级；ESS 为 134 / 109。
   B 的前提（强度上来后名次不跟）当前不成立：t12/t15 强度比仍为 0.13/0.03。
2. **幂率核本身可离线复现与验证**：`hsbg/az/train/power_trace.py` 实现 §B.1 前向
   `A_t=Σ w̃_l γ^l δ_{t+l}`、后向 trace 定义、`N_eff=1/Σw̃²`、`gae` 逐位等价与
   `α→0 / α→∞ / Gamma 混合 / timebase` 单测；`tests/test_credit.py` 收集 **30** 个用例。
3. **默认关闭逐位等价**：`--adv-estimator gae` 仍调用旧 `compute_gae`，不新增
   records/meta 键、不改动作序列/RNG；同 seed 的 `build_batch_from_records` 输出
   **逐元素相等**（`tests/test_credit.py::test_build_batch_default_gae_is_bitwise_equal...`）。
4. **§B.1 的 horizon 归一化在 PPO 里有一个反直觉副作用**：归一化后早期 advantage
   幅度 ~`1/L`，而 PPO loss 又做全局 advantage normalization，结果**早期决策反而更轻**：
   `early |A| share` 从 GAE 的 0.480 掉到 0.243（s14）/ 0.152（audit）。
   因此若要做 s16 A/B，应使用 `--power-normalize 0`（见下）。
5. **离线候选参数：α=0.25, κ=10, normalize=0, decision timebase**。两套轨迹一致：
   ESS 不降（+3.5% / +6.4%）、终端分量占比升（+18% / +51%）、与 MC advantage 相关
   不降反升（+0.037 / +0.010）、早期 `|A|` 份额持平、方差 0.83× / 0.92×。
6. **动作条件 baseline**：actor 的 baseline 仍然**只用 `V(s)`**；
   `--baseline-action-dependent` 只允许 0，非 0 在 CLI/`PPOConfig` 构造期直接报错。
   toy 测试枚举 `E[∇logπ b(s,a)]≠0`、中心化不修正、双采样修正≈0（§B.3）。
7. **现在不接主线**：B 在 V2 排序里是 P3（A→C→D→B）；现有证据只说明“幂率核是一个
   可测的候选”，没有证明早期 action/value error 是当前强度瓶颈，也没有过 §2.3 的
   human/质量面板门禁。先做 A 的强度可学性，B 只在独立 exam 可分辨后作为单因素 A/B。

## 1. 实现

### 1.1 `hsbg/az/train/power_trace.py`（纯 numpy，默认关闭）

前向 advantage（替换 GAE 内部时间核 `λ^d`，不是叠加）：

```text
δ_t   = r_t + γ V(s_{t+1}) − V(s_t)
w_l   = (1 + l/κ)^(−α)                       # lag l，不含 γ
A_t   = Σ_{l=0}^{L_t−1} w̃_l γ^l δ_{t+l}       # w̃_l = w_l / Σ_j w_j
N_eff = 1 / Σ_l w̃_l²
```

后向资格迹（**只用于 `δ_t e_t` 更新，不当 advantage**）：

```text
e_t = Σ_{k=0}^{t} (1 + k/κ)^(−α) γ^k ∇log π(a_{t−k}|s_{t−k})
```

关键 API：

| 函数 | 作用 |
|---|---|
| `compute_credit(rewards, values, dones, mode, gamma, lam, alpha, kappa, cutoff, normalize, timebase, turns, duration)` | 返回 `(advantages f32, returns f32, diagnostics)`；`mode=gae` 与旧 `compute_gae` 逐位相等 |
| `power_raw_kernel(L, α, κ)` / `geometric_raw_kernel(L, λ)` | 未归一化核 |
| `trace_weights(L, α, κ, γ)` | 后向资格迹 lag 权重 `(1+k/κ)^(−α)γ^k`（用于 `δ_t e_t`，不是 advantage） |
| `kernel_weights(...)` | 含 γ^l / 归一化 / cutoff 的一维核 |
| `effective_sample_size(w)` | `1/Σw̃²` |
| `compact_diagnostics(diag)` | 去掉逐步大数组，供 records/meta 记录 p10/p50/p90 |

边界约定（与旧 GAE 一致）：

- `dones[t]>0.5` 是 terminal/truncated 边界，不 bootstrap，下一段重新起算；
- 数组末尾无 done 的尾段按无 next value 处理；
- `timebase=decision`：lag=动作步数；`timebase=turn`：lag=未来 elapsed turn
  （`turns[j]−turns[t]`），γ^lag 是 SMDP 折扣；`duration` 可显式给逐决策持续时间；
- `cutoff>0` 只在 power/geom 支持；`gae` 传 `cutoff`/`normalize=True`/`turn` 直接报错。

### 1.2 PPO 接线（默认关闭）

| 文件 | 改动 |
|---|---|
| `hsbg/az/train/ppo.py` | `PPOConfig.adv_estimator/power_alpha/power_kappa/power_normalize/power_cutoff/credit_timebase/baseline_action_dependent`；`build_batch_from_records` / `build_batch_from_arrays` 在 `adv_estimator != gae` 时才调用 `compute_credit`；`gae` 分支仍是原 `compute_gae` |
| `hsbg/az/train/ppo_trainer.py` | `state_dict()` 在 `adv_estimator=gae` 时剔除新增字段，保持旧 `trainer.pt` 字节兼容 |
| `hsbg/az/train/process_pool.py` | lockstep 任务透传 estimator 参数；worker 内 build 使用同一核 |
| `hsbg/az/train/parallel_collect.py` | 非 lockstep 路径透传 |
| `scripts/train_entity_sync.py` | 新增 `--adv-estimator {gae,power,geom}`、`--power-alpha`、`--power-kappa`、`--power-normalize`、`--power-cutoff`、`--credit-timebase`、`--baseline-action-dependent`；顺带修复 `PPOConfig` 未传 `lam` 的日志缺陷（现在 `ppo.config.lam == args.lam`） |

关闭时：不加载新数据、不消耗 RNG、不增加 records 字段；`build_batch_from_records`
默认输出与旧路径逐元素相等（动作序列、old_logprob、mask、value、rewards、returns 全等）。

### 1.3 离线工具 `scripts/advantage_estimators.py`

```bash
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
cd /home/data/users/gaoletian/projects/HSBRSIM
export PYTHONPATH=rust/python:.

# 1) CPU 跑 s14 checkpoint 32 局自对弈并转储 records（trainer 不落盘 records）
$PY scripts/advantage_estimators.py --out runs/adv_estimators \
  --dump-records 32 --checkpoint runs/az_entity_s14/model.pt \
  --workers 8 --threads 2 --alpha 0.25 --kappa 10

# 2) 只分析已有轨迹（audit + 已转储 records）
$PY scripts/advantage_estimators.py --out runs/adv_estimators \
  --alpha 0.25 --kappa 10
```

产物（只写 `runs/adv_estimators/`）：

- `records_s14_32g.jsonl.gz`：32 局 × 8 座 = **256 episodes / 53,393 decisions**；
  只保留 estimator replay 需要的 `turn/action/value/old_logprob/rank` 标量，
  不含 features/cards/mask（体积 1.1 MB）；`records_manifest.json` 记录 checkpoint
  sha256、seed、CPU/耗时、`opponent=self` 等 provenance。
- `report.json`：两套轨迹的 3/4 种 estimator、α/κ 网格、几何拟合、跨源一致性。
- `REPORT.md`：同内容的简表。

## 2. 离线数字

### 2.1 轨迹

| 源 | provenance | games | episodes | decisions | 用途 |
|---|---|---:|---:|---:|---|
| `s14_records` | `runs/az_entity_s14/model.pt`（s14 10M），CPU 8 座自对弈，move-guard 1，seed 20100，无注入 | 32 | 256 | 53,393 | 与当前 checkpoint/训练分布最近 |
| `audit` | `runs/audit/trajectories.jsonl.gz`，s10 checkpoint vs 7 引擎 bot，无注入（PRESSURE_AUDIT §2.5） | 620 | 620 | 168,229 | 大样本冻结对照 |

两套轨迹都**不是**“真实人类注入大厅”的重采；它们只用于比较 estimator 的核，
不能当作训练分布已覆盖强度压力的证据。s14 dump 在 CPU 上 163 s 完成，未占 GPU。

### 2.2 三种 estimator（同一批轨迹，α=0.25, κ=10）

s14 32 局（256 episodes / 53,393 decisions）：

| estimator | corr(MC adv, t≤8) | corr(MC adv, 全部) | ESS 均值 | N_eff@t8/t12/t15 | 终端占比 t≤8 | 早期 \|A\| 占比 | Adv 方差 | 方差比 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| GAE λ=0.995 | 0.916 | 0.923 | 109.4 | 123.4 / 72.7 / 47.1 | 0.218 | 0.480 | 0.106 | 1.00 |
| power normalize=1（§B.1 默认） | 0.710 | 0.075 | 113.2 | 127.1 / 73.0 / 47.0 | 23.71 | 0.243 | 0.0003 | 0.003 |
| **power normalize=0（候选）** | **0.953** | **0.949** | **113.2** | 127.1 / 73.0 / 47.0 | **0.258** | **0.501** | **0.088** | 0.830 |
| geom λ*=0.967（归一化对照） | 0.735 | 0.094 | 48.4 | 53.2 / 42.1 / 33.0 | 0.265 | 0.250 | 0.0003 | 0.003 |

audit 620 局（168,229 decisions）：

| estimator | corr(MC adv, t≤8) | corr(MC adv, 全部) | ESS 均值 | N_eff@t8/t12/t15 | 终端占比 t≤8 | 早期 \|A\| 占比 | Adv 方差 | 方差比 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| GAE λ=0.995 | 0.953 | 0.921 | 134.0 | 184.8 / 109.3 / 60.7 | 0.158 | 0.419 | 0.0270 | 1.00 |
| power normalize=1 | 0.854 | 0.080 | 142.6 | 198.9 / 112.2 / 61.3 | 30.11 | 0.152 | 0.0001 | 0.003 |
| **power normalize=0** | **0.963** | **0.956** | **142.6** | 198.9 / 112.2 / 61.3 | **0.238** | **0.431** | **0.0228** | 0.920 |
| geom λ*=0.967（归一化对照） | 0.775 | 0.175 | 51.0 | 59.3 / 51.4 / 36.4 | 0.023 | 0.234 | 0.0001 | 0.003 |

读法：

- 相关是 per-episode Pearson 均值；`MC adv = R − V_t`，`R=u(rank)`、γ=1。
- 终端占比 = `|w_last δ_T| / |A_t|` 的中位；它对核的整体缩放不敏感，可与
  PRESSURE_AUDIT 的 14.6% 直接比较。GAE 在本实现的两套轨迹上为 15.8%/21.8%。
- `N_eff` 是核的 ESS（`1/Σw̃²`），不是样本数；GAE 在 t≤8 已达到 ~123–185，
  说明 λ=0.995 已经是长记忆核，幂率核的价值不在“把记忆变长”。
- **normalize=1 的问题**：早期 advantage 幅度 ~`1/L`，PPO 全局归一化后早期反而
  更轻（early |A| share 0.24/0.15）；且 `A_t` 接近零使 terminal-share 数值爆到 18–30，
  这个“变大”不是可用的信用信号。
- **normalize=0 的候选**：与 GAE 同一量级（方差 0.83×/0.92×），ESS 不降，
  终端分量占比 +18%/+51%，相关不降；这是唯一值得进 40–60 iter A/B 的形态。

### 2.3 α/κ 网格（s14 32 局，normalize=0，摘要）

| α | κ | N_eff(t≤8) | 终端占比 t≤8 | 早期 \|A\| 占比 | corr(MC adv, t≤8) | corr(全部) | 方差比 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.25 | 3 | 124.1 | 0.251 | 0.493 | 0.926 | 0.913 | 0.508 |
| **0.25** | **10** | **127.1** | **0.258** | **0.501** | **0.953** | **0.949** | **0.830** |
| 0.25 | 30 | 129.4 | 0.267 | 0.513 | 0.973 | 0.976 | 1.216 |
| 0.50 | 10 | 113.0 | 0.214 | 0.460 | 0.880 | 0.811 | 0.365 |
| 0.50 | 30 | 122.8 | 0.234 | 0.481 | 0.927 | 0.907 | 0.716 |
| 1.00 | 10 | 94.8 | 0.177 | 0.430 | 0.849 | 0.712 | 0.317 |
| 2.00 | 10 | 25.8 | 0.066 | — | 0.590 | — | 0.006 |

- α=0 的未归一化核就是 GAE(λ=1)（均匀和），corr≈1、方差 2.25×；不是“幂率”。
- κ 越大核越平（越接近均匀）；α 越大核越局部（ESS 下降）。
- **推荐 α=0.25, κ=10, normalize=0**：在两套轨迹上都同时满足
  ESS 不降、终端占比升、相关不降、早期 |A| 份额不降、方差 ≤ GAE。

### 2.4 几何对照

按 KL 最小拟合幂率核（L=64）：α=0.25,κ=10 → λ*=0.9673（KL 见 `report.json`）。
几何对照的 ESS 只有 ~48–51（因为归一化几何核在有限 horizon 上的有效记忆短），
相关/早期份额都明显低于幂率核。它验证了 §B.1 的“幂率不是单一 GAE λ”：
α 大时局部几何率约 `e^{−α/κ}`，但不能用 GAE(0.995) 冒充。

## 3. §B.3 动作条件 critic / baseline 边界

### 3.1 结论

- **actor baseline 只用 `V(s)`**。`--baseline-action-dependent 0` 是默认；
  传 1 在 `scripts/train_entity_sync.py` 和 `PPOConfig.__post_init__` 双处报错。
- 本任务**没有实现** `Q(s,a)` head；因此不存在“动作条件 Q 被误当 actor baseline”的
  代码路径。若后续实现，只允许：`Q(s,a)` 进 critic/TD loss，adv 用 `A=Q−V`；
  不得用 `G−Q(s,a)` 作 policy gradient。
- 动作依赖 baseline 的偏差 toy 测试（3 动作 softmax，`b(a)=1[a=0]`）：
  解析 `E[∇logπ b] = π_0(e_0−π)`，范数 >1e-3；1e6 次蒙特卡洛均值与解析值一致
  （<3e-3）；中心化 `b−E_π[b]` 的偏差**不变**；独立双采样
  `∇logπ(a)(G−b(a'))` 的均值 <3e-3。
- 离散 245 动作空间若要用 `b(s,a)`，必须显式加权修正
  `+Σ_{a'}π(a'|s)∇logπ(a'|s)b(s,a')`（全动作求和，b stop-grad），
  或独立双采样；两者都要重新过单测与方差评估。

### 3.2 为什么不能把 Q−V 和“G−Q”混为一谈

`E[∇logπ (Q−V)] = ∇J`（V 项消失）是合法的 advantage；有偏的是把 `Q(s,a)` 当作
`G_t` 的 baseline 去减（`G−Q`），因为 `Q` 依赖动作且未 stop-grad 时
`∇E_{a~π}[Q] ≠ 0`。本文件的实现边界与 §B.3 一致。

## 4. 接入 s16 的建议

### 4.1 是否值得切？

**暂不切主线；只值得在独立 exam 可分辨后做一次 40–60 iter 单因素 A/B。**
依据：

1. B 的前提未出现：human 6.25 vs 基线 6.445 已有改善，但 t12/t15 强度比仍
   0.13/0.03；方案本身把 B 放在 P3（A→C→D→B），且要求“确有 credit bottleneck”。
2. GAE 的早期终端分量 15.8–21.8%、ESS 109–134，没有“被压没”；C1 判据（<10%）
   不成立。λ=0.995 已经是长记忆核，幂率核主要在**重加权**而非延长记忆。
3. normalize=1 的 §B.1 默认形态在 PPO 全局归一化下**降低**早期 |A| 份额，
   不能直接上；normalize=0 才与 GAE 同量级。这个反直觉点必须先在小实验确认。
4. 离线相关/ESS 改善不是策略改进证明；必须过 §2.3 的 human + 质量面板门禁。

### 4.2 若做 A/B 的最小预算与命令

- 父 checkpoint：固定 s14/s15 某一 hash；同 seed、同 RNG、同 reward/γ/模型容量/暴露。
- 单因素：只替换 advantage estimator；`--lam 0.995` 与旧 GAE 同批对照。
- 40–60 iter（约 8–12M decisions），先 20 iter 看 NaN/ratio/value loss/KL，
  再决定是否跑满；采集开销不变（核是 O(L²) numpy，和 rollout 同量级），
  `collect_s` 预计 <+1%。
- 评测预算：human 256 局 ≈194 s + quality 64 局 ≈92 s（§5.4 分账）。

```bash
# 候选臂（只加单因素；其余与 s14 完全相同）
$PY scripts/train_entity_sync.py --checkpoint runs/az_entity_s14/model.pt \
  ...s14 公共参数... \
  --adv-estimator power --power-alpha 0.25 --power-kappa 10 \
  --power-normalize 0 --credit-timebase decision \
  --out runs/az_entity_s16_power
```

晋级门（§2.3）：human 配对 Δ≤−0.10 且 CI 上界 <+0.05；top4 ≥ 基线−2pp；
t12/t15 强度比各自 +10%；tier≥5 不降；出局 p50 不降；illegal/truncation/注入错误=0；
ESS 下降 <50%、`N_eff@t15` 不超预注册上限。任一不达标 → 回退 GAE。

### 4.3 为什么现在不接主线（一句话）

**当前证据只支持“幂率核可离线验证、normalize=0/α=0.25/κ=10 是一个不伤 ESS/相关的
候选”，不支持“早期信用是当前强度瓶颈”；且 B 的前提（强度上来后名次不跟）
尚未出现，按 V2 优先级应先做 A/C/D，B 最后做。**

## 5. 单测与复现

`tests/test_credit.py`（30 个 test 项，CPU，不含引擎）：

1. α=0 均匀核、`N_eff=L`；
2. `N_eff` 随 α 单调不增；α=1e3→one-step（`w[0]>0.999`、`argmax=0`）；
3. α=8,κ=1,L=128 的几何极限：λ*<0.01、KL<1e-3、cosine≥0.999；
   对 GAE(0.995) KL>1、cos<0.2；
4. 幂率 vs 指数 cosine/KL 矩阵端点；
5. Gamma 混合恒等式（数值积分）；
6. `compute_credit(mode="gae")` 与旧 `compute_gae` 逐元素相等；terminal/truncated/
   empty/all-done；α=0/κ>0/L=0 无 NaN；
7. ESS 定义 `1/Σw̃²`、α 单调、δ 加常数只平移归一化 A；
8. timebase：turn 的 elapsed-turn 折扣 ≠ decision 步数；duration 与 turns 一致；
9. baseline toy：动作依赖 baseline 有偏、中心化无效、双采样≈0；
10. 非法参数（α<0、κ≤0、γ 越界、λ 越界、非法 mode/timebase、负 cutoff、
    turn 缺 turns、turns 非降、gae+cutoff/normalize/turn）；
11. **默认关闭**：`build_batch_from_records(adv_estimator="gae")` 与默认调用逐元素相等，
    且 `power` 只改 advantages/returns、不改 features/mask/action/old_logp；
    `PPOConfig(baseline_action_dependent=1)` 报错。

```bash
$PY -m pytest tests/test_credit.py -q          # 30 passed
$PY -m pytest tests/test_az_ppo.py tests/test_parallel_collect.py tests/test_process_pool.py -q
$PY scripts/advantage_estimators.py --out runs/adv_estimators --alpha 0.25 --kappa 10
```

产物：`runs/adv_estimators/report.json`、`runs/adv_estimators/REPORT.md`、
`runs/adv_estimators/records_s14_32g.jsonl.gz`、`records_manifest.json`。

## 6. 证据边界

- s14 dump 是 **CPU 自对弈、无人类/镜像注入**的 32 局；audit 是 s10 对 7 bot 的
  冻结轨迹。两者都不是训练分布的无偏样本，只能比较 estimator 的核。
- 离线相关性/ESS/终端占比都是**诊断量**，不是策略改进或强度提升的证明。
- 幂率核的 α、κ 只在两套轨迹上扫描；没有做独立 exam、没有扫 init seed。
- 未实现 `Q(s,a)` head，也未实现双采样/加权修正的 actor 路径；本文件只给出
  安全边界与 toy 偏差结论。
