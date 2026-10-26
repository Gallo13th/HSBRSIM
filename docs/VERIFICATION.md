# 验收快照（VERIFICATION）

> 快照时间：2026-10-18 20:05 ｜ 数据：官方 37.0.0.255130 ｜ 机器：Windows 11 / Python 3.13 / RTX 4060 Ti
>
> 本文件记录**每条验收命令的预期输出形态**，用于交付/CI 对照。
> 数值会随卡脚本增加而变化；以 "门禁" 列（PASS/0 failed/0 crash）为硬标准，
> 指标（测试数/匹配率）为趋势参考。

## 1. 一键门禁

```powershell
python scripts/verify_all.py
```

预期：**7/7 gates PASS**（约 170–210s）：

| gate | 预期 |
|------|------|
| engine_tests | 0 failed（当前 4,588 passed / 2 skipped） |
| project_tests | 0 failed（当前 403 passed / 1 skipped） |
| smoke_8p | crashes=0，completed=8 |
| env_validation | `ok: true`，failures=[] |
| env_bench | 0 invalid / 0 reject，单局 ~0.3–0.7s |
| official_consistency | exit 0（硬门禁：DATA_GAP=0、behavior_mismatch=0、干净子集 100%） |
| version_check | 四信号检测成功（client/project/hsdata 对齐） |

产物：`runs/verify_all.json`。

## 2. 引擎与数据

```powershell
python -m pytest hsrl2/tests -o addopts='' -q
python -m pytest tests -o addopts='' -q
python tools/smoke_random_games.py --games 8 --seed 2000
python tools/audit_card_registry_v2.py --strict
```

| 命令 | 预期 |
|------|------|
| hsrl2/tests | 0 failed（当前 4,588 passed） |
| tests | 0 failed（当前 403 passed） |
| smoke 8p | crashes=0 |
| registry audit | 池内覆盖 99.6%（279/280，唯一 Geomagus DEFERRED）；`--strict` 因该已知缺口 exit 1 |

## 3. 环境 / RL 接口

```powershell
python scripts/demo_env.py --seed 42
python scripts/validate_env.py --games 30
python scripts/audit_env_coverage.py --games 40
python scripts/bench_env.py --seeds 20
python -m hsbg.rl.evaluate --policy teacher --episodes 20
python -m hsbg.rl.evaluate --policy random --episodes 20
python -m hsbg.rl.collector --policy teacher --envs 4 --episodes 40 --out runs/rl/verify.jsonl
python -c "from hsbg.rl.gym_wrapper import check_env_smoke; print(check_env_smoke(backend='real'))"
```

| 命令 | 预期 |
|------|------|
| demo_env | 完成一局，rank 1..8，errors=0 |
| validate_env | `ok: true`（确定性/2-4-8 人/选择步/奖励/vec env） |
| audit_env_coverage | GATE PASS（invalid=0、engine_rejected=0、无 step_cap） |
| bench_env | 0 crash；单局 ~0.2–0.7s；招募步 <1ms |
| rl evaluate teacher | mean_rank ~3.8–4.5 |
| rl evaluate random | mean_rank ~7.9 |
| rl collector | 4 workers ~6–8 局/s；JSONL 行型 header/step/episode |
| gym check | `True` |

## 4. 官方一致性

```powershell
python scripts/audit_official_consistency.py
```

预期：exit 0；硬门禁 `DATA_GAP=0 / behavior_mismatch=0 / 干净子集 100%`；
当前基线：679 场、MATCH **400（72.3%）**、确定性 **86.31%**（tolerant 94.35%）、
CONTEXT_GAP 59（dynamic_state 54）、ENGINE_DIVERGENCE 180（全部 missing_script）。

## 5. 版本同步

```powershell
python tools/version_sync.py --check
```

预期：client build = project patch = hsdata tag（当前均 255130），
rizling 参考版本落后一个版本属正常 warning。

## 6. 变更后如何刷新本快照

1. 跑 `python scripts/verify_all.py` 与 §2–§5 命令；
2. 更新本文件对应数字（保持"硬门禁"列不变）；
3. 回归 `docs/EXACTNESS_STATUS.md`（官方一致性指标）与 `docs/ENV_VALIDATION.md`（环境性能）。

---

## 7. 2026-10-26 AutoTavern 借鉴升级后的验收快照（macOS / Python 3.12）

> 本次升级新增了 AutoTavern 相关门禁（跨引擎一致性 / TavernBench / 双哈希进程
> 确定性 / 环境不变量），`verify_all` 从 7 个 gate 扩展为 10 个（缺 `taverngym`
> 时 `taverngym_conformance` 自动 SKIP）。以下数字是本机 macOS Apple Silicon
> 实测趋势值，硬标准仍是「0 failed / 0 crash / 门禁 PASS」。
> Windows/Python 3.13 的通过数会略不同（平台专属用例在 Windows 上执行）。

### 7.1 一键门禁（`python3 scripts/verify_all.py`）

| gate | 命令 | 预期（macOS 实测趋势） |
|---|---|---|
| engine_tests | `pytest hsrl2/tests -q` | 0 failed（**4890 passed / 6 skipped**，2026-10-26 冻结树实测） |
| project_tests | `pytest tests -q` | 0 failed（**667 passed / 62 skipped**，2026-10-26 冻结树实测） |
| smoke_8p | `tools/smoke_random_games.py --games 8 --seed 2000` | crashes=0、completed=8 |
| env_validation | `scripts/validate_env.py --games 20 --check-invariants` | `ok: true`，不变量违反 0 |
| env_bench | `scripts/bench_env.py --seeds 20` | 0 crash / 0 invalid，单局 ~2s 量级 |
| hashseed_determinism | `pytest tests/test_env_determinism_hashseed.py -q` | 0 failed（7 passed，~7s） |
| official_consistency | `scripts/audit_official_consistency.py --quiet` | 有官方语料时 exit 0；无语料机器自动 SKIP |
| version_check | `tools/version_sync.py --check` | 四信号成功 |
| taverngym_conformance | `pytest tests/conformance -q` | 0 failed（13 passed；无 taverngym 时 SKIP） |
| tavernbench_check | `scripts/run_tavernbench.py --check` | 26/26 PASS |

### 7.2 AutoTavern 相关专项

| 命令 | 预期（macOS 实测） |
|---|---|
| `pytest tests/test_backend_taverngym.py -q` | 42 passed（~1s；需 taverngym） |
| `pytest tests/conformance -q` | 13 passed（~4s；58 场景，MATCH 55 / CONVENTION_DIFF 2 / UNSUPPORTED 1） |
| `python3 -m tools.ac_conformance.run --seeds 48` | total=58，ENGINE_BUG 0（~4s） |
| `python3 scripts/run_tavernbench.py --check` | CHECK PASSED 26/26（~1s） |
| `pytest tests/test_env_snapshot.py tests/test_env_invariants.py -q` | 23 passed（~4s） |
| `PYTHONHASHSEED=0/1 pytest hsrl2/tests/test_hashseed_determinism.py -q` | 各 2 passed |
| `pytest hsrl2/tests/test_hashseed_determinism.py tests/test_env_determinism_hashseed.py -q` | 9 passed（跨进程确定性，~10s） |

### 7.3 本机既有失败/跳过说明

- 5 条搜索/价值测试依赖未入库的 `runs/bc/official_320/policy_bc.pt` → 按
  `tests/conftest.py` 精确 skip（Windows 有 checkpoint 时照常执行）。
- `tests/test_live_clickbot.py` 非 Windows 模块级 skip（Windows 照跑）。
- `tests/test_policy_model.py::test_forward_latency_batch64` 是**延迟基准**，
  在并发高负载（load average 很高）时会偶发超阈值；空载实测 34.9ms 通过，
  最终门禁应在空载下跑（不得靠放宽断言掩盖）。

---

## 8. 2026-10-26 第二阶段（P2：Rust 主引擎 + 37.0.0 数据 + 动作/观测标准）验收快照

> 环境：macOS Apple Silicon / Python 3.12.2 / Rust 1.98.1；数据 **37.0.0.255130**（Rust 引擎
> `data/p2/cards_37.json`，sha256 `c482612727c2618e…`）。硬标准仍是 0 failed / 门禁 PASS。

### 8.1 一键门禁（`python3 scripts/verify_all.py`）

| gate | 预期 |
|---|---|
| rust_engine_build | `cargo build --release -p hsbg-engine` exit 0（无 cargo/rust 时 SKIP） |
| engine_tests | 0 failed（4890 passed / 6 skipped 量级，legacy hsrl2） |
| project_tests | 0 failed（761 passed / 63 skipped 量级；含 P2 新增数据/动作/观测/Rust 引擎测试） |
| smoke_8p | crashes=0 |
| env_validation | ok=true，failures=[]（含不变量抽查） |
| env_bench | 0 errors / 0 invalid |
| hashseed_determinism | 0 failed（7 passed，双 PYTHONHASHSEED 子进程） |
| official_consistency | 有语料 exit 0；无语料 SKIP（不误红） |
| version_check | 四信号成功（项目数据 37.0.0.255130 为最新） |
| taverngym_conformance | 0 failed（13 passed；无 taverngym 时 SKIP） |
| tavernbench_check | 26/26 PASS |

### 8.2 P2 专项

| 命令 | 预期 |
|---|---|
| `cargo test --release --manifest-path rust/Cargo.toml -p hsbg-engine` | **858 passed / 0 failed**（36 套件，37 数据；含 6 个内容断言已按 37 重算） |
| `cargo test --release ... -p hsbg-engine --lib` | 15 passed |
| `pytest tests/test_rust_engine.py -q` | 10 passed + 1 skip（skip=上游 36.6.3 逐位对拍） |
| `pytest tests/test_action_space_std.py tests/test_obs_std.py -q` | 57 passed（金标：`action_name` 0..244 差异 0、`layout()` 32 项差异 0） |
| `pytest tests/test_p2_data.py -q` | 27 passed（3983 卡/池计数/机制元数据/Dark Paradox/幂等） |
| `pytest tests/test_env_snapshot.py tests/test_env_invariants.py -q` | 23 passed |
| `python3 tools/p2_data/gen_carddb_37.py --check` | byte-identical + meta/池计数/AT 脚本 id 0 missing |
| `python3 tools/p2_delta/run_all.py` | exit 0（覆盖矩阵/操作探针；产物 runs/p2_delta/） |
| `python3 tools/p2_perf/run_all.py` | exit 0（Rust/端到端/C 加速基准；产物 runs/p2_perf/） |
| `python3 rust/bench_engine.py --games 1000` | 裸引擎 ~274 games/s、3.65 ms/局（与上游比值 1.00） |

### 8.3 本机基线说明

- `pytest tests/test_policy_model.py::test_forward_latency_batch64` 是延迟基准，多 agent
  并发高负载时会偶发超阈值；空载复跑通过（不得放宽断言）。
- 5 条搜索测试依赖未入库的 `runs/` checkpoint、`tests/test_live_clickbot.py` 非 Windows
  模块级 skip —— 明细见 `docs/PORTABILITY.md`。
- Rust 构建产物 `rust/target/` 与 `*.so` 已 gitignore，不入库。


---

## 9. 2026-10-26 第三阶段（P3）验收快照：AT 唯一主引擎 + 37 池内内容补完

> 数据 37.0.0.255130；主引擎 `hsbg_engine`（AT fork）；hsrl2 冻结为 legacy/oracle。

| 检查 | 命令 | 结果 |
|---|---|---|
| Rust 构建 | `cargo build --release --manifest-path rust/Cargo.toml -p hsbg-engine` | PASS（verify_all rust_engine_build gate） |
| Rust 全量测试 | `cargo test --release -p hsbg-engine --no-fail-fast` | **39 套件 887 passed / 0 failed / 0 ignored** |
| P3 内容测试 | `--test p3_cards_a` / `p3_cards_b` / `p3_systems` | 8/8、13/13、8/8 |
| 池内覆盖门禁 | `python3 -m tools.p3_verify.run_all --skip-rebuild` | 池内随从 277 missing 0；池内法术 73 missing 0；P1 18 卡 missing 0 |
| oracle 差分 | 同上 | 15 MATCH / 1 DEFERRED / 2 STRUCTURAL_OK / 0 FAIL |
| 8 人 bot 冒烟 | `hsbg_engine` bot 驱动 ×20 seeds | crashes=0 |
| 确定性 | 同 seed 双跑 | PASS |
| Python 侧 | `pytest tests/test_rust_engine.py` | 10 passed + 1 skip |
| 一键门禁 | `python3 scripts/verify_all.py` | **12/12 gates PASS**（新增 rust_engine_build/rust_engine_test） |
| legacy | `pytest hsrl2/tests` | 4890 passed / 6 skipped（冻结不回退） |

剩余缺口（不阻塞 RL）：主技能长尾 9（Duos/旧替换）、P2 饰品/非池法术、P3 异变/任务、
679 场真实战斗 Rust 侧重放、Rally oracle debug seam；进入 RL 前需重冻结 seed 基准
（`rust/FORK.md` §7 checklist）。
