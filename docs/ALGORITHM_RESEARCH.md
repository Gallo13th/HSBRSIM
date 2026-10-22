# 算法调研与设计：面向 8 人酒馆战棋的 AlphaZero 类搜索

> 状态：**调研 + 设计**，不启动大规模训练。日期：2026-10-19。
> 范围：`hsbg/env`（Observation v2 / CandidateAction / VecEnv）、`hsrl2` 精确模拟器、
> `hsbg/policy`（实体 Transformer 1.24M）、`hsbg/train`（BC/PPO）、`hsbg/agents`（heuristic/teacher）、
> `hsbg/eval`、`hsbg/bridge`（Power.log/HDT 真实轨迹）。
> 结论先行：**采用「精确模拟器 forward model + PUCT/AlphaZero 式搜索 + 学习 policy prior +
> placement/rank 价值头」的路线；单人视角把 7 名对手视为带策略的随机环境；不使用 MuZero
> 学模型，也不采用 JEPA 风格决策器。** 当前第一阻塞是引擎缺少快速可分支的状态克隆接口
> （`deepcopy(Game)` 实测 150–600 ms / +43–64 MB），已在 §6 给出需要的接口与基准。

---

## 0. TL;DR

| 决策 | 选择 | 理由（本仓库事实） |
|------|------|------|
| 战斗子游戏 | **不搜索**，用引擎精确裁决 | `run_combat` 7v7 实测 1.63 ms；官方差分 `behavior_mismatch=0`、干净子集 100% |
| 招募阶段 | **精确模拟器 + PUCT**（先 macro 回合级，再 micro） | 已有确定性引擎、`enumerate_step` 0.015 ms、`build_observation` 0.25 ms |
| 是否 MuZero | **不选** | 已有精确模拟器；学模型会把模型误差叠加到引擎已知的 154 条 `missing_script`（历史非池卡为主，EXACTNESS_STATUS 2026-10-18）上；算力不划算 |
| 隐藏信息 | determinization + 对手模型 + 8 人 placement 值 | POMDP 边界见 `docs/ENV_SPEC.md` §7；观测只含上局对手战团/大厅公开信息 |
| 价值目标 | **名次分布 / 期望名次**（placement utility ∈ [-1,1]） | 与 `RewardConfig.placement` 一致；现有价值头就是 8 类 rank logits |
| 与 PPO/BC 关系 | BC 预训练 → 搜索自博弈生成 (π,z) → 蒸馏回策略/价值 → 可选 PPO | BC 4.06–4.34、teacher 4.24–4.30、PPO 4.4–4.6 未稳定超 BC |
| JEPA | **不采用**（至少当前阶段） | 不是决策算法；无样本效率/指标证据；当前瓶颈是搜索接口而非表征 |
| clone 现状 | clone **6.49 ms**（8p recruit，env-builder 2026-10-19）；目标 p90≤2 ms，差 ~3× | 决定 Phase1 预算：先 N=8–32 macro + 离线；实时大搜索/大规模自博弈等优化 |
| 先做原型 | 价值头离线训练 + MCTS 骨架 + 单回合搜索基准（§6/§7） | 不训练；先验证 clone/search 成本与价值信号 |

---

## 1. 问题结构分析（诚实版）

### 1.1 任务结构

| 维度 | 实际情况 | 证据/接口 |
|------|----------|-----------|
| 玩家数 | 8 人（可淘汰，人数递减） | `EnvConfig.num_players=8`；引擎 `game.heroes` 会原地删除被淘汰者 |
| 收益结构 | 名次线性 utility：`u=1-2*(rank-1)/(N-1)`，全员求和为 0（**8 人常和，不是 2 人零和**） | `RewardConfig.placement`（`hsbg/env/spec.py`） |
| 信息 | **部分可观测**：只能看自己完整信息 + 上一场对手战前战团 + 大厅公开信息 | `docs/ENV_SPEC.md` §7；`Observation.opponent_board` 来自 `game.last_opponent_warband()` |
| 随机性 | 商店刷新/卡池抽卡、对手策略、战斗内 RNG/攻击顺序、饰品/任务/异变 | 引擎唯一随机源 `game.rng`（`hsrl2/rng.py` `GameRNG`） |
| 动作空间 | 每步动态候选集合，`CANDIDATE_MAX=64`，12 类动作，含目标/位置组合；`choose` 是单独决策步 | `spec.py` `CANDIDATE_MAX/ACTION_KIND_INDEX`；`driver.enumerate_actions` |
| 决策步数 | agent 每局约 64–100 步（teacher/BC 轨迹）；每回合动作 ≤40；每回合候选 mean≈12.4、p90≈20、max≈34（实测） | 本次实测（seed=11，teacher，turn 9）：64 步、mean 12.4、max 34 |
| 回合结构 | 平均 13.55 回合；`end_turn` 是**宏动作**：驱动 7 名对手 → `game.end_recruit_phase()`（EoT+配对+战斗+幽灵+淘汰+下一回合） | `docs/ENGINE_RL_READINESS.md` §3；`docs/ENGINE_API.md` §6.1 |
| 每步成本 | teacher 轨迹 step mean 4.1 ms（p50 0.55、p90 11.9、p99 44；含 end_turn 波动） | 本次实测；环境目标 <5 ms/步（ENV_SPEC §8） |
| 模拟器精度 | 官方差分：strict MATCH **72.2%**、确定性战斗 **86.6%**、干净子集 **100%**、`behavior_mismatch=0`、`DATA_GAP=0`、`missing_script=154`（早期 FINAL_REPORT 快照为 72.3%/84.55%/246） | `docs/EXACTNESS_STATUS.md`（2026-10-18 快照）；`docs/FINAL_REPORT.md` §9.2 |

### 1.2 AlphaZero 假设逐条核对

AlphaZero 的核心假设是：**2 人、零和、完美信息、确定性、可反复访问同一状态、固定动作空间、每个状态都可用同一价值函数评估**。
对照本任务：

| 假设 | 是否成立 | 说明 |
|------|----------|------|
| 2 人 | ✗ | 8 人、可淘汰、人数递减（8→2）；配对/幽灵战使对手结构随回合变化 |
| 零和 | △ | 8 人按名次 utility 求和为 0（常和），但**不是两方零和**，不能做 negamax/两方 minimax |
| 完美信息 | ✗ | POMDP：对手当前战团/手牌/金币/饰品隐藏；引擎全状态只可作**特权教师**，不能进部署策略 |
| 确定性 | △ | 引擎给定 seed + 动作序列是确定性的；但存在商店抽取/战斗 RNG；搜索必须显式建 chance node，且 `GameRNG` 目前没有 `get_state/set_state` |
| 同一状态可反复访问 | ✗（当前） | 引擎没有 clone/fork/哈希；`deepcopy(Game)` 150–600 ms、+43–64 MB；动作以**当前观测槽位**引用，每步重算候选 |
| 固定动作空间 | △ | 每步候选动态 ≤64；可用 masked policy + candidate encoder 处理，但 PUCT 的 child 索引在节点间不固定 |
| 交替行动 | ✗ | 8 人同时招募；env 把对手建模为脚本，在 agent `end_turn` 时统一驱动 |
| 回合数固定/长 | ✗ | 平均 13.55 回合；比围棋短，价值函数必须承担“经济 vs 战力”的长期判断 |

**结论**：这不是标准 AlphaZero 适用域。可行形式是：

> **把 7 名对手视为带策略的随机环境（single-agent POMDP/MDP），对“自己的决策”做 PUCT；
> 对手动作/隐藏状态/商店/战斗作为 chance node 采样；价值目标是自己的 placement 分布；
> 在引擎克隆接口可用后用精确 forward model 做 macro（回合级）搜索，先不做 8 人联合 minimax。**

即“AlphaZero 式”的是：学习 policy prior + 学习 value + 模拟器 rollout + 搜索改进后蒸馏；
**不是**照搬两方零和 MCTS/negamax。

---

## 2. 候选算法与取舍

### 2.1 A. 战局内“战斗子游戏”：不搜索，用精确裁决

引擎已内置逐攻击、逐触发、逐死亡结算，且有官方轨迹差分：

- 单场战斗：`run_combat(hero_a, hero_b, alive_count)`；战后棋盘/监听器按快照复原，只有 PERSIST/Poet/伤害窗口例外（`docs/ENGINE_API.md` §6.2）。
- 成本：官方基准 clean `run_combat` **p50 1.47 ms / p99 4.57 ms**（`docs/ENGINE_RL_READINESS.md` §3.3）；本次 7v7 实测 **1.63 ms**。
- 精度：679 场真实 BG 战斗差分 `behavior_mismatch=0`、`DATA_GAP=0`、干净子集 100%；但 154 条 `missing_script`（历史非池轨迹卡为主）会造成 `ENGINE_DIVERGENCE`（`docs/EXACTNESS_STATUS.md`），搜索/训练应避开或降权这些卡。

**取舍**：战斗子游戏不建 MCTS 树（分支是攻击顺序 RNG，树宽大且引擎已足够快），只在
搜索叶评估/对手模型采样/价值辅助目标里调用：

1. **叶评估采样**：给定双方战团，`run_combat` 重复 K 次（K=4~8）得胜率/平局率/期望伤害，
   作为 value/auxiliary 特征；
2. **对手模型**：用历史 BC/真实轨迹中的战团分布 + 当前 tier/turn 采样对手战团，再用引擎裁决；
3. **训练辅助目标**：预测下场战斗胜率/受伤（不直接进主价值也可以作为辅助 head）。

注意：`run_combat` 会改英雄生命/战斗日志，不能在同一状态反复调用；需要 clone 或 rng fork（§6）。

### 2.2 B. 招募阶段：精确模拟器 + PUCT vs MuZero

**推荐：以引擎为 forward model 的 PUCT/AlphaZero 式搜索。**

- 宏动作（macro）：节点在回合边界，边是“本回合策略执行序列”；用策略网络/启发式生成 K 条候选
  回合方案（买/卖/打/升级/刷新顺序不同），每条 clone 后完整模拟到下一回合，价值头评估。
- 微观（micro）：节点是单个动作，候选 = 当前 obs.candidates；展开到回合结束再评估；分支数
  （mean 12/步、~30 步/回合）远大于宏动作，只适合深度小/预算低，或作为宏动作内的 1-ply 优化。

为什么不用 MuZero：

1. **已有精确模拟器**：`hsrl2` 是机制级 vendored 引擎，官方差分显示干净子集 100%；MuZero 的
   学模型只会引入额外近似误差（且要叠加 154 条 `missing_script` 与 72.2% strict match 的已知偏差）。
2. **算力**：MuZero 要学 dynamics/reward/policy 三个头并做 MCTS 训练，4050Ti 16GB 不划算；
   本仓库已有 1.24M 策略/价值可复用，直接接搜索最省。
3. **结构**：8 人、chance、动态候选、宏动作 `end_turn` 的 MuZero 建模（动作 embedding、奖励、
   support 分布）比“直接调引擎”复杂得多，收益不明显。
4. **可解释/可调试**：引擎搜索节点可回放、可与真实 Power.log 差分对齐；学模型黑盒不利于
   定位机制缺口。
5. **备选场景**：仅当 clone/search 成本无法降低、或要大规模离线 bootstrapping 时，才把
   “obs→latent 预测”作为 fallback 研究；当前不排期。

### 2.3 C. 隐藏信息处理

观测边界（`docs/ENV_SPEC.md` §7）：只能看自己、上一场对手战团、大厅公开信息；禁止把对手
当前手牌/金币/酒馆放进 obs。搜索要处理三件事：

1. **determinization（确定化）**：对每个“世界线”，按可见信息采样隐藏状态：
   - 对手当前战团：从历史战团分布（真实轨迹/BC/自博弈池）按 tier/turn/血量条件采样；
   - 对手手牌/金币/饰品：用对手模型（heuristic/teacher/历史策略）模拟到当前回合；
   - 商店/卡池：引擎 clone 后从当前 `game.rng` 派生子流采样（需要 rng fork）。
   建议 root K=4~8 条世界线；同一决策在世界线上共享动作先验、聚合 Q（“determinized PUCT”）。
2. **ISMCTS**：节点是信息集（我方观测 + 公开历史），不是隐藏状态；每条 world-line 独立维护
   访问统计再聚合。实现成本高于 determinization，但对抗“对手模型偏差”更稳；作为 Phase2 备选。
3. **对手模型**：7 个对手的策略未知且非对抗联盟。可选：
   - 训练时用脚本池（heuristic/teacher/历史 self-play 快照）作为环境；
   - 评估时用固定池 + 真人/真实轨迹复现；
   - 搜索时把对手动作视为环境随机性（采样对手策略），不做 minimax。
4. **8 人 placement 值**：价值头输出 8 类 rank logits（现有 `value_mode="distribution"`），
   搜索叶价值 = `E[placement utility]`（或直接用 rank 分布）；备份只累计“自己的期望 utility”，
   对手动作节点是 chance/policy 节点——这是一棵 **single-agent MDP 的 PUCT**，不是 minimax。

**特权教师 vs 部署策略**：引擎全状态（对手真实棋盘/手牌）可用于**训练期的 oracle 教师**
（类似 AlphaZero 用完美模拟器生成 target），但评估/部署只能用观测级策略；任何用隐藏信息的
搜索都必须在文档/评估里显式标注，避免“作弊指标”。

> **初始实现见 §3.6**：`hsbg/search/determinize.py` 的 `WarbandBank`（真实轨迹/BC 轨迹池采样）
> + 对手策略 rollout；Phase1 先 K=1，评估口径（战团分布匹配/战斗校准/oracle gap/泄漏检查）
> 见 §3.6；在 clone 优化前不展开 K=4/8。

### 2.4 D. 与现有 BC/PPO 的关系

现状（固定种子 100/300 评估，`docs/EVAL_REPORT.md` / `docs/FINAL_REPORT.md` §5）：

| 策略 | 平均名次 | 冠军率 | 前四率 | 来源 |
|------|----------|--------|--------|------|
| random | 7.85 [7.76,7.93] | 0% | 0% | seed 300–399 |
| heuristic（teacher 同源） | 4.30 [3.89,4.70] | 12% | 54% | 同上 |
| BC（320 局 / 30,300 样本） | **4.06** [3.69,4.47] | 9% | 62% | 同上 |
| PPO（多组） | 4.4–4.6（不稳定） | — | — | 未稳定超 BC |

另有 seed 100–199 的 TRAINING 表：random 7.80 / heuristic 4.24 / BC 4.34。**结论：BC 已接近
teacher，PPO 未稳定超过 BC；搜索是最有希望的“超越演示”方向。**

推荐路线（AlphaZero 式）：

```
BC 预训练（已有 policy/rank-value）
   → 搜索自博弈：用搜索改进 BC 策略，生成 (obs, π_search, z=placement)
   → 蒸馏/训练策略网：policy CE(π_search) + rank CE(z) + value/aux
   → 新策略作为搜索 prior，迭代（必要时加 PPO/league）
```

- **先 BC 预训练**：`runs/bc/official_320/policy_bc.pt`（1,241,354 参数，dim128/layers4，
  value_mode=distribution，rank 8 类）已可用于 prior/value 初始化。
- **搜索教师**：搜索 visit distribution 作为 π target（比 PPO 的 on-policy 样本更稳）。
- **蒸馏**：搜索只用于生成数据/教师；最终部署是观测级策略（不依赖引擎克隆）。
- **PPO 混合**：可将搜索 π 作为辅助损失/行为先验，或 PPO 初始化自搜索策略；短期不做。
- **辅助损失**：战斗结果/受伤/存活/经济（金币、tier）多任务，可缓解稀疏终局奖励。

### 2.5 E. 备选：1-ply/beam + value net，population/league

**1-ply/beam（Phase0 性价比最高）**：

- 对每个候选动作（或候选宏动作）clone→apply→value net，取 argmax；
- 成本：候选 mean 12.4 × (clone 目标 2 ms + apply ~0.07 ms + obs 0.25 ms + value 2–4 ms)
  ≈ 55–85 ms/决策（CPU），可接受；
- 若不做 clone，只能做“当前观测 value + policy prior”的 policy improvement（无 lookahead），
  对 BC 的提升有限——所以 1-ply 也依赖 §6 的 clone/snapshot 接口。
- 作用：作为 MCTS 的 baseline、验证价值头、快速消融。

**population/league（8 人环境常用）**：8 人局不是固定对手；用对手池（heuristic/teacher/历史
快照/BC/自博弈）+ 课程（先弱后强）+ 评估对抗不同池，能减少“只会欺负某脚本”的过拟合。
当前 env 只支持单 agent + 统一 `opponent` 脚本；需要 §6 的“按座位策略”接口才能做真正的
self-play league（或至少支持 `opponent` 从策略池采样/按回合切换）。

---

## 3. 设计蓝图（可实施）

### 3.1 状态/动作接口

**复用现有契约，不新增 obs 字段（v2 足够）**：

```python
# 现有（已验证可跑）
obs = env.reset(seed)                       # hsbg.env.spec.Observation (version=2)
step_actions = driver.enumerate_step(game, hero)   # 0.015 ms（实测）
obs = observation.build_observation(game, hero, step_actions.candidates, ...)  # 0.25 ms
enc = ObservationEncoder()                  # 39 entity slots, entity_dim 56, global 30, cand 38
batch = enc.collate([obs])                  # torch tensors, candidate_max=64
out = policy.forward_full(batch)            # policy logits + rank_logits(8) + value/E[rank]
```

- **宏动作/候选**：搜索节点需要保存“动作序列”而非仅当前候选（宏动作时）。建议统一抽象：
  `MacroAction = list[int]`（在当前节点逐步的候选下标，末尾必为 `end_turn`），执行前逐步
  `apply_action`；或 `MicroAction = CandidateAction`。
- **forward model**：引擎 `Game` + `driver.apply_action` + `game.end_recruit_phase()`；
  节点状态用 `Game.clone()`（待实现）或 `push_checkpoint/pop_checkpoint`（待实现）。
- **观测在每个节点重算**（0.25 ms）而不是缓存整棵树；“状态→obs/候选”是无副作用读取，
  可独立于 clone。

### 3.2 PUCT 公式与搜索细节

**选择（我方动作节点）**：

```
a* = argmax_a [ Q(s,a) + c_puct * P(s,a) * sqrt(N(s)) / (1 + N(s,a)) ]
```

- `P(s,a)`：policy prior（masked softmax，来自 BC/搜索蒸馏网络；未训练时可用 heuristic/teacher 频率）；
- `Q(s,a)`：单智能体期望 placement utility 的均值（不是 negamax）；
- `N(s)/N(s,a)`：访问计数；`c_puct` 初值 1.5–2.5，按评估标定；
- 叶节点价值：`v(s) = Σ_r P(rank=r) * u(r)` 或 `u(E[rank])`，其中 `u` 同 env 的 placement 奖励；
- 终局：直接 `u(rank)`；truncate：用价值头 + 惩罚。

**chance node（对手/隐藏信息/商店/战斗）**：

- 每个 macro 或 micro 边都可能消耗 RNG；搜索时对每条模拟采样一次 RNG 子流；
- 一条模拟 = clone 状态 + 从 `rng_state` fork 出独立流 → 应用动作/回合 → 战斗/淘汰 → 叶 value；
- 若 clone 不可用：暂用“同一 world-line 重放”不可行（单局 257 ms），所以 §6 接口是硬前提；
- 世界线 K=4–8；每个世界线内树独立，根聚合 `π(a)=Σ_w N_w(a)/Σ_w N_w`。

**价值 target**：

- 主 target：终局 `z = u(rank) ∈ [-1,1]`（与 `RewardConfig.placement` 一致）；
- 分布 target：rank one-hot 8 类（现有 rank CE head）；可加 HL-Gauss/软标签平滑；
- 中间 target：每回合 `Δhealth/Δboard_power` 不是最终目标，只做辅助；
- 多人：每个玩家自己的 utility 求和为 0，但价值头只学“自己名次”，不学对手值；对手由环境
  （脚本/模型）产生，不做 minimax 备份。

**深度/预算**：

- 第一版 **macro 搜索**：深度 1–2 个回合（≈13.5 回合/局，太深无必要），每条边是“本回合执行
  方案”；N 次模拟 = 32–64；K 世界线 = 4；
- 第二版 micro：只在本回合内展开 1–2 层，叶用价值头；macro 与 micro 可组合（macro 候选由
  micro 1-ply 生成）；
- 预算估算见 §4.2。

### 3.3 训练循环

```
初始化：BC policy/value (已有)
repeat:
  # 1) 生成：自博弈 / 对手池
  for game in sampler:
      K world-lines (仅训练期 oracle 或 determinization)
      for each agent decision:
          π = search(root)                     # PUCT + policy prior + value
          记录 (obs, π, z=None 占位)
      终局回填 z=u(rank) / rank one-hot
  # 2) 训练：replay buffer
  loss = CE(policy, π) + λ_rank * CE(rank_logits, rank) + λ_v * MSE(value, z) + aux
  # 3) 更新 prior/value；可选 distillation/league
```

- **对手池**：`heuristic` / `teacher` / `bc checkpoint` / 历史 self-play 快照；课程：前 20% 用
  heuristic/BC，之后逐步 teacher/self；每轮评估池固定，避免非平稳评估。
- **8 人座位**：env 目前仅 agent 座位 0 + 7 个脚本对手。完整 league 需要“按座位策略”接口
  （§6）；最小可行方案：随机化 `agent_index`/英雄，对手仍是池中策略（训练一个“任意座位”
  的通用策略），评估用固定种子。
- **数据格式**：复用 `hsbg/rl/api.EpisodeRecord` 或自建 JSONL/pickle（obs 可 pickle、候选可索引）；
  π 用稀疏候选下标+概率。
- **评估**：固定 seed 集 100 局（仓库已有 `hsbg/eval`：mean rank + bootstrap CI + rank 分布 +
  top4/win），对照 random/heuristic/teacher/BC/PPO；另测决策时间、搜索预算、invalid/truncated。
- **算力预算（RTX 4060 Ti 16GB + i5-12400F）**：见 §4.2；Phase2 建议 2–5k 局（4–10h），
  不做“大训练”。

### 3.4 与现有 `hsbg/policy` 复用

| 资产 | 现状 | 复用方式 |
|------|------|----------|
| `EntityTransformerPolicy` | 1,241,354 参数（dim=128, layers=4, heads=4, ff=256, vocab=3840, value_mode=distribution） | 直接作为 search prior/value；可在 checkpoint 上加 aux heads（需版本兼容） |
| `ObservationEncoder` | 39 entity slots；entity_num_dim=56；global_dim=30；cand_num_dim=38；candidate_max=64 | 不改；搜索节点重算 obs 后编码 |
| `forward_full` | 输出 policy logits（masked）、rank_logits(8)、value/E[rank] | prior = masked softmax；value = rank 分布 → utility |
| `act/evaluate_actions` | 已支持 masked 采样与 logp/value | 可作 rollout policy / 蒸馏目标 |
| BC checkpoint | `runs/bc/official_320/policy_bc.pt`（val acc 85.6%） | Phase0 直接初始化 prior/value |
| PPO 管线 | `hsbg/train/ppo.py`（GAE/clip/rank CE coef 0.5） | Phase3 可选混合；搜索 π 可作为辅助 target |

### 3.5 分阶段计划

| 阶段 | 内容 | 先决条件 | 验收/退出标准 |
|------|------|----------|----------------|
| **Phase 0**（无搜索） | ① 用现有 BC 数据离线训练/评估 rank/value 头（已有 BC checkpoint 自带 rank 头，可先评估校准）；② 价值头评估：rank CE、value MAE、用 value 排序候选的 action agreement；③ 单回合“无 lookahead”policy 评估 | 无（纯离线） | 价值头在验证集 rank CE ≤ BC policy 的随机基线（≈1.04? 用 log(8) 对照）；value 与真实 rank 相关系数 >0；不启动训练产出 |
| **Phase 1**（MCTS 原型） | 实现 `hsbg/search/mcts.py` 骨架（Node/PUCT/可注入 clone/forward_model/valuator）；单回合/单决策搜索基准；验证 clone/RNG/战斗接口；macro-K 候选；**先 macro 回合级、每决策 8–32 sims、K=1** | env-builder 提供 `Game.clone()`/RNG fork（§6）；当前 clone=6.49 ms 即可开始原型 | 见 §6.3 验收阈值：1-ply ≤20 ms/决策、N=8 ≤0.35 s、N=16 ≤0.7 s、N=32 ≤1.2 s（当前 clone 6.49 ms）；clone 优化到 p90≤2 ms 后收紧到 N=32 ≤0.5 s；搜索 π 合法/可复现；**不训练** |
| **Phase 2**（自博弈训练） | macro search 自博弈 + 蒸馏/rank value；对手池/课程；2–5k 局 | Phase1 通过；**clone p90 ≤2 ms 且 N=32 macro ≤0.5 s** | 固定 100 局评估 mean rank 相对 BC 提升 ≥0.3 且 CI 不重叠；top4/win 提升；无 invalid/挂死 |
| **Phase 3**（扩展/验证） | league/population、PPO 混合、真实轨迹（bridge）校准、规模扩展 | Phase2 有效 | 跨对手池稳定；在真实 Power.log 轨迹回放/差分上无系统偏差；评估报告归档 |

### 3.6 隐藏信息 determinization 初始实现（v0）

**目标**：让搜索在“看不见对手当前战团/手牌/饰品”的前提下，用**近似贝叶斯**的世界线采样代替
oracle 全信息；训练期 oracle 搜索只用于生成 target，评估/部署必须 obs-only。

**数据来源（按优先级）**：

1. **真实轨迹战团库**：从 `hsbg/bridge` 的 Power.log/HDT 解析出的真实对手战团（按 turn/tier/
   alive_count 分桶）；也可用 `runs/live/live_*/records.jsonl` 对应的 Power.log 离线重建；
2. **BC/teacher 轨迹池**：`runs/rl/heuristic_100.jsonl`、`runs/rl/lead_heur_40.jsonl`、
   `runs/rl/scale_8w.jsonl`、`runs/rl/bc_ckpt_16.jsonl` 等（按 turn/tier 采样 `opponent_board`
   或对手最终战团；注意：当前 JSONL 的 obs 摘要只含 `opponent_size`，没有对手棋盘 token/stats，
   需要采集器补 dump 或从 bridge 日志重建）；
3. **引擎自博弈生成**：在克隆局上让 7 个对手用 heuristic/teacher 策略从当前局面继续招募，
   得到“合理战团”，作为冷启动/兜底（成本 = 对手动作数 × rollout，需 bench）；
4. **对手策略池**：`heuristic` / `teacher` / `CheckpointPolicy(BC)` / 历史 self-play 快照；
   Phase1 对手池 = heuristic（最便宜）；Phase2 再扩。

**最小实现（`hsbg/search/determinize.py`，v0）**：

```python
@dataclass
class WarbandSample:
    turn: int; tier: int; board: tuple[EntityToken, ...]; source: str

class WarbandBank:
    def load(self, path: str) -> None: ...          # JSONL: turn/tier/board tokens
    def sample(self, turn: int, tier: int, rng) -> WarbandSample: ...

def determinize(model, bank, *, rng, oracle: bool = False,
                opponent_policy="heuristic") -> ForwardModel:
    """返回一个世界线：clone 当前局；oracle=False 时用 bank/对手池填充隐藏信息。"""
    m = model.clone()
    if oracle:
        return m                                    # 仅训练期 teacher，禁止用于评估
    for seat in range(1, 8):
        sample = bank.sample(m.turn, m.tier_of(seat), rng)
        if sample.board:                            # 有完整战团 token 才注入
            hidden.inject_hidden_state(m.game, m.hero_of(seat), board=sample.board)
    return m
```

- **Phase1 预算只开 K=1**（planning v1 clone 1.63 ms；Phase1 bench 验证 N=8–32 macro）；
- **现状（v0）**：`WarbandSample` 只有 ``turn/tier/size``（真实/BC JSONL 的 obs 摘要只有
  ``opponent_size``，没有对手棋盘 token/stats）；env-builder 已交付
  `hidden.inject_hidden_state`，但**没有完整 board 数据可注入** → 当前实现
  `mode="summary_only_uninjected"`、`injected_hidden=False`；评估必须按 oracle-gap 口径
  检查，不能把“摘要采样”当作真实隐藏信息；
- 对手手牌/金币/饰品：v0 不逐项采样；v1 再接入完整战团/手牌分布；
- **数据缺口**：需 bridge-analyst 从 Power.log 重建对手真实战团，或 env-builder 采集器
  补 dump `opponent_board` tokens/stats；否则 determinization 无法真正注入。

**评估口径**：

| 指标 | 定义 | 初版目标 |
|------|------|----------|
| 战团分布匹配 | 采样 vs 留出真实战团的 board_size/卡牌 id 分布（按 turn/tier 分桶），JS/KS | board_size JS < 0.1；卡牌 top-20 覆盖率 > 80% |
| 战斗校准 | 用采样战团跑 `run_combat` vs 真实下场战斗结果：胜率/伤害 MAE | 胜率偏差 < 5%；伤害 MAE < 2 |
| oracle gap | 同一 100 个状态：oracle 搜索 vs determinized 搜索的 π_top1 一致率 / Q 差 / 模拟对局名次差 | 名次差 ≤0.3（初始只报告，不阻断） |
| 泄漏检查 | 评估/部署路径是否读取引擎隐藏状态（board/hand of others） | 必须为 0；oracle 仅训练期 |
| 可复现 | 同 seed + 同世界线采样 ⇒ 同 π/动作 | 完全一致 |

**风险**：真实战团库数据量不足（尤其高 tier/后期）；v0 的对手 rollout 成本可能接近一次
`end_recruit_phase`（11.43 ms），K>1 时会压垮预算 → Phase1 只做 K=1，K↑ 留到 clone 优化后。

---

## 4. 实验设计与算力

### 4.1 baseline 与指标

**baseline**（仓库已有，固定 seed 集）：

| baseline | 平均名次（seed 300–399） | 备注 |
|----------|---------------------------|------|
| random | 7.85 | `hsbg/agents/random_agent.py` |
| heuristic | 4.30 | `hsbg/agents/heuristic.py` |
| teacher | 4.24（seed 100–199 表）/ 与 heuristic 同源实现 | `hsbg/rl/policies.py TeacherPolicy` |
| BC | **4.06** | `runs/bc/official_320/policy_bc.pt` |
| PPO | 4.4–4.6（不稳定） | `runs/ppo/*` |

**指标**：

- 主：`mean_rank` + 95% bootstrap CI（`hsbg/eval/metrics.py`）；
- 次：冠军率、前四率、rank 分布；
- 决策：每步决策时间/每局搜索时间/tokens（CPU & GPU）、搜索预算 N、世界线 K；
- 稳定性：invalid_actions=0、truncated 比例、单局崩溃=0；
- 真实一致性：在 bridge Power.log 轨迹上的动作/战斗结果差分（仅离线复核）。

### 4.2 搜索成本实测与可行性结论

> **更新（2026-10-19 v1 clone 优化版）**：下表是搜索原型**首轮**口径
> （`copy.deepcopy+共享 CardDB`，clone 6.49 ms）。env-builder 已交付
> `hsbg/planning` 快速 clone（结构化拷贝 + 闭包重绑），8p 招募期 clone 中位
> **~1.1–1.6 ms**、p90 **~1.8–2.0 ms**、heap **+202 KB**；最新权威数字见
> **§4.2.4**，`runs/planning_bench.json`（`scripts/bench_planning.py` 生成）。
> §4.2.1–4.2.3 保留为 6.49 ms 下的历史预算推导（Phase1 首跑已按该口径通过）。

#### 4.2.1 env-builder 首轮基准（2026-10-19，官方口径）

| 项目 | 实测值 | 备注 |
|------|--------|------|
| `Game.clone()`（8p recruit） | **6.49 ms** | raw `deepcopy` 158.9 ms = **24.5×**；heap 增量 **+209 KB** |
| `legal_actions()` | **0.036 ms** | 候选枚举（与本次独立测量 `enumerate_step` 0.015 ms 同量级） |
| `end_recruit_phase()` | **11.43 ms** | 完整宏回合（7 对手 + 战斗 + 淘汰 + 下一回合） |
| rollout 1 turn | **8.10 ms** | 一次完整回合展开（不含 clone） |
| 1000 × (clone + eval) | **6.5 s** | ≈6.5 ms/次 |
| 1000 × (clone + rollout) | **14.6 s** | ≈14.6 ms/次（6.49 + 8.10） |
| clone 目标 | p90 **≤2 ms** | 当前仍差 ~3×；env-builder 正做 checkpoint/push-pop 优化 |

#### 4.2.2 本机独立复测（用于交叉校验；不同测量环境，仅看量级）

| 项目 | 实测 | 备注 |
|------|------|------|
| `deepcopy(Game)` | 150–600 ms，+43–64 MB | 与 env-builder 的 raw deepcopy 158.9 ms 同量级 |
| `pickle(Game)` | **失败**（脚本闭包 `on_bind.<locals>...`） | 不能靠 pickle 做快照 |
| `_frozen_clone(minion)` ×7 | 0.15 ms | 只克隆随从，不能克隆整局 |
| `build_observation` | 0.25 ms | 节点重算 obs 很便宜 |
| `run_combat` 7v7 | 1.63 ms（官方 clean p50 1.47） | 战斗裁决便宜 |
| `end_recruit_phase` | 18.1 ms（官方 clean p50 10.7） | 与 env-builder 11.43 ms 一致量级 |
| policy forward batch=1 | CPU 2.1 ms / CUDA 3.9 ms | 1.24M 小模型，CUDA 启动开销占主导 |
| policy forward batch=8 | CPU 5.3 ms / CUDA 3.6 ms | 批量叶子评估更划算 |

#### 4.2.3 可行性结论（按当前 clone=6.49 ms）

记 `c=6.49 ms`（clone）、`r=8.10 ms`（rollout 1 turn）、`e=2–4 ms`（叶价值/策略前向），
则单次 macro 模拟成本：

- **clone + eval（浅层 1 步边界）**：`c+e ≈ 8.5–10.5 ms`
- **clone + 1-turn rollout + eval**：`c+r+e ≈ 16.6–18.6 ms`

| 预算 | 仅 clone+eval | clone+1-turn rollout+eval | 结论 |
|------|----------------|----------------------------|------|
| 1-ply（N=1） | 8.5–10.5 ms/决策 | 16.6–18.6 ms/决策 | ✅ 可行（离线/在线低预算） |
| N=8 macro | ~68–84 ms | ~133–149 ms | ✅ 可行（每回合一次决策也足够） |
| N=16 macro | ~136–168 ms | ~266–298 ms | ✅ 低预算可行 |
| N=32 macro | **~0.21–0.34 s**（Lead 口径 ≈0.21 s+） | ~0.53–0.60 s | ⚠️ 可离线用；实时回合内多次决策偏慢 |
| N=64 macro | ~0.42–0.67 s | ~1.06–1.19 s | ⚠️ 仅离线/教师数据生成 |
| N=1000 | **6.5 s** | **14.6 s** | ❌ 实时不可行；仅小规模离线实验 |

**结论**：

1. **实时完整搜索不可行**：clone=6.49 ms 下，N=32 macro 约 **0.21–0.60 s/决策**（取决于是否
   带 1-turn rollout），N=1000 = **6.5–14.6 s/决策**；30 s 回合计时内只能承受 **N≤16** 的低预算
   macro（或 1-ply），且一回合只适合做 1 次搜索。**离线/低预算可行**：N=8–32 可用于教师数据/
   原型；N≥32 的实时决策不做。
2. **离线/教师数据**：N=8–32 + 当前 clone 可跑；1000 sims/决策 = 6.5–14.6 s，
   64 决策/局 → 7–16 min/局/进程，**不适合大规模自博弈**；2–5k 局需先等 clone 优化。
3. **Phase 1 原型可以开始**：先做 macro 回合级、N=8–32、K=1；**不追求实时**，重点是
   验证 search 收益与成本曲线。
4. **Phase 2 前提**：clone p90 ≤2 ms（env-builder 目标；当前仍差 ~3×）；届时 1-ply 降到
   ~4–6 ms，N=32 macro（clone+eval）降到 ~130–200 ms/决策，8 进程自博弈才有工程意义。
5. 若 clone 优化失败（>5 ms p90）：MCTS 只做**离线小规模教师数据**，不做自博弈/实时；
   优先把预算投入价值头 + 1-ply/beam。


#### 4.2.4 env-builder clone v1 优化交付（2026-10-19，`runs/planning_bench.json`）

实现：`hsbg/planning/model.py::clone(strategy="fast")` = 结构化拷贝（共享
`CardDB`/`CardDef`/Enum/全原子 tuple-frozenset；不跑 `copy` 通用 reduce）
\+ **闭包回调重绑**（否则 quest/Listener 回调会把副本操作写回原对局）；另有
`checkpoint.push/pop_checkpoint`（clone 快照/独立恢复）、`digest`、`rng.get_state/set_state/fork`。

| 指标（8p 招募期） | 首轮（deepcopy+memo） | **v1（fast clone）** |
|---|---:|---:|
| clone p50 | 6.49 ms | **1.63 ms** |
| clone p90 / p99 | — | **1.75 / 2.66 ms** |
| clone heap 增量 | +209 KB | **+202 KB**（≤1 MB ✓） |
| raw `copy.deepcopy` | 158.9 ms | 151.7 ms（clone 快 93×） |
| clone 早期（T2） | — | **1.14 ms p50 / 1.25 ms p90** |
| clone 残局（T8） | — | 5.32 ms p50（晚期对象多，线性上升） |
| `legal_actions` | 0.036 ms | **0.029 ms** |
| `end_recruit_phase`（ERP） | 11.43 ms | **12.96 ms** |
| **快速 forward（只战斗裁决，不初始化下一回合）** | — | **3.51 ms**（ERP 的 ~1/4；`model.simulate_turn_combat`） |
| `run_combat` 2v2（含 clone） | — | 1.08 ms |
| `obs` 重算 | 0.25 ms | **0.16 ms** |
| RNG get/set/fork | — | **7.3 / 19.3 / 17.5 µs**（目标 ≤50 µs ✓） |
| N=8/16/32/64 搜索吞吐（clone+eval+1 动作） | — | **362/450/446/402 sims/s** |
| 确定性抽样（3 seeds × clone 同动作） | — | **PASS**（digest+RNG 一致） |
| 多人数（6/4/2）clone p50 | — | 2.53 / 0.96 / 1.65 ms |

**结论（更新）**：

1. clone 已达 **p50 ≈1.1–1.6 ms（early/M4）、p90 ≈1.8–2.0 ms、heap ≈0.2 MB**：
   Lead 目标 p50≤1.5/p90≤2.0 基本达成（机器负载会带来 ±30% 抖动；基准为 8p T4 9 次中位）。
2. **ERP 仍是 N 的瓶颈**（8p ~13–20 ms/次）；搜索叶节点改用
   `simulate_turn_combat`（**~3.5 ms**，只做战斗裁决）可把 forward 成本降 3–4×。
   若需要 ERP 本身更快，需引擎提供 `end_recruit_phase(skip_offers=True)` 类开关
   （profile：8 次 `_offer_trinkets` 的 pool 扫描约占 ERP 的 60–70%），属引擎改动，
   已按流程向 Lead 请示（未改）。
3. N=32 macro 成本（clone+turn_combat+eval）≈ 32×(1.6+3.5+~2) ms ≈ **0.23 s/决策**，
   在 Phase1 阈值（≤1.2 s）内；N=64 ≈0.46 s。
4. `GameRNG.get_state/set_state/fork` **~15–20 µs**（含 decisions 复制 404 条），
   满足 MCTS chance node 预算。
5. **Phase1 实测（`runs/search/phase1_bench.json`，8p T4，true MCTS + combat leaf）**：
   clone p50 **1.82 ms** / p90 **3.72 ms**（本机噪声；1000 次 clone+eval **2.43 s**）、
   ERP 9.76 ms、`simulate_turn_combat` 3.34 ms、1-ply 6.06 ms；
   N=1/8/16/32 决策 **41.7 / 119.6 / 191.2 / 336.4 ms**，全部在 §6.3 阈值内（见 §6.6）。

### 4.3 消融

| 消融 | 对照 | 观察 |
|------|------|------|
| 搜索预算 N | 0（BC）/1/8/32/64 | 名次/前四率 vs 决策时间曲线，是否存在“搜索边际收益” |
| c_puct | 0.5/1.5/2.5/4 | 探索-利用 |
| 价值头 | rank 分布 vs scalar value；BC 初始化 vs 随机 | 价值质量（rank CE、相关系数）与搜索收益 |
| 世界线 K | 1/4/8 | determinization 偏差；K↑ 方差↓ 但成本↑ |
| 对手模型 | heuristic / teacher / 历史池 / oracle | 对抗不同对手的稳定性（评估防过拟合） |
| 宏 vs 微观 | macro-K / micro-depth2 / 1-ply | 同样预算下名次/决策时间 |
| 真实轨迹校准 | 有/无 bridge 轨迹重放评估 | simulator 缺口对搜索策略的影响 |

### 4.4 风险与失败判据

| 风险 | 说明 | 缓解/判据 |
|------|------|-----------|
| 模拟器不精确 | 154 条 missing_script；strict match 72.2% | 用干净子集/高置信卡过滤；搜索 teacher 仅用于机制可信卡；评估离线真实轨迹差分 |
| 隐藏信息偏差 | determinization 采样不真实 → 搜索过拟合假想对手 | K↑、对手模型来自真实分布；评估用“确定性 oracle vs 采样”gap 监控 |
| 非平稳对手 | 8 人对手池变化 | 固定评估池 + league 课程；评估跨池 |
| clone 接口不可用/太慢 | Phase1 无法启动 | 先只做 Phase0 价值头；给出替代 snapshot/restore 接口指标 |
| 计算预算 | 4060Ti 16GB，搜索 + 自博弈慢 | 小预算 N/K、macro 优先、批处理叶评估、多进程；Phase2 2–5k 局封顶 |
| 收益不足 | 搜索提升 < BC | 失败判据：固定 100 局 mean rank 提升 <0.3 或 CI 重叠 → 回退 BC/PPO 路线，保留价值头 |
| 过拟合引擎伪影 | 引擎已知 bug/缺失脚本被策略利用 | 与真实轨迹/官方差分交叉验证；不把引擎特有漏洞当策略进步 |

---

## 5. 明确不采用 JEPA / MuZero 的理由

### 5.1 不采用 JEPA 风格决策器

- JEPA（Joint-Embedding Predictive Architecture）是**表征学习**框架：在 latent space 预测
  被 mask 的目标表征，用于自监督预训练；它本身不是序贯决策/搜索算法，不能直接产生
  “该买哪张/该不该升级”的策略或名次价值。
- 本任务当前瓶颈是：**精确模拟器已有、缺少可分支的快速 clone 接口、搜索/价值未验证**；
  表征学习不是瓶颈。把预算投到 JEPA 风格决策器上，短期内无法回答“能否超过 BC 4.06”。
- 若未来要做表征辅助，合理定位是：给 `ObservationEncoder` 加自监督辅助任务（masked entity/
  board 建模、对手战团预测）以改善样本效率，但需要单独的评估计划与算力；当前**不排期**，
  也不把它当决策器。

### 5.2 不选 MuZero（当前阶段）

- 已有 `hsrl2` 精确 forward model；MuZero 学 dynamics 的价值在于“没有模拟器”或“模拟器太慢/
  不可微”。本仓库环境 step ~4 ms、单局 257 ms，模拟器便宜。
- MuZero 的模型误差会与 154 条 `missing_script` 的已知偏差叠加，难以区分“模型错”还是“引擎缺口”。
- MuZero 的 MCTS 需要固定动作空间/离散动作 embedding；本任务每步候选动态（槽位引用）+
  `end_turn` 宏动作 + 8 人 chance，工程量大。
- 4060Ti 16GB 做 MuZero 训练+搜索不经济；同样的算力用于“精确模拟器 PUCT + 蒸馏”更直接。
- 何时重新考虑：如果 clone 接口无法做到 <2 ms 且引擎 macro step 无法优化，同时需要大规模
  offline bootstrapping，可再评估“latent model + search”作为 fallback（非当前优先级）。

### 5.3 搜索计算可行性依赖 env-builder 的基准数据

需要 env-builder（engine/env 负责人）提供/确认的接口与基准（这是 Phase1 的硬前提）：

1. **快速状态克隆/恢复**（二选一）：
   - `Game.clone() -> Game`：语义独立的深拷贝（heroes/board/hand/tavern/pools/queue/
     pending_choices/anomaly/trinkets/rng 等），共享不可变 `CardDB`；监听器/事件重建；
   - 或 `Game.push_checkpoint()/pop_checkpoint()`：原地应用动作后恢复；要求可嵌套/可重复。
   - 目标：**≤2 ms（p90）、≤1 MB 增量**；回归：clone 后独立 apply 动作互不影响、原状态不变、
     同 seed 两个 clone 轨迹一致。
2. **RNG fork**：`GameRNG.get_state()/set_state()` 或 `fork(seed)`；目标 <0.05 ms；
   支持搜索中每条模拟/世界线独立采样（商店/战斗/饰品）。
3. **无副作用战斗裁决**（可选但强烈建议）：`simulate_combat(board_a, board_b, seed,
   alive_count, damage_cap) -> CombatResult`（不修改主游戏；或明确只在 clone 上调用）；
   目标 ≤2 ms；用于叶评估 K 次采样/对手模型。
4. **按座位策略/对手池接口**（Phase2）：允许 7 个对手座位分别使用策略对象/历史快照，而不是
   统一 `opponent` 字符串；支持训练期 oracle 与部署期 obs-only 的切换。
5. **状态 digest（可选）**：`Game.digest()` 稳定哈希（turn+heroes+boards+hand+tavern 关键状态），
   用于 transposition/聚合；目标 <0.5 ms。
6. **基准数据**（统一输出 JSON）：
   - 每回合的 `clone`/`ERP`/`run_combat`/`enumerate_step`/`build_observation`/policy forward 耗时；
   - 在 8 人、6 人、4 人、2 人残局下的 clone/ERP 成本（状态规模变化）；
   - 单进程/8 进程的 macro-search 模拟吞吐（N=32/64、K=4）；
   - 内存：clone 后的进程 RSS 增量；
   - 单局 100 次的稳定性（无崩溃/无泄漏）。
7. **确定性验收**：同一 seed + 同一搜索动作序列 ⇒ 完全相同的 π/动作/结果（含 RNG fork 后），
   以便搜索可复现/可审计。

---

## 6. 最小原型计划（MCTS 骨架 + 单回合搜索基准）

> 只做骨架与基准，不训练、不接入正式 PPO/BC 训练管线；产物可丢弃/可演进。
> 建议目录（待建）：`hsbg/search/`、`scripts/bench_search.py`、`tests/test_search_*.py`。
>
> **范围（按 env-builder 首轮基准校准）**：先 **macro 回合级**、每决策 **N=8–32 sims**、
> 世界线 **K=1**；不做 micro 全宽树、不做自博弈训练。当前 clone=6.49 ms 下，N=8 约
> 0.07–0.15 s/决策、N=32 约 0.21–0.60 s/决策（见 §4.2.3）；Phase1 只验证成本/正确性/收益曲线，
> 不追求实时。clone 优化到 p90≤2 ms 后，再把 N=32 收紧到 ≤0.5 s/决策并考虑自博弈。

### 6.1 原型模块

```
hsbg/search/
  __init__.py
  types.py        # StateRef, MacroAction, SearchConfig, SearchResult
  forward.py      # EngineForwardModel：clone/apply_action/end_turn/current_obs/candidates/rng fork
  evaluator.py    # PolicyEvaluator：BC checkpoint → prior(obs,candidates)/value(obs)
  mcts.py         # Node/PUCT；chance node（K 世界线）；macro/micro 两种展开
  determinize.py  # WarbandBank + determinize（隐藏信息采样；oracle 开关；见 §3.6）
  rollout.py      # BC/heuristic rollout policy；macro 候选生成（K 条回合方案）
scripts/bench_search.py   # 单回合/单决策基准（§6.3），输出 JSON
tests/test_search_*.py    # 单元/回归/慢基准（默认 skip）
```

**协议（草案）**：

```python
class ForwardModel(Protocol):
    def clone(self) -> "ForwardModel": ...
    def apply(self, action: CandidateAction | int) -> None: ...
    def end_turn(self) -> None: ...       # macro transition（引擎 ERP）
    def obs(self) -> Observation: ...
    def candidates(self) -> Tuple[CandidateAction, ...]: ...
    def rng_state(self) -> Any: ...
    def set_rng_state(self, state: Any) -> None: ...

class Evaluator(Protocol):
    def prior(self, obs: Observation) -> np.ndarray: ...      # len == candidates
    def value(self, obs: Observation) -> np.ndarray: ...      # rank 分布(8) 或 utility
```

### 6.2 MCTS 骨架（伪代码）

**SearchConfig 默认（Phase1，按当前 clone=6.49 ms 校准）**：

```python
@dataclass
class SearchConfig:
    mode: str = "macro"          # 先 macro；micro 后置
    simulations: int = 16        # 8 / 16 / 32（Phase1 只跑这三档）
    world_lines: int = 1         # K=1；K=4/8 只在离线 bench
    c_puct: float = 2.0
    max_depth_turns: int = 2     # macro：最多推进 2 个回合
    max_macro_candidates: int = 4  # K 条回合方案（由 rollout policy 生成）
    temperature: float = 1.0
    time_budget_s: float = 0.6   # 单决策硬上限（Phase1）
```

```python
def search(root_obs, model, evaluator, cfg) -> SearchResult:
    root = Node(obs=root_obs, prior=None)
    for _ in range(cfg.simulations):
        # 1) 世界线：采样隐藏信息/对手模型
        m = sample_world_line(model, rng, cfg)      # 需 clone + rng fork
        obs = m.obs()
        path = []
        node = root
        # 2) 选择（PUCT），到未展开/终局
        while node.expanded and not node.terminal:
            a = puct_select(node, cfg.c_puct)
            m.apply(node.candidates[a])
            obs = m.obs()
            node = node.child(a) or node.expand(a, obs, evaluator.prior(obs))
            path.append((node, a))
            if node.depth >= cfg.max_depth or obs.phase == "game_over":
                break
        # 3) 叶价值
        if obs.phase == "game_over":
            v = utility(rank=terminal_rank(m))
        else:
            if cfg.macro and node.macro_boundary:
                m.end_turn()                       # macro transition
                v = expected_utility(evaluator.value(m.obs()))
            else:
                v = expected_utility(evaluator.value(obs))
        # 4) 备份（单智能体 Q，不做 negamax）
        for n, a in reversed(path):
            n.N += 1; n.Na[a] += 1; n.W[a] += v; n.Q[a] = n.W[a] / n.Na[a]
    # 5) 输出 visit 分布 / 温度采样
    return SearchResult(pi=normalize(root.Na), visits=root.N, best_action=argmax(root.Na))
```

### 6.3 单回合搜索基准（`scripts/bench_search.py`）

- 输入：固定 mid-game 快照（teacher/BC 跑 6–10 回合，保存 `Game` 或状态摘要；用 clone 接口）；
  另加 8 人 recruit / 6 人 / 4 人 / 2 人残局各 1 个快照，覆盖状态规模。
- 输出（JSON，按阶段拆解）：
  - `clone_ms` / `legal_actions_ms` / `obs_ms` / `forward_ms` / `erp_ms` / `combat_ms` / `rollout_1turn_ms`；
  - `N=1/8/16/32`（Phase1 不跑 64/1000；离线标定可选）的 `ms_per_decision`、`decisions_per_sec`；
  - 两种模式：`clone+eval`（1 步边界）与 `clone+rollout+eval`（1 回合 macro）；
  - `world_lines K=1/4` 的成本/方差（K=4 仅参考，不进 Phase1 验收）；
  - 与 BC policy top-1 一致率、search π 熵、叶 rank 分布、`invalid`/异常计数；
  - 1000 次循环的 RSS 增量（检查 clone 泄漏）。

**验收阈值（当前 clone=6.49 ms，env-builder 2026-10-19 基准）**：

| 项目 | Phase1 阈值（当前 clone） | clone 优化到 p90≤2 ms 后 |
|------|---------------------------|---------------------------|
| `clone_ms` p50 / p90 | ≤7 ms / ≤9 ms | **≤1.5 ms / ≤2.0 ms** |
| `legal_actions_ms` p50 | ≤0.1 ms | ≤0.1 ms |
| `erp_ms` p50 | ≤13 ms | ≤13 ms（独立优化） |
| `rollout_1turn_ms` p50 | ≤9 ms | ≤9 ms |
| 1-ply（N=1，clone+eval） | ≤20 ms/决策 | ≤8 ms/决策 |
| N=8 macro（clone+eval） | ≤0.35 s/决策 | ≤0.15 s/决策 |
| N=16 macro（clone+eval） | ≤0.7 s/决策 | ≤0.3 s/决策 |
| N=32 macro（clone+eval） | **≤1.2 s/决策**（Lead 口径 ~0.21 s+ 基于 6.5 ms/次，未含 rollout/叶） | **≤0.5 s/决策** |
| 1000 次 clone+eval 总耗时 | ≤8 s | ≤3 s |
| 1000 次 clone+rollout 总耗时 | ≤16 s | ≤11 s |
| 内存/泄漏 | 1000 次后 RSS 增量 <200 MB；无持续增长 | 同左 |
| 确定性 | 同 seed 两次运行 π/访问计数逐位一致；同 seed 两 clone 轨迹一致 | 同左 |
| 合法/正确性 | π 只在合法候选上（和=1）；macro 序列每步都是合法候选；无异常 | 同左 |

> 说明：Lead 给的 “32 sims macro search ≈ 0.21 s+” 对应 **仅 clone+eval**（6.5 ms/次×32）；
> 若每 sim 做 1-turn rollout（14.6 ms/次），N=32 约 0.47 s。bench 必须同时报告两种口径，
> 避免把“search 成本”与“rollout 成本”混在一起。
>
> **首次运行预期（当前 clone=6.49 ms，8p recruit 快照）**：`clone_ms` ~6.5、`legal_actions_ms`
> ~0.04、`erp_ms` ~11.4、`rollout_1turn_ms` ~8.1；N=8 约 0.07–0.15 s、N=16 约 0.14–0.30 s、
> N=32 约 0.21–0.60 s/决策；1000 次 clone+eval ~6.5 s、clone+rollout ~14.6 s。
> 这些预期值要在 bench JSON 中逐项对比，超 20% 需记录机器差异。


#### 6.3.1 env-builder 交付基准（`runs/planning_bench.json`，2026-10-19 v1）

`scripts/bench_planning.py --players-list 8,6,4,2 --turns 4 --endgame`
输出（每人数均含 early T2 / mid T4 / endgame T8 分离或合并；详细 JSON 见
`runs/planning_bench.json`）：

- clone：fast/deepcopy/raw 的 min/mean/median/**p90/p99**、heap 增量；
- forward：`legal_actions`、apply(buy/play/reroll/upgrade/end_turn)、
  `end_recruit_phase`、`simulate_turn_combat`、`obs_build`、`rollout_1turn`、`evaluate`；
- combat：战斗期 clone、`simulate_combat` 无副作用/可复现校验；
- rng：get_state/set_state/fork 成本 + 同状态同未来校验；
- search_throughput：N=8/16/32/64（clone+1 动作+evaluate）；
- memory：clone heap、RSS、连续 100 clone 的 RSS/泄漏；determinism：3 seeds 抽样。

验收（当前 8p T4 中位数）：clone **1.63 ms/p50、1.75 ms/p90**、heap **202 KB**、
ERP **12.96 ms**、turn_combat **3.51 ms**、N=32 **446 sims/s**、RNG fork **17.5 µs**、
determinism **PASS**。接口路径：
`from hsbg.planning import model, checkpoint, rng, digest, hidden`。

### 6.4 原型测试（不训练）

1. `clone` 隔离性测试：clone 后独立 apply 动作，原状态不变；两 clone 同 rng seed 轨迹一致。
2. PUCT 单元测试：固定假 model/evaluator，验证访问计数/备份公式/终局 utility。
3. macro 候选生成测试：K 条回合方案都合法（每一步候选包含在 obs 中，最后是 end_turn）。
4. 对 BC checkpoint 的 evaluator 冒烟：prior 形状 = len(candidates)，value 和=1。
5. 基准脚本回归：固定断言 clone/ERP 成本上限（CI 机器上可放宽；用环境变量
   `HSBG_BENCH_STRICT=1` 在专用机强制阈值）。

### 6.5 clone 优化到 p90≤2 ms 后的 Phase1 最小实现计划（不训练）

> 触发条件：env-builder 交付 clone p50≤1.5 ms / p90≤2.0 ms（或 checkpoint
> push/pop ≤0.5 ms）且 `rollout_1turn` ≤9 ms。满足后按下面清单落地；仍**不启动训练**。

**目录/文件（新增，均在 `hsbg/search/`）**：

```
hsbg/search/__init__.py
hsbg/search/types.py        # MacroAction(list[int]), SearchConfig, Node, SearchResult
hsbg/search/forward.py      # EngineForwardModel：clone/apply/end_turn/obs/candidates/rng fork
hsbg/search/evaluator.py    # PolicyEvaluator：BC checkpoint → masked prior + rank value
hsbg/search/mcts.py         # Node/PUCT/扩叶/备份（macro 优先；micro 可选）
hsbg/search/determinize.py  # WarbandBank + determinize（§3.6）；oracle 开关
hsbg/search/rollout.py      # macro 候选生成（K=4 条回合方案；BC/heuristic/随机扰动）
scripts/bench_search.py     # §6.3 基准脚本（JSON 输出，Phase1 不上训练循环）
tests/test_search_mcts.py   # 单元/回归测试（不依赖真实游戏）
tests/test_search_bench.py  # 慢测试：bench 阈值（标记 slow，默认 skip）
```

**最小实现顺序**：

1. `forward.py`：包 `Game.clone()` + `driver.apply_action` + `end_recruit_phase`；
   接口 `clone()/apply(cand)/end_turn()/obs()/candidates()`；异常/非法动作直接抛；
2. `evaluator.py`：加载 BC checkpoint，`prior()` = masked softmax（temperature 可调），
   `value()` = rank 分布 → `E[u(rank)]`；批处理叶评估（batch=8）可选；
3. `rollout.py`：生成 K=4 条 macro 动作序列（候选来源：BC 贪心、BC 采样、heuristic、
   当前 policy 采样）；序列末尾强制 `end_turn`；每步用 `candidates` 校验；
4. `mcts.py`：macro 根节点先展开 K 条 macro；每条模拟 = clone + 执行 macro + 叶 value；
   PUCT 选择；visit 分布输出；`N=8/16/32` 可配；`max_depth_turns=2`；
5. `bench_search.py`：按 §6.3 输出 JSON；固定快照（8/6/4/2 人各一）+ 1000 次循环；
6. `determinize.py`：先实现 **bank-only** 版本（K=1，无注入接口时跳过隐藏信息填充，
   用 oracle=false 的简化世界线）；bench 记录 determinization 耗时并单列。

**测试清单（Phase1 必须全绿，不训练）**：

- [ ] clone 隔离：clone→apply→原对象状态不变；两次 clone 同 seed 轨迹一致（`test_forward.py`）
- [ ] RNG fork：同 seed 两条世界线采样一致；不同 seed 分布不同（KS/方差合理）
- [ ] macro 序列合法性：K 条方案每步都是当前 candidates 之一，末尾 end_turn；非法序列被拒绝
- [ ] PUCT 数学：固定假 model/evaluator 下访问计数、备份 Q、终局 utility 精确匹配手算
- [ ] evaluator：prior 形状=候选数、masked 后和=1；rank→utility 单调
- [ ] 搜索确定性：同 seed 两次 `search()` 的 π/访问计数逐位一致
- [ ] 搜索预算：`N=8/16/32` 的 `ms_per_decision` 落在 §6.3 阈值内（慢机器用 strict 开关）
- [ ] 无泄漏：评估路径不读隐藏状态（oracle=false）；oracle=true 仅在训练/target 生成时允许
- [ ] 内存/泄漏：1000 次 clone+eval 后 RSS 增量 <200 MB；无异常
- [ ] 与 BC 对比：在 100 个快照上报告 top-1 一致率/π 熵，不做“更好”承诺（Phase1 只测）

**Phase1 出口标准**（不训练，仅架构建成 + 基准通过）：

1. `scripts/bench_search.py` 在固定快照上全部通过 §6.3 阈值（或记录超阈原因）；
2. 搜索可复现（seed）、无泄漏、无异常；
3. 输出一份 `runs/search/phase1_bench.json`（clone/ERP/rollout/N 档位/内存/确定性）；
4. 在 100 个快照上给出“search vs BC”动作/价值对比报告，供 Lead 决定是否进入 Phase2。

### 6.6 Phase 1 实测结果（2026-10-19，planning v1；不训练）

实现文件（已落地，`hsbg/search/`）：`types.py / forward.py / evaluator.py / rollout.py /
determinize.py / mcts.py` + `scripts/bench_search.py` + `tests/test_search_*.py`。
bench 命令（默认 8p T4、true MCTS、combat leaf、K=1、N=1/8/16/32）：

```powershell
python scripts\bench_search.py --out runs/search/phase1_bench.json --snapshots 100 --gain-snapshots 12
```

#### 6.6.1 成本（`runs/search/phase1_bench.json`，本机 CPU）

| 指标 | 实测 p50 | 阈值 | 结果 |
|---|---:|---:|---|
| clone（8p T4，含 warmup） | **1.82 ms**（p90 3.72；1000 次 clone+eval 2.43 s） | §6.3 当前口径 p50≤3/p90≤4 | ✅ |
| 1-ply（clone + BC eval） | **6.06 ms** | ≤20 ms | ✅ |
| `simulate_turn_combat` | **3.34 ms** | — | 比 ERP 9.76 ms 便宜 ~3× |
| N=1 / 8 / 16 / 32 macro 决策 | **41.7 / 119.6 / 191.2 / 336.4 ms** | ≤20 ms（1-ply）/ ≤0.35/0.7/1.2 s | ✅ |
| ERP 叶对照（N=8） | 173.2 ms（combat leaf 119.6） | — | combat leaf 快 ~1.4×；value 语义不同，未称等价 |
| 确定性 | π/visits/best 全一致 | 同 seed 逐位一致 | ✅ |
| 合法性 / 泄漏 | macro_legal=True、pi_valid=True、oracle_used=False、mode=none | 全满足 | ✅ |

> 说明：本机 clone 的 p90 3.72 ms 高于 env-builder 交付的 1.75 ms（机器/状态噪声），
> 因此阈值按本机实测口径取 p50≤3/p90≤4；env-builder 权威值仍以
> `runs/planning_bench.json`（1.63/1.75 ms）为准。

#### 6.6.2 search-vs-BC（100 快照）

| 配置 | top-1 一致率 | 说明 |
|---|---:|---|
| 默认（BC prior + BC-first macro） | **100/100** | **结构性**：macro 候选显式含 BC 首步，prior 也来自 BC logits → 不能当搜索有效性 |
| 对照（uniform prior + 无 BC-first macro） | **92/100** | 降低“喂答案”；剩余 8 例为搜索值改变选择 |

BC prior 很尖（root prior max 均值高、熵低），N=8 时 PUCT 常选 prior-top macro；因此
Phase1 **不宣称搜索优于 BC**，只验证系统/预算/可复现性。

#### 6.6.3 增益分析（12 快照，1-ply vs N=8/32、多 seed、Q 分布）

| 模式 | seed 稳定率（N=8） | 1→8 选择变化 | 8→32 选择变化 | N=8 Q spread | N=32 Q spread | N=8 prior-top 比例 |
|---|---:|---:|---:|---:|---:|---:|
| BC prior + BC macro | 1.00 | 0.00 | 0.00 | 0.136 | 0.259 | 0.83 |
| uniform prior + 无 BC macro | 0.50 | 0.50 | 0.50 | 0.433 | 0.452 | 0.50 |

解读：
- 默认模式下搜索选择高度稳定/贴近 BC → 说明是 prior 主导，**不是**搜索更强；
- uniform/no-BC 对照中，预算从 1→8→32 会改变一半快照的选择，Q spread 更大、seed 稳定率
  降到 0.5 → 搜索确实在利用 value 信息，但**Phase1 没有评估棋力收益**（需要 Phase2 自博弈+
  固定 100 局评测才能回答“是否改进 BC”）。
- 结论：Phase1 交付的是“可运行、可复现、成本达标、无泄漏”的 MCTS 骨架 + 评估工具，
  不是“搜索已超 BC”的证据。

### 6.7 无训练决策器 pilot（`hsbg/search/decision.py`，不训练）

用户指示“暂不训练，决策可设想为评分网络 + 纯搜索剪枝；先对比几种无训练决策器”。
实现（全部冻结、不更新权重）：

| 组件 | 实现 | 说明 |
|---|---|---|
| `BCValueScorer` | 冻结 BC checkpoint rank 价值头 | 8 类 rank logits → utility；BC prior 也来自同一冻结网络 |
| `CombatScorer` | `planning.simulate_turn_combat` | 引擎精确战斗裁决：胜负/伤害；无训练 |
| `HeuristicScorer` | `planning.evaluate` | 现有 heuristic/teacher 的棋盘/经济分 |
| `UniformScorer` | 均匀 | 对照 |
| `GreedyDecision` | macro 1-ply | K=4 macro 候选 → clone→apply→scorer→argmax |
| `BeamDecision` | W=2/4、D=1／2 回合 | macro beam，按 scorer 剪枝 top-W |
| `PuctDecision` | N=8/32、expand top-W=2 | 复用 §6 的 MCTS；BC scorer 用 BC prior，其余用 uniform prior |
| 剪枝 | `prune_candidates` / `prune_macros` | 去重、合法过滤、保留 end_turn、纯 end_turn macro 剪枝、上限；不改引擎语义 |

评测脚本：`scripts/eval_decision_gain.py`（同 seed 配对；对手 heuristic/teacher 交替；
20 局/cell；指标：mean rank/top4/win、配对 bootstrap CI + Wilcoxon、每决策/每局耗时、
动作改变率 vs BC top-1；K=1、oracle=False）。

**20 局/cell 正式矩阵结果**（`runs/search/decision_pilot.json/.md`；seeds 300–319，
对手 heuristic/teacher 交替；配对参考 `greedy-1ply+bc_value`）：

| 组合 | mean rank | top4 | win | ms/决策 | 配对 Δ vs 参考（95% CI） |
|---|---:|---:|---:|---:|---|
| **冻结 BC 策略基线**（非 macro 决策器） | **4.30** | **55%** | **10%** | ~2 | +1.75 [+0.40,+2.95] |
| PUCT N=32 + BCValue | **4.45** | 45% | **10%** | 738 | +1.60 [+0.30,+2.80] |
| greedy/beam + Heuristic | **4.55** | **50%** | 0% | ~100 | +1.50 [+0.25,+2.80] |
| PUCT N=8 + BCValue | 4.55 | 50% | 5% | 232 | +1.50 [+0.10,+2.70] |
| PUCT N=8/32 + uniform | 4.70–4.75 | 35% | 10% | 187–624 | +1.30–1.35 |
| uniform greedy/beam | 4.90 | 30% | 10% | ~100 | +1.15 |
| Combat（全部 decision） | 5.30–5.70 | 20–40% | 10–15% | 103–721 | +0.35–0.75（CI 跨 0） |
| greedy/beam + BCValue（参考） | 6.05 | 20% | 5% | ~135 | 0 |

**建议（基于本 pilot，非最终选型）**：
1. **没有无训练组合显著超过冻结 BC 策略**（4.30）：最好的 PUCT N=32+BCValue 为 4.45，
   CI 仍与 0 重叠，Wilcoxon p≈0.44（n=20，CI 很宽）；不能宣称“搜索改进 BC”。
2. **若看平均名次/吃鸡**：`PUCT N=32 + BCValue` 是唯一到 10% 吃鸡的组合，但 738 ms/决策，
   只适合离线/低预算；值得在 Phase2 用更多局（≥100）和更好 value 校准复测。
3. **若看成本/前四**：`greedy/beam + HeuristicScorer` 约 100 ms/决策、4.55/50% top4，
   是性价比最高的无训练候选；但 0% 吃鸡，上限可能有限。
4. **Uniform/Combat 不推荐**：Combat 只看单回合战斗结果、忽略经济/成长，5.3–5.7；
   uniform 是弱对照。Beam W=2/4 与 greedy 几乎相同（macro 候选少、深度 1，剪枝无增益）。
5. **BCValue 作为 scorer 的教训**：greedy/beam 下 BCValue 反而 6.05（macro 候选/价值头与
   macro 动作不匹配）；PUCT N=32 把 BCValue 拉到 4.55–4.45，说明“价值头 + 搜索”比
   “价值头直接贪心”更有希望，但需要更多验证。

> 边界：隐藏信息缺失（determinization 仅摘要）、K=1、oracle=False；所有分数/名次只来自
> 引擎环境，不等于真实客户端强度。pilot 只回答“哪种无训练组合值得进入下一轮”，
> 不是最终决策器选型结论。

### 6.8 硬搜索（train-free）pilot（`hsbg/search/hard_search.py`）

> **⚠️ 结论作废/仅作对照**：本节使用 macro 候选 + full-to-end/horizon3 叶（终局 rank），
> 不是用户最终要求的“单回合内状态间胜率”；正确形态见 §6.10。保留仅用于历史对照。

用户要求“硬搜索、不评分”：候选 macro → clone→执行→**rollout 到终局/高胜率**→选动作；
不使用 BC/价值网。实现：

- `HardSearchConfig`：candidates、rollout_budget、rollout_policy（heuristic/random）、
  max_horizon_turns、max_steps、prune、objective(utility/win)，以及两阶段
  `screen_horizon_turns / screen_rollouts / finalists / final_rollouts`；
- `rollout_to_terminal`：**默认 `backend="env"`** 走 env-builder
  `hsbg.planning.rollout_throughput.rollout_to_end(..., fast_opponents=False)`：
  对手正常买牌、所有座位用 heuristic 策略；返回 rank/win/top4/turns/steps/truncated；
  旧实现（对手不买牌）仅 `backend="legacy"` 对照，**不作为结论依据**；
- 选择：期望名次 utility（或胜率），successive halving 或“短 horizon 筛 top-2 + full 复核”；
  公共随机数按 stage 对齐；无 BC import/调用（测试断言）。

**成本实测（修正版，本机 8p T4）**：
- 单次 env rollout（正常对手买牌）：full-to-end **~443 ms**、horizon=3 **~62 ms**
  （env-builder `runs/planning_rollout_bench.json`；本机 1 局 demo 一致量级）。
- 修正版两阶段（4 候选、horizon=3×1 筛 top2、full×1）：**~0.7–1.0 s/决策**、
  **5 rollouts/决策**（4 短筛 + 2 full，部分候选被剪枝）；**6–9.6 s/局**；
- 5 局/cell 墙钟 **53s**（含 BC/greedy 基线）；3 局/cell 墙钟 **32s**，无 partial。

**修正版 5 局/cell 结果**（`runs/search/hard_search_pilot.json/.md`，seeds 300–304，
对手 heuristic/teacher 交替；env rollout 正常对手买牌、full-to-end；无 partial）：

| 组合 | mean rank | top4 | win | ms/决策 | rollouts/决策 |
|---|---:|---:|---:|---:|---:|
| 冻结 BC 策略基线 | **4.80** | **40%** | 0% | ~2 | — |
| greedy+heuristic | 5.20 | 20% | 0% | 89 | — |
| hard-search（horizon3 筛 top2 + full×1，env 正常对手） | 6.20 | 20% | 0% | **743** | **5.0** |

**20 局/cell 确认**（`runs/search/hard_search_confirm.json/.md`，seeds 300–319，
同 seed/对手，BC vs hard；墙钟 **205s**，无 partial）：

| 组合 | mean rank | top4 | win | ms/决策 | rollouts/决策 | 候选数 |
|---|---:|---:|---:|---:|---:|---:|
| 冻结 BC 策略基线 | **4.35** | **50%** | **10%** | ~2 | — | — |
| hard-search（修正版 env rollout） | 5.80 | 20% | 5% | **770** | **5.1** | 3.15（剪枝后） |

- 与 BC 配对差：**-1.45 名，95% CI [-2.45, -0.449]**（20 pairs；Wilcoxon p≈0.47，
  方向与 CI 一致，仍按“方向性/不宣称显著”报告）。
- **诊断**：
  - 动作改变率 vs BC 首步 = **28.9%**（hard 选的 macro 首步与 BC top-1 仅约 29% 不同）；
  - 候选集窄：剪枝后平均 **3.15 个** macro；生成来源为 **heuristic rollout + random rollout 变体**
    （`generate_macros_simple`；日志 source 统一显示 rollout），首动作分布以 buy(269)/sell(183)
    为主，缺少“整回合 BC 策略”候选；
  - 失败更可能是：候选空间窄 + horizon=3 筛选噪声 + full 仅 1 次，而不是 rollout 机制本身。
- **上一版（legacy rollout，对手不买牌）的 10 局结果（5.90 vs 4.50）作废**：
  那不是用户要求的“自对弈/正常对手 rollout”，不能作为“硬搜索无效”的证据。
- 结论：正常对手买牌 rollout 下，本实现 hard-search 仍比 BC baseline 差、成本高
  （770ms/决策）；20 局确认已足够给出“**不建议再扩 100 局**”的方向（若继续，应先修
  候选空间/筛选方差，而不是加局数）。
- 若坚持硬搜索，下一步用 env-builder `rollout_throughput` 批量/并行接口 +
  horizon1–3 筛 + top2 full（~1.2–2s/决策），并加入 BC/teacher 整回合候选、
  提高 full 重复次数；否则优先 “greedy+heuristic” 低成本 fallback（仍低于 BC 策略）。

**宽 beam 5 局/cell（W=4/8/16，`runs/search/hard_search_beamwide.json/.md`）**：
候选扩到 **8–16**（本次平均 **11.6**）：heuristic macro + **整回合 BC macro** +
random 变体 + **首步全动作枚举**（来源统计：first_step 460、random 114、heuristic 57、
bc_policy 31）；两阶段 horizon3×1 筛 top-W，再 full top-min(W/2,4)×1（env 正常对手）。
5 局 seeds 300–304，墙钟 **360s**（≤20min），无 partial：

| 组合 | mean rank | top4 | win | ms/决策 | rollouts/决策 | 候选数 |
|---|---:|---:|---:|---:|---:|---:|
| 冻结 BC baseline | **4.80** | **40%** | 0% | ~2 | — | — |
| beam W=4 | 6.00 | 20% | 0% | 1600 | 13.6 | 11.6 |
| beam W=8 | 6.00 | 20% | 0% | 2076 | 15.6 | 11.6 |
| beam W=16 | 6.00 | 20% | 0% | 2076 | 15.6 | 11.6 |

- **W 增大没有改善**（W4/8/16 名次完全相同）；诊断：BC 首步在候选中 **100%**、在 screen
  top-W 中 **100%**；动作改变率仅 **18.1%**；screen/full 均只 1 次 rollout，方差诊断不可用
  （单样本方差=0）；W16 的 full 被限制为 top-4，而 screen top-4 与 W4 top-2 的最终选择一致。
- 结论：**候选数量不是瓶颈**；当前候选质量/筛选信号（horizon=3 单次 rollout、full 单次）
  不足以改变选择；继续加大 W 只会增加成本（1.6–2.1s/决策），不改善名次。
  下一步应优先增加 rollout 重复（full≥2/3）与 horizon 对比、或引入更真实的对手模型/
  整回合 BC 候选的多样性，而不是继续加宽 beam。

**方差压缩验证 5 局/cell**（`runs/search/hard_search_variance.json/.md`，W=8，
env 正常对手，seeds 300–304，墙钟 **358s**，无 partial）：

| 组合 | mean rank | top4 | win | ms/决策 | rollouts/决策 | screen rank std | full rank std |
|---|---:|---:|---:|---:|---:|---:|---:|
| 冻结 BC baseline | **4.80** | **40%** | 0% | ~2 | — | — | — |
| hard-var h3 screen R=2 + full R=3 (top2) | 6.00 | 20% | 0% | 3615 | 29.2 | **0.0** | **0.0** |
| hard-var h1 screen R=2 + full R=3 (top2) | 6.00 | 20% | 0% | 2266 | 29.2 | **0.0** | **0.0** |

- **加重复次数没有改善**（仍 6.00，与单次 6.00 相同）；成本从 1.6–2.1s/决策涨到 2.3–3.6s/决策。
- 关键诊断：`screen rank std = 0`、`full rank std = 0` —— 因为当前 rollout 后端是**确定性
  heuristic（同 state 同 seed 结果完全相同）**，R=2/R=3 只是重复同一结果，**并未产生独立样本**；
  horizon 1 vs 3 也无差异（6.00），只影响成本（2.3s vs 3.6s/决策）。
- 结论：在 5 局样本下硬搜索无增益，**根因是 rollout 估计信号弱/确定性重复**，不是候选数或
  重复次数；需要**随机化 rollout（random policy/随机对手种子/噪声）或更强评估器**，再加预算，
  否则扩到 100 局也没有意义。

**随机化 rollout 5 局/cell**（`runs/search/hard_search_randomized.json/.md`，W=8，
screen h3 R2 + full top2 R3，seat/target 随机化，env 正常对手；墙钟 **355s**，无 partial）：

| 组合 | mean rank | top4 | win | ms/决策 | rollouts/决策 | screen std | full std |
|---|---:|---:|---:|---:|---:|---:|---:|
| 冻结 BC baseline | **4.80** | **40%** | 0% | ~2 | — | — | — |
| hard-random-seed（目标+对手 RandomEnginePolicy，rng fork） | 6.00 | 20% | 0% | **2124** | 29.2 | **0.71** | **1.30** |
| hard-epsilon-policy（heuristic + 15% 随机，对手同） | 6.00 | 20% | 0% | **3808** | 29.2 | **1.03** | **1.36** |

- 随机化成功：screen/full std 已 **>0**（0.71–1.03 / 1.30–1.36），不再是重复同一样本；
  但 5 局名次仍 **6.00**（与确定性单次/R=2/R=3 完全相同），无改善。
- 诊断：BC 首步在候选/top-W 仍 **100%**，动作改变率 18.1%，候选 11.6；即随机化并未让
  搜索选出不同/更好的 macro；可能原因：rollout 估计信号弱（heuristic/random 自对弈与真实
  对手/BC 策略差异大）、候选 macro 的质量/收益差异小、5 局样本不足以分辨。
- 结论：在 5 局样本下**随机化后仍无增益**；硬搜索需要**更强评估/对手模型、更多预算或更好
  候选空间**，不建议扩 100 局。后续若要继续，先做“同状态候选的 rollout 收益分布”诊断
  （是否真的存在显著更优候选），再决定是否加预算。

**状态级信号诊断**（`scripts/diag_hard_signal.py` → `runs/search/hard_signal_diag.json/.md`）：
10 个决策状态（turn 3/6/9），每状态候选 4–12（平均 8），每候选 full-to-end **R=5**
随机化 epsilon rollout；对比候选均值差、噪声（std/√R）、BC 首步 lift、配对 CI。
成本 **98s**。

- 候选间存在超过噪声的差异：**9/10** 状态 `max-min mean > max noise`；平均 max-min **1.80**
  vs 平均 max noise **0.93** → rollout 能在同一状态内区分候选。
- 但 **BC 首步已接近最优**：平均 BC-first lift 仅 **0.5 名**；lift>1 名仅 **2/10**；
  “显著优于 BC 首步”（均值>1、配对 bootstrap CI>0）仅 **1/10**。
- 结论（按用户口径）：**当前纯 rollout 硬搜索相对 BC 没有可利用的显著信号**——候选间有
  信号，但不足以稳定超过 BC 首步；要做搜索需要更强评估器/对手模型/训练价值网络与更多预算，
  而不是继续扩宽 beam 或增加重复。BC 仍是更强的无训练决策器。

### 6.9 动作级 micro-PUCT（`hsbg/search/micro_mcts.py`，train-free）

> **⚠️ 结论作废/仅作对照**：本节叶评估用 horizon3/full-game rank，不是“单回合状态间胜率”；
> 正确形态见 §6.10。保留仅用于历史对照。

针对“单回合内逐动作树搜索”实现：

- 节点 = 一个动作后的状态；边 = 当前合法 `CandidateAction`；
- 每决策：root clone → PUCT 选择 → **只展开 top-W 动作**（按 BC policy prior），
  其余合法动作保留为 `all_actions` 未展开边 → 叶用 `rollout_to_end`（env 正常对手，
  horizon=3 截断）评估 → 备份单智能体 Q；
- N=8、W=8、max_depth_actions=6；执行 root 最优动作后重新取 state 继续；
- 不训练、无价值网评分（BC 仅用于 prior；叶 value 来自 rollout 名次）、无 oracle。

**5 局/cell pilot**（`runs/search/micro_mcts_pilot.json/.md`，seeds 300–304，
heuristic/teacher 交替；墙钟 **424s**，无 partial；叶子 horizon=3，非全终局）：

| 组合 | mean rank | top4 | win | ms/决策 | sims/决策 | decisions/局 | 动作改变率 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 冻结 BC baseline | **4.80** | 40% | 0% | ~2 | — | 93.4 | — |
| micro-PUCT N=8 W=8 h3 | **4.60** | **60%** | **20%** | 1073 | 8.0 | 75.0 | **1.2%** |

- 配对差：**+0.2 名**（CI [-2.2,+2.8]，p≈0.8）；top4/win 方向更好，但 5 局样本小，
  **不能宣称显著**。
- 关键 caveat：**动作改变率只有 1.2%**——动作级树在 8 次模拟下几乎总是选回 BC top-1，
  因此名次差异很可能来自执行/样本噪声；要验证搜索增益需要更多模拟（N≥16/32）、
  更深/更宽探索或更强的叶评估（full-to-end 而非 horizon3）。
- 成本：单局 37–145s（个别 >60s），5 局 424s；每决策 1073ms/8 sims；若扩到 20 局需 ~28min，
  不建议在无增益证据前扩。
- 结论：动作级 micro-PUCT 是**正确的搜索形态**，但当前 N/W/horizon 下仍未显示“搜索优于 BC”；
  下一步应加 N/深度、full-to-end 叶、更强 prior/value 再评估。

**N=32 强预算尝试（预算受限，未完成 3 局）**：
- 按“N=32/W=8/horizon3 + root top-2 full 复核”跑 1 局，**单局 >600s**（未跑完即终止），
  远超 30min 预算；n=32 的动作级 micro-PUCT 在未优化实现中成本过高。
- 按降级规则改跑 **N=16/W=4/horizon3（无 full 复核）1 局**：
  BC 名次 6，micro 名次 3；`3007 ms/决策`、16 sims/决策、96 decisions/局、**290s/局**，
  **动作改变率 1.0%**（仍 <5%）。n=1，不能作结论；但“动作几乎不变”与 N=8 一致。
- 结论：**当前实现下 N=32 不可在 30min 内完成 3 局**；N=16 单局动作改变率仍 ~1%，
  说明即使加预算，在 horizon3 叶 + BC prior 下搜索仍基本复述 BC top-1。
  要实现用户要的“N=32 动作级搜索”，需要先优化树/prior 缓存与叶评估（或并行/GPU），
  并考虑 full-to-end 叶；否则时间预算内不可行。

### 6.10 回合内自枚举 + 两两胜率搜索（`turn_search.py`，按用户澄清）

用户澄清：搜索应**只搜当前回合**，每步选“当前回合所有可能状态彼此胜率”最高的动作，
不是 horizon3/full-game rank rollout。实现：

- `enumerate_turn_states`：从当前动作出发，用 heuristic/BC/random 完成本回合到
  `end_turn` 前的状态（**不执行 end_turn 推进**，断言 `turn == root_turn`）；状态数预算；
- `pairwise_winrate_matrix`：对枚举状态做两两战斗（`run_combat`/`simulate_turn_combat`，
  公共 seed；状态数多时按预算采样 pair），`score(s)=mean_{t≠s} winrate(s,t)`；
- `TurnSearch.decide`：每个当前动作 a → 执行 a（不推进回合）→ 枚举可达状态 → 取可达状态的
  max/mean 分数；选 argmax；执行后在**新状态再搜下一步**（receding horizon），直到 end_turn；
- 无价值网/无名次/无后续回合模拟；`--states-budget 16`、`samples_per_action=1`、
  `combat_samples=1`。

**5 局/cell pilot**（`runs/search/turn_search_pilot.json/.md`，seeds 300–304，
heuristic/teacher 交替；墙钟 **771s**，无 partial）：

| 组合 | mean rank | top4 | win | ms/决策 | states/决策 | combats/决策 | 动作改变率 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 冻结 BC baseline | **4.80** | 40% | 0% | ~2 | — | — | — |
| heuristic 无搜索 | 7.80 | 0% | 0% | ~0.2 | — | — | — |
| **turn-search（回合内两两胜率）** | **3.80** | **80%** | 0% | 1255 | 11.4 | 61.1 | **73%** |

- 配对差 vs BC：**+1.0 名**（CI [0.0, 2.2]）；**无 scipy 时的符号检验 p=0.5**
  （修正：之前误报 p≈0.03，因 fallback 公式错误；已修脚本/报告）。5 局只作方向性证据，
  但这是**首次出现动作改变率 >5%（73%）且指标方向一致改善**的搜索形态。
- 单局 52–228s；每决策 0.5–1.5s；状态数 11.4、combats 61.1（未达 16/120，因枚举去重/提前 end_turn）。
- **10 局确认（实际完成 7 局，max-wall 超时 partial）**：`turn_search_confirm.json/.md`
  seeds 300–306；BC 4.50/50%/10% vs turn-search **3.14/86%/14%**；
  配对差 **+1.43，CI [0.29,2.86]**，符号检验 **p=0.25**（3 个非零差全为正）；
  动作改变率 **75%**、1356ms/决策、states 11.8、combats 66.2；墙钟 1693s（有一局 594s）。
  n=7、p=0.25，**方向一致但不宣称显著**；仍值得扩到 20 局确认。
- **20 局确认（states_budget=8，并行 2 进程）**：`turn_search_confirm20.json/.md`
  seeds 300–319；BC **4.35**/55%/10% vs turn-search **3.70**/75%/5%；
  配对差 **+0.65，CI [-0.65,+1.90]**，精确符号检验 **p=0.63**；
  动作改变率 **71%**、ms/决策 485、states 7.5、combats 23.6；墙钟 **842s**（未 partial）。
  - **信号较 states16 的 7 局（+1.43, CI>0）减弱**：states8 下 CI 跨 0、p=0.63 →
    不满足“强方向证据”标准；说明效果**依赖状态枚举预算**（budget sensitivity）。
  - top4 75% vs 55% 方向仍正、动作改变率 71%，但平均名次优势变小。
- **20 局确认（states_budget=12，4 进程并行各 5 局）**：
  `turn_search_confirm20_s12.json/.md`，seeds 300–319；分进程墙钟 552–877s（<25min），未 partial：
  | 组合 | n | mean rank | top4 | win | ms/决策 | states/决策 | combats/决策 | 动作改变率 |
  |---|---:|---:|---:|---:|---:|---:|---:|---:|
  | BC baseline | 20 | **4.50** | 45% | 10% | ~2 | — | — | — |
  | turn-search s12 | 20 | **3.65** | **70%** | **15%** | 928 | 10.0 | 44.3 | **75%** |
  - 配对差 **+0.85，CI [-0.45,+2.20]**，精确符号检验 **p=0.63**；动作改变率 75%。
  - 介于 states8 (+0.65) 与 states16 7局 (+1.43) 之间，仍 **CI 跨 0**；未达“强方向证据”标准。
- 结论：**正确目标（回合内状态间胜率）下搜索有明显动作改变（71–75%）和 top4 方向收益**，
  但 states8/12/16（20/20/7 局）均**未达统计显著**（p≈0.6 或 n 太小）；效应依赖状态预算，
  需训练价值网/更多预算/更大样本；当前以“**有希望但未证实**”收口。

**最终收口（用户决定；2026-10-20 更新）**：
- 单回合自枚举 + 状态间两两胜率是**正确形态**；动作改变率 71–76%、top4 明显高于 BC；
  states8/12（20 局）配对差 +0.65/+0.85 且 CI 跨 0；**states16（20 局）配对差 +1.05，
  CI [0.35,1.80]，精确符号 p=0.0034 → 升级为“强方向证据”**（见 §6.14）；
- 不再扩 50 局是**此前决定**；states16 20 局结果后是否扩 50 局由用户/Lead 决定；
  代码保留（`hsbg/search/turn_search.py` 等）作为后续评估基础设施；
- 旧 macro/hard-search/horizon3 micro-PUCT 结论（§6.8/§6.9）**作废/仅作对照**：它们用
  terminal rank/horizon3 叶，不是用户要求的单回合状态胜率，不能作为“搜索无增益”的证据；
- **value head 边界（用户 2026-10-19 澄清）**：value 只能用于枚举/候选的中间排序与
  **剪枝**（如 `value_prune_pairwise(K=4–6)`）；每次 `decide` 的**最终 argmax 必须来自
  finalists 的 pairwise 真实战斗胜率**，value 分不能直接当最终分；
- 下一步见 `docs/VALUE_NETWORK_PLAN.md`（value 训练用于剪枝/加速；最终动作仍 pairwise）。

### 6.14 全 pairwise turn-search states=16 确认（2026-10-20）

- **20 局**：4 进程并行各 5 局（seeds 300–319，heuristic/teacher 交替），states_budget=16、
  samples=1、无 value 评分/剪枝；分进程墙钟 543–1270s。
  结果：BC **4.40**/50%/10% vs turn-search **3.35**/80%/15%；
  **配对差 +1.05，CI [0.35,1.80]**，精确符号检验 **p=0.0034**；
  动作改变率 **75.7%**、941.8 ms/决策、combats 64.9/决策。
- **50 局**：6 进程并行（seeds 300–349，heuristic/teacher 交替；9/9/9/9/8/6 局），
  分进程墙钟 1233–2000s。结果：BC **4.22**/58%/8% vs turn-search **2.90**/86%/30%；
  **配对差 +1.32，CI [0.80,1.82]**，精确符号检验 **p=4.26e-6**；
  动作改变率 **74.9%**、1132.7 ms/决策、combats 64.2/决策。
- 对比：states12（20局）3.65 vs4.50，+0.85 [−0.45,2.2] p=0.63；states16 信号明显更强，
  符合“更大状态枚举 + 最终 pairwise”的方向。
- 结论：**满足“Δ≥+1 且 CI 不跨 0”的强方向证据，50 局进一步确认（p≈4e-6）**；
  建议与 PPO/接口对接前再做跨对手集验证；产物
  `runs/search/turn_search_confirm20_s16.json/.md`、
  `runs/search/turn_search_confirm50_s16.json/.md`。
- **跨对手 10 局**（seeds 350–359，heuristic/teacher/random 循环；env 无 BC 对手）：
  BC **4.20**/50%/20% vs turn-search **1.70**/90%/70%；
  **配对差 +2.50，CI [1.30,3.70]**，精确符号检验 **p=0.0078**；动作改变率 77.8%、
  1035.7 ms/决策；状态 12/决策。产物 `runs/search/turn_search_crossopp_s16.json/.md`。

### 6.11 Phase1 value head + value-prune-pairwise（2026-10-20）

- 训练：冻结 encoder，只训 rank_head；`runs/value_data/turn_search_20k.pkl`
  （21,240 样本/140 局；split 98/21/21：14,981/3,365/2,894）；
  batch64/lr1e-3/30 epochs，seed0 **134s**；seed1/2 约 148s（稳定）。
- 同一 val：新头 MAE **1.276**、CE **2.346**、AUC **0.774**、ECE **0.011**；
  旧 BC value head MAE 1.517、CE 4.229、AUC 0.760、ECE 0.194。
  test：新头 MAE 1.352、CE 1.981、AUC 0.716、ECE 0.231；旧头 MAE 1.754、CE 4.213、
  AUC 0.746、ECE 0.329。
- 剪枝质量：value vs pairwise 状态分 **Spearman=-0.064**（n=243）；同状态动作一致率
  K4 **75%**、K6 **100%**（20 decisions）。远未达“剪枝不损 pairwise 排序”的标准。
- 5 局（seeds 300–304，states8/12）：见 `turn_search_value_prune_trained.json/.md`：
  states8 pairwise 3.60 vs K4 4.00/K6 3.40；states12 pairwise 2.20 vs K4 3.40/K6 3.80；
  剪枝 ms 降 1.2–1.8×、combats 降 40–75%，但名次不稳定；**不扩 states16/24、不扩 20 局**。
- 结论：value 训练成功但排序一致性不足，当前只能做加速/剪枝候选；最终动作仍由 pairwise
  决定（`final_choice_by_pairwise=True`）。下一步先提升 value-pairwise 一致性或保留全 pairwise。

### 6.12 当前回合相对强度 value head（pairwise 胜率标签，2026-10-20）

- 目标修正：终局 rank 与 turn-search 当前回合强度错配（§6.11 Spearman -0.064）。
- `scripts/build_winrate_labels.py`：20,749 个有 board 状态，同 `(turn,tier)` 采样 K=8 对照，
  `run_combat`（公共 seed）标签=平均胜率；label mean 0.501/std 0.306；全量 344.5s。
- `scripts/train_value_winrate.py`：冻结 encoder，只训 scalar_head（MSE+BCE）；seed0 112s；
  held-out val Spearman **0.511**、MAE 0.225、AUC 0.741；test Spearman **0.512**、AUC 0.747；
  旧 BC value head 仅 val 0.361/test 0.386 → 标签拟合达到 >0.3 目标。
- **但本地 turn-search 状态上 value vs pairwise Spearman 仍 -0.007**（n=243），K4/K6 动作一致率
  85%/100%；5 局：states8 pairwise 4.20 vs K4 3.20/K6 5.60；states12 pairwise 2.20、
  K4 2.60、K6 3.40；剪枝 ms 降 ~1.8×、combats 47→5/13，但 states12 top4 80% vs 100%，
  **仍不算“不掉点”**。
- 结论：标签目标正确，但离线状态池与本地搜索状态/对手池分布不一致；需 B 路线（采集时记录本地
  pairwise 矩阵）或对齐采样后重训；**不扩 states16/24/20 局**。最终动作仍 pairwise。

### 6.13 B 路线：本地 pairwise 标签 value head（2026-10-20）

- `TurnSearchConfig.record_trace=True` 记录本地枚举 state（obs/board/score）+ pairwise 矩阵；
  `scripts/collect_localpair.py` 6 workers/150 episodes/每回合最多1决策/states8：
  **13,008 states**（7–8/决策），wall 2075s。
- `scripts/train_value_localpair.py`（冻结 encoder、只训 scalar_head；MSE/BCE）：
  split 9,146/1,926/1,936；**held-out 本地 pairwise Spearman val 0.304 / test 0.224**
  （晚回合 6–12 仅 0.02–0.17；1–4 回合 0.4–0.7）；旧 BC value head 0.080/0.057；
  ranking-loss 变体 .306/.218，无提升。
- 动作一致率 states8：K4 90%、K6 95%；5 局：
  states8 pairwise 4.00/80% vs K4 6.40/0%、K6 4.40/60%；
  states12 pairwise 2.20/100% vs K4/K6 3.40/60%；ms 1.2–1.7×、combats 47→5/13，
  但 rank/top4 明显掉点。
- 结论：本地标签链路可用但 value 仍不够；**不扩 states16/24/20 局**，后续需更强特征/晚回合
  训练/对手池，否则保留全 pairwise。

---

## 7. 下一步需要的接口/基准（给 env-builder 的最终清单）

> 现状（2026-10-19 planning v1 已交付）：clone **1.63/1.75 ms**、checkpoint push/pop、
> RNG fork 17.5µs、无副作用 `simulate_combat` 1.24ms、`simulate_turn_combat` 3.51ms、
> `digest` 0.2ms、`hidden.inject_hidden_state` 已就绪；**剩余**：determinization 的完整
> 对手战团数据（当前 bank 只有 size）、按座位对手池、ERP skip_offers（未获批准）。
> 下列清单保留为验收基准；已交付项见 §4.2.4/§6.3.1。

1. **快速 clone / checkpoint（最高优先级）**：
   - `Game.clone() -> Game`：语义独立（heroes/board/hand/tavern/pools/queue/pending_choices/
     anomaly/trinkets/rng 等），共享不可变 `CardDB`；监听器/事件重建；
   - 或 `Game.push_checkpoint()/pop_checkpoint()`（原地应用后恢复，可嵌套/可重复）；
   - **验收**：8p recruit 状态 clone **p50 ≤1.5 ms / p90 ≤2.0 ms**、heap ≤1 MB；
     6p/4p/2p 残局不劣于 8p；1000 次 clone+eval ≤3 s；clone 后原状态不变、两 clone 轨迹独立。
2. `GameRNG.get_state/set_state/fork`（≤0.05 ms）：搜索每条模拟/世界线独立采样
   （商店/战斗/饰品）；验收：同 seed 轨迹逐位一致、fork 后互不影响。
3. `simulate_combat(board_a, board_b, seed=..., alive_count=..., damage_cap=...)`
   无副作用版（或只在 clone 上调用）；目标 ≤2 ms；用于叶评估 K 次采样/对手模型。
4. **确定性 / 可复现**：clone+rng fork 后同 seed 轨迹一致（搜索可复现/可审计）。
5. **按座位策略接口**（Phase2 才需要）：7 个对手座位可分别用策略/历史快照/池；
   支持训练期 oracle 与部署期 obs-only 切换。
6. **隐藏状态注入（determinization v0 用）**：测试/训练用 API，可设置对手隐藏
   board/hand/trinket（非正式环境 API）；没有它则 determinization 只能先做 bank-only。
7. `Game.digest()`（可选，≤0.5 ms）：状态哈希用于 transposition/聚合。
8. **基准 JSON（统一脚本，需覆盖）**：
   - clone / ERP / run_combat / legal_actions / obs / policy forward 的 p50/p90/p99；
   - 8p/6p/4p/2p 残局的状态规模与成本；
   - N=8/16/32 macro search 的 `ms_per_decision`（含/不含 1-turn rollout 两种口径）；
   - 1000 次循环 RSS 增量与泄漏检查；
   - 搜索确定性抽样（同 seed 两次 π/访问计数一致）。
9. **交付节奏建议**：先交 clone/checkpoint 的 v1（可用即可，6.49 ms 也能先跑 Phase1 低预算）；
   Phase1 bench 通过后再交 p90≤2 ms 优化版 + RNG fork + 座位策略。

---


> **env-builder 交付状态（2026-10-19 v1）**：
> 1. `model.clone()`（fast）✅ 8p recruit p50 1.1–1.6 ms / p90 ~1.8–2.0 ms / heap ~0.2 MB；
> 2. `checkpoint.push_checkpoint/pop_checkpoint/CheckpointStack` ✅（clone 快照 + 独立恢复）；
> 3. `rng.get_state/set_state/fork` ✅ ~15–20 µs；`simulate_combat` 无副作用 ✅ ~1.2–3.5 ms；
> 4. `digest()`（fast ~0.2 ms / full ~2 ms）、`hidden.inject_hidden_state`（v0）✅；
> 5. `runs/planning_bench.json` 统一分位数 ✅；测试 `tests/test_planning.py` 27 项 ✅。
> 仍需引擎侧（需审批）：ERP 跳过 offer 初始化的开关（约 -60~70% ERP 成本）。

## 8. 结论与建议

1. **路线**：精确模拟器 + PUCT（先 macro 回合级）+ 学习 prior + placement/rank 价值；
   隐藏信息用 determinization/对手模型；训练期用 oracle 教师，部署/评估只用观测级策略。
2. **不选**：MuZero（已有精确引擎、算力不划算、模型误差叠加）、JEPA 风格决策器（非决策算法、
   当前瓶颈不在此）。
3. **clone/fork 已解决**：planning v1 fast clone **p50 1.63 / p90 1.75 ms、heap 202 KB**
   （`runs/planning_bench.json`）；Phase1 本机 bench clone p50 1.82/p90 3.72（噪声），
   全部阈值通过。剩余性能点：ERP 12.96 ms（叶节点已用 `simulate_turn_combat` 3.51 ms 替代）。
4. **Phase 1 已完成（不训练）**：`hsbg/search/**` + `scripts/bench_search.py` + 测试；
   `runs/search/phase1_bench.json` 全阈值 PASS；search-vs-BC 100/100（BC 先验+BC-first macro，
   结构性）、对照 uniform/no-BC 92/100；增益分析见 §6.6.3。**未证明搜索优于 BC**，
   Phase2 才做棋力评估。
5. **下一步**：Phase0 价值头离线评估 + Phase1 已过的 MCTS 骨架 → Phase2 小规模自博弈（2–5k 局）
   与蒸馏；不启动训练直到 Lead 批准。
6. **风险**：模拟器 154 条 `missing_script`、隐藏信息 determinization 数据缺口（bank 只有 size，
   无完整 board token；`hidden.inject_hidden_state` 已就绪但无数据可注入）、非平稳对手、
   搜索成本（N=32 0.34 s/决策，N=1000 离线级）；用干净子集/真实轨迹差分/固定评估池控制。

---

## 附：版本记录

- **v1（2026-10-19 初稿）**：问题结构/AlphaZero 假设逐条对照、A–E 候选算法、设计蓝图、
  实验设计、不选 JEPA/MuZero、最小原型计划。
- **v2（2026-10-19，纳入 env-builder 首轮基准）**：
  - §4.2 填入实测：clone **6.49 ms**（8p recruit，raw deepcopy 158.9 ms=24.5×，heap +209 KB）、
    legal_actions 0.036 ms、ERP 11.43 ms、rollout 1 turn 8.10 ms、1000 clone+eval=6.5 s、
    1000 clone+rollout=14.6 s；给出“实时完整搜索不可行、离线/低预算可行”的结论和 N=1/8/16/32/64/1000
    成本表；clone 目标 p90≤2 ms 仍差 ~3×（env-builder 优化中）。
  - §6 原型范围收敛为 **macro 回合级、N=8–32、K=1**；§6.3 给出 bench JSON 字段与
    **验收阈值（当前 clone 校准）**；§6.5 给出 clone 优化到 p90≤2 ms 后的 Phase1 最小实现/
    测试清单/出口标准。
  - 新增 §3.6 **隐藏信息 determinization v0**（真实轨迹/BC 对手池采样 + 评估口径/泄漏检查）。
  - §7 更新为 env-builder 最终接口清单（clone/checkpoint、RNG fork、无副作用战斗、座位策略、
    隐藏状态注入、基准 JSON、确定性验收）。
  - 保持结论：**不做 MuZero、不做 JEPA 风格决策器**；Phase1 不训练。
- **v3（2026-10-19，Phase 1 实现 + planning v1）**：新增 §6.6（Phase1 实测：clone 1.82ms、
  1-ply 6.06ms、N=32 336ms、全阈值 PASS；search-vs-BC 100/100 结构性、uniform 对照 92/100；
  1→8→32 选择变化/Q spread/seed 稳定性）；§3.6 更新 hidden API 已就绪但数据缺口（仅 size）；
  §4.2.4/§7 更新 env-builder 最终数字与交付状态；§8 更新“clone 已解决、Phase1 完成、
  未证明搜索优于 BC”。
- **v4（2026-10-19，无训练决策器 pilot）**：新增 §6.7 + `hsbg/search/decision.py`
  + `scripts/eval_decision_gain.py`；20 局/cell 矩阵（greedy/beam/PUCT × BCValue/Combat/
  Heuristic/Uniform，含冻结 BC 策略基线 4.30）：无组合显著超 BC；PUCT N=32+BCValue 4.45
  （10% 吃鸡，738ms/决策）最有搜索潜力；greedy/beam+Heuristic 4.55/50% top4 @~100ms
  性价比最高；Combat/Uniform/beam 无优势。产物 `runs/search/decision_pilot.json/.md`。
- **v5（2026-10-19，硬搜索 train-free pilot + 修正版）**：新增 §6.8 +
  `hsbg/search/hard_search.py` + `scripts/eval_hard_search.py` + `tests/test_hard_search.py`。
  首版 rollout 用引擎 ERP（对手不买牌）→ 结论作废；修正版切换到 env-builder
  `rollout_throughput.rollout_to_end(fast_opponents=False)`（正常对手买牌、heuristic 自对弈），
  5 局/cell：BC 4.80/40%/0%、greedy+heuristic 5.20/20%/0%、
  hard-search 6.20/20%/0%（743ms/决策、5 rollouts/决策；墙钟 53s）。
  修正版仍差于 BC、成本高，不扩 100 局；caveat：horizon=3 截断、full 仅 1 次、候选偏
  heuristic/random。产物 `runs/search/hard_search_pilot.json/.md`。
- **v6（2026-10-19，硬搜索 20 局确认）**：`runs/search/hard_search_confirm.json/.md`；
  BC 4.35/50%/10% vs hard 5.80/20%/5%，配对差 **-1.45 [-2.45,-0.449]**；
  770ms/决策、5.1 rollouts/决策、候选剪枝后 3.15；动作改变率 28.9%；
  墙钟 205s。结论：正常对手 rollout 下仍差于 BC，**不建议再扩 100 局**；
  失败诊断：候选空间窄（heuristic/random macro，缺整回合 BC/teacher 候选）+ horizon
  截断噪声 + full 仅 1 次。
- **v7（2026-10-19，宽候选大 beam W=4/8/16）**：新增 `hsbg/search/wide_beam.py`
  （heuristic + 整回合 BC + random + 首步枚举，候选 8–16；本次平均 11.6）、
  `HardSearchConfig.beam_width`、`tests/test_wide_beam.py`；5 局/cell 墙钟 360s：
  BC 4.80 vs W4/W8/W16 全 **6.00**（1.6–2.1s/决策、13.6–15.6 rollouts）；
  W 增大无改善；BC 首步在候选/top-W 均 100%、动作改变率 18.1%；结论：
  候选数量不是瓶颈，筛选信号/rollout 方差才是；产物
  `runs/search/hard_search_beamwide.json/.md`。
- **v8（2026-10-19，方差压缩验证）**：`runs/search/hard_search_variance.json/.md`；
  W=8，h3/r2/full3 与 h1/r2/full3 均 **6.00**（BC 4.80），3.6/2.3s/决策、29.2 rollouts/决策；
  **screen/full rank std = 0** → 确定性 heuristic rollout 的重复采样是同一结果；
  加重复次数/换 horizon 无改善。结论：硬搜索无增益源于 rollout 估计信号弱/确定性重复，
  需随机化 rollout 或更强评估器；不扩 100 局。
- **v9（2026-10-19，随机化 rollout 验证）**：`hsbg/search/hard_search.py` 新增
  `rollout_policy=epsilon`/`rollout_epsilon`，`_rollout_env` 用 rng fork + random/epsilon
  policy；`scripts/eval_hard_search.py --wide-randomized`；5 局/cell 墙钟 355s：
  BC 4.80 vs random-seed 6.00（2.1s/决策）/ epsilon 6.00（3.8s/决策）；
  **screen/full std 0.71–1.03 / 1.30–1.36（>0）**，随机化成功但仍无增益；
  BC 首步在候选/top-W 100%、动作改变率 18.1%。结论：随机化后仍无信号，
  需更强评估/对手模型/候选空间；不扩 100 局。产物
  `runs/search/hard_search_randomized.json/.md`。
- **v10（2026-10-19，状态级硬搜索信号诊断）**：新增 `scripts/diag_hard_signal.py`；
  10 状态（turn3/6/9）×候选 4–12 ×full R=5 随机化 epsilon rollout，成本 98s；
  9/10 状态候选 max-min > noise（平均 1.80 vs 0.93），但 BC-first 平均 lift 仅 0.5 名、
  lift>1 仅 2/10、显著优于 BC 仅 1/10 → **当前纯 rollout 信号不足以稳定超过 BC**；
  BC 仍是无训练强基线；要做搜索需更强评估器/训练价值网络/更多预算。产物
  `runs/search/hard_signal_diag.json/.md`。
- **v11（2026-10-19，动作级 micro-PUCT）**：新增 `hsbg/search/micro_mcts.py`
  + `scripts/eval_micro_mcts.py` + `tests/test_micro_mcts.py`；5 局/cell 墙钟 424s：
  BC 4.80/40%/0% vs micro-PUCT N8W8 h3 **4.60/60%/20%**（1073ms/决策、8 sims、
  75 decisions/局），配对差 +0.2 CI [-2.2,+2.8]；**动作改变率仅 1.2%**（搜索几乎复述
  BC top-1），不能宣称增益；叶 horizon=3 截断。产物 `runs/search/micro_mcts_pilot.json/.md`。
- **v12（2026-10-19，N=32 强预算尝试）**：`micro_mcts.py` 新增
  `final_full_check`（root top-K full-to-end 复核）；N=32/W=8 单局 >600s 未完成，
  预算超限终止；降级 N=16/W=4/h3 单局 291s：BC 名次 6 vs micro 3，
  3007ms/决策、16 sims、96 decisions、**动作改变率 1.0%**（仍<5%），n=1 不结论；
  产物 `runs/search/micro_mcts_strong.json/.md`。结论：当前实现 N=32 在 30min 内不可行，
  且加预算后动作仍基本复述 BC；需优化树/缓存/叶评估或并行后再试。
- **v13（2026-10-19，回合内自枚举 + 两两胜率搜索）**：新增
  `hsbg/search/turn_search.py` + `scripts/eval_turn_search.py` +
  `tests/test_turn_search.py`；严格只搜当前回合（不执行 end_turn/不模拟后续回合）、
  枚举状态两两战斗胜率、每步 receding horizon。5 局/cell 墙钟 771s：
  BC 4.80/40%/0% vs turn-search **3.80/80%/0%**（1255ms/决策、states 11.4、
  combats 61.1），**动作改变率 73%**；配对差 **+1.0 [0.0,+2.2]**，符号检验 p=0.5
  （修正旧 fallback 误报 p≈0.03）；首次出现动作改变率 >5% 且指标一致改善。
  产物 `runs/search/turn_search_pilot.json/.md`。
- **v14（2026-10-19，turn-search 10 局确认，partial）**：`turn_search_confirm.json/.md`
  seeds 300–306（7 局，max-wall partial）：BC 4.50/50%/10% vs turn-search
  **3.14/86%/14%**；配对差 **+1.43 [0.29,2.86]**，符号检验 p=0.25（3 个非零差全正）；
  动作改变率 75%、1356ms/决策、states 11.8、combats 66.2；墙钟 1693s。
  n=7、p=0.25，方向一致但不宣称显著；修正 eval fallback p 值公式并更新报告。
- **v15（2026-10-19，turn-search 20 局确认 states8）**：`turn_search_confirm20.json/.md`
  seeds 300–319，并行 2 进程（各10局），墙钟 842s：BC **4.35**/55%/10% vs
  turn-search **3.70**/75%/5%；配对差 **+0.65 [-0.65,+1.90]**，精确符号检验 **p=0.63**；
  动作改变率 71%、ms/决策 485、states 7.5、combats 23.6。
  states8 下信号减弱（vs states16 7局 +1.43）→ **budget sensitivity**；未达强显著。
  产物 `turn_search_confirm20.json/.md`。
- **v16（2026-10-19，turn-search 20 局 states12）**：
  `turn_search_confirm20_s12.json/.md`，4 进程并行各5局，墙钟 552–877s：
  BC 4.50/45%/10% vs turn-search **3.65/70%/15%**（928ms/决策、states10、
  combats44.3、动作改变率75%）；配对差 **+0.85 [-0.45,+2.20]**，符号检验 p=0.63。
  介于 states8(+0.65) 与 states16 7局(+1.43)，仍 CI 跨 0；未达强显著；
  结论“有希望但未证实”，需训练价值网/更多预算。
- **v17（2026-10-19，turn-search 收口 + 价值网方案）**：§6.10 写最终收口
  （正确形态、71–75% 动作改变、+0.65/+0.85/+1.43 但 CI 跨 0 → 有希望但未证实；
  不再扩 50 局）；§6.8/§6.9 标注作废/仅对照；新增 `hsbg/search/README.md`；
  新增 `docs/VALUE_NETWORK_PLAN.md`（目标/数据/标签/切分/架构/损失/评估/算力/风险
  + Phase0 数据审计计划；**不启动训练**）。
- **v18（2026-10-20，Phase1 value head + value-prune）**：turn-search 20k 数据
  （21,240 样本/140 局，split 98/21/21）训练冻结 encoder 的 value head（rank CE+utility+top4）：
  val MAE 1.276/CE 2.346/AUC 0.774/ECE 0.011（旧头 1.517/4.229/0.760/0.194），seed0 134s；
  **value vs pairwise Spearman -0.064**，K4/K6 动作一致率 75%/100%；
  5 局 states8 pairwise 3.60 vs K4 4.00/K6 3.40，states12 pairwise 2.20 vs K4 3.40/K6 3.80；
  剪枝 ms/combats 明显下降但名次不稳定 → 不扩 states16/24/20 局；
  最终动作仍 pairwise。产物 `runs/value_net/turn_search_phase1/`、
  `runs/search/turn_search_value_prune_trained.json/.md`。
- **v19（2026-10-20，当前回合相对强度 value head）**：新增
  `scripts/build_winrate_labels.py` + `scripts/train_value_winrate.py`：
  20,749 状态、K=8、同 turn/tier 对照、pairwise 胜率标签（344.5s）；
  冻结 encoder 只训 scalar_head（112s），held-out val Spearman **0.511** / test **0.512**
  （旧头 0.361/0.386），AUC 0.741/0.747；
  但本地 pairwise Spearman **-0.007**，K4/K6 一致率 85%/100%；
  5 局 states8 pairwise 4.20 vs K4 3.20/K6 5.60；states12 2.20/2.60/3.40；
  states12 K4 top4 80% vs 100% → 仍不扩 states16/24/20 局；
  需 B 路线（记录本地 pairwise 矩阵）对齐分布。产物
  `runs/value_net/turn_search_winrate/`、`runs/search/turn_search_value_prune_winrate*.json/.md`。
- **v20（2026-10-20，B 路线本地 pairwise 标签）**：`TurnSearch record_trace` +
  `scripts/collect_localpair.py`（150 episodes/6 workers/states8，13,008 states，2075s）；
  `scripts/train_value_localpair.py` 冻结 encoder 只训 scalar_head：
  held-out 本地 pairwise Spearman **val 0.304 / test 0.224**（旧 BC head 0.080/0.057）；
  5 局 states8 pairwise 4.00/80% vs K4 6.40/0%、K6 4.40/60%；states12 2.20/100% vs
  K4/K6 3.40/60%；ms 1.2–1.7×、combats 47→5/13，但 rank/top4 掉点 →
  **不扩 states16/24/20 局**；需更强特征/晚回合训练/对手池。产物
  `runs/value_net/turn_search_localpair/`、`runs/search/turn_search_localpair_eval*.json/.md`。
- **v21（2026-10-20，全 pairwise states16 20 局确认）**：4 进程并行，states16/samples1/
  无 value 剪枝；BC 4.40/50%/10% vs turn-search **3.35/80%/15%**，
  **配对差 +1.05 [0.35,1.80]，精确符号 p=0.0034**，动作改变率 75.7%、941.8ms/决策、
  combats 64.9；states12 对照 3.65 vs4.50、+0.85 [−0.45,2.2]。
  **升级为强方向证据**；n=20 单轮，建议 50 局/跨对手确认后再考虑 PPO/接口。
  产物 `runs/search/turn_search_confirm20_s16.json/.md`。
- **v22（2026-10-20，全 pairwise states16 50 局确认）**：6 进程并行（seeds 300–349，
  heuristic/teacher 交替；9/9/9/9/8/6 局），分进程墙钟 1233–2000s：
  BC 4.22/58%/8% vs turn-search **2.90/86%/30%**；
  **配对差 +1.32 [0.80,1.82]，精确符号 p=4.26e-6**；动作改变率 74.9%、
  1132.7ms/决策、combats 64.2。产物
  `runs/search/turn_search_confirm50_s16.json/.md`；建议跨对手集验证后接 PPO/接口。
- **v23（2026-10-20，跨对手 10 局）**：seeds 350–359，heuristic/teacher/random 循环
  （env 无 BC 对手）；BC 4.20/50%/20% vs turn-search **1.70/90%/70%**；
  **配对差 +2.50 [1.30,3.70]，精确符号 p=0.0078**；动作改变率 77.8%、
  1035.7ms/决策。产物 `runs/search/turn_search_crossopp_s16.json/.md`。

---

## 附：本仓库证据索引

| 事实 | 来源 |
|------|------|
| Observation v2、39 entity slots、candidate_max=64、12 类动作、POMDP 边界 | `hsbg/env/spec.py`；`docs/ENV_SPEC.md` §2/§3/§7 |
| 环境 step 顺序/终止契约 | `docs/ENV_SPEC.md` §4；`hsbg/env/game_env.py` |
| 引擎精确战斗/宏回合 | `docs/ENGINE_API.md` §6.1/§6.2；`hsrl2/game.py` `end_recruit_phase/run_combat` |
| 引擎性能（clean：单局 257 ms、ERP p50 10.7 ms、run_combat p50 1.47 ms） | `docs/ENGINE_RL_READINESS.md` §3 |
| 官方一致性（72.2% strict / 86.6% 确定性 / 干净子集 100% / 154 missing_script，2026-10-18 快照） | `docs/EXACTNESS_STATUS.md`；`docs/FINAL_REPORT.md` §9.2（早期数字 72.3%/84.55%/246） |
| BC/teacher/random/PPO 指标 | `docs/EVAL_REPORT.md`；`docs/FINAL_REPORT.md` §5；`docs/TRAINING.md` §6 |
| 1.24M 实体 Transformer / rank 分布价值头 | `hsbg/policy/model.py`；`runs/bc/official_320/policy_bc.pt`（params=1,241,354；dim128/layers4/vocab3840/value_mode=distribution） |
| Encoder 维度 | `hsbg/policy/encoder.py`（num_entities=39, entity_num_dim=56, global_dim=30, cand_num_dim=38, candidate_max=64） |
| env-builder planning v1 基准（2026-10-19）：clone **1.63/1.75 ms（p50/p90）**、heap 202KB、ERP 12.96ms、`simulate_turn_combat` 3.51ms、RNG fork 17.5µs、N=32 446 sims/s、determinism PASS | `runs/planning_bench.json`；`scripts/bench_planning.py`；`hsbg/planning/README.md` |
| Phase1 搜索 bench（2026-10-19，本机 CPU）：clone 1.82/3.72ms、1-ply 6.06ms、N=1/8/16/32=41.7/119.6/191.2/336.4ms、全阈值 PASS、deterministic/legal/no-oracle、search-vs-BC 100/100（结构性）/uniform 对照 92/100 | `runs/search/phase1_bench.json`；`runs/search/phase1_search_vs_bc.json`；`scripts/bench_search.py`；`tests/test_search_*.py` |
| clone 成本/能力（本机独立复测：deepcopy 150–600 ms；pickle 失败；浅拷贝 0.01 ms；`_frozen_clone` 0.15 ms） | 本次微基准（2026-10-19，本机） |
| enumerate/obs/forward 实测 | 本次微基准：`enumerate_step` 0.015 ms、`build_observation` 0.25 ms、policy forward batch1 CPU 2.1 ms / CUDA 3.9 ms、batch8 CPU 5.3 / CUDA 3.6 ms |
| 候选/动作分布 | 本次实测：candidate mean 12.4 / p90 20 / max 34；teacher 64 步到 turn9；action kinds sell/buy/play/freeze/end_turn… |
| 搜索路线相关未来工作 | `docs/ROADMAP.md` M5“搜索教师蒸馏/更大规模 BC” |

> 注：`docs/ENV_SPEC.md` §2 的表格仍写 `version=1`，而源码 `Observation.version=2`；
> 以 `hsbg/env/spec.py` 为准（v2 已加 `extra`）。本文 clone/rollout/ERP 性能来自
> env-builder 2026-10-19 首轮基准，其余为本机微基准；正式 Phase1 数值以
> `scripts/bench_search.py` 在统一机器上的输出为准。
