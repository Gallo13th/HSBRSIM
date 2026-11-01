# 随机性感知搜索（StochasticSearcher）：K 次采样的 Monte-Carlo 叶值

> 状态：实现 + 单测 + s17 冻结快照上的 K∈{1,2,4} 128 局面板（结果见 §4）。
> 代码：`hsbg/az/train/infer_search.py`（`InferSearchConfig.rollouts` /
> `rollout_mode` / `rollout_seed`）、`scripts/human_panel_eval.py`
> （`--infer-search-rollouts` / `--infer-search-rollout-mode`）、
> `scripts/stoch_search_summary.py`、`tests/test_infer_search.py`。

## 0. 结论摘要

1. **为什么必须是采样型搜索**：真实对局的隐藏信息（对手手牌/战团、商店刷新、战斗
   随机数）**不可回放**，同 seed + 同动作序列只保证单局引擎内确定性。推理期搜索若
   只做一次确定性 rollout，等于把「一个可能世界」当成了真值；`InferSearcher` 的叶值
   `Q = L(Σ_end)` 应理解为 `E[L(Σ_end)]` 的**蒙特卡洛估计**。
2. **实现**：`rollouts=K` 时每个候选跑 K 个独立副本（`game.copy()` + 逐副本动作采样
   流），叶值取 K 次的**均值**，π_search 用均值 Q 构造，同时给出**标准误**；
   K=1 与旧路径**逐位一致**（单测 `test_k1_is_bit_identical_to_legacy_path`）。
3. **引擎限制（重要）**：`hsbg_engine` **没有** RNG 重播种 API（`Game.copy()` 连同
   RNG 状态一起复制）。因此「独立 RNG/隐藏状态」用**不同的动作采样流**近似：副本从
   π_base 采样后续动作，动作序列不同 ⇒ 商店刷新/战斗消耗引擎 RNG 的路径不同 ⇒
   隐藏信息沿不同分支展开。这是任务书允许的近似，**不是真正的 POMC/粒子滤波**。
4. **成本**：候选 lockstep 批量前向外加 K 倍副本，单次搜索耗时**亚线性**于 K
   （K=4 约 2–3× K=1），且 `--infer-search-max-ms` 可超时退回 π_base。
5. **最小可用 K**：见 §4 表。名次收益在 K=2 已基本拿满；若以「叶值标准误 / 候选间
   Q 标准差 ≤ 10%」为准则，K=4 仍不够（需 K≈16），所以**部署口径建议 K=2–4 + 超时
   兜底**，把 K 当作「降低决策噪声」而不是「无偏估计」。

## 1. 方法

### 1.1 叶值与聚合

单副本：候选动作 `a` 执行后，learner 用 rollout 策略走到本回合末（`turns=1`）或第
`turns` 个回合末，叶值

```
Q_k(a) = L(Σ_end,k) [+ w_t·tier/6] [+ w_h·health/30],  L(Σ)=log1p(Σ)/log1p(30000)
```

K 副本：

```
Q̄(a) = (1/K) Σ_k Q_k(a)
SE(a) = std({Q_k(a)}, ddof=1) / √K        (K>1；K=1 时 SE=0)
π_search ∝ p̃(a) · exp(clip((Q̄(a) − V)/τ, ±adv_clip)),  V = Σ_a p̃(a) Q̄(a)
```

动作规则不变（`pi_argmax` / `argmax_q` / `sample`）；`argmax_q` 用 `Q̄`。

### 1.2 独立副本怎么来

- `rollout_mode=auto`（默认）：K=1 → `greedy`（旧路径逐位一致）；K>1 → `sample`。
- K>1 时逐副本 RNG 种子 = `(rollout_seed, 第几次搜索, 候选下标, 副本下标)` 的
  `SeedSequence`。同 seed + 同调用序 ⇒ 逐位可复现；换 seed ⇒ 不同样本。
- 每个副本在 rollout 内**从 π_base 采样**动作（不是 argmax）；根候选动作仍固定，
  因此候选之间的比较是「同一动作在不同未来随机性下的期望」。
- **显式拒绝** `rollouts>1 + rollout_mode=greedy`：greedy 的 K 个副本必然逐位相同，
  静默跑 K 次是白花算力（`InferSearchConfig.validate` 直接 `ValueError`）。

### 1.3 性能

| 手段 | 说明 |
|---|---|
| 跨候选批量 rollout | 所有候选 × K 个副本在同一个 lockstep 循环里前向（B=topk·K） |
| 超时回退 | `--infer-search-max-ms`：单次搜索超时 ⇒ 返回 `None`，调用方用 π_base 动作 |
| 只搜关键决策 | `--infer-search-when carrier_or_spell` + 每回合上限（已有） |
| 叶值 horizon | `turns=1` 比 `turns=3` 便宜约 5×（已有） |

## 2. 接口

```bash
# K 次采样（默认 K=1 = 旧路径）
python scripts/human_panel_eval.py --checkpoint CKPT --games 128 --seats 4 \
  --seed-base 420000 --device cuda:7 --smoke --baseline-bot 0 \
  --infer-search 1 --infer-search-rollouts 4 --infer-search-rollout-mode sample \
  --infer-search-turns 1 --infer-search-topk 8 --infer-search-action pi_argmax \
  --out runs/stoch_search/panel_k4.json
```

统计字段（panel JSON 的 `search` 段）：

| 字段 | 含义 |
|---|---|
| `rollouts`, `rollout_mode` | K 与实际生效的 rollout 规则 |
| `mean_ms_per_call` | 单次搜索墙钟（含 K 副本） |
| `mean_q_se` | 每次决策的候选叶值标准误均值（L 单位） |
| `q_se_ratio` | `mean_q_se / mean(Q 跨候选标准差)`；= Monte-Carlo 噪声 / 信号 |
| `search_timeouts` | 超时回退次数 |

## 3. 单测（`tests/test_infer_search.py`）

1. `test_k1_is_bit_identical_to_legacy_path`：用**独立复刻**的旧实现（单副本、greedy、
   单次叶值）对比 K=1 的 `cands/q/sigma_end/pi`，逐位相等；
2. `test_stochastic_rollouts_mean_se_and_seed_determinism`：均值/SE 数学契约、同 seed
   逐位可复现、换 seed 有差异、K=4 内部确实出现非零方差；
3. `test_rollouts_gt1_greedy_is_rejected`：greedy+K>1 必须报错；
4. `test_search_timeout_falls_back_to_none`：超时返回 `None` 且 `timeouts` 自增。

## 4. 结果（s17 冻结快照 `step_001001`，128 局 = 4 seat × 32，seed 420000）

> s17 快照 sha256 前缀 `bbecd81e`。对照臂 = 关闭搜索。表格由
> `scripts/stoch_search_summary.py` 生成（`runs/stoch_search/SUMMARY.md`）。

| 臂 | K | rollout | mean rank | top4 | Δ vs off [95% CI] | s/局 | ms/call | leaf steps/call | q_se | q_se/spread |
|---|---:|---|---:|---:|---|---:|---:|---:|---:|---:|
| off | — | — | 6.344 | 10.9% | — | 1.42 | — | — | — | — |
| k1 | 1 | greedy | **5.938** | **18.0%** | **−0.406 [−0.672, −0.148]** | 8.29 | 307.7 | 107.5 | 0 | 0 |
| k1s | 1 | sample | 6.031 | 16.4% | −0.312 [−0.586, −0.039] | 11.11 | 430.9 | 101.8 | 0 | 0 |
| k2 | 2 | sample | 6.000 | 13.3% | −0.344 [−0.641, −0.055] | 12.89 | 487.7 | 205.9 | 4e−6 | 0.336 |
| k4 | 4 | sample | 6.000 | 9.4% | −0.344 [−0.602, −0.078] | 9.11 | 355.1 | 421.3 | 3e−6 | 0.299 |

读法：

1. **搜索在 s17 上依然显著**：K=1 greedy 把 mean rank 从 6.344 拉到 5.938
   （Δ=−0.406，CI 不含 0）、top4 10.9%→18.0%。这比 s16b 的 −0.422/−0.117 capture
   更好（s16b 起点 6.375），说明 s17 的搜索增益没有被训练吃掉。
2. **K=2/4 没有把名次做得更好**：三档采样臂都在 6.00–6.03，彼此 CI 重叠。单次
   采样的噪声（K=2 的 SE≈σ/√2）足以抵消 K 平均带来的稳定性；而 greedy K=1 的
   「确定性偏差」反而在 128 局上略优。
3. **成本随 K 线性**：`leaf_steps/call` = 107.5 → 205.9 → 421.3，正好 ≈1×/2×/4×。
   墙钟 ms/call 不可直接跨臂比较：K=2 与 K=4 跑在不同负载窗口（邻居实验
   08:36–09:35 占满 cuda:7，load 160–185；之后降到 ~20），K=4 的 355 ms/call
   反而低于 K=2 的 488 ms/call。**以 leaf steps 作为成本口径**。
4. **方差**：K=2 的 `q_se/spread = 0.336`，K=4 仍有 **0.299**。SE ∝ 1/√K，
   要把它压到 10% 需要 **K ≈ 4·(0.299/0.10)² ≈ 36**（取 32–64），是 K=4 的
   8–16 倍叶计算。绝对值上 `q_se ≈ 3e−6`（L 单位），因为大多数决策的候选 Q
   差异本来就只有 1e−5 量级 —— 即 **单次 rollout 的噪声远大于候选间差异**，这
   正是「搜索必须采样」的定量证据，也是「K 平均」在成本上不划算的原因。

### 4.1 超时回退实测（K=4, `--infer-search-max-ms 60`, 8 局）

8 局内触发 369 次搜索：**361 次超时回退到 π_base、8 次成功、0 错误**，成功调用的
mean 49.9 ms。说明 `--infer-search-max-ms` 能兜住尾延迟（即使 60 ms 预算下绝大多数
决策放弃搜索，评测也不会中断/报错）。部署时建议按「关键决策数 × 预算」估墙钟，
而不是按成功调用的平均延迟。

## 5. 结论：最小可用 K 与部署建议

- **按名次/耗时**：最小可用 K = **1（greedy）**。它是 128 局上最好的臂，成本也最低。
  但它是确定性的：同一个根状态只给一个可能世界，**不能报告不确定性**。
- **按方差可接受**：K=2 只能把相对 SE 降到 0.34，K=4 到 0.30；到 10% 需要
  K≈36。⇒ **K∈{2,4} 不是「方差可接受」的 K**，只是「能动起来」的 K。
- **部署建议**：
  1. 若目标是「比 π_base 强」：K=1 greedy + `--infer-search-max-ms` 兜底即可；
  2. 若目标是「搜索标签用于蒸馏」：需要 **K≤4 + 自适应采样**（只在 top-2 Q 差
     小于 SE 的决策上追加 K，而不是全局 K=32），否则 8–16× 叶计算买不到名次；
  3. 真正的随机性感知（POMC/粒子）需要引擎提供 **RNG 重播种或隐藏状态采样 API**；
     当前「逐副本动作采样」只近似了「未来随机性」，没有采样对手隐藏信息（对手
     仍由引擎 bot 的确定策略推进）。这是本实现最重要的边界，见 §1.2。
- **是否作为 s18 主线**：作为**评测期搜索**的默认口径（K=1 或 2）可以保留；作为
  「靠 Monte-Carlo 平均提升名次」的路线，本表不支持（K=2/4 无增益、成本线性）。

## 6. 复现

```bash
bash runs/stoch_search/run_k.sh          # off / K=1 greedy / K=1 sample / K=2 / K=4
python scripts/stoch_search_summary.py --dir runs/stoch_search \
    --out runs/stoch_search/SUMMARY.json
```
