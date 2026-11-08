# docs/_history — 历史报告归档区

> 建立于 **2026-11-04**（P1 清理，Lead 批准）。规则：`docs/` 只放**当前有效**的设计/契约/台账；
> 已被新结论取代或一次性完成的报告移入本目录，**不删除**，保留原文与 git 历史。
> 所有入链已改为 `docs/_history/<name>.md`（docs/ 内相对链接为 `_history/<name>.md`）。

## 归档清单（23 篇）

| 文档 | 归档理由 |
|---|---|
| `STAGE3_PLAN.md` | 旧 stage-3 可执行配方，已被 s73 干净配方取代 |
| `STAGE5_REPORT.md` | stage-5 阶段报告（100M decisions） |
| `STAGE6_REPORT.md` | stage-6 阶段报告（90M decisions） |
| `TRAINING_RUN_2026-10-27.md` | 1h tiny 试训负结果 |
| `THROUGHPUT_FINAL_REPORT.md` | 10-28 吞吐战役终版报告 |
| `THROUGHPUT_PLAN.md` | 10-28 吞吐调研计划 |
| `THROUGHPUT_TIMELINE.md` | 单 iteration 时间轴分析 |
| `TRAINING_THROUGHPUT_NOTES.md` | 吞吐笔记（异步 C0 评测/多 GPU actor） |
| `COMPUTE_BENCHMARK.md` | 18M/4 GPU 旧基准 |
| `COMPUTE_PLAN_4GPU.md` | 旧 4 GPU 长训练计划 |
| `RESOURCE_PROFILE.md` | 资源时间轴 profile |
| `ASTRA_FINAL_REVIEW.md` | GPT-6 Astra 终审（一次性） |
| `REVIEW_PPAI.md` | 同上（2026-10-28） |
| `REVIEW_PLATEAU.md` | 平台终审 6.34–6.45 |
| `REVIEW_LIBRARY_POOL.md` | 镜像对手库终审 |
| `REVIEW_MIRROR_SNAPSHOT.md` | 快照镜像终审 |
| `REVIEW_TRAJECTORY_LIBRARY.md` | 轨迹镜像库 v2 终审 |
| `REVIEW_RUST_COLLECTOR.md` | Rust collector spike 终审 |
| `RUST_COLLECTOR_PLAN_2S.md` | 已停的追 2s 方案 |
| `MERGE_CHECKLIST.md` | 并行 agent 时代合并清单 |
| `HUMAN_PLAY_3GAMES.md` | 人类手打 3 局一次性分析 |
| `HUMAN_TRACE_CHECK.md` | 5 条模型侧结论轨迹核对 |
| `FIRESTONE_MIX_AB.md` | s13→s14 Firestone 混池 A/B（结论已进 DECISIONS/EXPERIMENTS） |

## 恢复方式（任一篇）

```bash
git mv docs/_history/<name>.md docs/<name>.md
# 再把引用改回：docs/_history/<name>.md -> docs/<name>.md；docs 内 _history/<name>.md -> <name>.md
git grep -l "_history/<name>.md" -- docs README.md scripts
```

## 未归档的相邻项（保持原位）

`RUST_COLLECTOR.md`（仍有 7 处引用，spike 结论待并）、`SMALL_FULLGAME_RL.md`、`MIRROR_PROBE_DIAGNOSIS.md`
（任务书明确保留）；新审计 `BUG_AUDIT_SOL.md`、`ASTRA_REVIEW_2026-11.md`、`INTERFACE_AUDIT.md` 属当前有效。
