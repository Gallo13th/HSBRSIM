# 价值网 Phase0 数据审计（v2：turn-search 自对弈主路线）

> 状态：**只读审计，不训练、不改数据/引擎、不更新权重**。
> 2026-10-19 用户调整：**BC 主数据强度不够**，价值网数据改为 **turn-search 自对弈生成**，迭代：
> `turn-search 产数据 → 训 value → 更强 turn-search → 更多数据`。
> 本版替换 2026-10-19T22:57 的 v1 审计（v1 以 BC 为主，现改为冷启动/辅助）。
>
> 机器可读：`runs/value_dataset_audit.json` ｜ 设计文档：`docs/VALUE_NETWORK_PLAN.md` §2
> 证据：`tmp_255130/value_data_probe.json`、`turn_search_bench.json`、`turn_search_scorer_bench.json`、
> `runs/search/turn_search_*.json`

---

## 1. 结论摘要

| 问题 | 结论 |
|---|---|
| BC 320 局 / 30,300 样本还能用吗？ | **能，但只作冷启动/辅助**：rank 标签 100%、完整 Observation，可做 value head 初始化与 BC 基线；teacher 偏弱（mean rank≈4.28）、分布偏 1/2，**不作主训练集** |
| 现有 RL JSONL 能直接训 value 吗？ | **不能**：`obs` 只是 `obs_summary`（board/hand/tavern 的 card id + 标量），缺完整 token/数值/candidates；只作辅助（可用同 seed/policy 重放 env 重建，但有版本漂移） |
| 真实轨迹/HDT 能提供 placement 主标签吗？ | **不能**：`runs/official_traces` 是 **679 条战斗 trace / 24 局**（不是 679 局），只有每场战斗 `official_result`，无终局名次；Power.log 6 文件 10 局也无 placement tag；HDT/BgsLastGames 导出在本仓库**不存在** |
| 主数据方案 | **turn-search 自对弈**：每局保存完整 `Observation` v2 + action + turn + 最终 `rank`；schema 见 §4；采集成本见 §5 |
| 现在能开训吗？ | **不能直接开**：需先实现 `TurnSearchPolicy` + 采集脚本（§7，最小改动 0.5–1 天）；然后 Iter0 用 states=8 生成 20k 样本 |
| 20k / 50k 需要多少局/时间？ | states=8：**134 局 ≈ 2.9 CPU-h**（20k）/ **334 局 ≈ 7.3 CPU-h**（50k）；8 进程并行约 **22–29 min / 55–73 min**。states=12/16 约 1.8–2.3×；价值头 value-prune 后 Iter1 可再省 **1.3–2.3×**（实测，见 §5） |

---

## 2. 数据源盘点（实测）

| 源 | 规模（episodes/samples） | 终局 placement 标签 | 观测形态 | 同局分组 | 可直接做 value 训练？ |
|---|---|---|---|---|---|
| BC `heuristic_320_official.pkl` | **320 局 / 30,300 样本** | ✅ 每样本 rank 1..8（覆盖率 100%） | ✅ 完整 `Observation` v1（pickle） | `episode_ids` | **仅冷启动/辅助**（用户口径） |
| BC `heuristic_240.pkl` | 240 局 / 22,869 样本 | ✅ 100% | ✅ 完整 v1 | `episode_ids` | 辅助（未发现与 320 重复） |
| BC smoke 4 个 pkl | 8/4/7/7 局，878/317/858/1350 样本 | ✅（最后两个含 rank=-1） | ✅ v1 | `episode_ids` | 否（冒烟） |
| RL JSONL（`runs/rl/*.jsonl`） | **369 局 / 44,001 step 行** | ✅ episode 行 rank；step 需 join | ❌ `obs_summary`（摘要） | `episode_id` | 否（需重放/重采集） |
| PPO runs（3 个） | 564/769/851 episodes_finished（训练期） | 只有 eval mean rank | ❌ 无 obs 数据集 | — | 否 |
| `runs/official_traces`（HDT BobsBuddy） | **679 战斗 trace / 24 局** | ❌ 只有 `official_result`（win/loss/tie） | ❌ 战斗态（无 recruit 全状态） | `episode_id`（24 局） | 否（战斗辅助/校准） |
| 其他 traces 目录（hdt/powerlog/probe） | 约 785 traces，含重复/探测 | ❌ | ❌ | `episode_id` | 否（校准） |
| Power.log（6 文件） | **10 局**（无 placement tag） | ❌ | 仅可解析战斗 trace | 每文件 1–3 局 | 否（战斗/校准） |
| live records（`runs/live/*/records.jsonl`） | 16 条记录（8 真/8 dry-run），**4 条真实有 placement** | ⚠️ 部分 | ❌ 无逐决策 obs | `session_id`/`game_no` | 否（域外评估） |
| HDT/BgsLastGames | **0（仓库无实际导出）** | ❌ | — | — | 否（缺口） |
| `runs/state_corpus/states.jsonl` | 746 状态 | ❌ | 战斗边界态 | `trace_id` | 否（差分/校准） |
| `runs/search/turn_search_*.json` | 20+20+5 局评测 | ✅ 每局 rank | ❌ 未保存逐决策 obs | seed | 否（成本标定） |
| **turn-search 自对弈（拟新增）** | **按需生成（100–200 样本/局）** | ✅ env 终局 rank | ✅ `Observation` v2 + action | `episode_id` | ✅ **主训练集** |

> 关键修正：用户口径里的「真实轨迹 679 场」实际是 **679 条 combat trace，跨 24 局**（`runs/official_traces`；
> 同局多战斗）。`official_traces_hdt` 677 条/23 局是同一批日志的 HDT 版本（重复覆盖），
> `hdt2/hdt3/hdt_probe` 为补充探测（10/20/15 条）。
> 「26 场真实 Power.log」在仓库中实测为 **6 个 Power.log、10 局 BG**（`runs/powerlog*` 3 局 +
> `runs/live` 3 文件 7 局；其中 8 局已能解析出 powerlog trace）。

---

## 3. 现有数据细审

### 3.1 BC 数据（冷启动/辅助）

- `runs/bc_data/heuristic_320_official.pkl`：**320 局 / 30,300 样本**，`BCDataset.ranks` 100% 覆盖
  （`-1` 为 0），rank 分布：
  ```text
  {"1":5823,"2":5592,"3":5025,"4":3160,"5":4179,"6":2817,"7":2759,"8":945}
  ```
  每局步数 mean **94.7** / 中位 91 / p90 141 / max 244；turn 1–20；phase recruit 27,241 / choice 3,059。
- `runs/bc_data/heuristic_240.pkl`：240 局 / 22,869 样本；rank 100%；与 320 **不是同一批局**
  （首步 obs/rank/prefix 均不同）→ 可合并为冷启动，但同样只作辅助。
- smoke 集（878/317/858/1350 样本）含 rank=-1 或异常 freeze 计数，只冒烟用。
- **观测版本兼容性（重要）**：BC pkl 里 `Observation.version=1`，当前 `hsbg/env/spec.py` 是 **v2**
  （新增 `extra`）。实测：
  - `ObservationEncoder.encode(obs)` **可以正常编码**（encoder 不读 `extra`）；
  - 但旧 pickle 反序列化出的对象**没有 `extra` 属性**：`obs.get_extra()` / `repr(obs)` 会 `AttributeError`；
  - 若训练/loss/分析代码访问 `extra`，需迁移：`dataclasses.replace(obs, extra={})`（或 `setattr(obs,"extra",{})`）。
  - 训练侧 `BCDataset.encoded()` 只读 `ranks`/`candidates`，当前可跑；建议采集脚本统一写 v2 并在加载时校验版本。
- `runs/bc/official_320/report.json` **210 MB**（把 dataset repr 写进了 report），训练时不要加载它，用 pkl。
- **定位**：只做 value head 初始化/BC 基线/冷启动；不进入主训练 split。

### 3.2 RL JSONL（辅助）

- 7 个文件，**369 局 / 44,001 step 行**；`episode` 行均带 rank（覆盖率 100%），`step` 行有当前 rank/reward。
- **`step.obs` 只是 `obs_summary`**：`turn/phase/gold/tier/health/armor/rank/alive/total/board_size/...`
  + `board/hand/tavern` 的 card id 列表；没有实体数值、keywords、hero、candidates、extra。
  见 `hsbg/rl/api.py::obs_summary`（359 行）与 `Transition.to_dict`（164 行）。
- 策略分布：heuristic 6 个文件、BC checkpoint 1 个（`bc_ckpt_16.jsonl`）；
  每局 wall 192–1205 ms（仅模拟器）。
- **可重放性**：理论可用同 seed + 同 policy 重放 env 重建完整 obs（确定性环境），但当前 env 已升 v2
  （额外 extra/规则变化），重放可能与旧 obs 不完全一致；只作辅助，不作主数据。

### 3.3 PPO / 评测轨迹

- `runs/ppo/official_bcinit_60k`（60k steps / 564 eps）、`official_v2`（200k / 769）、`official_v3`（120k / 851）；
  只有 `train_log.csv`/`eval_log.csv`/`summary.json`（eval mean rank/win）。
- 训练 rollout 的 obs 未持久化 → **不能**作为 value 数据集；仅作基线/评测。

### 3.4 真实对局轨迹（679 combat traces / 24 局）

- `runs/official_traces`：`OfficialCombatTrace v1`，字段：`episode_id/combat_index/turn/player/opponent/
  events/official_result/official_lethal/official_damage/bb_rates/heroes`；**无 placement/最终名次**。
- 结果分布：win 271 / loss 195 / tie 58 / None 155（155 条无结果）；turn 1–18。
- 用途：战斗弱标签（combat value/伤害）、引擎校准、真实分布评估；**不能**做 placement value 主标签。
- 其他目录（`official_traces_hdt*`、`official_traces_powerlog*`、`official_traces_live*`）为同批/探测复跑，
  存在重复 episode，不要当独立样本计入规模。

### 3.5 Power.log（6 文件 / 10 局）

- 文件：`runs/powerlog`（1 局）、`runs/powerlog_2214`（1）、`runs/powerlog_2240`（1）、
  `runs/live/collect_fix3_logs`（2）、`fix3_real`（2）、`live_final_powerlog`（3）。
- **口径说明**：需求里的「26 场真实 Power.log」在本仓库实测为 **6 个 Power.log、10 局**；
  若另有 26 场未落盘/在其他机器，请 Lead 给出路径后再补审。`runs/official_traces` 的 679 也不是 679 局，
  而是 **679 条 combat trace / 24 局**（见 §3.4）。
- **原始 Power.log 无 `PLAYER_RANK`/结算名次/BACON 终局 tag**；只能解析战斗事件（8 局解析出 powerlog traces）。
- recruit 期完整观测（shop/hand/gold/hero choices）**不能仅由 Power.log 重建**（需要 HDT 插件/live memory）；
  因此不能作为 value 训练主源。
- 另：`reversed/powerlog_corpus.md` 记录 HDT Replays 1365 个 replay，**0 个 BG 局**（全构造 2 人），该语料不可用。

### 3.6 live 采集（小样本）

- 16 条 records：8 条真实（非 dry-run/blind），其中 **4 条有 placement**（2/3/6/7/8 等，dist: 2×3、3×2、6/7/8 各 1）；
  真实局 duration 84–2400s（1 局 2400s 超时），turns 0–18，actions 0–217。
- records 有 placement、Power.log 路径，但**没有逐决策 Observation**；`runs/live/state_stream.jsonl` 是
  attach/内存探针（822 行 `hsbg.live_state.v1`），不是对局状态序列。
- 用途：域外评估（4 局）；若需更多真实数据必须扩采集（同时有账号/合规风险，需 Lead 批准）。

### 3.7 HDT / BgsLastGames（缺口）

- 仓库只有 `hdt_types_raw`、HDT 相关文档/脚本，以及 2 份 BobsBuddy 文本日志（`runs/hdt_logs_2214/2240`）；
  **没有 BgsLastGames 的实际导出**（终局名次/最终战团）。
- 若后续接入 HDT 插件：BgsLastGames 可补「终局名次 + 最终战团」，但**仍不含逐回合完整 obs**；
  价值网主数据仍应来自自对弈/环境采集。

### 3.8 其他

- `runs/state_corpus/states.jsonl`：746 个战斗边界状态（无 recruit obs、无 rank）→ 只做引擎/战斗校准。
- `runs/search/*`：turn-search 评测（states=8 20 局、states=12 20 局、states=16 5 局），只有结果行，
  没保存逐决策 obs → 不能直接当训练数据；但提供了**每局真实耗时**（见 §5）。

---

## 4. turn-search 自对弈数据 schema（主训练集）

### 4.1 必备字段

```jsonc
// 文件头（JSONL 第 1 行；pkl 则放 meta）
{"type":"header","schema":"hsbg.value_selfplay.v1","created_at":"...",
 "engine_data_patch":"37.0.0.255130",
 "search":{"states_budget":8,"samples_per_action":1,"combat_samples":1,
           "completion_policy":"heuristic","state_scorer":"pairwise",
           "prune_top_k":4,"seed":123},
 "policy":{"name":"TurnSearchPolicy","checkpoint":null},
 "opponent_pool":["heuristic"],"num_players":8,"obs_version":2,
 "seed_range":[0,134]}

// 每局一条（episode 结束、rank 已知后写）
{"type":"episode","episode_id":0,"seed":0,"rank":3,"turns":12,"steps":132,
 "terminated":true,"truncated":false,"reason":"eliminated",
 "total_reward":-0.42,"wall_s":81.2,
 "search_stats":{"decisions":128,"mean_decision_ms":510.2,
                  "mean_states":8.0,"mean_combats":28.0}}

// 每步一条（value 训练直接消费）
{"type":"step","episode_id":0,"step":17,"turn":4,"phase":"recruit",
 "action":{"index":3,"signature":["buy","tavern",1,"",-1,-1,-1],
           "kind":"buy","n_candidates":11},
 "reward":0.0,"terminated":false,"truncated":false,"invalid":false,
 "obs":{ /* 完整 Observation v2：version=2、hero、board/hand/tavern/trinkets、
           opponent_board、lobby、alive_count、rank、pending_choice、candidates、
           extra、log；全部 token 的 card_id/atk/health/tier/cost/races/keywords/golden 等 */ }}
```

- **训练最小集**：`obs`（完整）、`action`、`episode_id`、`rank`（每局终局名次）。
- `obs.turn` 即权威 turn；`obs.rank` 是**当前名次**，不是标签；**标签只用 episode.rank**。
- **推荐物理格式**：`pickle`（与 `BCDataset` 兼容：`samples=[(Observation, action_idx)]`、
  `ranks=[终局 rank / 样本]`、`episode_ids=[...]`、`meta={search_config,...}`）——
  体积小（BC 实测 2.9 KB/样本；v2 略大，20k≈60 MB、50k≈150 MB），训练加载快；
  JSONL 仅作抽查/跨语言预览（完整 obs 的 JSONL 会大 2–4×）。
- **可见性**：只存 `Observation`（自己完整信息 + 上场对手战团 + 大厅公开信息）；禁止存对手当前手牌/战团/
  隐藏饰品；真实日志全信息只能做教师/校准，不进部署输入（见 `docs/ENV_SPEC.md` §7）。
- **切分键**：`episode_id`；同一局所有 step 只进一个 split。

### 4.2 与现有 BC 格式的差异

| 项 | BC pkl（现有） | turn-search 自对弈（新） |
|---|---|---|
| `obs.version` | 1 | **2**（含 `extra`） |
| 动作 | 教师动作下标 | **turn-search 搜索后执行的动作下标** |
| rank | 教师局终局 rank | env 终局 rank（同） |
| meta | teacher/opponent/seed/script | **search_config/policy/engine patch/golden split** |
| 来源 | heuristic 自博弈（teacher 弱） | **turn-search 自博弈（更强，分布随搜索演化）** |

---

## 5. turn-search 采集成本（实测 + 估算）

### 5.1 实测每局耗时（`runs/search/turn_search_*.json`）

| states | 每局墙钟 mean | 范围 | 局数 | 每局决策数（搜索） | 来源/并行 |
|---:|---:|---|---:|---:|---|
| **8** | **78.6 s** | 31.6–124.2 s | 20 | 153.5 | `turn_search_confirm20.json`，2 进程×10 局 |
| **12** | **144.3 s** | 128.0–235.2 s | 20 | 147.4 | `turn_search_confirm20_s12.json`，4 进程×5 局 |
| **16** | **152.4 s** | 86.1–227.5 s | 5 | 117.0 | `turn_search_pilot.json`，pilot（样本少） |

> 这些是**实际墙钟**（搜索 + env step），含 2–4 进程并行；单进程/低负载可能略快。
> 与用户口径「states=8 每局 31–152 s」一致（我们的范围 31.6–124.2，pilot s16 到 227.5）。

### 5.2 单决策微基准（本机，T4/T7 快照；`tmp_255130/turn_search_bench.json`）

| states | T4 单决策 | T7 单决策 | 状态数/combats（T7） |
|---:|---|---|---|
| 8 | 180–197 ms | 380–507 ms | 8 / 28 |
| 12 | 457–479 ms | 766–890 ms | 12 / 66 |
| 16 | 502–639 ms | 984–1009 ms | 13 / 78（可用状态被 candidates 限制） |

### 5.3 价值头加速（Iter1 起；`tmp_255130/turn_search_scorer_bench.json`，T7 单次）

| states | pairwise 单决策 | value_prune_pairwise(K=4) | 加速 | combats 降为 |
|---:|---:|---:|---:|---:|
| 8 | 355 ms | **273 ms** | 1.3× | 28→6 |
| 12 | 762 ms | **407 ms** | 1.9× | 66→6 |
| 16 | 913 ms | **526 ms** | 1.7× | 78→6 |

> 价值头先用 BC checkpoint 冷启动；完整训练后预计再改善。该模式只 pruning，最终选择仍 pairwise（避免价值头直接决定）。

### 5.4 样本/局 与 20k/50k 所需规模

> **口径（env-builder 提醒）**：本文所有「20k/50k」均指 **samples（step 数）**，不是局数；
> 「20k 局」按 states=8 约 **436 CPU-h**（≈20k×78.6s），差异巨大。写排期/报告时必须带单位。

采集中**每个 env step 都是样本**（含 choice）：实测搜索决策 153.5/147.4/117.0，加 choice step 约 10%；
保守按 **150/150/125 样本/局** 做预算（真实应在此之上，故局数偏保守）。

| 预算（samples） | states | 样本/局（假设） | 需要局数 | CPU 小时（串行） | 8 进程理想墙钟 | 8 进程现实（效率 0.75） | 单样本 CPU |
|---:|---:|---:|---:|---:|---:|---:|---:|
| **20k** | 8 | 150 | **134** | **2.9 h** | **22 min** | **29 min** | 0.52 s |
| 20k | 12 | 150 | 134 | 5.4 h | 40 min | 54 min | 0.96 s |
| 20k | 16 | 125 | 160 | 6.8 h | 51 min | 68 min | 1.22 s |
| **50k** | 8 | 150 | **334** | **7.3 h** | **55 min** | **73 min** | 0.52 s |
| 50k | 12 | 150 | 334 | 13.4 h | 100 min | 134 min | 0.96 s |
| 50k | 16 | 125 | 400 | 16.9 h | 127 min | 169 min | 1.22 s |

- Iter1 用 value_prune_pairwise 后，按 T7 加速 1.3–2.3× 估算：50k states=8 约 **3.5–5.5 CPU-h**
  （8 进程约 26–55 min），states=12 约 6–10 CPU-h；**先跑 pilot 实测再承诺**。
- **磁盘（env-builder 实测 obs 3.2 KB/step、全量轨迹 0.35 MB/局）**：20k samples ≈ **64–76 MB**、
  50k≈ **160–190 MB**（pkl）；JSONL 版 2–4×。20k **局** 则约 1.1 GB（不推荐按局囤）。
- 并行：12 逻辑核/32 GB；搜索 1 进程/核，建议 **8 workers**（留核给合并/监控）；其他 agent 同时运行时
  效率按 0.6–0.75 折算。
- clone v1 已生效：turn-search 决策约 **68.6% 时间在 clone**（T4/states=8：184.7/269 ms，75 次）；
  clone 从 ~7ms 降到 ~1.6–2.5ms 是 78.6s/局能跑下来的主因；进一步 p50 1.6→1.0ms 约再省 10–15% 局时，
  但 value_prune 降本更大（见 §5.3）。

### 5.5 迭代计划（与价值网训练对齐）

| 轮次 | 搜索配置 | 数据量 | 估算 | 产物 |
|---|---|---|---|---|
| Iter0（bootstrap） | pairwise，states=8 | 20k（134 局） | 2.9 CPU-h / 8 进程 22–29 min | `runs/value/selfplay/iter0/` |
| Train0 | 冻结 encoder，只训 value head（rank CE + utility + top4） | 20k（70/15/15） | GPU 分钟级（BC 初始化） | value head 权重 |
| Iter1 | `value_prune_pairwise` K=4，states=8/12 | 50k（334 局） | 4–10 CPU-h / 8 进程 30–70 min | iter1 数据 |
| Train1 | 重训/解冻部分层 + 校准；固定 golden test | 50k | GPU 分钟–小时 | value v2 |
| Iter2+ | states 提升到 12/16，价值网变强后继续扩 50k–100k | 按收益 | 按 §5.4 线性/并行 | 迭代数据与权重 |

---

## 6. 切分方案（按 `episode_id`，禁止同局跨集）

### 6.1 主训练集（turn-search 自对弈）

- **70/15/15 按 episode_id**，固定 seed；同局所有 step 只进一个 split。
- 20k 约：train 14,000 / val 3,000 / test 3,000 样本（按 150 spg ≈ 94/20/20 局）。
- 50k 约：train 35,000 / val 7,500 / test 7,500 样本（≈234/50/50 局）。
- **golden test 固定**：首轮 Iter0 的 15% 局冻结，后续迭代只新增 train 局，不改 val/test；
  便于跨迭代比较（防止“用新数据重画测试集”造成虚高）。
- 迭代数据版本记录：`iter_id`、`search_config`、`engine_data_patch`、`seed_range`。

### 6.2 BC 冷启动（辅助）

- 沿用 `runs/value_split.json`（320 局 → 224/48/48 局；21,203/4,437/4,660 样本）；
  **只用于 value head 冷启动/对照**，不与主数据混入同一 split。
- 若混用：以 `source` 命名空间隔离 episode_id（BC 用 `bc:*`，自对弈用 `sp:*`），并单独报告两域指标。

### 6.3 泄漏检查清单

- [ ] 同一 `episode_id` 不出现在两个 split（集合交集=0）；
- [ ] 同 seed/同 config 不重复生成（`(seed, states, opponent)` 去重）；
- [ ] BC val/test 不进入主训练集；主 test 不包含 BC 局；
- [ ] 真实 live/轨迹只做域外评估，不进训练；
- [ ] 若使用 golden test 的局做模型选择，严格禁止再回到训练。

---

## 7. 现有 collector/bridge 能否直接产出？最小改动

### 7.1 检查结论：**不能直接产出**

| 组件 | 现状 | 缺口 |
|---|---|---|
| `hsbg/rl/collector.py` | `collect_trajectories` 多进程采集，写 JSONL header/episode/step | step 的 obs 用 `obs_summary`，**完整 Observation 未落盘** |
| `hsbg/rl/api.py` | `Transition.obs` 在内存中是完整 `Observation`；`EpisodeRecord.observations()` 可取 | `to_jsonl_lines`→`Transition.to_dict`→`obs_summary`（359 行）只写摘要 |
| `hsbg/rl/policies.py` | 支持 `BasePolicy.act/bind_env`、`requires_engine`；`make_policy` 有 heuristic/random/teacher/checkpoint | **无 turn-search 策略**（需 env.game + `TurnSearch.decide`） |
| `scripts/eval_turn_search.py` | `run_turn_search` 已有完整循环：`EngineForwardModel.from_env(env, clone=False)` → `TurnSearch.decide` → 按 signature 找 obs.candidates 下标 → `env.step` | 这是采集脚本可直接复用的模式 |
| `hsbg/search/turn_search.py` | `TurnSearchConfig(states_budget/...)`、`TurnSearch.decide(model)` | 需在 collector 里绑定 env/game 并适配成 policy |
| `hsbg/bridge`（Power.log/HDT） | 战斗 trace/校准；无 recruit 完整 obs | 不用于主数据采集 |

### 7.2 最小改动建议（不改 env/engine；建议新脚本，不动 collector）

> env-builder 已核对（2026-10-19 23:06）：`EngineForwardModel.from_env(clone=False)` **只读**
> （`tests/test_search_env_readonly.py`：1 passed；decide 前后 env digest/RNG/候选/hero/board 不变）；
> `env.game`/`env.agent_hero` 是公开接口（建议 adapter 用 `agent_hero`，不要依赖 `_agent`）；
> env 不参与 pickle（worker 内 `make_env`）；obs 3.2 KB/step 可 pickle；clone v1 已生效。

1. **`TurnSearchPolicy`**（module-level、picklable；建议放 `hsbg/search/policy.py` 或 `hsbg/rl/policies.py`）：
   - `requires_engine = True`；`bind_env(env)` 保存 env（bind 后不要再 pickle/跨进程返回）；
   - `act(obs)`：`model = EngineForwardModel.from_env(env, clone=False)`（不 clone 环境）；
     `res = TurnSearch(config, evaluator).decide(model)`；
     按 `res.action.signature()` 在 `obs.candidates` 中找下标；找不到/turn 不一致/异常 → 回退 heuristic；
   - **pickle 约束**：持 config 的模块级实例可直接 pickle；若走字符串名（如 `"turn_search"`），
     需在 `hsbg/rl/policies.py::make_policy` 注册 alias（~10 行，policy-builder scope）；
   - 约 **80–120 行 + 单测**（含 mock 单测不依赖完整搜索；复用 `test_search_env_readonly` 的 digest/RNG 断言）。
2. **新采集脚本 `scripts/collect_turn_search_selfplay.py`**（推荐，避免改 collector）：
   - 复用 `hsbg.rl.api.run_episode(env, policy, seed, episode_id, collect_transitions=True)`——
     `EpisodeRecord.transitions` 已存每步完整 `obs` 与 `action`，`record.rank` 是终局名次；
   - 每 worker 独立 `BattlegroundsEnv`（`opponent` 可配），按 seed_range 分片；
   - 每局写 `samples=(obs, action)`、`ranks=record.rank`、`episode_ids`；落盘为
     `BCDataset` 兼容 pkl（+ meta：search_config/policy_header/engine patch/seed_range/golden_split）；
   - multiprocessing 用 collector 的 `_run_payloads`/`ensure_picklable` 或 `concurrent.futures`；
   - 约 **150–200 行**；可选 JSONL 预览。
3. **可选（后续）**：给 `collector.py` 加 `--obs-mode full`（把 `Transition.obs` pickle 化），
   Phase1 不必动 collector；`bridge` 无需改。
4. **与 env-builder 协作确认（已确认项）**：
   - ✅ `EngineForwardModel.from_env(clone=False)` 只读（`tests/test_search_env_readonly.py`）；
   - ✅ `env.agent_hero` 公开 property（reset 后非空）、`env.game`/`env.legal_actions()`/`num_players`
     稳定（`tests/test_env_public_contract.py`，2 passed）；
   - ✅ 构造/推进路径不变：`BattlegroundsEnv(...)` / `reset(seed)` / `step(cand|idx|descriptor)`；
     `run_episode(env, policy, seed, episode_id, collect_transitions=True)` 的 `Transition.obs` 为完整
     Observation，同 seed+同 policy 的 `(action, obs_digest)` 轨迹一致（contract test 已锁定）；
   - ✅ obs v2 `extra` 可 pickle（3.2 KB/step，0.35 MB/局）；env 不参与 pickle（worker 内 `make_env`）；
     policy 只需 bind 前 picklable（模块级实例或字符串 spec）；`ensure_picklable` 只查 policy；
   - 确定性：同 seed + 同 search seed → obs/动作/rank 完全一致（采集脚本中单独测试；复用 digest+RNG 断言）。

**工作量估计**：adapter+脚本+单测 **0.5–1 天**；确定性/并行合并/校验 **0.5 天**。不需要改 `hsrl2`。

### 7.3 实现验收清单（env-builder review 口径，Phase1 用）

- [ ] **bind 时机**：payload 只放 **bind 前** 的可 pickle policy 实例/字符串 spec；worker 内
  `make_policy` 后由 `run_episode` 调 `bind_env`；采集完成不把 policy 放回结果。
- [ ] **per-worker env**：worker 内 `make_env`、不 pickle；`finally: env.close()`；多 worker 分片用
  `(episode_id, seed)` 合并去重。
- [ ] **determinism**：同 seed + 同 search seed、与 worker 编号/调度顺序无关；测试用
  `obs_digest` + `game.rng._rng.getstate()` / `planning.digest` 断言；`TurnSearch` 的 search seed
  从 config 显式传入，不依赖全局随机。
- [ ] **golden split/meta**：`search_config`、`engine_data_patch`、`seed_range`、`golden_split`
  （按 episode 分组，禁止同局跨 split）、`policy_header`、`ranks=record.rank`；obs v2 `extra`
  已可 pickle，无需额外状态。

---

## 8. 缺口与补采建议（优先级）

| 优先级 | 缺口 | 建议 |
|---|---|---|
| P0 | 无 turn-search 自对弈数据集；collector 只存 obs 摘要 | 实现 §7 的 `TurnSearchPolicy` + `collect_turn_search_selfplay.py`；Iter0 states=8 20k |
| P0 | BC 只是冷启动数据（teacher 弱、obs v1） | 只做 value head 初始化/基线；obs v1→v2 迁移；不进主 split |
| P1 | 20k→50k 的迭代成本 | 用价值头 `value_prune_pairwise(K=4)`；实测 T7 1.3–2.3× 加速；先 pilot 再承诺 |
| P1 | golden test/跨迭代可比性 | 首轮固定 15% 局冻结；每轮记录 search_strength/分布 |
| P2 | 真实数据（live/HDT）有 placement 但无 obs | 只作域外评估；若要真实训练数据需 live memory/HDT 插件扩采集（合规/成本另评估） |
| P2 | 真实轨迹无终局名次 | 只能做战斗辅助/校准；不要伪造 placement |
| P3 | clone/ERP 仍是搜索瓶颈 | env-builder 已优化 clone≈1.6–1.8 ms；继续 1-ply/ERP skip 优化可再降采集成本 |

---

## 9. 与 `docs/VALUE_NETWORK_PLAN.md` 的对齐（数据部分）

- **§2.1 数据表**：BC 行改为 **「辅助/冷启动（非主训练集）」**；新增 **turn-search 自对弈（主）** 行。
- **§2.2 标签**：主标签仍是每局终局 `rank`（1..8）；自对弈数据由 env 结算，无缺失；
  BC 的 `rank=-1` 只作辅助/冷启动。
- **§2.4 Phase0 门槛**：改为「首轮 turn-search 数据 ≥20k 完整 obs 且每局有 rank」；BC 30k 不再作为
  “主数据达标”依据；阈值可升到 50k（Iter1）。
- **§2.5（新增）**：turn-search 自对弈主数据 schema/成本/迭代（即本文件 §4–§6 摘要）。
- **§5.3 切分**、**§6 Phase 表**：Phase1 数据改为「BC 冷启动 + turn-search 20k」；Phase2 改为
  「turn-search 50k/迭代 + value-prune 搜索」；Phase1 时长按 §5.4 更新（数据 22–29 min 而非分钟级）。
- **§7 风险**：新增「turn-search 采集 CPU 成本/分布漂移/golden test」风险。

---

## 10. 风险

1. **分布漂移**：turn-search 越强，自对弈数据分布越偏离 BC/真实；固定 golden test + 按迭代记录。
2. **标签噪声**：8 人局 rank 方差大；用分布损失/top4/校准，不追求单点 MAE。
3. **同局相关**：严格按 `episode_id` split；长局样本权重 1/sqrt(steps)。
4. **采集成本/机器负载**：12 逻辑核且多 agent 并行；先 pilot 校验，再按 8 workers 排期。
5. **obs v1/v2 兼容**：旧 BC `extra` 缺失；统一迁移/校验，训练前断言。
6. **搜索 bug/非法动作**：采集时记录 invalid/terminated/truncated；非法动作率>阈值重跑。
7. **真实域差异**：live 只有 4 局有 placement，无 obs；只能域外评估，不能替代主数据。

---

## 11. 复现/证据

```powershell
python tmp_255130\probe_value_data.py            # 数据源盘点（只读）
python tmp_255130\bench_turn_search_cost.py      # states=8/12/16 单决策成本
python tmp_255130\bench_turn_search_scorer.py   # pairwise vs value_prune 成本
python tmp_255130\build_value_audit.py           # 生成 runs/value_dataset_audit.json
```

- 机器可读：`runs/value_dataset_audit.json`
- 搜索实测：`runs/search/turn_search_confirm20.json`（s8）、`turn_search_confirm20_s12.json`（s12）、
  `turn_search_pilot.json`（s16）
- env-builder 交叉核对：`tests/test_search_env_readonly.py`（from_env/decide 只读断言，1 passed）；
  `tests/test_env_public_contract.py`（agent_hero/game/legal_actions/step 签名 + run_episode 完整 obs/
  同 seed 轨迹一致，2 passed）；
  obs pickle 3.2 KB/step、0.35 MB/局；clone 占决策时间 68.6%；env 不参与 pickle、policy bind 前需 picklable。
- 本审计**未训练、未改数据/引擎、未写 checkpoint**。

---

## 12. Phase1 采集结果（已完成，2026-10-20 00:01）

命令（6 workers；按 env-builder 建议避开多 agent 争用）：

```powershell
python scripts/collect_turn_search_selfplay.py --episodes 140 --workers 6 \
  --states-budget 8 --seed-start 20000 --out runs/value_data/turn_search_20k.pkl
```

| 指标 | 实测 |
|---|---|
| 数据 | `runs/value_data/turn_search_20k.pkl`（**83.27 MB**，BCDataset 兼容） |
| 样本/局 | **21,240 samples / 140 episodes**（151.71/局，>20k 目标） |
| 耗时 | **37.29 min**（23:23:50→00:01:09；6 workers，机器同时有 eval 进程） |
| rank | 100% 覆盖；dist `{1:2902,2:1515,3:3827,4:3412,5:4135,6:2884,7:1694,8:871}` |
| obs | 100% `version=2`（`extra` 可 pickle） |
| 搜索 | decisions 19,738；**fallbacks 8（0.04%）** |
| split | episodes 98/21/21；samples 14,981/3,365/2,894；leak 0/0/0 |
| 验证 | `--validate-only 2`：readonly=OK、determinism=OK ×2 |
| sha256 | `df4aac13ad07185bffc7a7c99b7eec888c0d0745f160e17d926c7faf180c1898` |
| 完整性 | action_index_valid 21,240/21,240；rank=-1=0；episodes unique 140；checks 全 true |
| 动作分布 | buy 4249 / play_minion 4190 / sell 3431 / play_spell 2569 / freeze 1477 / end_turn 1433 / **choose 1502** / reroll 1169 / activate 380 / hero_power 344 / upgrade 257 / use_dark_gift 239 |

- 审计：`runs/value_data/turn_search_20k_audit.json`（含每局 stats/shards/worker 结果、
  `dataset_sha256`、`action_kind_histogram`、`obs_extra_coverage`、`checks`）；
  `runs/value_dataset_audit.json` 新增 `collected_20k`；`runs/value_split.json` 新增 `turn_search_20k`
  （保留原 bc/rl 字段）。
- shard：已归档到 `runs/value_data/_archive/turn_search_20k_shards/*.partN.pkl`
  （6 个，约 75MB；merged+audit 校验后可删除）。
- 注意：**choice 样本 1,502**（`action_kind=choose`）混在 samples 中；value 训练直接用 rank 标签不受影响；
  若做 BC/动作模仿，需按 `obs.phase == "choice"` 过滤或单独解释 action 语义。
- 本数据可直接进入 value head 训练（frozen encoder；BC 冷启动可选）。
