# 训练系统设计：不完全信息 MCTS + 叶评估 + 自对弈 + PPO

> 目标：在唯一引擎 `hsbg_engine`（AutoTavern TavernGym fork，37.0.0.255790）上，
> 把「不完全信息 MCTS → 叶节点评估 → 8 座自对弈 → PPO」做成可扩展、可复现、吞吐可测的训练系统。
> 本文是设计蓝图；当前代码状态见 §10，未实现项明确标注。

## 0. 设计目标与约束

| 维度 | 目标 |
|---|---|
| 正确性 | 只用公开观测做决策；同 seed 轨迹逐位一致；动作 mask 精确 |
| 吞吐 | 目标 **1M decisions/iteration**（口径 = `selfplay` 的 `meta.decisions`，全座累计；约 2,222 局 @450）；P0 先 50k、P1 250k，端到端验收后升级 |
| 样本效率 | 同等 decisions 下，MCTS-guided PPO ≥ 纯 PPO；同等算力下评估名次更优 |
| 推理效率 | 评估时单决策 ≤ 100 ms（CPU/单 GPU 小 batch），训练 actor 不成为瓶颈 |
| 可复现 | 数据/引擎/模型/搜索配置/seed 全部进报告；checkpoint 可重放 |
| 可验证 | 固定 seed 500–1000 局；与 bot / 纯 PPO / 不同 sims 做配对比较 |

硬约束：
- 唯一动作空间：**245**（0..244），扩展段 245..273 不进入 AZ 训练；
- 唯一观测：**3227 floats + 124 cards**；
- 唯一引擎：`hsbg_engine`；不允许引入第二套引擎或旧候选动作栈；
- 搜索只允许不完全信息 MCTS（PIMC/ISMCTS + PUCT）与自对弈。

> **终审状态（2026-10-27，GPT-6 Astra 审阅）**：方向正确，但“1M decisions/iter”是**目标**
> 而非现状。必须先做批量叶评估、真实 chance/对手处理、KL anchor，并以端到端配对实验放行；
> 当前只是可验证原型。本文已按审阅意见修订搜索/剪枝/吞吐/PPO 的边界。

## 1. 问题形式化

单座位视角是 POMDP：

- 状态 `s`：8 人完整状态（含 7 个对手手牌/金币/酒馆/隐藏计数）；
- 观测 `o = Z(s)`：`observe(seat)` 的 3227+124，只含客户端可见信息；
- 动作 `a ∈ {0..244}`，`legal_mask(seat)` 精确；
- 转移：`EndTurn` 是宏动作，内部推进 7 座 bot/对手、配对、战斗 RNG、刷新、淘汰；
- 回报：终局名次 `r ∈ {1..8}`，效用 `u(r) = 1 - 2(r-1)/7 ∈ [-1,1]`；
- 目标：`π(a | h_t)` 最大化 `E[u(r)]`，其中 `h_t = (o_1..o_t, a_1..a_{t-1})`。

8 人局是常和但非两人零和：备份不做符号翻转，价值始终是**本座位视角**的 utility。

## 2. 系统总览

```text
┌──────────────────────────── Actor 层（并行） ────────────────────────────┐
│  8 座自对弈 / 1 学习座 vs bot / 对手库   ×   N 个 worker（进程）          │
│  每 worker：hsbg_engine.Game + 本地 MCTS + 本地网络前向（或批量队列）     │
└───────────────┬──────────────────────────────────────────────────────────┘
                │ (features, cards, mask, π, action, logprob, value, rank)
                ▼
┌──────────────────────────── 数据层 ──────────────────────────────────────┐
│  ring buffer / shard 文件；按 episode 分组；GAE 在 learner 侧计算         │
└───────────────┬──────────────────────────────────────────────────────────┘
                ▼
┌──────────────────────────── Learner 层（GPU） ───────────────────────────┐
│  PPO：clipped surrogate + rank/value + entropy + π 辅助 CE + KL anchor    │
│  固定 seed 评测 / checkpoint / 报告                                      │
└───────────────┬──────────────────────────────────────────────────────────┘
                ▼
        新 checkpoint → 下一轮 Actor（自对弈 / 对手库）
```

关键原则：
1. **Actor 不做梯度**；只做推理 + 搜索 + 数据落盘。
2. **Learner 只做批量前向/反向**；不持引擎。
3. **搜索与 PPO 解耦**：搜索产 `π` 与动作；PPO 用行为策略的 logprob 做 on-policy 修正。
4. **可降级**：没有 GPU/引擎时用 `toy_env`/synthetic 测试，训练主路径不依赖 mock。

## 3. 搜索设计

### 3.1 信息集与信念

PIMC（第一阶段）：
- 从公开观测 `o` 采样 `W` 个隐藏世界 `{s_w}`（`belief.EnginePublicPriorSampler`）；
- 注入后断言 `observe(seat)` 字节不变（信息隔离不变量）；
- 每个世界独立一棵 PUCT 树；根 visit 跨世界聚合。

已知偏差：
- strategy fusion（不同世界共用根策略）；
- non-locality（对手隐藏状态采样不完美）；
- 残余泄漏（引擎 debug 不能重置对手任务/饰品/技能次数）。

升级路径（第二阶段）：ISMCTS——单树、信息集节点、每次 simulation 采一个世界，节点统计跨世界共享；当跨世界 legal mask 不一致时按信息集合并。设计上保留 `BeliefSampler` 接口，PIMC/ISMCTS 可切换。

### 3.2 树与 PUCT

节点 `s` 保存：`N(s)`、`W(s)`、`P(s,a)`、`N(s,a)`、`W(s,a)`、`terminal`、`world_id`、`depth`。

选择：

```text
PUCT(s,a) = Q(s,a) + c_puct * P(s,a) * sqrt(N(s)) / (1 + N(s,a))
Q(s,a)    = W(s,a) / N(s,a)          (N=0 -> 0)
```

- 根先验：`P_root = (1-ε)P_θ + ε·Dir(α)`；训练 `ε=0.25`，评估 `ε=0`。
- 叶评估：`(P_θ(·|o), v_θ(o))`；价值备份用 `v`（不做符号翻转）。
- 终端：`v = u(rank)`。
- 温度：训练 `τ≈0.8–1.0` 采样；评估 `τ=0` argmax。
- 根 π：`π(a) ∝ Σ_w w_w N_w(a)^{1/τ}`；`w_w` 默认均匀，可选按世界先验 likelihood。

### 3.3 宏动作 `EndTurn` 与 chance

`EndTurn` 之后引擎内部推进 7 座 + 配对 + 战斗 RNG + 刷新 + 淘汰；它不是普通动作，而是一个**随机宏转移**。

两种实现：
- Rust `mcts_search`：宏转移折叠在边内（快，但树内不显式建模 chance）；
- Python 后端：`resample_on_end_turn=True` 时，EndTurn 后重新采隐藏世界，作为 chance 节点对照（慢，用于校准）。

设计选择与限制：
- **现状**：Rust `mcts_search` 的 `advance_to_seat()` 对其余 7 座调用固定 `bot::play_turn`，
  并把战斗/RNG 折叠进边；这是“bot 对手 + 宏转移”，**不是**真正的对手策略/机会分支。
- 训练默认仍用 Rust 宏动作，但把它标为 **P0 近似**；P0 的 root value 必须对终局 utility
  做校准检验，不能直接当无偏证据。
- 每 `K` 个 iteration 用 Python chance 后端做一致性抽查；生产训练**只允许 Rust 后端**，
  Python 失败不得静默降级混入数据。
- 对战斗方差大的局面（高 tier/高攻击），P1 显式采样 `C` 个战斗结果作为 chance 子节点；
  P1 再比较 ISMCTS（单树/信息集）与 PIMC。

### 3.4 动作剪枝（安全优先）

目标：在不丢关键动作的前提下减少 branching / leaf calls。

| 层级 | 方法 | 默认 | 规则/风险 |
|---|---|---|---|
| L0 | 精确 legal mask | ✅ | 只考虑 `mask=1`；非法概率恒 0；唯一无条件安全 |
| L1 | 先验 top-k/质量阈值 | ❌ 仅 ablation | 低先验的买卖/位置/战术动作可能是唯一翻盘动作；不能作为默认 |
| L2 | 根 UCB/Q 剪枝 | ❌ 默认关闭 | 有限 sims + 未校准价值 + 8 人非零和 → 可能锁定错误动作 |
| L3 | 转置/状态去重 | ✅ 有条件 | 仅同一 world 且 hash 覆盖完整可见/隐藏/RNG/信息集；跨 world 禁止合并 |
| L4 | 渐进加宽 | ❌ 仅 ablation | 必须保留未展开集合与探索 floor；245 动作下默认一次展开 |
| L5 | 集中度/价值早停 | ❌ 默认关闭 | 与 L2 同类风险；只允许在评估/调试用 |
| L6 | 批量叶评估 | ✅ | 多叶子合并一次 GPU 前向（见 §4.2），不改变动作集合 |

**默认策略 = L0 + 安全 L3 + L6**。L1/L2/L4/L5 只在受控 ablation 中开启，必须报告
剪枝率、rare-action 召回和配对名次变化；任何价值剪枝先通过 rank ECE/Brier 与
adversarial rare-action 测试。硬规则：
- 任何层级不得剪到 0 个动作；
- 剪枝动作在树中保留“已访问统计”，可恢复；
- 所有剪枝决策进 `search_info`，可审计。

### 3.5 搜索预算与自适应

- `sims`：训练 8–32，评估 32–128；按局面复杂度自适应：
  `sims = clamp(base + k·log(1+legal_count) + k2·uncertainty, min, max)`；
- 预算按**时间**而非固定 sims：`max_ms_per_decision`（训练 20–50ms，评估 100ms）；
- 根搜索与树复用：同一局下一步可复用子树（同世界、同 seat、动作未变）；新世界则丢弃或只复用公共部分；
- 搜索缓存：`(state_json, seat, world_id)` → `(π, v)`；只在同一世界/同一树内复用。

### 3.6 搜索伪代码

```text
def search(game, seat, cfg):
    worlds = sampler.sample(game, seat, cfg.W)
    roots = [Node(world, seat) for world in worlds]
    for w in worlds:
        for _ in range(cfg.sims // cfg.W):
            leaf, path = select_and_expand(roots[w], cfg)
            batch.add(leaf)                 # 批量叶评估
            backup(path, v)
    pi = aggregate_visits(roots)
    action = sample_or_argmax(pi, tau)
    return SearchResult(pi, action, root_value, ...)
```

## 4. 叶节点评估

### 4.1 模型

当前 `entity_model.py`：

- 输入：49 token（global 1 + 随从 7 + 手牌 10 + 酒馆 8 + 待选 16 + 对手 7）；
  论文 56 token 的额外槽位（独立 trinket/quest/attachment 等）当前**未实现**，只作为 P1 ablation；
- 卡牌：identity embedding + `card_static` 投影 + 字符 3-gram 文本 embedding（64 维）；
- trunk：Transformer `d=384, 8 layers, 8 heads, FF=4d`；
- 输出：pointer head 245 masked logits + rank 8 logits + 可选 scalar value；
- 实测 **14.8M** 参数；论文 18M。18M/56-token 只有在固定数据/FLOPs/延迟门禁下胜出才采用。
- 对手 token 参与 transformer 注意力并汇入 global；当前 pointer 头没有“直接指向对手”的分支（245 动作里也没有对手目标动作），不要把它说成独立的对手建模。
- 输入做 `sign(x)·log1p(|x|)`；LayerNorm；dropout（训练）/eval（推理）。

合理性：
- 49 token 覆盖主要公开实体；trinket/quest/secret 目前汇入 global 卡牌表示，未独立 token；
- pointer head 直接复用实体表示，避免 245 个独立 MLP；但 play/magnetize/move 是固定槽位
  点积 + 位置/类型 embedding，mask 只在 logits 后硬裁；必须用单测覆盖动作语义（卡类型/
  目标/槽位），不能假设点积表达全部规则；P1 可加动作类型条件化。
- rank 头比 scalar value 更稳（8 类分布 + 期望 utility），适合 8 人局；
- 14.8M 在 49 token 下有足够容量；18M 的增益需 ablation 验证。

### 4.2 批量叶评估（吞吐关键）

单叶逐次前向是当前最大瓶颈（entity 搜索比 tiny 慢 ~12×）。设计：

```text
Actor 收集叶子请求 (features, cards, mask) → 本地队列
  → 每 B=64..512 条做一次 GPU 前向
  → 返回 (P, v) → 回填各树
```

实现选项：
1. **Python 批量 PIMC**：重写 `hsbg/az/search.py` 的 Python 后端为“多树 + 批量叶”；
2. **Rust 搜索 + 批量回调**：Rust `mcts_search` 收集叶子，PyO3 一次回调批量推理；
3. **Actor-Learner**：actor 只做引擎/搜索，叶子批量 RPC 到 learner GPU（适合多机）。

首期选 1/2：
- 单机多进程 actor，每 worker 本地 batch（B=32–128）；
- 或一个 GPU learner 进程 + 多个 CPU actor，叶子通过共享队列批量；
- 目标：GPU 利用率 ≥ 60%，单次前向 batch ≥ 64。

### 4.3 缓存与精度

- 树内缓存 `(state_hash, seat)`；同一世界内复用；跨世界不共享 value；
- `torch.inference_mode()`；`model.eval()`；可选 `torch.compile`/ONNX（P2）；
- fp16/bf16 推理需校准 value；训练保持 fp32（或 AMP）；
- 叶子 batch 有上限；超时则用先验/父值回退，不阻塞搜索。

### 4.4 价值校准

- 训练目标：rank CE（主）+ scalar utility MSE（辅助，权重 0.1–0.5）；
- **注意**：rank CE 与 utility-MSE 不等价；PPO 的 GAE 使用 `E_{p(r)}[u(r)]`，必须报告
  rank 分布校准（Brier/ECE）与 value-rank corr；若校准差，GAE 的 value baseline 会偏。
  P1 可改为双头：rank 分布（辅助）+ scalar utility critic（GAE 主用），两者都记录。
- 评估：rank 分布 Brier / ECE、value-rank corr、按 turn/tier 分层校准；
- 若 value 过自信：温度缩放/直方图校准，再用于 PUCT 的 Q 初始化（P1）；
- 不做“价值剪枝”直到校准误差低于阈值。

## 5. 自对弈吞吐设计

### 5.1 计算模型

设：
- `D` = **每局所有座位决策合计**（约 450；以 `selfplay` 的 `meta.decisions` 实测为准）；
  `1M decisions ≈ 2,222 局 @450`。注意：`meta.decisions` 已全座累加，不要再乘 8。
- `D_iter` = 本 iteration 的 decisions（全座累计）；
- `S` = 每决策叶子评估数（sims）；
- `G` = 并行局数；
- `B` = 叶评估 batch；
- `t_eval(B)` = 一次 GPU 前向时间；
- `t_step` = 引擎 step 时间（Rust 宏动作含 7 bot + 战斗）。

近似（工程口径）：
```text
active_slots   = 实际并发 seat slots（由 actor 拓扑决定，不等于 G*8；串行 Game 路径只有 1 个）
decisions/s    ≈ active_slots / 单决策平均耗时
leaf_evals/s   ≈ decisions/s * S
leaf_batches/s ≈ leaf_evals/s / B
```
其中单决策平均耗时 = 搜索耗时 + 引擎 step 耗时 + 观测/编码耗时；搜索耗时主要由 `S/B * t_eval(B)` 决定。
更实用的迭代公式：
```text
T_iter ≈ max(采集, 训练, 评估)
采集 = D_iter / throughput_decisions
throughput_decisions ≈ min(
    engine_steps/s / steps_per_decision,
    GPU_leaf_evals/s / sims_per_decision,
    actor_cpu_parallelism
)
```

### 5.2 实测前向吞吐（RTX 4090，entity 14.8M，fp32，inference_mode）

| batch B | ms/批 | samples/s |
|---:|---:|---:|
| 1 | 4.54 | 220 |
| 8 | 5.23 | 1,530 |
| 32 | 4.88 | 6,555 |
| 64 | 4.91 | 13,025 |
| 128 | 7.05 | 18,144 |
| 256 | 13.41 | 19,085 |
| 512 | 26.05 | 19,651 |

结论：
- 单叶前向只有 **220 samples/s**；B≥64 后可达 **1.3–2.0 万 samples/s**（约 **60–90×**）。
- 1M seat decisions × sims 8 = 8M leaf evals：GPU 侧约 **7 分钟**（19k/s）；sims 32 约 **28 分钟**。
  若 W=4，每决策还有约 W 次根 eval，实际是 12M（sims8）→ ~10.5min；仍未计树选择/引擎/copy。
- 因此 **1M decisions/iter 只是“GPU 裸前向”的可达下界**；端到端必须由 benchmark 证明。
  当前 0.03 self-play games/s 的瓶颈是逐叶 Python 前向 + 串行座位，不是 GPU。
- 当前 `selfplay.py` 的 Game 路径是**逐座位串行**；`BatchEnv` 只支持 `act_batch`，不接 MCTS/PPO records。
  设计中的“8 座并行”需要新的 actor/search 调度，不能假设现有代码已支持。

> 注意：上表是**仅叶前向**的理想值。端到端还包含 `W` 次 determinization、根 eval、树选择、
> 引擎 step、Python↔Rust 拷贝、batch 等待；PIMC 的根 eval 约 `W` 次/决策。1M decisions
> 的采集时间必须由 P0 端到端 benchmark 给出，不能用 19k samples/s 直接外推。

### 5.3 目标预算

| 阶段 | decisions/iter | sims/decision | 预计采集 | 说明 |
|---|---:|---:|---:|---|
| Smoke | 10k | 4 | 分钟级 | CPU |
| P0 | **50k** | 4 | 先测 | Rust sims=4, W=1/2；端到端 benchmark |
| P1 | **250k** | 4–8 | 先测 | 批量叶 + 多 actor；验收后再谈 1M |
| P2 | 1M（目标） | 4–8 / 0 | 条件性 | 只有 P1 达到 decisions/s 目标才升级 |
| Eval | 500–1000 局 | 32–64 | 小时级 | 固定 seed |

> 当前实测（4 局 entity self-play，sims=4）约 **0.03 games/s**，对应 ~13 decisions/s；
> 距 1M decisions/iter 需 **~2 个数量级** 提升。设计上的主要杠杆：
> 1) 批量叶评估（目标 10–30×）；2) 降低训练 sims（8 vs 32）；3) 网络行为 PPO（不做逐叶搜索）；
> 4) Rust BatchEnv/多进程 actor；5) 剪枝/树复用（2–5×）。

### 5.4 Actor 拓扑

```text
方案 A（单机）：N 个 CPU actor 进程（各自 Game + 本地 PIMC）
               + 1 个 GPU learner（PPO）
               actor 通过 shard 文件/队列交数据；learner 定期发 checkpoint
方案 B（多机）：CPU actor 集群 + 1 GPU learner；叶子批量 RPC
```

- 每 actor 内：`BatchEnv(controlled=range(8))` 或 `Game` 逐步；
- 8 座共享同一策略（self-play）；对手库阶段只 learner 座收数据；
- 数据按 episode 分片，learner 端拼 batch/GAE，避免 actor 写大文件；
- checkpoint 发布用原子 rename；actor 只读最新 checkpoint；
- 失败隔离：actor 崩溃不影响 learner；超时任务重派。

## 6. PPO 设计

### 6.1 目标函数

```text
L = E[ min(ρ A, clip(ρ, 1-ε, 1+ε) A) ]
    + c_v * L_value
    + c_π * CE(π_MCTS, π_θ)
    - c_e * H(π_θ)
    + β * KL(π_θ || π_anchor)
```

- `ρ = π_θ(a|o) / π_behavior(a|o)`；行为策略必须记录 `old_logprob`；
- `L_value`：rank CE（8 类，主）或 utility MSE；**两者不等价**；GAE 用 `E[u(r)]`，
  必须报告校准。P1 可加 scalar utility critic 专供 GAE，rank 头作辅助。
- `π_MCTS`：根 visit 分布；`c_π=0.1–0.5`（0=纯 PPO）；
- `H`：masked entropy；`c_e=0.002–0.01`；
- `KL anchor`：`β·KL(π_θ || π_anchor)`，`π_anchor` 为上一 stage 冻结网络；前 100 iter
  β 退火。**当前代码没有 anchor_model/anchor_coef，仅 batch KL 早停**；P0 实现后再声称稳定化。
- 目标函数是 **minimize**（policy/value/aux + entropy 负号）；文档/代码符号必须一致。

### 6.2 行为策略选择

| 模式 | 行为 | ratio 分母 | 用途 |
|---|---|---|---|
| `net` | 网络 masked softmax 采样 | 网络 logprob | **默认**，严格 on-policy；MCTS π 作辅助 |
| `mixed` | `μ=(1-ε)π_MCTS+επ_net` 采样 | μ 的精确 logprob | 探索/冷启动 |
| `mcts` | MCTS visit π 采样 | π_MCTS | 生成教师数据；off-policy，高方差，慎用 |

推荐：
- 规模训练：`behavior=net`，`sims=0–8`；MCTS 只在需要 `π` 目标时开启；
- 冷启动：`behavior=mixed`，`sims=16`，逐步退火到 net；
- 不要把 `mcts` 行为直接用于大 lr PPO。

### 6.3 GAE / 8 人局

- 每局按 `(game_id, seat)` 分组；
- 终局 `r=rank`，`u=1-2(r-1)/7`；`done=1` 只在线程末；
- `δ_t = r_t + γ V(s_{t+1}) - V(s_t)`，`A_t = Σ (γλ)^l δ_{t+l}`；
- `γ=1.0`（终局效用），`λ=0.95–0.995`；
- 截断局（rank=0）丢弃；同 seed 配对评估。

### 6.4 超参与规模

论文 Table 7 作为起点：

| 项 | 值 |
|---|---|
| decisions/iteration | ~1M |
| iterations/stage | 300 |
| games/member × steps | 512 × 256 |
| minibatch | 8192 |
| lr | 6e-6 → 5e-6 |
| clip | 0.2 |
| target KL | 0.05 |
| γ / λ | 1.0 / 0.995 |
| entropy | 0.002 |
| value coef | 0.5 |
| aux π coef | 0.1 |

当前默认（`PPOConfig`）偏小（lr 3e-4、minibatch 64、2 epochs），只适合 smoke；规模训练必须切到上表或经 ablation 的值。

### 6.5 确定性守卫（forced EndTurn）

未训练网络可能陷入 Play/Cancel 循环；`max_actions_per_turn` 守卫在超限时强制 EndTurn。
这是**环境确定性约束**，不是行为分布采样：
- 采集记录 `logprob=0`、`forced=True`；
- PPO 的 policy/aux loss **排除 forced 样本**（`valid=~forced`），value/critic/回报链保留；
- 不能把 `log(μ[0])` 当行为概率（会伪造 on-policy ratio）；
- 单测必须覆盖：forced 标记、weighted clipped surrogate、policy/aux 排除、value 仍更新。

### 6.6 稳定化

- legal mask 硬约束：非法动作概率恒 0（测试断言 `illegal_prob_max==0`）；
- 梯度裁剪 0.5；KL 早停；NaN 检查；
- 输入归一化统计随 checkpoint 保存；
- 每个 stage 在 unseen seeds 上复检后才交付（G4 思路）；
- 评估与训练 seed 分离；固定 seed 集滚动更新。

## 7. 搜索与 PPO 的结合

### 7.1 三种结合方式

1. **MCTS-guided PPO（默认）**：网络行为，MCTS 根 π 作辅助 CE；搜索只改目标，不改行为分布 → on-policy、稳定。
2. **Search-distill PPO**：MCTS 生成数据，网络蒸馏 π；PPO 再用网络行为微调；两阶段，吞吐更好。
3. **Search-as-behavior**：MCTS 直接选动作；off-policy ratio；只用于冷启动/教师，不作为主训练。

### 7.2 搜索调度（吞吐关键）

- 训练早期：每 `k=4–8` 个决策做一次 MCTS（sims 8），其余网络行为；
- 训练后期：每 `k=16` 或只在高熵/高 legal 状态做 MCTS；
- 评估：每步 MCTS（sims 32–64）；
- 记录 `search_coverage`（MCTS 决策占比）、`pi_entropy`、`root_value`，用于 ablation。

### 7.3 为什么不是“纯 AlphaZero CE”

纯 AlphaZero 是 `CE(π_MCTS, π_θ)` + 终局 value；用户要求 **PPO**，所以：
- 行为策略用网络采样（on-policy）；
- PPO clipped objective 更新策略；
- MCTS π 作为辅助目标/搜索先验；
- 这样既保留 MCTS 的决策改进，又保留 PPO 的稳定性和样本复用。

## 8. 对手库与课程（P1，可选但高价值）

论文的最大单点增益是 **reality-calibrated opponent library**（first-place +6.3pt）。设计：

| 阶段 | 对手 | 数据 |
|---|---|---|
| C0 | 引擎 bot | 冷启动 |
| C1 | 历史 checkpoint 池（league） | 自对弈 + 评估 |
| C2 | bot + 历史 + 规则化对手 | 课程 |
| C3 | 真实对局/人类统计 library | 需要只读真实数据适配层 |

注意：`hsbg/bridge`/`live` 已随 AutoTavern-only 重构删除；C3 需要**重新引入只读 Power.log/HDT 数据适配层**（不恢复 hsrl2），先把“真实战斗/招募”解析成 library 样本。

课程：简化规则 → 全内容 → 玩家视角 → first-place 目标 → library；每阶段固定 seed 评估。

## 9. 评测与门禁

- **主指标**：固定 seed 500–1000 局，seat 轮换，mean rank / top4 / win / legal / truncated；
- **配对比较**：同 seed 同对手，bootstrap CI；报告 effect size；
- **搜索 ablation**：sims 0/4/8/16/32；MCTS 覆盖率 0/25/50/100%；
- **模型 ablation**：tiny / 14.8M / 18M；token 49 vs 56；
- **PPO ablation**：纯 PPO vs MCTS-guided；`π_coef` 0/0.1/0.5；KL anchor on/off；
- **门禁**：`scripts/verify_all.py` 六项全绿；无非法动作；NaN/Inf 检查；
- **TavernBench**：只做静态决策/值校准，不做 RL 回报。

## 10. 当前代码状态（诚实边界）

| 能力 | 状态 |
|---|---|
| AutoTavern 引擎 + 37.0.0.255790 | ✅ |
| 245 动作 / 3227+124 观测 | ✅ |
| PIMC/PUCT 搜索（Rust/Python） | ✅ 基础版；无批量叶、无 ISMCTS、无显式 chance 训练 |
| Entity transformer 14.8M + pointer | ✅ |
| 自对弈 | ✅ Game 逐座串行 / BatchEnv act_batch；无 MCTS 批量/无 library |
| PPO | ✅ `hsbg/az/train/ppo.py`；仅 1 局 smoke |
| 批量叶评估 | ❌ |
| KL anchor / 多 stage | ❌（仅 batch KL 早停） |
| 对手库 / 课程 | ❌ |
| 1M decisions/iter | ❌（当前 ~10^4 级） |

## 11. 实现计划

### P0（先做，决定可行性）
1. `hsbg/az/search_batched.py`：多树 + 叶子 batch 队列 + 批量网络前向；**同时修
   selfplay 的串行座位**（BatchEnv 目前只有 act_batch，不接 MCTS/PPO records）；吞吐口径统一用
   `meta.decisions`（全座累计），不要用 `G*8` 推断并发；端到端基准
   B=1/64/128/256、W=1/2/4、sims=4/8；验收 ≥10× 当前，报告 decisions/s、leaf/s、GPU 利用率、p50/p95；
2. `hsbg/az/train/ppo.py`：`anchor_model`/`anchor_coef`（冻结上一 stage 的 masked KL）、
   `search_every`、`batch_leaf`；forced 样本排除 policy/aux（已修）；
3. `scripts/train_az_ppo.py`：actor 模式、checkpoint 池、数据 shard、背压/崩溃重放；
4. 信息隔离：determinization 后公开观测字节一致、oracle=0、失败拒收 shard；
5. PPO 行为对账：net/mixed/mcts 的 old_logprob vs μ；GAE 按 episode/turn 单调；
6. 固定 seed 500 局：纯 PPO vs MCTS-guided 同数据/同 FLOPs 配对。

### P1（质量/吞吐）
1. 安全 L3 转置 + 树复用；L1/L2/L5 仅受控 ablation；
2. 对手库（bot/history）+ 课程；
3. 500–1000 局评测 + 配对 CI；
4. 模型 14.8M vs 18M ablation。

### P2（研究）
1. ISMCTS（单树/信息集）；
2. chance 节点/战斗结果采样；
3. 真实数据 library（只读适配层）；
4. 推理优化（batch/compile/ONNX）。

### 验收
- P0 先验收 250k decisions/iter 端到端；达到目标采集吞吐后再升级到 1M；
- 0 illegal / 0 NaN；
- MCTS-guided PPO 在固定 seed 上 ≥ 纯 PPO（pre-registered 指标）；
- 单决策评估延迟 ≤ 100 ms（小 batch）；
- 所有 ablation 可复现（seed/config 写入报告）。

## 12. 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| PIMC strategy fusion | 搜索高估 | ISMCTS/多世界校准；报告 root value vs 实际 |
| 叶评估慢 | 吞吐不达标 | 批量、剪枝、减小 sims、纯 PPO 分支 |
| 价值不校准 | 搜索被误导 | rank 分布 + ECE/Brier + 温度校准 |
| 剪枝丢动作 | 强度损失 | 安全剪枝规则 + 保留 floor + 审计 |
| PPO off-policy 方差 | 训练不稳 | 默认 net 行为；MCTS 只作辅助；KL anchor |
| 对手库泄漏 | 评估虚高 | exam library 隔离；unseen seeds |
| 数据版本 | 不可比 | 37.0.0.255790 固定；报告版本 |
| 过拟合 seed | 结论不稳 | 500–1000 局 + 配对 CI + 多 seed 集 |
