# RL 接口层（hsbg.rl）—— 协议、采集、评测与 Gym 包装

> 状态：**稳定接口层**（不训练、只做推理与数据采集）。
> 代码：`hsbg/rl/`；测试：`tests/test_rl_*.py`；上游契约：`hsbg/env/spec.py` + `docs/ENV_SPEC.md`。
> 本文档记录接口用法、JSONL schema、并发/确定性语义、实测性能与**已知限制/待办需求**。

---

## 1. 分层与数据流

```
┌──────────────────────────────────────────────────────────────────────┐
│ 引擎 hsrl2  →  环境层 hsbg.env（BattlegroundsEnv / VecEnv）           │
│                 reset(seed) -> Observation；step(action) -> 5 元组    │
└───────────────────────────────┬──────────────────────────────────────┘
                                │  EnvLike 协议（reset/step/close）
┌───────────────────────────────▼──────────────────────────────────────┐
│ hsbg.rl.api                                                          │
│   Policy / EnvLike 协议；Transition / EpisodeRecord                   │
│   run_episode()：唯一顺序单局驱动（所有组件共用）                       │
│   obs_summary()/JSONL 记录构造/validate_record()                      │
└──────┬────────────────┬─────────────────┬────────────────────────────┘
       │                │                 │
┌──────▼──────┐ ┌───────▼────────┐ ┌──────▼───────────┐ ┌──────────────┐
│ rl.policies │ │ rl.envs        │ │ rl.gym_wrapper   │ │ rl.collector │
│ random/     │ │ real/mock 工厂 │ │ Gymnasium 兼容   │ │ 多进程+JSONL │
│ heuristic/  │ │（Mock 确定性） │ │ time-limit/record│ │ 断点续采     │
│ callable/   │ │                │ │ /auto-reset      │ │              │
│ checkpoint  │ │                │ │ action_masks()   │ │              │
└──────┬──────┘ └───────┬────────┘ └──────┬───────────┘ └──────┬───────┘
       │                │                 │                    │
       └────────────────┴─────────────────┴────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │ rl.evaluate           │  复用 hsbg.eval.metrics
                    │ 固定种子 / CI / 多进程 │  （EvalResult / bootstrap CI
                    └───────────┬───────────┘   / rank_distribution）
                                │
                    ┌───────────▼───────────┐
                    │ hsbg.train（后续训练） │  PPO/BC 从 EpisodeRecord 或
                    │                       │  JSONL 读数据；checkpoint 经
                    └───────────────────────┘  CheckpointPolicy 复用
```

设计原则：

1. **只有一个单局循环**：`hsbg.rl.api.run_episode`。collector / evaluate / 测试全部复用它，
   避免"三处各写一套循环"导致行为漂移。
2. **不引入硬依赖**：`hsbg.rl` 只依赖 `hsbg.env.spec` + numpy + 标准库；torch 仅在加载
   checkpoint 时延迟导入；gymnasium 为可选依赖。
3. **确定性可复现**：第 `k` 局种子 = `seed + k`，策略随机源 = `random.Random(seed + k)`；
   与 worker 数无关（worker 只分配任务，不改变每局的种子与随机流）。

---

## 2. 协议（`hsbg/rl/api.py`）

### 2.1 `Policy`

```python
class Policy(Protocol):
    name: str
    def act(self, obs: Observation, *, deterministic: bool = False,
            rng: Optional[random.Random] = None) -> int | CandidateAction | None: ...
    def reset(self) -> None: ...
```

* 返回 **`obs.candidates` 的下标**最省事；返回 `CandidateAction` 时按 `signature()` 匹配；
* 返回 `None` / 越界下标 = 非法动作，`run_episode` 会自动兜底（优先 `end_turn`，
  否则最后一个候选）并在 `Transition.invalid=True` 记录；
* `deterministic=True` 表示评测/演示语义（启发式策略取 argmax，checkpoint 策略贪心；
  `random` 策略仍从传入的 `rng` 采样——rng 固定即可复现）；
* `reset()` 在每局开始时清空内部状态（启发式的每回合计数、checkpoint 无需处理）。

内置实现（`hsbg/rl/policies.py`）：

| spec | 说明 | 可移植性 |
|------|------|----------|
| `"random"` | 合法候选中均匀随机 | 任何后端（gym/mock/真环境） |
| `"heuristic"` | **观测级**贪心（买/打/升级优先 + 血量感知 + 每回合决策上限 + 无进展保护） | 任何后端；质量一般（实测 mean_rank≈5.7–6.2） |
| `"teacher"` | **引擎感知**启发式（复用 `hsbg.agents.heuristic.HeuristicPolicy`），`bind_env(env)` 后调用引擎教师 | **仅真环境**；离线采集/BC 教师/强基线（实测 mean_rank≈3.95–4.4） |
| `"first"` / `"end_turn"` | 最小闭环/回合推进测试用 | 任何后端 |
| `"runs/.../policy_final.pt"` | `hsbg.policy` checkpoint（自包含词表/config；默认贪心推理，torch 延迟导入） | 任何后端 |
| `fn(obs)` / `fn(obs, rng)` | 任意 callable（多进程要求模块级、可 pickle） | 取决于实现 |
| 带 `act()` 的对象 | 自动包成 `PolicyAdapter` | 取决于实现 |

#### `heuristic` vs `teacher`：定位与选择建议

| | `heuristic` | `teacher` |
|---|---|---|
| 输入 | 只读 `Observation`（spec 契约） | `Observation` + `env.game` / `env.agent_hero`（引擎内部状态） |
| 可移植性 | 高：gym 包装、mock、离线 replay 都能用 | 低：必须真实 `BattlegroundsEnv`（mock 后端直接报错） |
| 棋力（8 人、heuristic 对手） | mean_rank ≈ 5.7–6.2 | mean_rank ≈ **3.95–4.4**（接近环境自带对手 4.24） |
| 单步成本 | 只做候选打分 | 额外枚举一次引擎候选（约 1.5–2× 单步耗时） |
| 适用场景 | gym/SB3/接口回归/可移植基线 | **离线数据采集**（质量优先）、BC 教师、强基线对照 |

采集高质量 BC/离线数据请用 `--policy teacher`；需要跨后端/可移植或做吞吐基准时用
`--policy heuristic`。

**`bind_env` 协议**：需要 env 内部状态的策略实现 `bind_env(env)`；`BasePolicy`
默认 no-op。`hsbg.rl.api.run_episode` 会在**每局开始前**自动调用
`policy.bind_env(env)`，因此 collector/evaluate/手写循环都无需额外处理
（teacher 用字符串 spec 最省事：worker 内重建后各自 bind）。

### 2.2 `EnvLike`

与 `docs/ENV_SPEC.md` §4 一致：

```python
class EnvLike(Protocol):
    def reset(self, seed=None, options=None) -> Observation: ...
    def step(self, action) -> (Observation, float, bool, bool, Dict): ...
    def close(self) -> None: ...
```

* `action` 接受 `CandidateAction` 或候选下标（真实环境两种都支持）；
* `terminated` = 被淘汰/游戏结束；`truncated` = 超时截断；
* **`info["rank"]`**：终局名次（1..num_players）——采集/评测的终局奖励与名次分布都依赖它；
  truncated 时的 rank 是环境给出的当前估计值（文档与统计里会单独标 truncated 数）。

### 2.3 `Transition` / `EpisodeRecord`

```python
@dataclass
class Transition:      # 一步
    obs, action, action_kind, action_signature,
    reward, next_obs,
    terminated, truncated, info,
    episode_id, seed, step, rank, invalid

@dataclass
class EpisodeRecord:   # 一局
    episode_id, seed, rank, total_reward, turns, steps,
    terminated, truncated, reason, num_players,
    invalid_actions, policy, wall_seconds,
    transitions: List[Transition], error, meta
```

`EpisodeRecord.to_jsonl_lines(per_step=True, include_board=True)` → 若干 step 行 + 1 条 episode 行；
`Transition.to_dict(info_keys=...)` 控制 `info` 落盘字段（默认白名单，见 §4.2）。

---

## 3. 快速开始

```python
from hsbg.rl import (EpisodeRecord, make_env, make_policy, run_episode,
                     collect_trajectories, collect_rollouts, evaluate)

# 单局
env = make_env(backend="auto", seed=0)          # auto: 真环境优先，不可用回退 mock
policy = make_policy("heuristic", seed=0)
record = run_episode(env, policy, seed=0, episode_id=0, max_steps=2000)
print(record.rank, record.steps, record.total_reward)
env.close()

# 批量采集（写 JSONL，断点续采默认开启；观测级可移植策略）
stats = collect_trajectories("heuristic", num_envs=4, episodes=100, seed=0,
                             out_path="runs/rl/heuristic_100.jsonl")

# 高质量离线采集 / BC 教师（引擎感知 teacher，仅真环境）
stats = collect_trajectories("teacher", num_envs=4, episodes=100, seed=0,
                             out_path="runs/rl/teacher_100.jsonl")
print(stats.format())                            # games/s、rank 分布、动作分布

# 内存 trajectory（给后续训练/BC 用）
records, stats = collect_rollouts("random", num_envs=2, episodes=16, seed=0)

# 评测（复用 hsbg.eval 指标：mean_rank / bootstrap CI / rank 分布）
summary = evaluate("heuristic", episodes=20, seed=0, workers=2)
print(summary.format())
```

命令行：

```bash
# 观测级（可移植）采集
python -m hsbg.rl.collector --policy heuristic --envs 4 --episodes 100 \
    --out runs/rl/heuristic_100.jsonl
# 引擎感知 teacher（高质量离线/BC 数据；仅真环境）
python -m hsbg.rl.collector --policy teacher --envs 4 --episodes 100 \
    --out runs/rl/teacher_100.jsonl
python -m hsbg.rl.evaluate --policy random --episodes 20
# 对照表（多个策略用同一固定种子集）：
python -m hsbg.rl.evaluate --policy teacher --policy heuristic --episodes 20
# 回归对比：落盘 JSON（指标 + 配置 + per-episode rank）
python -m hsbg.rl.evaluate --policy teacher --episodes 20 --out runs/rl/eval_teacher_20.json
```

---

## 4. 采集器（`hsbg/rl/collector.py`）

### 4.1 并发与确定性语义

* **多进程**：`multiprocessing` + **spawn**（Windows 安全）；worker 是模块级函数
  `_collect_worker`，每个 worker 持有自己的 env，episode 任务按轮转分配。
* **任务 = 固定种子**：第 `k` 局 `seed_k = seed + k`；任务划分只影响"谁跑哪局"，
  不影响结果 ⇒ `workers=1` 与 `workers=4` 采到的 episode 内容完全一致（测试覆盖）。
* **策略随机源**：每局 `random.Random(seed_k)` 传给 `Policy.act`；同一 seed 两次采集
  动作序列逐条一致。
* **policy picklable 要求**：多进程时 policy 必须是字符串 spec（worker 内重建）或
  模块级函数/类实例；lambda/闭包会报错并提示（或改用 `num_envs=1`）。内置
  `is_picklable()` / `ensure_picklable()` 可提前检查。
* **断点续采**：`resume=True`（默认）时扫描输出文件里**完整**的 episode（按 `seed` 去重），
  只补采缺失局；合并时按 `(episode_id, step)` 去重后按 `episode_id` 排序；
  重复执行同一命令是幂等的（`new=0, resumed_skipped=N`）。
* **崩溃安全**：每个 worker 先写自己的 shard（`<out>.partN`），正常结束后由主进程合并为
  单一 JSONL 并删除 shard；单局异常只记 `type="error"` 行，不拖垮整批。
* **确定性**：环境种子完全决定对局（ENV_SPEC 要求）；`mock` 后端同样由 seed 决定。
* **引擎感知策略（teacher）**：需要真实环境。`--policy teacher` + `--backend mock`
  会在开始采集前直接报 `ValueError`（避免逐局失败）；`auto` 且真实环境不可用同理。
  teacher 的"动作 → 候选下标"通过 `signature()` 多级匹配，匹配不到时保守回退
  `end_turn`（`TeacherPolicy.fallbacks` 可观测）。

### 4.2 JSONL schema（`SCHEMA_VERSION = 1`）

文件按行组织，共 4 种记录（`type` 字段区分）；`validate_record(row)` 可校验必需字段：

| type | 频率 | 关键字段 |
|------|------|----------|
| `header` | 文件首行（1 条） | `v/api_version/obs_version/candidate_max`, `policy`, `backend`, `num_players`, `opponent`, `seed`, `episodes`, `workers`, `created_at` |
| `step` | 每步 1 条 | `episode_id, seed, step, turn, phase, action(下标), action_kind, action_signature, reward, terminated, truncated, invalid, rank, n_candidates, candidate_max, obs{...}` |
| `episode` | 每局末 1 条 | `episode_id, seed, rank, total_reward, turns, steps, terminated, truncated, reason, invalid_actions, policy, num_players, wall_ms` |
| `error` | 异常时 | `episode_id, seed, worker, error` |

`obs` 摘要（`obs_summary()`）字段：

```
turn, phase, gold, tier, health, armor, rank, alive, total,
pending_choice(choice kind), board_size, hand_size, tavern_size,
trinket_size, opponent_size, has_quest, n_candidates,
candidate_kinds[], board[card_id], hand[], tavern[]        # 后三组可用 --no-board 关闭
```

* **不落盘完整实体特征/张量**：需要时可用 `hsbg.policy.encoder.ObservationEncoder`
  重新编码（详见 §7）；JSONL 面向分析与轻量 replay，而不是训练时的 token 流。
* **`Observation.extra`（ENV_SPEC v2）**：环境已把 frozen/任务进度/powers 等放进
  `obs.extra`（dict，实测完整内容 ~12KB/步）。RL 层**默认不落盘**；需要时用
  `collect_trajectories(..., include_extra=True)` / CLI `--include-extra`，只写白名单
  `SUMMARY_EXTRA_KEYS`（frozen_tavern、free_refresh_left、refresh_cost、
  gold_spent_this_turn、cards_played_this_turn、minions_sold_this_turn、
  tavern_spells_cast_this_turn、quest_progress、quest_target、quest_completed）。
  `Transition.to_dict(include_extra=True)` 同样支持按行开启。
* **info 白名单**：真实环境的 `info` 可能含很大的 `obs_extra`（全部引擎标签、powers 等，
  实测 ~12 KB/步）。JSONL 默认只写 `JSONL_INFO_KEYS`：
  `turn/phase/rank/health/armor/alive_count/combat/invalid/wrong_action/terminated_reason/seed/episode_steps/episode`。
  需要全量时调用 `Transition.to_dict(info_keys=None)`。
* **体积参考**：真环境 100 局 / 12,699 步 → **13.9 MB**（约 1.1 KB/步，含棋盘/手牌/酒馆
  card_id 与候选类型）；`--no-board` 可显著缩小（去掉 3 组 card_id 列表）。

### 4.3 CLI 参数

| 参数 | 说明 |
|------|------|
| `--policy` | 策略 spec（见 §2.1）；高质量采集用 `teacher`（仅真环境），可移植基线用 `heuristic` |
| `--envs`/`--workers` | 并行 worker 数（也即并发环境数） |
| `--episodes` | 目标总局数（断点续采时是"目标总数"） |
| `--seed` | 基准种子，第 k 局 = seed+k |
| `--out` | JSONL 路径；省略时走内存采集（只打印统计） |
| `--backend auto\|real\|mock` | auto = 真环境优先，不可用回退 mock |
| `--num-players / --opponent` | 真环境构造参数 |
| `--max-steps-per-episode` | 单局步数硬上限（防死循环），超限按 truncated 记 |
| `--deterministic` | 策略尽量贪心（默认采样） |
| `--no-resume` | 关闭断点续采（覆盖旧文件） |
| `--no-per-step` | 只写每局一行（步骤不落盘） |
| `--no-board` | 观测摘要不含 board/hand/tavern card_id |
| `--include-extra` | 观测摘要附加 `Observation.extra` 白名单（frozen/任务进度等；体积更大） |
| `--json` | 以 JSON 打印统计 |

API：

```python
collect_trajectories(policy, *, num_envs, episodes, seed, out_path,
                     resume=True, per_step=True, include_board=True,
                     num_players=8, opponent="heuristic", backend="auto",
                     env_kwargs=None, mock_kwargs=None,
                     max_steps_per_episode=2000, deterministic=False,
                     device="cpu", verbose=False) -> CollectStats

collect_rollouts(...) -> (List[EpisodeRecord], CollectStats)   # 不写文件
```

`CollectStats`：`episodes/new_episodes/steps/new_steps/wall_seconds/workers/policy/backend/
mean_rank/rank_distribution/action_kinds/invalid_actions/truncated/errors/resumed_skipped`，
派生 `games_per_second` / `steps_per_second`（按本次新采集量计算，续采时为 0）。

---

## 5. 评测器（`hsbg/rl/evaluate.py`）

```python
evaluate(policy, *, episodes=20, seed=0, workers=1, seeds=None,
         num_players=8, opponent="heuristic", backend="auto",
         env_kwargs=None, mock_kwargs=None, max_steps_per_episode=2000,
         deterministic=False, device="cpu", name=None, verbose=False) -> EvalSummary

evaluate_many(policies, ...) -> List[EvalSummary]
comparison_table(summaries) -> str
```

* **复用 `hsbg/eval/metrics.py`** 的 `EvalResult`：mean_rank、bootstrap CI（默认 2000 次）、
  win_rate、top4/top-half、rank_distribution、invalid/truncated 计数；
* 固定种子集：第 `k` 局 = `seed + k`，或 `seeds=[...]` 显式指定；多进程时按 episode_id
  排序合并，**与 worker 数无关**（测试覆盖 workers=1 vs 3）；
* `EvalSummary` 额外提供：`games_per_second`、`steps_per_second`、`detailed()`（按名次的
  reward/步数、结束原因计数、seeds）、`episodes()`（逐局 rank/reward/steps/turns/reason）、
  `config`（评测配置）、`to_dict()`、`save(path)`、`format()`；
* 引擎感知教师也可评测：`--policy teacher`（仅真环境；mock 后端会提前报错）；
* CLI：可重复 `--policy` 打印对照表；`--json` 输出 JSON；`--out <path>` 落盘
  （便于回归对比）。`--out` JSON 结构：

```json
{
  "schema": "hsbg.rl.evaluate/v1",
  "created_at": "2026-10-18T18:00:00+08:00",
  "config": {
    "policy": "teacher", "policies": ["teacher"], "episodes": 20,
    "seed": 0, "seeds": null, "workers": 1, "num_players": 8,
    "opponent": "heuristic", "backend": "auto",
    "max_steps_per_episode": 2000, "deterministic": false, "device": "cpu"
  },
  "results": [
    {
      "name": "teacher", "policy": "teacher", "backend": "auto",
      "summary": {"episodes": 20, "mean_rank": 4.0,
                  "mean_rank_ci_low": 3.1, "mean_rank_ci_high": 4.9,
                  "win_rate": 0.05, "top_half_rate": 0.7, "...": "..."},
      "rank_distribution": {"1": 0.05, "...": "..."},
      "ranks": [3, 2, 4, 2, 3, 7, 1, 5, 7, 8, 5, 4, 2, 3, 8, 3, 3, 3, 4, 3],
      "episode_seeds": [0, 1, 2, "...", 19],
      "episodes": [
        {"episode_id": 0, "seed": 0, "rank": 3, "reward": -0.4,
         "turns": 12, "steps": 110, "reason": "eliminated"},
        "..."
      ],
      "config": {"policy": "teacher", "episodes": 20, "...": "..."},
      "detailed": {"by_rank": {"...": "..."}, "reasons": {"...": 3}}
    }
  ]
}
```

`EvalSummary.save(path)` 写出单个 result 的 `to_dict()`（不含外层 envelope）。

---

## 6. Gymnasium 包装（`hsbg/rl/gym_wrapper.py`）

> `gymnasium` 是**可选依赖**：`python -m pip install gymnasium`。
> 未安装时 `hsbg.rl` 其余功能完全不受影响；实例化 gym 类会抛 `ImportError` 并提示命令。

```python
from hsbg.rl.gym_wrapper import make_gym_env, check_env_smoke

env = make_gym_env(backend="auto", seed=0, time_limit=500)  # 可叠加 TimeLimit
obs, info = env.reset(seed=0)
mask = env.action_masks()                                    # sb3-contrib 兼容
obs, reward, terminated, truncated, info = env.step(int(np.flatnonzero(mask)[0]))
```

* **observation_space**：`spaces.Dict`，11 个字段，与
  `hsbg.policy.encoder.ObservationEncoder.encode_obs()` 输出**逐字段一致**：
  `entity_card/entity_num/entity_mask/entity_zone/entity_pos/global/`
  `cand_kind/cand_num/cand_src/cand_tgt/cand_mask`。
  因此"gym 采样 → 编码张量 → 策略网络"无需二次转换，可直接接 SB3 或自研训练循环。
* **action_space**：静态 `Discrete(CANDIDATE_MAX=64)`；真实合法动作由
  `action_masks()`（bool[CANDIDATE_MAX]）给出。越界动作不抛异常：回退 end_turn 并在
  `info["invalid_action"]=True` 标记（保证 `check_env` / 随机采样不崩）。
* **包装器**：
  * `TimeLimit(env, max_episode_steps)`：到步数截断 `truncated=True`，info 标
    `TimeLimit.truncated`；
  * `RecordEpisode(env, path, per_step=True, append=True)`：写与 collector 相同 schema 的
    JSONL（header/step/episode），支持中途 reset 记 `truncated`；
  * `AutoResetWrapper(env)`：终局自动 reset，旧终局观测放 `info["terminal_observation"]`，
    `info["terminal"]=True`。
* **`check_env` 冒烟**：`check_env_smoke(backend="mock")` 调用
  `gymnasium.utils.env_checker.check_env`，本项目已通过（含 seed 确定性 / space 包含 /
  step 契约检查）。`reset()` 会调用 `super().reset(seed=seed)` 以满足 gymnasium 的
  seed 确定性检查。
* 真实环境也可包装（`make_gym_env(backend="real")`，大 batch 时同样可用）。

---

## 7. 与 `hsbg.train` 的衔接（后续训练）

| 训练需要 | RL 接口层提供 |
|----------|----------------|
| BC 数据（obs → 教师动作） | `collect_rollouts("teacher", ...)` 返回带完整 `Observation` + 教师动作的 `EpisodeRecord`（**推荐：teacher 质量≈4.0–4.5**）；或 `collect_trajectories` 落 JSONL 后按 seed 重放 |
| PPO 在线 rollout | 两种选择：① `run_episode`/`collect_rollouts` 离线采样；② `hsbg.train.vec_env.SyncVecEnv` 包 `make_env()` 直接向量化在线训练 |
| checkpoint 推理 / 自蒸馏教师 | `make_policy("runs/.../policy_final.pt")` → `CheckpointPolicy`（贪心/采样可配） |
| 观测张量 | `hsbg.policy.encoder.ObservationEncoder.collate(obs_list)`；gym wrapper 的 Dict 观测与其逐字段一致 |
| 评测 | `hsbg.rl.evaluate`（与 `hsbg.train.evaluate` 独立，后者仍可继续用）；`--out` JSON 可做回归对比 |

数据采集建议：**离线高质量数据/BC 教师用 `teacher`（仅真环境）**；需要跨后端可移植、
或做吞吐/接口回归用 `heuristic`/`random`。

注意：**当前不训练**。collector/evaluate 只做推理与数据采集，不做参数更新。

---

## 8. 实测性能（本机 RTX 4060 Ti / i7，Windows，Python 3.13）

| 场景 | 规模 | 结果 |
|------|------|------|
| 真环境 collector `heuristic` | 4 workers × 40 局（seed 0–39） | 5.8 s，4,722 步 → **6.9 games/s**、810 steps/s；episode 均值 ≈118 步；mean_rank **6.20** |
| 真环境 collector `teacher` | 4 workers × 40 局（同一 seed 集） | 6.7 s，3,787 步 → **6.0 games/s**、567 steps/s；episode 均值 ≈95 步；mean_rank **4.375** |
| 真环境 evaluate `teacher` | 1 worker × 20 局 | 9.3 s → 2.2 games/s、224 steps/s；mean_rank **4.05** [3.20, 4.90]，win 5%、top_half 70% |
| 真环境 collector（mock 对照） | 4 workers × 100 局 | 0.41 s → **244 games/s**、13.9k steps/s |
| 真环境 evaluate `random` | 1 worker × 20 局 | 4.4 s → 4.6 games/s；mean_rank **7.90** [7.70, 8.00]（随机策略单局 ≈46 步，早死） |
| 真环境 evaluate `heuristic` | 2 workers × 20 局 | 4.8 s → 4.2 games/s、487 steps/s；mean_rank **6.15** [5.45, 6.80] |
| 真环境 collector `heuristic`（100 局基准） | 4 workers × 100 局 | 13.5 s，12,677 步 → 7.4 games/s、941 steps/s；mean_rank 5.70 |
| gym `check_env` | mock | 通过（`True`） |
| 真环境单步 | 8 人局 | ≈4–5 ms/步（heuristic）；teacher 复用环境已枚举的 descriptor（快路径），≈+10–30% |

> 吞吐会随机器负载波动（多次运行 teacher collector 在 5.5–7.2 games/s、heuristic 在
> 6.9–8.4 games/s 之间）。

**教师质量结论**（同一 seed 集 0–39 对照）：`teacher`（引擎感知）mean_rank **4.375**，
显著优于观测级 `heuristic` **6.20**（接近环境自带对手 4.24）；games/s 6.0 vs 6.9（−13%），
因为 teacher 单步略贵但单局更短（≈95 vs 118 步）。evaluate 20 局 teacher mean_rank **4.05**
（CI 3.20–4.90）。因此**离线采集/BC 数据建议用 teacher**；gym/可移植场景用 heuristic。

> teacher 性能优化：`TeacherPolicy` 优先复用环境本步已枚举的 `ActionDescriptor`
> （`env._step_actions`，与 `obs.candidates` 同源），只跑引擎教师的选牌逻辑，
> 避免二次 `enumerate_actions`；环境内部结构变化时自动回退公开的
> `engine.choose(game, hero, ctx)` 路径（动作匹配失败则回退 `end_turn` 并计数）。

JSONL 体积：真环境 100 局 / 12,677 步 → **13.9 MB**（≈1.1 KB/步，含棋盘/手牌/酒馆 card_id
与候选类型；`--no-board` 更小）；行数 = 1 header + 12,677 step + 100 episode。

---

## 9. 已知限制

1. **动态候选数**：动作空间是静态 `Discrete(CANDIDATE_MAX=64)`，必须用
   `action_masks()` 掩码；真实环境实测单步候选数上限正好 64。若未来环境超过 64 个候选，
   编码器会静默截断（丢动作）——需要同步上调 `CANDIDATE_MAX` 并重训策略/刷新 gym 空间。
2. **战斗内不可决策**：引擎自动结算战斗；RL 决策点只有招募阶段与 `phase="choice"`
   （发现/三选一/任务/饰品）。观测里只有"上一场对手的战前战团"（POMDP 边界），
   战斗过程中的目标选择/顺序不可见也不可控。
3. **`Observation.extra`（ENV_SPEC v2）已可用，但 RL 层默认不消费**：环境已把
   `frozen_tavern / powers / quest_progress / board_states` 等放进 `obs.extra`
   （并同步出现在 `info["obs_extra"]`）。RL 接口层默认忽略它（JSONL 需
   `--include-extra` 才落白名单字段），编码器/gym 观测空间也尚未把 extra 作为特征。
   若训练需要 frozen 等作为输入，建议在 `hsbg.policy.encoder` 增加 extra 特征块
   （属于训练侧改动，需 Lead 决定；RL 层接口不用改，`Observation.extra` 已可读取）。
4. **truncated 的 rank 语义**：`max_turns`/`max_steps` 截断时 `info["rank"]` 是环境估计值，
   不是最终名次；评测/采集会分别统计 `truncated` 数，分析时应把 truncated 局单列。
5. **多进程 policy 限制**：spawn 要求 policy 可 pickle；lambda/闭包只能单进程。
   `teacher` 请用字符串 spec（worker 内重建 + 各自 bind）。`TeacherPolicy` 的
   `__getstate__` 只序列化 `name/engine_kwargs`，不会把 env/引擎实例带进子进程。
6. **teacher 不可移植**：teacher 依赖真实 `BattlegroundsEnv`（`env.game`/`env.agent_hero`），
   mock 后端、gym 包装（若底层是 mock）都不能用；它复用 `hsbg.agents.heuristic`，
   属于"离线教师/强基线"，**不是**可部署策略。可部署策略请用 checkpoint 或观测级 heuristic。
7. **gymnasium 可选**：未安装时 gym 包装不可用（其余接口正常）；`install gymnasium` 是
   测试可选依赖，不进入项目硬依赖。
8. **Mock 环境不代表棋力**：`backend="mock"` 只验证接口/管线（确定性、结构、吞吐），
   其数值/名次是合成的，不能用于评价策略真实强度。
9. **JSONL 不是训练 token 流**：只存观测摘要 + 动作 + 奖励；需要实体张量时用
   `ObservationEncoder` 重新编码（或直接 `collect_rollouts` 拿 `Observation`）。
10. **teacher 动作匹配/快路径**：引擎 `ActionDescriptor → to_candidate()` 与观测候选同源；
    RL 层用 signature 多级匹配，匹配不到时回退 `end_turn`（`TeacherPolicy.fallbacks`
    计数可用于监控；当前实测 fallbacks=0）。性能快路径复用 `env._step_actions.descriptors`
    （环境层内部字段），若该字段缺失/长度不匹配会自动回退公开 `engine.choose()`，
    因此对 env 重构是**软依赖**（只影响速度，不影响正确性）。

---

## 10. 待办 / 与 Lead、env-builder 的接口协商

- [x] `Observation` v2：环境已加入 `extra`（frozen_tavern / powers / 任务进度等，
      `OBS_VERSION` 在 JSONL header 里自动记录为 2）；RL 层已能通过
      `obs.extra` / `--include-extra` 读取，暂不作为模型特征。
- [ ] 若要把 `obs.extra` 作为策略输入特征：在 `hsbg.policy.encoder` 增加 extra 特征块
      （会改变编码器 dims → 旧 checkpoint 不可复用，需重训/升版本）。
- [ ] 真环境 `info["rank"]` 在所有 truncated 路径上的语义确认（是否总是给出当前名次估计）。
- [ ] 若后续要支持"战斗前布阵/技能目标"等新决策点：用新的 `phase` + `CandidateAction.kind`
      扩展（RL 层 `Policy`/`run_episode` 无需改动，只需环境层枚举候选）。
- [ ] 大规模采集时的并行度调优（当前 4 worker 已接近引擎单核瓶颈；更多 worker 受 CPU 核数限制）。
- [ ] 与 `hsbg.train` 的在线向量化训练（VecEnv）做一次端到端对接验证（训练暂停中，暂未做）。
- [ ] `teacher` 目前复用 `hsbg.agents.heuristic.HeuristicPolicy`；若后续有更强教师
      （搜索/学习策略）可直接替换 `hsbg.agents.registry.make_opponent("teacher")` 的实现，
      RL 层的 `teacher` spec / bind_env 无需改动。
