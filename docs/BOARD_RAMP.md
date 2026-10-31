# 对手强度课程（board ramp）：席数 / 概率 / 分位按累计 decisions 爬坡

> 目标：**先降低训练对手强度，让模型活到能摸到缩放载体的 tier4–6，再逐步把对手加回来。**
> 代码：`hsbg/az/train/ppo.py`（`parse_board_ramp` / `BoardRampController` /
> `ramp_progress_metrics` / `board_ramp_history`）、`scripts/train_entity_sync.py`
> （CLI + 每 iteration 生效值 + history + 自适应门控）、`scripts/quality_monitor.py`
> （注入对照 + 存活/tier 指标）、`tests/test_board_ramp.py`。

---

## 1. 动机：s15 的训练分布「太强」，模型整局停在 tier1–3

s15（`runs/az_entity_s15`）的训练分布 = **人类战团 5 席 × p0.9（fidelity=full）**
+ 回合末快照镜像 2 席 × p0.2（p75）+ 换位守卫。实测证据：

| 证据 | 数值 | 位置 |
|---|---|---|
| 200 局 tier 分布（按回合） | t1..t6 = **822 / 706 / 483 / 96 / 3 / 3** | s15 分布质量面板 |
| 规则教师活到 t12 | **0 / 200 局** | `scripts/carrier_teacher.py`（s15 同分布） |
| 同教师 7-bot 宽松分布 | 84 局活到 t12，`r(载体回合, Σ12) = +0.255 [0.060, 0.443]`（CI 不含 0） | `carrier_teacher --bot-only` |
| 载体（11 张施法成长随从）常见 tier | **tier4–6** | `data/scaling/carriers.json` |

因果链：**对手太强 → 活不到 tier4–6 → 摸不到载体 → 学不到缩放**。s15 的 tier≥4
回合只有 96+3+3 = 102 / 2113 ≈ **4.8%**，也就是说缩放相关的决策在训练分布里几乎不存在。

课程假设：把对手强度压到「模型能稳定活到 t10–12」的水平，让 tier≥4 回合占比先涨起来，
再按**累计 learner decisions**（不是 iteration，也不是 wall time）分段加回强度。
`docs/CARRIER_SCALING.md` / `docs/TIER_TARGET.md` / `docs/REWARD_SHAPING.md`
提供了「怎么用后期」的杠杆，本文件只解决「怎么先活到后期」。

---

## 2. 机制与语法

### 2.1 CLI（`scripts/train_entity_sync.py`）

| 开关 | 默认 | 含义 |
|---|---|---|
| `--human-board-ramp` | `""` | 席数/概率课程：`decisions:seats:p,...` |
| `--human-board-quantile-ramp` | `""` | 分位课程（独立）：`decisions:quantile,...` |
| `--ramp-mode` | `step` | `step`=分段常数 / `linear`=段内线性插值 |
| `--ramp-adaptive` | `0` | `1`=用存活/tier 指标提前或推迟升档 |
| `--ramp-window` | `5` | 门控滑窗 iteration 数 |
| `--ramp-survive-threshold` | `0.25` | 升档门槛：存活到 t12 比例 |
| `--ramp-tier4-threshold` | `0.30` | 升档门槛：tier≥4 比例 |
| `--ramp-delay-decisions` | `2M` | 不达标时把后续档位整体推迟多少 decisions |
| `--ramp-max-forced-per-game` | `12` | 强制结束回合/局 超过该值 → 判定「假存活」，不升档 |
| `--ramp-start-decisions` | `0` | 续训时的 decisions 偏移（见 §9） |
| `--ramp-quality-json` | `""` | 可选：离线质量统计（`quality_monitor.py` 输出），门控优先用它 |

`decisions` 支持 `K` / `M` / `B` 后缀（`10M`、`2.5M`、`500K`）。示例：

```bash
--human-board-ramp "0:1:0.30,10M:2:0.50,20M:3:0.70,30M:5:0.90" \
--human-board-quantile-ramp "0:p75,20M:p90" \
--ramp-mode step --ramp-adaptive 1 --ramp-window 5
```

### 2.2 语义

- **按累计 learner decisions 求值**：该 iteration **采集开始前**已经累计的 learner
  决策数（与 `--curriculum-stage` / `seq_coef` / `bc_coef` 的 ramp 同一口径）。
  每档的生效边界是 `decisions >= 控制点`。
- **`step`（默认）**：分段常数；到点整档切换（seats 与 p 同时变）。
- **`linear`**：段内线性插值；`p` 连续，`seats` 线性插值后**四舍五入**（1.5→2、2.5→3，
  不用 Python 的银行家舍入）并夹在 `1..7`。
- **边界外**：早于首个控制点取第一档；晚于最后一个控制点**保持最后一档**（不会溢出）。
- **分位课程**（`--human-board-quantile-ramp`）是**类别**，只做分段常数、不插值；
  取值限 `auto/p50/p75/p90/max`；与席数/p 课程**互相独立**（可以只开一个）。
- **非法输入启动期 fail-fast**：片段必须三段、decisions 严格递增、seats ∈ `1..7`、
  p ∈ `[0,1]`、decisions 非负有限。报错形如
  `[error] 对手强度课程参数非法: board-ramp seats 必须在 1..7: '0:8:0.3'`。

### 2.3 生效路径（为什么真的会改变采集）

训练循环每 iteration 用 `BoardRampController.state(cum_decisions)` 求
`(seats, p, sample)`，写进 `CollectConfig.human_board_seats / human_board_p /
human_board_sample`，再交给采集进程池 worker 的 `human_board_pool.inject_turn`
（与 s15 完全同一条注入路径）。控制器是**唯一**的取值来源，history 记录的也是它。

> 注意：人类战团注入只在 **`--processes > 1` 且 `--lockstep 1`** 的采集路径生效
> （`process_pool` worker 内）；`--processes 1` 的逐局路径不读这些字段（会打印告警）。

---

## 3. 自适应门控（`--ramp-adaptive 1`）

不按「到点就升」，而是按**模型是否真的学会了后期**决定：

- 每个 iteration 取两个指标（0..1）：
  - `survive_t12`：该 iteration 里活到 **t12** 的局占比；
  - `tier_ge4`：该 iteration 里达到 **tier≥4** 的局占比；
- 取最近 `--ramp-window`（默认 5）个 iteration 的均值；
- **升档**：`survive_t12 ≥ 0.25` **且** `tier_ge4 ≥ 0.30` → 立刻跳一档（`band+1`）；
- **推迟**：不达标 → 把后续控制点整体后移 `--ramp-delay-decisions`（默认 2M），
  **每档最多推迟一次**（防止无限推迟把课程卡死）；
- **强制结束保护**：窗口内 `forced_per_game > --ramp-max-forced-per-game`（默认 12，
  s15 真实值 ≈ 0.16）时**不允许升档**——否则「活到 t12」可能是动作上限强制结束回合
  刷出来的假存活（模型在 Play/Cancel 循环里）；
- 只在「窗口满 + 距上次档位变化 ≥ window 个 iteration」时动作；
- 档位**单调不减**（内部 x 只增不减，推迟也不会回退档位）。**提前升档也是永久的**：
  升上去之后如果该档太强，课程会停在这一档（不断推迟下一档）而不是降回去——所以
  `--ramp-window` 不要设得太小（默认 5 已足够稳）。

> **pipeline 滞后**：`--pipeline 1` 时 `collect(k+1)` 在 update(k) 之前提交，所以 ramp
> 值在**提交采集时**求值——最多滞后 1 个 iteration（与 batch 版本的滞后同源）；
> history 里记的就是实际用的那一组值。

> **代理的已知局限**：轨迹代理只能看到 `turn`，看不到真实 `tier`。`tier_ge4` 用
> `max_turn>=8` 代理，等价于「活过了 tier_target 曲线里 tier4 该到的回合」，在
> 「活到 t12 但整局停在 tier3」的模型上会**高估**（s15 模型正是这种情况，见 §4.2）。
> 想要真实的 tier 观测，用 `--ramp-quality-json` 把 `quality_monitor.py` 的输出
> 接进来（离线面板每 ~10M decisions 跑一次即可，48 局 ≈ 1 分钟）。

**指标来源优先级**（`ramp_progress_metrics`）：

1. `--ramp-quality-json`：离线质量统计（`quality_monitor.py` 的
   `survive_t12_ratio` / `tier_ge4_ratio`，**真实 tier 观测**）；
2. 采集 meta 里的同名键（`collect.survive_t12_ratio` / `collect.tier_ge4_ratio`，供
   未来接在线质量面板）；
3. **轨迹代理**（默认）：`turns` 只记录 learner 决策回合，按 `game_id` 取每局最大 turn：
   - `survive_t12 = mean(max_turn >= 12)`（真口径）；
   - `tier_ge4 = mean(max_turn >= 8)`（**代理**：`tier_target` 曲线 `7:4,9:5,12:6`
     意味着第 7 回合该到 tier4，这里保守取 8；没有直接 tier 观测时的替代口径）。

`history.jsonl` 的 `ramp_gate` 段会写 `survive_t12 / tier_ge4 / source / max_turn_p50 /
forced_end_turns / forced_per_game / window / events`，可核对门控到底看了什么。

---

## 4. 短跑验证（小规模、不干扰 s15）

> 环境：`cuda:2`（s15 占用 3–6 未动；cuda:7 被其它用户进程占用），4 个 actor 进程，
> 48 局/iter，`--checkpoint runs/az_entity_s15/model.pt`，人类战团
> `library_real_quasi_full.jsonl` + `--human-board-fidelity full`。

### 4.1 课程调度真的改变生效值

**A. 按任务书原样命令** `--human-board-ramp "0:1:0.30,5M:2:0.50"`（3 iter）：

```text
[ramp] band 0: decisions>=0 seats=1 p=0.3
[ramp] band 1: decisions>=5000000 seats=2 p=0.5
[iter 0] ... hb=1s/p0.30/auto/b0
[iter 1] ... hb=1s/p0.30/auto/b0
[iter 2] ... hb=1s/p0.30/auto/b0
```

3 iter 只累计 ≈ 4 万 decisions（s15 尺度 ≈ 2.8 万 decisions/iter → 5M 边界约在
**第 180 个 iteration**），所以 20–30 iter 的短跑看不到切档。为了在短跑里看到切换，
**B** 用同一代码路径、把控制点按实测吞吐等比压缩（`0:1:0.30,60K:2:0.50,180K:3:0.70`
+ 分位 `0:p50,120K:p75`），26 iter / 152 s：

| iter | 累计 decisions | seats | p | sample | band | 注入 attempt / applied |
|---|---|---|---|---|---|---|
| 0–4 | 0 – 73K | 1 | 0.30 | p50 | 0 | 212 / 131（iter0） |
| 5–8 | 87K – 126K | 2 | 0.50 | p50 | 1 | 681 / 441（iter5） |
| 9–13 | 139K – 190K | 2 | 0.50 | **p75** | 1 | 662 / 425（iter9） |
| 14–25 | 203K – 252K | 3 | 0.70 | p75 | 2 | 1409 / 913（iter14） |

结论：**① seats/p/sample 按预期随累计 decisions 变化**（`history.jsonl` 的
`human_board` 段、`collect.human_board_*`、`summary.json.board_ramp` 三处一致），
训练无硬错（0 crash / 0 illegal / 0 truncated）。

> 同一段 history 还暴露了一个**真实动力学**：档位越高、局越短 → 每 iteration 的
> decisions 越少（13.9K → ~12.3K），所以「按 decisions 计时」的课程在后期会相对变慢。
> 这正是按 decisions 而不是按 iteration 计时的理由。
>
> 这段短跑用的是 s15 checkpoint + **默认 PPO 超参**（`lr=1e-4`、minibatch 128），
> 每个 epoch 都触发 KL 早停、熵塌到 0.0003，后期决策数掉到 ~1K/iter —— 说明
> **它只能当接线 smoke，不是可用的训练配方**；正式 s16 必须沿用 s15 的超参（见 §6）。
> 同分布对照（`--games 48`，1 席 p0.30）验证了这一点：这个短跑 checkpoint
> `mean_rank=8.0 / top4=0.00 / death_turn_p50=7`，而 s15 checkpoint 在同样的
> 1 席 p0.30 下是 `2.27 / 0.94 / 14` —— 落差来自 PPO 超参，不是对手强度。

**C. 自适应门控**（`--ramp-adaptive 1 --ramp-window 3`，12 iter，spec
`0:1:0.30,40K:2:0.50,100K:3:0.70`，`--ramp-delay-decisions 200K` 便于观察）：

```text
it 0 seats=1 band=0 gate surv=0.958 t4=1.00 forced/g=2.9  ev=[]
it 2 seats=1 band=0 gate surv=0.333 t4=1.00 forced/g=7.0  ev=['early']   -> band0->1
it 3 seats=2 band=1 gate surv=0.250 t4=1.00 forced/g=6.6  ev=[]
it 5 seats=2 band=1 gate surv=0.000 t4=0.63 forced/g=6.5  ev=['delay']  -> +200K
it 6..11 seats=2 band=1 delay=200000（不再升档，停在 band1 学）
```

即：**窗口达标 → 提前升档；新档位打不过 → 推迟下一档并停在这里**；`ramp_gate`
段把 `survive_t12 / tier_ge4 / source / forced_per_game / events` 全部落盘。

### 4.2 1 席 vs 2 席：对手强度确实决定「能否活到后期」

用**同一个** s15 checkpoint（避免短跑训练漂移混淆），`quality_monitor.py --games 48`，
同 seed（`--seed-base 520000`），只改席数/概率/分位：

| 配置 | mean_rank | top4 | win | death_turn_p50 | 活到 t12 | tier≥4 局占比 | tier≥4 回合占比 | max_tier_p50 | tier 回合分布（t1..t6） |
|---|---|---|---|---|---|---|---|---|---|
| **1 席 p0.30 p50**（band0） | **2.27** | 0.94 | 0.229 | 14 | **0.938** | **0.458** | **0.153** | 3 | 302/154/182/103/11/1 |
| 2 席 p0.50 p50（band1） | 3.44 | 0.77 | 0.063 | 13 | 0.771 | 0.312 | 0.075 | 3 | 291/169/147/41/8 |
| 3 席 p0.70 p75（band2） | 4.60 | 0.48 | 0.000 | 11 | 0.479 | 0.271 | 0.060 | 3 | 294/167/105/36 |
| **5 席 p0.90 auto**（= s15 训练分布） | 5.77 | 0.23 | 0.000 | 10 | **0.104** | 0.271 | 0.041 | 3 | 294/143/82/20/2 |

（上表由 `scripts/quality_monitor.py` 新增的 `survive_t12_ratio` /
`tier_ge4_ratio` / `tier_ge4_turn_ratio` / `tier_turn_hist` 直接产出；
「活到 t12」= **learner 还活着的回合** ≥ 12，分母 48 局，seed 相同。）

> 交叉验证：s15 训练分布这一档（5 席 p0.90 auto）测出的 `tier≥4 回合占比 = 4.1%`，
> 与 s15 自己的 200 局面板 `102/2113 = 4.8%` 一致（差额来自 s15 还叠了镜像 2 席），
> 说明这个口径与历史证据可比。

**结论（②）**：随档位上升，`活到 t12` **0.938 → 0.771 → 0.479 → 0.104**、
`tier≥4 回合占比` **0.153 → 0.075 → 0.060 → 0.041**、`mean_rank` 2.27 → 5.77、
`win` 0.229 → 0.000 —— **单调**，且 1 席 p0.30 相对 s15 分布把「活到 t12」提高
**9 倍**、tier≥4 回合占比提高 **3.7 倍**。这就是课程第一阶段要的起手点。

> 同时要看清代理的局限与第二个瓶颈：**四档的 `max_tier_p50` 全是 3**。
> 即使 1 席 p0.30 下 94% 的局活到 t12、中位存活 14.5 回合，learner 的**中位最高 tier
> 仍然只有 3**（tier≥4 只占 15% 回合）。也就是说「tier 上不去」不只是对手强度问题，
> 还有**升级决策本身**的问题（教师在第 7 回合就 tier4–5）；因此第一阶段必须同时上
> `--tier-target-coef`（或升级 DPO），单靠 ramp 到不了缩放窗口。

---

## 5. 与 s15 的差异

| 维度 | s15 | 开课程后 |
|---|---|---|
| 人类战团席数 | 固定 5 | 按档位 `1→2→3→5`（可配） |
| 注入概率 | 固定 0.9 | 按档位 `0.30→0.50→0.70→0.90` |
| 桶内分位 | `auto`（按 turn 走 p50/p75/p90） | 可独立爬坡（默认不爬：沿用 CLI 值） |
| 镜像快照 | 2 席 × p0.2（p75） | **建议第一阶段先关或固定 p≤0.1**（ramp 不覆盖 mirror），等 human-board 到 band3 再开 |
| 换位守卫 | 开 | 不变（与本课程正交） |
| 调度时钟 | 无 | 累计 learner decisions |

**不要**把 s15 的 `5 席 × 0.9` 直接当 band0：那会让课程从「模型完全学不到后期」的
分布起步。band0 必须明显弱于 s15。

---

## 6. 推荐的第一阶段 ramp 表（s16 phase 1）

按「先活到 t12，再谈强度」排序：**先加席数、后加概率**（席数决定「每回合被几个人压」，
概率决定「同一档位的强度密度」），分位最后加（`auto` 的 p90 在 t13+ 才生效，前期影响小）。

```bash
--human-board-ramp "0:1:0.30,10M:2:0.40,20M:2:0.60,30M:3:0.70,45M:5:0.90" \
--human-board-quantile-ramp "0:p50,15M:p75,30M:p90" \
--ramp-mode step --ramp-adaptive 1 --ramp-window 5 \
--ramp-survive-threshold 0.25 --ramp-tier4-threshold 0.30 \
--ramp-delay-decisions 2M \
--human-boards data/real_library/library_real_quasi_full.jsonl \
--human-board-fidelity full --human-board-fast-inject 1 --human-board-set-tier 1
```

- 界值依据：s15 尺度 ≈ 2.8 万 decisions/iter（192 局），10M ≈ 360 iter；gate 要求
  「活到 t12 ≥ 25% 且 tier≥4 ≥ 30%」才升档，不达标每年后移 2M。
- 若 gate 一直不达标，说明 band0 仍然太强：先降到 `0:1:0.15` 或 `--ramp-mode linear`。
- **tier 门槛建议接真实观测**：轨迹代理的 `tier_ge4` 会高估（§4.2 的 `max_tier_p50=3`
  也会被算成 1.0）。每 ~10M decisions 跑一次 `quality_monitor.py`（48 局、约 1 分钟），
  把输出 JSON 挂到 `--ramp-quality-json`，门控就按真实 tier≥4 判。
- 与**镜像快照**组合时：`--mirror-seats 2 --mirror-p 0.1`（human-board 到 band2 后再开到 0.2）。
- 经验法则：**band0 的目标是 tier≥4 回合占比 ≥ 15%、活到 t12 ≥ 80%**（§4.2 中
  1 席 p0.30 实测 15.3% / 93.8%，刚好达标），若 band0 达不到，先减对手而不是加训练量。

---

### 6.1 s16 phase 1 完整 CLI（= s15 的命令 + 下面这些改动）

s15 的实际命令可从 `runs/az_entity_s15/history.jsonl` 的 header 还原（`games 192 /
processes 16 / gpus 3,4,5 / device cuda:6 / pipeline 1 / lockstep 1 / sims 0 /
lr 1.2e-6 / epochs 1 / minibatch 1024 / grad_accum 8 / clip 0.2 / target_kl 0.02 /
lam 0.995 / seq_coef 0.05 / bc_coef 0.004 / dpo_coef 0.02 / move_guard 1 /
archetype_bias_coef 0.5 / mirror_snaps runs/library/snaps_champ / mirror_seats 2 /
mirror_p 0.2 p75 seat_random 1 / human_board 5×0.9 auto full fast_inject 1 /
eval_every_decisions 10M async cuda:7 panel human / stop_at_decisions 60M`）。

s16 只改这几处（其余保持 s15 一致，保证「只动对手强度这一个变量」）。
*① 课程与起点*、*② 镜像先弱化*、*③ tier 瓶颈同开* 是新增块，*④ 其余* 照抄 s15：

```bash
cd /home/data/users/gaoletian/projects/HSBRSIM
PYTHONPATH=rust/python:. python scripts/train_entity_sync.py \
  --checkpoint runs/az_entity_s15/model.pt --out runs/az_entity_s16 --seed 21600 \
  --human-boards data/real_library/library_real_quasi_full.jsonl \
  --human-board-fidelity full --human-board-fast-inject 1 --human-board-set-tier 1 \
  --human-board-ramp "0:1:0.30,10M:2:0.40,20M:2:0.60,30M:3:0.70,45M:5:0.90" \
  --human-board-quantile-ramp "0:p50,15M:p75,30M:p90" \
  --ramp-mode step --ramp-adaptive 1 --ramp-window 5 \
  --ramp-survive-threshold 0.25 --ramp-tier4-threshold 0.30 \
  --ramp-delay-decisions 2M --ramp-start-decisions 0 \
  --mirror-snaps runs/library/snaps_champ --mirror-seats 2 --mirror-p 0.1 \
  --mirror-sample p75 --mirror-seat-random 1 \
  --tier-target-coef 1.0 --tier-target-table 7:4,9:5,12:6 \
  --arch entity --device cuda:6 --processes 16 --gpus 3,4,5 --threads 8 \
  --games 192 --lockstep 1 --sims 0 --pipeline 1 --fast-act 1 \
  --epochs 1 --minibatch 1024 --grad-accum 8 --lr 1.2e-6 --lr-min-ratio 0.5 \
  --clip 0.2 --target-kl 0.02 --lam 0.995 --max-grad-norm 1.0 --entropy-coef 0.001 \
  --amp bf16 --compile-train 1 --anchor-beta 0.1 --anchor-iterations 200 \
  --anchor-beta-tail 0.02 --pi-coef 0 \
  --seq-coef 0.05 --bc-coef 0.004 --bc-batch 128 --bc-every 4 --bc-compile 1 \
  --dpo-coef 0.02 --dpo-beta 0.1 --dpo-batch 128 --dpo-every 1 \
  --move-guard 1 --move-cap 3 --move-repeat-limit 2 --archetype-bias-coef 0.5 \
  --eval-every-decisions 10000000 --eval-async 1 --eval-device cuda:7 \
  --eval-panel human --eval-games 256 \
  --stop-at-decisions 60000000 --iterations 8000 --minutes 1200
```

phase 2（band≥3 之后另起一段，`--trainer-state` 续训 + `--ramp-start-decisions`
接上累计值）：把 `--teacher-bc-coef` 打开（教师的标签窗口这时才有量）、`--mirror-p`
恢复 0.2、ramp 表继续往后接。

## 7. 与其他课程/辅助目标的组合

全部是**正交**开关（各写各的 `CollectConfig` 字段 / `history` 段），可以同时开：

| 组合 | 建议 | 理由 |
|---|---|---|
| 载体教师 `--teacher-bc-coef` | 等 band≥2（tier4 回合占比 > 10%）再开 | 教师的标签窗口是「gold≥10 且 tier≥4」；前期没有窗口 → 空标签 |
| 过程价值 `--process-value-coef` | 可从 band0 起开 | 目标来自状态日志（永久 buff/施法/consume），不依赖后期 |
| `--tier-target-coef`（等级进度奖励） | 全程开，系数 0.5–1.0 | 和 ramp 同一目标方向（把 tier 拉上去），曲线 `7:4,9:5,12:6` 与门控代理同源 |
| 奖励塑形 `--shaping-coef` | band0 可关，band2 起开 | 塑形势函数用 Σ(atk+hp)+tier，早期战团规模小、信号弱 |
| 经济课程 `--curriculum-stage/--gold-curriculum` | 独立 | 按同一 `cum_decisions` 的倍率（`gold_mult_at`），不冲突 |
| `seq_coef_ramp` / `bc_coef_ramp` | 独立 | 都按 `cum_decisions` 求值，可对齐同一时间轴 |
| 换位守卫 `--move-guard 1` | 保持 | 与对手强度正交；部署路径同样生效 |

---

## 8. 可观测性

`history.jsonl` 每行新增（默认也写，值 = CLI 值）：

```json
"human_board": {"seats": 2, "p": 0.5, "sample": "p75", "band": 1, "bands": 3,
                "mode": "step", "decisions": 252173, "adaptive": true,
                "early_advances": 0, "delay_decisions": 0, "start_decisions": 0,
                "ramp": "0:1:0.30,60K:2:0.50,180K:3:0.70",
                "quantile_ramp": "0:p50,120K:p75", "events": []},
"human_board_seats": 2, "human_board_p": 0.5, "human_board_sample": "p75",
"ramp_gate": {"survive_t12": 0.62, "tier_ge4": 0.41, "source": "batch",
              "max_turn_p50": 13.0, "forced_end_turns": 300, "forced_per_game": 6.2,
              "events": [], "window": {"iters": 5, "survive_t12_mean": 0.62,
              "tier_ge4_mean": 0.41}}
```

- `summary.json.board_ramp`：配置摘要（`points` / `quantile_points` / 门控阈值）+
  收尾 `final` 状态 + 全部 `events`；
- 采集侧同源计数：`collect.human_board_attempt / applied / rejected / ...`（证明注入真的发生）；
- 每 iter 控制台行尾 `hb=<seats>s/p<p>/<sample>/b<band>`。

`scripts/quality_monitor.py` 新增（默认关闭，`--human-board-p 0` 时行为与旧版一致）：

```bash
PYTHONPATH=rust/python:. python scripts/quality_monitor.py \
  --checkpoint runs/az_entity_s16/model.pt --device cuda:7 --games 48 \
  --human-boards data/real_library/library_real_quasi_full.jsonl \
  --human-board-seats 2 --human-board-p 0.50 --human-board-sample p50 \
  --human-board-fidelity full --human-board-fast-inject 1 \
  --out runs/quality/s16_band1.json
```

输出新增 `survive_t12_ratio` / `tier_ge4_ratio`（局级，门控用它）/
`tier_ge4_turn_ratio`（回合级，对齐 s15 证据口径）/ `max_tier_p50` /
`max_turn_p50` / `tier_turn_hist` / `human_board`（注入计数）。该 JSON 可直接喂
`--ramp-quality-json`，让门控用真实 tier 观测而不是 turn 代理。

---

## 9. 回退

- **默认（不传任何新开关）完全关闭**：`BoardRampController("")` 是恒等映射，
  `CollectConfig` 里仍是 `--human-board-seats/--human-board-p/--human-board-sample`
  的原值；`history` 只多出 `human_board` / `human_board_*` 三个平铺键（值不变）。
  已用「改前（git HEAD worktree）vs 改后」同 seed 2 iteration 对比验证：
  **model.pt 参数 sha 完全一致**（`history` 除新增键外只有耗时字段不同）。
- **只开一半**：只传 `--human-board-ramp` 不传分位课程 → 分位保持 CLI 值；
  `--ramp-mode linear` 可把切换平滑成过渡而不是台阶。
- **训练中途停掉课程**：`--ramp-adaptive 0` 且 `--human-board-ramp ""` 重跑
  （或直接用 `--trainer-state` 从上一次快照续训，见下）。
- **续训（`--trainer-state`）**：`cum_decisions` 从 0 重新计，所以必须补
  `--ramp-start-decisions <上次累计 decisions>`，否则课程会从 band0 重来。
  正确的续训组合：

  ```bash
  --trainer-state runs/az_entity_s16/snapshots/step_000400/trainer.pt \
  --human-board-ramp "..." --ramp-start-decisions 11500000
  ```

- **quality_monitor 侧**：`--human-board-p 0`（默认）即旧面板；`survive_t12_ratio`
  等指标仍会计算（纯观测，不影响对局）。
