# CLEANUP_PLAN — 历史版本清点与清理方案（2026-11-04）

> 只读清点产出，**本文件不执行任何删除/移动**；执行需 Lead 批准。
> 清点时刻：2026-11-04 00:00–00:15（训练进行中，`runs/` 数字持续增长）。体积=`du` 实测，引用=`grep` 全仓（docs/scripts/tests/hsbg/tools/README/AGENTS/Makefile）。
> 基线：HEAD=`194fc5b`，1305 tracked / 246 commits / `.git` 413M；`/home/data` 44T 用 37T、余 5.3T（88%）。

## 0. 一页结论

| 项 | 实测 | 判定 |
|---|---|---|
| `runs/` | **206G / 249 目录**；`.pt` 2620 个 = **197.5G** | 主要回收区，可回收 **~195G** |
| `data/` | 6.1G（650 tracked + 大量 gitignored） | **保留**（重生成成本高） |
| `rust/target` | 2.7G（gitignored 构建产物） | 可删，重编译 ~10min |
| `docs/` | 122 文件 = 114 md + 8 png（并行任务仍在新增） | 25 篇历史报告→`docs/_history/` |
| `scripts/` | 143 tracked + 4 未跟踪 + `__pycache__` 97 pyc | 12 篇一次性脚本→`scripts/_archive/` |
| `$t/` `.tmp_trace/` | 148K / 24K，**35+1 个 tracked 文件** | 归档（`git mv`，保历史） |
| 杂项 | `" "` 空目录 4K、`.pytest_cache` 100K、`.ruff_cache` 28K | 直接删 |
| `.git` | 413M | 保留，暂不 gc |
| `reversed/` | 16M（hsdata 37.0.0.255790，gitignored） | 保留（可重下但不值当删） |

**最高危三件事**（详见 §6）：① `scripts/auto_chain.py` 工作区多一行调 `/tmp/cleanup.sh`，该脚本会 `kill -9` 所有 HSBRSIM GPU 进程与全部 `train_entity_sync`——**正在跑的 s73 训练会被它杀**；② 删 `runs/az_entity_s61/{eval/ckpt_020026719.pt,trainer.pt}`（唯一最佳点/唯一精确续训源）；③ 删 `data/real_library/winner_library.jsonl`（chain 训练唯一人类库输入，无生成脚本）。

## 1. 体量与引用清点

| 路径 | 体积 | 规模 | git | 引用/价值 | 处置 |
|---|---:|---|---|---|---|
| `runs/` | 206G | 249 目录，2620 pt | ignored | 训练产物；文档引用约 40 个 run 名 | **A 主要删除区** |
| `data/` | 6.1G | 650 tracked + ignored jsonl/npz | 混合 | 训练/评测唯一数据源 | **C 保留** |
| `rust/` | 2.7G | 源码 4.8M+28M；`target/` 2.7G | target ignored | 引擎权威 | 源码 C，target A |
| `.git` | 413M | 246 commits | — | 历史资产 | C |
| `reversed/` | 16M | 3 文件 XML | ignored | 官方原始 hsdata（数据更新用） | C（可 B） |
| `docs/` | 3.6M | 122 文件（114 md+8 png） | 118 tracked | 当前设计 + 历史报告混杂 | B/C 见 §4 |
| `scripts/` | 6.0M | 143 tracked + 4 未跟踪 + 97 pyc | 混合 | 训练/评测/探针入口 | B/C 见 §5 |
| `benchmarks/` `tests/` `hsbg/` `tools/` | 14M/6.7M/5.1M/136K | — | tracked | 门禁与核心栈 | C |
| `$t/` | 148K | 35 tracked（s22–s26 临时脚本） | tracked | 历史实验，**零引用** | **B 归档** |
| `.tmp_trace/` | 24K | 1 tracked（`final.py`，human trace 分析） | tracked | 历史一次性分析 | **B 归档** |
| `" "`（空白名目录） | 4K | 空 | 未跟踪 | 误建 | **A 删除** |
| `.pytest_cache` `.ruff_cache` | 100K/28K | — | ignored | 缓存 | A |
| 根目录杂项 | 8K | `.lead_probe.txt`、`_audit_*.{sh,py}`（并行任务产生，数量在变） | 未跟踪 | 临时审计产物 | A（用完即删/移 `/tmp`） |

## 2. `runs/` 体积构成与回收估算

### 2.1 按组件（全仓 206G）

| 组件 | 体积 | 内容 | 策略 |
|---|---:|---|---|
| `*/snapshots/` | 66.4G | 每 100 iter 的 model+trainer 快照（keep 4） | **删**（保留清单除外） |
| `*/trainer.pt` | 26.4G | 精确续训状态（optimizer/RNG） | 删，仅留 s61/s73 |
| `*/_weights/` | 26.0G | 每 iter 权重版本（keep-versions 3） | **删** |
| `*/eval/` | 10.5G | 185 个评测 ckpt（65M/个）+ json/log | 删 ckpt，**留 json/log** |
| `*/model.pt` | 9.8G | 最新模型 | 删，保留清单除外 |
| `*/_pool_weights.pt` | 9.2G | 自对弈池权重 | **删** |
| `*/_proc_tmp/` | 3.8G | 采集中间临时文件（167 个目录） | **删**（纯垃圾） |
| `*/history.jsonl` | 1.0G | 逐 iter 指标（**元数据**） | **留** |
| `*/summary.json` | 0.4G | 聚合指标（**元数据**） | **留** |
| 其余（嵌套 `armA–D`、`B/`、`smoke/`、`checkpoints/` 等 pt） | ~49G | ab_* 实验各臂权重 | 删 |

### 2.2 按家族（单次 `du` 口径，合计≈205G）

| 家族 | 目录数 | 体积 | 说明 | 策略 |
|---|---:|---:|---|---|
| `az_entity_s*` | 83 | 88.6G | s1–s73 主训练线 | 只留 s61/s73 内核，其余删权重 |
| `ab_*` | 60 | 57.1G | A/B 臂（每臂 `armA–D`、`smoke` 各 ~770M） | 删权重，留 `SUMMARY.json`/日志 |
| 其他杂项 | 110 | 35.5G | `library`/`exam`/`comp_lines`/`infer_search_*`/`scaling_signal` 等离线实验 | 删权重，留 json/md |
| `az_entity_other` | 15 | 16.7G | `_kl_30m`/`t1p`/`p1m_s0` 等 | 删权重 |
| `compound_*` `small_expert*` `az_arch_ab` | 9 | 7.0G | 复利/小模型线（已归档结论） | 删权重 |
| 按 mtime：10 月 / 11 月 | 145 / 103 | ~145G / ~74G | 两口径求和有 ~14G 硬链接重复 | 以总量 206G 为准 |

### 2.3 回收估算（保守）

```text
保留集（§3-C）: s61 ckpt×2+trainer+model+snapshots ≈1.1G
                s73 运行中                          (不统计)
                per-doc-cited-run 各 1 个 ckpt ×10 ≈0.65G
                champion_c0_2279.pt 61M + eval_panel 135M
L0 元数据: history/summary/latest/eval json/log ≈1.6G
可删 pt 权重: 197.5G − ~2.0G ≈ 195G
外加 _proc_tmp 3.8G、rust/target 2.7G、caches 0.13G
→ 合计可回收 ≈ 196~198G；runs/ 206G → ~11G，磁盘 5.3T → ~5.5T
```

## 3. 三分批清单

### A. 直接删除（不可逆，先跑 manifest；**s73 训练期间不要删 s61/s73 及 `_smoke_p2b01`**）

| # | 路径 | 体积 | 理由 | 风险 | 回滚 |
|---|---|---:|---|---|---|
| A1 | 历史 run 的 `snapshots/`（除 C1/C2/C5） | 65.5G | 中间快照，指标已在 history | 不能从任意 step 续训 | 无（靠保留 ckpt + 重训）；manifest 留证 |
| A2 | 历史 run 的 `_weights/` | 25.8G | 每 iter 权重冗余 | 同上 | 无 |
| A3 | 历史 run 的 `trainer.pt`（除 s61/s73） | 26.0G | 精确续训状态，仅当前块需要 | 旧 run 不可逐位续训 | 无 |
| A4 | 历史 run 的 `model.pt`（除清单） | 9.5G | 可由 ckpt 替代 | 低 | 无 |
| A5 | 历史 run 的 `_pool_weights.pt`/`start_model.pt`/`checkpoint*` | 9.1G | 自对弈池临时权重 | 低 | 无 |
| A6 | 历史 run 的 `eval/ckpt_*.pt`（除保留清单） | ~11.2G | 185 个评测点，仅需最佳/节点 | 失去历史可复现点 | 保留 10 个代表点（§3-C） |
| A7 | `*/_proc_tmp/`、残留 `.train.lock` | 3.8G | 采集中间垃圾 | 极低 | 无 |
| A8 | `s62–s65` 整目录权重（`eval/` 为空） | ~4.5G | 失败链块，无新 ckpt，账本数字错 | 低（`CHAIN_300M.csv` 仍留证据） | 无 |
| A9 | 纯 smoke 权重：`s58_smoke`、`_smoke_p2b01`（结束后）、`ab_*_smoke` | ~5G | 冒烟产物 | 无 | 无 |
| A10 | `rust/target/` | 2.7G | 构建产物，gitignored | 下次编译变慢 | `cargo build --release` 重建 |
| A11 | `.pytest_cache/`、`.ruff_cache/`、`scripts/__pycache__/`（97 pyc） | ~0.13G | 缓存 | 无 | 自动重建 |
| A12 | 根目录空白名目录 `" "` | 4K | 误建空目录 | 无 | 无 |
| A13 | 根目录未跟踪审计临时文件 `.lead_probe.txt`、`_audit_*.{sh,py}` | <50K | 并行任务中间产物 | 需先确认任务已结束 | 重跑审计即可 |

### B. 归档（可逆，优先 `git mv` 保历史）

| # | 现状 | 去向 | 体积 | 理由 | 风险/回滚 |
|---|---|---|---:|---|---|
| B1 | 25 篇历史报告（§4 表） | `docs/_history/` + `_history/README.md` 索引 | <1M | 降噪，保留结论链接 | 低；`git mv` 可 revert |
| B2 | `docs/{human_arena_pending.png,human_arena_ui.png,training_curve_300m.png}` | `docs/assets/` | 0.5M | 资源归位（2 处链接需改） | 低 |
| B3 | 12 篇一次性脚本（§5 表） | `scripts/_archive/` + `README.md` | ~0.3M | 防误用已停用路径 | 低；`git mv` |
| B4 | `$t/`（35 文件） | `scripts/_archive/s22_s26/` | 148K | 历史实验脚本，零引用 | 低；`git mv` |
| B5 | `.tmp_trace/final.py` | `scripts/_archive/` | 24K | 一次性 human trace 分析 | 低 |
| B6 | `scripts/watch_s61_then_chain.sh`（未跟踪） | `scripts/_archive/`（不 commit 到主入口） | 239B | 会让 s61 结束自动起 chain，与今晚手动块冲突 | 低；文件保留 |
| B7 | `runs/CHAIN_300M.csv|log`（账本错误证据） | `runs/_archive/300m_chain/` | 84K | 保留“80/100 行错账”证据 | 低 |
| B8 | `reversed/hsdata_255790/` | 原处保留（或 `data/raw/`） | 16M | 官方原始数据，数据更新要用 | 无 |

### C. 保留（不可删）

| # | 对象 | 体积 | 理由 |
|---|---|---:|---|
| C1 | `runs/az_entity_s61/eval/ckpt_020026719.pt`（+`ckpt_010017876.pt`、`human_*.json/log`、`trainer.pt`、`model.pt`、`latest.json`、`snapshots/step_000201/`） | ~1.1G | **当前最佳点**（TRAINING_CURVE_300M 引用 4 次；strength 323.5/rank 6.083）+ 精确续训源 |
| C2 | `runs/az_entity_s73/`（今天 00:10 起的 20M 块） | 运行中 | 在跑训练，任何清理不得触碰；其 `ckpt_*` 是下一块起点 |
| C3 | `runs/eval_panel/`（2 ckpt + `history.json` + 面板 json/log） | 135M | 唯一评测口径（`scripts/eval_panel.sh`） |
| C4 | `runs/champion_c0_2279.pt` | 61M | 历史冠军点，脚本/文档引用 |
| C5 | 每个文档引用过的历史 run 留 **1 个** `eval/ckpt_*.pt` 作可复现证据（s14、s8b、s13、s15、s10、s25、s59、s60b、s72 等 ≤10 个） | ~0.65G | 结论可复现 |
| C6 | **全部** run 的 `history.jsonl`、`summary.json`、`latest.json`、`eval/*.json`、`*.log`、`BLOCK_INFO.txt` | ~1.6G | 曲线/审计元数据，删了等于重跑 |
| C7 | 核心文档（§4.2） | ~1M | 当前设计与契约 |
| C8 | 核心脚本（§5.1） | ~2M | 训练/评测/门禁入口 |
| C9 | `data/`、`reversed/`、`benchmarks/`、`tests/`、`hsbg/`、`rust/`（源码）、`.github/`、`.git/` | ~9.5G | 数据、门禁、引擎、历史 |
| C10 | git 基线 tag `pre-cleanup-2026-11-04` | — | 所有 git 侧操作的回滚锚点 |

## 4. `docs/` 清理

### 4.1 历史报告 → `docs/_history/`（25 篇；括号=当前入链次数）

| 文档 | 入链 | 归档理由 |
|---|---:|---|
| `STAGE3_PLAN.md` / `STAGE5_REPORT.md` / `STAGE6_REPORT.md` | 0/0/1 | 旧 stage 配方与阶段报告，已被 s73 干净配方取代 |
| `TRAINING_RUN_2026-10-27.md` | 1 | 1h tiny 试训负结果（README 链接，需同步改） |
| `THROUGHPUT_FINAL_REPORT.md` / `THROUGHPUT_PLAN.md` / `THROUGHPUT_TIMELINE.md` / `TRAINING_THROUGHPUT_NOTES.md` | 0/2/3/3 | 10-28 吞吐战役报告，结论已进 `TRAIN_THROUGHPUT.md` |
| `COMPUTE_BENCHMARK.md` / `COMPUTE_PLAN_4GPU.md` / `RESOURCE_PROFILE.md` | 1/1/0 | 旧算力基准/计划（README 链接 2 处需改） |
| `ASTRA_FINAL_REVIEW.md` / `REVIEW_PPAI.md` / `REVIEW_PLATEAU.md` / `REVIEW_LIBRARY_POOL.md` / `REVIEW_MIRROR_SNAPSHOT.md` / `REVIEW_TRAJECTORY_LIBRARY.md` / `REVIEW_RUST_COLLECTOR.md` | 0/0/1/0/0/0/0 | GPT-6 Astra 一次性终审记录（结论已进 DECISIONS） |
| `RUST_COLLECTOR_PLAN_2S.md` / `MIRROR_PROBE_DIAGNOSIS.md` | 0/2 | 已停路线（Rust collector spike / 镜像 arm3 诊断） |
| `MERGE_CHECKLIST.md` | 0 | 并行 agent 时代清单，已过时 |
| `HUMAN_PLAY_3GAMES.md` / `HUMAN_TRACE_CHECK.md` | 0/0 | 一次性 3 局/轨迹核对报告 |
| `FIRESTONE_MIX_AB.md` / `SMALL_FULLGAME_RL.md` | 0/0 | s13/s22 阶段 AB 报告，结论已进 §3 台账 |
| `RUST_COLLECTOR.md` | 7 | 进行中 spike 已停；先留原位，第二阶段归档 |

### 4.2 必须保留（当前设计/契约）

| 类别 | 文档 |
|---|---|
| 契约 | `AGENTS.md`、`README.md`（根）、`docs/{ARCHITECTURE,ENGINE,ACTION_OBS,AT_LAYOUT_CONTRACT,DATA,VERIFICATION,QUICKSTART}.md` |
| 决策/记忆 | `docs/{DECISIONS,PROJECT_MEMORY,EXPERIMENTS,AGENT_TEAM}.md` |
| 训练 | `docs/{TRAINING,TRAINING_DESIGN,TRAINING_RUNTIME_HANDOFF,MULTISTAGE_TRAINING,TRAINING_COMPILE,TRAIN_THROUGHPUT,EVAL_PANELS,TRAINING_CURVE_300M}.md` |
| AZ/搜索 | `docs/{AZ_MCTS_SELFPLAY_DESIGN,AZ_IMPERFECT_SEARCH_DESIGN,AZ_AUTOTAVERN_MODEL_TRANSFER,RESEARCH_PLAN_V2,INFERENCE_SEARCH}.md` |
| 复利/comp | `docs/{COMP_SCRIPTS,COMP_SCRIPTS_V2,COMP_SCRIPTS_TRAINING,COMPOUND_BC,COMPOUND_CHAINS,COMPOUND_INCOME,COMPOUND_SCRIPT,COMPOUND_TEACHER}.md` |
| 人类数据/对抗 | `docs/{HUMAN_ARENA,HUMAN_ARENA_UI_SPEC_V2,HUMAN_BOARD_OPPONENT,BC_AUX,BC_PRETRAIN,FIDELITY_INJECTION,ARENA_GUARD,MOVE_GUARD,REWARD_SHAPING,ECONOMY_SANDBOX}.md` |
| 审计（新） | `docs/{BUG_AUDIT_SOL,ASTRA_REVIEW_2026-11}.md` |

> `INTERFACE_*` 在仓库中**不存在**（全仓 0 命中）；接口契约由 `ACTION_OBS.md` + `AT_LAYOUT_CONTRACT.md` + `ENGINE.md` 承担，不另建。

### 4.3 死链（13 个被引用但不存在的文档）

`ACTION_SPACE_STD`、`AZ_1K_VALIDATION`、`AZ_PURE_SEARCH_TEST`、`BELIEF_STATE`、`DATA_37_MIGRATION`、`EXPERIMENT_LEDGER`、`HUMAN_TARGETS`、`OBS_STD`、`OPTIONS_HRL`、`PORTING_37_PLAN`、`RUST_ENGINE`、`TAVERNGYM_BACKEND`、`TRAINING_PLAN_AUTOTAVERN`（`.md`）
引用方：`docs/RESEARCH_PLAN_V2.md`、`scripts/{train_az_ppo,az_eval_search,human_arena,az_selfplay_smoke,comp_opponent_probe}.py`、`tests/{test_rust_engine,test_p2_data}.py`。处置：指向现存等价文档（如 `RUST_ENGINE→ENGINE`、`OBS_STD/ACTION_SPACE_STD→ACTION_OBS`）或删除链接。

## 5. `scripts/` 清理

### 5.1 保留（核心入口，33 个）
`train_entity_sync.py`、`train_block_clean.sh`、`chain_300m.sh`、`eval_panel.sh`、`quality_monitor.py`、`human_panel_eval.py`、`human_arena.py`、`async_eval.py`、`train_az_ppo.py`、`az_selfplay_smoke.py`、`az_eval_search.py`、`train_stage1.sh`、`bootstrap.sh`、`verify_all.py`、`run_tavernbench.py`、`arena_{agent,client}.py`、`comp_scripts.py`、`comp_opponent_probe.py`、`train_compound_{bc,ppo}.py`、`eval_compound_bc.py`、`bc_pretrain.py`、`train_search_bc.py`、`import_real_library.py`、`mix_human_libraries.py`、`build_board_problems.py`、`calibrate_strength.py`、`infer_search_{ab,formal_ab,formal_summary}.py`、`plot_{training_curves,iteration_timeline,resource_profile}.py`、`bench_{process_pool,collect_profile}.py`。

### 5.2 归档 12 篇（零引用且已停用路径）
`mechanism_audit.py`、`oilcan_prior_probe.py`、`probe_frozen_strength.py`、`quality_watch.py`、`plot_scaling_1m.py`、`plot_stage_curves.py`、`plot_strength_stages.py`、`plot_throughput_curves.py`、`curriculum_report.py`、`scaling_signal_run.sh`、`scaling_signal_run_v2.sh`、`train_block_clean_old`（如有）→ 统一入 `scripts/_archive/`。
另 14 篇零引用但 11-01 后新增（`best_of_n`、`bon_*`、`eval_lookahead`、`policy_hybrid`、`policy_lookahead`、`real_board_decompose`、`rich_features`、`ingest_human_play`、`gen/relabel_search_v2`、`tier_split_eval` 等）**暂留**，等下一轮实验判生死。

### 5.3 未跟踪文件处置（4 个）
| 文件 | 判定 | 动作 |
|---|---|---|
| `train_block_clean.sh` | **当前** 20M 块启动器（s73 真源） | commit 入库 |
| `chain_300m.sh` | 当前 300M 链驱动，docs 引用 10 次 | commit（先按 `BUG_AUDIT_SOL` P0-1 修 `_submit_eval`/账本断言） |
| `watch_s61_then_chain.sh` | 会按 s61 结束自动起 chain（已被今晚手动块取代，且会和 s73 抢卡） | 归档不入主入口 |
| `comp_opponent_probe.py` | 当前复利探针 | commit |

## 6. 残留进程 / 定时器（只读核查，处置待批）

| 对象 | 现状 | 归属 | 建议 |
|---|---|---|---|
| pid 615045 `train_entity_sync → runs/az_entity_s73` | 00:10 起，20M 块，`--minutes 400` | **本项目·正在训练** | **不动**；清理必须等它结束 |
| pid 3662893 `runs/az_entity_s19/post_eval.py` | 已挂 **2d10h**，CPU 0%，日志停在 11-01 15:11 | 本项目·僵尸 | `kill`（先 TERM 后 KILL）释放句柄 |
| `/tmp/s22/s27{,b,c,d}_monitor.py`（4 进程） | 1d+，只读 `runs/az_entity_s27*/history.jsonl`，**无拉起能力** | 本项目·旧监控 | 可 `kill`；不影响训练 |
| `/tmp/final_chain.sh`（pid 2904593，2d13h） | 在 `sbdd_baselines` 等排名结果 | **别的项目** | **勿动**（已确认非 HSBRSIM） |
| `scripts/watch_s61_then_chain.sh` / `auto_chain.py` / `chain_300m.sh` | **无进程**；`/tmp/chain.out` 0 字节；`CHAIN_300M.log` 止于 23:51 且带 semaphore 泄漏告警 | 本项目·已停 | 无需 kill；见 6.1 |
| `crontab -l` | `no crontab for gaoletian` | — | 无自动拉起 |
| `systemctl --user list-timers` | 仅 `systemd-tmpfiles-clean`、`grub-boot-success` | 系统 | 与本项目无关 |
| `/tmp` 总体 | 74G（含其他项目产物） | 混合 | **不在本方案范围**；本项目冒烟 pt 约 2–3G 可选清理 |

### 6.1 ⚠️ 最高危：`auto_chain.py` 被插入 `kill -9` 调用
`git diff scripts/auto_chain.py` = **+1 行**：`subprocess.run(["bash","-lc","bash /tmp/cleanup.sh ..."])`，位于每块训练**之前**。
`/tmp/cleanup.sh` 内容：按 GPU pid 找 cwd 含 `HSBRSIM` 的进程 `kill -9`，再 `pgrep -u gaoletian -f train_entity_sync | kill -9`，并删 `/dev/shm/hsb_az_*`。
→ 任何人再跑 `auto_chain.py`，会**杀掉正在跑的 s73（以及任何同机 HSBRSIM 评测）**。处置：人工删除该行（用编辑，不用 `git checkout`）；`/tmp/cleanup.sh` 改名或删除，并在 `DECISIONS.md` 记一条“禁止在仓内脚本调用 /tmp 清理器”。

## 7. git 提交策略（禁止 `git reset --hard` / `checkout -- .` / `clean`）

原则：**先打 tag，再分批小 commit；归档用 `git mv` 保历史；runs/ 被 gitignore，只做文件系统操作并留 manifest；绝不 force push。**

| 步骤 | 命令要点 | 内容 |
|---|---|---|
| 0 基线 | `git tag -a pre-cleanup-2026-11-04 -m "before history cleanup"`；把 `git status`/`rev-parse HEAD` 存 `docs/_history/CLEANUP_BASELINE.txt` | 回滚锚点 |
| 1 docs | `git mv` 25 篇→`docs/_history/`；新建 `docs/_history/README.md` 索引；改 README 3 处 + EVAL_PANELS/RESEARCH_PLAN_V2 各 1 处链接；修 13 死链 | `docs(history): archive superseded reports` |
| 2 scripts | `git mv` 12 篇→`scripts/_archive/`；新建 `scripts/README.md`（入口/归档两栏）；`git add` 4 个未跟踪当前脚本（watch 脚本除外） | `chore(scripts): separate entrypoints from one-offs` |
| 3 scratch | `git mv '$t' scripts/_archive/s22_s26/`；`git mv .tmp_trace/final.py scripts/_archive/`；`git mv` 3 个 png→`docs/assets/` | `chore(repo): park s22–s26 scratch and assets` |
| 4 fix | 编辑 `scripts/auto_chain.py` 删除 rogue 行；`.gitignore` 增 `_audit_*`、`.lead_probe*`、`runs/_smoke_*`、`docs/_history/*.tmp` | `fix(chain): drop /tmp cleanup call; ignore transient audits` |
| 5 runs | 不涉及 git；先写 `runs/_CLEANUP_MANIFEST_2026-11-04.tsv`（路径+字节），再按 A1→A9 删，保留 §3-C | 文件系统 |
| 6 收尾 | `python scripts/verify_all.py --fast`（纯文档/移动后确认无 import 断裂）；`git status`；`git tag -a cleanup-done-2026-11-04` | 门禁 + 第二锚点 |

注：每个 commit 只做一类事；**不要**把 docs 移动和代码修改混在一起；已 commit 的删除若要撤回，用 `git revert <sha>`（允许），不要 reset。

## 8. 执行顺序（建议）

| 阶段 | 动作 | 前置 |
|---|---|---|
| P0（立即可做，需批） | ① 删 `auto_chain.py` rogue 行；② `kill` s19 post_eval + 4 个 s27 监控；③ `/tmp/cleanup.sh` 停用 | 确认 s73 训练不受影响（它不经 auto_chain） |
| P1（低风险，可与训练并行） | git 脚本 §7 步骤 0–4（docs/scripts/scratch 归档 + 死链修复） | P0 完成 |
| P2（**等 s73 结束**） | runs 权重清理：manifest → A8/A9（失败块/smoke）→ A1–A6（全量历史）→ 保留 §3-C | s73 结束；先备份 s61/s73 清单 |
| P3（随时） | A10–A13：`rust/target`、caches、空白目录、根目录临时文件 | 无 |
| P4 | 门禁 + 体积核对 + `CLEANUP_DONE.md`（记录实际回收 GB 与残留风险） | P2 完成 |

**空间预期**：仓库 ~216G → **~18G**（runs 206→11G、rust 2.7G→30M、data 6.1G 保留），磁盘余量 5.3T → ~5.5T。
**不可逆项**：A1–A9 的权重删除（靠 C1–C5 保留点 + history 复现）；其余均可 `git revert` / 重生成。
