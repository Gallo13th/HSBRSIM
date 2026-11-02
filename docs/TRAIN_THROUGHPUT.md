# 训练吞吐：records 数据通路（shm / fp16）与批量（games 384）

> 任务 `task-16`。目标：完整对局训练**端到端**吞吐 4,200 → ≥7,000 dec/s，**不改学习语义**
> （PPO/奖励/课程一行未动，只改数据通路与批量）。
>
> 写范围：`hsbg/az/train/process_pool.py`、`scripts/train_entity_sync.py`（仅新增开关/接线）、
> `tests/test_train_throughput.py`、本文。
> 三个改动都可关闭：`--ipc-mode auto|disk|shm`（默认 **auto→shm**）、`--records-dtype fp32|fp16`
> （默认 **fp32**）、`--games`（默认未改，仍 192；本次只验证 384）。
> **默认组合 `--ipc-mode auto --records-dtype fp32` 与历史路径逐位等价**（§4 用 4 个 arm 交叉验证）。

## 0. TL;DR

| # | 改动 | 开关（默认） | 实测收益 | 语义 |
|---|---|---|---|---|
| 1 | records 走 **/dev/shm 环形缓冲** | `--ipc-mode auto`（→shm；`disk` 可回退） | 父进程 `read_s`：**1.76 s → 0.005–0.19 s**（384 局/845 MB 时 **15.4 s → 0.005 s**）；collect dec/s **3,043 → 4,005（+32%）** | **逐位等价**（E vs G，4/4 iter sha 相同） |
| 2 | records **fp16** 存储 | `--records-dtype fp16`（默认 **fp32**，不推荐） | records/决策 **14.1 → 8.1 KB**；省 ~2–3% 时间 | **不逐位等价**：小配置 12 iter 全同，但 384 局/8 进程下**第 3 iter 起分歧**（§4.3）⇒ 不进默认 |
| 3 | **games 192 → 384** | `--games 384`（默认仍 192） | collect dec/s **2,561 → 3,043（+19%）**，但若同时仍在 disk 上，端到端**持平**（G vs A 0.98×）——必须配 shm | 不变（每轮样本数 ×2 ⇒ PPO 时长 ×2） |

**同窗口配对比值（A vs D，8 进程/单卡，机器 load 200–274）**：端到端 **1,724 → 2,380 dec/s = 1.38×**；
collect **2,561 → 2,927 = 1.14×**。
**机制侧下界**：`read_s` 从 1.76 s（192 局/417 MB）→ 0.005 s（384 局/846 MB）是确定性收益；
在最有利窗口（E 臂，机器空闲）端到端到 **4,179 dec/s（vs A 1,724 = 2.4×）**。
**瓶颈在哪**：不是采集/前向，而是父进程的 records 往返（438 MB/iter 写盘再读回）+
把 8 个分片 concat 成一批。

## 1. 瓶颈证据（实测）

### 1.1 现场（`runs/az_entity_s22/dyn`，24 进程 × 192 局）

| 指标 | 值 |
|---|---|
| decisions/iter | 27.5k–30.4k |
| `profile.parent_read_s` / `build_batch_s` | **1.36 s / 1.06 s**（≈2.4 s/iter 串行在关键路径） |
| `collect.records_bytes` | **438 MB/iter** |
| 单决策字节 | features 12,908 + target_pi 980 + masks 245 + cards 248 ≈ **14.4 KB** |

`records_bytes ≈ 14.4 KB × 30k` 说明载荷就是 3,227 floats/决策的观测本身，不是引擎或前向。

### 1.2 数据通路微基准（`python tests/test_train_throughput.py --bench --n 25000`）

25k decisions（361 MB fp32）单进程测 save→read→concat（真实里 save 在 worker 并行、
read/concat 在父进程串行；下表是整轮等价量）：

| mode | dtype | MB | save_s | read_s | concat_s | total_s |
|---|---|---|---|---|---|---|
| disk | fp32 | 361 | 1.31–1.74 | **1.19–1.85** | 0.16–0.38 | **3.03–3.80** |
| shm | fp32 | 361 | 0.65–0.78 | **0.001** | 0.22–0.37 | **0.87–1.15** |
| disk | fp16 | 200 | 1.30–1.32 | 0.95–1.23 | 0.20–0.21 | 2.69–2.72 |
| shm | fp16 | 200 | 0.30–0.72 | 0.01–0.03 | 0.14–0.35 | 0.52–1.20 |

两点：
1. **`read_s` 是纯浪费**：`np.load` 0.35 GB/s（zip + 每数组一次拷贝），shm 是 mmap 零拷贝；
2. **fp32→fp16 必须用 torch**：numpy `astype(fp16)` 只有 **259 MB/s**（1.25 s / 322 MB），
   torch CPU 转换 **17.9 GB/s（18 ms）——快 70×**。第一版用 numpy 时 fp16 反而更慢（`shm/fp16`
   一度测出 13.6 s，就是它）。实现里 `_cast_fp16/_cast_fp32` 优先 torch，无 torch 才回退 numpy。

## 2. 三个改动（实现要点）

### 2.1 `--ipc-mode {auto,disk,shm}` — records 走 /dev/shm

* worker：`_shm_put()` 把 `_batch_arrays(batch)` 写进 `/dev/shm/hsb_az_rec_<tag>_w<i>_s<slot>`；
  布局 `[0,64 KiB)` JSON 头（name/dtype/shape/offset/nbytes）+ 各数组原始字节；队列只传元数据。
* 父进程：`_shm_read()` attach 后 `np.frombuffer` 得**段内视图**（零拷贝），`np.concatenate`
  一次成型；`packed_all.clear()` 后 `_close_shm()`（有视图未释放时 `close()` 会抛 `BufferError`，
  这是刻意的护栏）。
* 容量/回收：每 worker **2 slot**（父进程读第 k 轮时 worker 可写第 k+1 轮）、段大小按
  **32 MiB 取整**；worker 退出 unlink；父进程 `close()` 按名字兜底；`/dev/shm/hsb_az_rec_<tag>.owner`
  记父进程 pid，下次 pool 启动时**按 owner pid 是否存活**清掉被 SIGKILL 的残留段（另留 6 h
  mtime 兜底）。24 worker × 2 slot × 64 MiB ≈ 1.5 GB 上限（本机 252 GB）。
* `auto` = 有进程 pool 且 `/dev/shm` 存在则走 shm，否则 disk（单进程/其它机器不受影响）。

### 2.2 `--records-dtype {fp32,fp16}` — features 半精度**存储**

* 只降 `features`（占 88% 字节）。`cards` 本身就是 **int16**，转 fp16 既不省字节又丢索引精度
  ⇒ 明确不转（任务书写的"features/cards 都 fp16"在此标注为**无收益且有害**的偏差）。
* 先 clamp 到 ±65504 再转（不出 inf/NaN）；父进程 `_upcast_records()` 读入后立刻还原 fp32，
  下游 dtype 与旧路径一致。
* 真实 features 已归一到 **|x| ≤ 2.3**（97.0% 的值 fp16 精确，最大绝对误差 7.8e-4）。

### 2.3 `--games 192 → 384`

纯命令行：每 iter 决策数线性 ×2（`history.collect.decisions` 可核对），每 worker 局数 8→16、
leaf 前向 batch 8→16 ⇒ 前向/决策减半。代价：PPO 每轮样本 ×2（`ppo_s` 3.9 → 6.3–8.1 s），
所以只在 `ppo_s < collect_total_s` 时有净收益（本配方满足）。**注意：在 disk 通路上单独开 384 局
是负收益**（G vs A = 0.98×，因为 845 MB/iter 的盘上往返把 +19% 的采集收益吃光）。

## 3. 前后对比（同窗口配对，8 进程 × 3 线程 / cuda:7，`--stop-at-decisions`）

配置：`runs/az_entity_s22/ctrl3/eval/ckpt_010006112.pt`（0.667M entity d128×2 h4）、
s22/dyn 配方（去掉 dyn-curriculum 与 eval）、`--pipeline 1 --lockstep 1 --leaf-wait-ms 0`。
8 进程是为了不越 76 线程上限，**learner 与 actor 共用 GPU 7**（生产是分开的，所以绝对值偏悲观）。

| arm | games | ipc/dtype | iters | decisions | collect dec/s | 端到端 dec/s | read_s | build_s | ppo_s | records MB/iter |
|---|---|---|---|---|---|---|---|---|---|---|
| **A（基线）** | 192 | disk/fp32 | 21 | 610,249 | 2,561 | **1,724** | 1.760 | 0.502 | 3.92 | 416.5 |
| G | 384 | disk/fp32 | 5 | 291,935 | 3,043 | 1,691 | **15.364** | 3.424 | 8.14 | 841.4 |
| E | 384 | shm/fp32 | 4 | 232,089 | **4,005** | **4,179**¹ | **0.005** | 0.889 | 6.26 | 818.1 |
| **D** | 384 | shm/fp16 | 9 | 525,760 | 2,927 | **2,380** | 0.187 | 3.245 | 13.86 | 467.2 |

口径：collect dec/s = Σdecisions/Σcollect.wall_s（含父进程 read+build）；端到端 =
稳态 decisions/(seconds 增量)，**不含**启动与 `torch.compile` 预热（每臂 ~110 s）。
¹ E 臂窗口内 `s23` 已停（机器空闲），A/G/D 窗口内 24 进程 s23 在跑 ⇒ E 的绝对值偏乐观，
只能与 G 做「同 games、只差 IPC」的对照；**同窗口配对结论用 A vs D（1.38×）**。

**分解**：`games 384` 让 collect +19%（A→G）；`shm` 把 845 MB/iter 的盘上往返（read 15.4 s）
变成 0.005 s（G→E: collect +32%）；fp16 再省 ~2–3%（E→D，且 D 的窗口更吵）。

## 4. 逐位等价证据

### 4.1 小配置矩阵：三条通路 12/12 iteration 动作流 sha 全同

2 进程 × 16 局 × 12 iter，同 seed、同起点，`--collect-sha 1`：

| iter | dec | disk/fp32 | shm/fp32 | shm/fp16 |
|---|---|---|---|---|
| 0 | 2652 | a440f83078adcc68 | a440f83078adcc68 | a440f83078adcc68 |
| 1 | 2261 | 618c4e1abcbea0f5 | 618c4e1abcbea0f5 | 618c4e1abcbea0f5 |
| 2 | 2590 | 4646e29bb1a5b212 | 4646e29bb1a5b212 | 4646e29bb1a5b212 |
| 3 | 2389 | 3d2cf3b67915f8b5 | 3d2cf3b67915f8b5 | 3d2cf3b67915f8b5 |
| 4 | 2819 | ade65eb3ca57b38e | ade65eb3ca57b38e | ade65eb3ca57b38e |
| 5 | 2741 | 78532086438ab370 | 78532086438ab370 | 78532086438ab370 |
| 6 | 2538 | f93fa38d66d6062d | f93fa38d66d6062d | f93fa38d66d6062d |
| 7 | 2579 | 1f043224ea74c1bc | 1f043224ea74c1bc | 1f043224ea74c1bc |
| 8 | 1937 | b46b5f6063a78110 | b46b5f6063a78110 | b46b5f6063a78110 |
| 9 | 2164 | 903aaf8a54e6c1ca | 903aaf8a54e6c1ca | 903aaf8a54e6c1ca |
| 10 | 2403 | de23fe021d236e8d | de23fe021d236e8d | de23fe021d236e8d |
| 11 | 2617 | f9a6b74fab2e5bd6 | f9a6b74fab2e5bd6 | f9a6b74fab2e5bd6 |

### 4.2 生产规模：`shm` 与 `disk` 逐位相同（E vs G，384 局 / 846 MB/iter / 8 进程）

| iter | decisions | G=disk/fp32 | E=shm/fp32 |
|---|---|---|---|
| 0 | 58,643 | 61b8bb7002266d4e | 61b8bb7002266d4e |
| 1 | 56,755 | 344c428cc3c4481c | 344c428cc3c4481c |
| 2 | 60,047 | de9a0cb40412fbe3 | de9a0cb40412fbe3 |
| 3 | 56,644 | 71b5e23cb43a5dcd | 71b5e23cb43a5dcd |

⇒ **shm 只是传输替换**：4/4 iteration 的 `decisions` 与 `action_sha` 完全一致（含 845 MB 载荷）。

### 4.3 fp16 **不是**逐位等价（重要，故不进默认）

同配置只把 `--records-dtype fp16` 打开（D vs G）：

| iter | G=disk/fp32 | D=shm/fp16 | 结论 |
|---|---|---|---|
| 0 | 58,643 / 61b8bb70… | 58,643 / 61b8bb70… | 同 |
| 1 | 56,755 / 344c428c… | 56,755 / 344c428c… | 同 |
| 2 | 60,047 / de9a0cb4… | **60,068 / 9b40fb02…** | **分歧** |
| 3 | 56,644 / 71b5e23c… | **56,686 / 76bb8248…** | 分歧 |

小配置 12 iter 全同、大配置第 3 iter 起分歧（decisions 差 ±0.03%）。**原因不是 shm**（E vs G
证明 shm 干净），而是 features 的 fp16 舍入改动了 PPO 更新的输入：误差本身极小
（|Δx| ≤ 5e-4，且 PPO 前向是 bf16 autocast），但 56k 决策/iter 的采样会让个别动作在近边界处翻转。
⇒ **fp16 只作为「省 2–3% 时间」的可选项**，正式训练（含 s23b）请保持 `--records-dtype fp32`。

### 4.4 生产事故与修复：父进程 fd 泄漏（2026-11-02，s23b 跑 17 iter 后崩）

**现场**：`s23b`（24 进程 / `--games 384` / shm）第 17 个 iter 时 `torch.save` 报
`OSError: [Errno 24] Too many open files`（`ulimit -n` 软限 **1024**）⇒ ≈**60 fd/iter** 累积。

**根因（两个叠加）**：
1. 父进程每轮对每个 worker 的段 `SharedMemory(attach)` 一次（24 fd/iter）；
2. 关闭时只要有 numpy 视图还引用段内 buffer，`SharedMemory.close()` 抛 `BufferError`；旧版
   `_close_shm` 遇到它就 **`break`** ⇒ 该轮**剩下的段全部不关**。而 `collect()` 里
   `packed_all.clear()` 之后仍有 3 个局部引用活着：`_arrs`（最后一个分片）、`_seg`、
   fallback 循环变量 `p`/`lb` ⇒ 必触发 BufferError ⇒ 24 fd/iter + 权重/日志 fd ⇒ 17 iter 撞 1024。

**修复**（`hsbg/az/train/process_pool.py`）：
1. `_close_shm()` **永不 break**：先尽力关全部，失败的重试 3 次（中间 `gc.collect()`），
   仍失败的留到下一轮；失败数写进 `collect.shm_unclosed`（正常恒 0）；
2. `collect()` 在 close 前显式清引用（`packed_all.clear()` + `_arrs = _seg = p = lb = None`）；
3. worker 侧 `_shm_put()` 显式 `dst = None; del buf`，避免扩容时关不掉旧段；
4. 启动期把 `RLIMIT_NOFILE` 软限 best-effort 抬到 `min(硬限, 16384)`（无需 root），生效值写进
   `collect.fd_limit`——让长训练即使还有别的 fd 增长也不会撞 1024。

**回归验证**（8 进程 × 96 局 × 10 iter，`--ipc-mode shm`）：

| 检查 | 结果 |
|---|---|
| 父进程 `/proc/<pid>/fd` 计数（每 5 s 采样） | **稳定 129**（波动 129↔145 = torch/attr 临时文件，无单调增长） |
| `collect.shm_unclosed` | **0/10 iter** |
| `collect.fd_limit` | **16384**（启动期已抬限） |
| `parent_read_s` | 0.004–0.011 s |

**对 `ulimit -n`**：修复后**不再需要**手工 `ulimit -n 65536`（加了也无害，双保险）。
判据：`history.collect.shm_unclosed` 恒 0 且 `/proc/<trainer_pid>/fd` 不随 iter 单调增长。

### 4.5 单元测试（`tests/test_train_throughput.py`，10 例全绿）

| 用例 | 断言 |
|---|---|
| `test_disk_fp32_bitwise_roundtrip` | npz 写读 18 字段 dtype/shape/值逐位相同 |
| `test_shm_fp32_bitwise_equals_disk` | shm 与 disk 读回逐位相同；段 unlink 干净 |
| `test_records_dtype_fp16_only_features` | 只有 features 变 fp16；upcast == `cast_fp32(cast_fp16(…))`；其余 17 字段逐位相同；字节恰省 `features.nbytes/2`；>65504 被 clamp |
| `test_shm_fp16_payload_and_roundtrip` | shm 载荷 = `features/2 + 其他`；读回逐位等于期望 |
| `test_shm_slot_reuse_grow_and_cleanup` | 同 slot 扩容、双 slot 独立、清理无残留 |
| `test_purge_stale_shm_only_old_and_prefixed` | 只清本前缀且够旧的段 |
| `test_purge_dead_owner_segments` | owner pid 已死 ⇒ 整族残留段被清 |
| **`test_shm_parent_read_close_does_not_leak_fds`** | **50 轮 read→concat→close 后 fd 数不增长** |
| **`test_close_shm_never_breaks_on_buffer_error`** | **某段有活视图时其余段仍必须全关**（旧版 break 回归） |
| `test_pool_rejects_bad_ipc_flags` | 非法 ipc_mode/records_dtype 在 spawn 前 fail-fast |

回归：`tests/test_parallel_collect.py` 4/4 通过（默认路径不变）。

## 5. 用法与回退

```bash
# 推荐（默认即此）：进程 pool 自动走 shm，features 仍 fp32 ⇒ 与历史逐位等价
python scripts/train_entity_sync.py ... --games 384
# 显式写法
python scripts/train_entity_sync.py ... --ipc-mode shm --records-dtype fp32 --games 384
# 可选：records 再省 45% 字节（不保证逐位等价）
python scripts/train_entity_sync.py ... --records-dtype fp16
# 一致性自检：每 iter 的 action_sha 写进 history.jsonl
python scripts/train_entity_sync.py ... --collect-sha 1
```

| 想回到… | 命令 |
|---|---|
| 历史数据通路（disk + fp32） | `--ipc-mode disk --records-dtype fp32` |
| 历史批量 | `--games 192` |
| 关掉 sha 记录 | `--collect-sha 0`（默认） |

环境变量兜底（不接 CLI 的调用方）：`HSBRSIM_IPC_MODE` / `HSBRSIM_RECORDS_DTYPE` /
`HSBRSIM_IPC_SHM_SLOTS` / `HSBRSIM_COLLECT_SHA`。
代码回退：`git checkout -- hsbg/az/train/process_pool.py`（本文件的改动全在 process_pool.py）
+ 删掉 `scripts/train_entity_sync.py` 里那 4 个开关与接线（**该文件多角色共用，回退前先
`git diff` 确认，别丢别人的改动**）+ `rm tests/test_train_throughput.py`。
运维：trainer 被 SIGKILL 后残留段由下次启动的 owner-pid 清理兜底；也可 `rm -f /dev/shm/hsb_az_rec_*`。

## 6. 折算到生产配置 / 还差什么

实测可叠加的三块（都在关键路径上、互不冲突）：
1. **shm 去掉 read**：生产 24 进程时 `parent_read_s` 1.36 s / 438 MB ⇒ 归零；
2. **fp16（可选）**：records 再减半（若接受非逐位等价）；
3. **games 384**：leaf 前向/决策减半（collect 侧 +19% 实测）。

生产口径（s22：collect wall 7.2 s、decisions 28k、e2e ~4.2k）里 I/O 占 1.36+1.06=2.4 s（33%），
去掉后 collect ≈4.8 s；再叠 384 局的前向摊薄 ⇒ **端到端 ≈ 1.4–1.6×，即 5,900–6,700 dec/s**。
**要到并稳定 ≥7,000，还差一项**（不在本任务书写范围）：PPO 每样本成本（`ppo_s` ≈3.3 s / 28k
决策）或 leaf 前向 6 ms/调用 的固定成本。建议下一轮：`--minibatch`/`--epochs` 的等成本重算，
或把 `BatchLeafServer` 的跨 worker 共享推理（topology A）落地。

## 7. 限制

* 全部吞吐数字在 **8 进程 × 3 线程 / cuda:7、learner 与 actor 同卡、load 200–274** 下测得；
  A/G/D 窗口内有 24 进程 s23 在跑，E 窗口内没有 ⇒ 只能做同窗口配对（A vs D）与同 games 对照
  （G vs E）。
* `--rust-collector` 路径同样经 `_emit_records`（未做端到端 A/B）；MCTS（`--sims>0`）不在主环，未测。
* shm 段上限 32 MiB×2×workers；单轮 records 远超 64 MB/worker 时会按需扩容（不会静默截断），
  `/dev/shm` 不足时 `SharedMemory(create=True)` 直接抛错（fail-fast）。
* **已修的生产事故**：`--ipc-mode shm` 早期版本每 iter 漏 ~24–60 fd（`_close_shm` 遇
  BufferError 直接 break），17 iter 撞 `ulimit -n 1024`。现版本 `shm_unclosed` 恒 0、
  fd 计数稳定，且启动期把软限抬到 16384（§4.4）。
