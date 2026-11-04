# Stage-300M B01 运行卡（2026-11-04）

## 0. 一句话

从历史最优链（`s61 → s73`，精确续训）出发的**单进程连续 300M decisions** PPO stage；
每 10M 用 `eval_panel.sh` 打一个 canonical 点并重绘 16 面板曲线。

## 1. 启动

```bash
cd /home/data/users/gaoletian/projects/HSBRSIM
EVAL_DEVICE=cuda:6 nohup bash scripts/run_stage300m.sh > /tmp/stage300m_launch.out 2>&1 &
export PYTHONPATH=rust/python:.
nohup python scripts/stage_monitor.py --run runs/az_stage300m_b01 \
  --until-decisions 300000000 --eval-gpu auto --gpu-priority 7,1,6 \
  >> runs/az_stage300m_b01/monitor.log 2>&1 &
```

启动时间 2026-11-04 10:05:38（CST）；seed 27501；输出 `runs/az_stage300m_b01/`。

## 2. 配方（与 s73 唯一差异 = 预算 + 吞吐参数）

| 项 | 值 | 说明 |
|---|---|---|
| 起点 | `runs/az_entity_s73/model.pt` + `trainer.pt` | 精确续训（optimizer/updates/LR/RNG） |
| 预算 | 300,000,000 decisions，`--minutes 1500` 兜底 | 单进程连续 stage |
| 采集 | 32 procs / threads 2 / games 384 / actors GPU 3,4,5 | 吞吐基准 C |
| 学 习 | learner cuda:0；minibatch 2048 / grad-accum 4（有效 batch 8192） | 吞吐基准 C；PPO 侧 9.17→7.71 s/iter |
| 其余 | 与 clean recipe 完全相同（anchor 0.1 常数、max-updates 3000、lr-min 0.5、eval 10M） | 只改预算与吞吐，不改奖励/算法 |
| 评测 | 训练内 dev 96 局 seed 420000（cuda:6）；canonical 96 局 seed 520000（monitor，auto GPU） | 每 10M 各一次 |
| 快照 | 每 100 iter 存 model+trainer；保留 8 份 | 崩溃可精确续训 |

## 3. 监控产物（每 10M 更新）

- `runs/az_stage300m_b01/curves.png` — 16 面板：canonical/dev rank、top4/win、strength、
  tier≥4、tier≥5@t15、survive12、entropy、KL/clip、loss、lr/anchor_kl、dec/s、异常、注入、
  batch、显存。
- `runs/az_stage300m_b01/points.jsonl` — 每个 10M 的 canonical 指标（含 ckpt/seconds/GPU）。
- `runs/az_stage300m_b01/dashboard.md` — 人读摘要 + 点表 + 告警。
- `runs/az_stage300m_b01/system.jsonl` — 60s 系统采样。
- `runs/az_stage300m_b01/alerts.log` — 进程/指标异常告警。

## 4. 断点续训

```bash
bash scripts/resume_stage300m.sh    # 从最新 snapshot 精确续训；按已完成 decisions 计算剩余预算
```

## 5. 吞吐与 ETA

基准（`docs/THROUGHPUT_300M.md`）：C 臂 8.9k dec/s；实测本 run 稳态 9.5–10.1k dec/s。
300M ≈ **8.3–9.5 h**（含每 10M 的 dev + canonical 评测）；预计 2026-11-04 19:00–20:00 完成。
外部负载（songwei 等）会带来 ±10–20% 波动。
