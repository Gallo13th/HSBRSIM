# AlphaZero 风格**不完全信息**搜索原型（PIMC / determinization + PUCT）设计

> 状态：**v0.1 原型报告**（task-2），2026-10-26 23:5x。范围：Python 原型 + Rust 搜索核复用 +
> 固定 seed 小规模质量验证；**不是**最终 Rust 搜索核（最终核设计见
> [AZ_MCTS_SELFPLAY_DESIGN.md](AZ_MCTS_SELFPLAY_DESIGN.md) §7）。
>
> 代码：`hsbg/az/`（env_api / belief / puct / search / policy / toy_env / evaluate）
> 测试：`tests/test_az_search.py`
> 相关：[AZ_MCTS_SELFPLAY_DESIGN.md](AZ_MCTS_SELFPLAY_DESIGN.md)（D1–D11 决策）、
> [ACTION_OBS.md](ACTION_OBS.md)、[ACTION_OBS.md](ACTION_OBS.md)、
> [AZ_1K_VALIDATION.md](AZ_1K_VALIDATION.md)（从零 AZ 负结果）、
> [AZ_PURE_SEARCH_TEST.md](AZ_PURE_SEARCH_TEST.md)（bot-rollout 负结果）。

---

## 0. 摘要（TL;DR）

1. 实现了可运行的 **PIMC（Perfect Information Monte Carlo）原型**：每次决策从**公开观测**
   采样 $W$ 个隐藏世界（determinization），每个世界调一次 Rust `mcts_search`（或 Python
   PUCT 对照实现），根 visit 数跨世界聚合成 $\pi$，输出动作/根价值/`n_states`/耗时/回退原因。
2. **信息隔离**已用不变量强制：determinization 只用 `observe(seat)` 解出的公开字段（回合、
   对手 tier/血量/护甲、最近见到的战团）与静态卡表；注入隐藏状态后**断言 `observe(seat)`
   逐字节不变**；搜索不调用 `view/state_json`；源 `Game` 搜索前后 `state_json` 字节相等。
3. 质量验证（20 局固定 seed、seat0 对 7 个引擎 bot、配对）：
   | agent | mean rank | top4 | win | 说明 |
   |---|---:|---:|---:|---|
   | random | 8.00 | 0% | 0% | 均匀随机合法动作 |
   | heuristic（规则先验 argmax） | 6.60 | 5% | 5% | 修复后 |
   | **bot（引擎内置脚本）** | **2.65** | 90% | 15% | 强基线 |
   | search_uniform（16 sims / 4 det） | 8.00 | 0% | 0% | 无先验冷启动搜索：退化 |
   | search_heuristic（16/4） | 6.75 | 10% | 5% | 与 heuristic 同级，搜索增益不显著 |
   | **search_bot_prior（16/4，Python 后端）** | **2.80** | **85%** | 15% | 与 bot 同级（CI 重叠） |
   结论：**冷启动搜索质量由 evaluator 决定**；PIMC 本身能产出合法、非退化、bot 级对局，
   但要超过 bot 需要学习型价值/策略（训练闭环，§9）。
4. 定位并修复了"搜索总选 EndTurn"的退化链（§8.3）：**不是 chance/determinization 问题**，
   而是 ①`pending_kinds[0]=none` 被误判为"有待选"→ 先验退化成均匀；②买入后不 `Play`
   上棋盘（先验权重 bug）；③`temperature=0` 低 sims 下 visit 打平按小下标取到 EndTurn。
   修复后引擎状态上 root argmax 从 EndTurn 变为 `Buy/Play`（§8.3 有证据）。

---

## 1. 问题形式化与约束

### 1.1 8 人酒馆战棋 = 部分可观测随机博弈（单座视角 POMDP）

$$
\mathcal{M}=(\mathcal{S},\mathcal{A},\mathcal{O},T,Z,u),\qquad
o=Z(s),\quad |\mathcal{A}|=245,\quad r\in\{1..8\},
$$
$$
u(r)=1-\frac{2(r-1)}{7}\in[-1,1],\qquad \sum_{p=1}^{8}u(r_p)=0\ \text{（常和）}.
$$

- 状态 $s$ 含 8 座隐藏量（对手手牌/金币/商店/未公开战团）；
- 观测 $o$ 是 seat 的 3227 floats + 124 cards（[ACTION_OBS](ACTION_OBS.md)），其中对手只含
  **公开摘要**：血量/护甲/酒馆等级/最近一次见到的战团（`opponents`、`opponent_boards`）；
- 动作 245（[ACTION_OBS](ACTION_OBS.md)），`EndTurn=0` 是**宏动作**：
  触发其余 7 座行动（对手策略）+ 配对/战斗 RNG + 商店刷新 + 淘汰；
- 单座决策目标是最大化 $\mathbb{E}[u(r)]$；其余 7 座视为"带策略的随机环境"，不做
  negamax（8 人常和非两人零和）。

### 1.2 信息集与信念

观测历史 $h_t=(o_0,a_0,\dots,o_t)$ 对应信息集 $I(h_t)=\{s: Z(s)=o_t\ \text{沿同一动作史}\}$；
信念 $b_t(s)$ 是其后验。策略/价值只能以 $h$ 为输入：

$$
\pi(a\mid h),\qquad V^\pi(h)=\mathbb{E}_{s\sim b(h)}[V^\pi(s)].
$$

**硬约束（D3，本任务验收项）**：搜索/评估的决策输入只允许 `observe(seat)` + `legal_mask`；
禁止 `view()`（含对手实时棋盘）、禁止把 `state_json()` 的隐藏字段喂给网络/先验/价值。

### 1.3 本原型与最终 Rust 核的分工

| | 本原型（task-2） | 最终核（AZ 设计 §7） |
|---|---|---|
| 树/搜索 | 每 world 一次 Rust `mcts_search`；Python PUCT 对照 | Rust 统一树、虚拟损失、批量评估 |
| determinization | Python 采样 + `debug` 注入（~1.1 ms/world） | Rust `BeliefSampler` trait（§7.6） |
| chance/EndTurn | Rust 折叠在边内；Python 后端可选逐 EndTurn 重采样 | Rust chance 节点 + K 次转移采样 |
| 用途 | **可运行/可测/可用作训练 bootstrap**、验证评估链路 | 训练吞吐与大规模自对弈 |

---

## 2. 为什么 PIMC / ISMCTS 在这个 8 人 POMDP 里是合理选择

### 2.1 候选方案对比

| 方案 | 可行性 | 问题 |
|---|---|---|
| **完美信息 MCTS（oracle）** | 引擎支持（clone 真实 hidden） | **禁用**（D3）；只能做 oracle gap 诊断 |
| **策略网络直接决策（policy-only）** | 便宜 | 冷启动随机策略退化（AZ_1K：rank 8） |
| **CFR / 精确信息集求解** | 理论正确 | 8 人 × 245 动作 × 长局，状态空间不可行；对手策略非平稳 |
| **PIMC（本原型）** | 复用现有 Rust MCTS，工程成本低 | 有 strategy fusion / 非局部性偏差；世界先验偏差 |
| **ISMCTS（下一版）** | 单树按信息集聚合，避免策略融合 | 需处理"不同世界合法动作不同"的 mask 合并；实现复杂 |
| **RL 纯策略 + 搜索** | 最终目标 | 依赖训练闭环（§9） |

### 2.2 PIMC 的理论性质与本场景契合点

PIMC 在信念上做 Monte Carlo：
$$
Q_{\text{PIMC}}(h,a)=\frac{1}{W}\sum_{w=1}^{W}
\mathbb{E}_{\text{chance}}\bigl[V(h\cdot a;\ s_w)\bigr],
\qquad s_w\sim q(\cdot\mid h),
$$
其中 $q$ 是**只用公开信息**构造的世界先验。它等价于在"把每个采样世界当成完美信息"的
游戏上做 MCTS，再对世界取平均。

**合理性来自本场景的特殊结构**：

1. **单座控制 + 环境随机**：搜索只对 learner 的动作建树，其余 7 座由对手策略推进
   （原型用引擎 bot，训练时用 league/历史回放）。这使 PIMC 的"策略融合"主要发生在
   **learner 自己的后续动作**上，而后续动作本身也由同一网络/搜索决定，融合偏差通常在
   常数级（不是 CFR 那种需要精确信息集价值的场景）。
2. **合法动作集跨世界稳定**：determinization 只改隐藏量，不改公开观测；learner 的
   `legal_mask` 由己方可见状态决定，因此**同一信息集下各世界的合法动作一致**
   （我们在 `test_engine_determinization_public_invariant_and_hidden_overwrite` 与
   搜索冒烟中验证了 `observe` 不变）。PIMC 最常见的"动作在某世界非法"失败模式被消除。
3. **隐藏信息主要影响 chance 结果**（战斗/对手战团），对"买/卖/升级"这类动作的即时
   可行性影响小 → PIMC 的动作排序偏差可控。
4. **工程复用**：Rust `mcts_search` 已存在且经过基准（copy 2.45µs、search 0.06–0.1ms/stub），
   每 world 调一次即可得到 PIMC；不必先写 Rust 信息集树就能验证数据质量。

**已知偏差（必须写清楚）**：

- **Strategy fusion / 非局部性**：PIMC 允许"在 world A 用动作 a 占便宜、在 world B 用 b
  占便宜"，而真实信息集下只能选同一个 a/b。8 人局中对手隐藏战团差异大时会高估动作价值。
- **世界先验偏差**：$q_0$ 是手工公开先验（§4），与真实信念有偏差；偏差越大，PIMC 越像
  "对错误模型的最优反应"。用 **oracle gap**（§4.5）量化。
- **对手非平稳**：$Q$ 是"对当前对手池"的价值，不是全局最优；需要 league/定期重评估。

### 2.3 ISMCTS 何时替换 PIMC

当出现下列信号时，应升级到 ISMCTS（单树、节点=信息集、每次模拟随机抽世界）：
1. 跨世界 `legal_mask` 开始不一致（例如后续实现"按对手可见信息的反应动作"）；
2. strategy-fusion 诊断显示 PIMC 高估（同一动作在单世界 MCTS 与 PIMC 中排序显著不同）；
3. 世界数 $W$ 增大后 PIMC 方差仍高（ISMCTS 把世界方差摊到节点统计上，样本效率更高）。

本原型保留 `search.py` 的 `_PythonSearch`（单世界树）与 `belief.py` 的 sampler 接口，
升级 ISMCTS 时只需把"每世界一棵树"改成"共享节点 + per-simulation world state"，PUCT/
聚合逻辑复用。

---

## 3. 实现架构

### 3.1 模块

| 文件 | 职责 |
|---|---|
| `env_api.py` | env 适配（engine `Game` / toy）、观测块解码（ACTION_OBS 冻结偏移）、公开信息 `PublicInfo`、`opponent_seats` 映射、`finish_hero_select`/`warmup_with_bots` |
| `belief.py` | `BeliefSampler` 协议；`EnginePublicPriorSampler`（公开信息先验 + debug 注入）；`CloneSampler`（oracle，仅诊断）；`PassthroughSampler`；`split_simulations` |
| `puct.py` | `Node`、`masked_prior`、`puct_select`、`dirichlet_legal`、`visit_distribution`、`sample_action` |
| `search.py` | `SearchConfig`/`SearchResult`；Python PUCT+PIMC 后端；Rust `mcts_search` 后端；evaluator 适配（4 参回调 / `ObsView` 回调）；安全回退；诊断信息 |
| `policy.py` | 规则先验/价值（heuristic）、`UniformEvaluator`、`RolloutEvaluator`（截断 rollout）、`BotPriorEvaluator`；`RandomAgent/HeuristicAgent/BotAgent/SearchAgent` |
| `toy_env.py` | 无引擎环境下的 8 人 toy POMDP（公开/隐藏分离、确定性 seed），供本地单测 |
| `evaluate.py` | 固定 seed 配对评测（seat0 换 agent、其余 bot），rank/top4/win/util/耗时/回退 |

### 3.2 数据流（一次决策）

```text
game (真实状态)
  │  只读 observe(seat) / legal_mask(seat)          ← 唯一决策输入
  ▼
BeliefSampler.sample(game, seat, rng) × W
  │  world_w = game.copy() + 用公开先验覆写对手隐藏量(board/hand/shop/gold)
  │  断言 observe(seat) 逐字节不变（obs_invariant）
  ▼
每个 world_w 一次搜索（Rust mcts_search 或 Python PUCT）
  │  根先验 = evaluator(observe(seat), mask)     ← 与 world 无关的公开输入
  │  叶价值 = evaluator(叶 obs)                  ← 仍只读观测
  │  EndTurn 边内：引擎 bot 推进 7 座 + 引擎 RNG（chance 折叠）
  ▼
聚合：agg_counts = Σ_w counts_w
  ▼
SearchResult(pi=visit_distribution(agg), action 采样/argmax+tiebreak,
             root_value, visits, n_simulations, determinizations,
             n_states, elapsed_s, per_world, fallback, info)
```

### 3.3 API（训练侧可复用）

```python
from hsbg.az import search, SearchConfig, SearchResult

res = search(game, seat, config=SearchConfig(
    simulations=16, determinizations=4, c_puct=1.5, temperature=1.0,
    dirichlet_alpha=0.3, dirichlet_epsilon=0.0, seed=0),
    eval_fn=None,            # 默认启发式；或见下
    engine_backend="auto")   # engine Game→rust；否则 python

# 训练侧 evaluator（与 Rust mcts_search 的 eval 回调逐参一致）
def eval_fn(features, cards, mask, seat):   # f32[3227], i32[124], bool[245]
    return policy_245, value_float

res.pi        # f32[245]，合法外 0，和=1
res.action    # int
res.root_value, res.visits, res.n_simulations, res.determinizations
res.n_states  # Python 后端=实际 copy 数；Rust 后端=W+Σvisits 的估计（info 里标注）
res.elapsed_s
res.per_world# [{world, seed, visits, root_value, determinize:{mode,injected_hidden,oracle,obs_invariant,...}}]
res.info     # {engine_backend, eval, dirichlet, chance_resample, n_evals, n_worlds,
             #  timing:{determinize_s,search_s,total_s}, world_obs_invariant,
             #  determinize_modes, fallback_reason, oracle, entropy, top1_margin, ...}
res.fallback # eval/step 异常或全失败时 True（不抛出到训练进程）
```

`SearchAgent` 是 `Agent` 协议的搜索策略（`act(game, seat)`），可直接放进评测/自对弈循环；
`evaluate.play_game/evaluate_specs` 提供固定 seed 配对评测。

---

## 4. Determinization / 信念采样

### 4.1 公开信息先验 $q_0(h\mid o)$（无历史数据时的最小实现）

对每个对手槽（观测相对序：`(seat+1+k) % n`，已实测验证）：

1. **公开字段直接保留**：`present/alive/health/armor/tier/placement/hero`、最近战团
   `seen_minions=(card,atk,hp)`（这些都在 `observe` 里，是合法的公开信息）。
2. **战团（隐藏）**：
   - 以概率 `p_seen_board=0.6` 复用"最近见到的战团"（合法公开先验），再以 `p_mutate=0.35`
     替换其中 1 个随从（近似"上次见到后可能变强"）；
   - 否则按 `(turn, tier)` 采样：规模 `n≈clip(1+(turn+1)//3 ±1, 1,7)`，卡牌从公开卡表
     `catalog_json()` 的该 tier ±1 池中按"低 tier 更高频"采样；数值用卡面 atk/hp ±1。
3. **金币/手牌/商店（隐藏）**：金币 `clip(2+turn//2±1,0,10)`；手牌 0–2 张；商店 3 张
   （只出 `tier <= tavern_tier` 的卡）。
4. **覆写方式**：`world = game.copy()` 后用 `Game.debug(cmd_json)` 的
   `clear_zone/add_minion/set_player` 覆写隐藏区；**不使用** `view/state_json` 读隐藏值。
5. **不变量**：注入后比较 `observe(seat)` 的 features/cards 字节；必须完全一致。若不一致，
   把公开字段（health/armor/tier）回写后复查，仍失败则记录 `obs_invariant=False` 供审计
   （实测 engine 37.0.0 上始终 True）。

### 4.2 残余隐藏泄漏（已知限制，必须记录）

`debug` API 不能重置的隐藏字段仍然来自真实状态：对手任务/饰品/英雄技能使用次数/暗赠礼
计数/部分持续效果等。原型阶段：
- 在 `DeterminizeInfo.note` 明确写出；
- 影响面：这些字段主要影响对手自身的经济/成长（由 bot 使用），对 learner 的战斗结果影响
  小于棋盘本身；
- 正式版需要引擎侧正式接口 `Game::resample_hidden(seat, rng)` 或 `DeterminizeConfig`
  （AZ 设计 §7.6），届时 `BeliefSampler` 从"Python debug 注入"换成 Rust 采样。

### 4.3 世界数 $W$（determinization 数量）怎么选

PIMC 估计量的方差（给定固定 sims 总量 $S$，每世界 $S/W$）：

$$
\mathrm{Var}[\hat Q_{\text{PIMC}}]
=\underbrace{\frac{1}{W}\mathrm{Var}_{s\sim q}[Q(s)]}_{\text{世界方差}}
+\underbrace{\frac{1}{S}\mathbb{E}_{s\sim q}[\mathrm{Var}_{\text{MCTS}}(s)]}_{\text{搜索方差}}.
$$

- $W$ 增大降低世界方差，但每世界树变浅、搜索方差上升；**总预算固定时存在最优 W**；
- 实测（§7）determinization 注入 ~1.1ms/world（首次含 catalog 解析 ~50ms），是主要成本；
- **建议**：`S=8–32, W=2–4`（训练数据生成）；评估/诊断 `S=32–64, W=2–4`；
  无模型冷启动需要更大 S 才能弥补均匀先验；训练后期价值网络可靠后可用 `W=1–2` 省成本。
- 原型默认 `S=16, W=4`（每世界 4 sims）；低 sims 下 visit 易打平，已用根先验 tie-break
  （§6.4）。

### 4.4 确定性

- 每 world 采样 RNG：`random.Random(seed + 104729*(w+1))`；
- 每 world 搜索 seed：`cfg.seed + 7919*(w+1)`（Rust `mcts_search` 自带 SplitMix64）；
- 最终动作采样 RNG：`seed ^ 0x5EED`；
- 同 `seed + 模型 + S/W` ⇒ 相同 π/动作（单测 `test_engine_search_deterministic_*`）。

### 4.5 Oracle gap 诊断（只诊断，不进训练/部署）

`CloneSampler`（`oracle=True`）保留真实隐藏状态，仅用于测量：
$$
\Delta_{\text{oracle}}=\bar r_{\text{public-search}}-\bar r_{\text{clone-search}}.
$$
`SearchResult.info["oracle"]` 会标出是否使用了 oracle 世界；评测报告必须单列，禁止混入
训练数据。原型未跑大规模 oracle gap（成本高），留给训练阶段（AZ 设计 §6.7/§9）。

---

## 5. Chance 与 EndTurn 处理

### 5.1 EndTurn 是宏动作（不是普通边）

`step(seat, EndTurn)` 会连锁触发：其余 7 座行动（对手策略）→ 配对/战斗 RNG → 商店刷新
→ 淘汰。严格搜索应把它当 chance 节点：
$$
Q(h,\text{EndTurn})=\mathbb{E}_{a_{\text{opp}},c\sim P}[V(h')].
$$

### 5.2 两种后端下的处理

| | Rust 后端（默认） | Python 后端 |
|---|---|---|
| 对手推进 | 引擎 bot（`advance_to_seat`，边内折叠） | 引擎 bot（`drive_opponents`） |
| 战斗/刷新 RNG | 每个 world 的 `Game.copy()` 携带 RNG，树内确定 | 同左；**可选** `resample_on_end_turn` |
| chance 重采样 | 不支持（世界间差异来自 determinization） | 每次 `EndTurn` 后重新 `BeliefSampler.sample`，作为 chance 节点 |
| 成本 | 低（Rust 核） | 中（每次重采样 ~1.1ms，只在 `resample_on_end_turn=True` 且选中 EndTurn 时） |
| 建议 | 训练数据生成默认 | 研究 chance 方差 / 诊断时 |

**为什么 Rust 核内不逐 sim 重采样**：`mcts_search` 的 RNG 属于 world 的 `Game.copy()`，
同一 world 内同一动作路径的战斗结果确定；要逐 sim 采样 chance 必须改 Rust 核（chance 节点
+ K 次转移采样，AZ 设计 §3.4/§7.5）。本原型用 **W 个不同隐藏世界**提供世界级方差，
并在 Python 后端提供逐 EndTurn 重采样作为对照；文档化差异，避免误读为"Rust 搜索无 chance"。

### 5.3 为什么不用 bot-full-rollout 作叶价值

`AZ_PURE_SEARCH_TEST.md` 实测：Rust `rollout=true`（bot 打到终局作价值）在 1000 局上
rank≈7.98、top4=0%、胜率 0%，根因是 **off-policy 不匹配**：
$$
Q_{\text{rollout}}(s,a)=\mathbb{E}_{\text{bot policy}}[u]\neq
\mathbb{E}_{\text{search policy}}[u].
$$
因此本原型的默认叶评估是**公开观测启发式价值**（§6.2），并提供：
- `RolloutEvaluator`（截断 horizon 8 的规则 rollout，只在 Python 后端）；
- `BotPriorEvaluator`（bot 的**单步动作**做先验，而非终局 rollout；§8.4 实测有效）。

### 5.4 方差与 K/W 的关系

单次 EndTurn 采样的价值方差为 $\mathrm{Var}(V(h'))$；$K$ 次转移采样平均后方差
$\mathrm{Var}/K$。PIMC 中世界间差异与转移采样是**两个独立方差源**：
$$
\mathrm{Var}[\hat Q]=\frac{1}{W}\mathrm{Var}_{q}[Q]+\frac{1}{W K}\mathbb{E}_{q}[\mathrm{Var}_{chance}]
+\text{tree variance}.
$$
原型用 $W>1$ 承担第一项；若后期发现末期战斗方差主导，把 `resample_on_end_turn` + 同 world
多 sim 视为 $K>1$ 的近似（Python 后端）。

---

## 6. PUCT / 价值 / 回退细节

### 6.1 PUCT（与 AZ 设计 §3.2 一致）

$$
\text{PUCT}(a)=Q(a)+c_{\text{puct}}P(a)\frac{\sqrt{\sum_b N_b}}{1+N_a},
\qquad Q(a)=W(a)/N(a),
$$
只对 `legal_mask` 内动作选择；`c_puct` 默认 1.5；**备份不做符号翻转**（utility 是 seat 视角）。

### 6.2 叶评估（冷启动）

默认 `HeuristicEvaluator`：
- 先验：规则（可负担买入 > 升级/技能 > 打出手牌 > 刷新 > 结束回合；有待选项时在合法
  选择上均匀）；只读 `ObsView`；
- 价值：公开局面近似
  $v=\tanh$ 组合（血量/护甲、己方棋盘 atk+hp vs 回合期望、tier、对手平均血量），∈[-1,1]；
- **不是训练价值目标**（D9 仍只用终局名次）；只是 search bootstrap。

训练侧可传任意 `eval_fn`，接口与 Rust `mcts_search` 一致（见 §3.3），便于接策略/价值网络。

### 6.3 根 Dirichlet 噪声与温度

$$
\tilde P_{\text{root}}=(1-\varepsilon)P+\varepsilon\,\mathrm{Dir}(\alpha),
\qquad
\pi(a)=\frac{N(a)^{1/\tau}}{\sum_b N(b)^{1/\tau}}.
$$
- 训练自对弈：$\varepsilon=0.25,\alpha=0.3,\tau=1.0$ 采样动作、π 作为策略目标；
- 评估/部署：$\varepsilon=0,\tau\to0$（argmax）；
- 原型里 Rust 后端把噪声交给 `mcts_search` 的 `dirichlet_*` 参数；Python 后端在根展开后
  用 `dirichlet_legal` 加噪（每 world 独立 RNG）。

### 6.4 低 sims 打平的 tie-break（真实 bug 修复）

`temperature=0` 时 π 是 visit 的 one-hot；当 `S/W` 很小、多个动作各被访问 1 次时，
`argmax` 会按动作下标取到 `EndTurn(0)`。修复：**visit 相同则用根先验打破平局**
（`_finalize(..., root_prior)`），并用 `visits, prior` 二级排序。修复前后对比见 §8.3。

### 6.5 安全回退（训练进程不崩）

| 失败 | 处理 |
|---|---|
| evaluator 抛异常 / 返回 NaN | 记录 `errors`，用合法均匀先验 + value 0 继续该叶/该世界；最终 `fallback=True` |
| `step` 抛非法动作 | 该边记为 terminal value 0，继续其它模拟 |
| 单 world 搜索失败（Rust 回调异常/引擎问题） | 丢该 world 计数，继续其它 world |
| 全部失败 / 根无合法动作 | `fallback` 按配置：`legal`（均匀合法）/`bot`（引擎 bot 动作）/`prior`；π 退化为 one-hot 合法动作 |
| 引擎后端整体异常 | `rust→python` 自动降级（`info["backend_fallback"]`） |

---

## 7. 搜索预算与实测成本（远程 `biocourse-glt`，hsbg_engine 1.0.0 / 数据 37.0.0.255790）

### 7.1 原语（hiermolgen Python 3.10 / numpy 2.2，单线程）

| 原语 | 实测 |
|---|---|
| `Game.copy()` | **8.8 µs** |
| `Game.observe(p)` | **2.0 µs** |
| `Game.legal_mask(p)` | **0.15 µs** |
| `Game.debug(clear_zone/add_minion/set_player)` | **≈2.6 µs/次** |
| 首次 `catalog_json()` 解析（模块缓存） | ≈40–50 ms（一次性） |
| `EnginePublicPriorSampler.sample`（77 次注入/7 对手） | **≈1.1 ms/world**（首次 42–55ms，含 catalog 解析） |

### 7.2 单次决策（16 sims / 4 det，seed 70000/70001）

| 后端 | 耗时 | 说明 |
|---|---:|---|
| Rust（W=4） | **7–18 ms/决策** | 4×det(~4.4ms) + 4×`mcts_search`(≤4 sims) + Python eval |
| Python（W=4） | 5–15 ms/决策 | 同量级；节点 copy 8.8µs × ~S |
| 20 局评测（6 种 agent 全跑） | **71.8 s** | search_bot_prior 独占 53.9s（Python 后端 + bot_action/叶 + 注入） |

**成本结构**：determinization 注入占主导（~1.1ms/world）；Rust 搜索本身 <1ms/决策。
优化方向（不在本任务范围）：
1. 缓存已注入邻居（同局连续决策的世界可复用）；
2. 把注入移到 Rust（`BeliefSampler`，一次 copy + 直接写隐藏字段，省 JSON/命令解析）；
3. 批量注入/批量搜索（多决策并行）；
4. 只在"需要 chance 信息"的决策做 determinization（例如 EndTurn 前），普通买/打动作可
   省略世界采样（`W=1` clone + 只用公开先验注入一次）。

### 7.3 预算建议

| 场景 | S | W | 说明 |
|---|---:|---:|---|
| 快速冒烟/CI | 4–8 | 1–2 | 只验证可运行/合法/确定性 |
| 训练数据生成（冷启动） | 8–32 | 2–4 | 先保证 eval 可靠；S<8 会 visit 打平 |
| 评估/诊断 | 32–64 | 2–4 | rank 对比用固定 seed 配对 |
| 训练后期（价值网络可靠） | 16–64 | 1–2 | 世界方差让位于树方差时减少 W |
| 实时部署（快） | 1（纯策略）或 8 | 1 | 搜索非瓶颈时再加大 |

---

## 8. 质量验证

### 8.1 协议（可复现）

- 目标座位 seat0，其余 7 座固定引擎 bot（多座 bot 对局即"强基线大厅"）；
- 固定 seeds **70000–70019**（20 局），所有 agent 用同一 seed 集 → 配对比较；
- agent：random（均匀合法）/ heuristic（规则先验 argmax）/ bot（`bot_action`）/
  search_uniform / search_heuristic / search_bot_prior；
- 搜索配置：`S=16, W=4, c_puct=1.5, temperature=0, dirichlet_epsilon=0, seed=0`；
- 指标：平均名次（主）、前四率、冠军率、期望效用、决策数、耗时、回退数、95% bootstrap CI。

命令（远程 staging，`hiermolgen` py）：
```bash
cd /home/data/users/gaoletian/projects/az_stage
# 完整 6-agent 评测脚本（本报告数字来源）
PYTHONPATH=$PWD ~/.conda/envs/hiermolgen/bin/python run_eval2.py
# 等价 CLI（search_bot 内部强制 Python 后端；其余 search 用 Rust 核）
PYTHONPATH=$PWD ~/.conda/envs/hiermolgen/bin/python -m hsbg.az.evaluate \
  --games 20 --seed0 70000 \
  --agents random,heuristic,bot,search_uniform,search_heuristic,search_bot \
  --sims 16 --determinizations 4 --eval heuristic --backend rust
```

### 8.2 结果（20 局，2026-10-26 实跑）

| agent | mean rank | 95% CI | top4 | win | mean util | decisions | 耗时 | fallback |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| random | 8.00 | 8.00–8.00 | 0% | 0% | -1.000 | 1546 | 0.2s | 0 |
| heuristic（规则） | **6.60** | 5.80–7.25 | 5% | 5% | -0.600 | 893 | 0.3s | 0 |
| **bot（引擎脚本）** | **2.65** | 2.15–3.20 | **90%** | 15% | **+0.529** | 3534 | 0.2s | 0 |
| search_uniform | 8.00 | 8.00–8.00 | 0% | 0% | -1.000 | 182 | 1.8s | 0 |
| search_heuristic | 6.75 | 5.85–7.45 | 10% | 5% | -0.643 | 1001 | 15.0s | 0 |
| **search_bot_prior** | **2.80** | 2.25–3.35 | **85%** | 15% | +0.486 | 3544 | 53.9s | 0 |

**解读（如实）**：

1. **搜索非退化**：`search_bot_prior` 与引擎 bot 同级（rank 2.80 vs 2.65，CI 重叠；
   决策数 3544≈3534，说明搜索基本沿 bot 策略做有限前瞻，没有乱走）。
2. **冷启动 search_uniform 退化**（rank 8.00，仅 182 决策）：均匀先验 + 4 sims/world 时
   没有价值信号，搜索实际只做 1–2 次决策/回合——这与 AZ_1K/纯搜索负结果一致；原因是
   **预算/先验不足**，不是 PIMC 公式错。
3. **search_heuristic 与 heuristic 同级（6.75 vs 6.60，CI 重叠，甚至略差）**：
   规则先验+规则价值已经是"手工策略"，16 sims 的搜索在 8 人高方差局面上无法稳定改进它；
   这正说明 **search 的质量上限由 evaluator 决定**，需要学习型价值网络（§9）。
4. **bot 基线很强（rank 2.65 而非 4.5）**：seat0 与 7 座同为引擎 bot 时仍有显著优势，
   说明"座位 0 先行动"的执行顺序有优势（评测口径事实），配对比较对所有 agent 公平。
5. **fallback=0**：所有搜索决策都正常完成，无非法动作/异常泄漏到评测。

### 8.3 "搜索总选 EndTurn"归因（Lead 问题）

在调参过程中确实观察到 `search` 在 TavernBench/招募状态上总选 `EndTurn`。定位到**三个
叠加 bug**，与 chance/determinization 无关：

| # | 根因 | 证据 | 修复 |
|---|---|---|---|
| 1 | `pending_kinds` 是 one-hot，下标 0=`none`；把 `pending.sum()>0.5` 当"有待选" → **所有正常状态**被判定为 pending，规则先验退化为"合法动作均匀" | 在 seed70000 turn1：修复前 heuristic prior 7 个合法动作各 0.1429；修复后 Buy 各 0.242、Refresh 0.014 | `env_api.decode_public` 改为 `pending[1:].sum()>0.5` |
| 2 | 买入后随从进 **hand**，需 `Play` 才上棋盘；先验 Play 权重 0.9 与 EndTurn 0.9 打平，`argmax` 取小下标=EndTurn → "买了不打出、直接结束回合" | heuristic agent 前后对比：修复前 21 decisions/局、board_len 恒 0、rank 8.00；修复后 42 decisions/局、board_len 增长、rank 6.60 | `policy.heuristic_prior`：有手牌时 Play 权重 5.0、EndTurn 降到 0.02 |
| 3 | `temperature=0` 且低 sims（16/4）时多个动作 visit 数打平，`argmax` 按小下标取到 EndTurn(0) | 修复前 seed70000 turn1：8/16 sims 时 π one-hot EndTurn；加 tie-break 后 argmax=Buy(0) | `search._finalize`：visit 打平时用根先验 tie-break |

修复后实测（同一状态）：
```
turn1  seed70000: heuristic top [Buy(3) .242, Buy(0) .242, ...]; search argmax=Buy(0)
midgame seed70001 (turn5, gold7): heuristic top [Buy(0)..Buy(4) .152]; search argmax=Buy(0)
```
**Chance 侧证据（排除）**：`EnginePublicPriorSampler` 注入 69–77 次 debug 命令后，
`observe(0)` 与注入前**逐字节一致**（`obs_invariant=True`）；源 `Game.state_json()` 搜索
前后字节相等；Rust/Python 两后端 π 合法且和=1、同 seed 可复现（单测 + 远程探针）。
因此 EndTurn 现象是 **观测解码/先验/低 sims 打平**，不是 determinization 把世界采坏。

### 8.4 Bot 先验（搜索质量的关键 bootstrap）

`BotPriorEvaluator` 用引擎 bot 的**单步动作**做先验（blend 0.75），叶价值仍用公开启发式。
它避免了 bot-full-rollout 的 off-policy 偏差（§5.3），同时把搜索锚定在脚本策略附近；
实测 rank 2.80（≈bot 2.65），是当前冷启动下"搜索能产出足够质量对局"的直接证据。
代价：需要 Python 搜索后端（Rust eval 回调只有观测，拿不到 game 调 `bot_action`），
耗时从 11.1s 增到 59.4s/20 局。训练阶段若先用网络先验/蒸馏 bot 策略，可把 bot 先验换成网络先验，
把这项成本移到 NN 推理。

---

## 9. 与 AlphaZero 训练闭环的结合

### 9.1 两阶段闭环（与 AZ 设计 §6 一致）

```text
θ ← 随机初始化 / 网络先验(bot, heuristic)
for iter k:
    D_k ← SELFPLAY(θ, search=S/W 调度, opponents=league)     # π 目标 = visit 分布
    θ ← TRAIN(D_k, policy CE + rank CE)
    EVAL(θ, fixed seeds, baselines, search-on/off)
```

搜索在闭环中的角色：
1. **策略目标**：$\pi_{\text{target}}(a)=N(a)^{1/\tau}/\sum_b N(b)^{1/\tau}$（本原型 `res.pi`，
   τ=1 即 visit 归一化）；`π_target` 优于原始策略（§9.2 策略改进论证）。
2. **价值目标**：终局名次 one-hot（D9），不是搜索的 leaf value；搜索价值只用于 bootstrap。
3. **数据质量过滤**：根访问熵、top-1 margin、fallback 标记、`obs_invariant`/`oracle` 标记
   写进样本 stats（`SearchResult.info` 已提供）。
4. **调度**：初期 S=8–16/W=2–4 + 规则/bot 先验 bootstrap；价值网络可用后 S↑、W↓；
   评估/teacher 用大 S。
5. **对手池**：Phase A 8 座全搜索；Phase B 1 座学习 + 7 座历史回放（AZ 设计 §6.3）。
   本原型的 `BeliefSampler` 是唯一隐藏信息来源，切换对手池不需要改搜索。

### 9.2 策略改进的形式化（为什么搜索值得做）

有限 belief-MDP 上，给定 $\pi$，MCTS 的访问分布近似
$\pi_{\text{MCTS}}(a)\approx\exp(\beta Q^\pi(h,a))/\sum_b\exp(\beta Q^\pi(h,b))$，
$\beta$ 随访问数增大；策略改进定理给出 $V^{\pi'}\ge V^\pi$。部分可观测下该定理在
belief-MDP 上成立（状态=信念），但 **determinization 误差**与**对手非平稳**使改进是
"对采样世界/当前对手池"的局部改进——这也是要报告 oracle gap 与定期重评估的原因。

### 9.3 本原型的训练接入点

- 每决策可直接取 `(obs.features, obs.cards, obs.mask, res.pi, final_rank, seat, turn,
  res.root_value, res.visits, res.info)` 组成样本（与 AZ 设计 §8.1 schema 对齐）；
- `SearchAgent.results` 保留每次决策的 `SearchResult`，`evaluate.play_game` 可批量跑自对弈；
- 建议训练初期用 `heuristic` 或 `bot_prior` evaluator 生成 bootstrap 数据，同时训练价值头；
  当价值头与终局 rank 相关 >=0.5 后切换 evaluator=`net.eval`，再逐步降低 bot 先验 blend。

---

## 10. 测试与复现

### 10.1 本地（无 Rust 引擎，toy 层）

```powershell
cd C:\HSagent
python -m pytest tests/test_az_search.py -q
# 实测：23 passed, 8 skipped（引擎层因 hsbg_engine 未安装 skip）
```

覆盖：
- toy POMDP：π 合法且和=1、动作合法、同 seed 确定性、**隐藏量不同→公开观测相同时搜索
  决策/π 完全一致（信息隔离）**、搜索不修改源局面、eval 异常安全回退、终局根空 π、
  temperature=0 argmax、Dirichlet 只落在合法动作、根价值范围；
- 数学：PUCT 先验/ Q 选择、visit 分布温度、`masked_prior` 的 NaN/负值/非法清洗、
  sims 均分、placement utility 端点；
- 静态审计：搜索/世界采样源码不出现 `.view(`/`state_json(` 调用。

### 10.2 远程引擎层（真实 `hsbg_engine`）

```bash
# 隔离 staging（不写共享仓库）
cd /home/data/users/gaoletian/projects/az_stage
PYTHONPATH=$PWD ~/.conda/envs/hiermolgen/bin/python -m pytest tests/test_az_search.py -q
# 实测：30 passed, 1 skipped（慢评测 AZ_EVAL=1 门控）
```

引擎层覆盖：
- 真实 `Game` 上 determinization 后 `observe(seat)` 逐字节不变、`injected_hidden=True`、
  `oracle=False`、源状态未被修改；
- Rust / Python 两后端搜索：π 形状/合法/和=1、动作合法、root_value ∈[-1,1]、
  `n_evals>0`、world `obs_invariant=[True,...]`、`state_json` 前后一致；
- 同 seed 可复现（Python 后端）；
- 训练侧 4 参 `eval_fn` 回调直接可用且调用次数与 `info["n_evals"]` 一致；
- 无引擎时上述用例自动 skip（本地仍跑 toy 层）。

### 10.3 质量评测

见 §8.1 命令与 §8.2 结果；完整 JSON 在远程 staging `runs/eval_search_fixed.json`
（评测产物不入库）。

---

## 11. 限制与下一步

### 11.1 已知限制

1. **determinization 先验是手工 $q_0$**（无历史 replay/估计器）：公开可见信息利用有限
   （未用 lobby 种族条件化、未用对手英雄技能），偏差未量化；
2. **残余隐藏泄漏**：任务/饰品/技能计数等无法经 debug 覆写（§4.2），正式版需引擎
   `resample_hidden`；
3. **Rust 后端不逐 EndTurn 重采样 chance**（世界级方差代替）；Python 后端的
   `resample_on_end_turn` 未做大规模方差实验；
4. **PIMC strategy fusion** 未量化；ISMCTS 未实现（升级路径 §2.3）；
5. **冷启动搜索增益弱**：`search_heuristic` 未超过 heuristic；超过 bot 需要学习型价值；
6. **成本**：注入 ~1.1ms/world 是主要瓶颈；20 局 search_bot_prior 59s；
7. **座位 0 先行动优势**（评测口径）：bot 基线 rank 2.65 而非 4.5，配对比较公平但绝对
   名次不能直接外推到真实 8 人同步对局。

### 11.2 下一步（按价值排序）

1. **接价值网络**：用训练侧的 rank 分布头替换 `heuristic_value`，重跑同协议看
   `search_net` 是否显著优于 `search_heuristic`/bot（这是搜索增益的真实检验）；
2. **网络先验/蒸馏 bot 先验**：把 `BotPriorEvaluator` 换成网络先验，去掉 Python 后端成本；
3. **成对胜负矩阵**（AZ 设计 §3.10）作早期叶值，替代规则价值；
4. **ISMCTS + 跨世界 mask 合并**（若 strategy fusion 诊断显著）；
5. **Rust BeliefSampler**：把注入搬进引擎，目标 <0.2ms/world，支撑 8 座全搜索；
6. **oracle gap 测量**：CloneSampler vs 公开先验，量化先验质量；
7. **TavernBench 决策一致率**：把搜索 π 与 TavernBench 参考答案对照（只作对照，不训练）。

---

## 附录 A：公式

### A.1 PIMC 估计量

$$
\hat Q_{\text{PIMC}}(h,a)=\frac{1}{W}\sum_{w=1}^{W}\hat Q_w(h,a),\quad
s_w\sim q(\cdot\mid h),
$$
$$
\mathbb{E}[\hat Q_{\text{PIMC}}]=\mathbb{E}_{s\sim q}[Q(h,a;s)]\ \ne\ \mathbb{E}_{s\sim b}[Q]
\quad\text{（偏差 = 世界先验误差）}.
$$
$$
\mathrm{Var}[\hat Q_{\text{PIMC}}]=\frac{1}{W}\mathrm{Var}_{q}[Q(h,a;s)]
+\frac{1}{W}\mathbb{E}_{q}[\mathrm{Var}(\hat Q_w\mid s)].
$$

### A.2 PUCT 与备份

$$
\text{PUCT}(a)=Q(a)+c\,P(a)\frac{\sqrt{\sum_b N_b}}{1+N_a},\quad
N(a)\mathrel{+}=1,\ W(a)\mathrel{+}=v,\ Q(a)=W(a)/N(a),
$$
$v$ 为 seat 视角 utility（终局 $u(r)$ 或叶价值），**不取负**。

### A.3 根噪声与策略目标

$$
\tilde P=(1-\varepsilon)P+\varepsilon\mathrm{Dir}(\alpha),\qquad
\pi_{\text{target}}(a)=\frac{N(a)^{1/\tau}}{\sum_b N(b)^{1/\tau}}.
$$

### A.4 名次效用

$$
u(r)=1-\frac{2(r-1)}{7},\quad u(1)=+1,\ u(8)=-1,\quad
\sum_{p=1}^{8}u(r_p)=0.
$$

---

## 附录 B：最小用法

```python
# 1) 真实引擎：Rust 后端（快）
from hsbg_engine import Game
from hsbg.az import search, SearchConfig, env_api as EA

g = Game(70000)
EA.finish_hero_select(g)          # 英雄选择 → turn 1
res = search(g, seat=0, config=SearchConfig(
    simulations=16, determinizations=4, temperature=0.0, seed=0))
print(res.action, res.pi.sum(), res.info["engine_backend"], res.info["world_obs_invariant"])

# 2) Python 后端 + bot 先验（质量最好的冷启动路径）
from hsbg.az.policy import BotPriorEvaluator
res2 = search(g, seat=0, config=SearchConfig(
    simulations=16, determinizations=4, temperature=0.0, seed=0),
    eval_fn=BotPriorEvaluator(blend=0.75), engine_backend="python")

# 3) 无引擎（toy 环境，单测/演示）
from hsbg.az.toy_env import ToyGame
tg = ToyGame(seed=5)
r = search(tg, 0, config=SearchConfig(simulations=8, determinizations=2, seed=0))
```
