# 搜索标签 v2：rollout 叶值（回合末真实 Σ）+ 关键决策 + DAgger

> 任务：按 `docs/ECONOMY_SANDBOX.md` §10 的三条改进重做搜索标签，目标 gold10 下
> **t12 Σ p50 ≥ 900**（s14/起点 626 为参照）。本文件是 v2 的完整实验记录（实现 /
> 标签统计 / 在线搜索策略 / 离线 BC / 诊断 / 结论），日期 2026-11-01。
>
> 环境：`runs/az_entity_s16b/model.pt` 的快照
> `runs/search_labels_v2/s16b_snapshot.pt`（d_model 384 / 8 层），全程 `cuda:7`，
> 未触碰 cuda:3–6 的主训练。

## 结论先行

1. **三条改动都实现了、而且第一条把 v1 的病根修掉了**：叶值换成「候选动作后用当前
   策略 rollout 到本回合末」的**真实 Σ**（greedy rollout，引擎确定性 ⇒ 因果、
   可复现、无 winner's curse），不再是没训练过的 value 头。**单次搜索延迟 p50
   30.1 ms / p95 52.8 ms（目标 < 500 ms）**；300 局标签 739 s（2.47 s/局，16 局 lockstep）。
2. **搜索确实更优，但只优一点**：8989 个关键决策上，π_search 的 top-1 相对 π_base
   top-1 的**回合末 Σ 差 = 平均 +25.5（p50 +2，p90 +70，51.5% 为正）**；把「搜索找到的
   最好动作」都算上则平均 +28.8（p50 +7，64.4% 为正）。回合末 Σ 绝对值
   307 → 336（+9.4%）。
3. **在线用搜索策略（关键决策按 π_search 采样、其余按 π_base）96 局 gold10：
   t12 Σ p50 = 668 vs π_base 605.5（+10.3%），t15 941 vs 838（+12.3%）**。
   ⇒ **这就是 v2 标签能提供的上界**，离 900 差 26%（相对起点 626 也需要 +44%）。
4. **离线 BC 没达标，而且样本口径全部 ≤ 基线**：5 条臂 96 局 gold10（固定采样 RNG，
   与 s16b 成对）最好的是 `clip6+锚点` 的 **562（−3%）**；greedy 口径 +9%~+19%
   （与 v1 同一个 sign pattern：greedy 变好、sample 不涨）。**判据 900 未达。**
5. **3 回合叶值（`--rollout-turns 3`）实测（48 局）：t12 719.5（与 1 回合 718.5 相同），
   但 t15 从 896 拉到 1139（+27%）** ⇒ 深度买的是**后期复利**，不是 t12。
6. **结论：v2 值得作为「搜索信号源 / 推理期搜索」，但不值得作为 s17 的离线 BC 主路线**。
   t12 ≥ 900 这一轮的所有路线都够不到（BC ≤562、在线 1 回合 668、在线 3 回合 719）。

---

## 1. 实现（三条改动逐一落地）

| 任务要求 | 实现 | 文件 |
|---|---|---|
| 叶值 = 回合末真实 Σ（rollout） | `RolloutSearcher.search`：候选动作 `search_step` 后用 π_base `greedy/sample` rollout 到本回合末（`--rollout-turns 1`），叶值 `L(Σ_end)=log1p(Σ)/log1p(30000)`，可加 `--tier-bonus/--carrier-bonus`；**跨候选/跨局 lockstep 一次批量前向** | `hsbg/az/train/sandbox_rollout.py` |
| `--leaf-mode {rollout,value_head}` 默认 rollout | 默认 rollout；`value_head` 分支复用 v1 的 PUCT（需要 `--value-head` 拟合头） | `scripts/gen_search_labels_v2.py` |
| 只搜关键决策 | `--search-when {carrier_in_shop,carrier_in_hand,spell_in_hand,carrier_on_board,tier4plus,carrier_or_spell,any}`（默认 `carrier_or_spell` = 前三个的并），`--search-max-per-turn 3`；其余步直接用 π_base | 同上 + `sandbox_rollout.decision_tags` |
| DAgger 式标签 | **行为永远按 π_base 采样**（与搜索结果无关）；π_search 只当标签；每步记录 `obs / π_search top-k / π_base top-k / π_base top-1 / 搜索统计 / searched`；同时记录**每个候选的 σ_end** 供 Σ 差诊断 | 同上 |
| π 构造（v2 去掉探索预算） | 候选 = π_base 概率 top-8 的非 Move 合法动作（含 π_base top-1）；`V=Σp̃Q`，`A=Q−V`，`π ∝ p̃·exp(clip(A/τ,±adv_clip))`，`τ=q_temp_scale·std(Q)`（默认 1.0） | `sandbox_rollout.pi_from_q` |
| 离线重算 π（改 KL 预算不重跑搜索） | `scripts/relabel_search_v2.py`：用标签里存好的 `q/σ_end/pi_base_cands` 重算 π（`--adv-clip`） | 新文件 |

测试：`tests/test_sandbox_rollout.py`（8 项）——叶值 == 手动 greedy 滚到回合末的 Σ
（含 `turns=2`）、π 只落在合法非 Move 候选且和=1、确定性可复现、`base/best/σ_end`
对齐、`search_when` 每个原子标签与 `view(0)` 对账、每回合预算。
既有 `tests/test_sandbox_search.py` / `test_economy_sandbox.py` 全绿。

## 2. 300 局标签（主实验）

> **为什么主口径用 greedy rollout（而不是 sample）**：沙盒在给定动作序列下是确定性的，
> greedy rollout 的叶值就是「执行该候选后按 π_base greedy 打到回合末」的**精确 Σ**
> （因果、可复现）；sample rollout 的 Σ 含动作采样噪声，用它选出的 argmax 会带
> **winner's curse**（同一批采样既选动作又估价值，ΔΣ 被系统性高估）。24 局 pilot 里
> sample K=1/K=2/greedy 的在线 t12 是 727.5/574.5/668（24 局噪声 ±80，分不开），
> 所以主口径按「可测量性」选 greedy；`--rollout-mode sample --rollout-samples K`
> 是公共随机数（CRN）实现，留给「期望价值」口径的实验。

**配置**：`--games 300 --golds 10 --envs 16 --seed0 970000 --behavior pi_base
--leaf-mode rollout --rollout-mode greedy --rollout-turns 1 --topk 8
--search-when carrier_or_spell --search-max-per-turn 3 --q-temp-scale 1.0
--adv-clip 30 --latency-probe 8`
→ `data/search_labels_v2/sandbox_v2_g10.jsonl.gz`（300 局 / 81,039 步）。

### 2.1 覆盖率 / 延迟

| 项 | 值 |
|---|---|
| 局数 / 步数 / 搜索步 | 300 / 81,039 / **8,989（11.1%）** |
| 每局搜索次数 | mean **30.0**，p50 31，max 42（上限 45 = 3×15） |
| 单次搜索延迟（串行、batch=1，**任务口径**） | **p50 30.1 ms / p95 52.8 ms / max 53.2 ms** |
| 单次搜索延迟（16 局 lockstep 摊薄） | p50 62.4 ms / p95 181.7 ms |
| 每决策 rollout 步数（8 候选合计） | mean **113**（≈14 步/候选） |
| 标签生成墙钟 | 739 s（**2.47 s/局**） |
| 触发标签出现率（步级） | carrier_in_shop 11.0% / carrier_in_hand 15.8% / spell_in_hand 19.4% / tier≥4 74.9% |

### 2.2 KL / top-1 一致率（π 偏离先验的强度）

| 项 | 值 |
|---|---|
| KL(π_search‖π_base)（候选支撑上） | **p50 1.07**，mean 3.59（重尾：先验饱和的决策） |
| π top-1 vs π_base top-1 一致率 | **45.3%** |
| π 的 top-1 概率质量 | 0.83 |
| Q 的跨候选 std | 0.0068（L 单位） |

读法：v1 的 PUCT 默认探索预算把 KL 压到 0.011（≈自蒸馏、top1 一致 99.2%）；
v2 不用探索预算分配 π，直接用真实叶值 ⇒ **KL 大 100 倍、一半的关键决策换了 top-1**。
这是「信号真的进来了」，也是后面 BC 变差的来源（见 §4）。

### 2.3 搜索动作 vs 策略动作的回合末 Σ 差（核心诊断）

每个搜索决策都有每个候选的 `σ_end`（greedy rollout 的回合末真实 Σ，引擎确定性
⇒ 精确、因果）。`base` = π_base top-1，`best` = argmax Q，`π_top1` = π_search top-1
（它恒等于 base 或某个 Q 更高的动作，所以 Δ 不会为负）。

| 比较 | mean | p50 | p90 | frac > 0 | n |
|---|---:|---:|---:|---:|---:|
| **π_search top-1 − π_base top-1** | **+25.5** | **+2** | +70 | **51.5%** | 8989 |
| argmax Q − π_base top-1 | +28.8 | +7 | +79 | 64.4% | 8989 |
| L 差（argmax Q − base） | +0.0081 | — | — | — | 8989 |

回合末 Σ 绝对值：π_base top-1 的 p50 **307** → 最好动作 p50 **336（+9.4%）**。

**Δ 随回合增长**（Σ 越大、可改进空间越大）：

| 回合 | 1 | 4 | 7 | 10 | 12 | 15 |
|---|---:|---:|---:|---:|---:|---:|
| ΔΣ(π_top1−base) mean | +0.6 | +5.4 | +15.8 | +29.3 | +41.0 | +52.2 |
| frac > 0 | 16% | 58% | 54% | 55% | 51% | 48% |

换掉的 top-1 动作类型：sell 1589 / refresh 999 / buy 594 / choose 545 / play 339；
π_base top-1 类型：play 4475 / choose 1832 / buy 1334 / magnetize 473 / sell 439。

**结论**：搜索信号是**真的但很薄**——中位改进只有 +2 Σ，均值 +25 由长尾（大改进行为
sell/refresh 翻盘）贡献。1 回合 horizon 看不到「买载体→下回合复利」，这是 §5 的主要
证据。

### 2.4 行为轨迹（DAgger 用 π_base 采样，300 局）

t12 Σ p50 **619**、t15 859.5、tier p50 6 —— 与 docs 里 s14 的 626 同口径。
（BC 评测协议下 s16b 快照是 578.5，见 §4 —— 那条评测走 `torch.multinomial` + 全局固定 seed，和这里的逐决策 numpy RNG 不是同一条采样流，所以两个基线数不能混用。）

## 3. 在线搜索策略（v2 标签能达到的上界）

同一套搜索，但**行为**在关键决策按 π_search 采样（= 推理期搜索 + π_base 其余步），
96 局 gold10（同 seed 区 970000+，与 §2.4 前 96 局成对）：

| 口径 | π_base | **π_search（在线）** | 变化 |
|---|---:|---:|---:|
| **t12 Σ p50** | 605.5 | **668.0** | **+10.3%** |
| t15 Σ p50 | 838.0 | 941.0 | +12.3% |
| tier p50 | 6 | 5 | — |

⇒ **在线搜索是真的有用（+10%）**，但 668 就是这条 1 回合标签路线的天花板；
要达到 900 还差 35%。这也解释了 BC 的上限：即使完美模仿 π_search，也只能到 ~668。

## 4. 离线 BC（soft label，lr 3e-5 / batch 256 / 2 epoch，从 s16b 起）

评测：gold10、**96 局**、`torch.manual_seed(910000)` 固定采样 RNG，BC 与基线**同一条
采样流**（`scripts/train_search_bc.py` 的 `eval_sandbox`）。

| 臂 | 样本 | CE / top1（ep2） | **t12 sample** | t12 greedy | t15 sample | t15 greedy | tier(s) |
|---|---:|---|---:|---:|---:|---:|---:|
| baseline s16b | — | — | **578.5** | 567.5 | 860.0 | 775.0 | 6 |
| `clip30`（原始口径，只搜步） | 8,989 | 1.965 / 36.4% | 117.5 | 198.5 | 203.5 | 286.0 | 3 |
| `clip6`（只搜步） | 8,989 | 1.339 / 59.5% | 466.0 | 635.5 | 718.5 | 971.0 | 4 |
| `clip6` + 锚点（全部步） | 81,039 | 1.172 / 76.5% | **562.0** | 620.0 | 850.5 | 881.0 | 5 |
| `clip30` + 锚点 | 81,039 | 1.299 / 73.3% | 510.0 | **677.0** | 753.5 | 919.5 | 5 |
| `clip3` + 锚点 | 81,039 | 1.115 / 78.8% | 530.0 | 621.0 | 828.0 | 816.0 | 6 |

（`clipN` = `--adv-clip N`：π ∝ p̃·exp(clip(A/τ,±N))，N 越小标签越接近 π_base；
`+锚点` = `--only-searched 0 --base-fallback 1`，未搜索步用 π_base 当自蒸馏目标。
原始口径的 KL p50 1.07 → clip6 0.26 → clip3 0.07；top-1 一致率 45% → 66% → 83%。）

**判据：gold10 t12 Σ p50 ≥ 900 ⇒ 未达。** 最好的样本口径是 562（−3%），
而且**所有 5 条臂的样本口径都 ≤ 基线**；greedy 口径 +9%~+19%（`clip30+锚点` 677，
+19%），与 v1 的「greedy +15% / sample −13%」同一个 sign pattern。

**失败机理**（可定位的三层）：

1. **标签太尖、且集中在「卖/刷」类动作**：π top-1 质量 0.83、一半关键决策换 top-1，
   而被换掉的都是先验饱和（π_base≈1.0）的决策 ⇒ 只训搜索步时 CE 从 2.42 只降到 1.96、
   top1 只有 36%，模型没学会标签，却把 sell/refresh 的**全局动作先验**抬起来了 →
   样本口径崩到 117（tier 3、carrier_rate 0.14）。
2. **锚点能防崩、但抓不到搜索的收益**：把 81,039 步（含 89% 的 π_base 自蒸馏）一起训，
   CE 1.17 / top1 76.5%，策略不崩了，但样本 t12 只有 562（−3%）。搜索的 +10% 在线收益
   **没有被 BC 转成策略改进**——BC 学到的是「在关键决策上多做 sell/refresh」的粗粒度
   偏好，而不是「在这个局面下这一步更好」的细粒度条件（8.9k 个决策、245 维动作、
   2 epoch、lr 3e-5 的容量/分布都撑不住）。
3. **KL 预算与样本口径单调反向**：clip 越大，标签越接近搜索意图，greedy 越好；
   但样本口径反而更差（clip30+锚点 greedy 677 最好、sample 510 最差）。
   ⇒ 「把搜索标签学进去」在采样部署下是净负，这一点 v1 已经出现过、v2 换了真实叶值
   仍然复现。

## 5. 诊断：1 回合 horizon 够不够？（任务 step 4）

任务给的两条分支：若搜索更优但 BC 学不会 ⇒ 容量/分布问题；若搜索不更优 ⇒ rollout
叶值仍不够、需要 3 回合深度。本轮的测量是**两者都有**，但主因是后者：

- **搜索更优**：§2.3 的 +25.5 平均（p50 +2）、§3 的在线 +10.3%（668 vs 605.5）。
- **BC 学不会**：§4 的样本口径 −3%~−80%，锚点臂只到 562。
- **但提升的量级不够**：中位 ΔΣ 只有 +2，在线搜索的**上界**也只有 668。
  ⇒ 1 回合 horizon 的结构性缺陷（§2.3 的 Δ 随回合增长：t1 +0.6 → t15 +52）说明
  **真正的复利在后续回合**，叶值在「本回合末」截断就看不到「买载体 → 下回合施法」
  的收益，只能看到即时 Σ/载体动作。

### 5.1 3 回合深度实测（`--rollout-turns 3`，48 局，同 seed 区）

| 策略（48 局，seed 970000+） | t12 Σ p50 | t15 Σ p50 | tier p50 | 单次搜索延迟 p50 |
|---|---:|---:|---:|---:|
| π_base（DAgger 行为） | 616.0 | 868.5 | 6 | — |
| π_search，1 回合叶值 | 718.5 | 896.0 | 5 | 30 ms |
| **π_search，3 回合叶值** | **719.5** | **1139.0** | 5 | **167 ms** |

读法：**3 回合叶值几乎不动 t12（+1，噪声内），但把 t15 拉高 27%（896→1139）**——
深度买到的是**后期复利**，而不是 t12 这个中期快照。这也说明任务判据（t12 ≥ 900）
本身对「深度」不敏感：t12 的瓶颈更像「12 回合前的节奏/经济曲线」，不是「看不看得远」。
3 回合的单次搜索延迟 167 ms（<500 ms）仍然可接受，`--rollout-turns` 已支持到任意回合。

## 6. 迁移（完整游戏）——未触发

任务口径：**BC 达标（t12 ≥ 900）才跑** `quality_monitor --games 48`（1 席 p0.3 /
5 席 p0.9）。本轮未达标（562 / 510 / 530 / 466 / 117），故**没有跑迁移**；
按 v1 的经验（沙盒不涨 ⇒ 迁移不涨，§4 的 +3% 在噪声内），这一步跑也没有信息量。
如果只看 greedy 口径（677，+19%），也不能作为迁移依据——v1 的 greedy +15% 同样不可信。

## 7. 结论：v2 是否值得作为 s17 主路线？

**不值得作为「离线 BC」主路线；值得保留为「搜索信号源 / 推理期搜索」。**

- 三条改动本身都成立：真实叶值把 v1 的「value 头噪声 0.037 >> 动作效应 1e-3」问题解决
  了（现在是精确的因果量），延迟 30 ms/次，覆盖 11% 决策、每局 30 次，成本完全可接受。
- 但**1 回合 rollout + 离线 BC 这条组合**的上界是 668（+10%），BC 实际 562（−3%）：
  离线把「局面级搜索」压成「策略参数」时，信号被摊薄成「多做 sell/refresh」的粗偏好，
  样本部署下反而掉分。这与 v1 的结论同构，只是病根从「value 头」换成了「horizon」。
- 下一步（按优先级）：
  1. **推理期搜索**而不是 BC：在线 π_search 已经 +10%（668），如果只用于 t≥8 的关键
     决策，成本 ~30 ms×30 次/局，完整游戏里也放得下（比训练一个更差的策略更划算）。
     **3 回合叶值把 t15 拉到 +27%（1139 vs 896）、t12 不变**，所以深度是「后期复利」
     的答案，不是 t12 的答案。
  2. **`--rollout-turns 3`（已支持）**：想把 t15/后期强度当目标时用；对 t12 判据无效。
  3. 若仍要 BC：必须 **DAgger 锚点 + KL 信任域（clip 3–6）**（否则崩），并且把标签
     从「几乎 one-hot」软化到 top-1 质量 ≤0.6；同时把 sell/refresh 类动作的**槽位
     条件化**（当前动作头难分辨「卖哪一个」）。
  4. 判据校准：900 相对起点 626 需要 +44%，而 s14→s16 的整段完整游戏训练都只动 ±10%
     （band0 1 席 p0.3：s14 608 / s16 542，docs §9.7）；1 回合标签的上界是 668、3 回合
     是 719，都够不到 900。建议把「先到 750（+20%）」作为 s17 第一关，再谈 900。

## 8. 复现命令

```bash
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python

# 0) 快照 s16b（训练在跑，先固定一份）
cp runs/az_entity_s16b/model.pt runs/search_labels_v2/s16b_snapshot.pt

# 1) 300 局 gold10 标签（π_base 行为 + greedy rollout 叶值；739 s）
PYTHONPATH=rust/python:. $PY scripts/gen_search_labels_v2.py \
  --checkpoint runs/search_labels_v2/s16b_snapshot.pt --device cuda:7 \
  --games 300 --golds 10 --envs 16 --seed0 970000 --behavior pi_base \
  --leaf-mode rollout --rollout-mode greedy --rollout-turns 1 --topk 8 \
  --search-when carrier_or_spell --search-max-per-turn 3 \
  --q-temp-scale 1.0 --adv-clip 30 --latency-probe 8 \
  --out data/search_labels_v2/sandbox_v2_g10.jsonl.gz

# 2) 离线重算 π（KL 预算；不重跑搜索）
PYTHONPATH=rust/python:. $PY scripts/relabel_search_v2.py \
  --in data/search_labels_v2/sandbox_v2_g10.jsonl.gz \
  --out data/search_labels_v2/sandbox_v2_g10_clip6.jsonl.gz --adv-clip 6

# 3) BC + 96 局 gold10 评测（sample + greedy，固定 RNG，与 s16b 成对）
PYTHONPATH=rust/python:. $PY scripts/train_search_bc.py \
  --labels data/search_labels_v2/sandbox_v2_g10_clip6.jsonl.gz \
  --checkpoint runs/search_labels_v2/s16b_snapshot.pt --device cuda:7 \
  --epochs 2 --lr 3e-5 --batch 256 --only-searched 0 --base-fallback 1 \
  --out runs/search_bc_v2/bc_v2_clip6_anchor.pt \
  --eval-games 96 --eval-gold 10 --eval-seed 910000 \
  --baseline runs/search_labels_v2/s16b_snapshot.pt \
  --json-out runs/search_bc_v2/eval96_clip6_anchor.json

# 4) 在线搜索策略（上界）：关键决策按 π_search 采样
PYTHONPATH=rust/python:. $PY scripts/gen_search_labels_v2.py \
  --checkpoint runs/search_labels_v2/s16b_snapshot.pt --device cuda:7 \
  --games 96 --envs 16 --seed0 970000 --behavior pi_search \
  --rollout-mode greedy --rollout-turns 1 --search-when carrier_or_spell \
  --search-max-per-turn 3 --out data/search_labels_v2/online_pisearch_g10.jsonl.gz

# 5) 3 回合叶值（t15 诊断；48 局，~6 min）
PYTHONPATH=rust/python:. $PY scripts/gen_search_labels_v2.py \
  --checkpoint runs/search_labels_v2/s16b_snapshot.pt --device cuda:7 \
  --games 48 --envs 16 --seed0 970000 --behavior pi_search --rollout-mode greedy \
  --rollout-turns 3 --rollout-max-steps 320 --search-when carrier_or_spell \
  --search-max-per-turn 3 --out data/search_labels_v2/online_pisearch_t3_g10.jsonl.gz
```

## 9. 文件清单

| 文件 | 作用 |
|---|---|
| `hsbg/az/train/sandbox_rollout.py` | rollout 叶评估搜索（叶值/候选/π/关键决策） |
| `scripts/gen_search_labels_v2.py` | v2 标签生成（DAgger 行为 + 搜索统计 + Σ 差） |
| `scripts/relabel_search_v2.py` | 离线重算 π（改 `--adv-clip` / 温度，不重跑搜索） |
| `tests/test_sandbox_rollout.py` | 8 项契约（叶值==真实回合末 Σ、π 合法性、search_when） |
| `data/search_labels_v2/sandbox_v2_g10.jsonl.gz` | 300 局标签（8,989 搜索步） |
| `data/search_labels_v2/online_pisearch_g10.jsonl.gz` | 在线 π_search 96 局（上界） |
| `runs/search_bc_v2/ARMS.json` / `eval96_*.json` | 5 条 BC 臂的 96 局评测 |
| `data/search_labels_v2/online_pisearch_t3_g10.jsonl.gz` | 3 回合叶值在线 48 局（t15 +27%） |
| `runs/search_labels_v2/s16b_snapshot.pt` | 本轮固定的起点权重 |
