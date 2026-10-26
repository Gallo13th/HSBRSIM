# AlphaZero 风格不完全信息搜索：阶段报告

> 时间：2026-10-27 凌晨（截止 07:00 前）
> 范围：AutoTavern fork 的 Rust `hsbg_engine`（37.0.0.255130，245 动作）
> 目标：先确认「搜索能产出足够质量的对局」，再论证设计、做初期训练与 bench 验证。
> 结论先行：**搜索框架已可运行、信息隔离有强制不变量、在 bot 先验下达到引擎 bot 同档对局质量；学习型评估器尚未训成，纯观测搜索未超过 bot。** 这是阶段结论，不是最终强度结论。

---

## 1. 交付物

| 类型 | 路径 |
|---|---|
| 搜索原型 | `hsbg/az/`（`env_api.py` / `belief.py` / `puct.py` / `search.py` / `policy.py` / `toy_env.py` / `evaluate.py`） |
| 搜索设计 | `docs/AZ_IMPERFECT_SEARCH_DESIGN.md`（v0.1，14 节） |
| 搜索测试 | `tests/test_az_search.py` |
| 训练/评测脚手架 | `hsbg/az/train/**`、`scripts/az_selfplay_smoke.py`、`scripts/az_eval_search.py`、`tests/test_az_train.py` |
| Bench 调研 | `docs/AZ_BENCH_RESEARCH.md`（502 行，含 TavernBench 场景/标签/复现证据） |
| 实测报告 | `runs/az_eval/report.json`、`runs/az_eval/selfplay_smoke/report.json`、`runs/az_eval/selfplay_smoke_botprior/`、`runs/az_eval/bc100/`（部分在远程） |
| 上游设计 | `docs/AZ_MCTS_SELFPLAY_DESIGN.md`（已有 D1–D11/公式/训练闭环） |

---

## 2. 搜索：问题与设计

### 2.1 问题形式化

单座位视角是 POMDP：

- 状态 `s`：8 人完整状态（隐藏对手手牌/金币/商店/未公开战团）；
- 观测 `o = Z(s)`：`observe(seat)` 的 3227 floats + 124 cards（只公开信息）；
- 动作 245，`EndTurn=0` 是宏动作（推进 7 座 + 配对 + 战斗 RNG + 刷新 + 淘汰）；
- 回报仅终局名次 `u(r)=1-2(r-1)/7`；
- 决策目标 `π(a|h)`、`V(h)=E_{s~b(h)}V(s)`，输入只能是观测历史。

### 2.2 为什么选 PIMC / ISMCTS

文档 `AZ_IMPERFECT_SEARCH_DESIGN.md` 对比了 oracle MCTS、policy-only、CFR、PIMC、ISMCTS：

- 精确信息集求解在 8 人 × 245 动作 × 长局不可行；
- PIMC（determinization）可复用现有 Rust MCTS，工程成本最低；
- 本场景 7 个对手由 bot/league 推进，**learner 合法动作跨世界稳定**，PIMC 的 strategy fusion 偏差通常为常数级；
- 隐藏信息主要影响战斗/对手战团，对“买/打/升级”即时合法性影响小；
- 若后续跨世界 legal mask 不一致或 PIMC 高估明显，再升级 ISMCTS（单树/信息集节点/per-simulation 世界）。

### 2.3 PIMC 数据流

```text
game（真实状态，但决策只读 observe(seat)）
  → 从公开观测采样 W 个隐藏世界（determinization）
  → 每个世界跑一次 PUCT/MCTS（Rust mcts_search 或 Python PUCT 对照）
  → 根 visit 数跨世界聚合 → π
  → 采样/argmax + 根先验 tie-break → action
```

API：

```python
from hsbg.az import search, SearchConfig

res = search(
    game, seat,
    config=SearchConfig(
        simulations=16,
        determinizations=4,
        c_puct=1.5,
        temperature=1.0,
        dirichlet_alpha=0.3,
        dirichlet_epsilon=0.0,
        seed=0,
    ),
    eval_fn=None,          # 或 eval_fn(features,cards,mask,seat)->(pi[245],value)
    engine_backend="auto", # engine Game→rust，否则 python
)
res.pi, res.action, res.root_value, res.visits
res.n_simulations, res.determinizations, res.n_states, res.elapsed_s
res.per_world, res.fallback, res.info
```

### 2.4 隐藏信息 / determinization

默认 `EnginePublicPriorSampler`：

- 只用 `observe(seat)` 解出的公开信息；
- 对手战团以 `p_seen_board` 复用最近公开战团，再以 `p_mutate` 替换；
- 对手 tier/回合先验采样随从与数值；
- 用 `debug` 覆写对手 board/hand/shop/gold；
- **断言注入后 `observe(seat)` 逐字节不变**。

实测：

- 77 次注入后 `observe(0)` 字节不变，`obs_invariant=True`；
- 搜索前后源 `Game.state_json()` 字节相等；
- 每 world 注入约 1.1ms；16 sims/4 det 单决策 7–18ms（首调 catalog 解析约 50ms）。

已知残余泄漏（必须记录）：

- 引擎 `debug` 不能重置对手的任务/饰品/英雄技能使用次数等字段；
- 这些字段仍来自真实状态；
- 正式版需要引擎侧 `resample_hidden(seat, rng)`；当前只能作为原型限制。

Oracle `CloneSampler` 保留真实隐藏态，**只用于 oracle gap 诊断**，不进入训练/部署。

### 2.5 Chance / EndTurn

- Rust `mcts_search` 把 7 座 bot 推进 + 战斗/刷新 RNG 折叠在边内；
- 世界间差异来自 determinization，Rust 端不逐 EndTurn 重采样；
- Python 后端支持 `resample_on_end_turn`：EndTurn 后重新采样隐藏世界，作为 chance 节点对照；
- 文档明确两种后端差异，避免误读为“Rust 搜索无 chance”。

### 2.6 EndTurn 退化链（已修复）

观察到的“搜索总选 EndTurn”不是 chance/determinization 问题，而是三个叠加 bug：

1. `pending_kinds` one-hot 下标 0=`none` 被误判为“有待选” → 先验退化成合法动作均匀；
2. 买随从进 hand，必须 Play 才上棋盘；Play 权重 0.9 与 EndTurn 打平 → argmax 取小下标 EndTurn；
3. `temperature=0` 且低 sims 时 visit 打平，按小下标取到 EndTurn。

修复：

- `env_api`：`pending_kinds[1:]`；
- `policy.heuristic_prior`：有手牌时 Play=5.0、EndTurn=0.02；
- `search._finalize`：visit 打平时用根先验 tie-break；
- 回归测试 `test_engine_no_endturn_degeneracy_at_recruit_root`。

修复后引擎状态 root argmax 从 `EndTurn` 变为 `Buy/Play`。

---

## 3. 搜索质量实测

协议：seat0 = 被评策略，其余 7 座 = 引擎 bot；同 seed 配对；固定 seed 集；合法动作率/截断/耗时同时记录。

### 3.1 100 局主表（seed 90000–90099）

`runs/az_eval/report.json`：

| 策略 | mean_rank | top4 | win | legal | trunc | 时间 |
|---|---:|---:|---:|---:|---:|---:|
| random | 7.98 | 0% | 0% | 100% | 0 | 0.8s |
| engine bot | 4.75 | 44% | 11% | 100% | 0 | 0.8s |
| heuristic（obs-only） | 6.75 | 10% | 3% | 100% | 0 | 1.2s |
| **search_az + bot_prior (sims32/W2/τ0)** | **4.73** | **44%** | **12%** | **100%** | **0** | **474.7s** |

结论：**搜索框架 + 好先验可兑现 bot 级对局**；4.73 vs 4.75 差值在噪声内，不宣称超越 bot。

### 3.2 20 局对照（seed 70000–70019，search-architect）

| agent | mean rank | top4 |
|---|---:|---:|
| random | 8.00 | 0% |
| heuristic | 6.60 | 5% |
| bot | 2.65 | 90% |
| search_uniform (16/4) | 8.00 | 0% |
| search_heuristic (16/4) | 6.75 | 10% |
| **search_bot_prior (16/4)** | **2.80** | **85%** |

与 100 局主表趋势一致：bot prior 搜索 ≈ bot；纯观测搜索受叶评估器质量限制。

### 3.3 预算/确定性

- `sims16/W4`：约 7–18ms/决策（Rust，含 determinization）；
- `sims32/W2` Python backend：约 46s/20 局；
- 同 seed 完全可复现；π 合法、和=1；源状态不被修改；
- `W` 增大降低世界方差但每世界树变浅；总预算固定存在最优 W（文档 §4.3/§7）；
- 评测使用 `temperature=0`，训练数据使用 `temperature≈0.8–1.0` 探索。

---

## 4. 初期训练

### 4.1 模型/数据

`TinyAZNet`：输入 3227 features（无 cards embedding）→ 256 hidden → {245 policy, 8 rank value}；交叉熵 policy + rank CE；CPU。

数据：

- 8 座全 self-play（`BatchEnv(controlled=range(8))` 或 `Game` 逐座）；
- 轨迹 `(features, cards, mask, π, z)`；
- π 来自搜索（或 bot prior 诊断数据）；
- z 为终局名次 utility。

### 4.2 自对弈训练 smoke（4 局搜索 selfplay）

`runs/az_eval/selfplay_smoke/report.json`：

```text
samples=1652, games=4, seats=8, illegal=0, truncated=0
π entropy=0.426, rank 覆盖 1..8
train: 10297 samples, loss 2.12 -> 1.46, 3099 samples/s
value-rank corr=0.936
policy top-1 vs π=0.597
net search-off 20 局: rank 8.0 (bot 5.4)
```

### 4.3 Bot-prior 诊断 selfplay（2 局）

```text
samples=2057, games=2, illegal=0, truncated=0
rank_mean=3.72（8 座 self-play，非 vs bot）
π entropy=0.0068（近 one-hot，bot prior 诊断）
train loss 5.43 -> 3.27
value-rank corr=0.945
```

### 4.4 BC100 / net search A/B（task-4）

`runs/az_eval/bc100/`（`report.json` + `eval_supplement.log`；seed 80000–80019，20 局/项；search-on 10 局）：

训练：

```text
BC 冷启动：engine bot 全座位 100 局 = 107,134 样本 / 4.96s
bootstrap 10 epochs loss 2.58 -> 0.84
最终训练（bootstrap+1 局搜索 selfplay，100k 样本）10 epochs
  loss 0.478 -> 0.199（22,433 samples/s，48.6s）
supervised: value-rank corr 0.961, policy top-1 0.675
selfplay 数据：1 局 631 样本，illegal=0/trunc=0，π 熵 0.977，
  rank 覆盖 1..8（π argmax EndTurn 占 69%，net 先验偏 EndTurn）
```

评测：

| 策略 | mean_rank | top4 | win | legal | trunc | dec |
|---|---:|---:|---:|---:|---:|---:|
| engine bot | 5.40 | 45% | 0% | 100% | 0 | 2522 |
| heuristic | 6.90 | 10% | 0% | 100% | 0 | 1394 |
| random | 8.00 | 0% | 0% | 100% | 0 | 1797 |
| **net(search-off)** | **7.95** | 0% | 0% | 100% | 0 | **293** |
| net(search-on sims8) | 8.00（仅 1 局完成） | — | — | 100% | **9/10** | 2328 |
| net(search-on sims16) | 无有效 rank | — | — | — | **10/10** | 2468 |
| search_az+bot_prior（特权参照） | 5.40 | 45% | 0% | 100% | 0 | 2522 |

结论：**BC100 轻量 MLP 仍不能支撑纯观测搜索**；net 决策数仅 ~15/局（bot 126/局），过度偏好 EndTurn/无进展动作；search-on 在低 sims + 弱 net 先验下出现无进展循环/截断。当前瓶颈是**叶评估器质量 + 模型/特征容量**，不是训练管线或搜索树本身。
---

## 5. AutoTavern / TavernBench 数据

`docs/AZ_BENCH_RESEARCH.md` 已验证：

- `benchmarks/tavernbench`：960 任务 / 368 eval / 40 场景 / 8 类；
- eval states 288 行，280 条 `Game.from_json` 成功，8 条多候选状态；full 696/696；
- card_table 指纹 `0x9656b149b0ad6da7` 与本引擎 37.0.0 一致；
- 17 个可执行 A 场景（P/O/T/E3/D3/D5，144 eval / 432 full），标签是“对指定对手下一场胜率”的 argmax；
- 按 `options[i].ops`/`perms[i]` 复现：eval 104/104、full 312/312 top-1，0 非法动作，MAE ≤0.0057；
- B 类（B1–B6/R2）只做 value 校准；N/D 类只做长程排序；10 个规则场景是纯文本题，不能当动作标签；
- 可直接复用 vendored `tavernbench.engine`（`sys.modules["taverngym"]=hsbg_engine`），不需要重写；
- `run_tavernbench.py --check` 修复 Windows CRLF 后 **26/26 PASS**。

搜索质量与 bench 的关系：

- A 类标签是**单步 proxy**，不是整局 RL 回报；不能作为训练 reward；
- 已实测搜索目标错配：`turn_search` T2 8/8、T5 0/8；`mcts_search` rollout T2 7/8、T5 0/8；
- 因此本报告把 **TavernBench 用作静态决策/值校准 bench**，整局强度用固定 seed vs bot 的 100 局协议；
- Tier2（17 场景 × 搜索系统）尚未跑完，已在 `AZ_BENCH_RESEARCH.md` 给出可复现命令与验收线。

---

## 6. 关键结论

1. **搜索框架可用**：PIMC + PUCT 能运行、合法、非退化、可复现；信息隔离有强制不变量；在 bot 先验下达 bot 级对局（100 局 4.73 vs bot 4.75，top4/win 同档）。
2. **搜索质量的上限由叶评估器决定**：无学习价值时（uniform/heuristic）搜索退化到先验；要产生真正的搜索增益，必须有学习型 policy/value 或 pairwise 战斗叶值。
3. **训练闭环已搭好但模型太弱**：4 局/100 局 BC 的 TinyAZNet 能拟合 value（corr 0.94），但 policy 弱；net search-off 仍 rank≈8，search-on 退化/截断。
4. **EndTurn 退化已定位修复**；chance 不是主因，determinization 信息隔离已实测。
5. **bench 数据可用但用途要区分**：TavernBench A 类可做静态决策 sanity/value 校准；整局强度必须用自己的固定 seed 自对弈/对 bot 协议。

---

## 7. 限制与下一步

### 限制

- PIMC strategy fusion / 世界先验偏差；
- 残余隐藏泄漏（任务/饰品/技能次数）；
- Rust MCTS 不逐 EndTurn 重采样 chance；Python 对照成本高；
- 245 固定动作 vs 现有候选动作策略的 `CANDIDATE_MAX=64` 截断；
- MLP 无 cards embedding、容量小；BC100 仍弱；
- TavernBench A 类标签只是单步 proxy，Tier2 尚未全量跑。

### 下一步（按价值排序）

1. **价值函数增强**：pairwise combat 叶值 / 更强 BC（cards embedding、更多局）/ rank 分布头；
2. **纯观测 search vs bot A/B**：用同一 100 局协议验证搜索增益；
3. **TavernBench Tier2**：17 场景 × 3 个搜索系统，报 top1/regret/spearman/legal/sims-per-s；T5 目标错配单独解释；
4. **ISMCTS / Rust BeliefSampler**：解决跨世界 mask 合并与注入成本；
5. **规模评测**：500–1000 局 + bootstrap CI；
6. **训练闭环**：8 座全搜索自对弈（Phase A）→ league/历史回放，再进入 1 座学习 + 7 座历史对手。

---

## 8. 复现命令

```bash
cd ~/projects/HSBRSIM
export PYTHONPATH=$PWD:$PWD/rust/python

# 搜索 API 冒烟
python - <<'PY'
import hsbg_engine as E
from hsbg.az import search, SearchConfig
g = E.Game(0)
print(search(g, 0, config=SearchConfig(simulations=8, determinizations=2, seed=0)).action)
PY

# 100 局搜索质量（bot prior 诊断）
python scripts/az_eval_search.py --games 100 --seed 90000 \
  --policies random,bot,heuristic,search_az \
  --search-backend az --search-engine-backend python \
  --search-evaluator bot_prior --search-sims 32 --search-det 2 \
  --search-temperature 0 --out runs/az_eval/report_bot_prior_100.json

# 4 局搜索 selfplay + 初训
python scripts/az_selfplay_smoke.py --policy search_rust --games 4 \
  --search-sims 4 --bootstrap-games 8 --epochs 2 --eval-games 20 \
  --out runs/az_eval/selfplay_smoke

# TavernBench 完整性
python scripts/run_tavernbench.py --check
```

---

## 9. 证据边界

- 本报告明确区分：**搜索框架能力**（已验证）与**学习型搜索强度**（未达成）；
- bot_prior 使用 `game.bot_action`（特权），只证明框架可兑现强先验，**不是 AZ 训练输入**；
- 训练数据/报告均标注 `privileged_prior` / `az_training_input_ok=false`；
- 未运行的大规模实验不写成结果；Tier2 只给方案与已知反例。
