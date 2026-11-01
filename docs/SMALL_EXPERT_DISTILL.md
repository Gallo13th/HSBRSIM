# 小模型专家 → 大模型蒸馏（DAgger + 软标签 KL）

> 状态：实现 + 端到端小跑 + 200 局标签 + 256 局面板（结果见 §4）。
> 代码 `hsbg/az/train/small_expert_distill.py`、测试
> `tests/test_small_expert_distill.py`；教师 = 三阶段课程训出的小专家
> （`runs/small_expert/main/model.pt`，3.57M），学生 = s17 冻结快照
> （`runs/stoch_search/ckpt_s17_step1001.pt`，14.8M）。

## 0. 结论摘要

（待面板跑完后填写。）

## 1. 协议

| 项 | 口径 |
|---|---|
| 状态分布 | **大模型 π_base 行为**在完整游戏里采样（DAgger：状态来自要部署的模型，不来自小专家） |
| 对手 | 人类战团 2 档：**1 席 p=0.30**（100 局）+ **3 席 p=0.70**（100 局），共 200 局；`sample=p75`、`fidelity=full`、`set_tier=1`（与 s17 训练 band 同口径） |
| 标签 | 小专家在**同一** `(features, cards, legal_mask)` 上的 masked softmax；候选 = 大小模型 top-8 并集（非 Move），教师分布重新归一 |
| 关键决策 | `--only-when carrier_or_spell`（与 `search_exit` 的正向机制一致：搜索/专家真正改变的是载体与施法决策） |
| 损失 | `search_exit.ExitTrainer`：软标签 KL（温度 T=2）+ 优势加权关闭（`weight_mode=none`，纯 KD）+ `KL(π_ref‖π_θ) ≤ 0.10` 硬锚 + 每轮 `KL(π_old‖π_θ) ≤ 0.05` 预算 + 熵地板 0.85 |
| 可训练参数 | `train_scope=policy`（只训策略头，trunk/value 冻结；与 `runs/search_exit` 同一安全口径） |
| 优化 | Adam lr 1e-5，batch 256，最多 60 epoch（KL 预算/收敛提前停） |
| 验收 | 大模型**关闭搜索** human 面板 **256 局**（8 seat × 32，seed 420000）；配对 Δ 与 20000 次 bootstrap CI；判据 **Δ ≤ −0.10 且 CI 上界 < 0** |

## 2. 为什么是「小专家当教师」而不是「继续扩大搜索」

`docs/SEARCH_DISTILL_THEORY.md` / `docs/SEARCH_EXIT.md` 的归因是：瓶颈不是损失函数，
而是（a）KL 预算粒度、（b）标签规模与覆盖率。小专家的价值在于**单位标签的成本**：

- 搜索标签：每个决策 ~300 ms（K=1，本机负载下）、覆盖 ~19 次/局；
- 小专家标签：一次 batch 前向（3.57M，~1 ms/1024 状态），200 局可标 ~3 万个状态。

如果小专家在「让场面达到真实强度」上确实学到了搜索/人类强度的一部分，那么它能把
搜索的收益**摊销**成离线可复制的标签；否则它只是一个弱的额外先验（本实验的零假设）。

## 3. 单测（`tests/test_small_expert_distill.py`）

1. `_topk_union`：并集、剔除 Move、按大模型先验降序；
2. `make_samples`：教师分布来自小模型、先验来自大模型、`switch`/归一化契约；
3. 退化 mask（<2 合法动作）被丢弃；
4. `paired_stats` 的符号与 CI 自洽。

## 4. 结果

（待填。）

## 5. 结论

（待填。）
