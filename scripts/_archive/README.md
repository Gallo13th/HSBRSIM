# scripts/_archive — 一次性/已停用脚本

> 建立于 **2026-11-04**（P1 清理，Lead 批准）。规则：`scripts/` 只放当前入口；已被取代或一次性完成的
> 脚本移入本目录，**不删除**，保留 git 历史。**不要在新代码/文档中 import 或引用本目录脚本。**
> 如需恢复：`git mv scripts/_archive/<name> scripts/<name>`，并检查 `docs/`/`scripts/` 引用。

## 归档清单（11 个）

| 脚本 | 归档理由 |
|---|---|
| `mechanism_audit.py` | 一次性机制审计（0 引用） |
| `oilcan_prior_probe.py` | 单卡先验探针（0 引用） |
| `probe_frozen_strength.py` | 冻结强度探针（0 引用） |
| `quality_watch.py` | 旧质量 watch（被 `quality_monitor.py` 取代） |
| `plot_scaling_1m.py` | 一次性 1M 缩放曲线 |
| `plot_stage_curves.py` | 旧 stage 曲线 |
| `plot_strength_stages.py` | 旧强度 stage 图 |
| `plot_throughput_curves.py` | 10-28 吞吐战役曲线 |
| `curriculum_report.py` | 旧课程报告 |
| `scaling_signal_run.sh` | 缩放信号 A/B 旧驱动 |
| `scaling_signal_run_v2.sh` | 同上 v2 |

## 未归档的零引用脚本（11-01 后新增，等下一轮判生死）

`best_of_n.py`、`bon_all_states.py`、`bon_t8_t9.py`、`eval_lookahead.py`、`policy_hybrid.py`、
`policy_lookahead.py`、`real_board_decompose.py`、`rich_features.py`、`ingest_human_play.py`、
`gen_search_labels_v2.py`、`relabel_search_v2.py`、`tier_split_eval.py`。

## 入口索引

当前入口以 `scripts/README.md`（按角色分组）与 `docs/README.md` 为准；训练/评测/数据/门禁核心脚本
（`train_entity_sync.py`、`train_block_clean.sh`、`eval_panel.sh`、`verify_all.py` 等）**不在**本目录。

## 2026-11-04 · P3 追加归档

- `s22_s26/`（36 个文件）：原仓库根 `$t/`，s22–s26 时代的临时驱动/探针脚本，全仓零引用。
- `tmp_trace_final.py`：原 `.tmp_trace/final.py`，一次性 human trace 复算脚本。
- 恢复：`git mv scripts/_archive/s22_s26 '$t'`、`git mv scripts/_archive/tmp_trace_final.py .tmp_trace/final.py`（按需）。
