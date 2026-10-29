# 训练计划 v2：Entity 网络 + 异步 Actor-Learner + 反复“做题” + 冷启动课程

> 背景：1h tiny/self-play 试训（20 iter / 502,826 decisions / 53.7 min）只把对 bot 的
> mean rank 从 7.98 降到 7.63（top4 0.78%，0 胜；bot 基线 4.81），**不算明显改进**。
> 诊断：tiny 容量不足、吞吐只有 ~157 decisions/s、self-play 信号与“打赢 bot”错配、
> KL 早停压住更新、没有对同一局面反复搜索。
>
> 本计划针对五点：① 反复“做题”（同局/同回合重搜）；② 对齐 14.8M entity；
> ③ 异步串行/并行吞吐；④ 先单模型打 bot，稳定后再分裂联赛；⑤ 交 GPT-6-Astra 终审。
> 这是设计；当前代码状态见 §10。
>
> **v2.1（GPT-6-Astra 终审后修订）**：终审结论为“退回修改”。已修正：gate 的配对 CI
> 方向；8–16 个单请求 actor 不能填满 B64；重搜择优/续局价值偏置；全 rank8 冷启动死锁；
> 吞吐基线口径与存储预算。**本计划不承诺“明显改进”**；必须先证明真实批量吞吐与
> 同算力收益。

## 0. 目标与验收

| 维度 | 目标 |
|---|---|
| 冷启动 | 单 entity 模型 vs 7 引擎 bot，500 局 mean rank **< 4.75**、top4 **>55%**、zero truncation |
| 吞吐 | P0 50k → P1 250k → P2 1M decisions/iter；端到端目标 **≥150–300 decisions/s** |
| 训练 | MCTS-guided PPO；同局/同回合重搜（reanalysis）+ 联赛自对弈 |
| 模型 | entity 14.8M 为默认；tiny 仅 smoke；18M/56-token 仅 ablation |
| 可复现 | seed/config/engine/data/checkpoint 全记录；固定 seed 500+ 局配对 CI |
| 计算 | 单 RTX 4090 + 8–16 CPU actors；GPU 叶 batch B=64/128 |

“明显改进”预注册定义：
- 相对初始 entity：mean rank 降低 ≥0.5，且配对 95% CI 上界 < 0；
- 或冷启动 gate 达成（mean rank <4.75、top4 >55%）；
- 两者必须同时报告 top4/win/legal/truncation，不能只报 loss。

## 1. 模型：默认 entity 14.8M

- 默认 `arch=entity`：d=384、8 层、8 头、FF=4d，实测 **14.8M**；tiny 0.96M 只用于 1 分钟 smoke。
- 输入：49 token（global 1 + 己方随从 7 + 手牌 10 + 酒馆 8 + 待选 16 + 对手 7），
  3227 floats + 124 cards；pointer head 245；rank 8 + 可选 scalar value。
- 论文 18M/56-token 是 **P2 ablation**；当前不先做 56/18M。tiny 失败不足以证明容量是
  主因；先修对手战团编码（card id 序列/顺序）与动作语义测试，再做 ablation。
- 训练 batch 8192 不能由推理 benchmark 保证显存；先 128/256 微批 + 梯度累积。
- 批量推理是吞吐前提：B=1 220 samples/s、B=64 13k/s、B=256 19k/s（RTX 4090 实测）。
  单叶逐次前向无法训练；entity 必须配 §3 的批量叶评估。
- 训练/推理一致性：norm 统计随 checkpoint；eval 用 greedy；训练用采样；forced EndTurn
  守卫在训练/评测中一致（当前已修：logprob=0、policy/aux 排除）。

## 2. 冷启动：先单模型打 bot，稳定后再分裂

### C0 单模型 vs 7 bot（先不做自对弈）

- 1 个 entity 策略坐 seat0，其余 7 座引擎 bot；
- MCTS-guided PPO：behavior=net，sims=4–8，W=1–2；π 作辅助 CE；
- 每轮 8–16 局，直到冷启动 gate。

**冷启动 gate（500 局，8 seat 轮换，固定 seed 集）**：
**主判据（统计）**：
```text
paired Δ = rank_model - rank_bot（同 seed/seat）
95% CI upper < 0          # 才叫“击败 bot”，不是 CI lower < 4.81
512 局、8 seat 均衡、zero truncation/illegal
在封存集上连续两次独立确认
```
**工程参考**（不作为统计证明）：mean_rank <4.75、top4 >55%。
bot 必须用同一 512 局协议重测基线（16 局的 4.81 不作为判据）。

若全 rank8（终局奖励无区分、critic 收敛后优势消失）：
- 加入**退火弱 bot/合法动作示范**或先让搜索教师产生优于网络的 π；
- 单学习者 + 冻结历史池，暂不复制 4–8 个同质训练者；
- 主评测仍打完整 bot；弱 bot 仅课程。

未达成 gate 前不扩联赛；每 10 轮评测一次并保存 checkpoint。

### C1 分裂联赛（4–8 个模型）

C0 达标后：
- 从 C0 checkpoint 复制 4–8 个成员，分别用不同 seed/对手课程继续训练；
- 每局 8 座从 league（含 bot anchor、历史 checkpoint）采样；
- 对手池：C0 + 历史成员 + bot（bot 比例从 50% 退火到 10%）；
- 每个成员每周/每 stage 重新评测，淘汰最弱、保留 best。

### C2 全自对弈 + 重搜

- 8 座全 league 自对弈；
- 每个 iteration 对若干历史局面重搜（§4）；
- 评测仍用 unseen seeds + bot/league 混合。

### C3 真实对手库（P2）

真实对局数据适配层已随 AutoTavern-only 重构删除；C3 需重新引入**只读** Power.log/HDT
适配层（不恢复 hsrl2），先做 bot/历史 checkpoint library，再做人类统计校准。

## 3. 异步 Actor-Learner 与吞吐

### 3.1 拓扑

```text
Actor-1..N（CPU）                  InferenceServer（GPU）             Learner（GPU）
引擎 Game + MCTS 选择  ──叶请求──▶  batch(B=64/128) 前向  ──π/v──▶  PPO update
  │ 轨迹(shard)                                                        │
  └──────────────▶ ReplayBuffer / shard 文件 ─────────────────────────┘
                                      │
                               CheckpointPublisher ──▶ 新 actor 版本
Evaluator（独立 GPU/CPU）── 固定 seed 评测 ──▶ 报告/晋级
```

### 3.2 同步 vs 异步

- **同步模式（P0 默认）**：所有 actor 用同一 checkpoint 采一个 iteration 的 250k decisions；
  learner 更新后发布新 checkpoint；无策略陈旧，最稳。
- **异步模式（P1）**：actor 持续采集，learner 消费；允许 1 个版本滞后；
  - 每个样本记录 `policy_version`；
  - PPO batch 只混同版本（或按版本分组做重要性修正）；
  - 版本差 >1 的样本丢弃/降权；
  - KL anchor 对上一 stage，不针对 actor 旧版本。
- **并行粒度**：actor 进程并行，但**一个 actor 不能只发一个叶请求**；每个 actor 必须
  同时驱动多局/多棵树（或把“选择”和“回填”分离），才能凑 B=64/128。8–16 个单请求
  actor 最多形成 8–16 batch，等待 1–2ms 不会变成 64。
- actor 建议：8–32 个 actor × 每 actor 8–32 局/多树；GPU 队列按请求聚批；
  先做端到端 profiling，再谈 1M。不要 Hogwild。

### 3.3 关键工程

- 叶请求：`(features, cards, mask, request_id)`；GPU 端 B=64/128，最大等待 1–2 ms；
  返回 `(π, v)`；超时回退先验，不阻塞。
- 无 GIL：Rust 引擎/搜索在 actor；Python 只做观测/队列；批量张量 pinned memory。
- Replay：按 iteration 分 shard，原子 rename；learner 端预取/双缓冲；压缩写盘。
- Checkpoint：原子发布，actor 只读；eval 与 train seed 分离；失败隔离/重派。
- 背压：队列上限；GPU 饱和时 actor 降 sims；记录 queue wait p50/p95。
- **基线口径**：相对 tiny 的 157 decisions/s 与相对 entity 的 ~13 decisions/s 不同，
  必须写明；C0 只计学习座有效样本，不能直接与全座 self-play 比。
- 1M 目标：实测 entity B=256 19k/s；8M 叶约 7min 只是裸 GPU 下界（未计根/行为前向/
  树/引擎/同步/IO/重搜）。150–300 decisions/s 下 1M 采集约 **56–111min**，加训练/评测/
  IO 后不能承诺 2h。先 50k→250k，完整 iteration 验收后再 1M。
- 存储：1M×3227 f32 特征约 12.9GB（未含副本/π）；必须流式 shard + TTL/LRU +
  分层采样，不能每 seat 每回合全存又保证每局 ≤64。

### 3.4 吞吐预算（红线）

| 阶段 | decisions/iter | sims | actors | 验收 |
|---|---:|---:|---:|---|
| P0 | 50k | 4 | 4–8 | 端到端 benchmark，≥10× 当前 |
| P1 | 250k | 4–8 | 8–16 | ≥150 decisions/s，1M 条件性 |
| P2 | 1M | 4–8 | 16+ | 1M ≤2h；GPU util ≥60% |

## 4. 反复“做题”：同局/同回合重搜（Reanalysis）

### 4.1 定义

“做题” = 对已经历过的局面（同一局、某些回合）用**当前模型 + MCTS**重新探索，
尝试找到比原行为更好的单回合决策路径；结果作为额外训练信号，不直接破坏 on-policy PPO。

### 4.2 数据

每个 actor 在以下时机保存 `state_json`（精确、可恢复）：
- 每回合开始（每 seat 1 个）；
- 高价值/高熵/高 legal 数/低 margin；
- forced EndTurn、战斗大伤害、淘汰边缘；
- 每个 state 记录 `(state_json, seat, turn, behavior π/action, old value, rank, seed, policy_version)`。
压缩存储；每局最多 32–64 个 state，控制 1–2GB/iteration。

### 4.3 重搜流程

```text
for s in sample(priority):
    g = Game.from_json(s.state_json)
    for k in range(K):                      # 反复做题
        worlds = belief.sample(g, seat, W_re)
        res = MCTS(g, seat, sims_re, worlds, current_net)
        candidate = res.action / res.pi
        # 单回合分支：从 s 开始，用当前策略/bot 推进到终局 R 次
        z = mean(rollout_utility(g, seat, candidate, R))
        if z > s.old_value + delta:
            store (s.features, s.cards, s.mask, res.pi, z)
```

- **MCTS reanalysis**：同 state、不同 W/seed 重复 K 次，**不按最高 z 择优**；用共同随机数/
  配对世界比较候选，独立世界确认 `LCB(Δutility)>δ` 才接受；δ 预注册（如 0.02 ≈0.07 名）。
- **turn-level branch**：从 state 复制，生成到 `EndTurn` 的动作序列；原路径与候选采用
  **相同后续策略**（当前策略，不是 bot）和成对战斗随机数；R 次独立验证。
- **priority**：不确定性/新颖度 + 均匀采样底座；每局上限；禁止只保留“有提升”的样本
  （选择偏差）。K 先 1–2，总重搜时间 ≤10%，同算力收益成立后再升 20%。
- 目标：π_re + z_re 只进 **限权辅助 CE/value 校准**，不进 PPO ratio；不能用 bot 续局的 z
  或“最高 z”监督当前策略 V；需要当前策略独立 rollout 或独立教师 Q。π 必须对应已验证候选，
  不能只验证一个动作却蒸馏整棵树。
- **信息隔离**：state_json 仅用于恢复引擎；世界必须从公开观测生成，隐藏字段重采样；
  验证 `observe(seat)`/mask 字节不变、RNG 可复现、动作续放一致；泄漏测试不过拒收。

### 4.4 与 PPO 的结合

```text
L = PPO clip(on-policy actor data)
  + c_v * value
  + c_π * CE(π_MCTS, π_θ)          # actor 数据中的 π
  + c_re * CE(π_reanalysis, π_θ)   # 做题目标（可选）
  + β * KL(π_θ || π_anchor)
```

- 重搜样本不进 PPO ratio（行为策略不同）；
- 只作为 policy/value 辅助目标，或生成“教师动作”做小比例 mixed 行为；
- 记录 `reanalysis_gain`、`policy_top1_vs_re`、`value_rmse`、`reuse_rate`；
- 预算：10–20% actor 时间做重搜；每 state K=1–4；sims_re=16–32。

### 4.5 验收

- 同一 state 重搜后 root value 提升 ≥δ 的比例；
- 重搜 π 与旧 π 的 top1 分歧率（10–30% 合理，过高说明搜索噪声）；
- 加入重搜后 cold-start gate/对 bot 名次在配对 500 局上显著改善；
- 计算开销 ≤20% 总训练时间。

## 5. PPO 与搜索结合（现状+改动）

- 默认 `behavior=net`（严格 on-policy）；MCTS π 作辅助 CE；
- `behavior=mcts` 只用于教师/冷启动，ESS 监控；
- KL anchor：冻结上一 stage 网络，`β·KL(π_θ||π_anchor)` 前 100 iter 退火；
  与 batch KL 早停分开（当前代码只有后者）；
- rank 分布 critic + 可选 scalar utility；`gamma=1`、终局 rank 时 `E[u]` 合法；
  报告 Brier/ECE；`step_penalty=0` 为主结果；
- forced EndTurn：已修（logprob=0、policy/aux 排除、value 保留）；
- 规模超参：lr 1e-4→6e-6 退火、minibatch 8192（或 1024 起）、clip 0.2、target KL 0.05、
  entropy 0.002–0.005、value 0.5、π 0.1。

## 6. 搜索/剪枝（保持安全）

- P0：PIMC + Rust 宏动作；P1：显式 chance 多子树/ISMCTS；
- 唯一生产后端 Rust；Python 只离线一致性测试；
- 默认只允许 L0 legal mask + 安全 L3（完整 hash/RNG/phase/seat）+ 批量叶；
- L1 top-k/L2 UCB/L5 早停 **默认关闭**，仅受控 ablation；
- 搜索内对手=bot 与真实 self-play 策略不一致：P1 更明确 opponent policy/chance；
- `search_every`/`behavior=net` 是对 D6“每步搜索”的显式变更，必须单列报告。

## 7. 评测与晋级

- 冷启动 gate 500 局、8 seat、固定 seed；league 成员同协议；
- 配对 bootstrap（按局/seed 聚类）；报告 mean rank、top4 Wilson CI、win、legal、truncation；
- 禁止用训练 seed 评测；eval seeds 独立；
- 晋级：C0→C1 需 gate；C1→C2 需对 C0/bot 不退化；每次 checkpoint 记录数据/模型 hash。

## 8. 实施计划

### P0（原型排期，不是承诺）
1. 多局/多树 actor 调度 + 批量叶 InferenceServer（B=64/128）；端到端 profiling；
2. entity 纯 PPO 同步基线（持续 Adam/调度器/RNG），至少 3 个训练 seed；
3. C0 vs bot 课程 + 正确 gate（配对 CI 上界<0、512 局、封存集复验）；
4. 可重放 state + 隐藏隔离/forced/logprob 测试；
5. 50k iteration 验收：无丢轨迹、decisions/s/leaf/s/GPU util/p95/显存/IO。

### P1（原型排期，不是承诺）
1. 无偏重搜（配对/LCB、K=1–2、≤10%）+ 同算力消融；
2. 同步 vs 异步（年龄/KL/ESS/拒收率），质量不退化才用异步；
3. 历史池/联赛（先单 learner + 冻结池，gate 后扩）；
4. KL anchor + scalar utility/校准；250k 稳定后才 1M。

### P2（2–4 周）
1. chance/ISMCTS、56-token/18M ablation；
2. 真实对手库适配层；
3. 1M/iter 稳定训练 + 长期评测。

## 8.1 P0/P1 验收（按终审优先级）

1. 恢复/隐藏隔离/forced/logprob 测试；同权重 ratio≈1。
2. entity 纯 PPO 同步基线，持续 Adam，≥3 seed，分别报数据量/wall-clock。
3. 多局 B 分布、leaf/s、decisions/s、p95、显存/IO；对逐叶基线，50k 无丢轨迹。
4. 全 bot vs 教师/弱 bot 课程，同算力，封存 512 局配对 CI + top4/win。
5. 重搜离线配对候选增益 + 隐藏泄漏；独立验证不过不蒸馏。
6. 无重搜 vs CE 重搜同算力消融；名次差 CI 上界<0。
7. 同步 vs 异步：年龄/KL/ESS/拒收率；质量不退化且总耗时下降才启用。
8. gate 复验后试历史池；对 bot/C0 不退化才扩联赛；250k 稳定后才 1M。

## 9. 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| entity 逐叶慢 | 吞吐不达标 | 批量叶、actor 并行、sims 小 |
| 重搜噪声 | 错误 target | 多次 W/seed 聚合、δ 阈值、辅助小权重 |
| 冷启动 bot 无信号 | 全 rank8 | 先 gate；若长期不过，加入弱对手/教师课程 |
| 异步 stale policy | PPO 偏差 | 版本分组、丢弃/降权、KL anchor |
| 重搜 off-policy | 不稳定 | 只作辅助 CE，不进 PPO ratio |
| 评测过拟合 | 虚高 | unseen seed、500 局、CI、8 seat |
| 状态存储 | 磁盘/IO | 压缩、采样、每局 32–64 state |

## 10. 当前状态（诚实边界）

| 能力 | 状态 |
|---|---|
| entity 14.8M | ✅ 已有；默认尚未切 |
| tiny 1h 试训 | ✅ 7.98→7.63（top4 0.78%，0 胜） |
| 异步 actor-learner | ❌ 未实现；当前串行 |
| 批量叶 | ❌ 未实现；Rust 逐叶回调 |
| 重搜“做题” | ❌ 未实现 |
| 冷启动 C0/C1 | ❌ 未实现 |
| KL anchor | ❌ 未实现 |
| league/对手库 | ❌ 未实现 |

## 11. 终审问题（交 GPT-6-Astra）

1. 重搜目标是否应进 PPO，还是只作辅助 CE？δ/权重/优先级如何定？
2. entity 14.8M + 异步 actor 的吞吐预算是否现实？1M 的最短 wall-clock？
3. 冷启动 gate（mean rank <4.75/top4>55%）是否合理？分裂联赛的触发条件？
4. 异步 stale policy 的安全边界（版本差/丢弃/降权）？
5. 状态存储/重搜成本与吞吐的平衡点？
6. 最关键的 3 个 P0 改动是什么？
