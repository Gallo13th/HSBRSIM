# AutoTavern 第二阶段（P2）：Rust 主引擎 + 最新数据 + 动作/观测统一

> 本阶段起点：第一阶段「AutoTavern 借鉴升级」已完成并推送
> （`docs/AUTOTAVERN_UPGRADE.md`，HEAD `347d396`）。
> 本文件记录用户新指令、阶段决策、本轮交付与验收证据、下一步 P1 内容移植计划。
>
> **P3 决策（2026-10-26，后续更新）**：本 P2 阶段之后，用户确定 **以 AutoTavern fork
> （`hsbg_engine`）为唯一主引擎、直接修补 AT 补完 37.0.0 模拟环境**；`hsrl2` 冻结为
> legacy/oracle。P3 见 `docs/AUTOTAVERN_P3_KICKOFF.md`。
>
> 用户指令（2026-10-26）：
> 1. **机制实现首先参考 AutoTavern**，有误的部分再做精修；**数值按最新版本**记录算。
> 2. **考虑运算效率**：Rust 更高效则使用 Rust；我们转写出的 C 如果更快也可以。
> 3. **动作空间统一对齐**（原因：AutoTavern 团队即将发表论文，HSBRSIM 要作为
>    可比基线）；游戏内支持但双方都没实现的操作，由我们补充。

---

## 1. 阶段决策（已与用户确认）

| 决策项 | 结论 |
|---|---|
| 主路线 | **Fork AutoTavern Rust 引擎为主引擎**（vendor/重命名为 `hsbg_engine`）；hsrl2 降级为 legacy/参照/真实对局桥 |
| 数据版本 | **仅 37.0.0.255130**（已确认 hsdata tag 255130 为最新）；引擎数据由官方 37.0.0 数据生成，36.6.3 内容作 compat/移植参考 |
| 动作/观测 | **全面对齐 AutoTavern**：前 245 动作索引/语义逐位一致 + AT 观测（3227 floats + 124 cards）作为标准 profile；游戏支持但未实现的操作作为 245+ 扩展；旧 checkpoint 作 legacy，接受重训 |
| 本轮范围 | Rust 引擎 fork 可构建可跑、37.0.0 数据生成/差分管线、37.x 内容移植缺口清单与计划、统一动作/观测规范与测试、性能基准（Rust/C/Python）与迁移计划、文档与门禁、提交并推送 |
| 暂不做 | 37.x 内容脚本的完整 Rust 移植（列 P1 分批计划）、策略重训（动作/观测标准 profile 迁移后另行排期） |

---

## 2. 本轮交付物（P2-A ~ P2-F）

| 任务 | 交付 | 状态/证据 |
|---|---|---|
| P2-A Rust 引擎 fork | `rust/`（hsbg-engine/hsbg-engine-py + maturin 构建）、`rust/FORK.md`、`docs/RUST_ENGINE.md`、`tests/test_rust_engine.py`、基准 | ✅ 构建/安装通过；11 tests passed；裸吞吐 ~257–277 games/s（与上游比 0.97–1.02） |
| P2-B 37.0.0 数据管线 | `tools/p2_data/gen_carddb_37.py`、`data/p2/cards_37.json`、`data/p2/MANIFEST.json`、`tests/test_p2_data.py`、`docs/DATA_37_MIGRATION.md`、差分报告、`data/p2/at_scripted_ids.json` | ✅ 3983 卡 = 3695 映射 + 288 compat；单人池 minion 273 / spell **73** / hero 118；AT registry 1290 id **0 missing**；`--check` 幂等；25 tests |
| P2-C 内容移植计划 | `tools/p2_delta/`、`docs/PORTING_37_PLAN.md`（分 kind 缺口/难度/分批/P1 must-have/缺失操作清单） | ✅ 覆盖矩阵可复现；P1 must-have **18 卡**（15 池内随从+1 主技能+2 池内法术，全 M 级）；缺失操作 3 项已处置（FreezeSlot/备用技能槽/异变不阻塞） |
| P2-D 动作/观测统一 | `hsbg/env/action_space_std.py`（245 + 扩展 29）、`hsbg/env/obs_std.py`（3227+124）、金标测试、`docs/ACTION_SPACE_STD.md`、`docs/OBS_STD.md` | ✅ 前 245 与 AT 逐位一致（action_name 差异 0/245、layout 差异 0/32）；扩展段 245..273（含 FreezeSlot）；57 tests |
| P2-E 性能路线 | `tools/p2_perf/`、`docs/PERF_ROUTE.md`（Rust vs Python vs C 实测/结论/迁移优先级） | ✅ Rust 裸引擎 ~49× hsrl2；端到端 78% 在 Python obs 解码；Cython 零改造 0.95–1.02× → C 不作主路线 |
| P2-F 集成 | 37 数据入 fork 重建、旧门禁保持全绿、P2 门禁、README/AGENTS/REPO_STATUS/ENV_SPEC 更新、commit+push | ✅ 37 数据已入 `rust/` 并重建（sha256 `c4826127…`）：`game_version()==37.0.0.255130`、`cargo test` **858/0**（36 套件）；37 数据裸引擎 **274.1 games/s/3.65ms**；`verify_all` **11/11 gates PASS**（含 rust_engine_build；engine 4890 passed / project 761 passed / conformance 13 / tavernbench 26/26，177.6s）；见 §5 |

### 2.1 P2-C 内容缺口结论（详见 `docs/PORTING_37_PLAN.md`）

- **37.0.0 相对 36.6.3 没有新增可玩卡 id、没有 BG 数值改动**：37 独有 122 个 id
  全部是异变定义（108）与 UI 按钮/token（14）；差异 = 赛季池轮换（46 张，
  minion +38/−5 等）+ 文本/标签口径。
- **AT 36.6.3 的 1301 个脚本 id 对 37 池内随从覆盖 258/273**；分 kind 缺口：
  池内随从 **15**、英雄主技能 **1**、池内法术 **2**、池内法术全量 5（3 张
  Duos 伪影已从单人池剔除）、饰品 161（offerable 上界 138）、异变 108、
  任务奖励 2、T7 1（与池内随从重叠）；**黑暗赠礼 47/47、Timewarp 253/253 零缺口**。
- **“37.0.0 可用”P1 最小内容集 = 18 张卡（全部 M 级）**：15 池内随从
  （13 张有 hsrl2 参考脚本 + 2 张需新写）+ 1 主英雄技能（Azshara）+ 2 池内法术。
  估算 P1 ≈ 5.5–11 人天（含数据管线与验收）。
- **缺失操作（游戏支持但两引擎都没实现）3 项**：① 按槽位冻结/解冻
  （37 卡面 `BG22_HERO_004p` 证据；已补为标准动作扩展 266..273 FreezeSlot）；
  ② HeroPower slot≥2（std 预留 246..249）；③ 异变系统（AT 无对应原语，37 无
  新增异变卡，不阻塞 P1）。其余 14 项操作已核对被 AT 覆盖（整馆解冻 toggle、
  酒馆 8=7+1 法术槽、Choose16、Cancel、Activate 目标、Discard、Timewarp 等）。

---

## 3. 集成要点与风险

- **卡表并集**：上游 `src/script.rs::registry()` 启动时对每个 content 脚本执行
  `db().id(id)`，`CardDb::id` 缺失即 panic（`cards.rs:406`）。因此
  `cards_37.json` = 37.0.0 映射卡 **+ 36.6.3 compat 条目**（`pools=[]`、
  `reachable=false`，仅供脚本解析/测试，不进入池子）；生成器需断言
  AT content 引用的所有 card id 可解析（0 missing）。
- **数据版本元信息**：`meta.client_version=37.0.0.255130`、
  `server_patch=37.0.0`；fork 的 `GAME_VERSION`/`SERVER_RULES_VERSION`
  改为由 meta 驱动，避免硬编码漂移。
- **旧存档/状态兼容**：卡表 fingerprint 变化后旧 `state_json` 会被
  `check_loaded` 拒绝（符合预期）；TavernBench 的 36.6.3 states 不能用
  37 数据加载（TavernBench 仍以上游 36.6.3 环境与 vendored 数据独立运行）。
- **动作空间扩展**：245+ 扩展（至少解冻）只加在 Python 标准 profile；
  Rust 引擎侧对扩展动作的支持列入 P1 内容/操作移植计划。
- **性能**：Rust 引擎裸吞吐 ~275 games/s（36.6.3 数据），端到端瓶颈在
  Python 侧观测解码；路线见 `docs/PERF_ROUTE.md`。

---

## 4. 下一步（P1 内容与机制移植，按 `docs/PORTING_37_PLAN.md`）

1. **P1-A 数据可用**：37 数据入 fork 后跑通 bot 对局/BatchEnv/自对弈；
   补齐 registry 需要的 compat 内容与版本常量。
2. **P1-B 池内随从与英雄**：37.x 缺失脚本的池内随从/英雄（含文本/数值
   变化）优先移植到 Rust content；按 `PORTING_37_PLAN.md` 的 S/M/L 分批。
3. **P1-C 系统机制**：37.0.0 新系统（异变/Deity/Timewarp 相关状态等）在
   Rust 引擎中的数据/机制支持；AT 有误处（如 AC-04）精修。
4. **P1-D 动作/观测标准 profile 落地**：env/策略/训练/评测切换到 std
   profile（245+扩展 / 3227+124 obs），重训 BC/PPO 基线；旧 checkpoint 保留。
5. **P1-E 可比性评测**：同动作空间/观测/评测协议下产出与 AutoTavern 可比
   的基线数字（注明数据版本差异 37.0.0 vs 36.6.3）。

---

## 5. 集成结果（P2-F，2026-10-26）

### 5.1 37.0.0 数据已进入 Rust 主引擎

- `rust/crates/hsbg-engine/data/cards.json` ← `data/p2/cards_37.json`
  （sha256 `4ba9cdf7…3135bd`，3983 卡 = 3695 映射 + 288 compat；单人池
  minion 273 / hero 118 / spell 73 / trinket 236）；
- 重建：`cd rust && python3 -m pip install -e .`（maturin succeeded）；
- 冒烟：`hsbg_engine.game_version()=="37.0.0.255130"`、
  `server_rules_version()=="37.0.0"`、`db_info()==(3983,'37.0.0.255130','37.0.0')`；
  20 局 bot 对局 224 games/s、state_json 往返一致、BatchEnv 100 cycles 正常
  （registry 对 1290 个 AT 脚本引用 id 0 panic，compat 条目生效）；
- 随数据替换的代码改动仅 1 处测试断言（`cards.rs::pool_counts_match_bundle`
  273/118/73/236），无机制改动；版本上报由数据 meta 驱动（`rust/FORK.md` §11）。

### 5.2 37 数据基准（与上游 36.6.3 对照）

| 指标 | hsbg_engine（37） | 上游 taverngym（36.6.3） |
|---|---:|---:|
| 裸引擎（8 座全 bot，1000 局） | **274.1 games/s，3.65 ms/局** | 272.8 games/s，3.67 ms/局 |
| 端到端 8 人局（Python 驱动） | 3.57 ms/局（279.9 games/s） | 3.62 ms/局 |
| SoloEnv 观测+决策循环 | 792.9 games/s | 801.3 games/s |
| BatchEnv（64 局，threads=8） | 925.9 episodes/s | 916.9 episodes/s |

结论：数据替换未引入吞吐偏离（比值 1.00–1.01），37.0.0 与 36.6.3 的数值/平均回合数
（15.4）一致（印证 P2-B 的“无 BG 数值改动、差异=池轮换”结论）。Rust 测试最终全绿：
`cargo test --release -p hsbg-engine` **36 套件 858 passed / 0 failed / 0 ignored**
（6 个 36.6.3 内容断言已按 37 数据重算：eligible 276、文本单复数、Naga 回池；
无 ignore/删除测试），`cargo test --lib` 15/0，`pytest tests/test_rust_engine.py`
10 passed + 1 设计性 skip。数据 sha256 `c482612727c2618e…`。

### 5.3 仍需下一步（P1 内容移植）

Rust 引擎已“37.0.0 数据可运行”，但 37 池内仍有 AT 未实现脚本的卡（P1 must-have
18 张，见 `docs/PORTING_37_PLAN.md`）——在这些卡完成 Rust content 移植前，其机制
行为不等价于 37 官方实现（可能按 36.6.3 脚本/无脚本处理）；P1 批次与验收方式见
`docs/PORTING_37_PLAN.md` §4/§5。

### 5.4 最终门禁（2026-10-26 13:27，冻结工作树）

`python3 scripts/verify_all.py` → **11/11 gates PASS，0 skipped，177.6s**：

| gate | 结果 |
|---|---|
| rust_engine_build | PASS（cargo build --release -p hsbg-engine，54.2s） |
| engine_tests | 4890 passed / 6 skipped（legacy hsrl2） |
| project_tests | **761 passed / 63 skipped**（含 P2 新增数据/动作/观测/Rust 引擎测试） |
| smoke_8p | completed=8 / incomplete=0 / **crashes=0** |
| env_validation | ok=true，failures=[]（含 `--check-invariants`） |
| env_bench | 0 errors / 0 invalid |
| hashseed_determinism | 7 passed（双 PYTHONHASHSEED 子进程） |
| official_consistency | 无语料 SKIP（不误红） |
| version_check | 四信号成功（项目数据 37.0.0.255130 为最新） |
| taverngym_conformance | 13 passed |
| tavernbench_check | CHECK PASSED 26/26 |

专项：`cargo test --release -p hsbg-engine` **858 passed / 0 failed**（36 套件，
37 数据；6 个 36.6.3 内容断言已按 37 重算，无 ignore）；`cargo test --lib` 15/0；
`pytest tests/test_rust_engine.py` 10 passed + 1 设计性 skip；
`pytest tests/test_action_space_std.py tests/test_obs_std.py` 57 passed；
`pytest tests/test_p2_data.py` 27 passed；`tools/p2_data --check`、`tools/p2_delta/run_all.py`、
`tools/p2_perf/run_all.py` 均 exit 0。
