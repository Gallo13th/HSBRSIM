# B10：强制升本 + 终局「上限」辅助头（ceiling head）

## 1. 为什么是这条路（B08/B09 的直接结论）

| 轮次 | 机制 | 结果 |
|---|---|---|
| B08 | **强制升本**（买得起升级+最便宜商品 ⇒ 只允许升级） | `tier≥5@t15` **7.7% → 100%**，384 局 rank 1.505 vs 基线 1.477（无代价）；但 6 本盘面的**放大器卡位 0.00%**（人类 7.02%），继续训练还退化（250M 1.589） |
| B09 | **人类行为模仿（BC）**，全量 → 高本(tier≥5) | 放大器 **0.64%** vs 无 BC 基线 0.67%（无改善），human 面板稳定 −0.15~−0.25 ⇒ **模仿学不到"该买哪张核心"** |

⇒ 缺的不是"升本的意愿"，而是"**这一步会不会让终局更肥/更高本**"这个信号。BC 只教"人类看到什么买什么"，不含终局价值；PPO 的终局单标量又被 13+ 回合延迟淹没。

## 2. 机制：终局上限辅助头（`--ceiling-aux-coef`）

从每个中间状态预测该局**终点**（同一局所有决策共享目标）：

| 输出 | 目标 | 含义 |
|---|---|---|
| `ceiling_head[0]` | `log1p(终局盘面 Σatk+hp)` | 这局能滚多肥（复利的强度上限） |
| `ceiling_head[1]` | `终局 tier / 6` | 这局能爬多高（高本的收益预期） |

- 损失：`coef × [smooth_l1(pred0, log1p(S_final)) + smooth_l1(pred1, tier/6)]`
- 每个 minibatch 只在前 256 行算（一次小前向，成本可忽略）
- **零初始化**：初始 `pred=0`，trunk 梯度为 0（不扰动策略），head 先学均值，几步后才把信号传回 trunk
- **不改观测维度、不禁卡、不动奖励函数**（纯辅助监督，`ceiling_aux_coef=0` 时与原版逐位一致）
- 实现：`hsbg/az/train/entity_model.py`（`attach_ceiling_head` / `forward_ceiling`）、
  `parallel_collect.py`（局末挂 `final_strength` / `final_tier`）、`ppo.py`（batch 字段 + 损失）、
  `process_pool.py`（IPC 透传）、`scripts/train_entity_sync.py`（CLI + 建头 + 日志）
- 单测：`tests/test_ceiling_head.py`（零初始化不动策略 / 损失口径 / batch 字段 / 存档往返）

## 3. 配方（B10）

| 项 | 值 |
|---|---|
| 起点 | **B08@150M**（`runs/az_stage300m_b08/eval/ckpt_150028307.pt`，384 局 1.505 的最佳点） |
| 保留 | 强制升本 `=1`、5 席 p0.90 full 人盘、禁用「加重护手」、无长强加权、无 tier-target、λ=0.995、lr 3e-6 |
| 新增 | **`ceiling_aux_coef=0.02`**（唯一变量） |
| 关闭 | 人类 BC（`bc_coef=0`，B09 已证伪） |

## 4. 判据

| 指标 | B08@150M 基线 | B10 成功线 |
|---|---:|---:|
| 放大器卡位占比（`comp_metrics.py`） | 0.67% | **≥3%**（人类 7.02%） |
| 每唯一卡张数 | 1.06 | ≥1.20 |
| 6 本盘面 T5+ 卡位 | 25.2% | ≥40% |
| 384 局 bot rank | 1.505 | **≤1.50** |
| 96 局强度曲线 t15/t18 | 996 / 1308 | 提高（复利意味着后期更强） |

## 5. 风险与回退

- **ceiling 损失过大压过 PPO**：盯 `[ppo]` 的 `ceil` 与 `approx_kl`；若 KL 持续 >0.02 或 rank 掉 >0.15 → `ceiling_aux_coef` 0.02 → 0.01。
- **head 学成"均值预测"没有信息**：看 `ceil` 是否在 100M 前降到 ~0.3 以下；若一直是 5+，说明目标方差被 log1p 压缩过度 → 改 z-score 归一化。
- **退化成"堆数值"**：若强度上去了但 rank 不涨，说明需要 tier 项加权 → 提高第二个输出的权重。

## 6. 运行

```bash
bash scripts/run_stage300m_b10.sh                    # 正式（从 B08@150M 起）
MINUTES=5 STOP=200000000 OUT=runs/az_stage300m_b10_pilot TAG=az_stage300m_b10_pilot \
  bash scripts/run_stage300m_b10.sh                  # pilot
python scripts/comp_metrics.py runs/lineups/b10_50m_top2.json   # 复利指标
```
