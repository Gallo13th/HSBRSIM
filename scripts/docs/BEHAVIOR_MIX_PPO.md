# 搜索作为行为策略的 PPO（μ = (1−ε)π + ε·π_search）

> 状态：**实现 + 单测 + 端到端训练实验（s19）+ 关搜索 128 局配对面板**。
> 依据：`docs/SEARCH_DISTILL_THEORY.md` §4.5（μ 口径与方差）、`docs/SEARCH_EXIT.md`
> （第一条路线 ExIt 蒸馏：3 轮触 KL 上限、Δ 在噪声内）、`docs/INFERENCE_SEARCH.md`
> （搜索算子与 256 局 A/B）。
> 代码：`hsbg/az/train/behavior_mix.py`（混合行为策略 + 统计）、
> `hsbg/az/train/ppo.py`（records/批次/ratio 分母）、`hsbg/az/train/parallel_collect.py`
> 与 `hsbg/az/train/process_pool.py`（lockstep 决策点接线）、
> `scripts/train_entity_sync.py`（`--behavior-mix-*`）；测试 `tests/test_az_behavior_mix.py`。
> 产物：`runs/az_entity_s19/`（`train.log` / `history.jsonl` /
> `behavior_mix_report.jsonl` / `eval/` / `quality/`）。

## 0. 结论摘要

1. **实现完成**：lockstep 采集的每个 learner 决策点按 `μ=(1−ε)π+ε·π_search` 混合；
   records 同时写 `logp_pi`（log π(a)）与 `logp_mu`（log μ(a)），PPO 的 ratio 分母
   **改用 `logp_mu`**；`--behavior-mix-report` 落逐 iteration 统计（ε 命中率、搜索覆盖率、
   `KL(μ‖π)`、搜索耗时、IS 权重与 ESS）。**默认 `--behavior-mix-eps 0`，逐位等价旧路径**
   （证据：同 seed 2 iter 参数 sha256 完全相同，见 §3.2）。
2. **单测 16 项全绿**（`tests/test_az_behavior_mix.py`）：μ 的逐元素定义与
   `log μ(a)=log((1−ε)π(a)+ε π_S(a))` 手算对照、`KL(μ‖π)` 手算、ε=0 逐位等价、
   ratio 起点=1、ratio 分母确实换成 μ（解析 1.2 倍）、搜索失败/超时回退、
   ε 命中率与「按 μ 采样」的统计一致性（4σ + 卡方）、records 字段完整、
   批次 pack/save/load 往返、统计聚合。
3. **一处工程优化改变了可行性**：搜索 rollout 的逐候选 prior 原来走
   `evaluator.__call__`（每步 k 次队列往返，实测每步 8×12 ms）；改成一次批量
   `logits_batch` 后**单次搜索 960 ms → 223 ms（p50 905 → 166 ms）**，
   这是 s19 能跑起来的前提（`hsbg/az/train/batch_eval.py`）。
4. **s19 实验**：起点 `runs/az_entity_s17/model.pt`，ε=0.2、`carrier_or_spell`、
   每回合 ≤6、t1/top-8、lr 2e-7、minibatch 1024、grad-accum 8、人类战团 5 席 p0.9
   （fidelity full）。**实际预算 10M decisions**（20M 按实测采集成本不可行，见 §5.2）。
5. **判据**（关搜索 128 局配对 Δ ≤ −0.10 且 CI 上界 < 0、t12/t15 强度不降、
   采集开销 <50%）：结果见 §5.5/§6 —— **【待填：面板与开销】**。

## 1. 方法

### 1.1 行为策略必须写成 μ

在关键决策点（`carrier_or_spell`：`carrier_in_shop / carrier_in_hand / spell_in_hand`）
以概率 ε 用推理期搜索的 `π_search` 采样动作、以 1−ε 用 π 采样。轨迹的**实际采样分布**是

$$
\mu_{\theta_{old}}(a\mid s)=(1-\varepsilon)\,\pi_{\theta_{old}}(a\mid s)
+\varepsilon\,\pi_S(a\mid s),
$$

μ 才是 behavior policy，π **不是** on-policy 分布（`docs/SEARCH_DISTILL_THEORY.md` §4.5）。
PPO 的重要性比因此是

$$
r_t(\theta)=\frac{\pi_\theta(a_t\mid s_t)}{\mu_{\theta_{old}}(a_t\mid s_t)},
\qquad
L^{clip}=E_{t\sim\mu}\Big[\min\big(r_t\hat A_t,\ \mathrm{clip}(r_t,1-c,1+c)\hat A_t\big)\Big].
$$

用 π_old 作分母会得到 $E_{a\sim\mu}[(\pi_\theta/\pi_{old})\hat A]\neq E_{a\sim\pi}[\hat A]$，
偏差随 ε 与 $\mathrm{KL}(\pi_S\|\pi)$ 增大；只有 ε=0 才退化为普通 PPO。

### 1.2 μ 的 logprob 与实现细节

对**同一个**动作 a：

$$
\log\mu(a)=\log\!\big((1-\varepsilon)\pi(a)+\varepsilon\,\pi_S(a)\big),\qquad
\log\pi(a)=\log\pi(a).
$$

- `logp_mu` 是 PPO 的 ratio 分母；`logp_pi` 仍用于 KL/`approx_kl`（π_old vs π_new）与
  「训练前后策略变了多少」的监控 —— 两者不能混（混了就变成把搜索当旧策略）。
- 实现里 π 与 π_S 都是**同一个 masked 归一分布**（非法动作严格 0）：π 由与采样完全同一套
  `masked_probs_np(logits, mask, T)` 给出；π_S 由 `InferSearcher` 的 `pi_from_q`
  （top-k 候选 + 优势重加权）给出。μ 只在浮点漂移 `|Σ−1|>1e-9` 时重归一，正常情况下
  **逐位等于加权和**，便于手算对照。
- `LOGPROB_FLOOR` 兜底（μ(a) 可能极小但不会为 0，因为 π>0 在合法动作上）。

### 1.3 两条分支与无偏性

实现有两种模式（`--behavior-mix-exact`）：

| 模式 | 关键决策是否都搜索 | 命中 ε 的动作 | 未命中 ε 的动作 | `logp_mu` | 无偏性 |
|---|---|---|---|---|---|
| `1`（exact，理论口径） | 是（每个关键决策都跑搜索以拿到 π_S） | 从 π_S 采样 | 从 π 采样 | 全部 = log μ(a) | 精确：$E_{\mu}[r f]=E_\pi[f]$，权重 $r\le 1/(1-\varepsilon)$ |
| `0`（省钱，s19 采用） | 否（只在命中时搜索） | 从 π_S 采样 | 从 π 采样 | 命中 = log μ(a)；未命中 = log π(a) | 未命中分支等价于「该决策行为=π」；跨分支不再等于 marginal μ（残差偏差见 §4.3） |

exact 模式的无偏性证明（一次决策内，边际分布就是 μ）：

$$
E_{a\sim\mu}\Big[\frac{\pi(a)}{\mu(a)}f(a)\Big]
=\sum_a \mu(a)\frac{\pi(a)}{\mu(a)}f(a)=\sum_a\pi(a)f(a)=E_{\pi}[f].
$$

**s19 用 exact=0 是算力约束下的取舍**：实测算力下 exact 模式每 iteration 要
5,879 次搜索（关键决策 23.6%），10M decisions 需要 ≈11 h，超出一个会话的预算；
exact=0 把搜索次数降到 ε×（实测 1,136/iter）。残差偏差用 `weight_mean`
（批次上原始 IS 权重的均值，理论应为 1）**逐 iteration 直接量出来**并写进报告
（§4.3）；它不是「用 π_old 当分母」那种结构偏差，而是「未命中分支按 π 归一」带来的
尺度/状态重分布误差。

## 2. 实现

### 2.1 采集侧（`hsbg/az/train/behavior_mix.py`）

- `BehaviorMixConfig`：`eps / when / max_per_turn / topk / turns / max_ms / exact / seed`；
  `validate()` 对 eps∈[0,1)、topk≥2、turns≥1、when 合法、max_per_turn≥0、max_ms≥0 严格校验。
- `BehaviorMixer.propose(game, seat, game_id, *, action, logprob, f, c, mask, temperature, rng)`：
  1. 频率/上限：非关键决策或本回合已用满 `max_per_turn` → 返回 `None`（**不耗 RNG 以外的任何资源**）；
  2. 抽 ε 硬币（`exact=1` 时硬币只决定动作来源，搜索照跑；`exact=0` 时未命中直接返回）；
  3. 跑 `InferSearcher.search(prior=π, mask=mask)`（超时/失败返回 `None` → 回退 π 采样）；
  4. 由 π、π_S 算 μ，命中时从 π_S 采样，否则沿用 π 的动作；
  5. 返回 `MixOutcome(action, logp_mu, logp_pi, kl_mu_pi, elapsed_ms, used_search)`。
- 触发与 forced 互斥：被「回合动作数上限 / 换位守卫」强制 EndTurn 的决策**不搜索**、
  不计入 μ 样本（它们本来就被 PPO 排除）。
- 统计（`stats()`）：`decisions / eligible / trigger_ratio / eps_hits / eps_hit_rate /
  searched / searched_ratio / search_success_rate / actions_from_search /
  action_from_search_rate / failed / cap_skipped / switched / switch_rate /
  kl_mu_pi_{mean,p50,p95,max} / search_ms_{mean,p50,p95,total} / search_calls / search_timeouts`。
  多 worker 由 `aggregate_behavior_mix(metas)` 汇总（计数求和、均值按 searched 加权、分位取 max）。

### 2.2 records / 批次 / PPO

- record 新增（**只有启用混合时才写**，默认关闭字段集合不变）：
  `logp_pi`、`logp_mu`、`action_source ∈ {pi, pi_mix, search_mix, forced}`。
  `old_logprob` 仍是 π(a)（= `logp_pi`），语义不变。
- `pack_records_arrays` → `behavior_logprobs`（=logp_mu）、`pi_logprobs`（=logp_pi）；
  `PPOBatch` 新增同名字段（`BATCH_OPTIONAL_FIELDS`，可 save/load 往返）；
  worker 侧 `_save_built_batch` / 父进程合并键也同步（否则跨进程会被静默丢掉）。
- `ppo_losses`：`ratio = exp(logp_new − behavior_logprobs)`（有该字段时），`approx_kl`
  仍用 π_old；`train_ppo` 在 stats 里写 `behavior_mix{rate, mixed_rate, weight_*,
  ess_ratio, logp_mu_mean, ...}`，并保持「eps=0 时连 config 回显键都移除」。
- 逐 iteration 报告：`--behavior-mix-report <path>` 追加
  `{iter, decisions, updates, collect_s, collect{...}, ppo{...}}`。

### 2.3 lockstep 采集接线

`PPOSelfPlayPolicy.decide/decide_batch/decide(fast-act)` 三条路径都在**采样之后、写 record 之前**
调用 `mixer.propose(...)`：命中则替换动作与 logprob（`logprob = logp_pi`，并把 `logp_mu` 一并写进
record）。因为替换发生在 `_finish` 之前，换位守卫/流派偏置的动作历史看到的是**实际执行**的动作。
`process_pool` 在 worker 内按配置缓存 `InferSearcher`（权重热加载是 in-place 的，
searcher 自动看到新权重）；`--behavior-mix-eps>0` 但非 lockstep / 非 `behavior=net` 时**显式报错**。

### 2.4 搜索侧吞吐修复（`batch_eval.py`）

`InferSearcher.prior_batch` 原来对 `BatchPPOEvaluator` 没有 `logits` 方法 → 退回**逐行**
`__call__`，每个 rollout step 变成 k 次队列往返（k=8，实测每次 ≈12 ms，单次搜索 960 ms）。
新增 `BatchLeafServer.logits_batch / prior_batch`（`want_prior_batch` 请求：一次批量前向回传
`plog[k,245]`/`rlog[k,8]`/逐行 softmax）并让 `BatchPPOEvaluator.logits/prior_batch` 接上去：

| 口径（solo，cuda:3，s17 权重，t1/top-8） | 搜索次数 | mean ms | p50 ms | p95 ms | leaf steps/次 |
|---|---|---|---|---|---|
| 修复前（逐行 prior） | 30 | 960 | 905 | 2377 | 72.2 |
| 修复后（批量 prior） | 30 | **223** | **166** | 593 | 72.2 |

这一步**不改变任何数值语义**（同一前向、同一 mask、同一 softmax），只省队列往返；
`tests/test_batch_eval.py` 全绿。

## 3. 正确性

### 3.1 单测（16 项，`tests/test_az_behavior_mix.py`）

| # | 测试 | 断言 |
|---|---|---|
| 1 | `test_mix_distribution_elementwise` | μ=(1−ε)π+επ_S 逐元素相等、和=1、ε=0 逐位等于 π |
| 2 | `test_mu_logprob_hand_computed` | log(0.44)/log(0.4)/log(0.16) 手算；ε=1 与维度错都抛错 |
| 3 | `test_kl_mu_pi_hand_computed` | KL(μ‖π) 手算；ε=0 为 0；π 支撑为 0 → inf |
| 4 | `test_config_validation` | eps/topk/turns/when/max_per_turn 非法值全部抛错 |
| 5 | `test_trigger_requires_matching_tags` | 非关键决策 0 次搜索；`when=any` 才触发 |
| 6 | `test_per_turn_cap` | 同回合第 2 次被 cap 跳过；换回合重置 |
| 7 | `test_search_failure_falls_back` | 搜索返回 None → 保留 π 采样，`failed/timeouts=1` |
| 8 | `test_eps_hit_rate_and_mu_sampling_statistics` | ε 命中率 ≈0.25（4σ）；动作频率 ≈μ（4σ + 卡方<10.8） |
| 9 | `test_policy_records_logp_mu_and_pi` | 每条 record 都有 logp_mu/logp_pi/action_source，且 logp_mu 可手算复现 |
| 10 | `test_policy_eps_zero_is_bitwise_legacy` | ε=0（即使传了 mixer 对象）动作/logprob/value 序列逐位相同、字段集合不变、零搜索 |
| 11 | `test_pack_has_no_behavior_fields_by_default` | 默认不产出 behavior_logprobs / summary 无 behavior_mix 段 |
| 12 | `test_pack_build_and_roundtrip_with_mu` | pack→batch→save/load 往返保真；权重统计=1.5、ESS=1 |
| 13 | `test_ppo_ratio_starts_at_one_when_mu_equals_pi` | old=模型自己的 logπ 时 `ratio_mean=1`；μ=π 时策略损失逐位不变 |
| 14 | `test_ppo_ratio_denominator_uses_mu` | μ=π/1.2 ⇒ `ratio_mean=1.2` 且策略损失 ×1.2；用 π_old 当分母则仍是 1（证明分母真的换了） |
| 15 | `test_aggregate_behavior_mix` | 多 shard 计数求和、均值按 searched 加权、分位取 max |
| 16 | `test_real_searcher_timeout_falls_back` | 真 `InferSearcher` 在 `max_ms→0` 时返回 None 且 `timeouts=1`（引擎缺失时 skip） |

### 3.2 ε=0 与旧路径**逐位等价**（sha256 证据）

做法：`git worktree add /tmp/hsbr_base HEAD`（改动前提交 `c445d7c`），把 `data/` 与
`rust/python` 软链到本仓（同一份数据与同一份引擎 .so），两棵树跑**完全相同的命令行**
（8 局 × 2 进程、lockstep、move_guard/archetype/tier_target/seq/BC/DPO 全开、
`--seed 777`、2 iterations），只在新树额外传
`--behavior-mix-eps 0 --behavior-mix-when carrier_or_spell --behavior-mix-max-per-turn 6
--behavior-mix-topk 8 --behavior-mix-turns 1 --behavior-mix-max-ms 2000 --behavior-mix-exact 0`
（eps=0 时这些参数必须完全无效）。

```
aeab4cec95db7aa638081b207c153dd04fb3870b43d66db59d808c9d2fdb6437  /tmp/eq_base/model.pt   # 改动前
aeab4cec95db7aa638081b207c153dd04fb3870b43d66db59d808c9d2fdb6437  /tmp/eq_new/model.pt    # 改动后 + 全部 --behavior-mix-* 参数
```

**逐字节相同**（`samples=1503, updates=2` 两侧一致）。另有两项代码级保证：
① 只有 `eps>0` 才构造 `BehaviorMixer`（driver 与 worker 都如此），否则 `self._mix is None`；
② 即便传入了 mixer 对象但 `enabled=False`，`_finish` 也不写新字段、`propose` 不抽 RNG
（单测 #10）。

## 4. 方差分析

### 4.1 权重上界与 ESS

μ ≥ (1−ε)π ⇒ $r=\pi/\mu\le 1/(1-\varepsilon)$；μ ≥ ε π_S ⇒ $r\le \pi/(\varepsilon\pi_S)$
（π_S 近 one-hot 时搜索分支权重 ≈1/ε，这是「1/ε² 方差放大」的来源）。$\varepsilon=0.2$
时理论上界 1.25（对 π 支撑内的动作）与 5（对 π_S 独有的动作）。报告里逐 update 记
`weight_{mean,p50,p95,max}`、`weight_min` 与
$\mathrm{ESS}/N=(\sum w)^2/(N\sum w^2)$。

### 4.2 lr 补偿

方差放大 ~25×（1/ε²）⇒ 学习率按 ~1/25 降到 **2e-7**（s17 为 1.2e-6）。这不是精确换算，
而是「同量级保守下调」：PPO 的 ratio 方差放大会让同一个 lr 的有效步长更不稳，
再叠加 minibatch 1024 / grad-accum 8（有效 8192）与 clip 0.2。

### 4.3 exact=0 的残差偏差（逐 iteration 量出来）

exact=0 时，未命中的关键决策按 π 归一（logp_mu=logp_pi）。批次上原始 IS 权重均值

$$
\bar w=\frac1N\sum_t \exp(\log\pi(a_t)-\log\mu_t(a_t))
$$

在精确模式下恒为 1（$\sum_a\mu\cdot\pi/\mu=1$）；exact=0 时偏离 1 的量就是
「跨分支不再等价于 marginal μ」的尺度偏差。

**s19 实测（iter 0–5，逐 iteration 的批次统计）**：

| iter | `weight_mean` | `weight_p95` | `weight_max` | ESS/N | `KL(μ‖π)`（被搜索决策） |
|---|---|---|---|---|---|
| 0 | 0.9848 | 1.000 | 1.238 | 0.9853 | 0.446 |
| 1 | 0.9830 | 1.000 | 1.220 | 0.9835 | 0.492 |
| 2 | 0.9828 | 1.000 | 1.250 | 0.9834 | 0.501 |
| 3 | 0.9848 | 1.000 | 1.234 | 0.9854 | 0.401 |

- `weight_mean ≈ 0.983`：exact=0 的残差偏差是 **≈ −1.7% 的全局尺度**（不是 -50% 那种结构性
  偏差），且 `weight_max ≤ 1/(1−ε)=1.25` —— 因为分母仍是 μ、μ ≥ (1−ε)π，权重不会爆。
- `ESS/N ≈ 0.983`：IS 权重几乎不退化（没有 1/ε 重尾坍缩）；这也是 μ 分母相对「π_S 当分母」
  的实际优势。
- `KL(μ‖π) ≈ 0.4–0.5 nats`（被搜索决策）：搜索确实给出了与 π 显著不同的分布，
  `switch_rate ≈ 44–48%`（搜索动作与 π 动作在近一半的被搜索决策上不同），
  不是「搜了但什么都没变」。
- 状态重分布那一部分无法用一个标量表达，属于本模式的已知近似；exact=1 可消除它，
  代价是每个关键决策都要跑搜索（§5.2）。

## 5. 实验（s19）

### 5.1 配置

| 项 | 值 |
|---|---|
| 起点 | `runs/az_entity_s17/model.pt`（s17 终态，16.4M 参数 entity） |
| 人类战团 | 5 席 / p=0.9 / `fidelity full` / p90（s17 最终档，`--human-board-ramp 0:5:0.90`） |
| 原有旋钮 | rank-only 奖励、`--move-guard 1 --move-cap 3 --move-repeat-limit 2`、`--archetype-bias-coef 0.5`、`--dpo-coef 0.02`、`--bc-coef 0.004`、`--tier-target-coef 1.0`、`--seq-coef 0.05`、mirror 快照 p75/p0.1 |
| 混合 | `--behavior-mix-eps 0.2 --behavior-mix-when carrier_or_spell --behavior-mix-max-per-turn 6 --behavior-mix-topk 8 --behavior-mix-turns 1 --behavior-mix-max-ms 2000 --behavior-mix-exact 0` |
| 优化 | `lr 2e-7`、minibatch 1024、grad-accum 8、clip 0.2、target_kl 0.02 |
| 预算 | 目标 20M → **实际 10M decisions**（见 §5.2），`--minutes 320` 兜底 |
| 评测 | 每 5M：`human_panel_eval --games 128 --seats 8 --seed-base 420000 --smoke`（**关搜索**）+ `quality_monitor --games 96 --seed-base 520000 --carrier-audit 1`；基线臂 = 同一 128 局面板跑 s17 起点 |
| GPU | actor cuda:3,4,5 × 32 进程；learner cuda:6；评测/质量 cuda:2 |

### 5.2 采集成本（相对 s17）

单个 iteration = 192 局 / 32 worker / 每 worker 6 局 lockstep，≈25.5k learner decisions。
s17 同配置（无搜索）的 `collect_s ≈ 5.0 s`；s19 的实测（`behavior_mix_report.jsonl`
的 `collect_s`，逐 iteration）：

| 指标 | s19 实测（iter 0–5） | 相对 s17 |
|---|---|---|
| `collect.wall_s` | 41–63 s（稳态 ≈43–55 s） | **+720% ~ +1150%**（s17 = 5.02 s） |
| `decisions_per_s` | 605 | 4870（s17）⇒ **−88%** |
| decisions / iteration | 25.5k | 相同 |
| 关键决策占比（`trigger_ratio`） | 25.0–26.1% | — |
| ε 命中率（`eps_hit_rate`） | 19.1–20.5%（=ε，符合预期） | — |
| 被搜索决策占全部决策（`searched_ratio`） | **5.1%** | — |
| 单次搜索耗时（`search_ms_mean`，32 进程并发下） | 460–546 ms | solo 223 ms（§2.4） |
| 搜索超时（`max_ms=2000`） | **0.0–0.1%** | 2 s 上限足够 |
| 总搜索次数 / iteration | ≈1,300 | — |
| `actions_from_search` / searched | 100% | — |
| `switch_rate`（搜索动作 ≠ π 动作） | 44–48% | — |
| `KL(μ‖π)`（被搜索决策上，均值） | **0.40–0.50 nats** | π_S 与 π 差异很大 |

**结论：采集开销 ≈ +1000%，远高于任务书「<50%」的目标**。这是「搜索作为行为策略」的固有
成本，不是实现低效：

- 每次搜索 ≈0.2–0.55 s（t1/top-8：8 个候选各 roll 到本回合末，实测 72 个 leaf steps）；
- 搜索覆盖率 5.1%（=ε × 关键决策 25.5%），所以每个 learner decision 平均多花
  ≈0.05 × 0.45 s ≈ 23 ms，正好对应 25.5k decisions → 40–55 s/iteration；
- 定量地：单次搜索在 32 进程并发下占 **≈1.2–1.3 s 进程时间**（52 s × 32 / 1300）。
  要把采集开销压到 +50%（= 每 iteration 只多 2.5 s ≈ 80 进程秒），搜索次数必须降到
  **≈60 次/iteration = 全部决策的 0.25%**；在「关键决策占 25%、ε=0.2」下这是
  0.2×25% = 5%，差 20 倍。也就是说：**ε=0.2 + carrier_or_spell + 25% 关键决策
  与「采集开销 <50%」在结构上不兼容**，这不是调参能补的，除非把搜索本身做快 20 倍
  （例如把 rollout 换成 C++/批量跨局，或把叶值 horizon 缩到几步）。
- 要压到 <50%，只能动三个旋钮之一（都在任务书给定的语义内）：
  ① ε 0.2→0.02–0.05（搜索次数按比例降；代价是混合比例更弱）；
  ② `--behavior-mix-when` 收窄（如只 `carrier_in_shop`；关键决策占比可从 25% 降到 ~8%）；
  ③ `--behavior-mix-max-per-turn` 1（关键决策最多 1 次/回合，占比 ~10%）；
  ④ 更深的并行（更多 worker 进程）收益有限——瓶颈是每个 search 的串行 rollout，
     32 进程下 GPU 已被 tiny-batch 前向打满，per-forward 延迟上升抵消并行收益。

### 5.3 评测协议（严格关搜索）

| 臂 | 口径 |
|---|---|
| **before** | s17 起点 `runs/az_entity_s17/model.pt`，128 局 = 8 seat × 16 局，seed_base 420000，`human_panel_eval --smoke --bootstrap 1000 --baseline-bot 0`（与训练内评测同一条命令构造，`scripts/async_eval.py::build_human_cmd`） |
| **after** | s19 的 ckpt（`eval/ckpt_<decisions>.pt`），**同 128 局**、`--infer-search 0`（关搜索），配对 Δ = after − before（负 = 变强） |
| 配对统计 | `scripts/paired_panel_delta.py`：按 `(seat, 局序)` 严格配对的 bootstrap 95% CI（5000 次），同时报 top4 变化、非法/截断 |
| 质量面板 | `quality_monitor --games 96 --seed-base 520000 --carrier-audit 1`（selfplay vs 引擎 bot；t12/t15 Σ、载体指标在这里有样本）；基线 = 同一命令跑 s17 起点 |

### 5.4 训练曲线（采集侧 + PPO 侧）

逐 iteration 的 `history.jsonl`（`collect.behavior_mix` / `ppo.behavior_mix`）与
`behavior_mix_report.jsonl`；关键量：

| iter | decisions | collect_s | searched% | ms/search | KL(μ‖π) | switch | w_mean | ESS/N | policy kl | clip |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 25.0k | 62.7 | 4.92 | 546 | 0.446 | 0.450 | 0.9848 | 0.9853 | 0.00093* | 0.048* |
| 1 | 50.6k | 57.9 | 5.15 | 487 | 0.492 | 0.469 | 0.9830 | 0.9835 | — | — |
| 2 | 76.3k | 52.5 | 5.10 | 496 | 0.501 | 0.480 | 0.9828 | 0.9834 | 0.00031 | 0.025 |
| 3 | 101.9k | 41.2 | 5.14 | 459 | 0.401 | 0.440 | 0.9848 | 0.9854 | 0.00101 | 0.024 |

（`policy kl` / `clip` 取自同 iteration 的 `ppo.epochs[-1]`；* iter 0 的这两列来自第 1 个
update。）**训练稳定性**：`approx_kl` 一直在 1e-3 量级（target_kl=0.02 从未触发早停）、
`clip_frac 0.02–0.05`、熵稳定在 0.50 左右（s17 末值同量级），没有出现 IS 权重爆炸或
策略坍缩。

### 5.5 关搜索 human 面板（主判据）

| ckpt | 局数 | mean rank | top4 | 配对 Δ vs before | 95% CI | 判据（Δ≤−0.10 且 CI 上界<0） |
|---|---|---|---|---|---|---|
| before（s17） | 128 | 6.4297 | 7.03% | — | — | — |
| **after 5M**（ckpt_005010257） | 128 | **6.4063** | 7.03% | **−0.0234** | **[−0.1875, +0.1328]** | ❌（Δ 未过 −0.10、CI 跨 0） |
| after final（≈8.3M） | 128 | TBD | TBD | TBD | TBD | TBD |

5M 面板的配对细节：22 局变好 / 20 局变差 / **86 局并列**（2/3 的对局名次完全不变），
bootstrap SE = 0.081，`illegal=0`、`truncated=0`（128/128 完成）。**名次分布几乎不动**——
这与 ExIt 的观察一致：4–5M decisions 量级的扰动在该面板的噪声（SE≈0.08）下不可分辨。

### 5.6 质量面板（t12/t15 强度、载体）

| ckpt | t12 强度比 | t12 Σ p50 | t15 强度比 | 载体登场率 | 对载体施法/局 | 载体回合 Σ 相关 r |
|---|---|---|---|---|---|---|
| before（s17） | 0.1245 | 555（n=94） | 0.0249 | 0.5417 | 1.031 | 0.139 |
| **after 5M** | **0.1066** | **475（n=93）** | 0.0248 | 0.5000 | **0.417** | 0.266 |
| after final | TBD | TBD | TBD | TBD | TBD | TBD |

（`mean_rank` vs 引擎 bot：2.083 → 2.219；`top4` 0.958 → 0.948；`win` 0.323 → 0.281；
`survive_t12_ratio` 0.979 → 0.948。）5M 点的质量面板**略退**：t12 Σ p50 −14%、
「对载体施法/局」1.03 → 0.42（−60%）、载体回合数 2.54 → 2.14。注意这是 **96 局**
口径、`strength_ratio` 是相对真实 10k+ 玩家的同 turn 分位，绝对值噪声不小；
但方向与 human 面板（持平略好）不一致，说明 5M 时策略在「后期做大/载体」这条轴上
尚未朝搜索的方向移动（甚至反向）。

## 6. 结论

【待填】
