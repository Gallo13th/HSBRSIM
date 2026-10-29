# 训练系统交接文档：数据、对手、Actor、决策与评分

> 目的：换一台机器连到本项目目录时，不看聊天记录也能接管训练/评测。
> 项目根：`/home/data/users/gaoletian/projects/HSBRSIM`
> 引擎/数据：`hsbg_engine` 1.0.0，Hearthstone 37.0.0.255790。
> 本文只描述当前代码实际行为；与论文/AutoTavern 的差异单独标注。

## 0. 快速入口

```bash
cd /home/data/users/gaoletian/projects/HSBRSIM
P=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python

# 引擎（若未安装）
cd rust && $P -m pip install -e . && cd ..

# 测试
PYTHONPATH=rust/python:. $P -m pytest tests -q

# BC 冷启动
$P scripts/train_bc_bot.py --games 700 --max-samples 100000 --epochs 3 \
  --arch entity --device cuda --out /tmp/entity_bc100k

# entity PPO（单进程、持久 trainer）
$P scripts/train_entity_sync.py --checkpoint /tmp/entity_bc500k/model.pt \
  --iterations 1 --games 540 --workers 64 --batch-size 64 \
  --arch entity --device cuda --sims 4 --opponent bot \
  --epochs 1 --minibatch 1024 --lr 1e-5 --target-kl 0.1 \
  --out runs/az_entity_ppo

# C0 gate（正式协议必须 512×8、双封存；--smoke 仅自检）
$P scripts/c0_gate.py --checkpoint runs/az_entity_ppo/model.pt --arch entity \
  --device cuda --games 512 --seats 8 --smoke --out /tmp/c0.json

# 曲线
$P scripts/plot_training_curves.py --out runs/plots/training_curves.png
```

关键文件：

| 文件 | 作用 |
|---|---|
| `hsbg/az/train/entity_model.py` | entity transformer（49 token，14.8M） |
| `hsbg/az/train/ppo.py` | PPO、行为策略、masked logprob、GAE、collect |
| `hsbg/az/train/ppo_trainer.py` | 持久 Adam/LR/RNG/state |
| `hsbg/az/train/parallel_collect.py` | 多线程采集（当前 actor 原型） |
| `hsbg/az/train/batch_eval.py` | BatchLeafServer / BatchPPOEvaluator |
| `hsbg/az/train/selfplay.py` | 8 座自对弈循环 |
| `hsbg/az/train/evaluate.py` | 固定 seed 评测 |
| `hsbg/eval/c0.py` | C0 配对 CI / gate 判定 |
| `scripts/train_bc_bot.py` | BC 冷启动 |
| `scripts/train_dagger_bot.py` | DAgger 冷启动 |
| `scripts/train_entity_sync.py` | entity PPO 单进程入口 |
| `scripts/c0_gate.py` | C0 评测入口 |
| `docs/MULTISTAGE_TRAINING.md` | 多 stage/数据预算/曲线 |

---

## 1. BC 到底学的是哪里的数据？

### 1.1 数据来源

BC **不是人类对局，也不是 AutoTavern 数据**。  
它学的是 **本仓库 Rust 引擎内置 bot 的动作**。

`scripts/train_bc_bot.py` 的实际逻辑：

```python
game = E.Game(seed=seed + gi)
for seat in range(8):
    if seat == 0 and game.needs_action(0):
        f, c = obs_arrays(game.observe(0))     # 公开观测：3227 floats + 124 cards
        m = mask_from_bytes(game.legal_mask(0)) # 245 维合法动作 mask
        a = game.bot_action(0)                  # 标签：引擎 bot 的动作
        dataset.append((f, c, m, a))
        game.step(0, a)                         # 用 bot 动作推进
    else:
        game.bot_play(seat)                     # 其余 7 座也是引擎 bot
```

因此：

- 状态分布：**seat0 对 7 个引擎 bot 的对局**；
- 标签：`game.bot_action(0)`；
- 其他座位：`bot_play`；
- 不是 self-play，不是人类 Power.log，不是 AutoTavern library；
- 数据不落盘，训练时在线采集。

### 1.2 实际样本量

本次会话跑过：

| 文件 | games | samples | BC top1 |
|---|---:|---:|---:|
| `/tmp/entity_bc` | 120 | 16,726 | 0.477 |
| `/tmp/entity_bc100k` | 700 | 93,192 | 0.639 |
| `/tmp/entity_bc500k` | 3,753 | 500,000 | 0.814 |

C0 smoke：

- BC 16k ≈ 7.02；
- BC 93k ≈ 6.17；
- BC 500k ≈ 5.00（64 局）。

### 1.3 BC 的局限

- BC 只能逼近 teacher（引擎 bot），不能稳定超过 teacher；
- 数据是 bot 的状态分布，不是当前策略的状态分布 → DAgger 用于补足：
  - `scripts/train_dagger_bot.py`：当前策略 rollout，但在每个状态查询 `game.bot_action(0)` 作标签；
  - DAgger 34k 状态 top1 0.88，但 64 局 C0 没有比 BC+PPO 更好。

---

## 2. 所谓的“对手课程”指什么？

### 2.1 当前支持的三类对手

`CollectConfig.opponent`：

| 值 | 行为 | 现状 |
|---|---|---|
| `self` | 8 座都用当前策略 | 有 rank 方差，但没有历史池/联赛 |
| `bot` | seat0 学习，其余 7 座引擎 bot | 最强；常出现全 rank8、优势为 0 |
| `weak` | 90% 合法 EndTurn，否则随机合法动作 | 太被动，单局 ~1,200 decisions，训练太慢 |

“weak” 的意图是打破“对完整 bot 全 rank8、PPO 没有胜负信号”的死锁，但实际效果：

- 对局变长；
- 1M 弱课程不可行；
- C0 对完整 bot 仍 8.0。

### 2.2 真正的“对手课程”应该是什么

不是简单把 bot 变弱，而是**按 stage 控制对手分布、版本和难度**：

```text
C0 单模型 vs 完整 bot（先过 gate）
  -> 混合弱 bot / 合法示范
  -> 历史 checkpoint 池（league）
  -> 真实对局 library（P2）
```

需要但不存在的组件：

1. **stage 调度器**：每个 stage 的对手集合、数据量、KL anchor、晋级条件；
2. **历史 checkpoint 池**：4–8 个成员 + best/old，按概率采样；
3. **对手版本记录**：每个样本记录 opponent_id/version；
4. **难度退火**：弱 bot 比例、bot 比例、历史池比例随 stage 变化；
5. **评测隔离**：exam seeds 不参与训练。

当前代码只有单策略 `self` / 固定 bot / 伪 weak，**没有历史池、没有 stage 切换**。

### 2.3 为什么全 rank8 是问题

对 8 人局，终局奖励是 placement utility。若模型每局都第 8：

```text
reward = u(8) = -1
advantage ≈ 0（同局所有样本同 rank）
```

PPO 几乎没有“方向”。  
要么用搜索教师产生更好的动作分布，要么用弱对手/BC/DAgger 提供非零胜负信号。

---

## 3. 所谓的“actor 架构”问题指什么？

### 3.1 当前实际实现

`collect_ppo_batch_parallel`：

```python
with ThreadPoolExecutor(max_workers=workers) as ex:
    futs = {ex.submit(_one_game, ...): gi for gi in range(games)}
    for f in as_completed(futs):
        results[gi] = f.result()
```

- **一个 Python 进程**；
- `workers=64` 是 **64 个线程**，不是 64 个 actor 进程；
- 每个线程：自己一个 `Game` + `PPOSelfPlayPolicy` + 共享只读 model / BatchLeafServer；
- 每个决策同步走：
  - 网络 forward（或 BatchLeafServer）
  - 可选 MCTS `hsbg.az.search.search`（Rust 逐叶回调）
- 每个线程必须等当前决策完成才继续。

所以叫“64 workers”但本质是 **1 个 actor 进程内的 64 个阻塞线程**。

### 3.2 实测瓶颈

| 配置 | 结果 |
|---|---|
| sims=0, 64 threads, 1000 games | ~55s，~115k samples |
| sims=4, 64 threads, 64 games | ~40s |
| sims=4, 1000 games | **>21.5min 未完成** |
| sims=4 1M 推算 | **>3.5h** |
| BatchLeafServer | max_batch 64，但 fill 约 49% |

原因：

1. Python GIL；
2. Rust MCTS 逐叶同步回调；
3. 没有“挂起搜索/回填叶”的机制；
4. 没有 actor 进程池、推理服务、learner 分离；
5. 64 线程并不能让 MCTS 并行。

### 3.3 目标 actor 架构

```text
4–8 actor processes（每个 8–32 局/多树）
    -> 叶请求队列
    -> GPU InferenceServer（B=64/128）
    -> actor 回填
    -> replay shard
    -> learner PPO（单进程）
    -> checkpoint publisher
    -> 新 actor version
```

关键点：

- **actor 进程**而不是线程；
- 每 actor 多局/多树，才能持续填满 B；
- 推理服务与 learner 解耦；
- 版本化策略：记录 actor policy_version；
- 异步时限制 age/KL/ESS，不合格样本拒收；
- P0 先同步，P1 再异步。

当前代码没有这些；`batch_eval.py` 只解决“推理 batch”，不解决“actor 调度”。

---

## 4. 当前决策方法

### 4.1 输入

每个决策：

```text
features: float32[3227]
cards:    int64[124]
mask:     bool[245]        # 精确合法动作
seat:     int
```

### 4.2 训练策略 `PPOSelfPlayPolicy.decide`（`hsbg/az/train/ppo.py`）

伪代码：

```python
f, c = game.observe(seat)
mask = game.legal_mask(seat)

# 1) 网络或批量叶服务
if eval_fn is not None:
    prior, value = eval_fn(f, c, mask, seat)   # BatchPPOEvaluator
    logits = log(prior)
else:
    logits, value = model(f, c, mask)

# 2) 行为分布
p_net = masked_softmax(logits / temperature, mask)

# 3) 可选 MCTS
target_pi = search(game, seat, search_config, eval_fn=eval_fn)
if behavior == "net" or target_pi is None:
    mu = p_net
elif behavior == "mcts":
    mu = target_pi
else:  # mixed
    mu = normalize((1-eps)*target_pi + eps*p_net)

# 4) 采样
a ~ mu
logprob = log(mu[a])

# 5) 强制 EndTurn 守卫
if actions_this_turn > 40 and EndTurn legal:
    a = EndTurn
    logprob = 0.0
    forced = True
```

记录字段：

```text
features/cards/mask/action/old_logprob/value/target_pi/forced/rank/game_id/seat/turn
```

### 4.3 MCTS 是什么

`hsbg/az/search.py`：

- PIMC（determinization）；
- 每个 world 一棵 PUCT 树；
- 叶评估：`eval_fn(features, cards, mask, seat) -> (prior, value)`；
- Rust 后端 `mcts_search`；
- `EndTurn` 宏动作；
- 根 visit 聚合 → `π_MCTS`。

当前生产训练默认 **behavior=net**，MCTS 的 visit π 只作 `pi_coef` 辅助 CE；  
`behavior=mcts/mixed` 是 off-policy，慎用。

### 4.4 评测策略 `PPOGreedyPolicy`

- 不采样：`argmax(masked logits)`；
- search-off；
- 同样的 forced EndTurn 守卫；
- C0 gate 用它，因此 gate 是“裸网络 + greedy”强度，不是 search-on。

### 4.5 小例子

假设某回合：

```text
mask = [EndTurn, Buy, Play, Sell, ...]（245 维，只有部分 True）
logits 经 mask 后：
  EndTurn 0.10
  Buy     0.50
  Play    0.30
  Sell    0.10
```

- 行为 `net`：按 [0.10,0.50,0.30,0.10] 采样；若抽到 Buy，`old_logprob=log(0.50)`；
- 评测 `greedy`：直接选 Buy；
- 若本回合已 41 个动作且 EndTurn 合法：强制 EndTurn，`logprob=0`、`forced=True`；
- PPO 更新时 forced 样本只进 value/critic，不进 policy/aux。

---

## 5. 评分方法

### 5.1 训练奖励

终局名次 `r ∈ 1..8`：

```text
u(r) = 1 - 2*(r-1)/7
```

- 第 1：+1
- 第 4：≈ +0.143
- 第 8：-1

`reward` = 终局 `u(r)` + 可选 `step_penalty`（当前 0）。  
PPO 用 GAE(λ)，`gamma=1.0`、`lam=0.95`；value 头可选 rank CE 或 `E[u]` MSE。

### 5.2 评测指标

`hsbg/az/train/evaluate.py`：

- `mean_rank`：越小越好；
- `top4_rate`：前四比例；
- `win_rate`：第 1 比例；
- `legal_action_rate`；
- `truncated_games` / `truncated_combats`。

评测协议：

- seat0 对 7 bot（或 8 seat 轮换）；
- 固定 seed 集；
- 输出 `rank_sequence`，供配对分析。

### 5.3 C0 gate

`scripts/c0_gate.py`：

- 正式：**512 局 = 8 seat × 64 局**；
- 两个互不重叠封存 seed 面板；
- 模型与 bot 用**相同 seed/seat**；
- 配对：

```text
Δ_g = rank_model(g) - rank_bot(g)
```

- 对 Δ 做 95% bootstrap CI；
- 只有 **CI 上界 < 0** 且 0 illegal / 0 game+combat truncation 才算击败；
- 512 局单面板约 6 分钟，双面板约 12 分钟。

**64 局结果不可用于晋级**：本次会话中 0.378M checkpoint 64 局 4.36，512 局 4.77。

### 5.4 示例

512 局（1.259M sims0 checkpoint）：

```text
model mean rank = 4.709
bot mean rank   = 4.506
paired Δ        = +0.203
95% CI          = [-0.039, +0.459]
top4            = 45.7%
```

CI 上界 0.459 > 0 → **不通过**。  
注意：`mean rank` 4.709 看起来接近 bot 4.506，但配对 CI 显示没有稳定优势。

---

## 6. 当前训练/数据事实

| 项目 | 结果 |
|---|---|
| entity 参数 | 14,808,254（14.8M） |
| token | 49（含 global） |
| AutoTavern | 56+1 token / ~18M，**未严格对齐** |
| BC 500k | top1 0.814，C0 5.0（64局） |
| BC+PPO 50k | 4.72（64局），4.77（512局） |
| 1M sims=0 | 1,259,447 decisions / 910s，C0 4.709（512局） |
| 1M sims=4 | 1000 局 shard >21.5min，1M 推算 >3.5h，未完成 |
| C0 gate | 未通过 |

当前瓶颈：

1. C0 强度；
2. 对手课程/历史池；
3. actor 架构；
4. AutoTavern token/参数对齐；
5. 真实对手 library 缺失。

---

## 7. 已知坑（不要重复踩）

1. `--games 2700` 一次性 futures 会长时间无进度；用分片 + `as_completed`。
2. 64 Python 线程不是 64 actor；sims=4 不扩展。
3. `--smoke` 永不放行；正式 gate 必须 512/8/双封存。
4. 64 局评测噪声极大，不能选 checkpoint。
5. BC 标签是引擎 bot，不是人类/AutoTavern。
6. `weak` 90% EndTurn 会让对局过长，不是有效课程。
7. PPO 的 `processed_samples` 要按实际 minibatch 计，不能用 `updates×mb`。
8. forced EndTurn 必须 `logprob=0` 且排除 policy/aux。
9. 1M sims=0 不代表 1M sims=4。
10. 模型 49 token/14.8M ≠ AutoTavern 56+1/18M。

---

## 8. 接手清单

- [ ] 引擎 37.0.0.255790 可用；
- [ ] `pytest tests` 通过；
- [ ] 确认 `runs/` 是 gitignored，实验产物不入库；
- [ ] 用 `c0_gate --smoke` 自检，再用正式 512×8 双封存；
- [ ] 任何“提升”必须 512 局配对 CI，不接受 64 局；
- [ ] 加数据前先确认 PPO scaling 有单调趋势；
- [ ] 下一步优先级：历史 checkpoint 池/联赛 > actor 重构 > 模型对齐 > 继续加数据。
