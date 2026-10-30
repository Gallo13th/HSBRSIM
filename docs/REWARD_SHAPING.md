# 势函数奖励塑形（Reward Shaping）

> 状态：已实现，**默认关闭**（`--shaping-coef 0`）。关闭时采集 records / 打包 / GAE
> 与旧路径逐位一致。
>
> 代码：`hsbg/az/train/reward_shaping.py`、`hsbg/az/train/parallel_collect.py`、
> `hsbg/az/train/ppo.py`、`scripts/train_entity_sync.py`；
> 测试：`tests/test_reward_shaping.py`。

## 1. 动机：只奖名次 → 保守局部最优

`scripts/quality_monitor.py` 对 C0 champion（mean rank 1.746，vs 7 bot）的诊断：

| 指标 | 实测 | 真实 10k+ MMR 参考 | 结论 |
|---|---|---|---|
| 第 9 回合起 tier | **恒为 4** | 逐步升 5 / 6 | 从不升级 |
| 战团强度 p50（t13–15） | 真实值的 **3%–13%** | t15 p50 ≈ 26516 | 战团规模差 1–2 个数量级 |
| 出局回合 p50 | 15 | — | 能活到中后期 |
| 出局时强度 p50 | **746** | t15 p50 26516 | 「活着但空板」 |

现有奖励是稀疏终局奖励：每个 seat 末步 `u(rank)`（rank 1..8 → `1, 0.71, …, -1`），
其余步只有可选 `-step_penalty`。对弱 bot 局面，「不买怪、不升级、少掉血」也能稳定前四，
于是策略收敛到**保守局部最优**：名次不差，但战团强度完全跟不上真人。

塑形项把「战团更大 / 酒馆更高」变成**每决策的稠密奖励**，给策略一条除名次外的
直接梯度；势函数形式保证（γ 一致时）不改变最优策略。

## 2. 公式

对 learner seat（其它座位不算）：

```
Φ(s) = w_str * Σ(atk + hp) + w_tier * TIER_BONUS[tier]
F_t  = λ * (γ * Φ(s_{t+1}) - Φ(s_t))
reward_t = F_t + (旧奖励：-step_penalty；末步再加 u(rank))
```

- `Σ(atk+hp)`：与 `hsbg/az/train/mirror_snapshots.py::board_strength` **同定义**
  （board 中每个 minion 的 atk+hp 相加，空 board = 0）。
- `TIER_BONUS` 默认 `[0,0,20,60,150,400,900]`，**按 tier 直接索引**（索引 0 为占位）：
  tier1→0、tier2→20、tier3→60、tier4→150、tier5→400、tier6→900；
  tier≤0 / tier≥7 / 缺省 → 0（tier 7 是特殊等级；需要时传更长的表）。
- `γ = 0.995`（`SHAPING_GAMMA`），`λ = --shaping-coef`，`w_str = --shaping-w-str`，
  `w_tier = --shaping-w-tier`。
- 只作用于 **learner seat**；`opponent=self`（8 座都是 learner）不支持，启动时报错。

### 2.1 s' 的定义（为什么每决策只读一次 Φ）

learner MDP 的一步 = 「learner 动作 + 对手/战斗推进到下一次 learner 决策」。所以

```
s_t     = 第 t 次 learner 决策前的状态
s_{t+1} = 第 t+1 次 learner 决策前的状态   （= 动作执行 + 对手回应之后）
```

实现上在**每个 learner 决策前读一次 Φ**；这个值同时是上一决策的 `Φ(s')`。
局末 / 截断的最后一决策按 `Φ(terminal) = 0`（有限时域目标的标准处理）。
这样每局累计塑形奖励满足望远镜求和：

```
Σ_t γ^t F_t = λ * (γ^T Φ(terminal) − Φ(s_0)) = −λ Φ(s_0)   （Φ(terminal)=0）
```

**每决策只读一次状态，是「前后各取一次」的等价优化**：省掉一次序列化，且 s' 用的
就是真正的下一决策状态（而不是动作后、对手尚未行动的中间态）。

## 3. 不改变最优策略的论证

Potentially-based reward shaping（Ng, Harada & Russell, 1999）：

若 `F(s,a,s') = γΦ(s') − Φ(s)`，则对任意 `Φ`、任意策略 `π`，

```
Q'_π(s,a) = Q_π(s,a) − Φ(s)
V'_π(s)   = V_π(s) − Φ(s)
```

因此 `Q'_π` 与 `Q_π` 的**动作序不变**，最优策略集合不变。λ 只是整体缩放，不影响
argmax。两个前提：

1. **γ 与目标折扣一致**。训练入口当前 GAE `γ=1.0`（回合制 + 终局 utility），而塑形按
   任务约定用 `γ=0.995`；严格不变性要求两者一致。`0.995` 等价于对「越早变强」略加
   前视权重，实践中偏差 O(0.5%)。若要做严格 A/B，可把训练 `--lam`/GAE γ 与塑形 γ
   对齐后重跑。
2. **终局势能为 0**：实现里最后一决策用 `Φ(terminal)=0`，避免「终局战团大小」直接
   进入回报（否则会把名次奖励替换成终局 board 奖励）。

## 4. 参数建议

| 参数 | 默认 | 建议 |
|---|---|---|
| `--shaping-coef λ` | 0（关） | **先 1e-4**（5e-5 ~ 2e-4）；Φ 上万后降到 1e-5 量级 |
| `--shaping-w-str` | 1.0 | 保持 1.0（Σ(atk+hp) 与真实强度线性相关） |
| `--shaping-w-tier` | 0.5 | 0.5；想让升级更快可到 1.0，但注意 tier 奖励会与 board 奖励同量级 |
| `--shaping-tier-bonus` | `0,0,20,60,150,400,900` | 保持；tier6（900）是主要激励，tier5（400）次之 |

量级参考（用于选 λ）：

- 终局名次 utility 跨度只有 **2**（+1 … −1）。
- champion t15：强度 p50 ≈ 746，tier4 → `Φ ≈ 746 + 0.5*150 = 821`；
  真实 10k+ MMR t15 强度 p50 ≈ 26516 → `Φ ≈ 26516 + 0.5*900 ≈ 26966`。
- 单次 F 的量级 ≈ `λ * ΔΦ`（升 tier / 买大怪时 ΔΦ 可达数百），局末
  `F_last = −λ*Φ(last)`；但**整局求和**因望远镜 + `Φ(terminal)=0` 几乎为 0，所以
  要看逐决策 F 的量级，而不是整局均值。
- `λ=1e-4`：champion 局末项 ≈ `−0.08`、一次 tier6 升级 ≈ `+0.045`；human 强度
  局末项 ≈ `−2.7`（已与名次 utility 同量级）。
- `λ=1e-3`：champion 局末 ≈ `−0.8`、human ≈ `−27`，明显会主导名次奖励。
- 结论：**从 1e-4 起步（甚至 5e-5）**；监控 `reward_shaping_abs_max`，让它的典型值
  保持在 `0.2–0.5`（名次 utility 跨度的 10%–25%）以内。若模型战团已接近真人
  （Φ 上万），把 λ 再降一个数量级。

推荐起步命令（在现有训练命令上加）：

```bash
PYTHONPATH=rust/python:. python scripts/train_entity_sync.py \
  ... 原有参数 ... \
  --shaping-coef 1e-4 \
  --shaping-w-str 1.0 --shaping-w-tier 0.5 \
  --shaping-tier-bonus 0,0,20,60,150,400,900
```

## 5. 实现位置与数据流

| 位置 | 作用 |
|---|---|
| `hsbg/az/train/reward_shaping.py` | Φ / F / tier 表 / `RewardShaper` / 开销统计与多 worker 聚合 |
| `parallel_collect.collect_ppo_lockstep` | lock-step 主路径：每决策前读 Φ，F 写入该条 record 的 `reward` |
| `parallel_collect._one_game` | 逐局并行路径（`--workers>1` / 非 lockstep）同样接线 |
| `ppo.collect_ppo_batch` | 串行采集路径（`--workers 1 --processes 1`）同样接线 |
| `ppo.pack_records_arrays` | 有 `reward` 字段时额外打包 `rewards`（默认关闭时输出键集合不变） |
| `ppo.build_batch_from_records` / `build_batch_from_arrays` | 把 record `reward` 作为基础项，末步再加 `u(rank)`；无字段时走旧公式 |
| `process_pool` | 汇总 worker 的塑形统计到 collect meta（跨 shard 加权） |
| `scripts/train_entity_sync.py` | `--shaping-*` CLI；history 的 `ppo` 段写 `shaping_coef`/`reward_shaping_mean` |

采集 meta（history 的 `collect` 段）新增字段（**仅 coef≠0 时出现**）：

```
shaping_coef, shaping_gamma, shaping_w_str, shaping_w_tier, shaping_tier_bonus,
shaping_calls, shaping_decisions, shaping_seconds,
reward_shaping_sum, reward_shaping_mean, reward_shaping_abs_mean,
reward_shaping_abs_sum, reward_shaping_abs_max, shaping_overhead_pct
```

history 的 `ppo` 段（每个 iteration）：

```json
{"shaping_coef": 1e-4, "reward_shaping_mean": 0.00042, ...}
```

## 6. 开销

Φ 从标准观测 `game.observe(seat)` 读取，而不是 `player_json`：

- board 块 7×31 里已有 `present/atk/hp`（atk/hp 编码为 `raw/10`），global 的 `tier`
  编码为 `raw/6`；用 `memoryview.cast("f")` 只读 22 个槽位。
- 单次 `potential(game, seat)`（含 `observe`）实测 **≈ 4–7 µs**（CPU，Python 3.10；
  numpy 小数组版约 14 µs，已替换为 `memoryview.cast("f")`）。
- 对照：`game.player_json` 6–50 µs，再 `json.loads` 全量解析 40–350 µs；本实现比
  「player_json + json」快 **1–2 个数量级**。
- CPU tiny 实测（2–4 局、`--fast-act 1`，`shaping_seconds / elapsed`）：

  | 路径 | 局数 | Φ 读取 | 开销 |
  |---|---|---|---|
  | lockstep（单进程） | 2 | 112 次 | **1.0%–1.2%** |
  | 逐局串行 `collect_ppo_batch` | 2 | 161 次 | **0.94%** |
  | 逐局并行 workers=2/4 | 4 | 247 次 | **2.2%** |
  | 完整 1 iteration（tiny，CPU） | 2 | 130 次 | **3.1%** |

  真实训练模型前向远大于 Φ 读取，占比更低。目标 `<5% collect` 达成。

### 6.1 冒烟数字（CPU tiny，2 局，seed=2）

| 配置 | records | 有 `reward` 的条数 | 奖励均值 | 开销 |
|---|---|---|---|---|
| `coef=0`（关） | 112 | 0 | −0.017857 | — |
| `coef=1e-4` | 112 | 86 | −0.017864 | 1.17% |
| `coef=1e-3` | 112 | 86 | −0.017925 | 1.09% |

方向（λ=1e-3，按相邻决策 Φ 变化分组）：战团变大 17 次，平均 `F=+0.00843`；
变小 12 次，平均 `F=−0.01213`；不变 83 次，`F≈0`（只剩 `γ−1` 的极小负项）。
λ=1e-4 时同比缩放为 `+0.000843 / −0.001213`。**变大 → 奖励更高，方向正确。**

> 注意：整局塑形奖励之和 ≈ 0（望远镜求和 + 局末 Φ=0），所以「奖励均值」几乎不变；
> 评估塑形是否生效要看**逐决策 F 的正负与 `reward_shaping_abs_max`**，而不是整局均值。

测试里还有宽松上界的微基准（`test_potential_microbench`），CI 抖动不会误报。

## 7. 如何关闭 / 回退

- 默认即关闭：`--shaping-coef 0`（或不传）。关闭时：
  - records 没有 `reward` 字段；
  - `pack_records_arrays` 没有 `rewards` 键；
  - GAE 奖励与旧公式逐位一致（同 seed 回归见
    `test_zero_coef_bitwise_identical_and_reward_path`）；
  - collect meta 不出现 `shaping_*` 键。
- 回退 = 下一个 iteration 直接把 `--shaping-coef 0`；无需改数据/checkpoint
  （塑形不写入模型状态）。

## 8. 失败判据（何时降 λ / 关闭）

监控 `history.jsonl` 的 C0 评测与 collect 段的
`reward_shaping_abs_max` / `reward_shaping_abs_mean`：

1. **C0 退化**：mean rank 比开启前基线差 > 0.05，或 top4 掉 > 2 个百分点 → 先把 λ
   降到 1e-5 量级，再不行关闭。
2. **塑形主导**：`reward_shaping_abs_max` 持续 > 0.5（名次 utility 跨度的 25%），
   或 `reward_shaping_abs_mean` 与终局奖励同量级 → 降 λ 一个数量级。
3. **只升级不变强**：tier 分布上移但战团强度 p50 不涨 → 降 `--shaping-w-tier`
   （如 0.2）或把 tier 表压平；说明模型在刷 tier 奖励。
4. **只堆怪不升级**：强度 p50 涨、tier 仍恒 4 → 提高 `--shaping-w-tier`/tier6 bonus。
5. **与注入/镜像冲突**：注入的人类战团替换的是对手座位，Φ 只算 learner，不受影响；
   若发现塑造奖励异常大，先查 `shaping_decisions` 是否等于 decisions。

## 9. 快速自检

```bash
# 单测（纯函数 + 引擎接线 + 入口参数）
PYTHONPATH=rust/python:. python -m pytest tests/test_reward_shaping.py -q -p no:warnings

# 全量
PYTHONPATH=rust/python:. python -m pytest tests -q -p no:warnings
```
