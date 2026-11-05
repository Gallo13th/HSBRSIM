# 300M 训练前吞吐基准（2026-11-04）

> 目的：在不改变训练语义（奖励/PPO/数据）的前提下，实测 4 组采集/更新配置的**端到端**吞吐，
> 为 300M decisions 的 PPO 训练选参。全部从 `runs/az_entity_s73/{model,trainer}.pt` 精确续训
> （start_iter=566），每臂 `--stop-at-decisions 1500000`、周期评测关闭
> （`--eval-every-decisions 1000000000 --eval-async 0`）、`--minutes 30`，顺序执行。
> 环境：actors GPU 3,4,5；learner cuda:0；games 384；CPU 128 核但他人在跑（load 80–140；
> GPU 1/2/6/7 有他人 20–23GB；GPU0 有他人 2.3GB）。

## 1. 结果（history.jsonl；剔除前 3 iter 的稳态值）

| 臂 | procs/threads/mb/ga | 训练墙钟* | iter | decisions | e2e dec/s | median dec/s | collect dec/s | ppo_s/iter | collect_s/iter | batch_fill | GPU0 峰值 | actors 峰值 | 300M 预计 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A baseline | 24 / 3 / 1024 / 8 | 251 s | 21 | 1,506,182 | 7,536 | 8,139 | 8,444 | 9.17 | 8.50 | 0.157 | 12.3 GB | 6.7 GB | **11.06 h** |
| B | 32 / 2 / 1024 / 8 | 285 s | 22 | 1,559,697 | 7,032 | 7,228 | 7,198 | 9.58 | 9.84 | 0.123 | 12.4 GB | 8.6 GB | 11.85 h |
| **C** | **32 / 2 / 2048 / 4** | **247 s** | 22 | 1,570,411 | **8,897** | **8,669** | **9,233** | **7.71** | **7.73** | 0.123 | 16.7 GB | 8.4 GB | **9.37 h** |
| D | 40 / 2 / 2048 / 4 | 262 s | 22 | 1,569,960 | 7,161 | 7,752 | 7,295 | 8.90 | 9.77 | 0.104 | 16.5 GB | 8.6 GB | 11.64 h |

\* 训练墙钟 = 训练循环耗时；另含启动/编译 ~105–125 s（A/B/C/D 总墙钟 356/411/412/399 s）。
有效 batch 固定 8192（A/B：1024×8；C/D：2048×4）。

## 2. 结论（推荐 C）

1. **C（32 procs / threads 2 / minibatch 2048 / grad-accum 4）最快**：e2e +18.1% vs A（均值），
   稳健口径（逐 iter 中位数）**+6.5%**；collect +9.3%、`ppo_s/iter` 从 9.17 s 降到 7.71 s。
   原因是**更新侧变快**（同样有效 batch，但 minibatch 翻倍 → 每次更新的 step 数减半、GPU 利用率更高），
   而 A 的瓶颈正是 update（`ppo_s/iter > collect_s/iter`，e2e≈更新墙钟）。
2. **D（40 procs）不划算**：collect_s/iter 9.77 s（C 7.73），`batch_fill` 0.104（C 0.123），
   3 张 actor 卡被 40 进程过载；比 C 慢 19%，也慢于 A。40 procs **没有 OOM**（rc=0、restarts=0），
   只是不划算。
3. **B（32 procs/2 threads、mb 1024）比 A 慢 7%**：多出来的 8 个进程没换来吞吐，更新仍 9.58 s/iter，
   collect 反而 9.84 s/iter（CPU 争抢）→ 32 procs 只有在把 minibatch 提到 2048 时才成立。
4. **波动与置信**：外部负载（songwei，load 80–140）与顺序执行带来 ~±10% 波动；A 的逐 iter 墙钟
   7.71–20.18 s（首稳态 iter 偏慢），因此同时给均值（+18%）与中位数（+6.5%）两种口径。
   两者都 >5%，**不属于「已接近本机瓶颈」**；但 `ppo_frac≈0.96` 说明下一步要提速应优化更新侧
   （compile/leaf 批处理），靠加 actor 进程已无效。
5. **300M 预计**：C ≈ **9.4 h**（保守中位数口径 9.6 h）；A 11.1 h、B 11.9 h、D 11.6 h。
   周期评测若保留（96 局 human panel 在 s73 实测 83–96 s/次，每 10M 一次），串行代价 ≈0.8 h；
   异步跑在 GPU1 时大部分被训练掩盖，预计 +0.3–0.8 h ⇒ **C 全流程 ≈9.7–10.2 h**。

## 3. 产能校验（全部通过）

- 4 臂均 `rc=0`；`illegal_actions=0`、`truncated_games=0`、`restarts=0`；日志无 Traceback/OOM。
- 40 procs（D）显存峰值 actors ≈8.6 GB/卡、learner 16.5 GB（含他人 2.3 GB），24 GB 卡余量充足。
- `batch_p50=1.0`（每进程 batch 仍为 1，pipeline leaf-wait 0 的行为未变）。
- 进程数不同本就不保证 records 逐位一致（未做 sha 对比，符合任务约定）。

## 4. 复现

```bash
cd /home/data/users/gaoletian/projects/HSBRSIM && export PYTHONPATH=rust/python:.
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
# C 臂（推荐）：
$PY scripts/train_entity_sync.py \
  --checkpoint runs/az_entity_s73/model.pt --trainer-state runs/az_entity_s73/trainer.pt \
  --device cuda:0 --gpus 3,4,5 --processes 32 --threads 2 --games 384 \
  --minibatch 2048 --grad-accum 4 --lockstep 1 --pipeline 1 \
  --minutes 30 --stop-at-decisions 1500000 --eval-every-decisions 1000000000 --eval-async 0 \
  --gpu-free-check 0 --snapshot-every 100 --keep-snapshots 1 --out runs/_bench300_C
# A/B/D 只改：--processes 24 --threads 3 --minibatch 1024 --grad-accum 8（A）
#             --processes 40 --threads 2 --minibatch 2048 --grad-accum 4（D）
```
产物：`runs/_bench300_{A,B,C,D}/`（各 ~503 MB：history.jsonl / train.log / summary.json /
model.pt / trainer.pt / _nvidia_smi.csv / _arm.csv），保留供核查。

---

## 5. B04 冻结对手席下的吞吐（2026-11-06）

背景：B04 让 2 个 bot 席由冻结 net 驱动（每席每决策一次 forward），actor 侧算力需求从「1 席 net」变成「3 席 net」，
基线吞吐从 B03 的 ~7.4k dec/s 掉到 **5.3k dec/s**。用 5 分钟 pilot 扫了三类旋钮（只改吞吐，不改算法）：

| 配置 | actor 卡 | dec/s | s/iter | 结论 |
|---|---|---:|---:|---|
| P32 T2 wait0（基线） | 3,4,5 | **5288** | 13.20 | 参照 |
| P32 T2 wait3 | 3,4,5 | 5154 | 13.50 | ❌ `--leaf-wait-ms` 攒批无效（宿主 CPU 抢不过隔壁作业） |
| P32 T2 wait10 | 3,4,5 | — | — | 未跑（wait3 已负收益） |
| **P32 T2 wait0** | **3,4,5,6** | **6366** | **11.00** | ✅ **+20%**，采纳为 B04 默认 |
| P48 T2 wait3 | 3,4,5,6 | 5220 | 13.38 | ❌ 48 procs 在 load 100+ 的宿主上反而更慢 |

- 结论：**actor 卡数是唯一有效杠杆**（10–11 worker/GPU → 8 worker/GPU，单次 forward 更快）；
  加进程/加攒批在这个宿主（load 100–166，隔壁 cmscan/diamond 占满 CPU）上均为负收益。
- 余量：actor util 98–99% 但功耗仅 ~150W/350W ⇒ 仍然是「小批次、延迟受限」；`batch_fill` ≈0.13。
  真正解法是 Rust 采集器（`--rust-collector`）或把叶子评估批更大，两者都还没做（当前 Rust 采集器不支持冻结席/human-board 注入）。
