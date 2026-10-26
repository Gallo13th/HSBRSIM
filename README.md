# HSbg Agent — 炉石传说·酒馆战棋智能体

把「酒馆战棋」做成**可训练、可评估、可复现**的强化学习智能体项目。

```
主引擎 hsbg_engine（Rust/PyO3，fork AutoTavern TavernGym）→ RL 环境/策略/训练
legacy 引擎 hsrl2（Python，37.0.0 全内容/真实对局桥）
```

数据基线：**官方 build 37.0.0.255130**（客户端 `.product.db` 为 37.0.0.255130.254477；当前版本 Naga 不在随从池，池内随从 252）。
一键门禁 `python scripts/verify_all.py`：引擎/项目测试 + 冒烟 + 环境验收 +
官方一致性 + 版本检测 + **跨引擎一致性（AutoTavern 参照）** + **TavernBench 评分复现**。
测试通过数不写死在本文件（会漂移），以 `docs/VERIFICATION.md` 与门禁实测为准。

> **2026-10-26 AutoTavern 借鉴升级**：接入 [MCG-NJU/AutoTavern](https://github.com/MCG-NJU/AutoTavern)
> 的 TavernGym 作为**可选/参照模拟后端**，用其规则实现与 mechanics 测试对
> `hsrl2` 做跨引擎一致性审计（发现并修复 T1 池份数、升级费等规则偏差），
> 并引入 TavernBench 决策评测、环境快照/不变量、精确动作掩码验收。
> 详见 [docs/AUTOTAVERN_UPGRADE.md](docs/AUTOTAVERN_UPGRADE.md)。
>
> **2026-10-26 第二阶段（P2）启动**：按用户新指令把 AutoTavern 的 Rust 引擎
> **fork 为本仓库主引擎 `hsbg_engine`**（`rust/`，MIT，含 37.0.0 数据管线），
> 动作空间/观测全面对齐 AutoTavern（前 245 动作 + 3227 floats + 124 cards；
> 游戏支持但未实现的操作作为 245+ 扩展），性能路线与内容移植计划已产出。
> 详见 [docs/AUTOTAVERN_P2_KICKOFF.md](docs/AUTOTAVERN_P2_KICKOFF.md)、
> [docs/RUST_ENGINE.md](docs/RUST_ENGINE.md)、[docs/PORTING_37_PLAN.md](docs/PORTING_37_PLAN.md)。
>
> **2026-10-26 第三阶段（P3）**：**以 AutoTavern fork（`hsbg_engine`）为唯一主引擎，
> 直接修补 AT 把 37.0.0 模拟环境补完整**；`hsrl2` 冻结为 legacy/oracle（只读参考、
> 只维护回归，不再新增功能）。**P1 内容已完成**：37 池内缺失 15 随从 + Azshara 主技能 +
> 2 池内法术已移植进 Rust content；池内脚本覆盖 **missing 0**、hsrl2 oracle
> **15 MATCH/1 DEFERRED/2 STRUCTURAL_OK**、全量 Rust 测试 **887/0**；模拟环境补完，
> 下一步转入 RL（std 245/3227 profile 的训练/评测）。详见
> [docs/AUTOTAVERN_P3_KICKOFF.md](docs/AUTOTAVERN_P3_KICKOFF.md)。

## 组成与状态

| 层 | 目录 | 状态 |
|----|------|------|
| **主模拟引擎（P2）** | `rust/`（`hsbg_engine`） | ✅ fork AutoTavern TavernGym（Rust + PyO3）：245 动作 + 精确 mask、3227+124 观测、BatchEnv；裸吞吐 ~274 局/s / 3.65 ms/局（37 数据最终态；上游同代码 272.8；比值 1.00） |
| legacy 模拟引擎（冻结） | `hsrl2/` | 🧊 Python 引擎（37.0.0 全内容/真实对局桥/参照 oracle）；P3 起**冻结**：不再新增功能，只维护回归与差分 oracle |
| **37.0.0 数据管线（P2）** | `data/p2/` + `tools/p2_data/` | ✅ 官方 37.0.0 → AutoTavern schema（3983 = 3695 映射 + 288 compat；脚本 id 0 missing） |
| **动作/观测标准 profile（P2）** | `hsbg/env/action_space_std.py` / `obs_std.py` | ✅ 前 245 动作与 AT 逐位一致 + 扩展段；3227 floats + 124 cards 布局与 AT 32 项逐项一致 |
| RL 环境 | `hsbg/env/` | ✅ 单智能体 8 人对局、实体 token 观测、候选动作、奖励、确定性、多进程向量化 |
| 环境可靠性 | `hsbg/env/snapshot.py` / `hsbg/env/invariants.py` | ✅ 精确存档/恢复（obs/RNG/候选逐位一致）、结构不变量检查（移植 AutoTavern `invariants.rs`） |
| RL 接口层 | `hsbg/rl/` | ✅ Policy/EnvLike 协议、Gymnasium 包装（`check_env` 通过）、JSONL 采集器（4 进程 7.4 局/s）、多进程评测 |
| 双引擎后端 | `hsbg/backends/` | ✅ TavernGym 参照后端（`make_env(backend="taverngym")`；默认仍 `hsrl2`），两后端同 harness 基准 |
| 智能体与教师 | `hsbg/agents/` | ✅ 随机 / 启发式（引擎感知贪心） |
| 策略网络 | `hsbg/policy/` | ✅ 实体 Transformer（候选打分 + 名次分布价值），1.24M 参数 |
| 训练管线 | `hsbg/train/` | ✅ BC（行为克隆）+ PPO（GAE/clip/KL 早停）+ 数据收集 |
| 评测 | `hsbg/eval/` | ✅ 固定种子集、bootstrap CI、名次分布、基线对比 |
| 决策基准 | `benchmarks/tavernbench/` | ✅ TavernBench 960 任务 / 368 评测集（vendored，MIT，评分离线可复现；`scripts/run_tavernbench.py --check`） |
| 跨引擎一致性 | `tests/conformance/` + `tools/ac_conformance/` | ✅ 57 场景双引擎对拍、数据差异台账、AC-01…AC-04 审计台账（`docs/CONFORMANCE_AUTOTAVERN.md`） |
| 真实对局桥 | `hsbg/bridge/` | ✅ Power.log 解析、HDT/BobsBuddy 轨迹抽取、rizling 版本跟踪 |
| 官方一致性工具 | `tools/` | ✅ 官方数据抓取/差分、客户端程序集分析、差分 harness、版本同步流水线 |

## 快速开始

```powershell
cd C:\HSagent

# 1) 引擎回归（约 50s）
python -m pytest hsrl2/tests -q

# 2) 项目测试（环境/策略/桥接）
python -m pytest tests -q

# 3) 跑一局 8 人对局（启发式智能体，打印每回合状态）
python scripts/demo_env.py --seed 42

# 3b) RL 接口：数据采集 / 评测 / Gym 包装
python -m hsbg.rl.collector --policy heuristic --envs 4 --episodes 100 --out runs/rl/heuristic_100.jsonl
python -m hsbg.rl.evaluate --policy random --episodes 20
python -c "from hsbg.rl.gym_wrapper import make_gym_env; env=make_gym_env(); print(env.observation_space, env.action_space)"

# 3c) 环境验收 / 全量门禁
python scripts/validate_env.py --games 30 --json runs/env_validation.json
python scripts/verify_all.py --fast

# 4) 环境基准（吞吐/耗时/崩溃）
python scripts/bench_env.py --seeds 20

# 5) 收集教师示范 → BC → 评测（CPU 即可，GPU 更快）
python scripts/collect_bc.py --episodes 320 --workers 4 --out runs/bc_data/heuristic_320_official.pkl
python scripts/train_bc_dataset.py --dataset runs/bc_data/heuristic_320_official.pkl `
    --epochs 30 --device cuda --out runs/bc/official_320
python scripts/evaluate.py --checkpoint runs/bc/official_320/policy_bc.pt --episodes 100 --seed 100

# 6) PPO 微调（需要 CUDA，约 8~20 分钟）
python scripts/train_ppo.py --total-steps 120000 --num-envs 6 --env real --device cuda `
    --init-from runs/bc/official_320/policy_bc.pt --out runs/ppo/official

# 7) 版本同步（游戏补丁后）
python tools/version_sync.py --check          # 四信号检测
python tools/version_sync.py --dry-run        # 取数/生成/差分（不覆盖 data/）
python tools/version_sync.py --apply --yes    # 备份→应用→回归（失败自动回滚）

# 8) 官方一致性差分（679 场真实 BG 战斗）
python tools/diff_extract_replays.py --limit 5
python tools/diff_replay_combat.py --traces runs/official_traces --limit 10

# 9) AutoTavern 借鉴升级（2026-10-26，见 docs/AUTOTAVERN_UPGRADE.md）
#    9a) TavernGym 参照后端（需先按 docs/TAVERNGYM_BACKEND.md 构建 taverngym）
python -m hsbg.backends.benchmark --games 10 --seed 0 --engine-games 500   # 两后端同 harness 基准
python -m hsbg.rl.collector --policy random --envs 1 --episodes 2 --backend taverngym --out runs/rl/tg.jsonl

#    9b) 跨引擎一致性套件（AutoTavern 36.6.3 参照 vs hsrl2 37.0.0；无 taverngym 时自动 skip）
python -m pytest tests/conformance -q
python -m tools.ac_conformance.run --seeds 48        # 57 场景分类报告（JSON 落 runs/conformance/）

#    9c) TavernBench 决策评测（vendored，离线可复现评分）
python scripts/run_tavernbench.py --check           # 数据完整性 + 已发布答案评分复现
python scripts/run_tavernbench.py --systems tavernagent,jev

#    9d) 环境精确存档/恢复与结构不变量（见 docs/ENV_SNAPSHOT.md）
python -c "from hsbg.env import BattlegroundsEnv; from hsbg.env.snapshot import snapshot, restore; \
e=BattlegroundsEnv(seed=42); o=e.reset(seed=42); s=snapshot(e); print(len(s.game.heroes))"
python scripts/validate_env.py --games 20 --check-invariants   # 不变量抽查（默认关闭）

# 10) 第二阶段（P2）：Rust 主引擎 / 37 数据 / 标准动作观测（见 docs/AUTOTAVERN_P2_KICKOFF.md）
cd rust && python -m pip install -e . && cd ..          # 构建并安装 hsbg_engine（需 Rust 1.98 + maturin）
python -c "import hsbg_engine; g=hsbg_engine.Game(seed=1); print(hsbg_engine.game_version(), list(g.placements()))"
python rust/bench_engine.py --games 2000 --e2e-games 20  # 引擎吞吐基准（对照上游 taverngym 可选）
python tools/p2_data/gen_carddb_37.py --check           # 37.0.0 数据管线自检（--report 看差分）
python -m pytest tests/test_action_space_std.py tests/test_obs_std.py tests/test_rust_engine.py tests/test_p2_data.py -q
python tools/p2_delta/run_all.py                        # 内容缺口/操作缺口覆盖矩阵（产物 runs/p2_delta/）
python tools/p2_perf/run_all.py                         # Rust vs Python vs C 性能基准（产物 runs/p2_perf/）
```

## 评测结果（100 局固定种子，8 人局，名次越小越好）

| 策略 | 平均名次 | 冠军率 | 前四率 |
|------|----------|--------|--------|
| 均匀随机 | 7.85 | 0% | 0% |
| 启发式教师 | 4.30 | 12% | 54% |
| **BC 策略（本仓库训练）** | **4.06** | 9% | 62% |
| PPO 微调 | 稀疏奖励下未稳定超过 BC（训练暂停） | — | — |

BC：320 局教师示范 / 30,300 样本；验证集动作准确率 **85.6%**（随机基线 11.5%）。
环境：单局约 **0.3–0.5 s**、~100 步、3–5 ms/步；单进程 2–3 局/s，4 进程 7 局/s。

### 双引擎吞吐（2026-10-26 本机 macOS Apple Silicon 实测，同一 benchmark harness）

| 后端 | 观测源 | games/s | ms/局 | ms/步 |
|------|--------|--------:|------:|------:|
| hsrl2（默认） | 实体 token + 候选动作 | 6.52 | 153.3 | 3.89 |
| TavernGym（参照，36.6.3） | features（3227↑ + 124 卡） | **33.88** | **29.5** | **0.356** |
| TavernGym（参照） | view JSON（调试视图） | 3.21 | 312.0 | 3.59 |

TavernGym 引擎裸吞吐 **275.5 games/s**（3.63 ms/局，15.4 回合）；端到端默认观测源
比 hsrl2 快 **5.2×**（每步 **10.9×**），瓶颈在 Python 侧观测解码。注意两后端是
**不同游戏版本/动作空间**，吞吐数字只用于说明参照引擎的工程上限，策略不可直接迁移。
复现：`python -m hsbg.backends.benchmark --games 10 --seed 0 --engine-games 500`。

### TavernBench 决策质量基准（引入自 AutoTavern）

- 960 任务 / 40 场景 / 8 类别；论文固定评测集 368 任务（`data/eval`）。
- 已发布 1 个 agent + 12 个 LLM/tool-use 系统答案，评分**纯标准库离线可复现**。
- 复现：`python scripts/run_tavernbench.py --check`（本机 **26/26 检查通过**）。
- 与 self-play 评测的关系：TavernBench 测「单步决策判断」（LLM/agent 向），
  不替代名次分布评测；详见 `docs/TAVERNBENCH.md`。

## 设计要点

- **引擎是机制精度的唯一权威**：卡牌数值来自官方 CardDefs（build 255130）；主引擎
  `hsbg_engine`（Rust，fork 自 AutoTavern）沿用其机制实现，有误处按证据精修
  （`rust/FORK.md` 台账 + `docs/PORTING_37_PLAN.md`）；legacy `hsrl2` 保留为对照/oracle。
- **动作/观测与 AutoTavern 对齐**：标准 profile 前 245 动作索引/语义/`action_name`
  与 AT 逐位一致，观测 3227 floats + 124 cards 与 AT `layout()` 32 项逐项一致；
  扩展动作段（≥245）补游戏内支持但双方未实现的操作（如按槽位冻结）。
- **数据与性能路线**：37.0.0 数据由 `tools/p2_data` 生成 AutoTavern schema（含 compat
  条目避免脚本 registry panic）；Rust 裸引擎 ~274 局/s（3.65 ms/局，37 数据），是 hsrl2 的 ~40×，
  端到端瓶颈转为观测编码（路线见 `docs/PERF_ROUTE.md`）。
- **双引擎与可靠性参照**：默认 `hsrl2`（37.0.0，可训练/可桥接真实对局）；可选
  `taverngym` 参照后端（AutoTavern，Rust/PyO3，36.6.3）用于跨引擎对拍、吞吐对照
  与规则证据；跨引擎一致性套件把「参照实现/官方 wiki/真实日志」分级为证据。
- **实体中心观测**：棋盘/手牌/酒馆等按槽位序列化为实体 token；策略用 Transformer
  建模实体间关系（39 实体槽、候选动作 ≤64、8 名次分布价值头）。
- **候选动作打分**：不固定动作空间；每步枚举合法动作（含目标组合），策略对候选
  打分并做 masked argmax，天然支持动态棋盘与发现三选一。
- **精确动作掩码**：`env.legal_actions()` 的每个候选都由引擎接受并可推进（枚举全候选
  的隔离测试）；非法动作返回 `invalid` 且状态不推进、不崩训练进程。
- **环境快照/恢复**：`hsbg.env.snapshot` 在决策步保存 env+引擎全状态，恢复后观测/
  候选/RNG 逐位一致（搜索、离线回放、故障恢复用）；结构不变量移植自 AutoTavern。
- **确定性**：环境完全由 seed 决定；同 seed 轨迹逐位一致，训练可复现。
- **防死循环**：每回合动作预算（40）、freeze 单向、无进展保护。

## 官方一致性（本项目的核心要求）

| 工作 | 结果 |
|------|------|
| 官方数据 | 迁移到 build **255130**（37.0.0）：BG 实体 +175、新卡 +179、384 处数值变化、新种族 ABERRATION(126) |
| 引擎回归 | 数据迁移后 **4,175 → 4,187 passed**；补卡后引擎 4,588+ 项 + 项目 403+ 项（当前合计 **5,104 passed**（持续增长）） |
| 官方轨迹差分 | 679 场真实 BG 战斗：DATA_GAP=0，strict MATCH **72.3%**，确定性 **86.3%**（tolerant 94.4%），干净子集 **100%（33/33）**，behavior_mismatch=0；**真实 Power.log 事件级 26 场战斗 behavior_mismatch=0**（3 局：6+10+10，HDT 同局交叉 B/C 各 10/10，伤害上限 5/10/15 三档确认；C round6 经 F-14 修复）；有 CI 门禁 `scripts/audit_official_consistency.py` |
| 已修引擎 bug | 战斗快照 deepcopy 实体（性能 7×/内存 98×）、Ozumat SoC 召唤 6-7 只 Tentacle（官方 1 只） |
| **AutoTavern 对拍（2026-10-26）** | 58 场景双引擎对照：**MATCH 55**、CONVENTION_DIFF 2（AC-01 先攻平局二源冲突；AC-04 参照侧脚本行为）、**ENGINE_BUG 0**、UNSUPPORTED 1；已修 **AC-02 T1 池份数 16→15**、**AC-03 升级费 T5/T6 9/10→11/11**（wiki + 参照双证据）；共享卡 3412、共享随从 2393 攻/血/tier/种族差异 0。台账 `docs/CONFORMANCE_AUTOTAVERN.md` |
| **新门禁发现的真实缺陷** | **F-36 跨进程确定性**（3 处 frozenset→RNG，不同 PYTHONHASHSEED 轨迹分裂；已修 + 双哈希子进程回归）；**F-37 Reborn 棋盘溢出**（Reborn 直插不检查 7 上限 → board=8；对照 AutoTavern `reborn→summon` 修复，`validate_env --check-invariants` 60 局 0 违反） |
| 客户端逆向 | REA（rea-agents 6.7）+ ilspycmd：无官方战斗模拟器（服务器权威）；官方 GameTag 1214 项 vs 引擎 126 项差异报告；BobsBuddy 战斗算法逐条对照 |
| 已知缺口 | 37 张 37.x 新池随从无效果脚本（差分分歧主因）；4 个 DEFERRED Dark Gift；动态 SCRIPT_DATA_NUM tag 撞号待建模 |

详见 `docs/OFFICIAL_EXACTNESS.md`、`docs/DIFF_HARNESS.md`、`docs/REA_FINDINGS.md`、
`docs/VERSION_SYNC.md`。

## 文档

- `docs/AUTOTAVERN_UPGRADE.md` — **AutoTavern 借鉴升级总报告**（对比/设计/变更/证据/限制）
- `docs/AUTOTAVERN_P2_KICKOFF.md` — **第二阶段总报告**（Rust 主引擎/37 数据/动作观测统一/性能/内容移植计划）
- `docs/RUST_ENGINE.md` — Rust 主引擎 `hsbg_engine`（架构/安装/用法/与上游关系/基准）
- `docs/DATA_37_MIGRATION.md` — 37.0.0→AutoTavern schema 数据管线与差分（compat 条目/字段覆盖/局限）
- `docs/PORTING_37_PLAN.md` — 37.x 内容移植缺口/难度/分批计划 + 缺失操作清单（P1 must-have）
- `docs/ACTION_SPACE_STD.md` — 标准动作空间（245 + 扩展段）规范/编码/迁移
- `docs/OBS_STD.md` — 标准观测（3227 floats + 124 cards）块布局/字段/迁移
- `docs/AZ_MCTS_SELFPLAY_DESIGN.md` — 逐步 MCTS + 自对弈训练设计（推理/训练两阶段/公式推导/Rust 搜索核/远程部署）
- `docs/PERF_ROUTE.md` — Rust vs Python vs C 性能实测与迁移路线
- `docs/CONFORMANCE_AUTOTAVERN.md` — 跨引擎一致性审计台账（57 场景 / AC-01…AC-04 / 数据差异）
- `docs/TAVERNGYM_BACKEND.md` — TavernGym 参照后端（安装/构建、EnvLike 适配、基准、限制）
- `docs/TAVERNBENCH.md` — TavernBench 决策评测（数据结构/评分口径/复现/提交答案）
- `docs/ENV_SNAPSHOT.md` — 环境精确存档/恢复与结构不变量（契约/开销/已知偏差）
- `docs/PORTABILITY.md` — macOS/Linux 工程可移植性与测试基线
- `docs/ARCHITECTURE.md` — 分层架构与数据流
- `docs/ENV_SPEC.md` — 环境接口契约（观测/动作/奖励/step 顺序）
- `docs/ENGINE_API.md` — 引擎 API 速查（含本次新增只读查询/名次/phase/解冻 API）
- `docs/ENGINE_RL_READINESS.md` — 引擎对 RL 的适配性评估（基准 + 缺陷清单）
- `docs/TRAINING.md` — 训练手册、超参、结果
- `docs/OFFICIAL_EXACTNESS.md` — 官方一致性技术路线（数据/行为/官方实现可行性）
- `docs/DIFF_HARNESS.md` — 官方轨迹差分方法与统计
- `docs/REA_FINDINGS.md` — REA/客户端/BobsBuddy 逆向结论
- `docs/VERSION_SYNC.md` — 版本跟踪与一键同步流水线
- `docs/ENV_VALIDATION.md` — 环境验收报告（确定性/多人数/选择步/奖励/性能/采集吞吐）
- `docs/EXACTNESS_STATUS.md` — 官方一致性状态快照（数据/脚本覆盖/差分/缺口/下一步）
- `docs/VERIFICATION.md` — 验收快照（每条命令的预期输出形态，交付/CI 对照）
- `docs/EVAL_REPORT.md` — 策略评测报告（100 局固定种子 + 名次分布图）
- `docs/RL_INTERFACE.md` — RL 接口层（Policy/EnvLike 协议、Gym 包装、JSONL 采集器、并发与确定性）
- `docs/REAL_GAME_BRIDGE.md` — 真实对局数据桥（Power.log / AgenticAssistant）
- `docs/LIVE_AUTOMATION_PROTOCOL.md` — 实时自动化/截图/采集/热修/协作协议
- `docs/LIVE_TO_SIM_GAP.md` — Live 操作 → 模拟器补全差距表
- `docs/AUDIT_LIVE_TO_SIM.md` — Live 截图/文档/代码审计与机制缺口
- `docs/AUDIT_ENV_ACTIONS.md` — env 动作/观测覆盖审计
- `docs/AUDIT_ENGINE_MECHANICS.md` — 引擎/卡牌机制审计
- `docs/AUDIT_PROTOCOL.md` — 审计协议（证据等级/gap schema/回归门槛）
- `docs/MULTI_AGENT_RULES.md` — 多智能体任务板/写范围/handoff
- `docs/POLICY_OBS_V3.md` — obs v3/MOVE_MINION/旧 checkpoint 迁移
- `docs/SEARCH_15TURN_BENCH.md` — 15 回合单座搜索宽度/深度/跨回合预期基准
- `docs/TURN_SEARCH_RUST.md` — Rust 回合内 TurnSearch（pairwise 搜索基线）
- `docs/REFERENCE_PROJECTS.md` — 外部参考项目评估（HearthstoneLegendArriver / AutoTavern）
- `docs/WEBUI.md` — 本地 Web 控制台（评测/训练结果/runs/TavernBench）
- `docs/8H_FINAL_REPORT.md` — 8h 自主工作最终报告
- `docs/schemas/live_action.schema.json` — 动作日志 JSON Schema
- `docs/ENGINE_NOTES.md` — 引擎修改记录（F-01…F-30+）
- `AGENTS.md` — 协作与验收约定

## 目录

```
rust/           ★ P2 主引擎：hsbg-engine（fork AutoTavern TavernGym，Rust+PyO3）+ hsbg_engine Python 包
hsrl2/          legacy Python 引擎（vendored；卡牌脚本在 scripts/batches/）
data/           官方 37.0.0 数据（backup_249896/ 为旧基线备份）；data/p2/ 为 AutoTavern schema 37 数据
hsbg/env/       RL 环境（spec/driver/observation/game_env/vec_env/snapshot/invariants）
hsbg/rl/        RL 接口层（api/policies/envs/gym_wrapper/collector/evaluate）
hsbg/backends/  TavernGym 参照后端（EnvLike 适配、基准；默认后端仍是 hsrl2）
hsbg/agents/    对手与教师
hsbg/policy/    编码器 + 实体 Transformer + checkpoint
hsbg/train/     BC / PPO / buffer / vec env / 评测
hsbg/eval/      指标与评测运行器
hsbg/bridge/    Power.log / HDT 轨迹 / rizling 版本
hsbg/search/    turn-search / PUCT/MCTS / 决策矩阵
hsbg/planning/  引擎 clone / forward / checkpoint（搜索原语）
benchmarks/     TavernBench 决策评测（vendored，MIT）
tools/          数据生成/审计、官方数据抓取、差分 harness、版本同步、ac_conformance
tests/          环境/策略/引擎契约/桥接测试；tests/conformance/ 跨引擎一致性套件
scripts/        demo/collect/train/evaluate/benchmark/run_tavernbench 入口
reversed/       逆向分析产物（官方 XML/枚举/REA/BobsBuddy）
tmp_*/          隔离工作区（数据迁移/修复演练，可删）
```

## 运行环境

- 开发/训练：Windows 11，Python 3.13（`numpy`、`torch 2.9 + CUDA`、`pytest`）；
  RTX 4060 Ti 16GB；训练与评测均可在 CUDA 或 CPU 上运行。
- 本仓库同时验证 **macOS（Apple Silicon, Python 3.12）**：`python3 -m pytest tests`
  全绿（平台/缺失 checkpoint 用例按 `tests/conftest.py` 精确 skip，见 `docs/PORTABILITY.md`）。
- 可选依赖 `taverngym`（AutoTavern 上游参照后端）与 **Rust 主引擎 `hsbg_engine`**
  需要 Rust 1.98 + maturin 从源码构建：`cd rust && python -m pip install -e .`；
  不安装时 legacy 流程与测试不受影响（`tests/test_rust_engine.py` 自动 skip）。
- 本机验证：macOS Apple Silicon（Rust 1.98.1）构建通过；`cargo test --release -p hsbg-engine`
  与 Python 侧冒烟见 `docs/RUST_ENGINE.md`。
