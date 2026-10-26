# AGENTS.md — HSbg Agent 协作指南（AI/人类开发者必读）

> 目标：把「炉石传说·酒馆战棋」做成可训练、可评估、可复现的智能体项目。
> 三层：**模拟引擎** → **强化学习环境** → **策略与训练**。

## 0. 文档索引（先读）

| 文档 | 用途 |
|---|---|
| [docs/AUTOTAVERN_UPGRADE.md](docs/AUTOTAVERN_UPGRADE.md) | ★ AutoTavern 借鉴升级（第一阶段）总报告（双引擎/变更/证据/限制） |
| [docs/AUTOTAVERN_P2_KICKOFF.md](docs/AUTOTAVERN_P2_KICKOFF.md) | ★★ 第二阶段总报告：Rust 主引擎/37 数据/动作观测统一/性能/内容移植（改引擎/数据/动作必读） |
| [docs/RUST_ENGINE.md](docs/RUST_ENGINE.md) / [rust/FORK.md](rust/FORK.md) | Rust 主引擎 `hsbg_engine` 架构/构建/用法 + fork 策略与改动台账 |
| [docs/DATA_37_MIGRATION.md](docs/DATA_37_MIGRATION.md) | 37.0.0 → AutoTavern schema 数据管线（生成器/差分/compat 条目/局限） |
| [docs/PORTING_37_PLAN.md](docs/PORTING_37_PLAN.md) | 37.x 内容移植缺口/难度/分批计划 + 缺失操作清单（P1 must-have 18 卡） |
| [docs/ACTION_SPACE_STD.md](docs/ACTION_SPACE_STD.md) / [docs/OBS_STD.md](docs/OBS_STD.md) | 标准动作空间（245+扩展）/ 标准观测（3227+124）与迁移 |
| [docs/PERF_ROUTE.md](docs/PERF_ROUTE.md) | Rust/Python/C 性能实测与迁移路线 |
| [docs/CONFORMANCE_AUTOTAVERN.md](docs/CONFORMANCE_AUTOTAVERN.md) | 跨引擎一致性台账（57 场景/AC 编号/数据差异；改引擎机制后须同步） |
| [docs/TAVERNGYM_BACKEND.md](docs/TAVERNGYM_BACKEND.md) | TavernGym 参照后端（安装/构建/EnvLike 适配/基准，改 `hsbg/backends/**` 必读） |
| [docs/TAVERNBENCH.md](docs/TAVERNBENCH.md) | TavernBench 决策评测（数据/评分/复现，改 `benchmarks/**` 必读） |
| [docs/ENV_SNAPSHOT.md](docs/ENV_SNAPSHOT.md) | 环境精确存档/恢复与结构不变量（改 `hsbg/env/snapshot.py`/`invariants.py` 必读） |
| [docs/PORTABILITY.md](docs/PORTABILITY.md) | 非 Windows 平台测试基线（平台守卫规则） |
| [docs/LIVE_AUTOMATION_PROTOCOL.md](docs/LIVE_AUTOMATION_PROTOCOL.md) | 实时对局自动化（改 `hsbg/live/**` 必读） |
| [docs/LIVE_COLLAB_SECTION.md](docs/LIVE_COLLAB_SECTION.md) | Live 协作章节（已合并进 `LIVE_AUTOMATION_PROTOCOL.md` §10，保留为历史片段） |
| [docs/POLICY_OBS_V3.md](docs/POLICY_OBS_V3.md) | obs v3/MOVE_MINION/旧 checkpoint 迁移（改 policy/训练必读） |
| [docs/SEARCH_15TURN_BENCH.md](docs/SEARCH_15TURN_BENCH.md) | 15 回合单座搜索宽度/深度/跨回合预期基准（搜索调参必读） |
| [docs/REFERENCE_PROJECTS.md](docs/REFERENCE_PROJECTS.md) | 外部参考项目评估（含 HearthstoneLegendArriver） |
| [docs/8H_FINAL_REPORT.md](docs/8H_FINAL_REPORT.md) | 8h 自主工作最终报告（2026-10-23 07:00） |
| [docs/AUDIT_PROTOCOL.md](docs/AUDIT_PROTOCOL.md) | 审计协议：输入/证据等级 E0–E4/gap schema/复现命令/回归门槛/8h 节奏 |
| [docs/MULTI_AGENT_RULES.md](docs/MULTI_AGENT_RULES.md) | 多智能体协作：写范围/任务板 claim/消息格式/handoff/超时/冲突/Lead 职责 |
| [docs/AUDIT_CONSISTENCY.md](docs/AUDIT_CONSISTENCY.md) | 三篇审计的口径/冲突/重复/编号映射登记 |
| [docs/LIVE_TO_SIM_GAP.md](docs/LIVE_TO_SIM_GAP.md) | Live → 模拟器缺口台账（带截图/actions 证据） |
| [docs/ENV_SPEC.md](docs/ENV_SPEC.md) / [docs/ENGINE_API.md](docs/ENGINE_API.md) | 环境契约 / 引擎 API |

## 1. 仓库布局

```
C:\HSagent\
├── hsrl2/                 # 模拟引擎（vendored，机制精度权威；回归测试全绿）
│   ├── game.py            # Game：招募回合 / 配对 / 战斗 / 淘汰（约 5.7k 行）
│   ├── hero.py minion.py entity.py tags.py
│   ├── combat.py queue.py events.py pools.py db.py defs.py
│   ├── actions/           # 引擎 Action 原语
│   ├── scripts/           # 卡牌/英雄/饰品/异变效果脚本 + REGISTRY
│   └── tests/             # 引擎回归测试（禁止为了新功能改红）
├── data/                  # 引擎卡牌数据 JSON（37.0.0.255130 基线）
├── hsdata/                # 可选：原始 CardDefs（不入库，按 docs/DATA_REBUILD.md 重建）
├── rust/                  # ★★ P2 主引擎：hsbg-engine（fork AutoTavern TavernGym，Rust+PyO3）
│   ├── crates/hsbg-engine/     # 引擎 crate（数据在 data/cards.json，编译期嵌入）
│   ├── crates/hsbg-engine-py/  # PyO3 绑定（Python 模块 hsbg_engine._core）
│   ├── python/hsbg_engine/     # numpy 包装（Game/BattlegroundsEnv/BatchEnv）
│   └── FORK.md                 # 上游 commit/重命名/改动台账/数据替换步骤
├── hsbg/                  # ★ 本项目新增代码
│   ├── env/               # RL 环境（spec 契约 / 观测 / 动作 / 对局循环 / 向量化 / snapshot / invariants）
│   ├── backends/          # ★ TavernGym 参照后端（EnvLike 适配 + 基准；默认后端仍是 hsrl2）
│   ├── rl/                # Policy/EnvLike 协议、Gym 包装、JSONL 采集/评测、make_env 工厂
│   ├── agents/            # 脚本对手 / 启发式教师
│   ├── policy/            # 实体 Transformer 策略 + 价值头
│   ├── train/             # BC / PPO 训练管线
│   ├── eval/              # 评测 / 锦标赛 / 基线
│   ├── bridge/            # 真实对局桥（Power.log 解析、数据资产）
│   └── paths.py
├── benchmarks/tavernbench/ # ★ vendored TavernBench（960 任务/368 评测集，MIT）
├── tests/                 # ★ 新增功能的测试（pytest；tests/conformance/ = 跨引擎一致性套件）
├── scripts/               # 可执行入口（demo / train / evaluate / run_tavernbench）
├── docs/                  # 架构、环境契约、引擎 API、训练手册、AutoTavern 升级报告
├── tools/                 # 引擎自带审计/生成器（只读使用）；tools/ac_conformance/ 双引擎对拍
└── runs/                  # 训练产物（git 忽略）
```

**`hsrl2/` 是 vendored 引擎**：默认视为只读。确需修改时：
1. 先在 `hsrl2/tests/` 或 `tests/test_engine_fixes.py` 写失败测试；
2. 改动必须保持 `python -m pytest hsrl2/tests -q` 全绿；
3. 在 `docs/ENGINE_NOTES.md` 记录动机、规则依据、影响面；
4. 只有 Lead 批准才能改 `game.py` / `combat.py` / `queue.py` / `tags.py` 等核心文件。

规则权威文档在 `docs/reference_old/BATTLEGROUNDS_RULES.md`（113KB，旧项目遗留，
查规则时参考）；卡牌录入参考 `docs/reference_old/CARD_REGISTRATION_GUIDE.md`、
`docs/reference_old/MECHANICS_REFERENCE.md`。旧项目的 RL 文档（`RL_SYSTEM_GUIDE.md`、
`RL_ENVIRONMENT_AUDIT.md`）仅供参考，**不要**照搬其 v1 引擎接口。

## 2. 环境与命令（Windows 主开发；macOS/Linux 可复核）

```powershell
cd C:\HSagent
python -m pytest hsrl2/tests -q          # 引擎回归（通过数以本次输出为准，不抄旧值）
python -m pytest tests -q                # 本项目新增测试（含 tests/conformance/；无 taverngym 时自动 skip）
python tools/smoke_random_games.py --games 8 --seed 2000   # 全对局压测
python scripts/verify_all.py --fast      # 一键快速门禁（约 2min）
python scripts/verify_all.py             # 一键全量门禁（约 4-6min；有 rust/ 时含 Rust build gate）
```

P2 新增命令（详见 docs/AUTOTAVERN_P2_KICKOFF.md）：
```powershell
cd rust; python -m pip install -e .; cd ..   # 构建/安装 Rust 主引擎（Rust 1.98 + maturin）
python -m pytest tests/test_rust_engine.py tests/test_action_space_std.py tests/test_obs_std.py tests/test_p2_data.py -q
python tools/p2_data/gen_carddb_37.py --check          # 37 数据管线自检
python tools/p2_delta/run_all.py                        # 内容/操作缺口覆盖矩阵
python tools/p2_perf/run_all.py                         # Rust/C/Python 性能基准
cargo test --release --manifest-path rust/Cargo.toml -p hsbg-engine   # Rust 测试
```

macOS/Linux 上用 `python3` 代替 `python`；平台专属用例按 `tests/conftest.py`
精确 skip（不改变 Windows 行为），基线见 `docs/PORTABILITY.md`。

> 测试函数/行数等基线不要写死在文档里（会漂移）；当前实测值见
> `docs/AUDIT_CONSISTENCY.md` §2，门禁细则见 `docs/AUDIT_PROTOCOL.md` §8。

依赖：`numpy`、`torch`（CUDA 可用，RTX 4060 Ti 16GB）、`pytest`。
新增第三方依赖前先问 Lead。**禁止**引入 gym/stable-baselines3 作为硬依赖
（环境层提供 gymnasium 兼容外观即可，内部零依赖）。
**可选**依赖 `taverngym`（AutoTavern 参照后端/跨引擎对拍，需 Rust 1.98 + maturin
从源码构建，见 `docs/TAVERNGYM_BACKEND.md`）；不安装时默认流程与门禁不受影响。

## 3. 核心约定

- **语言**：代码注释/文档用中文；标识符用英文。
- **实时对局自动化**：改动 `hsbg/live/**` 前先读
  `docs/LIVE_AUTOMATION_PROTOCOL.md`；新发现缺操作必须登记到
  `docs/LIVE_TO_SIM_GAP.md`，附截图/actions.jsonl 证据，不能只口头描述。
- **审计**：任何"缺机制/缺动作/缺字段"的结论必须先读
  `docs/AUDIT_PROTOCOL.md`（证据等级 E0–E4、gap schema、复现命令、回归门槛）；
  审计结论/优先级冲突登记到 `docs/AUDIT_CONSISTENCY.md`，不要只在消息里说。
- **多智能体协作**：并行写作/任务领取按 `docs/MULTI_AGENT_RULES.md`：
  任务板 claim/complete 带 revision、同一文件禁止并行写、完成后必须给 Lead
  四段消息（任务/证据/结论/下一步）。
- **编码**：所有文件 UTF-8（`open(..., encoding="utf-8")`）；不要用系统默认编码。
- **确定性**：环境行为必须由 `seed` 完全决定（引擎 RNG = `game.rng`）。
  训练可复现性依赖这一点。
- **引擎随机**：`hsrl2` 内禁止 `import random`（走 `game.rng`）；新增代码同理。
- **PendingChoice 契约**：`game.pending_choices` 是队列；`choice.choose(i)`
  只结算**不出队**，必须由环境 `pop(0)`，否则重复结算（引擎文档 TEST_SOP §8）。
- **异常**：动作非法时引擎抛 `hsrl2.game.GameStateError`；环境层必须捕获并
  转为 `info["invalid"]=True`，不得让训练进程崩溃。
- **观测/动作**：以 `hsbg/env/spec.py` 为唯一契约；改字段 = 升 `version` 并同步
  `docs/ENV_SPEC.md`。
- **测试**：每个新模块必须有对应 `tests/test_*.py`；性能敏感路径加基准测试。
- **不要提交 `runs/`、`__pycache__`、模型权重**。

## 4. 并行开发与写权限（重要）

多个 agent 共享同一工作目录，**只写自己 scope 内的文件**；同一文件同一时间只能有一个 writer。
完整协作规则（任务板 claim/complete、handoff、消息格式、超时/冲突处理、Lead 汇总职责）见
[docs/MULTI_AGENT_RULES.md](docs/MULTI_AGENT_RULES.md)。下表是仓库级唯一写范围源：

| 角色 | 写范围 |
|------|--------|
| Lead | `hsbg/env/spec.py`、`hsbg/paths.py`、`docs/`（仲裁/合并）、`tests/test_integration.py`、`tests/test_live*`、`scripts/`、根配置、`git commit` |
| protocol-writer | `docs/AUDIT_PROTOCOL.md`、`docs/MULTI_AGENT_RULES.md`、`docs/AUDIT_CONSISTENCY.md`、`docs/LIVE_COLLAB_SECTION.md`、`AGENTS.md`（仅链接/写权限/基线说明） |
| live-automator | `hsbg/live/**`、`tests/test_live_*.py`、`docs/LIVE_AUTOMATION_PROTOCOL.md` |
| live-analyst / live-gap-analyst | `runs/live/analysis/**`（只读代码/截图/日志；gap 建议写入 `docs/LIVE_TO_SIM_GAP.md` 需 Lead/owner 协调） |
| env-builder / env-auditor | `hsbg/env/**`、`tests/test_env_*.py`、`hsbg/agents/**`、`tests/test_agents_*.py`、`docs/ENV_SPEC.md`、`docs/AUDIT_ENV_ACTIONS.md` |
| engine-analyst / engine-mech-auditor | `docs/ENGINE_API.md`、`docs/ENGINE_RL_READINESS.md`、`docs/ENGINE_NOTES.md`、`docs/AUDIT_ENGINE_MECHANICS.md`、`tools/probe_*.py`、`hsrl2/tests/**` |
| card-script-builder | `hsrl2/scripts/**`、`hsrl2/tests/test_batch_*`；`hsrl2/game.py` 等核心需 Lead 批准 |
| policy-builder | `hsbg/policy/**`、`hsbg/train/**`、`tests/test_policy_*.py`、`scripts/train_*.py` |
| bridge-analyst | `hsbg/bridge/**`、`tools/powerlog_*.py`、`tests/test_bridge_*.py`、`docs/REAL_GAME_BRIDGE.md` |

规则：

1. 遇到必须跨 scope 修改的情况：先读文件、改最小片段，并在回复里明确告知 Lead 与原 owner。
2. `hsrl2/game.py` / `combat.py` / `queue.py` / `tags.py`、`data/**`、根配置、依赖清单：
   只有 Lead 批准后才能改，且先写失败测试。
3. 代码生成器、格式化器、批量重写脚本视为写操作，需独占文件并先告知。
4. 禁止 `git checkout -- .` / `git reset --hard` / `git clean` / 批量格式化全仓；
   未经 Lead 授权不得 `git commit`。
5. 写前 30 秒内重新 `read` 目标文件；`FS_STALE_VERSION` 时 rebase 自己的最小改动后重试。
6. 任务领取与完成一律走共享任务板（`team_task_*`，claim 带 `expected_revision`），
   不抢占别人 `in_progress` 的任务；完成必须带证据（测试输出/文档路径/run_id）。

## 5. 数据现状（已知缺口）

- 引擎卡池数据基线 **37.0.0.255130**；原始 `CardDefs.xml` 不入库，重建流程见
  `docs/DATA_REBUILD.md`（`tools/generate_bg_data.py` / `tools/version_sync.py`）。
- 新卡/数值差异属于已知问题，不阻塞 RL 管线；但**不要**把"数据旧"当成环境 bug 去改引擎。

## 6. 验收门槛

任何改动合入前：
```powershell
python -m pytest hsrl2/tests -q      # 必须 0 failed
python -m pytest tests -q            # 必须 0 failed（taverngym 缺失时 conformance 自动 skip）
python tools/smoke_random_games.py --games 4 --seed 7   # crashes=0
python scripts/verify_all.py         # 推荐：一键全量门禁（引擎/项目/冒烟/环境验收/一致性/版本/
                                     # AutoTavern 跨引擎对拍/TavernBench 评分复现；缺 taverngym 的项 SKIP）
```

AutoTavern 借鉴升级新增命令（详见 [docs/AUTOTAVERN_UPGRADE.md](docs/AUTOTAVERN_UPGRADE.md) §6）：
```powershell
python -m pytest tests/conformance -q          # 跨引擎一致性套件（需 taverngym，缺失自动 skip）
python -m tools.ac_conformance.run --seeds 48  # 57 场景分类报告（MATCH/ENGINE_BUG/CONVENTION_DIFF/...）
python scripts/run_tavernbench.py --check      # TavernBench 数据完整性 + 已发布答案评分复现
python -m hsbg.backends.benchmark --games 10 --seed 0   # 双后端同 harness 吞吐基准
python scripts/validate_env.py --games 20 --check-invariants   # 结构不变量抽查（默认关闭）
```
**对拍台账纪律**：`tests/conformance` 的 expected 分类是
`docs/CONFORMANCE_AUTOTAVERN.md` 的结论快照；改引擎机制后若套件失败，必须
复核台账并按证据更新（不是放宽断言）。新发现的分歧按 `AC-xx` 编号记入台账，
注明证据等级（参照实现 / 官方 wiki / 真实 Power.log）与是否修复。

环境/策略层额外要求：
- 环境：同一 seed 两次 rollout 的观测/动作序列完全一致（确定性测试）。
- 策略：`forward` 对随机 batch 输出形状正确、masked softmax 不含 NaN；
  短 PPO 冒烟能跑通并保存/加载 checkpoint。

门禁纪律（完整矩阵见 [docs/AUDIT_PROTOCOL.md](docs/AUDIT_PROTOCOL.md) §8）：
- 记录「命令 + 时间 + passed/failed/耗时」，**不要**把历史数字当基线；
- 已知红只允许 `xfail(reason="<gap-id>")` 并登记 `docs/LIVE_TO_SIM_GAP.md`；
  禁止为变绿而删测试、放宽断言或 `skip` 掩盖；
- 纯文档改动：只需链接/路径自检，不要求跑 pytest，但不得改代码/测试；
- 改 `hsbg/env/spec.py`（唯一契约）= 同步 `docs/ENV_SPEC.md` 并升 `Observation.version`；
- baseline 变红且非本次改动引入：停止修复，记录并通知 Lead，不要顺手改别人 scope。

## 7. 第二阶段（P2）约定：Rust 主引擎 / 数据 / 标准动作观测

- **主引擎是 Rust `hsbg_engine`**（`rust/`，fork AutoTavern TavernGym，MIT）：
  - 机制实现以 AutoTavern 为基准；**偏离上游必须登记 `rust/FORK.md` §7 台账**
    （原因/证据/影响/回归）；有误处按官方/真实日志证据精修，禁止无证据改机制。
  - 数据在 `rust/crates/hsbg-engine/data/cards.json`（编译期嵌入）；**只允许由
    `tools/p2_data/gen_carddb_37.py` 生成**，不得手改；替换后 `cd rust && python -m pip install -e .` 重建。
  - 版本上报由数据 `meta` 驱动（`game_version()/server_rules_version()`），不得硬编码。
  - `hsrl2` 降级为 **legacy/对照 oracle/真实对局桥**：不做新功能，但必须保持回归全绿。
- **数据版本 = 37.0.0.255130（唯一）**；源数据在 `data/`，AutoTavern schema 产物在
  `data/p2/`（`cards_37.json` = 37 映射 + 36.6.3 compat 条目，保证脚本 registry 0 missing）。
  数值/卡面以 `data/`（官方 CardDefs 37.0.0）为准；不得用旧中文快照覆盖英文权威。
- **动作/观测标准 profile**（`hsbg/env/action_space_std.py`/`obs_std.py`）：
  - 前 245 动作与 AutoTavern **逐位一致**（金标测试保证），扩展段 ≥245 只追加不改前段；
  - 观测 3227 floats + 124 cards 与 AT `layout()` 32 项逐项一致；
  - legacy candidate/Observation v3 保留，但新训练/评测默认走 std profile（P3 接入）。
- **性能纪律**：引擎/热路径优先 Rust（`docs/PERF_ROUTE.md`）；C 加速仅在实测更快且
  维护成本可接受时采用（当前结论：Cython 零改造无收益，不引入 C 主路线）。
- **内容移植**：按 `docs/PORTING_37_PLAN.md` 分批（P1 = 18 卡：15 池内随从 + 1 主英雄
  技能 + 2 池内法术；黑暗赠礼/Timewarp 0 缺口）；每张卡先写验收用例（与 AT 行为对拍 +
  hsrl2 参考实现），再写 Rust content；不允许“占位脚本”混入池子。
- **可比性**：与 AutoTavern 论文对比时必须注明数据版本（37.0.0 vs 36.6.3）与动作/观测
  profile；同引擎同数据版本才可逐位比较，跨版本卡牌下标需按 card id 重映射。
