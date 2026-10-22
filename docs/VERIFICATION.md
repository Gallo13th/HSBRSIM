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
