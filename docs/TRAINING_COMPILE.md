# 训练侧 torch.compile（PPO learner fwd+bwd）

> 目标：只给 **learner 侧 PPO 训练更新**（`train_ppo` 的 forward+backward 与 anchor
> 参考前向）加 `torch.compile`，把 `ppo_s` 压下来；**不碰**叶前向 / `PPOEvaluator` /
> `BatchLeafServer` / 自对弈 / 评测。实现：`hsbg/az/train/ppo.py` 的 `TrainForward`
> + `PPOConfig.compile_train`，入口 `scripts/train_entity_sync.py --compile-train`。

## 1. TL;DR（实测）

同一 checkpoint（`runs/az_entity_s5/model.pt`）、同 seed、`cuda:7`、2 workers、
64 games、6 iterations、production 同款超参（`--amp bf16 --minibatch 1024
--grad-accum 8 --epochs 1 --anchor-beta 0.1 --seq-coef 0.03`）：

| arm | compile | anchor_amp | `ppo_s` 中位 | wall/iter 中位 | dec/s | 显存 peak | `ppo_s`/baseline |
|---|---|---|---|---|---|---|---|
| base | 0 | 0 | **3.37 s** | 7.24 s | 2182 | 6054 MiB | 1.000 |
| **compile** | 1 | 0 | **2.39 s** | 6.32 s | 2500 | 6002 MiB | **0.707** |
| anchor_amp | 0 | 1 | 2.87 s | 7.09 s | 2208 | 6066 MiB | 0.851 |
| compile+anchor_amp | 1 | 1 | **2.15 s** | 6.32 s | 2669 | 6002 MiB | **0.638** |

- **只开 compile 就达到验收线**（≤ eager 的 0.8 倍）：`0.707×`，即训练更新 **1.41×**；
  叠加 anchor 参考前向 bf16（`--anchor-amp 1`）到 `0.638×`（**1.57×**）。
- 这一组小规模 A/B 里 **wall/iter 只降 13%**，因为该规模下 collect（6.5–7.2 s）比
  ppo 更慢，流水线被 collect 卡住；production 里 ppo（7.4 s）> collect（6.1 s），
  所以 ppo 的收益会直接变成 wall 收益（见 §6 外推）。
- 每 iteration `ppo_s`（s，第 0 个 iteration 含一次性 warmup 之后的抖动）：
  base `[3.859, 3.245, 3.385, 3.463, 3.364, 2.638]`、
  compile `[4.827, 2.344, 2.427, 2.538, 2.344, 1.927]`、
  compile+amp `[5.967, 2.076, 2.259, 2.157, 2.152, 1.635]`。
- 显存不涨（编译图的 workspace 与 eager 相当，实测 peak 6.0 GiB 持平）。

复现命令（把 `--compile-train` / `--anchor-amp` 换掉即可，每次换 `--out`）：

```bash
env -u CUDA_VISIBLE_DEVICES python scripts/train_entity_sync.py \
  --checkpoint runs/az_entity_s5/model.pt --arch entity --device cuda:7 \
  --processes 2 --gpus 7 --threads 8 --games 64 --sims 0 --epochs 1 \
  --minibatch 1024 --grad-accum 8 --amp bf16 --lr 2e-6 --lr-min-ratio 0.5 \
  --max-updates 3000 --clip 0.2 --target-kl 0.02 --lam 0.995 --max-grad-norm 1.0 \
  --entropy-coef 0.001 --pi-coef 0.0 --anchor-beta 0.1 --anchor-iterations 200 \
  --anchor-beta-tail 0.02 --pipeline 1 --lockstep 1 \
  --mirror-snaps runs/library/snaps_champ --mirror-seats 2 --mirror-p 0.164 \
  --mirror-sample p75 --mirror-p-ramp 0.164@0,0.3@0.5 --mirror-seat-random 1 \
  --seq-coef 0.03 --seq-coef-ramp 0.03@0,0.05@0.7 --seq-ramp-total-decisions 68000000 \
  --gpu-free-check 0 --seed 7100 --eval-every-decisions 0 --iterations 6 \
  --snapshot-every 100 --keep-snapshots 2 --out /tmp/ab_compile \
  --compile-train 1 --anchor-amp 0
```

## 2. 为什么训练侧 compile 可行

1. **形状固定**：feature `[B, 3227]`、cards `[B, 124]`、mask `[B, 245]`、动作空间
   恒 245、minibatch `B` 恒 1024（`--minibatch`）。用 `dynamic=False` 只编**一张**
   静态图，不存在 dynamic shape 分桶/重编译。
2. **一次编译覆盖 fwd+bwd**：`torch.compile` 走 AOTAutograd，对 `model.forward` /
   `forward_aux` 调用会同时生成 forward 图与 backward 图；梯度仍写回**原**
   `model.parameters().grad`，optimizer / `state_dict` / checkpoint 格式完全不变。
3. **eager 小算子多**：entity 网络（14.9 M 参数、49 token、8 层、d=384）每步有几百个
   小 kernel（`_card_repr` 的多次 embedding+Linear、logits 分段写入、pointer head、
   layernorm/gelu 等），在 4090 上 eager 的 MFU 很低，正是 inductor 融合的收益区。
4. **尾批不参与编译**：`train_ppo` 的最后一个 minibatch 往往 `< minibatch`，这类
   `B != minibatch` 的尾批直接走 eager（`TrainForward._size_ok`），避免每次 iteration
   产生一个新形状、触发重新编译（这是 leaf 侧翻车的根因之一，见 §3）。

实测微基准（RTX 4090 / torch 2.6.0+cu124 / triton 3.2.0，`cuda:7` 独占）：

| 场景 | eager | compiled | 加速 |
|---|---|---|---|
| entity 训练 fwd+bwd，B=1024，autocast bf16 | 101.7 ms | 73.7 ms | **1.38×** |
| 训练 fwd+bwd 的编译+warmup | — | ~52 s（一次） | — |
| anchor 参考前向，B=4096，fp32（`mode=default`） | 206 ms | 202 ms | 1.02× |
| anchor 参考前向，B=4096，fp32 + TF32 | 143 ms | 140 ms | **1.47×** |
| anchor 参考前向，B=4096，autocast bf16 | 113 ms | 84 ms | **2.46×** |
| 整批 anchor_logp（46 322 样本，12 chunk） | 2.45 s | 1.69 s | 1.45× |
| 同上，`--anchor-amp 1`（bf16） | — | 1.03 s | 2.38× |

> 注：只编译、不开 TF32/bf16 的 fp32 anchor 前向**没有收益**（1.02×）——它是 fp32
> 算力受限。因此 `build_train_forward` 在启用编译时同时打开
> `torch.set_float32_matmul_precision("high")`（TF32），与既有 `--leaf-compile`
> 的做法一致；anchor 想再快就开 `--anchor-amp 1`（bf16，见 §7）。

## 3. 与 leaf server 历史失败的区别（为什么这次不会重演）

历史记录：leaf server 上对**推理**前向做 `torch.compile(mode="reduce-overhead")`
后灾难性变慢（2.98 s/次、51 张 CUDA graph）。那是完全不同的场景：

| 维度 | leaf 侧（历史失败） | 训练侧（本次） |
|---|---|---|
| 用途 | MCTS 叶评估（推理） | learner fwd+bwd |
| batch 形状 | 每步不同（1..64，聚批窗口动态） | 固定 minibatch（1024） |
| 编译形状策略 | 默认 dynamic → 每形状一张图；`reduce-overhead` 还会捕获 CUDA graph | `dynamic=False` + 固定 B，一张图；不用 CUDA graph |
| 每步调用次数 | 数千次/秒，任何重编译/拷贝都致命 | 每 iteration 数十次 |
| 反向 | 无 | AOTAutograd 静态图，融合收益更大 |

本次刻意**不用** `mode="reduce-overhead"`（不带 CUDA graph）：训练每步都 `opt.step()`
改写参数，CUDA graph 捕获的静态地址/参数快照与优化器 step 的语义容易打架，收益也远
小于融合收益。用 `mode="default"`（或可选 `max-autotune`），`dynamic=False`。

## 4. 实现与开关

| 位置 | 内容 |
|---|---|
| `hsbg/az/train/ppo.py:316` | `compile_train_mode()`：规范化 0/1/2（`True→1`） |
| `hsbg/az/train/ppo.py:367` | `PPOConfig.compile_train: int = 0` |
| `hsbg/az/train/ppo.py:371` | `PPOConfig.anchor_amp: bool = False` |
| `hsbg/az/train/ppo.py:958` | `class TrainForward`：编译/回退/尾批路由/warmup |
| `hsbg/az/train/ppo.py:1143` | `build_train_forward()`：按配置构建（0→`None`） |
| `hsbg/az/train/ppo.py:1181` | `ppo_losses(..., train_forward=None)` |
| `hsbg/az/train/ppo.py:1331` | `train_ppo(..., train_forward=None)` |
| `hsbg/az/train/ppo_trainer.py:73` | `PPOTrainer` 启动时编译训练前向（计时之外） |
| `hsbg/az/train/ppo_trainer.py:86` | `set_anchor()` 编译 anchor 参考前向（forward-only warmup） |
| `hsbg/az/train/ppo_trainer.py:103` | `_anchor_logp()` 走编译图 / `anchor_amp` |
| `scripts/train_entity_sync.py:164` | CLI `--compile-train {0,1,2}` |
| `scripts/train_entity_sync.py:168` | CLI `--anchor-amp {0,1}` |
| `tests/test_compile_train.py` | 等价/尾批/回退 单测 |

行为：

- `compile_train=0`（默认）：**零开销、零行为变化**，`build_train_forward` 返回
  `None`，`ppo_losses` 走原来的 `forward_model` / `forward_model_aux`。
- `compile_train=1`：`torch.compile(..., mode="default", dynamic=False, fullgraph=False)`；
  `=2` 用 `mode="max-autotune"`（首次编译可能几分钟，不建议频繁重启的 run 用）。
- **warmup**：`PPOTrainer.__init__`（或直接调 `train_ppo` 时，在 `model.eval()` 之后、
  第一个 minibatch 之前）用固定形状的零张量各跑一次 fwd+bwd（梯度随后清零），把
  编译开销放在训练计时之外。实测 entity B=1024 两份图（main+aux）约 19–72 s（取决于
  机器缓存），anchor 图约 4–16 s。
- **回退**：`torch.compile()` 抛错、warmup 抛错、或运行期前向抛错 → `_warn()` 打印
  **一次** `[ppo][warn] torch.compile 训练前向（main|aux）不可用，自动回退 eager：...`，
  该路径永久回退 eager，**训练继续**（`stats["compile_active"]=False`，不会崩）。
- **diagnostics**：`train_ppo` 的 stats 增加
  `compile_train` / `compile_active` / `cuda_peak_mb`，启用编译时再加
  `compile`（`mode/active/main_compiled/aux_compiled/warmup_s/compiled_calls/eager_calls/warnings`）；
  `PPOTrainer.update` 在编译 anchor 时再给 `anchor_compile`。
- 启动日志：`[ppo] train compile mode=1 main=on aux=on warmup=19.0s`、
  `[compile] train compile=1 active=True ...`、`[compile] anchor compile active=True ...`。

- **只编译模型前向，损失保持 eager**：`ppo_losses` 里的 loss 计算（`[B,245]` 的
  log_softmax / entropy / clip / aux CE）是纯 elementwise，占比很小；而 `seq_coef`、
  `anchor_coef`、`pi_coef` 每个 iteration 都会变（ramp），若把它们闭包进编译图，
  Dynamo 会按 Python 标量特化 → **每 iteration 重编译一次**，得不偿失。因此
  `TrainForward` 只包 `model.forward` / `model.forward_aux`（AOTAutograd 连 backward
  一起编），loss 仍在 eager 里算，配置怎么变都不触发重编译。
- **anchor 参考前向也在编译范围内**：`PPOTrainer._anchor_logp` 是 learner 侧
  **no_grad** 的整批前向（不是叶/推理路径），实测占 `ppo_s` 约 36%，所以同一个
  `compile_train` 开关也编它（`minibatch=4096` 固定分块、forward-only warmup、
  尾块 eager）。它不经过 `PPOEvaluator` / BatchLeafServer，评测进程也不受影响。

## 5. A/B 之外：production batch 大小的 learner-only 测量

用 46 322 条合成样本（= 生产每 iteration decisions）在独占卡上直接跑
`trainer.update`（无 collect 抢卡），3 次重复取中位：

| arm | `ppo_s` |
|---|---|
| eager | 5.06 s |
| compile | 3.70 s（0.73×，1.37×） |
| compile + anchor_amp | 3.68 s（0.73×） |

anchor 单独计时：eager 2.45 s → 编译+TF32 1.69 s → 编译+bf16 1.03 s。整条 update
的收益 ≈ 训练主干（~36 微批 × 每批 102 ms）+ anchor（~2.45 s）两部分的加权：
`train 1.38×` + `anchor 1.45–2.4×`。小规模真机 A/B 里 anchor 占比更高，所以
compile+anchor_amp 的收益更明显（0.638×）。

## 6. 对 wall/iter 的外推（以及为什么小规模 A/B 的 wall 只降 13%）

流水线（`--pipeline 1`）下 `wall/iter ≈ max(collect, ppo) + 少量固定开销`：

- 现状（s5）：`collect 6.1 s / ppo 7.4 s / wall 7.8 s`，44–46 k decisions/iter
  → 5.7–5.9 k dec/s。
- 只开 compile：`ppo ≈ 7.4 × 0.71 ≈ 5.2 s` → `wall ≈ max(6.1, 5.2) ≈ 6.1–6.5 s`
  → **≈ 7.1–7.6 k dec/s**（达到 ≥7 k 目标）。
- 叠加 `--anchor-amp 1`：`ppo ≈ 4.7–5.2 s`，wall 仍由 collect 决定（≈6.3 s）。
- **要到 5.5 s wall，collect 必须降到 ≈5.1 s**（或进一步重叠）——那是 collect 侧的
  优化（Rust 采集器 / 更多 worker / 更强卡），不在本文件范围。反过来，compile 让
  learner 少占 GPU 后，同卡 collect 也会略快（本 A/B 里 7.15→6.58 s，−8%），所以
  production 的 collect 也可能随之下降。

## 7. 注意事项

1. **不改 `amp` 口径**：`compile_train` 不改训练精度；只有 `anchor_amp=1` 才让
   anchor 参考前向用 `--amp` 的 bf16。anchor 只是 KL 正则项的参考分布，换 bf16 会让
   `anchor_kl` 有 ~1e-3 量级差异，**不影响**策略/价值主干与 PPO ratio。想完全保数值
   就不开 `--anchor-amp`（compile 本身在 `amp=bf16` 下对训练主干是数值等价的）。
2. **TF32**：启用编译时 learner 进程会 `torch.set_float32_matmul_precision("high")`
   （与 `--leaf-compile` 一致）。`amp=bf16` 时训练主干是 bf16，TF32 只作用于 anchor
   的 fp32 前向；`amp=off` 的训练主干会走 TF32（相对 fp32 约 1e-3 相对误差，吞吐
   更高）——要严格 fp32 数值就别开编译。
3. **CUDA graph 不用于训练**：不选 `reduce-overhead`；optimizer step 会改写参数，
   CUDA graph 的静态地址假设在训练里不成立。
4. **minibatch 变了要重编译**：形状固定是收益来源，也是约束。换 `--minibatch`
   会在下一个 iteration 触发一次重编译（几十秒，只一次）。尾批不会。
5. **启动成本**：每个新进程启动多 20–90 s（main+aux+anchor 图），只付一次；`=2`
   max-autotune 可能几分钟。频繁 restart 的实验别开 `=2`。
6. **eval 不受影响**：异步/同步评测是独立进程（`c0_gate.py` / eval worker）加载
   checkpoint 跑；learner 里的编译图只在 `train_ppo`/anchor 使用。`PPOEvaluator`、
   `BatchLeafServer`、自对弈策略一行没改，`--leaf-compile` 仍是独立开关。
7. **checkpoint 兼容**：`TrainForward` 不替换 `model` 对象、不修改 `state_dict`
   的 key，`trainer.pt` / `model.pt` 与旧版本可互相加载（`PPOConfig` 新字段有默认值，
   旧 `trainer.pt` 里的 config 缺 `compile_train` 时按 0 处理）。
8. **单测**：`python -m pytest tests/test_compile_train.py -q`（5 项，CPU ~18 s）：
   - 配置规范化（0/1/2、`True→1`、非法值报错、0 → `None`）；
   - `compile_train=0` vs `=1` 同 seed 1 个 epoch：loss 各项 ≤1e-4、参数更新
     `allclose(atol=1e-4)`；并断言 2 个满 minibatch 走编译图、1 个尾批走 eager；
   - seq 辅助头（`forward_aux` + `seq_coef=0.02`）路径等价；
   - 尾批路由（`B==minibatch` 编译 / `B<minibatch` eager）；
   - monkeypatch 让 `torch.compile` 抛异常：只 warn 一次、`compile_active=False`、
     参数仍被更新（回退路径可用）。

## 8. 回退到 eager

- 运行期：去掉 `--compile-train`（或设 `PPOConfig(compile_train=0)`）即可，零开销。
- 代码里：`build_train_forward()` 返回 `None`，`ppo_losses` 自动走 eager 分支。
- 若只是某一张图有问题：`TrainForward` 会对 main / aux 分别回退，另一个仍可用；
  `stats["compile"]["warnings"]` 里有原因。
- anchor 精度想回旧行为：`--anchor-amp 0`。
