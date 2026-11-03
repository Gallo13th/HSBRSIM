# 合并检查清单（并行 agent 时代）

> 目的：多个子代理并行改同一批文件时，避免增量被整文件覆写。合并/提交前逐条核对。

## 1. 必保留的增量（compound-prior 线，2026-11-01）
文件：`hsbg/az/train/economy_sandbox.py`、`scripts/train_economy_sandbox.py`

- `batch_act(..., bias=)`（沙盒向量化动作采样接受 prior bias）
- `prior_bias_rows()`（按流派核心牌构造偏置行）
- `evaluate(..., prior=, core_ids=)`（评测时带先验与核心牌度量）
- CLI：`--compound-prior-coef`、`--archetype-background-penalty`、`--compound-archetype`、`--compound-core-metric`
- `EconomySandbox(core_ids=)`、`VectorEconomySandbox(core_ids=)`
- `summarize()` 的 `core_*` 键

## 2. 必保留的增量（small-expert 线）
- `action-cap` ramp、`t12_t15` reward 组合项（同一文件，属另一 agent）

## 3. 提交纪律
- 提交前 `git diff` 逐文件检查上述符号是否仍在；
- 优先用 `git add -p` 或按文件提交，避免 `git add -A` 把并行 agent 未完成的改动一起打包；
- 若发现某增量已被覆盖，从 `git log`/`git stash`/对应 agent 的补丁记录恢复。

## 4. 资源纪律（cuda:7 共享）
- 沙盒训练默认 `--minibatch 512 --grad-accum 16`（有效批 8192，单进程 ~1.5–2 GB）；
- 并行 ≤3 组；出现 OOM 先降 minibatch，不要杀别人的进程；
- cuda:3–6 属主训练，禁止占用。
