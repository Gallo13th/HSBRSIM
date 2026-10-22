# 价值网络训练方案（Phase1 已批准：只训 value head）

> 状态：**Phase0 完成，Phase1 训练已获用户批准**（2026-10-19）；数据由
> `scripts/collect_turn_search_selfplay.py` 采集，训练脚本 `scripts/train_value_head.py` 已准备；
> **最终动作仍由 pairwise 决定，value 只用于剪枝/加速**。
> 目标：用学习到的价值网络给候选状态排序/剪枝，减少 turn-search 的状态/战斗
> （不是替代 pairwise 最终选择）。

---

## 1. 目标与定位

### 1.1 要解决的问题

当前 turn-search（`hsbg/search/turn_search.py`）用**手工两两战斗胜率**给状态打分：

```
score(s) = mean_{t≠s} win_rate(s vs t)      # 引擎 simulate/run_combat，公共 seed
action_value(a) = max/mean score(reachable states after a)
```

优点：无训练、可解释、动作改变率 71–75%；缺点：
- 只反映“单场战斗强弱”，忽略经济/血量/成长/后续回合；
- 状态数/战斗数预算直接决定信号（states8→16 效应 +0.65→+1.43，但 20 局 CI 仍跨 0）；
- 两两比较是 O(K²) 战斗，成本随状态数平方增长；
- 不能表达 placement/名次/前四概率这类最终目标。

### 1.2 目标输出

给“当前回合候选状态”一个价值分：

- 主目标：**8 类 rank 分布**（名次 1..8）→ 期望名次 / placement utility；
- 可选：**top4 概率**（二分类）、scalar utility 回归；
- 用途：**只作枚举/候选排序与剪枝**（value_prune_pairwise 的 top-K 选择）；最终动作由
  finalists 的 pairwise 胜率决定；不直接作为最终分/叶评估替身；
- 输入：与策略相同的 `Observation` v2（不允许隐藏信息，见 §2.3）。

### 1.3 非目标（本轮）

- 不做决策策略端到端训练/PPO；
- 不改引擎/环境；
- 不直接把价值网络接入线上 live 采集；
- 不宣称“价值网一定让搜索超过 BC”——需要 §6 的搜索增益验证。

---

## 2. 数据

### 2.1 现有数据源（仓库实测）

| 数据 | 位置 | 规模/标签 | 状态可见性 | 备注 |
|---|---|---|---|---|
| **turn-search 自对弈（主）** | 拟新增：`scripts/collect_turn_search_selfplay.py`（见 §2.5） | 每局 125–160 完整 obs 样本 + env 终局 rank；states=8/12/16 | `Observation` v2 + action | 数据随价值头迭代而增强；20k≈134 局/2.9 CPU-h，50k≈334 局/7.3 CPU-h（详见 `docs/VALUE_DATA_AUDIT.md` §5） |
| BC 教师示范（**辅助/冷启动**） | `runs/bc_data/heuristic_320_official.pkl`（88 MB） | **320 局 / 30,300 样本**；`BCDataset.ranks` 有终局名次（1..8，-1=未知）；teacher 平均名次 4.28、胜率 13.1% | `Observation` v1（完整 obs，需 v1→v2 迁移） | **不再作主训练集**；只做 value head 初始化/BC 基线；`episode_ids` 可用于按局切分 |
| BC 训练报告 | `runs/bc/official_320/report.json`（~200 MB） | 含完整 samples/ranks；val action acc 85.6% | 同上 | 不建议训练时重复加载巨大 JSON，用 pkl |
| RL/BC 轨迹 JSONL | `runs/rl/heuristic_100.jsonl`（13.2 MB，100 局）、`scale_8w.jsonl`（19.9 MB，160 局）、`lead_heur_40.jsonl`（5.1 MB，40 局）、`bc_ckpt_16.jsonl`（1.7 MB，16 局） | 合计 **316 局 / ~38.5k step 行**；episode 行带 rank | step 行的 `obs` 是**摘要**（board/tavern 卡 id、size、gold/tier 等），不是完整实体 token/stats | 价值训练需重新从 env/replay 生成完整 Observation，或只用于辅助/审计 |
| 真实 HDT/Power.log | `runs/powerlog/Power.log`（10.2 MB）；`runs/diff_powerlog2/3*.json` 各 10 traces | 官方差分文档累计 **679 场真实 BG 战斗**；本地只保留部分 trace | 真实对局全信息（但需解析） | 主要价值在**战斗/伤害辅助标签**与引擎校准；终局名次需从日志/战绩补 |
| live 采集 | `runs/live/collect_fix3/records.jsonl`（2 局）、`runs/live/live_final/records.jsonl`（1 局） | records 含 placement、Power.log 路径；无逐决策完整 obs | 真实客户端 | 量很小；可先用 livebot 扩采，但需 Lead 允许操作游戏 |
| 引擎自博弈（拟新增） | 由 env + 策略生成 | 可按需生成任意规模，带 rank 标签 | `Observation` v2 | 训练价值网的最终主力；需注意与 BC 数据的分布偏移 |

> 数据审计时以**实际统计**为准（见 §2.4 / Phase0），本表是设计时的已知量。

### 2.2 标签

- **主标签**：每局终局名次 `rank ∈ {1..8}`（`BCDataset.ranks` / episode 行 `rank`）。
  - placement utility：`u = 1 - 2*(rank-1)/(N-1)`（与 env reward 一致）；
  - rank 分布 one-hot（8 类）；可做 label smoothing / 软标签。
- **辅助标签（可选）**：
  - top4 = rank ≤ 4（二分类，缓解 8 类稀疏）；
  - 本回合战斗胜负/伤害（来自 `last_combat` / 引擎 replay / Power.log）；
  - 每回合血量/护甲/场面变化（dense auxiliary）。
- **未知标签**：`rank=-1` 的样本必须 mask（不参与 value loss），只参与 policy/辅助。

### 2.3 可见性/泄漏约束

- 价值网输入严格使用 `Observation` v2：自己完整信息 + 上一场对手战团 + 大厅公开信息；
  **禁止**使用对手当前手牌/战团/隐藏饰品（与 ENV_SPEC §7 一致）。
- 真实日志数据若用全信息（HDT 内部）只能做**离线辅助标签/教师**，不能进部署输入；
  训练数据生成器必须在 obs 构建层过滤，审计时检查字段集合。
- 终局 rank 标签来自环境/真实结果，不能由输入 obs 直接反推（不存在“标签泄漏到输入”除外：
  lobby 的 `rank` 字段是当前排名，不是终局名次；审计需区分）。

### 2.4 数据审计计划（Phase0，0.5 天，无 GPU）

产出 `runs/value_data_audit.json` + 简短报告；检查项：

1. **规模/去重**：episodes、samples、每局步数分布；`episode_id` 唯一性；重复 obs 检测。
2. **标签完整性**：rank 分布（1..8）、`rank=-1` 比例、每局是否都有终局 rank；top4/utility 派生。
3. **切分泄漏**：按 `episode_id` 分 train/val/test（如 70/15/15），验证同一局不跨 split；
   统计每 split 的 rank 分布/英雄/对手策略。
4. **可见性**：检查 Observation 字段是否只含允许信息（无对手当前 hand/board/trinket）；
   JSONL 摘要数据不足以训练时标记“需重新生成完整 obs”。
5. **分布**：BC/teacher vs self-play vs 真实 live 的 turn/tier/alive/rank 分布差异；
   为后续 distribution shift 评估留基线。
6. **数据质量**：非法/截断局（truncated）、rank=0、缺失字段；按局剔除或 mask。
7. **可复现**：固定 split 文件（JSONL of episode_id）供所有 Phase 共用。

建议命令（Phase0 实现时写成 `scripts/audit_value_data.py`）：

```powershell
# BC pkl（按需，样本量小）
python - <<'PY'
from hsbg.train.bc import BCDataset
d = BCDataset.load("runs/bc_data/heuristic_320_official.pkl")
print(len(d), d.num_episodes())
# rank 分布、episode 步数、-1 比例
PY
# RL JSONL 统计
python scripts/audit_value_data.py --jsonl runs/rl/*.jsonl --live runs/live/*/records.jsonl
```

**Phase0 验收门槛（建议，可调；2026-10-19 用户调整后）**：
- **主数据改为 turn-search 自对弈**：首轮 ≥20k 带有效 rank 的**完整 obs** 样本（states=8，约 134 局）；
  Iter1 目标 50k（约 334 局）；数据 schema/成本见 §2.5 与 `docs/VALUE_DATA_AUDIT.md`；
- **BC 30,300 只作冷启动/辅助**，不再作为“主数据达标”依据；
- 每局都有 rank；`rank=-1` <5%；
- split 无同局泄漏；rank 1..8 均有样本（尾类 1/8 可少但 >100）；
- 可见性审计通过（无隐藏字段）；
- 审计报告+固定 split 文件产出后，才进入 Phase1。

---

### 2.5 turn-search 自对弈主数据（2026-10-19 用户调整）

> 详细审计/schema：`docs/VALUE_DATA_AUDIT.md`；机器可读：`runs/value_dataset_audit.json`。

**路线**：`turn-search 自对弈产数据 → 训 value → 更强 turn-search（value 做 prior/prune）→ 更多数据`；
BC 仅冷启动/基线，不作主训练集。

**schema**（训练最小集；推荐 pickle + `BCDataset` 兼容）：
- 文件头：`schema=hsbg.value_selfplay.v1`、`engine_data_patch`、`search_config`（states_budget/
  samples_per_action/combat_samples/completion_policy/state_scorer/prune_top_k/seed）、
  `policy{name,checkpoint}`、`opponent_pool`、`obs_version=2`、`seed_range`；
- 每步：`episode_id/step/turn/phase/action{index,signature,kind,n_candidates}/obs(完整 Observation v2)/
  reward/invalid/terminated/truncated`；
- 每局：`episode_id/seed/rank(终局 1..8)/turns/steps/reason/wall_s/search_stats`；
- 切分：`episode_id` 70/15/15；首轮 15% 局冻结为 golden test，后续迭代只增 train 局；
- 可见性：只存 `Observation`（自己 + 上场对手 + 大厅公开信息），禁止隐藏手牌/战团。

**成本（实测 `runs/search/turn_search_*.json`）**：

| states | 每局墙钟 | 每局决策 | 样本/局（假设） | 20k 需局数 | 20k 串行 CPU | 20k 8 进程 | 50k 需局数 | 50k 串行 CPU | 50k 8 进程 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 8 | 78.6 s | 153.5 | 150 | 134 | 2.9 h | 22–29 min | 334 | 7.3 h | 55–73 min |

> Phase1 实测（2026-10-20）：6 workers + 并发负载下 140 局/**21,240 samples** 用 **37.3 min**（>20k 目标；预估 22–29min 为独占 8 workers 理想值）。
| 12 | 144.3 s | 147.4 | 150 | 134 | 5.4 h | 40–54 min | 334 | 13.4 h | 100–134 min |
| 16 | 152.4 s | 117.0 | 125 | 160 | 6.8 h | 51–68 min | 400 | 16.9 h | 127–169 min |

> 口径：表头 20k/50k 指 **samples（step 样本）**，不是局数；对应局数见「需局数」列。
> 20k 局（states=8）≈ 436 CPU-h，勿混淆。

- Iter1 起用价值头 `value_prune_pairwise(K=4)`：T7 实测 **1.3–2.3×** 加速（combats 28/66/78 → 6），
  50k states=8 约 **3.5–5.5 CPU-h**（8 进程约 26–55 min），先 pilot 实测再承诺。
- 磁盘（env-builder 实测 obs 3.2 KB/step、0.35 MB/局）：**20k samples≈64–76 MB / 50k≈160–190 MB**（pkl；
  完整 obs 的 JSONL 2–4×）；注意 **20k samples ≠ 20k 局**（20k 局 states=8 ≈436 CPU-h）。
- clone v1 已生效（env-builder）：turn-search 决策约 68.6% 时间在 clone（T4/states=8：184.7/269 ms）；
  继续 p50 1.6→1.0 ms 约再省 10–15% 局时，但 value_prune 降本更大。

**采集实现（最小改动，不改 env/engine；env-builder 已核对 from_env 只读，见 `tests/test_search_env_readonly.py`）**：
1. 新增 `TurnSearchPolicy`（module-level、picklable；`requires_engine=True`、`bind_env(env)`；
   `act(obs)` = `EngineForwardModel.from_env(env, clone=False)` + `TurnSearch.decide` +
   按 `signature` 映射 `obs.candidates` 下标；失败回退 heuristic；用 `env.agent_hero` 公开接口）≈80–120 行；
   若走字符串名需在 `hsbg/rl/policies.py::make_policy` 注册 alias（~10 行，policy-builder scope）；
2. 新增 `scripts/collect_turn_search_selfplay.py`：复用 `hsbg.rl.api.run_episode`（其
   `EpisodeRecord.transitions` 已存完整 `obs` 与 `action`，`record.rank` 为终局名次）+
   `BCDataset.save` + 多进程分片 ≈150–200 行；**不必改 collector/bridge**（env 不参与 pickle，worker 内 make_env）；
3. env-builder 已确认：from_env 只读（`tests/test_search_env_readonly.py`）、`env.agent_hero`/`legal_actions`
   公开稳定（`tests/test_env_public_contract.py`，2 passed）、obs v2/extra 可 pickle（3.2KB/step）、
   多进程 spawn（policy 需 bind 前 picklable）、`ensure_picklable` 只查 policy；
4. 工作量：0.5–1 天 adapter+脚本+单测；0.5 天确定性/并行合并校验。

---

## 3. 架构

### 3.1 复用现有 encoder

- `EntityTransformerPolicy`（`hsbg/policy/model.py`，1.24M 参数；dim=128、layers=4、
  heads=4、ff=256、vocab=3840；`value_mode="distribution"`，8 类 rank logits）。
- `ObservationEncoder`（39 entity slots、entity_num_dim=56、global_dim=30、
  cand_num_dim=38、candidate_max=64）。
- 初始化：`runs/bc/official_320/policy_bc.pt`（自包含 config/词表）。

### 3.2 Value head 变体

| 变体 | 输出 | 用途 |
|---|---|---|
| A. rank 分布（现有 `rank_head`） | 8 logits → softmax | 主方案；E[rank]/utility/前四概率均可导出 |
| B. scalar utility（现有 `scalar_head` 可切换） | 1 个 tanh | 回归 `u∈[-1,1]`；简单但少分布信息 |
| C. rank 分布 + top4 二分类 + utility 回归 | 多头 | 推荐：主 CE + 辅助 top4/utility |
| D. 冻结 encoder + 新 head | 只训 head | Phase1 低成本、防过拟合 |
| E. 微调 encoder | 全部/后 N 层 | Phase2；需小 lr、早停 |

### 3.3 冻结策略

- **Phase1 冻结 encoder**，只训练 value head（随机初始化或复用现有 rank_head）；
  原因：30k 样本、8 类标签，全网络微调易过拟合；BC encoder 已含强状态表征。
- **Phase2 解冻**：后 1–2 层或全部，lr=1e-5~3e-5，冻结前若干 epoch，监控 val rank CE/MAE
  与 policy 输出是否漂移（若只做 value，策略 head 可冻结）。

---

## 4. 损失与训练

### 4.1 主损失

- **rank 分布 CE**：`CE(rank_logits, rank-1)`（mask rank=-1）；
- **utility 回归**：`MSE(value, u(rank))`（value 由 rank 分布 E[rank]→u 或单独 scalar）；
- **top4 二分类**：`BCE(top4_logit, rank≤4)`（辅助，权重小）；
- 标签平滑/软标签：可选 `ε=0.05`，或对相邻名次做 soft label（8 人局名次噪声）；
- 样本权重：按 episode 平衡（避免长局样本主导），可 `1/sqrt(episode_steps)`。

建议初值（待 Phase0/Phase1 调）：

```yaml
loss: rank_ce + 0.5*utility_mse + 0.2*top4_bce
label_smoothing: 0.05
optimizer: AdamW
lr: 3e-4 (head only) / 3e-5 (fine-tune)
weight_decay: 1e-4
batch_size: 512
epochs: 30–60 (head) / 5–15 (fine-tune)
early_stop: val rank_CE, patience 5
seed: 固定; 至少 3 seeds 报均值
```

### 4.2 校准

- 温度缩放（在 val 上拟合 T）用于 rank 分布/前四概率；
- isotonic 回归（可选，按 E[rank] 分桶）用于 utility 校准；
- 报告校准前后 ECE。

---

## 5. 评估

### 5.1 离线指标

| 指标 | 定义 | 建议门槛（Phase1 初版） |
|---|---|---|
| rank MAE | `|E[rank] - rank|` 均值 | ≤1.5（基线：常数预测均值约 2.0–2.5，需 Phase0 定） |
| rank RMSE | 同上平方根 | 记录，不单独设硬门槛 |
| rank CE | 8 类交叉熵 | 优于 uniform log8≈2.079，目标 ≤1.8 |
| top4 AUC/PR | 二分类 | AUC ≥0.65（初版） |
| ECE | 10-bin 校准误差（rank 分布/前四） | ≤0.08（温度缩放后） |
| 分桶 | 按 turn/tier/alive 分组 MAE | 记录，防止只拟合早期状态 |

### 5.2 搜索增益（Phase3，关键）

**边界（用户 2026-10-19 澄清）**：value 只用于枚举/候选的中间排序与**剪枝**（如
`value_prune_pairwise(K=4–6)`）；**最终动作必须由 finalists 的 pairwise 真实战斗胜率 argmax
决定**，value 分绝不直接作为最终分。

```
enumerate_turn_states → value_net(obs(state)) 只排序/剪枝 top-K
  → finalists 做 pairwise 战斗 → 最终 argmax(pairwise_scores)
```

对照：
- BC baseline（冻结策略）；
- turn-search 全 pairwise（states=8/12/16；历史 states12 3.65/70%/75%，n=20）；
- value_prune_pairwise(K=4) + final pairwise（同 states_budget）；
- 指标：mean rank/top4/win、动作改变率、ms/决策、combats/决策、与全 pairwise 动作一致率；
- 先用 5 局/cell pilot，方向性；若剪枝后动作一致率高、成本明显下降，再 states 32/20 局。

### 5.3 训练/验证切分

- **主数据（turn-search 自对弈）**按 `episode_id` 70/15/15；固定 split 文件
  `runs/value_split_selfplay.json`；首轮 15% 局冻结为 golden test，后续迭代只新增 train 局；
- 同一局所有 step 只进一个 split；**BC 只作冷启动**（沿用 `runs/value_split.json`，224/48/48 局），
  不与主数据混 split；真实 live 数据作为额外域外 test（不训练）；
- 报告 train/val/test 的 rank 分布与 calib，避免 val 过拟合；跨迭代沿用同一 test。

### 5.4 首轮 Phase1 结果（2026-10-20，20k）

- 训练：`scripts/train_value_head.py`，冻结 encoder，只训 rank_head；
  data `runs/value_data/turn_search_20k.pkl`（21,240/140 局），split 98/21/21；
  batch64/lr1e-3/30 epochs，**seed0 134s**，seed1/2 约 148–149s。
- 同一 val（3,365）：新头 MAE **1.276**、CE **2.346**、AUC **0.774**、ECE **0.011**；
  旧 BC head MAE 1.517、CE 4.229、AUC 0.760、ECE 0.194。
  test（2,894）：新头 MAE 1.352、CE 1.981、AUC 0.716、ECE 0.231；旧头 MAE 1.754、
  CE 4.213、AUC 0.746、ECE 0.329（test AUC 略低）。
- 剪枝质量（关键）：value 状态分 vs pairwise 状态分 **Spearman = -0.064**（n=243），
  远未达 >0.3；同状态动作一致率 K4 **75%**、K6 **100%**（20 decisions）。
- 5 局（seeds 300–304）：states8 pairwise 3.60 vs K4 4.00/K6 3.40；states12 pairwise
  2.20 vs K4 3.40/K6 3.80；剪枝 ms 降 1.2–1.8×、combats 降 ~40–75%，
  但名次/lift 不稳定，**不满足“剪枝后不掉点”的扩 states 条件**；不改用 value 直接选动作。
- 结论：训练本身成功（val 显著优于旧 value head），但 **value 排序与 pairwise 一致性差**，
  当前只适合作为加速/剪枝候选；下一步应先改善一致性（更多/更对路数据、pairwise 一致性目标、
  状态采样），再试 states16/24；不要扩 20 局。

### 5.5 目标修正：当前回合相对强度（2026-10-20）

终局 rank 目标与 turn-search 的“当前回合 pairwise 强度”错配（§5.4 Spearman -0.064），改为
离线 pairwise 胜率标签：

- `scripts/build_winrate_labels.py`：对每个有 board 的样本（20,749/21,240）重建我方 board，
  从同 `(turn,tier)` 其他样本采样 K=8 对照，`run_combat` 公共 seed，label=平均胜率（draw=0.5）；
  全量 **344.5s**，label mean 0.501/std 0.306。
- `scripts/train_value_winrate.py`：冻结 encoder，只训 `scalar_head`；目标 utility=2*winrate−1，
  MSE+BCE；30 epochs，seed0 **112s**（best epoch 13），seed1/2 ~112–114s。
- held-out：val Spearman **0.511**、MAE 0.225、AUC 0.741；test Spearman **0.512**、AUC 0.747；
  旧 BC value head 仅 val 0.361/test 0.386 → **达到 >0.3 的标签拟合目标**。
- 但本地 turn-search 状态上的 value vs pairwise Spearman 仍 **-0.007**（n=243）；K4/K6 动作
  一致率 85%/100%；5 局：states8 pairwise 4.20 vs K4 3.20/K6 5.60；states12 pairwise 2.20、
  K4 2.60、K6 3.40；剪枝 ms 降 ~1.8×、combats 47→5/13，但 states12 top4 80% vs 100%，
  **仍不算“不掉点”**。
- 结论：标签目标正确，但离线标签池与本地搜索状态/对手池分布不一致；下一步走 B 路线（采集时
  记录本地 pairwise 矩阵）或对齐状态采样，再训练/重试；不扩 states16/24/20 局。

### 5.6 B 路线：本地枚举状态 + pairwise 矩阵（2026-10-20）

- `TurnSearchConfig.record_trace=True`：记录每决策枚举 state 的 obs/board/score、完整 pairwise
  矩阵；`scripts/collect_localpair.py` 6 workers、150 episodes、每回合最多 1 决策、states8：
  **13,008 states**（7–8 states/决策），wall **2075s**；`runs/value_data/turn_search_localpair.pkl` + npz。
- 训练 `scripts/train_value_localpair.py`：冻结 encoder，只训 scalar_head（MSE/BCE）；
  split 150 episodes→70/15/15（9,146/1,926/1,936 states）；30 epochs，best epoch26。
- held-out **本地 pairwise Spearman：val 0.304 / test 0.224**（晚回合 6–12 仅 0.02–0.17；
  1–4 回合 0.4–0.7）；旧 BC value head val 0.080/test 0.057；ranking-loss 变体
  val .306/test .218，无提升。
- 动作一致率 states8：K4 90%、K6 95%；5 局：
  states8 pairwise 4.00/80% vs K4 6.40/0%、K6 4.40/60%；
  states12 pairwise 2.20/100% vs K4/K6 3.40/60%；ms 1.2–1.7×、combats 47→5/13，
  但 **rank/top4 明显掉点**，不满足“加速≥1.5× 且不掉点”。
- 结论：本地标签训练链路可用，但 value 仍不够；**不扩 states16/24/20 局**，后续需更强特征/
  晚回合训练/对手池，否则保留全 pairwise。

---

## 6. 算力与阶段

| Phase | 内容 | 数据/算力 | 时长 | 验收/退出 |
|---|---|---|---|---|
| **Phase0** | 数据审计：turn-search 自对弈 schema/成本、现有源盘点、split 设计 | 无 GPU；CPU/磁盘 | 0.5 天 | `runs/value_dataset_audit.json` + `docs/VALUE_DATA_AUDIT.md`；见 §2.4 门槛 |
| **Phase1** | 实现 turn-search 采集（`TurnSearchPolicy`+脚本）→ 生成 **20k**（states=8，134 局）→ 冻结 encoder 只训 value head（A/C 变体） | turn-search 20k：2.9 CPU-h（8 进程 22–29 min）；训练 RTX 4060 Ti 16GB | 1–1.5 天（采集主导） | val rank CE ≤1.8、MAE ≤1.5、top4 AUC ≥0.65、ECE ≤0.08；3 seeds |
| **Phase2** | 价值头接 `value_prune_pairwise(K=4)` → 生成 **50k**（states=8/12，334 局；约 3.5–10 CPU-h）→ 解冻 1–2 层微调 + 校准 | 自对弈 50k；训练 GPU | 1–2 天 | 相对 Phase1 MAE/CE 改善；策略 head 无退化；采集成本较 Iter0 降 1.3–2.3× |
| **Phase3** | 接入 turn-search 打分；5 局 pilot → 20 局 | 搜索评估（CPU） | 1–2 天 | 动作改变率、名次/top4 vs 手工/BC；不达标则回退 |

GPU 预算（4060 Ti 16GB）：
- Phase1：20k 自对弈样本 × 30–60 epoch，head-only，预计 **<15 min/seed**（BC 冷启动可更快）；
- Phase2：50k 样本 × 5–15 epoch，head-only/解冻，预计 **<1–2 h/seed**；
- Phase3：搜索 CPU 为主（value 前向 2–4 ms/状态，states 12 × ~150 决策 ≈ 数分钟/局）。
- 不启动 RL/PPO 训练；本计划只训 value head/微调。

---

## 7. 风险

| 风险 | 说明 | 缓解/判据 |
|---|---|---|
| 标签噪声/方差 | 8 人局名次受对手/RNG 影响大；同状态不同局名次不同 | 按局 split；分布损失+校准；报告 CI；不追求单点 MAE 过低 |
| 分布偏移 | BC/teacher 数据 vs 搜索自博弈/真实 live | 分域评估；Phase3 用搜索数据重测；必要时混自博弈数据 |
| 隐藏信息 | 对手当前战团/手牌不可见；价值网不能利用 | 输入仅 Observation v2；审计字段；真实日志全信息只作教师/辅助 |
| 过拟合同局样本 | 同局 step 高度相关 | 严格 episode-level split；dropout/weight decay；早停 |
| 标签泄漏 | lobby rank/当前排名不是终局名次；实时记录只有少量有 rank | 审计字段；只使用终局 rank；live 数据按局剔缺失 |
| 样本量/类别不均衡 | 冠军/前四少；rank 1/8 少 | top4 辅助、class weight、label smoothing；报告分桶 |
| 搜索评估误判 | 价值网打分好但名次不变 | Phase3 以固定 5/20 局配对；不达标即回退/继续手工 |
| 数据管线成本 | turn-search 采集 CPU 密集（states=8 ≈79 s/局；states=12/16 ≈144–152 s/局） | 8 进程并行；Iter1 起 value_prune 降 1.3–2.3×；按 §2.5 预算排期 |
| 主数据分布漂移 | 自对弈搜索越强，数据分布越偏离 BC/真实 | 固定 golden test（首轮 15% 局）；每轮记录 search_strength；真实 live 只做域外评估 |

---

## 8. 交付物与下一步

1. **本设计文档**（本文件）。
2. **Phase0 数据审计**：`docs/VALUE_DATA_AUDIT.md`（v2，turn-search 主路线）+ `runs/value_dataset_audit.json`。
3. 待用户批准后：
   - Phase0：实现 `TurnSearchPolicy` + `scripts/collect_turn_search_selfplay.py`；产 `runs/value/selfplay/iter0/`
     与固定 split（`runs/value_split_selfplay.json`）；
   - Phase1：`scripts/train_value_head.py`（冻结 encoder，只训 value）→ `runs/value/phase1/`；
   - Phase2/3：按 §5/§6 验收；
4. 本轮**不训练、不更新权重、不改 env/engine**；turn-search 代码/评估保留作为对照基础设施。

> 重要：价值网训练完成后仍需用 §5.2 的搜索增益实验验证“价值网打分是否让搜索超过 BC/手工
> turn-search”；离线 MAE/ECE 好不等于搜索收益。
