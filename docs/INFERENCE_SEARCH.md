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
`scripts/infer_search_ab.py`（配对 A/B 分析）、`tests/test_infer_search.py`（11 项契约）。
本节之后新增的**正式协议**（3 checkpoint × 512×2 封存面板）、**搜索调参**、**叶值消融**
与**部署默认配置**见 §7。
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
| `scripts/human_panel_eval.py` | `--infer-search {0,1}`、`--infer-search-turns {1,3}`、`--infer-search-max-per-turn`、`--infer-search-when`、`--infer-search-action`、`--infer-search-topk`、`--infer-search-adv-clip`、`--infer-search-max-ms`、`--infer-search-seed`、**`--infer-search-tier-bonus` / `--infer-search-health-bonus`**（叶值附加项）；面板 JSON 新增 `panels[i].search`（统计）与 `panels[i].strength`（Σ(turn) 轨迹 + 逐局行） |
| `scripts/quality_monitor.py` | 同名 CLI；输出新增 `infer_search`（含 `search_calls / search_ms_total / mean_ms_per_call / search_ms_per_game / switch_rate / search_timeouts` 与 `strength_t12_p50 / t15_p50`） |
| `scripts/infer_search_ab.py` | 两个面板 JSON 的**逐局配对**分析：Δrank + bootstrap CI、top4、强度比、成本、判据 |
| `tests/test_infer_search.py` | 11 项契约（pass-through、不改局面、叶值/π 合法、回合预算、守卫终止、turns=3 更深、统计自洽、snapshot/since 增量、**`leaf_score` 权重契约、叶值附加项接线**） |

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
2. **（2026-11 更新）** §5.2 的判断已被 §7 的正式协议（3 checkpoint × 512×2 封存面板）
   与调参（t6）取代：**部署默认配置以 §7.6 为准**（`max_per_turn=6` + `max_ms 300–500`，
   竞技场协议 v2 暂不可用）。下面第 3/4 条保留为历史依据。
3. **竞技场（`scripts/arena_agent.py`）建议：先 smoke 再默认开**。
   - 单次搜索 ~119 ms（solo 见 §5.4），只在 **11%** 的决策上发生；非搜索决策仍是
     6 ms ⇒ 对局平均 +2.3 s；
   - **必须带 `--infer-search-max-ms 300~500`**：solo 实测 `turns=1` p90 257 ms /
     max 306 ms，长回合（8 候选 × 剩余 20+ 动作）能到 300 ms 以上；500 ms 预算下
     几乎不会触发，300 ms 会砍掉 ~5–10% 的尾延迟搜索，超时退回 π_base 是安全的；
   - 与 `--move-guard` **互补**：搜索候选剔除 Move 段，天然不再「每回合刷满换位」；
   - 已知风险：搜索的叶值只含盘面 Σ（无战斗、无经济、无池），长回合尾延迟不可预测，
     **不要**在 `turns=3` 下开竞技场默认（5 s/局）。
4. **不要**把搜索当训练信号（v2 已证 BC 学不进去）；也不要在同一批部署里既开
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

---

## 7. 正式协议验证（512 局 × 2 封存面板）/ 搜索调参 / 叶值消融

§1–§6 的证据都来自**单个 256 局面板 + 单个 checkpoint**（s16b step401 快照）。本节把它
升级到正式协议：**3 个 checkpoint × {off, t1} × 512 局 × 2 个不重叠封存面板**，
并在最好的 checkpoint 上做搜索超参调优与叶值消融，最后给部署默认配置。

### 7.1 协议

| 项 | 值 |
|---|---|
| checkpoint | `runs/az_entity_s14/model.pt`（训练期 human 面板最好 6.223）、`runs/az_entity_s16/model.pt`（band0 60M）、`runs/az_entity_s16b/model.pt`（**step 1001 快照**，主训练在跑，先冻结） |
| 快照目录 | `runs/infer_search_formal/ckpt_{s14,s16,s16b}.pt`（sha256 见 §7.2） |
| 面板 | **512 局 = 8 seat × 64 局**，auto 难度曲线（t≤8 p50 / 9–12 p75 / ≥13 p90） |
| 面板 A / B | `--seed-base 830001`（种子 830001–830512）/ `830513`（种子 830513–831024） |
| 配对 | 同 (seat, 局序) 逐局配对；Δ = rank(t1) − rank(off)；bootstrap 20000 |
| 面板聚合 | 合并 1024 局的 Δ 与 CI，**另报面板分层 bootstrap** 与**逐面板 Δ**（两面板是否同向） |
| 硬约束 | 0 illegal / 0 truncated / 0 truncated_combats（3 ckpt × 2 臂 × 2 面板全部通过） |
| 设备 | 只 `cuda:7`（主训练在 cuda:3–6，未触碰、未重启） |

**关于面板 seed**：任务里写的是「830001 / 830002」。本脚本的种子派生是
`seed_base + seat·per_seat`（per_seat = 64），`830002` 与 `830001` 会重叠 **511/512 局**
—— 两个面板几乎是同一批局，配对完全没有独立信息；`human_panel_eval.py --confirmations 2`
也会直接拒绝这种重叠（`sealed_base < seed_base + games`）。所以面板 B 取
**830001 + 512 = 830513**：两面板的 512 个 seed 完全不重叠，这才是「2 个独立封存面板」。

调参 / 消融用**第三个面板** `830901`（256 局，8 seat × 32），与正式两面板不共享任何种子，
只用于选配置；选出的配置再回到正式面板做确认（§7.4）。

### 7.2 正式结果：三个 checkpoint × {off, t1}

1024 局/臂，配对 1024 对（8 名对手全部注入人类战团，0 illegal / 0 truncation）：

| checkpoint | off mean rank | t1 mean rank | **配对 Δ [95% CI]** | SE | 面板 A Δ / 面板 B Δ | top4 off→t1 |
|---|---:|---:|---:|---:|---:|---:|
| **s14**（6.223） | 6.2754 | **5.9131** | **−0.362 [−0.450, −0.273]** | 0.045 | −0.375 / −0.350 | 9.08% → **14.94%**（+5.86pp） |
| s16（60M） | 6.3232 | 5.9443 | **−0.379 [−0.468, −0.291]** | 0.045 | −0.391 / −0.367 | 8.59% → 13.38%（+4.79pp） |
| s16b（step1001） | 6.3359 | 5.9375 | **−0.398 [−0.489, −0.309]** | 0.046 | −0.494 / −0.303 | 8.79% → **15.04%**（+6.25pp） |

快照 sha256（前缀）：`s14` = `fffc395c`、`s16` = `97631cfb`、`s16b` = `937d1783`
（`runs/infer_search_formal/ckpt_*.pt`；s16b 的 `model.pt` 在训练中每步更新，所以必须先
快照再评测 —— 快照点是 step 1001，与 §4 的 step 401 不是同一份文件）。

- **三个 checkpoint 全部通过判据**（Δ ≤ −0.10 且 CI 上界 < +0.05），CI 上界都在 −0.27 ~ −0.31，
  离 +0.05 有 0.3 以上余量；**两个封存面板方向一致**（分层 bootstrap CI 与合并 CI 几乎相同）。
- **t1 口径最好的组合 = `s14` + `t1`：5.9131**（比 s16b t1 低 0.024、比 s16 t1 低 0.031；
  再叠上 §7.3/§7.4 的 `max_per_turn=6` 得到 **`s14` + `t6` = 5.8428**，是全部 4 个
  checkpoint×配置组合里最低的（off→t6 的配对 Δ = −0.433）。三个
  checkpoint 的 t1 名次在 5.91–5.94，彼此差 ≤0.03，远小于 CI 半宽 0.09 ⇒ 三者的
  **搜索后**名次统计上不可区分；但 off 臂上 s14 最稳（两面板 6.277 / 6.273，另两个
  checkpoint 的面板间波动 0.08–0.21）。
- top4 也是三个 checkpoint 全部 +4.8 ~ +6.3pp：`s16` +4.79pp CI [+2.3, +7.2]、
  `s16b` +6.25pp CI [+3.7, +8.8]、`s14` +5.86pp CI [+3.2, +8.5] —— 1024 局下
  **top4 提升已经显著**（256 局面板的 CI 还跨 0，§4.1）。
- 冠军率仍为 **0/1024**（人类战团绝对强度差距仍在，搜索是缓解）。

**强度（逐回合末盘面 Σ，两面板取中位）**：

| checkpoint | t8 条件 p50 | t10 | t11 | **t12 条件 p50** | **t12 无条件 E[Σ]** | t12 存活率 |
|---|---:|---:|---:|---:|---:|---|
| s14 | ×1.20 | ×1.22 | ×1.17 | **×1.24** | **×1.87** | 12.9/15.4% → 22.1/22.9% |
| s16 | ×1.17 | ×1.15 | ×1.12 | ×1.05 | ×1.76 | 12.3/13.9% → 20.7/21.9% |
| s16b | ×1.18 | ×1.20 | ×1.18 | ×1.18 | ×1.80 | 13.3/13.5% → 20.7/21.7% |

读法与 §4.2 相同：**t12 条件 p50 有生存者偏差**（存活率从 ~13% 涨到 ~22% ⇒ 多出来的
是「本来会死在第 11 回合」的局），无条件 `E[Σ_t12]` 才是可比口径（×1.76–1.87）。
存活率整条曲线都抬升：t10 **63–69% → 79–82%**、t11 **35–41% → 49–57%**、t12 **12–15% → 21–23%**
（三个 checkpoint 一致，见 `SUMMARY.json` 的 `strength.survival`）。
在 1024 局上，三个 checkpoint 的 t12 条件 p50 都在 ×1.05–1.24 —— 也就是说 §4.1 里
「t12 条件强度比不达标（×0.96）」是**单面板 256 局的噪声**，不是搜索的固有性质。

**成本**：off 臂 **1.6–2.1 s/局**、t1 臂 **4.6–5.2 s/局**（同一批 6 路并发下的
`model_seconds`，逐面板见 `SUMMARY.json`），两臂墙钟比 2.5–2.9×；其中**搜索占 t1 的
63–72%**（2.9–3.8 s/局、18.4–19.2 次/局、单次 155–236 ms —— 并发下的墙钟，solo 见 §7.6）。
注意 6 路并发里 off 臂被 t1 挤慢（solo 0.9 s/局）⇒ 这个比值**低估**纯搜索开销，
solo 口径仍是 §4.3 的 3.8×。三个 checkpoint 的搜索次数/局几乎一样（18.4–19.2）
⇒ 成本差异只来自并发/负载，不是模型差异。

### 7.3 搜索调参（s14，256 局单面板 830901，逐配置 vs 默认 t1 配对）

默认 t1 = `--infer-search-when carrier_or_spell --infer-search-max-per-turn 3
--infer-search-topk 8`；一次只改一个维度。Δ = rank(配置) − rank(默认)，负值 = 更好。

| 配置 | when | max/turn | topk | mean rank | **Δ [95% CI]** | top4 | 搜索次数/局 | 搜索 ms/局 |
|---|---|---|---:|---:|---:|---|---:|---:|---:|
| 默认 t1（参考） | `carrier_or_spell` | 3 | 8 | 5.9258 | — | 10.55% | 19.37 | 3044 |
| **t6** | `carrier_or_spell` | **6** | 8 | **5.8164** | **−0.109 [−0.238, +0.023]** | 14.45% | 32.59 | 5148 |
| `any` | `any` | 3 | 8 | 5.9258 | 0.000 [−0.195, +0.195] | 15.23% | 32.65 | 4847 |
| `spell_in_hand` | `spell_in_hand` | 3 | 8 | 5.9492 | +0.023 [−0.062, +0.109] | 12.89% | 18.32 | 2776 |
| `max1` | `carrier_or_spell` | **1** | 8 | 5.9844 | +0.059 [−0.086, +0.207] | 12.50% | 7.12 | 1147 |
| `topk16` | `carrier_or_spell` | 3 | **16** | 5.9531 | +0.027 [−0.082, +0.141] | 10.94% | 19.23 | 3533 |

- **唯一达标的配置是 `max_per_turn 3 → 6`（t6）**：Δ = **−0.109**，CI 上界 **+0.023 < +0.05**
  ⇒ 同时满足「再低 ≥0.05 名」与「CI 上界 < +0.05」。代价是搜索次数 19.4 → 32.6 次/局、
  搜索耗时 3044 → 5148 ms/局（×1.69），墙钟约 ×1.7。
- **`any` 的名次收益正好是 0**（逐局配对 Δ 均值 = 0.0000，CI [−0.195, +0.195]），但
  **top4 +4.69pp、t12 存活率 21.9% → 29.7%** —— 它把搜索预算花在「更早的回合」上，
  买到的是强度/生存，不是名次。触发次数 32.65 次/局（比默认多 69%），名次却不动
  ⇒ **搜索覆盖率不是名次的瓶颈**。
- `spell_in_hand` 与默认**几乎等价**（触发 18.3 次/局 ≈ 默认 19.4；Δ +0.023 在噪声内）：
  「手牌有法术」这一条几乎覆盖了 `carrier_or_spell` 的全部有效触发。
  `max_per_turn=1` 反向验证了预算的重要性（触发降到 7.1 次/局，Δ +0.059：省 62% 搜索
  换来 0.06 名退步，**性价比很高**，见部署建议）。
- `topk 8 → 16` **没有收益**（Δ +0.027，单次搜索贵 17%）：π_base 的 top-16 里多出来的
  候选几乎不会成为最优 —— 候选集不是瓶颈。
- 统计功效提醒：256 局配对 Δ 的 SE ≈ 0.044–0.076，CI 半宽 0.09–0.15。**只有 t6 的效应量
  （−0.11）能在这个样本量下被分辨**；其余配置的 |Δ| < 0.06 都在噪声内，不能读成
  「更差」，只能读成「没有可测收益」。

### 7.4 t6 的正式面板确认跑 + 叶值消融

**先把调参结论放回正式面板**（`runs/infer_search_formal/confirm/s14_t6_panel{A,B}.json`，
与 §7.2 的 `human_s14_t1.json` **同 seed/seat 逐局配对**，n = 1024）：

| 对比（s14） | 基线 mean rank | t6 mean rank | **配对 Δ [95% CI]** | SE | 面板 A / B Δ | top4 |
|---|---:|---:|---:|---:|---:|---:|
| t6 vs 默认 t1 | 5.9131 | **5.8428** | **−0.070 [−0.135, −0.006]** | 0.033 | −0.076 / −0.064 | 14.94% → **17.77%**（+2.83pp） |
| t6 vs off | 6.2754 | **5.8428** | **−0.433 [−0.523, −0.343]** | 0.046 | −0.451 / −0.414 | 9.08% → **17.77%** |

- **256 局的 −0.109 在 1024 局上回落到 −0.070**（SE 从 0.066 降到 0.033）：方向、量级都在，
  但**小样本调参表会放大效应量** —— 可信的部署增益是 **−0.070**，不是 −0.109。
- 判据：Δ = −0.070 ≤ −0.05 且 **CI 上界 −0.006 < +0.05** ⇒ **达标**；而且 CI 上界 < 0，
  即「t6 优于默认 t1」在 95% 水平上显著。两个封存面板同向（−0.076 / −0.064）。
- top4 也显著（+2.83pp，CI [+0.49, +5.27]）；冠军率仍然 0/1024。
- **t6 相对 t1 没有额外买到强度**：t10/t11/t12 条件 p50 = ×1.04 / ×1.04 / ×0.99，
  无条件 `E[Σ_t12]` ×1.01，t12 存活率基本持平（22.1/22.9% → 23.8/22.1%）⇒ 它的收益纯粹来自
  「同一回合内多搜几次、把次序排对」，**不是后期复利**。这也解释了它为什么比 `any`
  （把预算摊到更早的回合、t12 存活率能到 29.7%）更划算：名次要的是**当前回合的最优动作**。
- 代价：搜索次数 19.2 → 32.0 次/局（×1.67），单次搜索延迟不变；s14 solo 实测
  **p50 130 ms / p90 267 ms / max 291 ms**（`latency_solo_s14_t1.json`，n=14）⇒
  **max-ms 300 会砍掉约 5% 的尾延迟搜索，500 基本不触发**。

叶值消融（同一 256 局面板 830901，逐局配对）：

| 叶值 | mean rank | **Δ vs 默认叶值 [95% CI]** | top4 | t12 存活率 |
|---|---:|---|---:|---:|
| `log1p(Σ)`（默认） | 5.9258 | — | 10.55% | 21.9% |
| **`+ 0.02·(health/30)`** | 5.9141 | **−0.012 [−0.059, +0.039]** | 10.55% | **23.4%** |
| `+ 0.02·(tier/6)` | 5.8711 | **−0.055 [−0.156, +0.047]** | **14.45%** | 23.4% |

- **血量项（w=0.02）在名次上没有可测收益**（Δ −0.012，CI [−0.059, +0.039]，半宽 0.049），
  但方向对、成本为零（单次搜索 ms 反而从 157 降到 147，t12 存活率 +1.5pp）⇒ 可以作为
  **零风险的部署备选**，但**不能**宣称它有效。
- **tier 项（w=0.02）方向一致且更大**：Δ = **−0.055**，CI 上界 **+0.047 < +0.05**，top4
  +3.91pp、t12 存活率 +1.5pp；按本任务的机械判据（Δ ≤ −0.05 且 CI 上界 < +0.05）它「达标」，
  但 CI 跨 0（[−0.156, +0.047]，SE 0.052）⇒ **证据强度远低于 t6**，只能当「方向性支持」。
- 两个附加项都是**加性的小项**（w·(tier/6) / w·(health/30)，最大贡献 0.02），而 8 候选叶值的
  典型 spread 是 0.02–0.10 ⇒ 它们只在「叶值几乎打平」的决策上改选择，天然只能拿到小幅收益。
  想放大效应需要更大的 w（会开始压过 Σ 信号）或 `turns=3`，两者都没在本轮验证。
- 结论：**叶值只含 `log1p(Σ)` 的默认口径已经够用**；「高身材但快死」的担忧在这个
  面板上没有转化为名次差异 —— 因为 1 回合叶值里血量几乎不变（同一回合内血量只在
  战斗后变化，而 1 回合叶值在 learner 回合末截止，通常还没结算战斗），
  **health 项的信息量本来就低**。要让它有用，得配 `--infer-search-turns 3`（跨回合才会
  出现「买载体 vs 保血」的权衡）。

### 7.5 并发/吞吐：cuda:7 的饱和点

这一轮把并发误差量化了（`runs/infer_search_formal/concurrency_bench.json`）：

| 并发 | 单进程 t1 速度 | 聚合吞吐 | 结论 |
|---:|---:|---:|---|
| 1–2 | 3.6 s/局 | 0.56 局/s | GPU 空转一半 |
| **4** | 3.5 s/局 | **1.13 局/s** | **饱和点，单进程速度不掉** |
| 6（3×t1 + 3×off） | 3.7 s/局 | ~1.1 局/s | 仍饱和，off 臂被压到 4.1 s/局 |
| 12 | **15 s/局** | <0.4 局/s | **CUDA 上下文抖动，吞吐反降** |

- 每局 t1 大约 380 次 leaf forward（`139 决策 + 19 次搜索 × 102.6 rollout 步 / 8 候选`），
  4090 上的饱和吞吐 ≈ **420 leaf-forward/s** ⇒ 6 条并发臂正好吃满。**跑评测请开 4–6
  条并发，不要开 8 条以上**；本节所有成本数字都是 6 条并发下的墙钟（单次搜索 155–236 ms），
  **solo 的 p50 = 130 ms / p90 267 ms / max 291 ms**（s14 实测，§7.4；与 §5.4 的
  118 ms 同量级，差异来自机器负载）。

### 7.6 部署默认配置建议

| 场景 | 建议配置 | 依据 |
|---|---|---|
| **评测/面板（评模型用）** | `--infer-search 1 --infer-search-turns 1 --infer-search-when carrier_or_spell --infer-search-max-per-turn 6 --infer-search-topk 8 --infer-search-action pi_argmax`（= **t6**） | 正式面板 1024 局确认：s14 + t6 = **5.8428**（off 6.2754，t1 5.9131），t6−t1 = **−0.070 [−0.135, −0.006]**、top4 17.77%；成本 = 搜索次数 ×1.67、单次延迟不变 |
| **训练期异步评测（`--eval-async 1`）** | 同上，再加 `--infer-search-max-ms 500` | 异步评测有排队语义，500 ms 兜底几乎不触发（solo p90 267 ms），超时退回 π_base 不影响结论 |
| **本地/自托管对局（有完整 `hsbg_engine.Game`）** | 同上；**必须带 `--infer-search-max-ms 300–500`** | s14 solo 实测 p50 130 / p90 267 / max 291 ms；300 ms 会砍掉 ~5% 的尾延迟搜索（超时退回 π_base 是安全的），500 ms 基本不触发 |
| **竞技场（TavernArena 协议 v2）** | **真实竞技场客户端暂不开搜索**：`arena_agent.act()` 只有 4017/447 观测，没有本地 `Game`，rollout 无从展开。**本地模拟（`quality_monitor --policy arena`）可以开**（那里有 engine `Game`，按上一行带 max-ms） | `scripts/arena_agent.py` 是 obs→动作的单次前向，无法构造候选 rollout；这是**能力边界，不是调参问题**。arena 的硬超时若 < 300 ms，宁可不搜（超时退回 π_base 只是回到旧行为） |
| **成本敏感 / 只想赚便宜的名次** | `--infer-search-max-per-turn 1` | 触发 7.1 次/局（省 62% 搜索）、搜索耗时 1147 ms/局（并发下），Δ 仅 +0.059（退 0.06 名），且 top4 +1.95pp |

**一句话**：正式协议下三个 checkpoint 的 t1 都稳定拿到 **−0.36 ~ −0.40** 名
（s14 最好 5.9131）；**`max_per_turn 3 → 6` 在正式面板上再压 −0.070**
（s14 5.9131 → **5.8428**，CI [−0.135, −0.006]，CI 上界 < 0），代价是搜索次数 ×1.67、
单次延迟不变 ⇒ **部署默认取 t6**；若评测墙钟/成本敏感，退回默认 t1（差 0.07 名）或
`max_per_turn=1`（差 0.13 名、搜索省 62%）。叶值加 health/tier 项只有 −0.01/−0.05 的
边际效果（CI 跨 0），**不建议为了它们改默认叶值**。

### 7.7 复现命令

```bash
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
cd /home/data/users/gaoletian/projects/HSBRSIM

# 0) 冻结三个 checkpoint（主训练在跑，先快照；s16b 是 step 1001）
mkdir -p runs/infer_search_formal
cp runs/az_entity_s14/model.pt  runs/infer_search_formal/ckpt_s14.pt
cp runs/az_entity_s16/model.pt  runs/infer_search_formal/ckpt_s16.pt
cp runs/az_entity_s16b/model.pt runs/infer_search_formal/ckpt_s16b.pt

# 1) 正式协议：3 ckpt × {off, t1} × 512 局 × 2 不重叠封存面板（830001 / 830513），
#    6 条臂并发正好吃满 cuda:7（见 runs/infer_search_formal/launch_formal.sh）
bash runs/infer_search_formal/launch_formal.sh

# 2) 多面板配对 A/B（合并 1024 局 + 面板分层 bootstrap + 逐面板 Δ）
PYTHONPATH=rust/python:. $PY scripts/infer_search_formal_ab.py \
  --off runs/infer_search_formal/human_s14_off.json \
  --on  runs/infer_search_formal/human_s14_t1.json \
  --out runs/infer_search_formal/ab_s14_t1.json

# 3) 调参 + 叶值消融（256 局单面板 830901；最多 2–3 并发，见 §7.5）
CKPT=s14 SLOTS=3 bash runs/infer_search_formal/launch_queue.sh

# 4) t6 确认跑（正式两面板各 512 局）+ 与默认 t1 / off 的逐局配对
PYTHONPATH=rust/python:. $PY scripts/infer_search_confirm_ab.py \
  --base runs/infer_search_formal/human_s14_t1.json \
  --arm runs/infer_search_formal/confirm/s14_t6_panelA.json \
  --arm runs/infer_search_formal/confirm/s14_t6_panelB.json \
  --out runs/infer_search_formal/ab_s14_t6_confirm.json

# 5) 汇总（正式 + 调参 + 消融 + 确认跑 + 排名）→ SUMMARY.json
PYTHONPATH=rust/python:. $PY scripts/infer_search_formal_summary.py \
  --dir runs/infer_search_formal --bootstrap 20000

# 6) 部署口径的 solo 延迟
PYTHONPATH=rust/python:. $PY scripts/infer_search_latency.py \
  --checkpoint runs/infer_search_formal/ckpt_s14.pt --device cuda:7 \
  --turns 1 --topk 8 --max-per-turn 3 --samples 16 \
  --out runs/infer_search_formal/latency_solo_s14_t1.json
```

---

## 8. 文件清单

| 文件 | 作用 |
|---|---|
| `hsbg/az/train/infer_search.py` | 完整游戏 rollout 搜索 + 策略包装 + Σ(turn) 轨迹 |
| `tests/test_infer_search.py` | 11 项契约（pass-through / 不改局面 / 叶值 / π / 预算 / 守卫 / turns=3 / 统计 / **叶值附加项 + 接线**） |
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
| `scripts/infer_search_formal_ab.py` | **多封存面板**配对 A/B（合并 1024 局 + 面板分层 bootstrap + 逐面板 Δ） |
| `scripts/infer_search_formal_summary.py` | 正式/调参/消融汇总 → `runs/infer_search_formal/SUMMARY.json` |
| `scripts/infer_search_confirm_ab.py` | 单面板确认臂 vs 多面板正式臂的配对（按 seed_base 拼面板） |
| `runs/infer_search_formal/ckpt_{s14,s16,s16b}.pt` | 正式协议的三个冻结 checkpoint（sha256 `fffc395c` / `97631cfb` / `937d1783`） |
| `runs/infer_search_formal/human_{s14,s16,s16b}_{off,t1}.json` | **正式 512×2 面板**的 6 个负载（每臂 1024 局） |
| `runs/infer_search_formal/tune/s14_*.json` | 调参/消融 256 局单面板（`ref`/`w_any`/`w_spell`/`t1`/`t6`/`k16`/`h002`/`tier002`） |
| `runs/infer_search_formal/confirm/s14_t6_panel{A,B}.json` | t6 在正式封存面板上的确认跑 |
| `runs/infer_search_formal/ab_s14_{t6_confirm,off_vs_t6}.json` | t6 vs 默认 t1 / t6 vs off 的正式面板配对报告 |
| `runs/infer_search_formal/latency_solo_s14_t1.json` | s14 的 solo 单次延迟（p50 130 / p90 267 / max 291 ms） |
| `runs/infer_search_formal/SUMMARY.json` | 正式 + 调参 + 消融 + 排名的机器可读汇总 |
| `runs/infer_search_formal/concurrency_bench.json` | cuda:7 并发/吞吐基准（§7.5 的依据） |
