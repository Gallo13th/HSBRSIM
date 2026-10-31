# 推理期搜索：完整游戏 rollout 叶值 + π_search（评测接入 + human 面板 A/B）

> **一句话**：把沙盒里验证过的搜索（候选动作 → π_base rollout 到回合末 → 叶值
> `log1p(Σ)` → π_search）搬到**完整游戏的评测路径**上，只在关键决策覆盖动作、
> **不改训练**。human 面板 256 局同 seed 配对：**mean rank 6.375 → 5.953
> （配对 Δ = −0.422，95% CI [−0.602, −0.242]）**，top4 10.2% → 14.8%，
> 盘面 Σ 在 t6–t11 上 **+17%~28%**，活到 t12 的比例 **12.9% → 24.6%（1.9×）**；
> 代价是 **≈2.3 s/局搜索、评测墙钟 3.8×**。
>
> **结论**：按任务判据（Δhuman ≤ −0.10 且 CI 上界 < +0.05）**四条臂全部通过**，
> 且大幅超出 ⇒ **推理期搜索值得作为部署/评测默认项**（推荐 `turns=1` +
> `pi_argmax`；`turns=3` 在同名次下把 t12 强度再拉 +33%，但评测墙钟 6.8×，
> 只在看后期复利时用）。

相关实现：
`hsbg/az/train/infer_search.py`（搜索 + 策略包装）、
`scripts/human_panel_eval.py` / `scripts/quality_monitor.py`（`--infer-search*` CLI）、
`scripts/infer_search_ab.py`（配对 A/B 分析）、`tests/test_infer_search.py`（9 项契约）。
搜索本身的沙盒证据见 `runs/search_labels_v2/REPORT.md`；面板口径见
`docs/EVAL_PANELS.md`。

---

## 1. 方法

### 1.1 为什么要「推理期搜索」而不是把搜索标签学进策略

`runs/search_labels_v2/REPORT.md` §4 的结论：同一套搜索结果**离线 BC 学不进去**
（样本口径 −3%~−80%），但**在线用**（关键决策按 π_search 动作）有 **+10.3% t12 /
+12.3% t15**。所以正确用法是**推理期**：评测/部署时现算，不经过参数更新。

### 1.2 一次搜索做什么（与沙盒同一套，只换状态载体）

对当前决策点（完整游戏状态 `hsbg_engine.Game`）：

1. **候选集**：π_base 概率 top-k（默认 8）的**非 Move** 合法动作（含 π_base top-1）。
   Move 段剔除，因为换位不改变盘面 Σ（也天然避开模型的换位抖动，见
   `docs/ARENA_GUARD.md`）。
2. **每条候选一条 rollout**：在 `game.copy()`（引擎深拷贝，实测 **0.011 ms**）上先执行
   该候选，然后**learner 座位用 π_base argmax 继续走到本回合末**（`--infer-search-turns 1`）
   或**第 3 个回合末**（`--infer-search-turns 3`）；`turns>1` 时其它座位用引擎 `bot_play`
   推进（0.05 ms/动作）。rollout 内 learner 每回合动作上限 40（与评测
   `--max-actions-per-turn` 同口径，防 Play/Cancel 死循环）。
3. **叶值** = `L(Σ_end) = log1p(Σ_end)/log1p(30000)`，`Σ_end` = 目标回合**最后一个
   learner 决策时**的盘面 `atk+hp` 求和（EndTurn 不改盘面 ⇒ 等价于回合末盘面）。
   观测解码 `sigmas_from_features`（×10 标定）在 12 局 157 个决策上与 `player_json`
   **逐一相等**（`tests/test_infer_search.py`）。
4. **π_search**（`sandbox_rollout.pi_from_q` 同一实现）：`V = Σp̃Q`、
   `A = Q − V`、`π ∝ p̃·exp(clip(A/τ, ±adv_clip))`，`τ = q_temp_scale × std(Q)`。
5. **动作规则**（`--infer-search-action`）：`pi_argmax`（默认，取 π_search argmax，
   确定性可复现）/ `argmax_q`（沙盒的「best」，纯叶值最优）/ `sample`（按 π_search
   采样，= 沙盒 §3 的在线口径；RNG 由 seed 派生，可复现）。
6. **预算**：只在**关键决策**上搜（`--infer-search-when`，默认 `carrier_or_spell`
   = 载体在商店/手牌 或 手牌有法术，与沙盒实测口径一致），每回合最多 3 次
   （`--infer-search-max-per-turn 3`）。其余决策照常走 π_base。

跨候选、跨 rollout 的叶前向是**一次批量 forward**（8 行），所以代价是
「一条 rollout 的步数 × 一次 forward」而不是「8 × 步数 × forward」。

### 1.3 为什么可以直接在完整游戏上做

- `Game.copy()` 是**深拷贝且极便宜**（0.011 ms；`state_json` 0.46 ms / `from_json`
  0.70 ms 的方案被否决）；搜索**不修改原局面**（单测断言 `state_json` 前后逐位相等）；
- learner 座位的观测/掩码就在手边，rollout 里不需要任何特权信息；
- 1 回合叶值**不需要推进其它座位**（learner 一结束本回合就收叶子）；只有 `turns>1`
  才需要 `bot_play` 其它座位 —— 否则单次搜索要多付 ~8 座的引擎调用。

### 1.4 边界：**不改训练**

`InferSearchPolicy` 只是 `Policy.decide` 外面的一层包装：先调 `base.decide` 拿基线与
先验，再决定是否覆盖动作。`--infer-search 0` 时是**纯 pass-through**（单测逐动作断言
等于裸 base）。实测：`--infer-search 0` 的 256 局面板 mean rank **6.375**，与历史
s16b 同口径面板（6.355）同量级（checkpoint 不是同一份文件，不能逐位比）；真正逐位
可比的是同一个 checkpoint 的 `t1`/`t1b` 复现跑（8/8 seat 完全相同）。训练侧
（`ppo.py` 采集、checkpoint、EMA、`train_entity_sync.py`）**一行未改**。

---

## 2. 实现与接口

| 位置 | 内容 |
|---|---|
| `hsbg/az/train/infer_search.py` | `InferSearchConfig` / `InferSearcher`（rollout 搜索）/ `InferSearchPolicy`（包装层）/ `trace_summary`（Σ(turn) 轨迹） |
| `scripts/human_panel_eval.py` | `--infer-search {0,1}`、`--infer-search-turns {1,3}`、`--infer-search-max-per-turn 3`、`--infer-search-when`、`--infer-search-action`、`--infer-search-topk`、`--infer-search-adv-clip`、`--infer-search-max-ms`、`--infer-search-seed`；面板 JSON 新增 `panels[i].search`（统计）与 `panels[i].strength`（Σ(turn) 轨迹 + 逐局行） |
| `scripts/quality_monitor.py` | 同名 CLI；输出新增 `infer_search`（含 `search_calls / search_ms_total / mean_ms_per_call / search_ms_per_game / switch_rate / search_timeouts` 与 `strength_t12_p50 / t15_p50`） |
| `scripts/infer_search_ab.py` | 两个面板 JSON 的**逐局配对**分析：Δrank + bootstrap CI、top4、强度比、成本、判据 |
| `tests/test_infer_search.py` | 9 项契约（pass-through、不改局面、叶值/π 合法、回合预算、守卫终止、turns=3 更深、统计自洽、snapshot/since 增量） |

**记录字段**（面板 `panels[i].search`，两臂都写，便于 A/B 对齐）：

```
search_calls / search_ms_total / mean_ms_per_call / search_ms_per_decision /
search_calls_per_game / search_ms_per_game / switch_rate / search_errors /
search_timeouts / rollout_leaf_steps(_per_call) / rollout_truncated
```

另外 `panels[i].strength` 记录 `per_turn_start` / `per_turn_end`（Σ 的
n/p50/p75/mean）、`strength.t12/t15`、`last_turn_sigma` 与**逐局行**（配对分析用）。

部署兜底：`--infer-search-max-ms`（默认 0=不限）在 rollout 循环里按墙钟检查，
超时**放弃本次搜索、退回 π_base 动作**并计入 `search_timeouts` —— 竞技场这类有
硬超时的环境应设 300–500 ms。

---

## 3. A/B 协议

- **同一 checkpoint**：`runs/infer_search_ab/ckpt_s16b_snapshot.pt`，sha256
  `ce83599e8d6fbde6c00fda49e5ed0ff89e0037bb8a816c985ba7430692b0d0d2`（= 主训练
  `runs/az_entity_s16b` step 401 的 `model.pt` 快照；训练在跑，先冻结再评测）。
- **同一 seed 面板**：`--games 256 --smoke --seed-base 420000`（8 seat × 32 局，
  auto 分位 = t≤8 p50 / 9–12 p75 / ≥13 p90，7 座对手 = 真实 10k+ 人类战团注入）。
  seat `s` 的种子是 `420000 + s·32 + [0..31]`，**两臂逐局同 seed/seat**。
- 配对统计：`Δrank = rank(search) − rank(off)`，对 256 个配对逐个重采样
  （bootstrap 20000）取 95% 分位 CI；全部确定性（无采样 RNG；`sample` 臂的 RNG 由
  seed 派生）⇒ 同一面板可复现。
- 设备：只 `cuda:7`（主训练在 cuda:3–6，未触碰）。四条搜索臂大部分时间是**并发**
  跑在 cuda:7 上的；实测并发对墙钟影响很小（GPU 是 launch-bound、多进程可交错：
  4 条并发 3.29 s/局 vs 2 条并发 3.65 s/局），所以下面的耗时可以直接当单进程口径看。
- **可复现性**：`t1` 与后来用同一配置重跑的 `t1b` 在 8 个 seat 上**逐位相同**
  （5.906/6.031/6.188/5.719/5.750/5.781/5.938/6.313）⇒ 搜索是确定性的
  （`pi_argmax` 无采样 RNG；`argmax_q` 同理；`sample` 的 RNG 由 seed 派生）。

---

## 4. 结果

### 4.1 名次 / top4（主判据）

| 臂 | 动作规则 | 叶值 horizon | mean rank | **配对 Δ [95% CI]** | top4 | 冠军 |
|---|---|---|---:|---:|---:|---:|
| `off` | — | — | 6.375 | — | 10.16% | 0 |
| `t1` | `pi_argmax` | 1 回合 | **5.953** | **−0.422 [−0.602, −0.242]** | **14.84%** | 0 |
| `t3` | `pi_argmax` | 3 回合 | **5.922** | **−0.453 [−0.648, −0.258]** | 12.89% | 0 |
| `q1` | `argmax_q` | 1 回合 | **5.934** | **−0.441 [−0.633, −0.250]** | 14.06% | 0 |
| `s1` | `sample` | 1 回合 | **5.973** | **−0.402 [−0.578, −0.227]** | 14.84% | 0 |

- **判据「Δhuman ≤ −0.10 且 CI 上界 < +0.05」：四条臂全部通过**，CI 上界都在
  −0.23 ~ −0.26（离 +0.05 有 0.28 的余量）。
- 一致性：`t1` 在 256 局里 **51.2% 变好 / 23.8% 变差**（配对符号比 2.1:1）；
  seat 级 8 个 seat 中 6 个变好、2 个不动，**没有一个 seat 变差**。
- 冠军率仍为 0（opponent 是 10k+ 人类战团，t12 Σ p50 4858 vs 我们 963）——
  **搜索是缓解，不是解药**，绝对强度差距仍在（见 `docs/EVAL_PANELS.md`）。
- top4 +4.7pp（CI [−0.4pp, +9.8pp]）方向一致但单臂不够显著（n=256、基线只有 10%
  ⇒ 配对比例差的分辨率约 ±5pp）。

### 4.2 强度：t12/t15 与**生存者偏差**

每回合末盘面 Σ 的 p50（该回合**仍活着**的局）：

| turn | off p50 (n) | `t1` ×ratio | `t3` ×ratio | `q1` ×ratio | `s1` ×ratio |
|---:|---:|---:|---:|---:|---:|
| t6 | 95.5 (256) | 112 (**×1.17**) | 102 (×1.07) | 112.5 (×1.18) | 111 (×1.16) |
| t8 | 222.0 (249) | 280.5 (**×1.26**) | 277 (×1.25) | 282 (×1.27) | 282 (×1.27) |
| t9 | 349.0 (206) | 437 (**×1.25**) | 479 (**×1.37**) | 441 (×1.26) | 437.5 (×1.25) |
| t10 | 482.5 (172) | 619 (**×1.28**) | 695 (**×1.44**) | 621 (×1.29) | 620 (×1.28) |
| t11 | 625.0 (97) | 744 (**×1.19**) | 978.5 (**×1.57**) | 794.5 (×1.27) | 789.5 (×1.26) |
| **t12** | **963.0 (33)** | 921 (**×0.96**) | **1225 (×1.27)** | 1064.5 (**×1.11**) | 967 (×1.00) |
| t13 | 1135.0 (7) | 834 (×0.73) | 1563 (×1.38) | 1585 (×1.40) | 1011.5 (×0.89) |
| t15 | — (0) | — | — | — | — |

**t15 在 human 面板上不可测**：256 局里 learner **一局都没活到 t15**（t14 只有 2 局），
所以「t15 强度比」无法在这个面板上复现沙盒的 +27%（那是 gold10 沙盒、人人活到 t15）。

**t12 条件 p50 被生存者偏差污染**。`off` 只有 33 局（12.9%）活到 t12 —— 这是它最强的
12.9%；`t1` 有 63 局（24.6%）活到 t12，多出来的都是「本来会死在第 11 回合」的局，
所以**条件** p50 反而低 4%。正确的可比口径是**对全部 256 局的无条件期望**
`E[Σ_t] = P(活到 t) × E[Σ_t | 活到 t]`（与沙盒「人人活到」的口径同构）：

| turn | off `E[Σ]` | `t1` | `t3` | `q1` | `s1` |
|---:|---:|---:|---:|---:|---:|
| t9 | 290.3 | **×1.45** | ×1.64 | ×1.42 | ×1.45 |
| t10 | 342.7 | **×1.51** | ×1.96 | ×1.50 | ×1.52 |
| t11 | 255.9 | **×1.57** | **×2.35** | ×1.72 | ×1.54 |
| t12 | 121.8 | **×2.03** | **×2.30** | ×1.87 | ×1.99 |

生存率（n/256）：t10 **67.2% → 80.5%**、t11 **37.9% → 50.4%**、t12 **12.9% → 24.6%**
（`t1`）。

**逐局配对强度**（同一 (seat, 局序)）：

| 指标 | 配对局数 | off | on | 配对 Δ [95% CI] | p50 比 |
|---|---:|---:|---:|---|---:|
| `t1` 局末（≈死亡时）Σ | **256（全部）** | 443.5 | **666.5** | **+197.0 [+150.9, +242.6]** | **×1.50** |
| `q1` 局末 Σ | 256 | 443.5 | 649.0 | — | ×1.46 |
| `s1` 局末 Σ | 256 | 443.5 | 671.5 | — | ×1.51 |
| `t1` t12 Σ（两臂都活到 t12 的局） | 13 | 1075.0 | 1058.0 | +52.2 [−198.4, +289.0] | ×0.98（均值比 ×1.28） |
| `q1` t12 Σ（同上） | 12 | 932.0 | 1173.5 | +327.7 [+55.1, +640.3] | ×1.26 |
| `s1` t12 Σ（同上） | 14 | 968.0 | 1080.5 | +115.7 [−86.6, +307.7] | ×1.12 |

**局末（死亡时）Σ 是本面板最干净的强度证据**：不受「活到 t12」的条件筛选，
256 局全配对，`t1` **+50%（配对 Δ +197，CI [151,243]，≈8.4 个标准误）**。
而「两臂都活到 t12」的子集只有 13–14 局、且基线那 13 局是它的精英局
（off p50 1075 比全体条件 p50 963 还高）⇒ 该子集上 p50 比接近 1，**不宜当主指标**。

> 读法：**判据里的「t12 强度比 ≥ +10%」在本面板上要么按无条件 E[Σ]（×2.03）算、
> 要么按 t6–t11 的条件 p50（+17%~28%）算才成立；只按「t12 条件 p50」算会得到 −4%
> 的假象**（t3/q1 因为存活集较小，连条件 p50 也都是正的 +27%/+11%）。

### 4.3 耗时

| 项 | `off` | `t1` | `t3` | `q1` | `s1` |
|---|---:|---:|---:|---:|---:|
| 搜索次数 / 局 | 0 | **18.96** | 20.61 | 19.13 | 18.92 |
| 单次搜索 mean（ms） | — | **119.4** | **245.8** | 118.0 | 116.6 |
| 搜索耗时 / 局（s） | 0 | **2.26** | **5.07** | 2.26 | 2.21 |
| 每决策 ms（含推理） | 6.26 | 20.03 | 41.32 | 20.15 | 19.62 |
| 评测墙钟 256 局（s） | 222.6 | **843.1** | **1523.9** | 838.3 | 821.9 |
| 墙钟倍数 | 1.0× | **3.8×** | **6.8×** | 3.8× | 3.7× |
| 每次搜索 rollout 步数 | — | 102.6 | 247.9 | 101.8 | 101.1 |
| 动作切换率（覆盖 π_base） | — | 32.6% | 42.3% | 42.5% | 41.4% |

- 触发率：**18.96 次/局，占 learner 决策的 11.5%**（搜索臂 164.4 决策/局；
  对照臂 139.0 决策/局是因为对局更早结束）。每回合 3 次的上限在 16 回合里基本打满
  被触发的回合（理论上限 48 次）。
- 单次延迟的量级与沙盒同阶但**更慢**：本机 leaf forward 是**批内常数 ~5.3 ms**
  （B=1 与 B=8 同价：16.4M 模型在 4090 上是 launch-bound），所以
  `turns=1 ≈ (rollout 步数 / 8 个候选的并行度) × 5.3 ms + 每步引擎开销`。
  单点分布见 §5.4（p50 118 ms / p90 257 ms / max 306 ms）。

### 4.3.1 `quality_monitor` 接线核对

`quality_monitor --infer-search 1` 已跑通（`runs/infer_search_ab/quality_smoke.json`，
3 局 / 421000 起）：`search_calls=85`、`mean_ms_per_call=155.6`、`search_timeouts=0`
（`--infer-search-max-ms 500`）、`searched_ratio=9.7%`、`strength_t12_p50=801`。
注意 `quality_monitor` 的默认对手是**引擎 bot**（mean rank 1.0，已饱和），所以它的
**名次**不能当搜索 A/B 的判据；它的价值在逐回合强度/载体/`infer_search` 统计段。
搜索效果的 A/B 只看 human 面板（§4.1–4.2）。

### 4.4 `turns=1` vs `turns=3`，以及动作规则

- **名次上两者分不开**：`t1` → `t3` 的配对 Δ 只有 **−0.031 [−0.219, +0.160]**（CI 跨 0），
  top4 反而 −1.95pp；也就是说**深度不是名次的答案**（与沙盒 §5.1 一致）。
- **深度买的是后期强度**：t12 条件 p50 `t3/t1` = **×1.33**、t11 ×1.32、E[Σ_t12] ×2.30
  vs ×2.03。代价是搜索耗时 **2.24×**（5.07 s/局）、墙钟 **6.8×**。
- **动作规则几乎没有差别**：`pi_argmax` / `argmax_q` / `sample` 三者的 Δrank 分别是
  −0.422 / −0.441 / −0.402（CI 互相重叠），差别只在切换率（33% / 43% / 41%）与
  t12 条件强度（×0.96 / ×1.11 / ×1.00，`t3` 最高 ×1.27）。**默认取 `pi_argmax`**：
  确定性、便宜、与 `sample` 同分布族。

---

## 5. 判据核对与部署建议

### 5.1 判据

| 判据 | `t1` | `t3` | `q1` | `s1` |
|---|---|---|---|---|
| Δhuman ≤ −0.10 且 CI 上界 < +0.05 | ✅ −0.422 [−0.602,−0.242] | ✅ −0.453 [−0.648,−0.258] | ✅ −0.441 | ✅ −0.402 |
| t12 强度比 ≥ +10%（条件 p50） | ❌ ×0.96 | ✅ ×1.27 | ✅ ×1.11 | ❌ ×1.00 |
| t12 强度比 ≥ +10%（无条件 E[Σ]） | ✅ ×2.03 | ✅ ×2.30 | ✅ ×1.87 | ✅ ×1.99 |
| t11 条件 p50 ≥ +10% | ✅ +19% | ✅ +57% | ✅ +27% | ✅ +26% |

→ 按「名次 + 无条件强度」口径 **四条臂全部达标**；唯一不达标的是「t12 **条件** p50」，
而它在本面板上是被生存者偏差污染的量（§4.2）。任务里的备选结论「只有强度比涨而名次
不动」**没有出现**——名次涨得比强度更明显。

### 5.2 部署建议

1. **评测/面板默认开**（`--infer-search 1 --infer-search-turns 1 --infer-search-action
   pi_argmax`）：
   - 收益：human 面板 mean rank −0.42（= 4.5 个配对标准误）、top4 +4.7pp、
     t12 存活翻倍、局末盘面 +50%；
   - 代价：256 局评测 **+10 分钟**；512 局正式面板从 ~7 分钟到 ~28 分钟（可接受，
     且与训练异步评测（`scripts/async_eval.py`）不冲突）；
   - 若只要便宜的名次信号，`turns=1` 就够；`turns=3` 用在「后期复利」专项。
2. **竞技场（`scripts/arena_agent.py`）建议：先 smoke 再默认开**。
   - 单次搜索 ~119 ms（solo 见 §5.4），只在 **11%** 的决策上发生；非搜索决策仍是
     6 ms ⇒ 对局平均 +2.3 s；
   - **必须带 `--infer-search-max-ms 300~500`**：solo 实测 `turns=1` p90 257 ms /
     max 306 ms，长回合（8 候选 × 剩余 20+ 动作）能到 300 ms 以上；500 ms 预算下
     几乎不会触发，300 ms 会砍掉 ~5–10% 的尾延迟搜索，超时退回 π_base 是安全的；
   - 与 `--move-guard` **互补**：搜索候选剔除 Move 段，天然不再「每回合刷满换位」；
   - 已知风险：搜索的叶值只含盘面 Σ（无战斗、无经济、无池），长回合尾延迟不可预测，
     **不要**在 `turns=3` 下开竞技场默认（5 s/局）。
3. **不要**把搜索当训练信号（v2 已证 BC 学不进去）；也不要在同一批部署里既开
   搜索又保留 `--move-guard 1` 的高 cap（重叠但无害）。

### 5.3 局限

- **评测耗时 3.8×（1 回合）/ 6.8×（3 回合）**：`turns=1` 时 2.26 s/局、每决策
  6.26 → 20.03 ms；`turns=3` 时 5.07 s/局、41.32 ms/决策。搜索是**串行**的
  （一个决策一次），不能跨决策批量摊销。
- **2–5× 延迟**：单次 119 ms（1 回合）/ 246 ms（3 回合），p100 在长回合上可到
  0.4–0.5 s；并发评测时再 ×1.3–1.6。
- **叶值是我的**：1 回合 horizon 看不到「买载体 → 下回合施法」的复利（沙盒 §5、本面板
  §4.4 同结论）；叶值只有 Σ，**不含战斗胜负、经济、共享池、英雄技能**。
- **面板量级**：本轮只有 **1 个封存 seed 面板（420000，256 局）**，正式面板按协议是
  512 局 × 2 面板；top4 的配对 CI 仍跨 0，冠军率仍为 0。
- **t15 不可测**：human 面板上 learner 活不到 t15（t15 n=0），沙盒的 t15 +27%/3 回合
  +27% 无法在本面板复核。
- **搜索只覆盖 11% 决策**：其余 89% 仍是 π_base，所以上限受策略本身限制；搜索没有
  改变「绝对强度离 10k+ 还差 5×」这件事。

### 5.4 solo 延迟实测（部署口径）

单进程、无其它评测进程，在真实中局决策点（turn 4/6/8/10/12/13，4 个 seed）上各跑一次
完整搜索（`scripts/infer_search_latency.py`）：

| 配置 | n | mean ms | **p50** | **p90** | **max** | rollout 步数 | 覆盖动作率 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `turns=1`, topk=8, `pi_argmax` | 14 | 144.8 | **117.8** | **256.6** | **306.5** | 111.9 | 71% |
| `turns=3`, topk=8, `pi_argmax` | 14 | 293.3 | **281.2** | **301.0** | **471.1** | 236.4 | 64% |

（这里的「覆盖动作率」是无条件在**每个**决策点上搜的比例；真实评测里只有 11.5% 的
关键决策会搜，所以 19 次/局 × 118 ms ≈ **2.2 s/局**。数据文件：
`runs/infer_search_ab/latency_solo_t1.json` / `latency_solo_t3.json`。）

读法：`turns=1` 的 p90 是 p50 的 2.2 倍（长回合 rollout 步数多），`turns=3` 的分布更窄
但整体高 2 倍多；两者都在「每步一次批量 forward」的 5.3 ms 粒度上。

---

## 6. 复现命令

```bash
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
cd /home/data/users/gaoletian/projects/HSBRSIM

# 0) 冻结 checkpoint（主训练在跑，先快照）
cp runs/az_entity_s16b/model.pt runs/infer_search_ab/ckpt_s16b_snapshot.pt

# 1) 对照臂：search 关（256 局 / seed 420000 / 8 seat × 32）
PYTHONPATH=rust/python:. $PY scripts/human_panel_eval.py \
  --checkpoint runs/infer_search_ab/ckpt_s16b_snapshot.pt --games 256 --smoke \
  --device cuda:7 --seed-base 420000 --bootstrap 1000 --baseline-bot 0 \
  --infer-search 0 --out runs/infer_search_ab/human_base0.json

# 2) 实验臂：turns=1 / pi_argmax（turns=3 换 --infer-search-turns 3；
#    动作规则换 --infer-search-action argmax_q|sample）
PYTHONPATH=rust/python:. $PY scripts/human_panel_eval.py \
  --checkpoint runs/infer_search_ab/ckpt_s16b_snapshot.pt --games 256 --smoke \
  --device cuda:7 --seed-base 420000 --bootstrap 1000 --baseline-bot 0 \
  --infer-search 1 --infer-search-turns 1 --infer-search-max-per-turn 3 \
  --infer-search-when carrier_or_spell --infer-search-action pi_argmax \
  --out runs/infer_search_ab/human_t1.json

# 3) 配对 A/B（Δrank + bootstrap CI、top4、t12/t15 强度比、成本、判据）
PYTHONPATH=rust/python:. $PY scripts/infer_search_ab.py \
  --off runs/infer_search_ab/human_base0.json \
  --on  runs/infer_search_ab/human_t1.json \
  --out runs/infer_search_ab/ab_t1.json

# 4) 质量面板（逐回合强度 + 载体 + 搜索统计）
PYTHONPATH=rust/python:. $PY scripts/quality_monitor.py \
  --checkpoint runs/infer_search_ab/ckpt_s16b_snapshot.pt --device cuda:7 \
  --games 48 --infer-search 1 --infer-search-turns 1 \
  --infer-search-max-ms 500 --out runs/infer_search_ab/quality_s1.json

# 5) 契约测试
PYTHONPATH=rust/python:. $PY -m pytest tests/test_infer_search.py -q
```

---

## 7. 文件清单

| 文件 | 作用 |
|---|---|
| `hsbg/az/train/infer_search.py` | 完整游戏 rollout 搜索 + 策略包装 + Σ(turn) 轨迹 |
| `tests/test_infer_search.py` | 9 项契约（pass-through / 不改局面 / 叶值 / π / 预算 / 守卫 / turns=3 / 统计） |
| `scripts/human_panel_eval.py` | `--infer-search*` CLI + 面板 `search` / `strength` 段 |
| `scripts/quality_monitor.py` | 同名 CLI + 输出 `infer_search` 段 |
| `scripts/infer_search_ab.py` | 两面板逐局配对分析（Δrank CI / top4 / 强度比 / 成本 / 判据） |
| `runs/infer_search_ab/ckpt_s16b_snapshot.pt` | 冻结 checkpoint（sha256 `ce83599e…`） |
| `scripts/infer_search_latency.py` | 单进程单次延迟实测（§5.4） |
| `runs/infer_search_ab/human_{base0,t1,t3,q1,s1}.json` | 5 条臂的 256 局面板 |
| `runs/infer_search_ab/human_t1b.json` | `t1` 的复现跑（验证确定性 + 逐局轨迹） |
| `runs/infer_search_ab/ab_{t1,t1b,t3,q1,s1,t1_vs_t3}.json` | 配对 A/B 报告 |
| `runs/infer_search_ab/latency_solo_t{1,3}.json` | solo 延迟分布 |
| `runs/infer_search_ab/quality_smoke.json` | `quality_monitor --infer-search 1` 接线核对 |
| `runs/infer_search_ab/smoke_s1.json` | 8 局开发 smoke（接线自检） |
