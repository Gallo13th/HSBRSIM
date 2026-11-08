# Firestone 近期库混池 A/B（s13 → s14 决策依据）

> 任务：把近期 Firestone 战团库与现有 10k+ 库**混池**，并从 s13 当前 checkpoint 起做一次
> 40 iter 的 A/B，判定「加入近期 Firestone 战团」是否改善 human 面板。
>
> 结论（TL;DR）：**不改**。混池本身已落地且可复现（3,922 行 / 80% 准完整），但在
> 0.5/0.3/0.2 配方 + 40 iter（≈1.1M learner decisions）的预算下，human 面板
> 配对 Δ(B−A) = **+0.06 ~ +0.07**（B 略差），512 局面板的 95% CI **排除**了
> 「B 比 A 好 ≥0.10」；t12/t15 强度比**没有上升**（t15 −0.005）。
> 因此**不把 `library_mixed.jsonl` 作为 s14 的默认库**；建议 s14 继续用
> `library_real_quasi_full.jsonl` 作默认，Firestone 只在「高回合上限补充」的
> 小权重配方下另开一次预算足够的 A/B（见 §6）。
>
> 附带交付：`scripts/mix_human_libraries.py`（+21 项单测）、
> `human_board_pool._row_to_payload` 的 `gold/hero_hp/main_placement` 透传（+5 项单测）、
> `scripts/archetype_probe.py`（流派分类器可行性探针，实测 11 类种族 top1 **85.7%**、
> 16 类流派 top1 **66.4%** / top3 **91.5%**）。

---

## 0. 一页数字

| 项 | 结果 |
|---|---|
| 混池输出 | `data/real_library/library_mixed.jsonl`，**3,922 行**（quasi 1,961 + firestone 1,177 + degraded 784） |
| 去重 | 严格签名重复 **0**；「准完整 vs board-only 同帧」低信息重复 **1,898**（全部来自 degraded） |
| payload 覆盖 | **3,138 / 3,922 = 80.0%**（过 `HumanBoardPool` 后 `payload_kept` 3,134；5 行被过滤，其中 4 行是离群帧） |
| 混合强度 p50（t5/t10/t15） | **45 / 1,095 / 22,739**（quasi 48/1,132/26,194；firestone 40/731/21,497；degraded 48/1,145/29,729*） |
| 训练预算 / 臂 | 40 iter × 192 局，8 进程，**~1.1M learner decisions**，A 412 s / B 408 s（cuda:7 串行） |
| human 面板 144（主口径） | A 6.2917 / B 6.3542；配对 **Δ=+0.0625**，95% CI **[−0.132, +0.236]**，SE 0.095，n=144 |
| human 面板 512（补充，smoke 单面板） | A 6.3496 / B 6.4180；配对 **Δ=+0.0684**，95% CI **[−0.031, +0.172]**，SE 0.052，n=512 |
| bot 面板 128（c0 gate） | A 1.8594 / B 1.9297；配对 **Δ=+0.0703**，95% CI **[−0.133, +0.281]**，n=128 |
| quality 面板 64 | A 1.7969 / B 1.6406；配对 Δ=**−0.156**，CI [−0.391, +0.078]（B 略好，不显著） |
| t12 / t15 强度比 | A 0.1381 / 0.0363 → B 0.1375 / 0.0312（**t12 −0.0006，t15 −0.0051**） |
| 判定 | human Δ 与 CI、bot 非劣 CI、t12、t15 四项判据**全部不满足**（§5） |
| 起点 | `runs/ab_firestone_mix/start_model.pt`，sha256 `c9438767…cc160`（s13 当前 `model.pt` —— `latest.json` version 2301 —— 的冻结副本） |

\* degraded 的官方 stats JSON 用线性插值，t15 p50=29,729；本节其余数字统一用最近秩
（与 `human_board_pool` 采样同一公式），故 degraded 列显示 32,620。

---

## 1. 混池：`scripts/mix_human_libraries.py`

### 1.1 口径

| 决策 | 取值 | 理由 |
|---|---|---|
| 去重键 | `(game_id, turn, frame_signature)` | `docs/FIRESTONE_REPLAY_INGEST.md §7.1`。签名 = `turn + board(card/atk/hp 排序) + hand(card) + tier + perspective + board_detail(golden,kw)` 的 sha1 前 16 位 |
| 去重优先级 | 源顺序（默认准完整库在前） | 跨库同帧保留信息更全的那条 |
| 二级去重 | 「同粗键（game/turn/视角/战团/手牌）+ 一边有 `board_detail`」→ 只留全的 | 避免同一观测帧以「准完整 + board-only」两份进入混池（本次命中 **1,898** 条，全部是 quasi_full 与 degraded 的同帧孪生） |
| 权重语义 | **输出行数占比**（`proportional`） | 任务要求「Firestone 只作补充、不能替换」：权重直接限制其份额 |
| 规模 | `N = floor(min_i n_i / w_i)`，不超采样 | 默认 `N = 3,922`（quasi 1,961 全取、firestone 1,177、degraded 784）；`--max-rows` 可再剪 |
| 抽样 | 每源内**按 turn 分层**、桶内不放回、固定 seed | 保留各源自身的 turn 曲线，不让 Firestone 的 t3–t13 长尾把分布带偏；同 seed 逐字节幂等 |
| 备选 | `--sizing keep-all` | 只去重、保留全部行（15,158 行，但 Firestone 占 71%，强度曲线被拉低）——**不推荐**做训练默认 |

```bash
# 默认配方
python scripts/mix_human_libraries.py --name s14_default
# 自定义
python scripts/mix_human_libraries.py \
    --source high=data/real_library/library_real_quasi_full.jsonl:0.7 \
    --source fs=data/real_library/library_firestone_recent.jsonl:0.2 \
    --source low=data/real_library/library_real_degraded.jsonl:0.1
```

### 1.2 产物统计（`data/real_library/library_mixed_stats.json`）

| 源 | 权重 | 输入行 | 严格去重 | 低信息去重 | 可用 | 配额 | 输出 | 其中带 payload |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| quasi_full | 0.50 | 1,961 | 0 | 0 | 1,961 | 1,961 | **1,961** | 1,961 (100%) |
| firestone_recent | 0.30 | 10,811 | 0 | 0 | 10,811 | 1,177 | **1,177** | 1,177 (100%) |
| degraded | 0.20 | 4,284 | 0 | 1,898 | 2,386 | 784 | **784** | 0 |
| 合计 | 1.00 | 17,056 | **0** | **1,898** | 15,158 | 3,922 | **3,922** | 3,138 (80.0%) |

- 坏行 0；turn 覆盖 1–18（`t1 89, t2 153, t3 287, t4 345, t5 353, t6 355, t7 352,
  t8 348, t9 348, t10 339, t11 309, t12 253, t13 203, t14 115, t15 51, t16 17, t17 4, t18 1`）。
- 用真实 `HumanBoardPool` 复读：`rows=3922 kept=3917 payload_kept=3134`，
  过滤 `stat_outlier=4, empty_board=1`（与训练里 `human_board_payload_rows=3134` 完全一致）。
- **幂等**：同一输入 + seed 连跑两次，JSONL sha256 相同（`5ec49e2f…`），
  统计 JSON 除 `generated_at/elapsed_s/out` 外逐字段相同。
- 单测 `tests/test_mix_human_libraries.py`：21 项（去重/优先级/隐藏位/golden 差异/
  权重配额/占比/keep-all/max-rows/零权重/空输入/坏行/幂等/turn 分层/CLI）。

### 1.3 强度对比（p50，最近秩）

| turn | mixed | quasi_full | firestone_recent | degraded |
|---:|---:|---:|---:|---:|
| 5 | 45 | 48 | 40 | 48 |
| 8 | 244 | 266 | 163 | 261 |
| 10 | 1,095 | 1,132 | 731 | 1,145 |
| 12 | 4,160 | 4,458 | 3,270 | 4,858 |
| 13 | 7,934 | 9,446 | 6,432 | 10,176 |
| 15 | 22,739 | 26,194 | 21,497 | 32,620 |
| 16 | 23,270 | 19,296 | 20,753 | 34,019 |

读法：混池把 Firestone 的份额限制在 30%，所以 t5–t15 的 p50 只比纯 quasi 低 3–13%
（t15 −13%），比纯 Firestone 高 6–13%。**混池没有「替换」10k+ 校准，但也确实把
t13–t15 的强度分位往下拉了一档** —— 这正是 §5 里 t12/t15 强度比未升的原因。

**稀释集中在哪几个回合**（低端 p50 与高端 p90 各看一遍）：

| turn | mixed p50 | quasi p50 | 比 | mixed p90 | quasi p90 | 比 |
|---:|---:|---:|---:|---:|---:|---:|
| 5 | 45 | 48 | 0.94 | 71 | 73 | 0.97 |
| 10 | 1,095 | 1,132 | 0.97 | 2,949 | 2,948 | 1.00 |
| 12 | 4,160 | 4,458 | 0.93 | 15,685 | 13,288 | **1.18** |
| 13 | 7,934 | 9,446 | 0.84 | 27,700 | 31,142 | 0.89 |
| 14 | 12,598 | 20,889 | **0.60** | 61,670 | 74,435 | 0.83 |
| 15 | 22,739 | 26,194 | 0.87 | 62,167 | 64,318 | 0.97 |

也就是：t≤10 几乎没被影响，**t14 的 p50 直接腰斩（−40%）**，t13/t14 的 p90 也掉了
11–17%。Firestone 在 t13–t15 的样本量远大于 quasi（t14：511 vs 41 行），按 30% 配额
混进去后把这几档的分布整体拉低——而 human 面板恰好在这几档最敏感（`auto` 曲线 t≥13 取 p90）。
**「只补上限」用 turn 过滤解决不了这个问题**（Firestone 的 t15 p90 也低于 quasi 的 t15 p90：
83,993 vs 64,318 是反例，但 t14 p90 49,130 vs 74,435 是正例；按回合切只在 t12 有效）。
要补上限，必须按**强度分位**（而不是按回合）从 Firestone 取帧。

---

## 2. payload 增强：`gold / hero_hp / main_placement`

`hsbg/az/train/human_board_pool.py::_row_to_payload` 现在把这三个字段透传：

```python
"gold": _opt_int(row.get("gold")),            # 10k+ 准完整库没有 -> None（与旧的 "gold": None 逐位一致）
"hero_hp": _opt_int(row.get("hero_hp")),
"main_placement": _opt_int(row.get("main_placement")),
```

- **默认逐位不变**：`library_real_quasi_full.jsonl`（A 臂）不含这三个字段 → payload 里全是
  `None`，`human_obs_full.inject_quasi_state` 只在 `gold is not None` 时写回，
  所以 A 臂的注入行为与改动前完全一致（训练日志：A 的 `human_board_unavailable_fields.gold=7460`
  即 100% 不可得）。
- **有字段才生效**：Firestone self 帧覆盖 `gold 56.6% / hero_hp 100% / main_placement 100%`
  → B 臂 6,326 次 full 注入里有 **589 个座位真的写入了观测金币**。
- 单测：`tests/test_human_board_pool.py` 新增 5 项（透传、缺字段为 None、非法值退化、
  真实 quasi 库全 None 回归锚点、真实 Firestone 库带 gold）；`tests/test_full_state_injection.py`
  新增 2 项（full 档写 gold、`gold=None` 不覆写现场金币）。

---

## 3. A/B 协议

| 项 | A（对照） | B（混池） |
|---|---|---|
| 起点 | `runs/ab_firestone_mix/start_model.pt`（s13 `model.pt` 冻结副本，sha256 `c9438767…`） | 同左 |
| 人类战团库 | `data/real_library/library_real_quasi_full.jsonl`（1,961 行） | `data/real_library/library_mixed.jsonl`（3,922 行） |
| 其余超参 | 与 s13 一致：`rank-only value`、`move-guard 1`（cap 3 / repeat 2）、DPO 0.02 every1 β0.1、BC 0.004 every4、seq 0.05、lr 1.2e-6、mirror 2 席 p0.2 p75、human 5 席 p0.9 auto、`--human-board-fidelity full`、`--human-board-set-tier 1`、`--eval-every-decisions 0`、`--iterations 40`、`--processes 8 --gpus 7 --device cuda:7`、`--seed 19100` | 同左（唯一变量 = `--human-boards`） |
| 训练耗时 | 412 s（40 iter，160 updates，1,109,975 learner decisions） | 408 s（40 iter，160 updates，1,149,765 learner decisions） |
| 产物 | `runs/ab_firestone_mix/A/{model.pt,history.jsonl,summary.json}`，sha256 `4d415198…` | `runs/ab_firestone_mix/B/{…}`，sha256 `c69784cd…` |

- **没有 kill 任何进程**：s13 主训练（cuda:6 trainer + 3,4,5 actor）全程未受影响；
  本 A/B 只用当时空闲的 **cuda:7**，两臂**串行**（避免互相抢算力，也避免 OOM）。
  s13 自己的异步评测在 cuda:7 上与我们的评测/训练有过短时重叠，只影响 wall time。
- 评测工具与训练解耦（固定量具，A/B 完全相同）：
  ```bash
  python scripts/human_panel_eval.py --checkpoint <arm>/model.pt --arch entity --device cuda:7 \
      --games 144 --smoke --quantile auto --bootstrap 2000 --out eval_<arm>/human_panel_144.json
  python scripts/c0_gate.py --checkpoint <arm>/model.pt --arch entity --device cuda:7 \
      --games 128 --smoke --bootstrap 2000 --out eval_<arm>/c0_gate_128.json
  python scripts/quality_monitor.py --checkpoint <arm>/model.pt --arch entity --device cuda:7 \
      --games 64 --out eval_<arm>/quality_64.json
  # 补充（本次额外跑，用于收紧 CI）：--games 512 --smoke 的 human 面板
  ```
- 注入计数（最后一 iter 的 collect meta）：

| 指标 | A | B |
|---|---:|---:|
| attempt | 11,899 | 11,941 |
| applied（full 档成功） | 7,460 (62.7%) | 7,417 (62.1%) |
| rejected（主要 `pending_choice`：t6/t9 饰品/任务选择回合） | 4,439 | 4,524 |
| missing（该回合无数据） | 0 | 0 |
| **payload_missing**（无 `board_detail` → 退化 board-only） | **0** | **1,721 (14.4%)** |
| hand_applied | 7,460 | 5,600 |
| hand_unavailable（对手视角帧） | 0 | 726 |
| counters_applied | 7,460 | 6,326 |
| **gold 真正写入** | 0 | **589** |
| skipped_by_mirror | 473 | 492 |

> B 的 `payload_missing=1,721` 全部来自混池里 784 行 degraded 帧（20% 配额，无 detail）；
> 它们按 board-only 注入，因此 B 的「full 档暴露」实际只有 ~80%。

---

## 4. 结果

### 4.1 human 面板（主指标，`--quantile auto`，对手 = 10k+ 分位战团）

| 口径 | A | B | 配对 Δ(B−A) | 95% CI | SE | n | B 更好/更差/平 |
|---|---:|---:|---:|---|---:|---:|---|
| **144 局（任务口径）** | 6.2917 | 6.3542 | **+0.0625** | [−0.132, +0.236] | 0.095 | 144 | 34 / 42 / 68 |
| 512 局（补充） | 6.3496 | 6.4180 | **+0.0684** | **[−0.031, +0.172]** | 0.052 | 512 | 110 / 141 / 261 |
| 两面板逆方差合并 | — | — | +0.0669 | [−0.023, +0.157] | 0.046 | 656 | — |

- top4 的配对翻转（512 局）：A 独占 top4 34 局 / B 独占 25 局 —— 与 mean rank 的方向一致。
- 两臂对 bot 基线的配对差（面板内，可作为「量具是否正常」的对照）：
  A −1.4167 [−1.611, −1.215]（144）/ −1.4473 [−1.566, −1.334]（512）；
  B −1.3542 [−1.549, −1.160]（144）/ −1.3789 [−1.496, −1.262]（512）。
  即：在同一批人类战团下，两臂都**显著强于 bot**（这是面板有效性检查），但**彼此没有显著差异**（B 的点估计略差 +0.07）。
- 512 局的 CI 下界 −0.031 **高于 −0.10**：在 95% 置信下可以**排除**「混池让 human 面板改善 ≥0.10」。
  （配对差 SD ≈ 1.19；若真效应是 −0.10，n≈250 就足够让 CI 上界 < +0.05 —— 也就是说
  本 A/B 的样本量不是「测不出」的主因，**真实效应不在 −0.10 附近**。）

### 4.2 bot 面板（c0 gate 128 局，回归基线）

| 口径 | A | B | 配对 Δ(B−A) | 95% CI | n |
|---|---:|---:|---:|---|---:|
| c0 gate 128（mean rank） | 1.8594 | 1.9297 | **+0.0703** | [−0.133, +0.281] | 128 |
| c0 gate 128（win rate） | 46.1% | 37.5% | −8.6 pp | — | 128 |
| c0 gate 128（top4） | 96.875% | 96.875% | 0 | — | 128 |

- 非劣判据（mean rank ≤ +0.10）：**点估计通过（+0.070），CI 上界不通过（+0.281）**。
- 胜场配对：A 独赢 29 局 / B 独赢 18 局（A 共 59 胜、B 48 胜）；top4 各自独占 3 局。
  也就是说 B 在 bot 面板上不仅名次略差，**夺冠率也低 8.6 个百分点**（n=128，属噪声量级，
  但方向与 human 面板一致）。
- illegal/truncated 均 0。

### 4.3 quality 面板（64 局，vs bot，无人类战团）

| 指标 | A | B | Δ(B−A) |
|---|---:|---:|---:|
| mean_rank（配对） | 1.7969 | 1.6406 | **−0.156**（CI [−0.391, +0.078]，n=64） |
| top4 | 100% | 100% | 0 |
| win | 39.06% | 43.75% | +4.7 pp |
| death_strength_p50 | 873 | 763.5 | −109.5 |
| strength_ratio t9 | 0.3916 | 0.4300 | **+0.0384** |
| strength_ratio t12 | 0.1381 | 0.1375 | **−0.0006** |
| strength_ratio t15 | 0.0363 | 0.0312 | **−0.0051** |
| tier_p50 t9/t12/t15 | 4/4/4 | 4/4/4 | 0 |
| tier≥5 占比 t12 / t15 | 17.2% / 39.5% | 21.9% / 46.0% | +4.7 / +6.5 pp |

读法：B 在**纯 bot 面板**上名次更好一点、tier≥5 的板子更多，但**战团 p50 强度在 t15 反而更低**
（−135），t12 持平。也就是说混池让模型「更早上 tier 5」，但没有把 t12/t15 的战团规模做上去 ——
与混池自身的 t13–t15 强度分位下移（§1.3）一致。

### 4.4 起点对照（模型是不是被「训动了」）

| 对比 | human 144 | human 512 |
|---|---:|---:|
| start（未训练） | 6.3125 | 6.4746 |
| A − start | −0.0208 [−0.194, +0.160] | **−0.125 [−0.233, −0.022]** |
| B − start | +0.0417 [−0.090, +0.181] | −0.0566 [−0.145, +0.029] |

40 iter（≈1.1M decisions）在 512 局口径下让 A 相对起点前进约 0.125 名（显著），B 只有 0.057
（不显著）；两者之差 +0.068。也就是说：**同样的预算，接 quasi_full 的那一臂学到的更多**。

---

## 5. 判据判定

| 判据 | 阈值 | 实测 | 判定 |
|---|---|---|---|
| human 配对 Δ(B−A) | ≤ **−0.10** | **+0.063**（144）/ +0.068（512） | ✗（方向相反） |
| human CI 上界 | < **+0.05** | +0.236（144）/ +0.172（512） | ✗ |
| bot 非劣 | ≤ **+0.10** | +0.070（CI 上界 +0.281） | 点估计 ✓ / CI ✗ |
| t12 强度比 | 上升 | −0.0006 | ✗ |
| t15 强度比 | 上升 | −0.0051 | ✗ |
| （附加）硬约束 | 0 illegal / 0 truncation | 全部 0 | ✓ |
| （附加）B 的 full 档覆盖 | — | 80%（payload_missing 14.4%） | 需知情 |

**总判定：判据不成立。** 证据方向一致（144 / 512 / bot 三个面板都是 B 略差 ~+0.07），
但都没有达到统计显著；可以确定的是**没有出现 ≥0.10 的改善**，而不是「已证明有害」。

---

## 6. 结论：是否把混池作为 s14 的默认库

**不建议。** 具体建议：

1. **s14 默认库保持 `data/real_library/library_real_quasi_full.jsonl`**（s13 的配置），
   即 `--human-boards data/real_library/library_real_quasi_full.jsonl --human-board-fidelity full`。
2. 如果仍想引入 Firestone，**不要用「0.5/0.3/0.2 全回合混」**，并且先想清楚目的：
   - **目的是多样性（战团形状/种族）** → `quasi_full ≥ 0.80`、Firestone `≤ 0.20`，
     并且**只在 Firestone 强度 ≥ quasi 同回合 p75 的帧上混**（按强度筛，不是按回合筛）；
     每次都要核对混池 p50/p90 表，t13–t15 的 p50 跌幅控制在 5% 以内再上训练。
   - **目的是抬高上限** → 不要混进同一个池。保持 quasi_full 为池，另建一个
     「Firestone 每回合 p90+」的补充桶，在 `HumanBoardPool` 里作为**第二个来源**只对
     t≥13 的 p90 档供给（当前 `--human-boards` 只接受一个文件，需要在该模块加「多池」支持，
     或先离线合成一个高分量文件）。本次已经验证：把 Firestone 全量按 30% 配额混进来，
     t14 的 p50 会腰斩，human 面板不会因此变好。
   - 无论哪种配方，都保留 `--human-board-fidelity full` + 本报告的 gold 透传
     （Firestone self 帧的 gold/hero_hp 是纯增量信息，对 quasi 是 no-op）。
   - 工具已支持 `--min-turn/--max-turn`（全局）与 `--source NAME=PATH:WEIGHT@MIN-MAX`
     （单源）两种 turn 过滤，可直接产出「只取 Firestone t≥12」的配方，例如：
     ```bash
     python scripts/mix_human_libraries.py \
         --source high=data/real_library/library_real_quasi_full.jsonl:0.8 \
         --source fs=data/real_library/library_firestone_recent.jsonl:0.2@12- \
         --out /tmp/mix_t12plus.jsonl --stats-out /tmp/mix_t12plus.json
     ```
     **注意**：这条命令只解决「t≤11 被拉低」。实测（`--out /tmp/mix_t12plus.jsonl`，
     2,451 行、payload 100%）：t5–t10 的 p50 与 quasi **完全一致**（ratio 1.000），
     但 t12/t13/t14/t15 的 p50 仍被拉到 0.863 / 0.804 / 0.744 / 0.832，t14 的 p90 只剩 0.729
     （t15 的 p90 反而 +31%）。所以**必须**看 stats 里的 `strength_by_turn_mixed` 再决定，
     不能用「按回合过滤」代替「按强度分位取帧」。
3. **下一次 A/B 的预算至少要够**：本 A/B 每臂 1.1M decisions ≈ s13 一个 10M 评测窗口的 11%，
   两臂都只是「从起点轻微漂移」。建议 ≥10M decisions/臂（8 进程下约 360 iter ≈ 1 h/臂），
   评测用 **512 局 × 2 个封存面板**（`--confirmations 2`，非 smoke），并预注册判据。
   本次 512 局面板（单面板）的 SE 是 0.052，双面板可到 ~0.037，足以判定 −0.10。
4. 混池文件保留为**可选项**（`data/real_library/library_mixed.jsonl` + stats），
   不要删；它已经通过 `HumanBoardPool` 复读与幂等验证，s14 想开消融时可直接用。
5. `payload` 的 `gold/hero_hp/main_placement` 改动**与混池解耦**，建议保留（无论默认库选哪个）；
   唯一注意：B 臂有 14.4% 的帧因 degraded 行退化为 board-only，若要把混池当默认，
   应该把 degraded 权重降到 0 或改成「只取带 `board_detail` 的帧」。

---

## 7. archetype 数据准备建议

### 7.1 现有数据

| 项 | 数值 |
|---|---|
| 动作样本 | `data/firestone_replays/firestone_recent_actions.jsonl.gz`：**149,166 条 / 500 局**（298.3 条/局） |
| 字段 | `game_id, turn, action_type, card_id, target_card_id, board_cards, hand_cards, shop_cards, shop/hand/board_slot, play_pos, gold, tier, health, armor, action_index, placement, build_number, source` |
| 标签 | `data/real_library/library_firestone_recent.jsonl` 的 `archetype`（每局一个）：**27 个流派，427 局有标签，73 局 `null`（14.6%）** |
| 分布 | `beast_lobster 64 / neutral_tea_set 40 / dragon_shield 31 / quilboar_gem_spam 31 / demon_boost_shop 26 / mech_apm 25 / mech_volumizer 23 / elemental_azerite 20 / pirate_discover 19 / aberration_discard 17 / undead_butcher 17 / demon_self_damage 15 / quilboar_choose_one 14 / quilboar_felboar_spam 14 / undead_eternal_knight 11 / murloc_scam 11 / …`，尾部 11 类 ≤9 局（4 类 ≤2 局） |
| 种族（标签第一段） | 11 类：`beast 70 / quilboar 59 / mech 53 / dragon 47 / demon 41 / neutral 40 / undead 35 / pirate 23 / elemental 21 / murloc 20 / aberration 18` |
| 卡表 | `rust/crates/hsbg-engine/data/cards.json` 的 `races`（字符串：BEAST/MECHANICAL/…），`card_id` 与动作里的 `card_id` 直接对齐 |

### 7.2 可行性（实测，`scripts/archetype_probe.py`）

局级特征（135 维）：12 类动作占比 + 6 类动作 × 15 回合节奏 + 11 种族「买/打出手牌」直方图
+ 11 种族「场上战团」直方图 + tier 里程碑（t5/8/10/12/15、max）+ 总量/金币均值。
模型：`StandardScaler + LogisticRegression(class_weight=balanced)`，
**按局** 5 折分层 CV（一局一个样本，无泄漏）。全流程 5.5 s。

| 任务 | 样本 | 类数 | top-1 | top-3 | macro-F1 | majority 基线 |
|---|---:|---:|---:|---:|---:|---:|
| 种族（11 类） | 427 | 11 | **0.857** | **0.972** | 0.857 | 0.164 |
| 流派（只保留 ≥10 局的 16 类） | 378 | 16 | **0.664** | **0.915** | 0.624 | 0.169 |

结论：**可行，但只能做到「种族级硬标签 + 流派级软排序」**。tail 类（≤9 局，11 类）
在 5 折 CV 下每类只有 1–2 个测试样本，学不出来，也不该单独出标签。

复现：

```bash
python scripts/archetype_probe.py --min-games 10 \
    --out runs/ab_firestone_mix/archetype_probe.json
```

### 7.3 最小实现（建议直接按这个落地）

1. **数据准备**（一次性，~30 行）
   - `game_id -> archetype`：从战团库取（去重后 427 局；`null` 保留为 `unlabeled` 池）；
   - `game_id -> 特征`：流式读 149k 动作聚合（`archetype_probe.build_features` 已实现）；
   - 种族标签 = `archetype.split("_")[0]`；
   - 按 `md5(game_id) % 10` 复用一个固定的 train/eval 划分（与战团库的 `split` 字段同规则，
     避免同一局同时进训练和评测）。
2. **两段式模型**（推荐，而不是 28 类硬分）
   - 段 1：11 类种族（top1 0.857，已够用）→ 硬标签 + 概率；
   - 段 2：在段 1 的种族内部做流派 softmax，只对 support ≥10 的 16 类出标签，
     其余合并为 `<tribe>_other`；
   - 阈值/弃答：段 1 最大概率 < 0.5 时不输出流派（只输出种族）。
3. **标签噪声控制**
   - 73 局无标签的样本可做半监督（伪标签 + 置信度阈值），但**不要**混进 CV 的评测集；
   - 用 `battleResultHistory`/`compositionsOverTurn` 可以给「同一局多个候选流派」做软标签
     （future work，需要重新解析 PMS）。
4. **用途（按性价比排序）**
   - **(a) 训练采样分层键**：`human_board_pool` 现在只按 `turn × strength 分位` 采样；
     加一层 `archetype`（或种族）分层，能让 5 个对手席位的战团更「异质」，这是最便宜的用法
     （不需要模型精度很高，种族级 0.857 就够）；
   - **(b) BC 辅助头**：把 `archetype` 作为局级辅助分类目标（与现有 `bc_type/bc_card` 并列），
     让共享 trunk 学到「流派语义」；权重 0.01–0.05，只对有标签的局生效；
   - **(c) 观测/策略输入**：把种族概率作为 11 维附加输入（需改 obs 契约，成本最高）。
5. **评测口径**：必须 **grouped by game**（同一局的动作不能跨折）、报 top-1/top-3/macro-F1
   + 混淆矩阵；对比基线用 majority（0.164）与「只按买牌种族众数」的规则基线。

### 7.4 风险

- **分布偏差**：feed 是 curated perfect games（491/500 名次=1，MMR 中位 6.5k），
  流派分布是「赢的阵容」而非天梯分布；用它训练出来的分类器在 s14 的镜像/bot 局上会偏。
- **样本量**：427 局 / 27 类 → 只支持种族级 + 头部流派；尾部 11 类不要单独上线。
- **标签来源**：`archetype` 来自 feed 的人工/启发式标注，噪声底未知；上线前应先做
  「同一 replay 两个独立解析器标签一致性」检查（本次两批 replayId 不相交，暂无法做）。
- **卡表版本**：动作里的 `card_id` 是 37.0 卡表；跨版本要重新映射（本项目已有
  `card_id -> cid` 的映射表，可复用 `human_obs_full.load_card_meta()`）。

---

## 8. 复现清单

```bash
# 0) 起点冻结
cp runs/az_entity_s13/model.pt runs/ab_firestone_mix/start_model.pt   # sha256 c9438767…

# 1) 混池 + 单测
python scripts/mix_human_libraries.py --name s14_default
python -m pytest tests/test_mix_human_libraries.py -q

# 2) payload 改动单测
python -m pytest tests/test_human_board_pool.py tests/test_full_state_injection.py -q

# 3) 两臂训练（串行，cuda:7，8 进程；脚本内含全部超参）
bash runs/ab_firestone_mix/run_arm.sh A data/real_library/library_real_quasi_full.jsonl
bash runs/ab_firestone_mix/run_arm.sh B data/real_library/library_mixed.jsonl

# 4) 评测（human 144 / c0 128 / quality 64；脚本会打印汇总）
bash runs/ab_firestone_mix/run_eval.sh A
bash runs/ab_firestone_mix/run_eval.sh B

# 5) 汇总 + 配对 bootstrap（含 512 补充面板与 start 对照）
python runs/ab_firestone_mix/compare.py --baseline start \
    --out runs/ab_firestone_mix/compare.json

# 6) 流派可行性
python scripts/archetype_probe.py --out runs/ab_firestone_mix/archetype_probe.json
```

产物目录 `runs/ab_firestone_mix/`：

| 文件 | 内容 |
|---|---|
| `start_model.pt` / `start/model.pt` | 冻结起点（s13 model.pt） |
| `A/`, `B/` | `model.pt / history.jsonl / summary.json`（40 iter） |
| `A.log`, `B.log` | 两臂完整训练日志 |
| `eval_{A,B,start}/` | `human_panel_144.json`、`human_panel_512.json`、`c0_gate_128.json`、`quality_64.json` |
| `compare.json` | 臂内/臂间配对 Δ、bootstrap CI、quality 对比、注入计数 |
| `archetype_probe.json` | 流派可行性探针结果 |
| `run_arm.sh`, `run_eval.sh`, `compare.py` | 可复现脚本 |

代码改动：

| 文件 | 改动 |
|---|---|
| `scripts/mix_human_libraries.py` | 新增（混池 + 去重 + 分层配额 + 统计 + pool 自检） |
| `tests/test_mix_human_libraries.py` | 新增 21 项单测（去重/权重/空输入/幂等/turn 过滤/CLI） |
| `hsbg/az/train/human_board_pool.py` | `_row_to_payload` 透传 `gold/hero_hp/main_placement`（新增 `_opt_int`） |
| `tests/test_human_board_pool.py` | 新增 5 项 payload 单测 |
| `tests/test_full_state_injection.py` | 新增 2 项 gold 写回单测 |
| `scripts/archetype_probe.py` | 新增（流派分类器可行性探针） |
| `data/real_library/library_mixed.jsonl` + `_stats.json` | 新增混池产物 |
