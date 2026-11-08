# STAGE300M_MONITOR — 300M 训练守护器

`scripts/stage_monitor.py`：300M PPO 训练的 **10M 计点 + 系统监控 + 告警 + 曲线**。
只读训练进程、不改训练代码；唯一对外动作是调用既有 `scripts/eval_panel.sh`（评测串行，同一时间 1 个）。

## 1. 启动（一条命令）

```bash
cd /home/data/users/gaoletian/projects/HSBRSIM
export PYTHONPATH=rust/python:.
nohup /home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python \
  scripts/stage_monitor.py --run runs/az_stage300 \
  --until-decisions 300000000 --eval-gpu auto \
  >> runs/az_stage300/monitor.log 2>&1 &
```

训练侧：`--out runs/az_stage300 --stop-at-decisions 300000000 --eval-every-decisions 10000000`
（训练内 = dev 面板 seed 420000）。canonical 由守护器独立打点：96 局 / seed 520000 / 5 席 p0.9 / full。

## 2. 计点

- 累计 decisions = 本 run `history.jsonl` 的 `collect.decisions` 求和；点 `p = k × 10M`。
- ckpt 取 `eval/ckpt_<decisions>.pt` 中 `decisions ≥ p` 的最小者（最多等 300s），跑 canonical
  后写 `points.jsonl`（point_decisions/ckpt/status/rank/top4/strength/tier_ge4/tier_ge5_t15/
  survive12/seconds/gpu/reused）；缺失或评测失败记 skipped/failed。
- **重启去重**：以 `point_decisions` 为键，已记录点不再评测（含 skipped；删该行可重点评）。

## 3. GPU 选择

- auto：排除训练 actors+learner（进程 `--gpus`/`--device`、history `collect.gpus`），按
  `--gpu-priority`（默认 1,7,5,4,3,0,2,6）选第一张 `free ≥ --min-free-mib`（默认 2500 MiB）
  的卡；等 600s 仍无 → skipped+告警。显式 `cuda:N` 同样检查，强跑用 `--allow-low-free`。

## 4. 告警（`alerts.log`，同类 600s 冷却，恢复写 RESOLVED）

- ERROR：trainer_exited（进程消失）/ illegal_actions / restarts / nan_loss / point_eval_failed
- INFO：summary_json 出现（训练内评测点也可能写该文件）
- WARN：truncated_spike（> max(5, 3×近 20 iter 中位+2)）/ low_dps（<3000 连续 3 iter）/
  point_ckpt_missing / point_gpu_unavailable

## 5. 产物

- `curves.png` 16 面板：canonical+dev rank+基线、top4/win、strength、tier≥4、tier≥5@t15、
  survive12、entropy、KL+clip、policy/value loss、lr+anchor_kl、dec/s+collect/ppo、
  illegal/trunc/restart+GPU、hb 注入率、batch、显存、状态；X 轴统一累计 decisions (M)；
  新增点或每 300s 重绘。
- `dashboard.md`（状态+点表+dev 表+告警）、`points.jsonl`、`system.jsonl`（60s：GPU/CPU/
  RSS/load/df）、`alerts.log`、`monitor.log`（nohup stdout）。

## 6. 运维与自测

- 重启：重复 §1（不会重复计点）；训练崩溃时守护器继续轮询等待重启；训练结束且计点补齐后
  自动退出（`--keep-alive` 可常驻）。停止守护器：`pkill -f stage_monitor.py`（不动训练）。
- 离线自测（不依赖新训练、不写 run 目录）：
  `--once --no-eval --out-prefix runs/_stage_monitor_selftest/<name>`，产物
  `<prefix>.curves.png` / `<prefix>.dashboard.md`（示例：s73、az_script_ab_2seats）。
