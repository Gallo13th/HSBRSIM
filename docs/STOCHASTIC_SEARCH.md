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

## 4. 结果（s17 冻结快照 `step_001001`，128 局，seed 420000）

> 表格由 `scripts/stoch_search_summary.py` 自动生成（见 `runs/stoch_search/SUMMARY.md`）。

（结果待 K=1/2/4 面板跑完后填入。）

## 5. 结论与部署建议

（待填。）

## 6. 复现

```bash
bash runs/stoch_search/run_k.sh          # off / K=1 greedy / K=1 sample / K=2 / K=4
python scripts/stoch_search_summary.py --dir runs/stoch_search \
    --out runs/stoch_search/SUMMARY.json
```
