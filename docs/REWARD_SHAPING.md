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
- `γ_s = --shaping-gamma`，**默认空 = 跟随训练 γ**（`--gamma` / `PPOConfig.gamma`，
  当前 1.0）。**只有 `γ_s == 训练 γ` 时**下面的望远镜求和与策略不变性成立；
  显式设成不一致的值会在启动期警告并记录累计偏差（见 §3）。
- `λ = --shaping-coef`，`w_str = --shaping-w-str`，`w_tier = --shaping-w-tier`。
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
Σ_t γ_t^t F_t = λ * (γ_s^T Φ(terminal) − Φ(s_0)) = −λ Φ(s_0)   （γ_s=γ_t，Φ(terminal)=0）
```

**每决策只读一次状态，是「前后各取一次」的等价优化**：省掉一次序列化，且 s' 用的
就是真正的下一决策状态（而不是动作后、对手尚未行动的中间态）。

## 3. 不改变最优策略的条件

Potential-based reward shaping（Ng, Harada & Russell, 1999）：

若 `F(s,a,s') = γΦ(s') − Φ(s)` 且 **γ 就是目标回报的折扣**，则对任意 `Φ`、任意策略 `π`，

```
Q'_π(s,a) = Q_π(s,a) − Φ(s)
V'_π(s)   = V_π(s) − Φ(s)
```

因此 `Q'_π` 与 `Q_π` 的**动作序不变**，最优策略集合不变。λ 只是整体缩放，不影响
argmax。两个前提：

1. **塑形 γ_s 与训练 γ 严格一致**。本仓库的训练折扣是 `PPOConfig.gamma`（CLI
   `--gamma`，当前 **1.0**，回合制 + 终局 utility）；**`--lam` 是 GAE 的 λ（s9d 用
   0.995），不是折扣 γ**，不能拿它和塑形 γ 对齐。
   - 若 `γ_s == γ_t`，按训练折扣求和严格望远镜：
     `Σ_t γ_t^t F_t = λ(γ_t^T Φ(s_T) − Φ(s_0)) = −λΦ(s_0)`（`Φ(s_T)=0`），与策略无关。
   - 若 `γ_s ≠ γ_t`，多出 `λ(γ_s−γ_t) Σ_t γ_t^t Φ(s_{t+1})`；训练 γ=1 时即
     `−λ(1−γ_s) Σ_t Φ(s_t)`。这是**随回合长度 / 势值累积的惩罚**（长局、强局被系统性
     惩罚），与策略相关，因此不满足策略不变性。
2. **终局势能为 0**：实现里最后一决策用 `Φ(terminal)=0`，避免「终局战团大小」直接
   进入回报（否则会把名次奖励替换成终局 board 奖励）。

### 3.1 历史实现的错误（P0）

2026-10 之前的实现把 `γ_s` 硬编码为 `SHAPING_GAMMA=0.995`，而训练 γ=1.0；旧版文档
把这写成「偏差 O(0.5%)」，**这是错的**：0.5% 是**每决策**的折扣差，整局误差按
`Σ Φ(s_t)` 累积（T 步约 `(1−γ_s)·T` 的相对量），不是单步相对误差。

实测（生产 run `runs/az_entity_s9d`，c=1e-3、w_tier=1.0、192 局、iter0）：

| 量 | 值 |
|---|---|
| decisions | 36,745 |
| `reward_shaping_sum`（整局未折扣求和） | **−111.48** |
| 每局 | **≈ −0.58** |
| 名次效用全距（+1 … −1） | 2.0 |
| 占比 | **≈ 29%** |

起始 `Φ(s_0)≈0`，所以 `−λΦ(s_0)` 几乎为 0，这 −111 基本全部来自
`−λ(1−γ_s)ΣΦ(s_t)` 的累积项。它与跨 2 个名次的效用同量级，足以改变策略；这就是
「长局被系统性惩罚」的直接证据。

### 3.2 修复后的行为

- **默认**：`shaping_gamma=None`（CLI `--shaping-gamma` 留空）= 跟随训练 γ
  （`PPOConfig.gamma` / `--gamma`），此时 F 逐决策严格望远镜，整局和 = `−λΦ(s_0)`。
- **显式不一致**：启动期打印 `UserWarning` + 参考偏差估算（不静默）；collect meta
  记录 `shaping_gamma_aligned=false` 与 `reward_shaping_bias_sum`（本次采集实测的
  `λ(γ_s−γ_t)Σ_t γ_t^t Φ(s_{t+1})` 累计值，跨局求和）。
- 参考估算（函数 `shaping_bias_per_episode`，T=45 决策/局、Φ̄=5000、c=1e-3、
  γ_s=0.995 vs γ=1.0）：每局额外 ≈ **−1.125**（全距 2 的 56%）。真实值以
  `reward_shaping_bias_sum` 为准，不要用估算替代实测。
- `shaping_coef=0` 时完全不解析 `shaping_gamma`（连非法值也不校验），旧路径逐位等价。

## 4. 参数建议

| 参数 | 默认 | 建议 |
|---|---|---|
| `--shaping-gamma γ_s` | 空（= 跟随 `--gamma`） | **保持空**；只有做「不一致折扣」消融时才显式设值，且先读启动警告 |
| `--shaping-coef λ` | 0（关） | s9d 生产用 1e-3 / w_tier=1.0；保守起步 1e-4（5e-5 ~ 2e-4） |
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

> 不传 `--shaping-gamma`（默认空）= 跟随 `--gamma`；这是满足策略不变性的唯一推荐配置。

## 5. 实现位置与数据流

| 位置 | 作用 |
|---|---|
| `hsbg/az/train/reward_shaping.py` | Φ / F / tier 表 / `RewardShaper` / 开销统计与多 worker 聚合 |
| `parallel_collect.collect_ppo_lockstep` | lock-step 主路径：每决策前读 Φ，F 写入该条 record 的 `reward` |
| `parallel_collect._one_game` | 逐局并行路径（`--workers>1` / 非 lockstep）同样接线 |
| `ppo.collect_ppo_batch` | 串行采集路径（`--workers 1 --processes 1`）同样接线 |
| `ppo.pack_records_arrays` | 有 `reward` 字段时额外打包 `rewards`（默认关闭时输出键集合不变） |
| `ppo.build_batch_from_records` / `build_batch_from_arrays` | 把 record `reward` 作为基础项，末步再加 `u(rank)`；无字段时走旧公式 |
| `process_pool` | 汇总 worker 的塑形统计到 collect meta（跨 shard 加权）；把任务级训练 γ 透传给采集器 |
| `scripts/train_entity_sync.py` | `--shaping-*` / `--gamma` CLI；启动期校验折扣一致性；history 的 `ppo` 段写 `shaping_coef`/`shaping_gamma`/`reward_shaping_mean`/`reward_shaping_bias_sum`/`adv_std` |

采集 meta（history 的 `collect` 段）新增字段（**仅 coef≠0 时出现**）：

```
shaping_coef, shaping_gamma, shaping_gamma_train, shaping_gamma_aligned,
shaping_w_str, shaping_w_tier, shaping_tier_bonus,
shaping_calls, shaping_decisions, shaping_seconds,
reward_shaping_sum, reward_shaping_mean, reward_shaping_abs_mean,
reward_shaping_abs_sum, reward_shaping_abs_max, shaping_overhead_pct,
reward_shaping_bias_sum
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

> 下表是**修复前**（γ_s=0.995）的实测；修复后 γ_s=训练 γ=1，不变步的 F 严格为 0
> （不再有 0.5% 的残余负项），其余数值差异 <1%。

| 配置 | records | 有 `reward` 的条数 | 奖励均值 | 开销 |
|---|---|---|---|---|
| `coef=0`（关） | 112 | 0 | −0.017857 | — |
| `coef=1e-4` | 112 | 86 | −0.017864 | 1.17% |
| `coef=1e-3` | 112 | 86 | −0.017925 | 1.09% |

方向（λ=1e-3，按相邻决策 Φ 变化分组）：战团变大 17 次，平均 `F=+0.00843`；
变小 12 次，平均 `F=−0.01213`；不变时 `F≈0`。
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
  - collect meta 不出现 `shaping_*` 键；
  - `--shaping-gamma` 即使给了非法值也不解析/不报错（关闭路径零影响）。
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
6. **折扣不一致**：`shaping_gamma_aligned=false` 或 `reward_shaping_bias_sum≠0` →
   立刻把 `--shaping-gamma` 留空（跟随训练 γ）。只要不一致，§3 的策略不变性就不成立，
   此时 C0/human 面板的任何差异都不能归因于塑形本身。

## 9. 快速自检

```bash
# 折扣对齐专项（本 P0 修复）
PYTHONPATH=rust/python:. python -m pytest tests/test_reward_shaping_gamma.py -q -p no:warnings

# 单测（纯函数 + 引擎接线 + 入口参数）
PYTHONPATH=rust/python:. python -m pytest tests/test_reward_shaping.py -q -p no:warnings

# 全量
PYTHONPATH=rust/python:. python -m pytest tests -q -p no:warnings
```

## 10. 本次 P0 消融（2026-10-30，A/B 60 iter）

协议：从 `runs/az_entity_s9d/model.pt` 起，同 seed=15100、同 s9d 超参（192 games/iter、
`--move-guard 1`、λ 见下），两臂各 60 iter ≈ **2.25M decisions**；评测同 seed：
human 96 局（seat 0..7 × 12，`auto` 分位）、bot 64 局、quality 64 局。

| 指标 | A：`--shaping-coef 0` | B：`--shaping-coef 1e-3`，γ_s=γ=1.0 |
|---|---|---|
| human mean rank / top4 / win | **6.458** / 11.5% / 0% | **6.250** / 16.7% / 0% |
| human 配对差 B−A（bootstrap 95% CI） | — | **−0.208 [−0.427, +0.010]**；31/16/49 局 |
| bot mean rank / top4 / win | **1.703** / 100% / 46.9% | **1.797** / 98.4% / 42.2% |
| bot 配对差 B−A（95% CI） | — | **+0.094 [−0.125, +0.313]** |
| tier p50 @ t15 / tier≥5 @ t15 | **5.0** / 52.4% | **4.0** / 38.5% |
| 战团强度比 @ t15（ours p50 / real） | 3.35% | 3.36% |
| `reward_shaping_abs_max`（mean / max） | — | **16.12 / 56.98** |
| 优势 std（60 iter 均值） | **0.268** | **0.848**（方差 ≈10×） |
| `reward_shaping_bias_sum` | — | **0.0**（对齐，望远镜成立） |
| collect 开销 | — | 4.05%（mean） |

结论：

1. **按本任务判据，B 未显著劣于 A**（human 配对差 CI 含 0；点估计甚至略好，符号检验
   31:16、p≈0.04，但均值效应只有 0.21 名）。因此不能得出「塑形有害」的结论。
2. **但塑形也没有带来可测收益**：human rank 差 0.2 名在噪声内，tier/强度比没有改善
   （t15 tier 反而低 1 档），bot 面板略差。
3. **1e-3 的奖励尺度不可接受**：`|F|` 均值峰值 16、最大 57，是名次效用全距 2 的
   **8–28 倍**；优势方差被放大 ~10×。这会把 PPO 的优化目标从名次换成「刷 board/tier」，
   与 §4 的监控建议（`|F|max` 0.2–0.5）相差 ~30–80 倍。
4. **s10 建议**：
   - 首选**关闭塑形**（`--shaping-coef 0`），与论文只使用名次奖励一致；本次 A/B
     未证明它能改善 human 面板。
   - 若必须保留稠密塑形：保持 `--shaping-gamma` 留空（严格跟随训练 γ=1.0），并把
     λ 从 1e-3 降到 **2e-5 ~ 5e-5**（`|F|max` 约 0.3–0.7），再重跑同协议 A/B；
     **不要**沿用 1e-3 / `w_tier=1.0`。
